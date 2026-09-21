"""Real PostgreSQL boundaries in an isolated, disposable test schema.

Opt in with PHARMA_TEST_DATABASE_URL pointing to a database ending in ``_test``.
No production data is truncated; each case rolls back and the fixture only drops
the randomly named schema it created itself.
"""

import copy
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.requests import Request
from starlette.responses import Response
from support.pharma import database as database
from support.pharma import repo as repo

from app.pharma import db
from app.pharma.domain import ingest, verify_evidence
from app.pharma.errors import PharmaError
from app.pharma.seed import fixture, seed

pytestmark = pytest.mark.integration


def _trial(repo):
    return repo.rows("source_record", source="ctgov", external_id="DEMO-CT-001")[0]


def _other_workspace(repo):
    workspace = repo.add("workspace", name="Isolated synthetic workspace", settings={"data_mode": "demo"})
    return db.Repository(repo.connection, workspace["id"])


def _envelope(index=0):
    snapshot = copy.deepcopy(fixture("02-trial-snapshots.json")[index])
    return {**snapshot, "source": "ctgov", "external_id": "DEMO-CT-001", "record_type": "trial", "url": "demo://DEMO-CT-001"}


@pytest.fixture
def auth_session(repo, monkeypatch):
    from app.pharma import auth

    scoped, actor = repo

    @contextmanager
    def same_transaction(workspace_id=None):
        yield db.Repository(scoped.connection, workspace_id)

    monkeypatch.setattr(auth, "transaction", same_transaction)
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    session = scoped.add("app_session", user_id=actor, token_hash=db.text_hash(token), csrf_hash=db.text_hash(csrf), expires_at=db.now() + timedelta(hours=1))
    return auth, scoped, actor, session, token, csrf


def _request(token="", method="GET", **headers):
    values = {"host": "testserver", **headers}
    if token:
        values["cookie"] = "pharma_session=" + token
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": "/api/pharma/v1/auth/me",
            "raw_path": b"/api/pharma/v1/auth/me",
            "root_path": "",
            "query_string": b"",
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 12345),
            "headers": [(key.encode(), value.encode()) for key, value in values.items()],
        }
    )


def test_migrations_are_repeatable_and_include_immutable_triggers(database):
    with database.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one().startswith("pharma_")
        triggers = connection.execute(text("SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema = current_schema()")).scalars().all()
        assert {"immutable_source_snapshot", "immutable_evidence", "immutable_report_version", "immutable_review"} <= set(triggers)


def test_d1_to_d5_preserves_baseline_repeated_observation_and_content_reversion(repo):
    scoped, actor = repo
    seed(scoped, actor, 1)
    first_record = _trial(scoped)
    first_snapshot = first_record["current_snapshot_id"]
    assert len(scoped.rows("source_snapshot")) == 1
    assert scoped.rows("source_observation")[0]["outcome"] == "baseline"
    assert scoped.rows("event_revision") == []

    seed(scoped, actor, 2)
    assert len(scoped.rows("source_snapshot")) == 1
    assert len(scoped.rows("source_observation")) == 2
    assert scoped.rows("event_revision") == []

    seed(scoped, actor, 3)
    assert len(scoped.rows("source_snapshot")) == 2
    assert len(scoped.rows("source_observation")) == 3
    assert {event["category"] for event in scoped.rows("intelligence_event")} == {"status", "enrollment"}
    assert len(scoped.rows("event_revision")) == 2
    for revision in scoped.rows("event_revision"):
        assert revision["before_observation_id"] != revision["after_observation_id"]
        assert len(revision["evidence_ids"]) == 2
        for evidence_id in revision["evidence_ids"]:
            verify_evidence(scoped, evidence_id, "2026-09-16T23:59:59+00:00")

    seed(scoped, actor, 4)
    assert _trial(scoped)["current_projection"]["enrollment"] == {"count": 150, "type": "estimated"}
    assert len(scoped.rows("source_record", source="pubmed")) == 1
    assert len(scoped.rows("source_snapshot", record_id=first_record["id"])) == 3

    seed(scoped, actor, 5)
    current = _trial(scoped)
    assert current["current_snapshot_id"] == first_snapshot
    assert current["current_projection"]["enrollment"] == {"count": 120, "type": "estimated"}
    assert len(scoped.rows("source_snapshot", record_id=current["id"])) == 3
    observations = scoped.rows("source_observation", record_id=current["id"], order=scoped.table("source_observation").c.observation_seq)
    assert [row["observation_seq"] for row in observations] == [1, 2, 3, 4, 5]
    assert [row["outcome"] for row in observations] == ["baseline", "unchanged", "changed", "changed", "changed"]
    assert observations[-1]["snapshot_id"] == observations[0]["snapshot_id"]
    reversions = scoped.rows("event_revision", after_observation_id=observations[-1]["id"])
    assert len(reversions) == 2
    assert all(item["severity"] == "correction" for item in reversions)


def test_replayed_days_are_idempotent_and_do_not_ingest_future_documents(repo):
    scoped, actor = repo
    seed(scoped, actor, 3)
    counts = {name: len(scoped.rows(name)) for name in ["source_record", "source_snapshot", "source_observation", "event_revision", "evidence"]}
    seed(scoped, actor, 3)
    assert {name: len(scoped.rows(name)) for name in counts} == counts
    assert scoped.rows("source_record", source="pubmed") == []
    assert all(datetime.fromisoformat(row["first_observed_at"]) <= datetime(2026, 9, 16, 8, tzinfo=UTC) for row in scoped.rows("source_snapshot"))


def test_same_fictional_fixture_can_be_loaded_into_two_isolated_workspaces(repo):
    scoped, actor = repo
    other = _other_workspace(scoped)
    other.add("membership", user_id=actor, role="analyst")
    seed(scoped, actor, 3)
    seed(other, actor, 3)
    assert len(other.rows("drug")) == len(scoped.rows("drug")) == 2
    assert {item["id"] for item in other.rows("drug")}.isdisjoint({item["id"] for item in scoped.rows("drug")})
    assert _trial(other)["id"] != _trial(scoped)["id"]
    assert len(other.rows("source_observation")) == len(scoped.rows("source_observation")) == 3


def test_seed_refuses_live_workspace(repo):
    scoped, actor = repo
    scoped.update("workspace", scoped.workspace_id, settings={"data_mode": "live"})
    with pytest.raises(PharmaError) as caught:
        seed(scoped, actor, 1)
    assert caught.value.code == "DEMO_ONLY"
    assert scoped.rows("drug") == []


def test_workspace_scoping_hides_objects_and_overrides_supplied_workspace(repo):
    scoped, actor = repo
    seed(scoped, actor, 1)
    other = _other_workspace(scoped)
    with pytest.raises(PharmaError) as caught:
        other.get("source_record", _trial(scoped)["id"])
    assert caught.value.status == 404
    created = other.add("drug", workspace_id=scoped.workspace_id, display_name="Scope injection is ignored")
    assert created["workspace_id"] == other.workspace_id
    assert scoped.rows("drug", id=created["id"]) == []


def test_composite_foreign_key_rejects_cross_workspace_snapshot_evidence(repo):
    scoped, actor = repo
    seed(scoped, actor, 1)
    other = _other_workspace(scoped)
    snapshot_id = _trial(scoped)["current_snapshot_id"]
    with pytest.raises(IntegrityError), scoped.connection.begin_nested():
        other.add("evidence", snapshot_id=snapshot_id, locator={"kind": "json_pointer", "path": "/normalized/status"}, quoted_text="RECRUITING", snippet_hash=db.text_hash("RECRUITING"), original_language="en", extractor_version="test")
    assert other.rows("evidence") == []


def test_composite_foreign_key_rejects_cross_workspace_current_pointer(repo):
    scoped, actor = repo
    seed(scoped, actor, 1)
    other = _other_workspace(scoped)
    record = other.add("source_record", source="ctgov", external_id="DEMO-OTHER", kind="trial", canonical_url="demo://DEMO-OTHER", is_demo=True)
    with pytest.raises(IntegrityError), scoped.connection.begin_nested():
        other.update("source_record", record["id"], current_snapshot_id=_trial(scoped)["current_snapshot_id"])
    assert other.get("source_record", record["id"])["current_snapshot_id"] is None


@pytest.mark.parametrize("name", ["source_snapshot", "source_observation", "evidence", "event_revision"])
@pytest.mark.parametrize("action", ["update", "delete"])
def test_database_rejects_rewriting_or_deleting_versioned_evidence(repo, name, action):
    scoped, actor = repo
    seed(scoped, actor, 3)
    row = scoped.rows(name)[0]
    table = scoped.table(name)
    statement = table.update().values(created_at=db.now()) if action == "update" else table.delete()
    with pytest.raises(DBAPIError, match="immutable"), scoped.connection.begin_nested():
        scoped.connection.execute(statement.where(table.c.id == row["id"]))
    assert scoped.get(name, row["id"]) == row


@pytest.mark.parametrize("name", ["report_version", "claim", "claim_evidence", "review", "run_event", "audit_log"])
@pytest.mark.parametrize("action", ["update", "delete"])
def test_database_preserves_signed_reports_review_and_audit_history(repo, name, action):
    scoped, actor = repo
    seed(scoped, actor, 1)
    run = scoped.add("research_run", created_by=actor, question="Synthetic history integrity case", runtime_mode="replay", frozen_request={}, prompt_version="test")
    report = scoped.add("report", run_id=run["id"], created_by=actor, title="Synthetic report")
    content = {"synthetic": True}
    version = scoped.add("report_version", report_id=report["id"], version_no=1, created_by=actor, content_json=content, content_hash=db.digest(content), runtime_mode="replay")
    claim = scoped.add("claim", report_version_id=version["id"], claim_key="C1", statement="Synthetic source field", category="fact", verification_status="unverified", numeric_check="not_applicable")
    scoped.add("claim_evidence", claim_id=claim["id"], evidence_id=scoped.rows("evidence")[0]["id"], relation="context")
    reviewer = scoped.add("app_user", email=f"{uuid4().hex}@pharma-test.invalid", display_name="Synthetic reviewer", password_hash="not-a-login-credential")
    scoped.add("review", report_id=report["id"], version_id=version["id"], reviewer_id=reviewer["id"], content_hash=db.digest(content), decision="approve", note="Synthetic integrity test")
    scoped.add("run_event", run_id=run["id"], seq=1, type="run.queued", occurred_at=db.now())
    scoped.audit(actor, "synthetic_integrity_check", "research_run", run["id"])
    row = scoped.rows(name)[0]
    table = scoped.table(name)
    statement = table.update().values(created_at=db.now()) if action == "update" else table.delete()
    with pytest.raises(DBAPIError, match="immutable"), scoped.connection.begin_nested():
        scoped.connection.execute(statement.where(table.c.id == row["id"]))
    assert scoped.get(name, row["id"]) == row


def test_evidence_tampering_and_future_cutoff_fail_verification(repo):
    scoped, actor = repo
    seed(scoped, actor, 4)
    record = _trial(scoped)
    tampered = scoped.add(
        "evidence", snapshot_id=record["current_snapshot_id"], locator={"kind": "json_pointer", "path": "/normalized/status"}, quoted_text="APPROVED", snippet_hash=db.text_hash("APPROVED"), original_language="en", extractor_version="test"
    )
    with pytest.raises(PharmaError) as caught:
        verify_evidence(scoped, tampered["id"])
    assert caught.value.code == "EVIDENCE_INVALID"
    current = next(item for item in scoped.rows("evidence", snapshot_id=record["current_snapshot_id"]) if item["id"] != tampered["id"])
    with pytest.raises(PharmaError) as caught:
        verify_evidence(scoped, current["id"], "2026-09-16T23:59:59Z")
    assert caught.value.code == "EVIDENCE_INVALID"


def test_estimated_to_actual_is_a_change_even_with_same_count(repo):
    scoped, _ = repo
    envelope = _envelope()
    ingest(scoped, envelope, "estimated", observed_at="2026-09-14T08:00:00Z")
    changed = copy.deepcopy(envelope)
    changed["normalized"]["enrollment"]["type"] = "actual"
    changed["raw_payload"]["projection"]["enrollment"]["type"] = "actual"
    _, _, revisions = ingest(scoped, changed, "actual", observed_at="2026-09-15T08:00:00Z")
    assert len(revisions) == 1
    difference = revisions[0]["changes"][0]
    assert difference["path"] == "/enrollment"
    assert difference["before"] == {"count": 120, "type": "estimated"}
    assert difference["after"] == {"count": 120, "type": "actual"}


def test_removed_enrollment_stays_missing_in_projection_and_evidence(repo):
    scoped, _ = repo
    envelope = _envelope()
    ingest(scoped, envelope, "present", observed_at="2026-09-14T08:00:00Z")
    changed = copy.deepcopy(envelope)
    del changed["normalized"]["enrollment"]
    del changed["raw_payload"]["projection"]["enrollment"]
    record, _, revisions = ingest(scoped, changed, "missing", observed_at="2026-09-15T08:00:00Z")
    assert "enrollment" not in record["current_projection"]
    assert revisions[0]["changes"] == [{"path": "/enrollment", "type": "removed", "before": {"count": 120, "type": "estimated"}, "after": None}]
    assert len(revisions[0]["evidence_ids"]) == 1
    assert all(item["locator"]["path"] != "/normalized/enrollment" for item in scoped.rows("evidence", snapshot_id=record["current_snapshot_id"]))


def test_auth_role_comes_from_membership_and_cross_workspace_is_hidden(auth_session):
    auth, scoped, actor, _, token, _ = auth_session
    principal = auth.authenticate(_request(token, **{"x-pharma-role": "admin"}), scoped.workspace_id)
    assert principal.user_id == actor
    assert principal.role == "analyst"
    with pytest.raises(PharmaError) as caught:
        principal.require_role("admin")
    assert caught.value.status == 403
    other = _other_workspace(scoped)
    with pytest.raises(PharmaError) as caught:
        auth.authenticate(_request(token), other.workspace_id)
    assert caught.value.status == 404


@pytest.mark.parametrize("condition", ["session_revoked", "session_expired", "user_disabled", "membership_disabled"])
def test_auth_rechecks_revocation_for_each_request(auth_session, condition):
    auth, scoped, actor, session, token, _ = auth_session
    assert auth.authenticate(_request(token), scoped.workspace_id).user_id == actor
    if condition == "session_revoked":
        scoped.update("app_session", session["id"], revoked_at=db.now())
    elif condition == "session_expired":
        scoped.update("app_session", session["id"], expires_at=db.now() - timedelta(seconds=1))
    elif condition == "user_disabled":
        scoped.update("app_user", actor, is_active=False)
    else:
        membership = scoped.table("membership")
        scoped.connection.execute(membership.update().where(membership.c.workspace_id == scoped.workspace_id, membership.c.user_id == actor).values(enabled=False))
    with pytest.raises(PharmaError) as caught:
        auth.authenticate(_request(token), scoped.workspace_id)
    assert caught.value.status == (404 if condition == "membership_disabled" else 401)


@pytest.mark.parametrize("headers", [{}, {"x-csrf-token": "invented"}, {"origin": "https://untrusted.invalid"}, {"sec-fetch-site": "cross-site"}])
def test_auth_mutations_require_bound_csrf_and_trusted_origin(auth_session, headers):
    auth, scoped, _, _, token, csrf = auth_session
    request_headers = headers if not headers or "x-csrf-token" in headers else {"x-csrf-token": csrf, **headers}
    with pytest.raises(PharmaError) as caught:
        auth.authenticate(_request(token, "POST", **request_headers), scoped.workspace_id)
    assert caught.value.code == "CSRF_FAILED"
    assert auth.authenticate(_request(token, "POST", **{"x-csrf-token": csrf, "origin": "https://testserver"}), scoped.workspace_id).role == "analyst"


def test_login_stores_only_token_hashes_and_sets_secure_http_only_session(auth_session):
    auth, scoped, actor, _, _, _ = auth_session
    password = secrets.token_urlsafe(24)
    user = scoped.update("app_user", actor, password_hash=auth.PASSWORDS.hash(password))
    response = Response()
    result = auth.login(_request(method="POST", origin="https://testserver"), response, {"email": user["email"], "password": password})
    cookies = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        cookies.load(header)
    session_cookie = cookies["pharma_session"]
    assert session_cookie["secure"] and session_cookie["httponly"]
    assert session_cookie["samesite"] == "lax"
    assert session_cookie["path"] == "/api/pharma"
    stored = scoped.rows("app_session", token_hash=db.text_hash(session_cookie.value))
    assert len(stored) == 1
    assert stored[0]["token_hash"] != session_cookie.value
    assert stored[0]["csrf_hash"] == db.text_hash(result["csrf_token"])
    assert result["user"]["id"] == actor
    assert "password_hash" not in result["user"]
