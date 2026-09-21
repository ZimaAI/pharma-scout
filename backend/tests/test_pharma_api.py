"""Executable API contracts and complete research/review journey on isolated PG."""

import asyncio
import copy
from contextlib import contextmanager
from datetime import timedelta

import jsonschema
import pytest
import test_pharma_persistence as _persistence
from fastapi.testclient import TestClient

from app.pharma import auth, db, main, research, subscriptions
from app.pharma.contract import specification
from app.pharma.seed import seed

pytestmark = pytest.mark.integration
database = _persistence.database
repo = _persistence.repo


@pytest.fixture
def api_case(repo, monkeypatch):
    scoped, actor = repo
    seed(scoped, actor, 3)
    password = "Synthetic-password-only-in-tests!"
    hashed = auth.PASSWORDS.hash(password)
    analyst = scoped.update("app_user", actor, password_hash=hashed)
    people = {"analyst": analyst}
    for role in ("reviewer", "reader"):
        user = scoped.add("app_user", email=f"{db.uid()}@api-test.invalid", display_name=role, password_hash=hashed)
        scoped.add("membership", user_id=user["id"], role=role)
        people[role] = user

    @contextmanager
    def same_transaction(workspace_id=None):
        yield db.Repository(scoped.connection, workspace_id)

    for module in (auth, main, research, subscriptions):
        monkeypatch.setattr(module, "transaction", same_transaction)
    clients = {}
    for role, user in people.items():
        client = TestClient(main.app, base_url="https://testserver")
        response = client.post("/api/pharma/v1/auth/login", json={"email": user["email"], "password": password}, headers={"origin": "https://testserver"})
        assert response.status_code == 200, response.text
        client.headers.update({"x-csrf-token": response.json()["csrf_token"], "origin": "https://testserver"})
        clients[role] = client
    yield scoped, people, clients
    for client in clients.values():
        client.close()


def route(operation, workspace_id, **params):
    for path, methods in specification()["paths"].items():
        for definition in methods.values():
            if isinstance(definition, dict) and definition.get("operationId") == operation:
                return path.format(workspace_id=workspace_id, **params)
    raise AssertionError(f"Unknown operation: {operation}")


def assert_schema(response, name, status=200):
    assert response.status_code == status, response.text
    root = specification()
    schema = {"$ref": f"#/components/schemas/{name}", "components": root["components"]}
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(response.json())
    return response.json()


def start_replay(scoped, clients):
    drug = next(item for item in scoped.rows("drug") if item["development_code"] == "PX-101")
    body = {
        "question": "核对公开试验注册记录的变化及原始证据",
        "drug_ids": [drug["id"]],
        "time_range": {"start": "2026-09-14T00:00:00Z", "end_exclusive": "2026-09-21T00:00:00Z", "timezone": "Asia/Shanghai"},
        "source_allowlist": ["ctgov", "pubmed"],
    }
    path = route("runs_create", scoped.workspace_id)
    key = "api-replay-" + db.uid()
    response = clients["analyst"].post(path, json=body, headers={"idempotency-key": key})
    run = assert_schema(response, "ResearchRun", 202)
    repeated = clients["analyst"].post(path, json=body, headers={"idempotency-key": key})
    assert repeated.json()["id"] == run["id"]
    assert len(scoped.rows("research_run")) == 1
    stored = scoped.get("research_run", run["id"])
    token = db.uid()
    job = scoped.update("job", stored["job_id"], state="running", owner_token=token, lease_expires_at=db.now() + timedelta(minutes=5))
    asyncio.run(research.execute_research(job, token))
    finished = assert_schema(clients["analyst"].get(route("runs_get", scoped.workspace_id, run_id=run["id"])), "ResearchRun")
    assert finished["status"] == "completed"
    assert finished["runtime_mode"] == "replay"
    report = assert_schema(clients["analyst"].get(route("reports_get", scoped.workspace_id, report_id=finished["report_id"])), "Report")
    version = assert_schema(clients["analyst"].get(route("reports_version_get", scoped.workspace_id, report_id=report["id"], version_id=report["current_version_id"])), "ReportVersion")
    return finished, report, version


def test_full_replay_edit_independent_review_publish_inbox_and_sse(api_case):
    scoped, people, clients = api_case
    run, report, version = start_replay(scoped, clients)
    params = {"workspace_id": scoped.workspace_id, "report_id": report["id"]}
    assert clients["reader"].get(route("reports_get", **params)).status_code == 404
    action = {"version_id": version["id"], "content_hash": version["content_hash"]}
    assert clients["analyst"].post(route("reports_submit_review", **params), json=action).status_code == 200

    # Grant the creator reviewer role to exercise independent-author enforcement,
    # rather than merely failing because analysts have no review permission.
    membership = scoped.table("membership")
    predicate = (membership.c.workspace_id == scoped.workspace_id) & (membership.c.user_id == people["analyst"]["id"])
    scoped.connection.execute(membership.update().where(predicate).values(role="reviewer"))
    decision = {**action, "decision": "approve", "note": "核对演示来源与字段变化。"}
    self_review = clients["analyst"].post(route("reviews_decide", **params), json=decision)
    assert self_review.status_code == 403
    assert self_review.json()["error"]["code"] == "SELF_REVIEW_FORBIDDEN"
    scoped.connection.execute(membership.update().where(predicate).values(role="analyst"))
    assert_schema(clients["reviewer"].post(route("reviews_decide", **params), json=decision), "Review", 201)

    edited = copy.deepcopy(version["content"])
    edited["title"] += "（核对版）"
    new_version = assert_schema(clients["analyst"].post(route("reports_new_version", **params), json={"base_version_id": version["id"], "content": edited, "edit_note": "补充核对说明"}), "ReportVersion", 201)
    assert new_version["version_no"] == 2
    stale = clients["analyst"].post(route("reports_publish", **params), json=action, headers={"idempotency-key": "publish-old-" + db.uid()})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_VERSION"
    action = {"version_id": new_version["id"], "content_hash": new_version["content_hash"]}
    wrong = clients["analyst"].post(route("reports_submit_review", **params), json={**action, "content_hash": "0" * 64})
    assert wrong.status_code == 409
    assert clients["analyst"].post(route("reports_submit_review", **params), json=action).status_code == 200
    assert clients["reviewer"].post(route("reviews_decide", **params), json={**action, "decision": "approve", "note": "独立核对指定版本及证据，演示限定已保留。"}).status_code == 201
    key = "publish-current-" + db.uid()
    published = assert_schema(clients["analyst"].post(route("reports_publish", **params), json=action, headers={"idempotency-key": key}), "Report")
    assert published["published_version_id"] == new_version["id"]
    assert clients["analyst"].post(route("reports_publish", **params), json=action, headers={"idempotency-key": key}).status_code == 200
    assert len(scoped.rows("delivery")) == 1
    assert subscriptions.process_deliveries(scoped.workspace_id)["accepted"] == 1
    inbox = clients["analyst"].get(route("inbox_list", scoped.workspace_id))
    assert inbox.status_code == 200, inbox.text
    assert len(inbox.json()["items"]) == 1
    assert clients["reader"].get(route("inbox_list", scoped.workspace_id)).json()["items"] == []
    assert_schema(clients["reader"].get(route("reports_get", **params)), "Report")

    events_url = route("runs_stream", scoped.workspace_id, run_id=run["id"])
    streamed = clients["analyst"].get(events_url, headers={"last-event-id": "1"})
    assert streamed.status_code == 200
    assert "event: run.completed" in streamed.text
    assert "id: 1\n" not in streamed.text
    assert "event: report.ready" in streamed.text
    assert clients["reader"].get(events_url).status_code == 404


def test_api_mutation_csrf_cross_workspace_and_unknown_evidence(api_case):
    scoped, _, clients = api_case
    run, report, version = start_replay(scoped, clients)
    path = route("reports_submit_review", scoped.workspace_id, report_id=report["id"])
    action = {"version_id": version["id"], "content_hash": version["content_hash"]}
    bad_csrf = clients["analyst"].post(path, json=action, headers={"x-csrf-token": "invented"})
    assert bad_csrf.status_code == 403
    assert bad_csrf.json()["error"]["code"] == "CSRF_FAILED"
    assert clients["analyst"].get(route("runs_get", db.uid(), run_id=run["id"])).status_code == 404
    content = copy.deepcopy(version["content"])
    content["claims"][0]["evidence_links"][0]["evidence_id"] = db.uid()
    invalid = clients["analyst"].post(route("reports_new_version", scoped.workspace_id, report_id=report["id"]), json={"base_version_id": version["id"], "content": content, "edit_note": "Synthetic unknown citation"})
    assert invalid.status_code in {404, 422}
    assert len(scoped.rows("report_version", report_id=report["id"])) == 1


def test_list_filters_use_contract_query_and_only_approved_aliases(api_case):
    scoped, people, clients = api_case
    client = clients["analyst"]
    drugs_url = route("drugs_list", scoped.workspace_id)
    drug = next(item for item in scoped.rows("drug") if item["development_code"] == "PX-101")
    for status, alias in [("approved", "Synthetic approved alternate name"), ("pending", "Synthetic pending alternate name")]:
        scoped.add("drug_alias", drug_id=drug["id"], alias=alias, normalized_alias=alias.casefold(), namespace="development_code", note="Synthetic filter fixture", status=status, proposed_by=people["analyst"]["id"])
    for query in ["PX-101", "approved alternate"]:
        page = assert_schema(client.get(drugs_url, params={"query": query}), "DrugPage")
        assert [item["id"] for item in page["items"]] == [drug["id"]]
    for query in ["NO-MATCH-DRUG", "pending alternate"]:
        assert client.get(drugs_url, params={"query": query}).json()["items"] == []

    trials_url = route("trials_list", scoped.workspace_id)
    trials = scoped.rows("source_record", kind="trial")
    assert len(trials) == 1
    for query in [trials[0]["external_id"], trials[0]["current_projection"]["title"]]:
        result = client.get(trials_url, params={"query": query})
        assert result.status_code == 200, result.text
        assert [item["id"] for item in result.json()["items"]] == [trials[0]["id"]]
    assert client.get(trials_url, params={"query": "NO-MATCH-TRIAL"}).json()["items"] == []
    after = client.get(trials_url, params={"observed_since": "2026-09-17T00:00:00Z"})
    assert after.status_code == 200, after.text
    assert after.json()["items"] == []
    during = client.get(trials_url, params={"observed_since": "2026-09-15T00:00:00Z"})
    assert during.status_code == 200, during.text
    assert len(during.json()["items"]) == 1
    events = client.get(route("events_list", scoped.workspace_id), params={"observed_since": "2026-09-17T00:00:00Z"})
    assert events.status_code == 200, events.text
    assert events.json()["items"] == []


def test_run_status_filter_and_queued_cancel_are_terminal_and_idempotent(api_case):
    scoped, _, clients = api_case
    client = clients["analyst"]
    completed, _, _ = start_replay(scoped, clients)
    response = client.post(route("runs_create", scoped.workspace_id), json=completed["frozen_request"], headers={"idempotency-key": "queued-cancel-" + db.uid()})
    queued = assert_schema(response, "ResearchRun", 202)
    runs_url = route("runs_list", scoped.workspace_id)
    assert [item["id"] for item in client.get(runs_url, params={"status": "queued"}).json()["items"]] == [queued["id"]]
    assert [item["id"] for item in client.get(runs_url, params={"status": "completed"}).json()["items"]] == [completed["id"]]
    assert client.get(runs_url, params={"status": "failed"}).json()["items"] == []
    cancel_url = route("runs_cancel", scoped.workspace_id, run_id=queued["id"])
    cancelled = assert_schema(client.post(cancel_url), "ResearchRun", 202)
    assert cancelled["status"] == "cancelled"
    stored = scoped.get("research_run", queued["id"])
    assert scoped.get("job", stored["job_id"])["state"] == "cancelled"
    assert len(scoped.rows("run_event", run_id=queued["id"], type="run.cancelled")) == 1
    assert client.post(cancel_url).json()["status"] == "cancelled"
    assert len(scoped.rows("run_event", run_id=queued["id"], type="run.cancelled")) == 1
    assert client.get(runs_url, params={"status": "queued"}).json()["items"] == []
    stream = client.get(route("runs_stream", scoped.workspace_id, run_id=queued["id"]))
    assert stream.status_code == 200
    assert "event: run.cancelled" in stream.text


def test_cursor_valid_page_and_scope_filters_are_enforced(api_case):
    scoped, people, clients = api_case
    client = clients["analyst"]
    path = route("drugs_list", scoped.workspace_id)
    first = assert_schema(client.get(path, params={"limit": 1}), "DrugPage")
    assert first["has_more"] is True
    cursor = first["next_cursor"]
    second = assert_schema(client.get(path, params={"limit": 1, "cursor": cursor}), "DrugPage")
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert second["has_more"] is False
    assert client.get(path, params={"query": "PX-101", "cursor": cursor}).status_code == 422

    other = scoped.add("workspace", name="Synthetic second pagination scope", settings={"data_mode": "demo"})
    foreign_repo = db.Repository(scoped.connection, other["id"])
    foreign_repo.add("membership", user_id=people["analyst"]["id"], role="analyst")
    assert client.get(route("drugs_list", other["id"]), params={"cursor": cursor}).status_code == 422


@pytest.mark.parametrize("cursor", ["invalid-base64!", "W10=", "e30="])
def test_malformed_cursor_is_validation_error(api_case, cursor):
    scoped, _, clients = api_case
    response = clients["analyst"].get(route("drugs_list", scoped.workspace_id), params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_cursor_timestamp_is_validated_before_database_query(api_case):
    import base64
    import json

    scoped, _, clients = api_case
    path = route("drugs_list", scoped.workspace_id)
    cursor = clients["analyst"].get(path, params={"limit": 1}).json()["next_cursor"]
    decoded = json.loads(base64.urlsafe_b64decode(cursor))
    decoded["created_at"] = "not-a-timestamp"
    corrupt = base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode()
    response = clients["analyst"].get(path, params={"cursor": corrupt})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
