"""Single research slot, durable PostgreSQL jobs and separately fenced delivery.

Run: python -m app.pharma.worker. A database advisory lock elects one scheduler
and research executor; lease tokens fence every completed external operation.
"""

import asyncio
import logging
import time
from contextlib import suppress
from datetime import datetime, timedelta

from sqlalchemy import select, text

from .api import source_health
from .auth import Principal
from .db import Repository, digest, engine, now, transaction, uid
from .domain import ingest
from .errors import PharmaError, require
from .sources import PharmaSources, SourceError

logger = logging.getLogger(__name__)


def assert_lease(repo, job_id, owner_token):
    job = repo.get("job", job_id, lock=True)
    require(job["state"] == "running" and job["owner_token"] == owner_token and datetime.fromisoformat(job["lease_expires_at"]) > now(), "LEASE_LOST", "执行租约已失效", 409)
    return job


def recover_and_claim():
    with transaction() as base:
        table = base.table("job")
        expired = base.connection.execute(select(table).where(table.c.state == "running", table.c.lease_expires_at < now()).with_for_update(skip_locked=True)).mappings().all()
        for row in expired:
            repo = Repository(base.connection, str(row["workspace_id"]))
            if row["kind"] == "research":
                from .research import append_event

                run_id = row["payload"]["run_id"]
                current = repo.get("research_run", run_id, lock=True)
                if current["job_id"] == str(row["id"]) and current["status"] in ("running", "verifying", "cancelling"):
                    repo.update("research_run", run_id, status="recovery_required", stop_reason="runtime_error", updated_at=now())
                    append_event(repo, run_id, "run.recovery_required", {"reason": "worker_lease_expired"})
                repo.update("job", str(row["id"]), state="failed", error_code="RECOVERY_REQUIRED")
            else:
                repo.update("job", str(row["id"]), state="retry_wait", available_at=now(), owner_token=None)
        row = base.connection.execute(select(table).where(table.c.state.in_(["queued", "retry_wait"]), table.c.available_at <= now()).order_by(table.c.available_at).with_for_update(skip_locked=True).limit(1)).mappings().first()
        if not row:
            return None
        repo = Repository(base.connection, str(row["workspace_id"]))
        return repo.update("job", str(row["id"]), state="running", owner_token=uid(), lease_expires_at=now() + timedelta(seconds=90), attempt=row["attempt"] + 1, updated_at=now())


def heartbeat(job):
    with transaction(job["workspace_id"]) as repo:
        current = repo.get("job", job["id"], lock=True)
        if current["owner_token"] != job["owner_token"] or current["state"] != "running" or datetime.fromisoformat(current["lease_expires_at"]) <= now():
            return False
        repo.update("job", job["id"], lease_expires_at=now() + timedelta(seconds=90), updated_at=now())
        return True


async def keep_lease(job):
    while True:
        await asyncio.sleep(20)
        if not await asyncio.to_thread(heartbeat, job):
            return


def authorize_ingestion(repo, job, source=None):
    actor = repo.get("app_user", job["payload"]["actor_id"])
    memberships = repo.rows("membership", user_id=actor["id"], enabled=True)
    require(actor["is_active"] and memberships and memberships[0]["role"] in ("analyst", "reviewer", "admin"), "FORBIDDEN", "任务发起人权限已失效", 403)
    if source:
        workspace = repo.get("workspace", repo.workspace_id)
        require(workspace["settings"].get("sources", {}).get(source, True), "SOURCE_DISABLED", "来源已停用", 503)


def plan_ingestion(job):
    with transaction(job["workspace_id"]) as repo:
        assert_lease(repo, job["id"], job["owner_token"])
        payload = job["payload"]
        authorize_ingestion(repo, job)
        workspace = repo.get("workspace", repo.workspace_id)
        if workspace["settings"].get("data_mode") == "demo":
            from .seed import seed

            for source in payload["sources"]:
                authorize_ingestion(repo, job, source)
            for drug_id in payload["drug_ids"]:
                require(not repo.get("drug", drug_id)["archived"], "VALIDATION_ERROR", "药物已归档", 422)
            seed(repo, payload["actor_id"], workspace["settings"].get("demo_day", 3))
            coverage = [
                {"source": source, "status": "complete", "records_count": len(repo.rows("source_record", source=source)), "truncated": False, "as_of": now().isoformat(), "limitations": ["虚构数据回放，不代表真实世界来源覆盖。"]}
                for source in payload["sources"]
            ]
            repo.update("job", job["id"], state="succeeded", coverage=coverage, progress={"processed": sum(c["records_count"] for c in coverage), "total": None})
            return None
        plan = []
        if payload.get("source_plan"):
            return payload["source_plan"]
        health = {source["source"]: source for source in source_health(repo)}
        for source in payload["sources"]:
            for drug_id in payload["drug_ids"]:
                drug = repo.get("drug", drug_id)
                require(not drug["archived"], "VALIDATION_ERROR", "药物已归档", 422)
                aliases = repo.rows("drug_alias", drug_id=drug_id, status="approved")
                record_ids = {link["record_id"] for link in repo.rows("entity_link", drug_id=drug_id, status="approved")}
                records = [repo.get("source_record", identifier) for identifier in record_ids]
                ids = [r["external_id"] for r in records if r["source"] == source]
                plan.append({"source": source, "drug_id": drug_id, "aliases": [a["alias"] for a in aliases], "ids": ids, "enabled": health[source]["enabled"]})
        repo.update("job", job["id"], payload={**payload, "source_plan": plan})
        return plan


def save_result(job, scope, envelope, index):
    with transaction(job["workspace_id"]) as repo:
        assert_lease(repo, job["id"], job["owner_token"])
        authorize_ingestion(repo, job, scope["source"])
        envelope["actor_id"] = job["payload"]["actor_id"]
        return ingest(repo, envelope, f"{job['id']}:{scope['source']}:{envelope['external_id']}", drug_id=scope["drug_id"])


def authorize_source_request(job, source):
    with transaction(job["workspace_id"]) as repo:
        assert_lease(repo, job["id"], job["owner_token"])
        authorize_ingestion(repo, job, source)


def save_source_failure(job, source, external_id, code):
    """A failed refresh is an observation, never a replacement snapshot."""
    with transaction(job["workspace_id"]) as repo:
        assert_lease(repo, job["id"], job["owner_token"])
        authorize_ingestion(repo, job, source)
        repo.advisory(f"ingest:{repo.workspace_id}:{source}:{external_id}")
        rows = repo.rows("source_record", source=source, external_id=external_id)
        if not rows:
            return
        record = rows[0]
        operation_key = f"{job['id']}:{source}:{external_id}:failure"
        if repo.rows("source_observation", record_id=record["id"], operation_key=operation_key):
            return
        seq = record["next_observation_seq"] + 1
        repo.add("source_observation", record_id=record["id"], observation_seq=seq, fetched_at=now(), outcome="unavailable" if code == "not_found" else "failed", error_code=code, operation_key=operation_key)
        repo.update("source_record", record["id"], next_observation_seq=seq, updated_at=now())


def complete_ingestion(job, coverage):
    with transaction(job["workspace_id"]) as repo:
        assert_lease(repo, job["id"], job["owner_token"])
        authorize_ingestion(repo, job)
        for item in coverage:
            fingerprint = digest({"sources": [item["source"]], "drugs": job["payload"]["drug_ids"]})
            rows = repo.rows("source_sync_state", source=item["source"], query_fingerprint=fingerprint)
            values = {"last_error_code": None if item["status"] == "complete" else "SOURCE_PARTIAL", "last_success_at": now() if item["status"] == "complete" else rows[0]["last_success_at"] if rows else None}
            if item["status"] == "complete":
                values["complete_watermark"] = now()
            if rows:
                repo.update("source_sync_state", rows[0]["id"], **values)
            else:
                repo.add("source_sync_state", source=item["source"], query_fingerprint=fingerprint, scope={"drug_ids": job["payload"]["drug_ids"]}, **values)
        repo.update(
            "job",
            job["id"],
            state="failed" if all(c["status"] == "failed" for c in coverage) else "succeeded",
            coverage=coverage,
            error_code="SOURCE_PARTIAL" if any(c["status"] != "complete" for c in coverage) else None,
            progress={"processed": sum(c["records_count"] for c in coverage), "total": None},
            updated_at=now(),
        )


async def execute_ingestion(job):
    plan = await asyncio.to_thread(plan_ingestion, job)
    if plan is None:
        return
    sources = PharmaSources()
    coverage = {source: {"source": source, "status": "complete", "records_count": 0, "truncated": False, "as_of": now().isoformat(), "limitations": []} for source in job["payload"]["sources"]}
    record_limit = job["payload"].get("record_limit", 50)
    processed = 0
    attempted = 0
    query_count = 0
    deadline = time.monotonic() + 600
    seen = set()

    async def persist(scope, envelope):
        nonlocal processed
        await asyncio.to_thread(save_result, job, scope, envelope, processed)
        identity = (scope["source"], envelope["external_id"])
        if identity not in seen:
            seen.add(identity)
            processed += 1
            coverage[scope["source"]]["records_count"] += 1
            if coverage[scope["source"]]["status"] == "failed":
                coverage[scope["source"]]["status"] = "partial"

    def failed(item, code):
        item["status"] = "partial" if item["records_count"] else "failed"
        if code not in item["limitations"]:
            item["limitations"].append(code)

    try:
        for scope in plan:
            item = coverage[scope["source"]]
            try:
                require(scope["enabled"], "SOURCE_DISABLED", "来源已停用", 503)
                truncated = False
                if job["payload"]["mode"] == "refresh_linked":
                    for external_id in scope["ids"]:
                        if attempted >= record_limit or time.monotonic() >= deadline:
                            truncated = True
                            break
                        await asyncio.to_thread(authorize_source_request, job, scope["source"])
                        attempted += 1
                        try:
                            envelope = await sources.fetch(scope["source"], external_id)
                        except SourceError as exc:
                            await asyncio.to_thread(save_source_failure, job, scope["source"], external_id, exc.code)
                            failed(item, exc.code)
                            continue
                        await persist(scope, envelope)
                else:
                    require(scope["aliases"], "SCOPE_AMBIGUOUS", "请先审核药物别名再同步官方来源", 422)
                    for alias in scope["aliases"]:
                        if attempted >= record_limit or query_count >= 20 or time.monotonic() >= deadline:
                            truncated = True
                            break
                        await asyncio.to_thread(authorize_source_request, job, scope["source"])
                        query_count += 1
                        try:
                            page = await sources.search(scope["source"], alias, limit=min(100, record_limit - attempted))
                        except SourceError as exc:
                            failed(item, exc.code)
                            continue
                        attempted += len(page["items"])
                        for envelope in page["items"]:
                            await persist(scope, envelope)
                        truncated |= page["coverage"]["status"] != "complete"
                if truncated:
                    item["status"], item["truncated"] = "partial", True
                    item["limitations"].append("达到本次记录或分页上限，资料覆盖不完整。")
            except (SourceError, PharmaError) as exc:
                if exc.code in {"LEASE_LOST", "FORBIDDEN"}:
                    raise
                failed(item, exc.code)
        await asyncio.to_thread(complete_ingestion, job, list(coverage.values()))
    finally:
        await sources.__aexit__(None, None, None)


def tick_schedules():
    from .research import create_run
    from .subscriptions import scan_subscriptions

    with transaction() as base:
        workspaces = base.rows("workspace")
    for workspace in workspaces:
        with transaction(workspace["id"]) as repo:
            scan_subscriptions(repo, create_run=lambda r, owner, body: create_run(r, Principal(r.get("app_user", owner), {}, r.workspace_id, "analyst"), body))
    return [w["id"] for w in workspaces]


def fail_job(job, code):
    with transaction(job["workspace_id"]) as repo:
        assert_lease(repo, job["id"], job["owner_token"])
        repo.update("job", job["id"], state="failed", error_code=code, updated_at=now())
        if job["kind"] == "research":
            from .research import append_event

            run_id = job["payload"]["run_id"]
            current = repo.get("research_run", run_id, lock=True)
            if current["job_id"] == job["id"]:
                repo.update("research_run", run_id, status="failed", stop_reason="runtime_error", updated_at=now())
                append_event(repo, run_id, "run.failed", {"error_code": code})


async def service_schedules_and_deliveries(interval=2):
    """Keep durable occurrences and notifications moving during long research."""
    from .subscriptions import process_deliveries

    while True:
        workspaces = await asyncio.to_thread(tick_schedules)
        for workspace_id in workspaces:
            await asyncio.to_thread(process_deliveries, workspace_id)
        await asyncio.sleep(interval)


async def monitor_leadership(connection):
    while True:
        await asyncio.to_thread(connection.execute, text("SELECT 1"))
        await asyncio.sleep(5)


async def serve():
    from .research import execute_research

    # Session lock is released automatically on process/database disconnect.
    with engine().connect() as leadership:
        elected = leadership.execute(text("SELECT pg_try_advisory_lock(734102981)")).scalar()
        require(elected, "WORKER_ALREADY_RUNNING", "已有医药任务执行进程", 409)
        async with asyncio.TaskGroup() as group:
            group.create_task(service_schedules_and_deliveries())
            group.create_task(monitor_leadership(leadership))
            while True:
                job = await asyncio.to_thread(recover_and_claim)
                if not job:
                    await asyncio.sleep(2)
                    continue
                keepalive = asyncio.create_task(keep_lease(job))
                try:
                    if job["kind"] == "research":
                        await execute_research(job, job["owner_token"])
                    elif job["kind"] == "ingest":
                        await execute_ingestion(job)
                except Exception as exc:
                    code = exc.code if isinstance(exc, PharmaError) else "WORKER_ERROR"
                    logger.error("Job failed job_id=%s code=%s", job["id"], code)
                    with suppress(PharmaError):
                        await asyncio.to_thread(fail_job, job, code)
                finally:
                    keepalive.cancel()
                    with suppress(asyncio.CancelledError):
                        await keepalive


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
