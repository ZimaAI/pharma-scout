"""Subscription scheduling and durable delivery semantics, using synthetic data."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from support.pharma import database as database
from support.pharma import repo as repo

from app.pharma import db, subscriptions
from app.pharma.errors import PharmaError
from app.pharma.seed import seed
from app.pharma.subscriptions import preview_schedule


def schedule(local_time="09:00", timezone="Asia/Shanghai", frequency="daily", weekday=None):
    return {"frequency": frequency, "local_time": local_time, "weekday": weekday, "timezone": timezone}


def test_daily_schedule_keeps_timezone_and_utc_distinct():
    result = preview_schedule(schedule(), after=datetime(2026, 9, 21, 1, 0, tzinfo=UTC))
    assert len(result["occurrences"]) == 5
    assert result["occurrences"][0] == {"utc": "2026-09-22T01:00:00Z", "local": "2026-09-22T09:00:00+08:00", "dst_adjusted": False}


def test_dst_gap_advances_to_first_valid_minute():
    result = preview_schedule(schedule("02:30", "America/Los_Angeles"), after=datetime(2026, 3, 8, 0, 0, tzinfo=UTC), count=1)
    assert result["occurrences"] == [{"utc": "2026-03-08T10:00:00Z", "local": "2026-03-08T03:00:00-07:00", "dst_adjusted": True}]


def test_dst_fold_chooses_first_occurrence_and_never_second():
    plan = schedule("01:30", "America/Los_Angeles")
    first = preview_schedule(plan, after=datetime(2026, 11, 1, 0, 0, tzinfo=UTC), count=1)["occurrences"][0]
    assert first["utc"] == "2026-11-01T08:30:00Z"
    second = preview_schedule(plan, after=datetime(2026, 11, 1, 8, 45, tzinfo=UTC), count=1)["occurrences"][0]
    assert second["utc"] == "2026-11-02T09:30:00Z"


def test_weekly_uses_iso_weekday_including_sunday():
    result = preview_schedule(schedule(frequency="weekly", weekday=7), after=datetime(2026, 9, 21, tzinfo=UTC), count=1)
    assert result["occurrences"][0]["local"].startswith("2026-09-27T09:00:00")


@pytest.mark.parametrize("bad", [schedule(timezone="Mars/Olympus"), schedule(local_time="25:00"), schedule(frequency="weekly", weekday=0), schedule(weekday=1), {**schedule(), "recipient": "attacker@example.invalid"}])
def test_invalid_schedule_is_rejected(bad):
    with pytest.raises(PharmaError):
        preview_schedule(bad)


def _input(scoped, **overrides):
    return {"name": "Synthetic subscription", "drug_ids": [scoped.rows("drug")[0]["id"]], "source_allowlist": ["ctgov", "pubmed"], "schedule": schedule(), "channels": ["in_app"], "enabled": True, **overrides}


def _run(scoped, owner, body):
    return scoped.add("research_run", created_by=owner, question=body.get("question", "Synthetic research question"), runtime_mode="replay", frozen_request=body, prompt_version="synthetic-test")


def _delivery(scoped, actor, subscription, channel="in_app"):
    run = _run(scoped, actor, {})
    report = scoped.add("report", run_id=run["id"], created_by=actor, title="Synthetic report")
    version = scoped.add("report_version", report_id=report["id"], version_no=1, created_by=actor, content_json={"title": "Synthetic report"}, content_hash=db.digest({"title": "Synthetic report"}), runtime_mode="replay")
    scoped.update("report", report["id"], state="published", current_version_id=version["id"], published_version_id=version["id"])
    return scoped.add(
        "delivery",
        report_version_id=version["id"],
        subscription_id=subscription["id"],
        recipient_user_id=actor,
        channel=channel,
        idempotency_key=f"{version['id']}:{actor}:{channel}",
        rendered_payload={"title": "[DEMO] Synthetic report", "report_id": report["id"], "version_id": version["id"], "runtime_mode": "replay"},
        covered_event_revisions=[row["id"] for row in scoped.rows("event_revision")],
    )


@pytest.fixture
def delivery_repo(repo, monkeypatch):
    scoped, actor = repo
    seed(scoped, actor, 3)

    @contextmanager
    def same_transaction(workspace_id=None):
        with scoped.connection.begin_nested():
            yield db.Repository(scoped.connection, workspace_id)

    monkeypatch.setattr(subscriptions, "transaction", same_transaction)
    monkeypatch.delenv("PHARMA_SMTP_ENABLED", raising=False)
    subscription = subscriptions.create_subscription(scoped, actor, _input(scoped))
    return scoped, actor, subscription


@pytest.mark.integration
class TestPersistence:
    def test_email_cannot_be_enabled_without_operator_configuration(self, repo, monkeypatch):
        scoped, actor = repo
        seed(scoped, actor, 1)
        monkeypatch.delenv("PHARMA_SMTP_ENABLED", raising=False)
        with pytest.raises(PharmaError) as exc:
            subscriptions.create_subscription(scoped, actor, _input(scoped, channels=["email"]))
        assert exc.value.code == "EMAIL_NOT_CONFIGURED"
        assert scoped.rows("subscription") == []

    def test_occurrence_is_unique_and_configuration_stays_frozen(self, delivery_repo):
        scoped, actor, subscription = delivery_repo
        at = datetime(2026, 9, 21, 1, tzinfo=UTC)
        first = subscriptions.trigger_subscription(scoped, subscription["id"], actor, scheduled_at=at, create_run=_run)
        repeated = subscriptions.trigger_subscription(scoped, subscription["id"], actor, scheduled_at=at, create_run=_run)
        assert first["id"] == repeated["id"]
        assert len(scoped.rows("research_run")) == 1
        subscriptions.update_subscription(scoped, subscription["id"], actor, _input(scoped, name="Edited future subscription", enabled=False), 1)
        frozen = scoped.get("schedule_occurrence", first["id"])["config_snapshot"]
        assert frozen["name"] == "Synthetic subscription"
        assert frozen["revision"] == 1
        assert frozen["non_interactive"] is True
        assert frozen["knowledge_cutoff"] == "2026-09-21T01:00:00Z"
        assert scoped.get("subscription", subscription["id"])["next_run_at"] is None
        assert scoped.get("research_run", first["run_id"])["status"] == "queued"
        with pytest.raises(PharmaError) as exc:
            subscriptions.update_subscription(scoped, subscription["id"], actor, _input(scoped), 1)
        assert exc.value.code == "STALE_VERSION"

    def test_downtime_only_catches_up_latest_occurrence(self, delivery_repo):
        scoped, _, subscription = delivery_repo
        scoped.update("subscription", subscription["id"], next_run_at=datetime(2026, 9, 1, 1, tzinfo=UTC))
        at = datetime(2026, 9, 21, 2, tzinfo=UTC)
        occurrences = subscriptions.scan_subscriptions(scoped, _run, at=at)
        assert len(occurrences) == 1
        assert subscriptions._utc(occurrences[0]["scheduled_at"]) == datetime(2026, 9, 21, 1, tzinfo=UTC)
        assert occurrences[0]["config_snapshot"]["skipped_window"] == {"from": "2026-09-01T01:00:00Z", "before": "2026-09-21T01:00:00Z"}
        assert subscriptions.scan_subscriptions(scoped, _run, at=at) == []

    def test_disabled_owner_cannot_execute_schedule(self, delivery_repo):
        scoped, actor, subscription = delivery_repo
        scoped.update("subscription", subscription["id"], next_run_at=datetime(2026, 9, 1, tzinfo=UTC))
        scoped.update("app_user", actor, is_active=False)
        assert subscriptions.scan_subscriptions(scoped, _run, at=datetime(2026, 9, 21, tzinfo=UTC)) == []
        assert scoped.get("subscription", subscription["id"])["last_outcome"] == "failed"
        assert scoped.rows("research_run") == []

    def test_in_app_acceptance_advances_cursors_once_and_never_marks_read(self, delivery_repo):
        scoped, actor, subscription = delivery_repo
        delivery = _delivery(scoped, actor, subscription)
        result = subscriptions.process_deliveries(scoped.workspace_id)
        assert result["accepted"] == 1
        row = scoped.get("delivery", delivery["id"])
        assert row["state"] == "accepted" and row["accepted_at"]
        assert row["read_at"] is None
        cursors = scoped.rows("subscription_cursor", subscription_id=subscription["id"])
        assert {cursor["last_accepted_revision_id"] for cursor in cursors} == set(delivery["covered_event_revisions"])
        assert subscriptions.process_deliveries(scoped.workspace_id)["processed"] == 0
        assert len(scoped.rows("delivery_attempt")) == 1

    def test_new_revisions_are_not_lost_and_complete_unchanged_is_no_change(self, delivery_repo):
        scoped, actor, subscription = delivery_repo
        delivery = _delivery(scoped, actor, subscription)
        subscriptions.process_deliveries(scoped.workspace_id)
        occurrence = subscriptions.trigger_subscription(scoped, subscription["id"], actor, create_run=_run)
        coverage = [{"source": source, "status": "complete", "truncated": False} for source in ["ctgov", "pubmed"]]
        assert subscriptions.pending_event_revision_ids(scoped, occurrence["run_id"], delivery["covered_event_revisions"]) == []
        assert subscriptions.finalize_occurrence(scoped, occurrence["run_id"], coverage, delivery["covered_event_revisions"]) == "no_change"
        coverage[1]["status"] = "failed"
        assert subscriptions.finalize_occurrence(scoped, occurrence["run_id"], coverage, delivery["covered_event_revisions"]) == "partial"
        before = set(delivery["covered_event_revisions"])
        seed(scoped, actor, 4)
        all_revisions = [row["id"] for row in scoped.rows("event_revision")]
        assert set(subscriptions.pending_event_revision_ids(scoped, occurrence["run_id"], all_revisions)) == set(all_revisions) - before

    def test_unknown_smtp_never_retries_or_advances(self, delivery_repo, monkeypatch):
        scoped, actor, subscription = delivery_repo
        monkeypatch.setattr(subscriptions, "email_available", lambda: True)
        calls = []

        def unknown(row):
            calls.append(row["id"])
            raise subscriptions.DeliveryFailure("SMTP_OUTCOME_UNKNOWN", unknown=True)

        monkeypatch.setattr(subscriptions, "_smtp_send", unknown)
        delivery = _delivery(scoped, actor, subscription, "email")
        subscriptions.process_deliveries(scoped.workspace_id)
        assert scoped.get("delivery", delivery["id"])["state"] == "unknown"
        assert scoped.rows("subscription_cursor") == []
        subscriptions.process_deliveries(scoped.workspace_id)
        assert calls == [delivery["id"]]

    def test_definite_connect_failure_retries_same_delivery_at_most_five_times(self, delivery_repo, monkeypatch):
        scoped, actor, subscription = delivery_repo
        monkeypatch.setattr(subscriptions, "email_available", lambda: True)

        def disconnected(_row):
            raise subscriptions.DeliveryFailure("SMTP_CONNECT_FAILED", retryable=True)

        monkeypatch.setattr(subscriptions, "_smtp_send", disconnected)
        delivery = _delivery(scoped, actor, subscription, "email")
        for attempt in range(1, 6):
            subscriptions.process_deliveries(scoped.workspace_id)
            row = scoped.get("delivery", delivery["id"])
            assert row["attempt_count"] == attempt
            if attempt < 5:
                assert row["state"] == "queued"
                assert subscriptions._utc(row["next_attempt_at"]) > db.now()
                scoped.update("delivery", delivery["id"], next_attempt_at=db.now() - timedelta(seconds=1))
            else:
                assert row["state"] == "failed"
        assert len(scoped.rows("delivery_attempt")) == 5
        assert scoped.rows("subscription_cursor") == []

    def test_expired_email_lease_becomes_unknown_and_stale_worker_is_fenced(self, delivery_repo, monkeypatch):
        scoped, actor, subscription = delivery_repo
        monkeypatch.setattr(subscriptions, "email_available", lambda: True)
        delivery = _delivery(scoped, actor, subscription, "email")
        claimed = subscriptions._claim_delivery(scoped.workspace_id)
        scoped.update("delivery", delivery["id"], lease_expires_at=db.now() - timedelta(seconds=1))
        assert subscriptions._finish_delivery(scoped.workspace_id, claimed) is False
        subscriptions.process_deliveries(scoped.workspace_id)
        assert scoped.get("delivery", delivery["id"])["state"] == "unknown"
        assert subscriptions._finish_delivery(scoped.workspace_id, claimed) is False
        assert scoped.rows("subscription_cursor") == []

    def test_retracted_reports_cannot_be_delivered(self, delivery_repo):
        scoped, actor, subscription = delivery_repo
        delivery = _delivery(scoped, actor, subscription)
        scoped.update("report", delivery["rendered_payload"]["report_id"], state="retracted", retracted_at=db.now())
        subscriptions.process_deliveries(scoped.workspace_id)
        assert scoped.get("delivery", delivery["id"])["state"] == "cancelled"
        assert scoped.rows("delivery_attempt") == []
