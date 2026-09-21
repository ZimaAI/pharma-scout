"""Durable research orchestration around the bounded existing DeerFlow runtime."""

from __future__ import annotations

import asyncio
import copy
import os
import time
from datetime import datetime

from .auth import Principal
from .contract import validate
from .db import canonical, now, transaction, uid
from .domain import check_question, differences, ingest, verify_evidence
from .errors import PharmaError, require
from .runtime import DeerFlowRuntimeAdapter, ReplayRuntimeAdapter, RuntimeBudget, RuntimeContext, RuntimeResult

UPSTREAM_REF = "29d285731b326a728a9df33d3641f73b68bbe48b"
ACTIVE = {"queued", "running", "verifying", "cancelling"}


def _time(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))


def public_usage(usage):
    return {
        "tool_calls": usage.get("tool_calls", 0),
        "model_calls": usage.get("model_calls", 0),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "usage_quality": "estimated" if usage.get("estimated") else "reported" if "input_tokens" in usage else "unknown",
        "estimated_cost": None,
        "currency": None,
    }


def append_event(repo, run_id, event_type, payload):
    run = repo.get("research_run", run_id, lock=True)
    seq = run["next_event_seq"] + 1
    timestamp = now()
    event = repo.add("run_event", run_id=run_id, seq=seq, schema_version="1.0", type=event_type, payload=payload, occurred_at=timestamp)
    repo.update("research_run", run_id, next_event_seq=seq, updated_at=timestamp)
    return event


def serialize_run(repo, run):
    result = {key: run[key] for key in ("id", "workspace_id", "created_at", "created_by", "question", "status", "runtime_mode", "attempt", "frozen_request", "coverage", "stop_reason", "updated_at")}
    result["usage"] = public_usage(run.get("usage", {}))
    result["event_seq"] = run["next_event_seq"]
    reports = repo.rows("report", run_id=run["id"])
    result["report_id"] = reports[0]["id"] if reports else None
    if run["status"] == "awaiting_input" and run.get("research_state", {}).get("clarification"):
        result["clarification"] = run["research_state"]["clarification"]
    return result


def create_run(repo, principal, body):
    principal.require_role("analyst")
    require(principal.workspace_id == repo.workspace_id)
    validate("ResearchInput", body)
    check_question(body["question"])
    require(len(set(body["drug_ids"])) == len(body["drug_ids"]) and len(set(body["source_allowlist"])) == len(body["source_allowlist"]), "VALIDATION_ERROR", "研究对象和来源不能重复", 422)
    aliases, revisions = {}, {}
    for identifier in body["drug_ids"]:
        drug = repo.get("drug", identifier)
        require(not drug["archived"], "VALIDATION_ERROR", "归档药物不能发起新研究", 422)
        aliases[identifier] = [a["alias"] for a in repo.rows("drug_alias", drug_id=identifier, status="approved")]
        revisions[identifier] = drug["revision"]
    parent = None
    if body.get("parent_run_id"):
        parent = repo.get("research_run", body["parent_run_id"])
        principal.owns(parent)
    workspace = repo.get("workspace", repo.workspace_id)
    stamp = now().isoformat()
    scope = {"drug_ids": list(body["drug_ids"]), "time_range": copy.deepcopy(body["time_range"]), "knowledge_cutoff": min(_time(stamp), _time(body["time_range"]["end_exclusive"])).isoformat()}
    coverage = [{"source": source, "status": "not_requested", "records_count": 0, "truncated": False, "as_of": None, "limitations": ["尚未执行本次来源核查。"]} for source in body["source_allowlist"]]
    run = repo.add(
        "research_run",
        created_by=principal.user_id,
        question=body["question"],
        frozen_request=copy.deepcopy(body),
        runtime_mode="replay" if workspace["settings"].get("data_mode") == "demo" else "deerflow",
        research_state={"scope": scope, "approved_aliases": aliases, "drug_revisions": revisions, "issued_evidence_ids": [], "background": False},
        budget=body.get("budget", {}),
        usage={},
        coverage=coverage,
        upstream_ref=UPSTREAM_REF,
        model_ref=os.environ.get("PHARMA_MODEL_NAME"),
        prompt_version="research-system-v1.0",
        attempt=parent["attempt"] + 1 if parent else 0,
        parent_run_id=parent["id"] if parent else None,
        created_at=stamp,
        updated_at=stamp,
    )
    job = repo.add("job", kind="research", state="queued", payload={"run_id": run["id"], "actor_id": principal.user_id})
    repo.update("research_run", run["id"], job_id=job["id"])
    append_event(repo, run["id"], "run.queued", {"runtime_mode": run["runtime_mode"]})
    repo.audit(principal.user_id, "research.create", "research_run", run["id"])
    return repo.get("research_run", run["id"])


def lease_fence(repo, job_id, owner_token):
    job = repo.get("job", job_id, lock=True)
    require(job["state"] == "running" and str(job.get("owner_token")) == str(owner_token) and job.get("lease_expires_at") and _time(job["lease_expires_at"]) > now(), "LEASE_LOST", "任务租约已失效，旧执行器不能继续写入", 409)
    return job


def _principal(repo, run):
    user = repo.get("app_user", run["created_by"])
    memberships = repo.rows("membership", user_id=user["id"], enabled=True)
    require(user["is_active"] and memberships, "FORBIDDEN", "发起人账户或工作区权限已失效", 403)
    principal = Principal({k: user[k] for k in ("id", "is_active")}, {}, repo.workspace_id, memberships[0]["role"])
    principal.require_role("analyst")
    return principal


def snapshots_in_scope(repo, run, drug_ids=None, source=None):
    requested = set(drug_ids or run["frozen_request"]["drug_ids"])
    require(requested <= set(run["frozen_request"]["drug_ids"]))
    cutoff = _time(run["research_state"]["scope"]["knowledge_cutoff"])
    records = {item["id"]: item for item in repo.rows("source_record", limit=10000) if item["source"] in run["frozen_request"]["source_allowlist"] and (source is None or item["source"] == source)}
    approved = {link["record_id"] for link in repo.rows("entity_link", status="approved", limit=10000) if link["drug_id"] in requested}
    return [
        snapshot
        for snapshot in repo.rows("source_snapshot", limit=10000)
        if snapshot["record_id"] in approved & records.keys() and _time(snapshot["first_observed_at"]) <= cutoff and _time(snapshot["first_observed_at"]) < _time(run["frozen_request"]["time_range"]["end_exclusive"])
    ]


def _eligible_observations(repo, record_id, scope):
    observations = [
        item
        for item in repo.rows("source_observation", record_id=record_id, limit=10000)
        if item.get("snapshot_id") and item["outcome"] != "failed" and _time(item["fetched_at"]) <= _time(scope["knowledge_cutoff"]) and _time(item["fetched_at"]) < _time(scope["time_range"]["end_exclusive"])
    ]
    return sorted(observations, key=lambda item: item["observation_seq"])


def _envelope(data=None, *, evidence=(), coverage=(), error=None):
    return {"ok": error is None, "data": data if error is None else None, "error": error, "coverage": list(coverage), "provenance": {"evidence_ids": list(evidence)}}


def _coverage(source, count, cutoff, *, mode, failed=False, late=False):
    return {
        "source": source,
        "status": "failed" if failed else "complete" if mode == "replay" else "partial",
        "records_count": count,
        "truncated": False,
        "as_of": cutoff,
        "limitations": ["仅覆盖已载入的虚构演示资料。" if mode == "replay" else "仅覆盖研究截止时间前已同步且关联已批准的资料；未检索到不代表不存在。"] + (["本次新抓取资料晚于固定截止时间；请确认实体关联后新建研究任务。"] if late else []),
    }


class DomainTools:
    """All nine tools share server-owned run, membership and lease checks."""

    def __init__(self, job, owner_token):
        self.job = job
        self.owner_token = owner_token

    def _open(self, repo, *, allow_cancelling=False):
        lease_fence(repo, self.job["id"], self.owner_token)
        run = repo.get("research_run", self.job["payload"]["run_id"], lock=True)
        require(run["job_id"] == self.job["id"], "LEASE_LOST", "任务租约已被新的执行尝试替换", 409)
        require(run["status"] in {"running", "verifying"} or (allow_cancelling and run["status"] == "cancelling"), "RUN_STOPPED", "研究任务已停止", 409)
        return run, _principal(repo, run)

    def _transaction(self, fn):
        with transaction(self.job["workspace_id"]) as repo:
            run, principal = self._open(repo)
            return fn(repo, run, principal)

    def _record_tool(self, name, args):
        def begin(repo, run, principal):
            # Summaries expose reference IDs and counts, never user/source bodies.
            summary = {key: value for key, value in args.items() if key in {"drug_id", "drug_ids", "snapshot_id", "evidence_ids", "trial_id", "before_id", "after_id", "limit"}}
            return repo.add("tool_call", run_id=run["id"], call_key=uid(), tool=name, state="started", arguments_summary=summary)

        return self._transaction(begin)

    async def __call__(self, name, args, context):
        require(context.workspace_id == self.job["workspace_id"] and context.run_id == self.job["payload"]["run_id"])
        started = time.monotonic()
        call = await asyncio.to_thread(self._record_tool, name, args)
        try:
            result = await asyncio.to_thread(self._transaction, lambda repo, run, principal: self.dispatch(repo, run, principal, name, args))
            # Searches use the frozen approved alias set. New official hits are
            # persisted as mapping candidates, never silently approved or backdated.
            if name in {"search_trials", "search_publications"} and result.get("_live_query"):
                result = await self._external_search(result.pop("_live_query"), name, args)
        except PharmaError as exc:
            if exc.code in {"LEASE_LOST", "RUN_STOPPED", "FORBIDDEN"}:
                raise
            result = _envelope(error={"code": exc.code, "message": exc.message, "retryable": False})
        except asyncio.CancelledError:
            raise
        except Exception:
            result = _envelope(error={"code": "TOOL_FAILED", "message": "领域工具暂不可用", "retryable": False})

        def finish(repo, run, principal):
            issued = set(run["research_state"].get("issued_evidence_ids", [])) | set(result["provenance"]["evidence_ids"])
            state = {**run["research_state"], "issued_evidence_ids": sorted(issued)}
            if name == "request_clarification" and result["ok"]:
                state["clarification"] = {"question_id": call["id"], **args}
            coverage = {item["source"]: item for item in run["coverage"]}
            coverage.update({item["source"]: item for item in result["coverage"]})
            repo.update("research_run", run["id"], research_state=state, coverage=list(coverage.values()), updated_at=now())
            repo.update(
                "tool_call",
                call["id"],
                state="completed" if result["ok"] else "failed",
                evidence_ids=result["provenance"]["evidence_ids"],
                error_code=result["error"]["code"] if result["error"] else None,
                duration_ms=int((time.monotonic() - started) * 1000),
                completed_at=now(),
            )

        await asyncio.to_thread(self._transaction, finish)
        return result

    def dispatch(self, repo, run, principal, name, args):
        scope = run["research_state"]["scope"]
        snapshots = snapshots_in_scope(repo, run)
        allowed_snapshots = {item["id"]: item for item in snapshots}
        if name == "resolve_drug":
            needle = args["text"].strip().casefold()
            aliases = run["research_state"]["approved_aliases"]
            candidates = []
            for drug_id in scope["drug_ids"]:
                drug = repo.get("drug", drug_id)
                if needle in {drug["display_name"].casefold(), *(alias.casefold() for alias in aliases[drug_id])}:
                    candidates.append({"id": drug_id, "display_name": drug["display_name"], "approved_aliases": aliases[drug_id]})
            return _envelope({"candidates": candidates[: args.get("limit", 10)], "ambiguous": len(candidates) != 1})
        if name in {"search_trials", "search_publications"}:
            source = "ctgov" if name == "search_trials" else "pubmed"
            enabled = repo.get("workspace", repo.workspace_id)["settings"].get("sources", {}).get(source, True)
            if not enabled:
                coverage = _coverage(source, 0, scope["knowledge_cutoff"], mode=run["runtime_mode"], failed=True)
                return _envelope(coverage=[coverage], error={"code": "SOURCE_DISABLED", "message": "该来源已由工作区管理员停用。", "retryable": False})
            matches = snapshots_in_scope(repo, run, [args["drug_id"]], source)
            snapshot_by_id = {item["id"]: item for item in matches}
            latest = {}
            for record_id in dict.fromkeys(item["record_id"] for item in matches):
                observations = _eligible_observations(repo, record_id, scope)
                eligible = [item for item in observations if item["snapshot_id"] in snapshot_by_id]
                if eligible:
                    # A later observation may point back to an older content
                    # hash. Observation order, not snapshot creation, is truth.
                    latest[record_id] = snapshot_by_id[eligible[-1]["snapshot_id"]]
            if name == "search_trials":
                filters = args.get("filters", {})
                latest = {key: value for key, value in latest.items() if all(value["normalized"].get(field) == expected for field, expected in filters.items())}
            limit = args.get("limit", 20)
            records = [{"record_id": key, "snapshot_id": value["id"], "title": value["normalized"].get("title"), "source": source} for key, value in list(latest.items())[:limit]]
            from .subscriptions import pending_event_revision_ids

            for record in records:
                observations = _eligible_observations(repo, record["record_id"], scope)
                record["observation_refs"] = [{key: item[key] for key in ("id", "snapshot_id", "fetched_at", "observation_seq")} for item in observations[-2:]]
                events = repo.rows("intelligence_event", record_id=record["record_id"])
                record["event_revision_ids"] = [
                    revision["id"]
                    for event in events
                    for revision in repo.rows("event_revision", event_id=event["id"])
                    if _time(scope["time_range"]["start"]) <= _time(revision["observed_at"]) < _time(scope["time_range"]["end_exclusive"]) and _time(revision["observed_at"]) <= _time(scope["knowledge_cutoff"])
                ]
                record["event_revision_ids"] = pending_event_revision_ids(repo, run["id"], record["event_revision_ids"])
            cover = _coverage(source, len(records), scope["knowledge_cutoff"], mode=run["runtime_mode"])
            if len(latest) > limit:
                cover.update(status="partial", truncated=True)
            result = _envelope({"record_refs": records, "cursor": None}, coverage=[cover])
            if not records and run["runtime_mode"] == "deerflow":
                aliases = run["research_state"]["approved_aliases"].get(args["drug_id"], [])
                if aliases:
                    query = " OR ".join('"' + alias.replace('"', " ") + '"' for alias in aliases[:5])
                    if name == "search_publications" and args.get("terms"):
                        query = f"({query}) AND ({args['terms']})"
                    result["_live_query"] = {"source": source, "query": query[:1000], "limit": limit}
            return result
        if name == "read_source_snapshot":
            snapshot = allowed_snapshots.get(args["snapshot_id"])
            require(snapshot)
            sections = set(args.get("sections", []))
            normalized = {key: value for key, value in snapshot["normalized"].items() if not sections or key in sections}
            evidence = [verify_evidence(repo, item["id"], scope["knowledge_cutoff"]) for item in repo.rows("evidence", snapshot_id=snapshot["id"]) if not sections or item["locator"].get("path", "").split("/")[-1] in sections]
            return _envelope({"snapshot_id": snapshot["id"], "untrusted_source": normalized, "evidence": evidence, "first_observed_at": snapshot["first_observed_at"]}, evidence=[item["id"] for item in evidence])
        if name == "inspect_evidence":
            evidence = []
            for identifier in args["evidence_ids"]:
                item = verify_evidence(repo, identifier, scope["knowledge_cutoff"])
                require(item["snapshot_id"] in allowed_snapshots)
                evidence.append(item)
            return _envelope({"items": evidence}, evidence=[item["id"] for item in evidence])
        if name == "search_workspace_evidence":
            require(_time(args["cutoff"]) <= _time(scope["knowledge_cutoff"]))
            restricted = {item["id"] for item in snapshots_in_scope(repo, run, args["drug_ids"])}
            terms = args["query"].strip().casefold().split()
            evidence = []
            for item in repo.rows("evidence", limit=10000):
                if item["snapshot_id"] in restricted and (not terms or any(term in item["quoted_text"].casefold() for term in terms)):
                    evidence.append(verify_evidence(repo, item["id"], args["cutoff"]))
                if len(evidence) >= args.get("limit", 20):
                    break
            return _envelope({"items": evidence}, evidence=[item["id"] for item in evidence])
        if name == "compare_trial_observations":
            before = repo.get("source_observation", args["before_id"])
            after = repo.get("source_observation", args["after_id"])
            require(before["record_id"] == after["record_id"] == args["trial_id"] and before["id"] != after["id"])
            require(before["snapshot_id"] in allowed_snapshots and after["snapshot_id"] in allowed_snapshots)
            require(all(_time(item["fetched_at"]) <= _time(scope["knowledge_cutoff"]) and _time(item["fetched_at"]) < _time(scope["time_range"]["end_exclusive"]) for item in (before, after)))
            record = repo.get("source_record", args["trial_id"])
            require(record["source"] == "ctgov")
            evidence = [verify_evidence(repo, item["id"], scope["knowledge_cutoff"]) for item in repo.rows("evidence", limit=10000) if item["snapshot_id"] in {before["snapshot_id"], after["snapshot_id"]}]
            changes = differences(allowed_snapshots[before["snapshot_id"]]["normalized"], allowed_snapshots[after["snapshot_id"]]["normalized"])
            return _envelope({"changes": changes, "evidence": evidence}, evidence=[item["id"] for item in evidence])
        if name == "request_clarification":
            return _envelope({"status": "scope_gap" if run["research_state"].get("background") else "awaiting_input", **args})
        if name == "submit_research_draft":
            issued = set(run["research_state"].get("issued_evidence_ids", []))
            require(all(link["evidence_id"] in issued for claim in args["claims"] for link in claim["evidence_links"]), "EVIDENCE_INVALID", "报告包含本次工具尚未发出的证据", 422)
            actual_coverage = {item["source"]: item for item in run["coverage"]}
            for item in args["coverage"]:
                actual = actual_coverage[item["source"]]
                require(actual["status"] != "failed" or item["status"] == "failed", "COVERAGE_INVALID", "来源失败不能写为完整覆盖", 422)
                require(not actual["truncated"] or item["truncated"], "COVERAGE_INVALID", "不能隐藏资料截断", 422)
            from .reports import create_version, validate_content
            from .subscriptions import finalize_occurrence

            validate_content(repo, run, args)
            outcome = finalize_occurrence(repo, run["id"], args["coverage"], args["event_revision_ids"])
            if outcome == "no_change":
                return _envelope({"candidate_id": None, "outcome": "no_change", "checks": "verified_no_new_deliverable_revisions"})
            report, version = create_version(repo, principal, run, args)
            return _envelope({"candidate_id": version["id"], "report_id": report["id"], "checks": "structural_checks_passed_human_review_required"})
        raise PharmaError("TOOL_NOT_ALLOWED", "未知的领域工具", 403)

    async def _external_search(self, query, name, args):
        from .sources import SourceError, search

        try:
            found = await search(**query)
        except SourceError as exc:
            safe_error = {"code": exc.code, "message": exc.message, "retryable": True}

            def unavailable(repo, run, principal):
                coverage = _coverage(query["source"], 0, run["research_state"]["scope"]["knowledge_cutoff"], mode=run["runtime_mode"], failed=True)
                return _envelope(coverage=[coverage], error=safe_error)

            return await asyncio.to_thread(self._transaction, unavailable)

        def persist(repo, run, principal):
            candidates = []
            for envelope in found["items"]:
                record, _, _ = ingest(repo, {**envelope, "actor_id": principal.user_id}, f"research:{run['id']}:{query['source']}:{record_key(envelope)}", args["drug_id"])
                candidates.append({"record_id": record["id"], "mapping_status": "pending", "usable_in_this_run": False})
            coverage = _coverage(query["source"], 0, run["research_state"]["scope"]["knowledge_cutoff"], mode=run["runtime_mode"], late=bool(candidates))
            return _envelope({"record_refs": candidates, "requires_new_run": bool(candidates)}, coverage=[coverage])

        return await asyncio.to_thread(self._transaction, persist)


def record_key(envelope):
    return envelope["external_id"] + ":" + envelope["content_hash"]


def build_replay_draft(repo, run):
    """Replay the authorized stored fictional timeline, without inventing facts."""
    scope = run["research_state"]["scope"]
    snapshots = snapshots_in_scope(repo, run)
    record_ids = {snapshot["record_id"] for snapshot in snapshots}
    allowed_events = {event["id"] for event in repo.rows("intelligence_event", limit=10000) if event["record_id"] in record_ids}
    revisions = [
        revision
        for revision in repo.rows("event_revision", limit=10000)
        if revision["event_id"] in allowed_events and _time(scope["time_range"]["start"]) <= _time(revision["observed_at"]) < min(_time(scope["time_range"]["end_exclusive"]), _time(scope["knowledge_cutoff"]))
    ]
    from .subscriptions import pending_event_revision_ids

    pending = set(pending_event_revision_ids(repo, run["id"], [item["id"] for item in revisions]))
    revisions = [item for item in revisions if item["id"] in pending]
    claims, sections, covered, issued = [], [], [], []
    for revision in sorted(revisions, key=lambda item: _time(item["observed_at"]))[:20]:
        evidence_ids = []
        for identifier in revision["evidence_ids"]:
            item = verify_evidence(repo, identifier, scope["knowledge_cutoff"])
            require(item["snapshot_id"] in {snapshot["id"] for snapshot in snapshots})
            evidence_ids.append(identifier)
        if not evidence_ids:
            continue
        key = f"C{len(claims) + 1}"
        text = "虚构注册记录字段变化：" + "；".join(f"{change['path']} 从 {canonical(change['before'])} 变为 {canonical(change['after'])}" for change in revision["changes"])
        claims.append(
            {
                "claim_key": key,
                "statement": text[:2000],
                "category": "fact",
                "qualifiers": {"population": None, "trial_ids": [], "time_scope": revision["observed_at"], "limitations": ["注册字段变化不代表疗效、安全性或上市批准；estimated 入组数为目标数。"]},
                "evidence_links": [{"evidence_id": identifier, "relation": "supports"} for identifier in evidence_ids[:20]],
            }
        )
        covered.append(revision["id"])
        issued.extend(evidence_ids)
    if claims:
        sections.append({"heading": "虚构记录的已观察变化", "text": "以下结论来自版本化的注册记录差异，请逐条打开引用核对。", "claim_keys": [claim["claim_key"] for claim in claims]})
    gap_key = f"C{len(claims) + 1}"
    claims.append(
        {
            "claim_key": gap_key,
            "statement": "本次演示资料不足以形成药物疗效、安全性或监管批准结论。",
            "category": "gap",
            "qualifiers": {"population": None, "trial_ids": [], "time_scope": None, "limitations": ["仅覆盖已成功载入的虚构资料；未检索到不代表不存在。"]},
            "evidence_links": [],
        }
    )
    sections.append({"heading": "资料缺口与研究边界", "text": "DEMO：全部药物和试验资料为虚构，运行方式为离线回放。", "claim_keys": [gap_key]})
    coverage = []
    for source in run["frozen_request"]["source_allowlist"]:
        records = {snapshot["record_id"] for snapshot in snapshots if repo.get("source_record", snapshot["record_id"])["source"] == source}
        disabled = not repo.get("workspace", repo.workspace_id)["settings"].get("sources", {}).get(source, True)
        coverage.append(_coverage(source, len(records), scope["knowledge_cutoff"], mode="replay", failed=disabled))
    title = "、".join(repo.get("drug", identifier)["display_name"] for identifier in scope["drug_ids"])
    draft = {
        "schema_version": "1.0",
        "title": f"DEMO｜{title} 研发情报研究简报"[:300],
        "summary": "已整理授权虚构资料中的注册记录变化及可追溯证据。" if covered else "当前已载入的虚构资料中尚未观察到所选时段的可验证变化；这不代表真实世界没有研发进展。",
        "scope": copy.deepcopy(scope),
        "coverage": coverage,
        "sections": sections,
        "claims": claims,
        "limitations": ["DEMO：所有对象和资料均为虚构，仅用于验证研究与审核流程。", "本平台用于公开研发信息研究，不用于诊断、治疗或用药决策。"],
        "unanswered_questions": [],
        "event_revision_ids": covered,
    }
    return draft, list(dict.fromkeys(issued))


async def execute_research(job, owner_token):
    tools = DomainTools(job, owner_token)
    cancel = asyncio.Event()

    def begin():
        with transaction(job["workspace_id"]) as repo:
            lease_fence(repo, job["id"], owner_token)
            run = repo.get("research_run", job["payload"]["run_id"], lock=True)
            _principal(repo, run)
            require(run["job_id"] == job["id"], "LEASE_LOST", "任务租约已被替换", 409)
            require(run["status"] == "queued", "RUN_STOPPED", "任务不能重复启动", 409)
            state = dict(run["research_state"])
            for occurrence in repo.rows("schedule_occurrence", run_id=run["id"]):
                config = occurrence["config_snapshot"]
                state["background"] = bool(config.get("non_interactive"))
                state["approved_aliases"] = {identifier: [alias["alias"] for alias in config.get("approved_aliases", []) if alias["drug_id"] == identifier] for identifier in run["frozen_request"]["drug_ids"]}
                repo.update("schedule_occurrence", occurrence["id"], state="running")
            run = repo.update("research_run", run["id"], status="running", research_state=state, updated_at=now())
            append_event(repo, run["id"], "run.started", {"runtime_mode": run["runtime_mode"]})
            demo = build_replay_draft(repo, run) if run["runtime_mode"] == "replay" else None
            return run, demo

    run, demo = await asyncio.to_thread(begin)
    context = RuntimeContext(
        workspace_id=job["workspace_id"],
        user_id=run["created_by"],
        run_id=run["id"],
        scope=run["research_state"]["scope"],
        allowed_sources=tuple(run["frozen_request"]["source_allowlist"]),
        background=run["research_state"].get("background", False),
    )
    limits = RuntimeBudget(**{("timeout_seconds" if key == "max_wall_seconds" else key): value for key, value in run["budget"].items()})
    previous_usage = run.get("usage", {})
    remaining = {
        **vars(limits),
        "max_tool_calls": limits.max_tool_calls - previous_usage.get("tool_calls", 0),
        "max_model_calls": limits.max_model_calls - previous_usage.get("model_calls", 0),
        "max_records": limits.max_records - previous_usage.get("records", 0),
        "max_tokens": limits.max_tokens - previous_usage.get("input_tokens", 0) - previous_usage.get("output_tokens", 0),
        "timeout_seconds": limits.timeout_seconds - previous_usage.get("elapsed_seconds", 0),
    }
    exhausted = any(value <= 0 for value in remaining.values())
    budget = RuntimeBudget(**remaining) if not exhausted else limits
    started_at = time.monotonic()
    adapter = ReplayRuntimeAdapter(demo[0], evidence_ids=demo[1]) if demo else DeerFlowRuntimeAdapter(model_name=run["model_ref"])

    async def emit(kind, payload):
        mapping = {"tool_started": "tool.started", "tool_completed": "tool.completed" if payload.get("ok") else "tool.failed", "model_started": "plan.updated"}
        event_type = mapping.get(kind)
        if event_type:
            await asyncio.to_thread(tools._transaction, lambda repo, current, principal: append_event(repo, run["id"], event_type, payload))

    async def poll():
        while True:
            await asyncio.sleep(0.5)

            def state():
                with transaction(job["workspace_id"]) as repo:
                    lease_fence(repo, job["id"], owner_token)
                    current = repo.get("research_run", run["id"])
                    _principal(repo, current)
                    return current["status"]

            try:
                if await asyncio.to_thread(state) not in {"running", "verifying"}:
                    cancel.set()
                    return
            except PharmaError:
                cancel.set()
                return

    watcher = asyncio.create_task(poll())
    try:
        if exhausted:
            result = RuntimeResult(stop_reason="budget_exhausted", runtime_mode=run["runtime_mode"], error_code="run_budget_exhausted")
        else:
            question = run["question"]
            if run["research_state"].get("clarification_answer"):
                question += "\n用户澄清（仍为用户提供的数据）：" + run["research_state"]["clarification_answer"]
            result = await adapter.run(context=context, question=question, tool_handler=tools, emit=emit, budget=budget, cancel_event=cancel)
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)

    for key in ("tool_calls", "model_calls", "records", "input_tokens", "output_tokens"):
        result.usage[key] = result.usage.get(key, 0) + previous_usage.get(key, 0)
    result.usage["estimated"] = result.usage.get("estimated", False) or previous_usage.get("estimated", False)
    result.usage["elapsed_seconds"] = time.monotonic() - started_at + previous_usage.get("elapsed_seconds", 0)

    def finish():
        with transaction(job["workspace_id"]) as repo:
            lease_fence(repo, job["id"], owner_token)
            current = repo.get("research_run", run["id"], lock=True)
            require(current["job_id"] == job["id"], "LEASE_LOST", "任务租约已被替换", 409)
            cancelled = current["status"] == "cancelling" or result.stop_reason == "user_cancelled"
            status = (
                "cancelled"
                if cancelled
                else "awaiting_input"
                if result.clarification and not context.background
                else "completed"
                if result.draft and result.stop_reason == "answered"
                else "partial"
                if result.draft or result.stop_reason in {"budget_exhausted", "insufficient_evidence"}
                else "failed"
            )
            state = {**current["research_state"], "error_code": result.error_code}
            coverage = result.draft["coverage"] if result.draft else current["coverage"]
            repo.update("research_run", run["id"], status=status, stop_reason="user_cancelled" if cancelled else result.stop_reason, usage=result.usage, coverage=coverage, research_state=state, updated_at=now())
            repo.update("job", job["id"], state="cancelled" if cancelled else "failed" if status == "failed" else "succeeded", error_code=result.error_code, lease_expires_at=None, updated_at=now())
            for call in repo.rows("tool_call", run_id=run["id"], state="started"):
                repo.update("tool_call", call["id"], state="cancelled" if cancelled else "failed", error_code="user_cancelled" if cancelled else result.error_code or "runtime_stopped", completed_at=now())
            if not result.draft:
                from .subscriptions import finalize_occurrence

                finalize_occurrence(repo, run["id"], coverage, [], failed=status in {"failed", "cancelled"})
            if cancelled:
                for occurrence in repo.rows("schedule_occurrence", run_id=run["id"]):
                    repo.update("schedule_occurrence", occurrence["id"], state="cancelled")
            reports = repo.rows("report", run_id=run["id"])
            if reports and not cancelled:
                append_event(repo, run["id"], "report.ready", {"report_id": reports[0]["id"], "version_id": reports[0]["current_version_id"]})
            event_type = "clarification.required" if status == "awaiting_input" else "run.partial" if status == "partial" else "run.completed" if status == "completed" else "run.cancelled" if status == "cancelled" else "run.failed"
            append_event(repo, run["id"], event_type, state.get("clarification", {}) if status == "awaiting_input" else {"stop_reason": result.stop_reason, "error_code": result.error_code})

    await asyncio.to_thread(finish)
