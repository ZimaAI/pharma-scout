import copy
from datetime import timedelta

import pytest

from app.pharma.auth import Principal
from app.pharma.db import now, uid
from app.pharma.errors import PharmaError
from app.pharma.research import append_event, create_run, lease_fence, serialize_run, snapshots_in_scope


class MemoryRepo:
    def __init__(self):
        self.workspace_id = uid()
        self.data = {}
        self.locked = []

    def rows(self, name, limit=500, lock=False, **filters):
        return [copy.deepcopy(row) for row in self.data.get(name, []) if all(row.get(k) == v for k, v in filters.items())][:limit]

    def get(self, name, identifier, lock=False):
        if lock:
            self.locked.append((name, identifier))
        rows = self.rows(name, id=identifier)
        if not rows:
            raise PharmaError("NOT_FOUND", "missing", 404)
        return rows[0]

    def add(self, name, **values):
        row = {"id": uid(), "workspace_id": self.workspace_id, "created_at": now().isoformat(), "updated_at": now().isoformat(), **copy.deepcopy(values)}
        if name == "research_run":
            row = {"next_event_seq": 0, "attempt": 0, "stop_reason": None, "status": "queued", **row}
        self.data.setdefault(name, []).append(row)
        return copy.deepcopy(row)

    def update(self, name, identifier, **values):
        for row in self.data[name]:
            if row["id"] == identifier:
                row.update(copy.deepcopy(values))
                return copy.deepcopy(row)
        raise AssertionError("Missing update")

    def advisory(self, _):
        pass

    def audit(self, *_, **__):
        pass


def setup_case():
    repo = MemoryRepo()
    principal = Principal({"id": uid(), "is_active": True}, {}, repo.workspace_id, "analyst")
    repo.add("workspace", id=repo.workspace_id, settings={"data_mode": "demo"})
    drug = repo.add("drug", display_name="PX-101", revision=1, archived=False)
    repo.add("drug_alias", drug_id=drug["id"], alias="PX-101", normalized_alias="px-101", status="approved")
    request = {
        "question": "研究公开注册资料中的变化与证据",
        "drug_ids": [drug["id"]],
        "time_range": {"start": "2026-09-01T00:00:00Z", "end_exclusive": "2026-10-01T00:00:00Z", "timezone": "Asia/Shanghai"},
        "source_allowlist": ["ctgov", "pubmed"],
    }
    return repo, principal, request


def test_run_mode_and_identity_are_server_bound():
    repo, principal, request = setup_case()
    run = create_run(repo, principal, request)
    assert run["runtime_mode"] == "replay"
    assert run["created_by"] == principal.user_id
    assert run["frozen_request"] == request
    assert run["research_state"]["scope"]["knowledge_cutoff"] == run["created_at"]
    assert repo.get("job", run["job_id"])["payload"] == {"run_id": run["id"], "actor_id": principal.user_id}
    serialized = serialize_run(repo, run)
    assert serialized["event_seq"] == 1
    assert serialized["report_id"] is None
    assert serialized["usage"]["estimated_cost"] is None


def test_unknown_drug_and_injected_mode_are_rejected():
    repo, principal, request = setup_case()
    request["drug_ids"] = [uid()]
    with pytest.raises(PharmaError):
        create_run(repo, principal, request)
    repo, principal, request = setup_case()
    request["runtime_mode"] = "replay"
    with pytest.raises(PharmaError):
        create_run(repo, principal, request)


def test_reader_cannot_start_run():
    repo, principal, request = setup_case()
    reader = Principal(principal.user, {}, repo.workspace_id, "reader")
    with pytest.raises(PharmaError):
        create_run(repo, reader, request)


def test_event_sequence_allocated_under_run_lock():
    repo, principal, request = setup_case()
    run = create_run(repo, principal, request)
    event = append_event(repo, run["id"], "run.started", {})
    assert event["seq"] == 2
    assert ("research_run", run["id"]) in repo.locked
    assert repo.get("research_run", run["id"])["next_event_seq"] == 2


def test_lease_owner_and_expiration_fence_writes():
    repo, principal, request = setup_case()
    run = create_run(repo, principal, request)
    token = uid()
    repo.update("job", run["job_id"], state="running", owner_token=token, lease_expires_at=(now() + timedelta(minutes=2)).isoformat())
    lease_fence(repo, run["job_id"], token)
    with pytest.raises(PharmaError, match="租约"):
        lease_fence(repo, run["job_id"], uid())
    repo.update("job", run["job_id"], lease_expires_at=(now() - timedelta(seconds=1)).isoformat())
    with pytest.raises(PharmaError, match="租约"):
        lease_fence(repo, run["job_id"], token)


def test_future_snapshot_and_pending_mapping_never_enter_scope():
    repo, principal, request = setup_case()
    run = create_run(repo, principal, request)
    old = (now() - timedelta(days=1)).isoformat()
    future = (now() + timedelta(days=1)).isoformat()
    record = repo.add("source_record", source="ctgov", external_id="DEMO-CT-001")
    link = repo.add("entity_link", record_id=record["id"], drug_id=request["drug_ids"][0], status="pending")
    past = repo.add("source_snapshot", record_id=record["id"], first_observed_at=old, normalized={})
    repo.add("source_snapshot", record_id=record["id"], first_observed_at=future, normalized={})
    assert snapshots_in_scope(repo, run) == []
    repo.update("entity_link", link["id"], status="approved")
    assert [item["id"] for item in snapshots_in_scope(repo, run)] == [past["id"]]


def test_historical_run_clamps_knowledge_cutoff_to_exclusive_window_end():
    repo, principal, request = setup_case()
    request["time_range"]["end_exclusive"] = "2026-09-17T00:00:00Z"
    run = create_run(repo, principal, request)
    assert run["research_state"]["scope"]["knowledge_cutoff"] == "2026-09-17T00:00:00+00:00"
    record = repo.add("source_record", source="ctgov", external_id="DEMO-CT-001")
    repo.add("entity_link", record_id=record["id"], drug_id=request["drug_ids"][0], status="approved")
    repo.add("source_snapshot", record_id=record["id"], first_observed_at="2026-09-17T00:00:00+00:00", normalized={})
    assert snapshots_in_scope(repo, run) == []


def test_disabled_source_is_a_failed_coverage_not_empty_success():
    from app.pharma.research import DomainTools, build_replay_draft

    repo, principal, request = setup_case()
    run = create_run(repo, principal, request)
    repo.update("workspace", repo.workspace_id, settings={"data_mode": "demo", "sources": {"ctgov": False}})
    tools = DomainTools(repo.get("job", run["job_id"]), uid())
    result = tools.dispatch(repo, run, principal, "search_trials", {"drug_id": request["drug_ids"][0]})
    assert result["ok"] is False
    assert result["error"]["code"] == "SOURCE_DISABLED"
    assert result["coverage"][0]["status"] == "failed"
    draft, _ = build_replay_draft(repo, run)
    assert next(item for item in draft["coverage"] if item["source"] == "ctgov")["status"] == "failed"
