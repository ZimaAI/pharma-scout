"""Research tool/report flow on a disposable migrated PostgreSQL schema."""

import copy
from contextlib import contextmanager
from datetime import timedelta

import pytest
import test_pharma_persistence as _persistence

from app.pharma import db, research
from app.pharma.auth import Principal
from app.pharma.errors import PharmaError
from app.pharma.seed import seed

database = _persistence.database
repo = _persistence.repo

pytestmark = pytest.mark.integration


def prepare(scoped, actor):
    seed(scoped, actor, 3)
    principal = Principal(scoped.get("app_user", actor), {}, scoped.workspace_id, "analyst")
    drug = next(row for row in scoped.rows("drug") if row["development_code"] == "PX-101")
    run = research.create_run(
        scoped,
        principal,
        {
            "question": "整理公开注册记录的变化与可核对证据",
            "drug_ids": [drug["id"]],
            "time_range": {"start": "2026-09-14T00:00:00Z", "end_exclusive": "2026-09-21T00:00:00Z", "timezone": "Asia/Shanghai"},
            "source_allowlist": ["ctgov", "pubmed"],
        },
    )
    token = db.uid()
    job = scoped.update("job", run["job_id"], state="running", owner_token=token, lease_expires_at=db.now() + timedelta(minutes=5))
    return run, job, token, principal


@pytest.mark.asyncio
async def test_replay_worker_generates_persisted_version_and_auditable_tools(repo, monkeypatch):
    scoped, actor = repo
    run, job, token, _ = prepare(scoped, actor)

    @contextmanager
    def same_transaction(workspace_id=None):
        assert workspace_id == scoped.workspace_id
        yield db.Repository(scoped.connection, workspace_id)

    monkeypatch.setattr(research, "transaction", same_transaction)
    await research.execute_research(job, token)
    current = scoped.get("research_run", run["id"])
    assert current["status"] == "completed"
    assert scoped.get("job", job["id"])["state"] == "succeeded"
    report = scoped.rows("report", run_id=run["id"])[0]
    version = scoped.get("report_version", report["current_version_id"])
    assert version["runtime_mode"] == "replay"
    assert len(version["content_json"]["event_revision_ids"]) == 2
    assert scoped.rows("claim_evidence")
    calls = scoped.rows("tool_call", run_id=run["id"])
    assert {item["tool"] for item in calls} == {"inspect_evidence", "submit_research_draft"}
    assert all(item["state"] == "completed" for item in calls)
    events = scoped.rows("run_event", run_id=run["id"], order=scoped.table("run_event").c.seq)
    assert [item["seq"] for item in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "run.completed"
    assert report["published_version_id"] is None


def test_domain_tool_rejects_foreign_and_future_evidence(repo):
    scoped, actor = repo
    run, job, token, principal = prepare(scoped, actor)
    run = scoped.update("research_run", run["id"], status="running")
    tool = research.DomainTools(job, token)
    snapshot = scoped.rows("source_snapshot")[0]
    foreign = scoped.add("source_record", source="ctgov", external_id="DEMO-UNAPPROVED", kind="trial", canonical_url="demo://DEMO-UNAPPROVED", is_demo=True)
    from app.pharma.domain import ingest
    from app.pharma.seed import fixture

    payload = {**copy.deepcopy(fixture("02-trial-snapshots.json")[0]), "source": "ctgov", "external_id": foreign["external_id"], "record_type": "trial", "url": foreign["canonical_url"]}
    _, observation, _ = ingest(scoped, payload, "foreign-record")
    evidence = scoped.rows("evidence", snapshot_id=observation["snapshot_id"])[0]
    with pytest.raises(PharmaError):
        tool.dispatch(scoped, run, principal, "inspect_evidence", {"evidence_ids": [evidence["id"]]})
    with pytest.raises(PharmaError):
        tool.dispatch(scoped, run, principal, "read_source_snapshot", {"snapshot_id": observation["snapshot_id"]})
    assert snapshot["id"] in {item["id"] for item in research.snapshots_in_scope(scoped, run)}


def test_submission_cannot_use_evidence_not_issued_in_this_run(repo):
    scoped, actor = repo
    run, job, token, principal = prepare(scoped, actor)
    run = scoped.update("research_run", run["id"], status="running")
    draft, _ = research.build_replay_draft(scoped, run)
    with pytest.raises(PharmaError, match="尚未发出"):
        research.DomainTools(job, token).dispatch(scoped, run, principal, "submit_research_draft", draft)
    assert scoped.rows("report", run_id=run["id"]) == []


def test_revoked_membership_stops_tool_before_database_read(repo):
    scoped, actor = repo
    run, job, token, _ = prepare(scoped, actor)
    scoped.update("research_run", run["id"], status="running")
    member = scoped.table("membership")
    scoped.connection.execute(member.update().where(member.c.workspace_id == scoped.workspace_id, member.c.user_id == actor).values(enabled=False))
    with pytest.raises(PharmaError, match="权限"):
        research.DomainTools(job, token)._open(scoped)


def test_search_uses_latest_observation_even_when_content_reverts(repo):
    scoped, actor = repo
    seed(scoped, actor, 5)
    run, job, token, principal = prepare(scoped, actor)
    tool = research.DomainTools(job, token)
    drug_id = run["frozen_request"]["drug_ids"][0]
    live = tool.dispatch(scoped, run, principal, "search_trials", {"drug_id": drug_id})
    current_ref = live["data"]["record_refs"][0]
    current = scoped.get("source_snapshot", current_ref["snapshot_id"])
    assert current["normalized"]["enrollment"]["count"] == 120
    assert current_ref["observation_refs"][-1]["snapshot_id"] == current["id"]

    historical_run = copy.deepcopy(run)
    historical_run["research_state"]["scope"]["knowledge_cutoff"] = "2026-09-17T00:00:00+00:00"
    historical = tool.dispatch(scoped, historical_run, principal, "search_trials", {"drug_id": drug_id})
    historical_ref = historical["data"]["record_refs"][0]
    snapshot = scoped.get("source_snapshot", historical_ref["snapshot_id"])
    assert snapshot["normalized"]["enrollment"]["count"] == 160
    assert historical_ref["observation_refs"][-1]["snapshot_id"] == snapshot["id"]

    # D5 reuses an old snapshot; filtering only first_observed_at would let
    # its boundary observation leak into a window that ends before D5.
    boundary_run = copy.deepcopy(run)
    boundary_run["research_state"]["scope"]["knowledge_cutoff"] = "2026-09-18T08:00:00+00:00"
    boundary_run["research_state"]["scope"]["time_range"]["end_exclusive"] = "2026-09-18T08:00:00+00:00"
    boundary_run["frozen_request"]["time_range"]["end_exclusive"] = "2026-09-18T08:00:00+00:00"
    boundary = tool.dispatch(scoped, boundary_run, principal, "search_trials", {"drug_id": drug_id})
    boundary_ref = boundary["data"]["record_refs"][0]
    assert scoped.get("source_snapshot", boundary_ref["snapshot_id"])["normalized"]["enrollment"]["count"] == 150
    previous, latest = current_ref["observation_refs"]
    with pytest.raises(PharmaError):
        tool.dispatch(scoped, boundary_run, principal, "compare_trial_observations", {"trial_id": current_ref["record_id"], "before_id": previous["id"], "after_id": latest["id"]})
