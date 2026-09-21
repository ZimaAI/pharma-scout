"""Real PostgreSQL worker fencing with synthetic, offline source responses."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta

import pytest
from support.pharma import database as database
from support.pharma import repo as repo

from app.pharma import db, worker
from app.pharma.domain import ingest
from app.pharma.errors import PharmaError
from app.pharma.sources import SourceError, normalize_ctgov


@pytest.fixture
def worker_repo(repo, monkeypatch):
    scoped, actor = repo
    scoped.update("workspace", scoped.workspace_id, settings={"data_mode": "live"})

    @contextmanager
    def same_transaction(workspace_id=None):
        with scoped.connection.begin_nested():
            yield db.Repository(scoped.connection, workspace_id)

    monkeypatch.setattr(worker, "transaction", same_transaction)
    return scoped, actor


def _job(scoped, actor, **overrides):
    drug = scoped.add("drug", display_name="Synthetic worker research object")
    scoped.add("drug_alias", drug_id=drug["id"], alias="Synthetic worker alias", normalized_alias="synthetic worker alias", namespace="development_code", note="Synthetic test", proposed_by=actor, status="approved")
    payload = {"actor_id": actor, "drug_ids": [drug["id"]], "sources": ["ctgov"], "mode": "refresh_linked", "record_limit": 20, **overrides}
    return scoped.add("job", kind="ingest", state="running", payload=payload, owner_token=db.uid(), lease_expires_at=db.now() + timedelta(seconds=90))


def _envelope(identifier="NCT00000001", status="RECRUITING"):
    return normalize_ctgov({"protocolSection": {"identificationModule": {"nctId": identifier, "briefTitle": "Synthetic worker trial"}, "statusModule": {"overallStatus": status}}, "hasResults": False})


def _link(scoped, actor, job, identifier):
    envelope = {**_envelope(identifier), "actor_id": actor}
    record, observation, _ = ingest(scoped, envelope, "synthetic-baseline:" + identifier, drug_id=job["payload"]["drug_ids"][0])
    link = scoped.rows("entity_link", record_id=record["id"])[0]
    scoped.update("entity_link", link["id"], status="approved")
    return record, observation


@pytest.mark.integration
class TestWorkerPersistence:
    def test_heartbeat_cannot_revive_expired_or_replaced_lease(self, worker_repo):
        scoped, actor = worker_repo
        job = _job(scoped, actor)
        assert worker.heartbeat(job) is True
        scoped.update("job", job["id"], lease_expires_at=db.now() - timedelta(seconds=1))
        assert worker.heartbeat(job) is False
        with pytest.raises(PharmaError) as caught:
            worker.assert_lease(scoped, job["id"], job["owner_token"])
        assert caught.value.code == "LEASE_LOST"
        scoped.update("job", job["id"], owner_token=db.uid(), lease_expires_at=db.now() + timedelta(seconds=90))
        assert worker.heartbeat(job) is False

    @pytest.mark.parametrize("mutation", ["cancel", "owner", "membership", "source"])
    def test_after_response_writes_recheck_lease_membership_and_source(self, worker_repo, mutation):
        scoped, actor = worker_repo
        job = _job(scoped, actor)
        if mutation == "cancel":
            scoped.update("job", job["id"], state="cancelled")
        elif mutation == "owner":
            scoped.update("job", job["id"], owner_token=db.uid())
        elif mutation == "membership":
            table = scoped.table("membership")
            scoped.connection.execute(table.update().where(table.c.workspace_id == scoped.workspace_id, table.c.user_id == actor).values(enabled=False))
        else:
            scoped.update("workspace", scoped.workspace_id, settings={"data_mode": "live", "sources": {"ctgov": False}})
        with pytest.raises(PharmaError):
            worker.save_result(job, {"source": "ctgov", "drug_id": job["payload"]["drug_ids"][0]}, _envelope(), 0)
        assert scoped.rows("source_snapshot") == []

    def test_disabled_demo_source_does_not_ingest_fixture(self, worker_repo):
        scoped, actor = worker_repo
        job = _job(scoped, actor)
        scoped.update("workspace", scoped.workspace_id, settings={"data_mode": "demo", "sources": {"ctgov": False}})
        with pytest.raises(PharmaError) as caught:
            worker.plan_ingestion(job)
        assert caught.value.code == "SOURCE_DISABLED"
        assert scoped.rows("source_record") == []

    @pytest.mark.asyncio
    async def test_refresh_keeps_success_and_records_not_found_without_losing_current_snapshot(self, worker_repo, monkeypatch):
        scoped, actor = worker_repo
        job = _job(scoped, actor)
        first, _ = _link(scoped, actor, job, "NCT00000001")
        second, previous = _link(scoped, actor, job, "NCT00000002")

        class Sources:
            async def fetch(self, source, external_id):
                if external_id == "NCT00000002":
                    raise SourceError("not_found", "Synthetic missing record", source)
                return _envelope(external_id, "ACTIVE_NOT_RECRUITING")

            async def __aexit__(self, *_args):
                pass

        monkeypatch.setattr(worker, "PharmaSources", Sources)
        await worker.execute_ingestion(job)
        assert scoped.get("source_record", first["id"])["current_projection"]["status"] == "ACTIVE_NOT_RECRUITING"
        assert scoped.get("source_record", second["id"])["current_snapshot_id"] == previous["snapshot_id"]
        failures = scoped.rows("source_observation", record_id=second["id"], outcome="unavailable")
        assert len(failures) == 1 and failures[0]["error_code"] == "not_found" and failures[0]["snapshot_id"] is None
        complete = scoped.get("job", job["id"])
        assert complete["coverage"][0]["status"] == "partial"
        assert complete["coverage"][0]["records_count"] == 1
        assert scoped.rows("source_sync_state")[0]["complete_watermark"] is None

    @pytest.mark.asyncio
    async def test_discovery_preserves_first_page_when_later_alias_fails(self, worker_repo, monkeypatch):
        scoped, actor = worker_repo
        job = _job(scoped, actor, mode="discovery")
        drug_id = job["payload"]["drug_ids"][0]
        scoped.add("drug_alias", drug_id=drug_id, alias="Second synthetic alias", normalized_alias="second synthetic alias", namespace="development_code", note="Synthetic test", proposed_by=actor, status="approved")

        class Sources:
            calls = 0

            async def search(self, source, query, limit):
                self.calls += 1
                if self.calls == 2:
                    raise SourceError("timeout", "Synthetic timeout", source)
                return {"items": [_envelope()], "coverage": {"status": "complete"}}

            async def __aexit__(self, *_args):
                pass

        monkeypatch.setattr(worker, "PharmaSources", Sources)
        await worker.execute_ingestion(job)
        assert len(scoped.rows("source_snapshot")) == 1
        coverage = scoped.get("job", job["id"])["coverage"][0]
        assert coverage["records_count"] == 1 and coverage["status"] == "partial"

    def test_idempotent_observation_still_links_second_drug_candidate(self, worker_repo):
        scoped, actor = worker_repo
        job = _job(scoped, actor)
        second = scoped.add("drug", display_name="Second synthetic research object")
        for drug_id in [job["payload"]["drug_ids"][0], second["id"]]:
            worker.save_result(job, {"source": "ctgov", "drug_id": drug_id}, _envelope(), 0)
        assert len(scoped.rows("source_observation")) == 1
        assert {link["drug_id"] for link in scoped.rows("entity_link")} == {job["payload"]["drug_ids"][0], second["id"]}
        assert {link["status"] for link in scoped.rows("entity_link")} == {"pending"}

    def test_old_failed_job_cannot_overwrite_new_research_attempt(self, worker_repo):
        scoped, actor = worker_repo
        old_job = scoped.add("job", kind="research", state="running", owner_token=db.uid(), lease_expires_at=db.now() + timedelta(seconds=90))
        new_job = scoped.add("job", kind="research", state="queued")
        run = scoped.add("research_run", created_by=actor, job_id=new_job["id"], question="Synthetic retried research", runtime_mode="replay", frozen_request={}, prompt_version="synthetic-test")
        old_job = scoped.update("job", old_job["id"], payload={"run_id": run["id"]})
        worker.fail_job(old_job, "SYNTHETIC_OLD_FAILURE")
        assert scoped.get("job", old_job["id"])["state"] == "failed"
        assert scoped.get("research_run", run["id"])["status"] == "queued"
        assert scoped.rows("run_event", run_id=run["id"]) == []


@pytest.mark.asyncio
async def test_scheduler_and_delivery_continue_while_research_is_running(monkeypatch):
    from app.pharma import research, subscriptions

    research_started = asyncio.Event()
    tick_during_research = asyncio.Event()
    loop = asyncio.get_running_loop()
    claimed = False

    class Result:
        def scalar(self):
            return True

    class Leadership:
        def execute(self, *_args):
            return Result()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    class Engine:
        def connect(self):
            return Leadership()

    def claim():
        nonlocal claimed
        if claimed:
            return None
        claimed = True
        return {"kind": "research", "id": "synthetic-job", "owner_token": "synthetic-owner"}

    def tick():
        if research_started.is_set():
            loop.call_soon_threadsafe(tick_during_research.set)
        return ["synthetic-workspace"]

    async def run(*_args):
        research_started.set()
        await asyncio.Event().wait()

    original_service = worker.service_schedules_and_deliveries
    monkeypatch.setattr(worker, "service_schedules_and_deliveries", lambda: original_service(interval=0.01))
    monkeypatch.setattr(worker, "engine", Engine)
    monkeypatch.setattr(worker, "recover_and_claim", claim)
    monkeypatch.setattr(worker, "tick_schedules", tick)
    monkeypatch.setattr(research, "execute_research", run)
    monkeypatch.setattr(subscriptions, "process_deliveries", lambda _workspace: None)
    task = asyncio.create_task(worker.serve())
    try:
        await asyncio.wait_for(tick_during_research.wait(), timeout=3)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
