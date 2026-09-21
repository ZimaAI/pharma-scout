"""Contract operations. Transactions keep authorization, versions and effects atomic."""

import base64
import json
from datetime import datetime, timedelta
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, func, or_, select, tuple_

from . import reports
from .auth import Principal
from .db import digest, now
from .domain import differences, event_category, event_title, verify_evidence
from .errors import PharmaError, require


def mode(repo):
    return repo.get("workspace", repo.workspace_id)["settings"].get("data_mode", "live")


def source_health(repo):
    workspace = repo.get("workspace", repo.workspace_id)
    result = []
    for source in ("ctgov", "pubmed"):
        states = repo.rows("source_sync_state", source=source)
        state = states[0] if states else {}
        enabled = workspace["settings"].get("sources", {}).get(source, True)
        result.append(
            {
                "source": source,
                "enabled": enabled,
                "configured": True,
                "state": "degraded" if state.get("last_error_code") else "healthy" if state.get("last_success_at") else "unknown",
                "last_success_at": state.get("last_success_at"),
                "last_error_code": state.get("last_error_code"),
            }
        )
    return result


def page(repo, name, query, *, extra=None, transform=None, **filters):
    table = repo.table(name)
    statement = repo.query(name, **filters)
    if extra is not None:
        statement = statement.where(extra)
    try:
        limit = int(query.get("limit", 20))
        require(1 <= limit <= 100, "VALIDATION_ERROR", "每页数量需在 1–100 之间", 422)
    except ValueError:
        raise PharmaError("VALIDATION_ERROR", "分页参数无效", 422) from None
    fingerprint = digest({"workspace": repo.workspace_id, "table": name, "query": {k: v for k, v in query.items() if k not in ("cursor", "limit")}, "filters": filters})
    if cursor := query.get("cursor"):
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor))
            require(decoded["scope"] == fingerprint, "VALIDATION_ERROR", "分页游标与筛选范围不匹配", 422)
            UUID(decoded["id"])
            cursor_time = datetime.fromisoformat(decoded["created_at"].replace("Z", "+00:00"))
            require(cursor_time.tzinfo is not None, "VALIDATION_ERROR", "分页时间缺少时区", 422)
            statement = statement.where(tuple_(table.c.created_at, table.c.id) < tuple_(cursor_time, UUID(decoded["id"])))
        except (KeyError, ValueError, TypeError):
            raise PharmaError("VALIDATION_ERROR", "分页游标无效", 422) from None
    records = repo.connection.execute(statement.order_by(table.c.created_at.desc(), table.c.id.desc()).limit(limit + 1)).mappings().all()
    rows = jsonable_encoder([dict(row) for row in records[:limit]])
    more = len(records) > limit
    cursor = base64.urlsafe_b64encode(json.dumps({"scope": fingerprint, "created_at": rows[-1]["created_at"], "id": rows[-1]["id"]}).encode()).decode() if more else None
    return {"items": [transform(row) for row in rows] if transform else rows, "has_more": more, "next_cursor": cursor}


def list_page(rows):
    return {"items": rows, "next_cursor": None, "has_more": False}


def delivery_view(repo, delivery):
    version = repo.get("report_version", delivery["report_version_id"])
    return {**delivery, "report_id": version["report_id"]}


def event_view(repo, event):
    record = repo.get("source_record", event["record_id"])
    legacy_title = f"{record['external_id']} · {event['category']} 字段变化"
    title = event_title(record["external_id"], event["category"]) if event["title"] == legacy_title else event["title"]
    return {**event, "category": event_category(event["category"]), "title": title}


def etag(request, row):
    require(request.headers.get("if-match", "").strip('"') == str(row["revision"]), "STALE_VERSION", "内容已更新，请刷新后再保存", 409)


def owned_run(repo, principal, run_id):
    run = repo.get("research_run", run_id)
    principal.owns(run)
    return run


def operation(repo, principal, name, path, query, body, request):
    user = principal.user_id
    if name in ("workspace_configuration", "demo_advance"):
        workspace = repo.get("workspace", repo.workspace_id)
        if name == "demo_advance":
            principal.require_role("analyst")
            from .seed import seed

            seed(repo, user, body["day"])
            workspace = repo.get("workspace", repo.workspace_id)
        from deerflow.config import get_app_config

        from .subscriptions import email_available

        return {"data_mode": mode(repo), "model_configured": bool(get_app_config().models), "email_enabled": email_available(), "demo_day": workspace["settings"].get("demo_day")}
    if name == "dashboard_get":

        def count(table, *criteria):
            return repo.connection.scalar(select(func.count()).select_from(repo.table(table)).where(repo.table(table).c.workspace_id == repo.workspace_id, *criteria))

        return {
            "watched_drugs": len({drug for sub in repo.rows("subscription", owner_id=user, enabled=True) for drug in sub["drug_ids"]}),
            "events_last_7_days": count("event_revision", repo.table("event_revision").c.observed_at >= now() - timedelta(days=7)),
            "pending_reviews": count("report", repo.table("report").c.state == "in_review"),
            "source_health": source_health(repo),
            "as_of": now(),
            "is_demo": mode(repo) == "demo",
        }
    if name == "members_list":
        principal.require_role("admin")
        return list_page([{"user": {k: repo.get("app_user", m["user_id"])[k] for k in ("id", "email", "display_name", "is_active")}, "role": m["role"], "enabled": m["enabled"]} for m in repo.rows("membership")])
    if name == "members_update_role":
        principal.require_role("admin")
        repo.advisory(f"members:{repo.workspace_id}")
        members = repo.rows("membership", user_id=path["user_id"])
        require(members)
        member = members[0]
        if member["role"] == "admin" and (body.get("role", "admin") != "admin" or body.get("enabled") is False):
            require(len(repo.rows("membership", role="admin", enabled=True)) > 1, "LAST_ADMIN", "不能停用或降级最后一位管理员", 409)
        table = repo.table("membership")
        repo.connection.execute(table.update().where(table.c.workspace_id == repo.workspace_id, table.c.user_id == path["user_id"]).values(**body))
        repo.audit(user, "member.update", "membership", path["user_id"], **body)
        member.update(body)
        return {"user": {k: repo.get("app_user", path["user_id"])[k] for k in ("id", "email", "display_name", "is_active")}, "role": member["role"], "enabled": member["enabled"]}
    if name == "drugs_list":
        table = repo.table("drug")
        extra = table.c.archived.is_(query.get("archived") == "true")
        if query.get("query"):
            text = "%" + query["query"].replace("%", "\\%").replace("_", "\\_") + "%"
            aliases = repo.table("drug_alias")
            matches = select(aliases.c.drug_id).where(aliases.c.workspace_id == repo.workspace_id, aliases.c.status == "approved", aliases.c.alias.ilike(text))
            extra = and_(extra, or_(table.c.display_name.ilike(text), table.c.development_code.ilike(text), table.c.id.in_(matches)))
        return page(repo, "drug", query, extra=extra)
    if name == "drugs_create":
        principal.require_role("analyst")
        return repo.add("drug", **body)
    if name in ("drugs_get", "drugs_update", "drugs_archive"):
        drug = repo.get("drug", path["drug_id"], lock=name != "drugs_get")
        if name == "drugs_get":
            return drug
        principal.require_role("analyst")
        etag(request, drug)
        changes = {"archived": True} if name == "drugs_archive" else body
        repo.audit(user, name, "drug", drug["id"])
        return repo.update("drug", drug["id"], **changes, revision=drug["revision"] + 1, updated_at=now())
    if name in ("aliases_list", "aliases_pending"):
        filters = {"drug_id": path["drug_id"]} if "drug_id" in path else {}
        if "drug_id" in path:
            repo.get("drug", path["drug_id"])
        if query.get("status"):
            filters["status"] = query["status"]
        return page(repo, "drug_alias", query, **filters)
    if name == "aliases_propose":
        principal.require_role("analyst")
        repo.get("drug", path["drug_id"])
        if body.get("evidence_id"):
            verify_evidence(repo, body["evidence_id"])
        return repo.add("drug_alias", drug_id=path["drug_id"], **body, normalized_alias=body["alias"].casefold().strip(), proposed_by=user)
    if name == "links_list":
        filters = {k: query[k] for k in ("drug_id", "record_id", "status") if query.get(k)}
        return page(repo, "entity_link", query, **filters)
    if name == "links_propose":
        principal.require_role("analyst")
        repo.get("drug", body["drug_id"])
        repo.get("source_record", body["record_id"])
        if body.get("evidence_id"):
            verify_evidence(repo, body["evidence_id"])
        return repo.add("entity_link", **body, proposed_by=user)
    if name in ("aliases_decide", "links_decide"):
        principal.require_role("reviewer")
        table, key = ("drug_alias", "alias_id") if name == "aliases_decide" else ("entity_link", "link_id")
        repo.get(table, path[key], lock=True)
        statuses = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}
        repo.audit(user, name, table, path[key], **body)
        return repo.update(table, path[key], status=statuses[body["decision"]], reviewed_by=user, reviewed_at=now())
    if name == "sources_list":
        return {"items": source_health(repo)}
    if name == "sources_update":
        principal.require_role("admin")
        require(path["source"] in ("ctgov", "pubmed"), "VALIDATION_ERROR", "未知来源", 422)
        workspace = repo.get("workspace", repo.workspace_id, lock=True)
        settings = workspace["settings"]
        settings.setdefault("sources", {})[path["source"]] = body["enabled"]
        repo.update("workspace", workspace["id"], settings=settings)
        repo.audit(user, name, "workspace", workspace["id"], source=path["source"], **body)
        return next(s for s in source_health(repo) if s["source"] == path["source"])
    if name == "sources_sync":
        principal.require_role("analyst")
        for drug in body["drug_ids"]:
            require(not repo.get("drug", drug)["archived"], "VALIDATION_ERROR", "归档对象不能同步", 422)
        return repo.add("job", kind="ingest", payload={**body, "actor_id": user}, progress={"processed": 0, "total": None})
    if name == "jobs_list":
        principal.require_role("analyst")
        jobs = repo.table("job")
        return page(
            repo,
            "job",
            query,
            extra=None if principal.role in ("reviewer", "admin") else jobs.c.payload["actor_id"].astext == user,
            transform=lambda row: {**row, "progress": {"processed": row["progress"].get("processed", 0), "total": row["progress"].get("total")}},
        )
    if name == "jobs_get":
        job = repo.get("job", path["job_id"])
        require(job["payload"].get("actor_id") == user or principal.role in ("reviewer", "admin"))
        job["progress"] = {"processed": job["progress"].get("processed", 0), "total": job["progress"].get("total")}
        return job
    if name in ("trials_list", "publications_list"):
        table = repo.table("source_record")
        extra = table.c.kind == ("trial" if name == "trials_list" else "publication")
        if query.get("query"):
            term = "%" + query["query"].replace("%", "\\%").replace("_", "\\_") + "%"
            extra = and_(extra, or_(table.c.external_id.ilike(term), table.c.current_projection["title"].astext.ilike(term)))
        if query.get("status"):
            extra = and_(extra, table.c.current_projection["status"].astext == query["status"])
        if query.get("has_results") in ("true", "false"):
            extra = and_(extra, table.c.current_projection["has_results"].astext == query["has_results"])
        if query.get("observed_since"):
            observations = repo.table("source_observation")
            extra = and_(
                extra,
                table.c.current_observation_id.in_(select(observations.c.id).where(observations.c.workspace_id == repo.workspace_id, observations.c.fetched_at >= datetime.fromisoformat(query["observed_since"].replace("Z", "+00:00")))),
            )
        if query.get("drug_id"):
            links = repo.table("entity_link")
            extra = and_(extra, table.c.id.in_(select(links.c.record_id).where(links.c.workspace_id == repo.workspace_id, links.c.drug_id == query["drug_id"], links.c.status == "approved")))
        return page(repo, "source_record", query, extra=extra)
    if name in ("trials_get", "publications_get"):
        key, kind = ("trial_id", "trial") if name == "trials_get" else ("publication_id", "publication")
        record = repo.get("source_record", path[key])
        require(record["kind"] == kind)
        return record
    if name in ("records_snapshots", "records_observations", "records_diff"):
        record = repo.get("source_record", path["record_id"])
        if name != "records_diff":
            return page(repo, "source_snapshot" if name == "records_snapshots" else "source_observation", query, record_id=record["id"])
        before = repo.get("source_observation", query["before_observation_id"])
        after = repo.get("source_observation", query["after_observation_id"])
        require(before["record_id"] == after["record_id"] == record["id"])
        require(before["snapshot_id"] and after["snapshot_id"], "VALIDATION_ERROR", "失败的观察没有可比较的快照", 422)
        changes = differences(repo.get("source_snapshot", before["snapshot_id"])["normalized"], repo.get("source_snapshot", after["snapshot_id"])["normalized"])
        evidence = [e["id"] for snapshot in (before["snapshot_id"], after["snapshot_id"]) for e in repo.rows("evidence", snapshot_id=snapshot)]
        return {"record_id": record["id"], "before_observation_id": before["id"], "after_observation_id": after["id"], "changes": changes, "evidence_ids": evidence}
    if name == "snapshots_get":
        return repo.get("source_snapshot", path["snapshot_id"])
    if name == "evidence_get":
        return verify_evidence(repo, path["evidence_id"])
    if name == "events_list":
        extra = None
        if query.get("drug_id"):
            link = repo.table("entity_link")
            extra = repo.table("intelligence_event").c.record_id.in_(select(link.c.record_id).where(link.c.workspace_id == repo.workspace_id, link.c.drug_id == query["drug_id"], link.c.status == "approved"))
        if query.get("observed_since"):
            revisions = repo.table("event_revision")
            observed = repo.table("intelligence_event").c.id.in_(
                select(revisions.c.event_id).where(revisions.c.workspace_id == repo.workspace_id, revisions.c.observed_at >= datetime.fromisoformat(query["observed_since"].replace("Z", "+00:00")))
            )
            extra = and_(extra, observed) if extra is not None else observed
        return page(repo, "intelligence_event", query, extra=extra, transform=lambda row: event_view(repo, row))
    if name == "events_get":
        return event_view(repo, repo.get("intelligence_event", path["event_id"]))
    if name == "events_revisions":
        repo.get("intelligence_event", path["event_id"])
        return page(repo, "event_revision", query, event_id=path["event_id"])
    if name.startswith("runs_"):
        from .research import append_event, create_run, serialize_run

        if name == "runs_create":
            principal.require_role("analyst")
            return serialize_run(repo, create_run(repo, principal, body))
        if name == "runs_list":
            table = repo.table("research_run")
            return page(
                repo,
                "research_run",
                query,
                extra=None if principal.role in ("reviewer", "admin") else table.c.created_by == user,
                transform=lambda row: serialize_run(repo, row),
                **({"status": query["status"]} if query.get("status") else {}),
            )
        run = owned_run(repo, principal, path["run_id"])
        if name == "runs_get":
            return serialize_run(repo, run)
        if name == "runs_tool_calls":
            return page(repo, "tool_call", query, run_id=run["id"])
        principal.require_role("analyst")
        if name == "runs_cancel":
            job = repo.get("job", run["job_id"], lock=True)
            run = repo.get("research_run", run["id"], lock=True)
            require(run["job_id"] == job["id"], "STALE_VERSION", "任务执行尝试已更新", 409)
            if run["status"] in ("queued", "running", "awaiting_input", "verifying"):
                repo.update("research_run", run["id"], status="cancelling", updated_at=now())
                append_event(repo, run["id"], "run.cancel_requested", {})
                if job["state"] in ("queued", "retry_wait") or run["status"] == "awaiting_input":
                    repo.update("job", job["id"], state="cancelled")
                    repo.update("research_run", run["id"], status="cancelled", stop_reason="user_cancelled", updated_at=now())
                    append_event(repo, run["id"], "run.cancelled", {})
                repo.audit(user, "run.cancel", "research_run", run["id"])
            return serialize_run(repo, repo.get("research_run", run["id"]))
        if name == "runs_retry":
            require(run["status"] in ("failed", "partial", "cancelled", "recovery_required"), "STALE_VERSION", "当前任务不可重试", 409)
            original = {k: v for k, v in run["frozen_request"].items() if k in ("question", "drug_ids", "time_range", "source_allowlist", "budget")}
            original["parent_run_id"] = run["id"]
            result = create_run(repo, principal, original)
            repo.audit(user, "run.retry", "research_run", run["id"], new_run_id=result["id"], reason=body["reason"])
            return serialize_run(repo, result)
        if name == "runs_clarify":
            require(run["status"] == "awaiting_input", "STALE_VERSION", "任务当前未等待澄清", 409)
            state = dict(run["research_state"])
            require(body["question_id"] == state.get("clarification", {}).get("question_id"), "STALE_VERSION", "澄清问题已过期", 409)
            state["clarification_answer"] = body["answer"]
            job = repo.add("job", kind="research", payload={"run_id": run["id"], "actor_id": user}, progress={"processed": 0, "total": None})
            repo.update("research_run", run["id"], status="queued", job_id=job["id"], research_state=state)
            append_event(repo, run["id"], "run.queued", {"reason": "clarification_received"})
            return serialize_run(repo, repo.get("research_run", run["id"]))
    if name.startswith("reports_") or name.startswith("reviews_"):
        if name == "reports_list":
            table = repo.table("report")
            editor = True if principal.role in ("reviewer", "admin") else table.c.created_by == user if principal.role == "analyst" else False
            published = table.c.published_version_id.is_not(None)
            extra = or_(editor, published)
            if query.get("state"):
                visible_state = table.c.state == "retracted" if query["state"] == "retracted" else table.c.state != "retracted" if query["state"] == "published" else False
                extra = or_(and_(editor, table.c.state == query["state"]), and_(~editor if not isinstance(editor, bool) else not editor, published, visible_state))
            return page(repo, "report", query, extra=extra, transform=lambda row: reports.visible_report(repo, principal, row))
        report, editor = reports.report_access(repo, principal, path["report_id"])
        if name == "reports_get":
            return reports.visible_report(repo, principal, report)
        if name == "reports_versions":
            return page(
                repo,
                "report_version",
                query,
                report_id=report["id"],
                extra=None if editor else repo.table("report_version").c.id.in_(reports.published_version_ids(repo, report)),
                transform=lambda row: reports.visible_version(repo, principal, report["id"], row["id"]),
            )
        if name == "reports_version_get":
            return reports.visible_version(repo, principal, report["id"], path["version_id"])
        if name == "reports_version_claims":
            version = reports.visible_version(repo, principal, report["id"], path["version_id"])

            def claim(row):
                row["evidence_links"] = [{"evidence_id": link["evidence_id"], "relation": link["relation"]} for link in repo.rows("claim_evidence", claim_id=row["id"])]
                return row

            return page(repo, "claim", query, report_version_id=version["id"], transform=claim)
        if name == "reports_notices":
            return page(repo, "report_notice", query, report_id=report["id"], extra=None if editor else repo.table("report_notice").c.version_id.in_(reports.published_version_ids(repo, report)))
        if name == "reports_export":
            version_id = query.get("version_id") or (report["current_version_id"] if editor else report["published_version_id"])
            return reports.visible_version(repo, principal, report["id"], version_id)
        if name == "reviews_list":
            require(editor)
            return page(repo, "review", query, report_id=report["id"])
        if name == "reports_new_version":
            principal.require_role("analyst")
            require(editor)
            report = repo.get("report", report["id"], lock=True)
            require(body["base_version_id"] == report["current_version_id"], "STALE_VERSION", "当前版本已变化", 409)
            _, version = reports.create_version(repo, principal, repo.get("research_run", report["run_id"]), body["content"], report, body["edit_note"])
            return reports.visible_version(repo, principal, report["id"], version["id"])
        actions = {"reports_submit_review": reports.submit_review, "reviews_decide": reports.review, "reports_publish": reports.publish, "reports_retract": reports.retract}
        return actions[name](repo, principal, report["id"], body)
    if name.startswith("subscriptions_"):
        from .subscriptions import create_subscription, preview_schedule, trigger_subscription, update_subscription

        principal.require_role("analyst")
        if name == "subscriptions_preview":
            return preview_schedule(body)
        if name == "subscriptions_create":
            return create_subscription(repo, user, body)
        if name == "subscriptions_list":
            return page(repo, "subscription", query, owner_id=user)
        subscription = repo.get("subscription", path["subscription_id"])
        require(subscription["owner_id"] == user or principal.role == "admin")
        if name == "subscriptions_get":
            return subscription
        if name == "subscriptions_update":
            etag(request, subscription)
            return update_subscription(repo, subscription["id"], subscription["owner_id"], body, subscription["revision"])
        if name == "subscriptions_trigger":
            from .research import create_run

            return trigger_subscription(repo, subscription["id"], subscription["owner_id"], create_run=lambda r, owner, frozen: create_run(r, Principal(repo.get("app_user", owner), {}, repo.workspace_id, "analyst"), frozen))
    if name in ("inbox_list", "deliveries_list"):
        filters = {"recipient_user_id": user}
        if name == "inbox_list":
            filters.update(channel="in_app", state="accepted")
        if name == "deliveries_list" and principal.role == "admin":
            filters = {}
        return page(repo, "delivery", query, transform=lambda row: delivery_view(repo, row), **filters)
    if name in ("inbox_mark_read", "deliveries_get"):
        delivery = repo.get("delivery", path["delivery_id"])
        require(delivery["recipient_user_id"] == user or (name == "deliveries_get" and principal.role == "admin"))
        if name == "inbox_mark_read":
            delivery = repo.update("delivery", delivery["id"], read_at=now())
        return delivery_view(repo, delivery)
    if name == "audit_list":
        principal.require_role("admin")
        return page(repo, "audit_log", query)
    raise PharmaError("NOT_FOUND", "接口不存在", 404)
