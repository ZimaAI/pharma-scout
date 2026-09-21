"""Timezone-aware subscriptions and a separately retryable delivery outbox.

Database operations are synchronous, as is the SMTP transport. Async callers
must invoke the worker entry points through their dedicated thread executor.
Research/model execution never happens inside this module or a DB transaction.
"""

from __future__ import annotations

import copy
import os
import random
import re
import smtplib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_

from .db import now, transaction, uid
from .errors import PharmaError, require

CreateRun = Callable[[Any, str, dict], dict]
MAX_DELIVERY_ATTEMPTS = 5
DELIVERY_LEASE = timedelta(minutes=2)


def _utc(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        # SQLite test repositories lose tzinfo. Production timestamptz rows
        # and public Schedule inputs always carry an explicit UTC offset.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _schedule(value: dict) -> tuple[ZoneInfo, int, int]:
    try:
        if set(value) != {"frequency", "local_time", "weekday", "timezone"}:
            raise ValueError("Unexpected schedule field")
        if value["frequency"] not in {"daily", "weekly"}:
            raise ValueError("Invalid frequency")
        if value["frequency"] == "weekly":
            if type(value["weekday"]) is not int or not 1 <= value["weekday"] <= 7:
                raise ValueError("Invalid ISO weekday")
        elif value["weekday"] is not None:
            raise ValueError("Daily schedules do not have a weekday")
        if not isinstance(value["local_time"], str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value["local_time"]):
            raise ValueError("Invalid local time")
        zone = ZoneInfo(value["timezone"])
        hour, minute = map(int, value["local_time"].split(":"))
        return zone, hour, minute
    except (TypeError, KeyError, ValueError, ZoneInfoNotFoundError):
        raise PharmaError("VALIDATION_ERROR", "无效的排程；星期采用 ISO 1（周一）至 7（周日）", 422) from None


def _resolve_local(local: datetime, zone: ZoneInfo) -> tuple[datetime, bool]:
    requested = local
    # Round trips distinguish missing local times from an ambiguous fold.
    # Two days also covers IANA date-line transitions that skip a whole day.
    for _ in range(48 * 60 + 1):
        candidates = []
        for fold in (0, 1):
            candidate = local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if candidate.astimezone(zone).replace(tzinfo=None) == local:
                candidates.append(candidate)
        if candidates:
            return min(candidates), local != requested
        local += timedelta(minutes=1)
    raise PharmaError("VALIDATION_ERROR", "时区内无法找到合法排程时刻", 422)


def preview_schedule(schedule: dict, after: datetime | None = None, count: int = 5) -> dict:
    zone, hour, minute = _schedule(schedule)
    require(type(count) is int and 1 <= count <= 5, "VALIDATION_ERROR", "排程预览最多五次", 422)
    reference = after or now()
    require(reference.tzinfo is not None, "VALIDATION_ERROR", "预览参考时间必须携带时区", 422)
    reference = reference.astimezone(UTC)
    day = reference.astimezone(zone).date()
    occurrences = []
    seen = set()
    for delta in range(370):
        target = day + timedelta(days=delta)
        if schedule["frequency"] == "weekly" and target.isoweekday() != schedule["weekday"]:
            continue
        utc, adjusted = _resolve_local(datetime(target.year, target.month, target.day, hour, minute), zone)
        if utc <= reference or utc in seen:
            continue
        seen.add(utc)
        occurrences.append({"utc": _iso(utc), "local": utc.astimezone(zone).isoformat(), "dst_adjusted": adjusted})
        if len(occurrences) == count:
            return {"occurrences": occurrences}
    raise PharmaError("VALIDATION_ERROR", "无法在有限范围内生成排程", 422)


def _latest_due(schedule: dict, at: datetime) -> datetime:
    zone, hour, minute = _schedule(schedule)
    day = at.astimezone(zone).date()
    for delta in range(9):
        target = day - timedelta(days=delta)
        if schedule["frequency"] == "weekly" and target.isoweekday() != schedule["weekday"]:
            continue
        occurrence, _ = _resolve_local(datetime(target.year, target.month, target.day, hour, minute), zone)
        if occurrence <= at:
            return occurrence
    raise PharmaError("VALIDATION_ERROR", "无法计算最近一次排程", 422)


def email_available() -> bool:
    """Only operator configuration may opt in to the SMTP side effect."""
    host = os.environ.get("PHARMA_SMTP_HOST", "")
    return os.environ.get("PHARMA_SMTP_ENABLED") == "1" and bool(host) and bool(os.environ.get("PHARMA_SMTP_FROM")) and (host in {"localhost", "127.0.0.1", "::1", "mailpit"} or os.environ.get("PHARMA_SMTP_ALLOW_EXTERNAL") == "1")


def _active_owner(repo, owner_id: str, *, research: bool = True) -> dict:
    user = repo.get("app_user", owner_id)
    members = repo.rows("membership", user_id=owner_id, enabled=True)
    require(user["is_active"] and members, "FORBIDDEN", "订阅所属账户或工作区成员资格已停用", 403)
    if research:
        require(members[0]["role"] in {"analyst", "reviewer", "admin"}, "FORBIDDEN", "当前成员角色不能发起研究", 403)
    return user


def _validate_input(repo, value: dict) -> None:
    from .contract import validate

    validate("SubscriptionInput", value)
    _schedule(value["schedule"])
    require(len(set(value["drug_ids"])) == len(value["drug_ids"]), "VALIDATION_ERROR", "关注对象不能重复", 422)
    require(len(set(value["channels"])) == len(value["channels"]), "VALIDATION_ERROR", "交付渠道不能重复", 422)
    require(len(set(value["source_allowlist"])) == len(value["source_allowlist"]), "VALIDATION_ERROR", "来源不能重复", 422)
    for drug_id in value["drug_ids"]:
        drug = repo.get("drug", drug_id)
        require(not value["enabled"] or not drug["archived"], "DRUG_ARCHIVED", "已归档对象不能新增自动跟踪", 409)
    if value["enabled"] and "email" in value["channels"]:
        require(email_available(), "EMAIL_NOT_CONFIGURED", "邮件交付尚未由管理员启用，请使用站内通知", 422)


def create_subscription(repo, owner_id: str, payload: dict) -> dict:
    _active_owner(repo, owner_id)
    _validate_input(repo, payload)
    next_run = preview_schedule(payload["schedule"], count=1)["occurrences"][0]["utc"] if payload["enabled"] else None
    row = repo.add("subscription", owner_id=owner_id, **copy.deepcopy(payload), next_run_at=_utc(next_run) if next_run else None)
    repo.audit(owner_id, "subscription.create", "subscription", row["id"])
    return row


def update_subscription(repo, subscription_id: str, owner_id: str, payload: dict, expected_revision: int, *, can_manage: bool = False) -> dict:
    row = repo.get("subscription", subscription_id, lock=True)
    require(row["owner_id"] == owner_id or can_manage)
    if payload.get("enabled"):
        _active_owner(repo, row["owner_id"])
    require(row["revision"] == expected_revision, "STALE_VERSION", "订阅已被其他操作更新，请刷新后重试", 409)
    _validate_input(repo, payload)
    next_run = preview_schedule(payload["schedule"], count=1)["occurrences"][0]["utc"] if payload["enabled"] else None
    result = repo.update("subscription", subscription_id, **copy.deepcopy(payload), revision=row["revision"] + 1, next_run_at=_utc(next_run) if next_run else None, updated_at=now())
    repo.audit(owner_id, "subscription.update", "subscription", subscription_id, revision=result["revision"])
    return result


def trigger_subscription(
    repo,
    subscription_id: str,
    owner_id: str,
    *,
    create_run: CreateRun,
    scheduled_at: datetime | None = None,
    trigger_kind: str = "manual",
    skipped_window: dict | None = None,
) -> dict:
    subscription = repo.get("subscription", subscription_id, lock=True)
    require(subscription["owner_id"] == owner_id)
    _active_owner(repo, owner_id)
    require(trigger_kind in {"manual", "scheduled"}, "VALIDATION_ERROR", "无效的订阅触发类型", 422)
    if trigger_kind == "scheduled":
        require(subscription["enabled"], "SUBSCRIPTION_PAUSED", "订阅已暂停", 409)
    at = _utc(scheduled_at or now())
    existing = repo.rows("schedule_occurrence", subscription_id=subscription_id, scheduled_at=at)
    if existing:
        return existing[0]
    aliases = []
    for drug_id in subscription["drug_ids"]:
        drug = repo.get("drug", drug_id)
        require(not drug["archived"], "DRUG_ARCHIVED", "关注对象已归档", 409)
        aliases.extend({"id": alias["id"], "drug_id": drug_id, "alias": alias["alias"], "namespace": alias["namespace"]} for alias in repo.rows("drug_alias", drug_id=drug_id, status="approved"))
    frozen = {key: copy.deepcopy(subscription[key]) for key in ("name", "drug_ids", "source_allowlist", "channels", "schedule", "revision", "owner_id")}
    frozen.update({"approved_aliases": aliases, "knowledge_cutoff": _iso(at), "skipped_window": skipped_window, "non_interactive": True})
    occurrence = repo.add("schedule_occurrence", subscription_id=subscription_id, scheduled_at=at, config_snapshot=frozen, trigger_kind=trigger_kind)
    # The window is a research scope, never a delivery watermark. Explicit
    # event revision IDs are used for deduplication, including late arrivals.
    body = {
        "question": f"为订阅“{subscription['name']}”研究所关注对象的公开研发进展，核对新增试验与文献变化、证据及资料缺口。",
        "drug_ids": copy.deepcopy(subscription["drug_ids"]),
        "time_range": {"start": _iso(at - timedelta(days=30)), "end_exclusive": _iso(at), "timezone": subscription["schedule"]["timezone"]},
        "source_allowlist": copy.deepcopy(subscription["source_allowlist"]),
        "budget": {"max_tool_calls": 30, "max_model_calls": 12, "max_wall_seconds": 600, "max_records": 200},
        "parent_run_id": None,
    }
    run = create_run(repo, owner_id, body)
    result = repo.update("schedule_occurrence", occurrence["id"], run_id=run["id"], state="queued")
    repo.audit(owner_id, "subscription.trigger", "schedule_occurrence", result["id"], trigger_kind=trigger_kind, subscription_revision=subscription["revision"])
    return result


def scan_subscriptions(repo, create_run: CreateRun, at: datetime | None = None, limit: int = 50) -> list[dict]:
    """Claim due subscriptions in one short transaction; coalesce downtime."""
    at = _utc(at or now())
    repo.advisory("pharma:scheduler:scan")
    table = repo.table("subscription")
    statement = repo.query("subscription", enabled=True).where(table.c.next_run_at <= at).order_by(table.c.next_run_at, table.c.id).limit(limit).with_for_update(skip_locked=True)
    subscriptions = jsonable_encoder([dict(row) for row in repo.connection.execute(statement).mappings()])
    occurrences = []
    for subscription in subscriptions:
        due = _latest_due(subscription["schedule"], at)
        old_due = _utc(subscription["next_run_at"])
        skipped = {"from": _iso(old_due), "before": _iso(due)} if old_due < due else None
        try:
            # A savepoint prevents a disabled member/archive error from
            # stopping unrelated subscriptions in the same scan.
            with repo.connection.begin_nested():
                occurrence = trigger_subscription(repo, subscription["id"], subscription["owner_id"], create_run=create_run, scheduled_at=due, trigger_kind="scheduled", skipped_window=skipped)
                occurrences.append(occurrence)
        except PharmaError as exc:
            repo.update("subscription", subscription["id"], last_outcome="failed", updated_at=at)
            repo.audit(subscription["owner_id"], "subscription.trigger_failed", "subscription", subscription["id"], error_code=exc.code)
        following = preview_schedule(subscription["schedule"], after=at, count=1)["occurrences"][0]["utc"]
        repo.update("subscription", subscription["id"], next_run_at=_utc(following), updated_at=at)
    return occurrences


def has_new_revisions(repo, subscription_id: str, event_revision_ids: list[str], channels: list[str]) -> bool:
    if any(not repo.rows("delivery", subscription_id=subscription_id, state="accepted", channel=channel, limit=1) for channel in channels):
        return True  # First delivery for this channel establishes its baseline.
    revisions = [repo.get("event_revision", identifier) for identifier in event_revision_ids]
    for channel in channels:
        for revision in revisions:
            cursors = repo.rows("subscription_cursor", subscription_id=subscription_id, channel=channel, event_id=revision["event_id"], limit=1)
            cursor = cursors[0] if cursors else None
            if not cursor or not cursor["last_accepted_revision_id"]:
                return True
            accepted_revision = repo.get("event_revision", cursor["last_accepted_revision_id"])
            if accepted_revision["revision_no"] < revision["revision_no"]:
                return True
    return False


def pending_event_revision_ids(repo, run_id: str, revision_ids: list[str]) -> list[str]:
    """Return the union of revisions still new to any frozen delivery channel."""
    occurrences = repo.rows("schedule_occurrence", run_id=run_id)
    if not occurrences:
        return list(revision_ids)
    pending = set()
    for occurrence in occurrences:
        channels = occurrence["config_snapshot"]["channels"]
        subscription_id = occurrence["subscription_id"]
        for identifier in revision_ids:
            if has_new_revisions(repo, subscription_id, [identifier], channels):
                pending.add(identifier)
    return [identifier for identifier in revision_ids if identifier in pending]


def finalize_occurrence(repo, run_id: str, coverage: list[dict], event_revision_ids: list[str], *, failed: bool = False) -> str | None:
    """Call after actual source work, before persisting an unchanged report."""
    occurrences = repo.rows("schedule_occurrence", run_id=run_id, lock=True)
    state = None
    for occurrence in occurrences:
        config = occurrence["config_snapshot"]
        successful = {item["source"] for item in coverage if item["status"] == "complete" and not item.get("truncated", False)}
        complete = set(config["source_allowlist"]) <= successful
        if failed:
            state = "failed"
        elif not complete:
            state = "partial"
        elif has_new_revisions(repo, occurrence["subscription_id"], event_revision_ids, config["channels"]):
            state = "generated"
        else:
            state = "no_change"
        repo.update("schedule_occurrence", occurrence["id"], state=state)
        repo.update("subscription", occurrence["subscription_id"], last_outcome=state, updated_at=now())
    return state


def _advance_cursors(repo, delivery: dict) -> None:
    if not delivery.get("subscription_id"):
        return
    revisions = [repo.get("event_revision", identifier) for identifier in delivery["covered_event_revisions"]]
    for revision in sorted(revisions, key=lambda item: (item["event_id"], item["revision_no"])):
        repo.advisory(f"cursor:{repo.workspace_id}:{delivery['subscription_id']}:{revision['event_id']}:{delivery['channel']}")
        rows = repo.rows("subscription_cursor", subscription_id=delivery["subscription_id"], event_id=revision["event_id"], channel=delivery["channel"], lock=True)
        if rows:
            cursor = rows[0]
            previous = repo.get("event_revision", cursor["last_accepted_revision_id"]) if cursor["last_accepted_revision_id"] else None
            if previous and previous["revision_no"] >= revision["revision_no"]:
                continue
            repo.update("subscription_cursor", cursor["id"], last_accepted_revision_id=revision["id"], updated_at=now())
        else:
            repo.add("subscription_cursor", subscription_id=delivery["subscription_id"], event_id=revision["event_id"], channel=delivery["channel"], last_accepted_revision_id=revision["id"])


def _recover_expired(repo, at: datetime) -> None:
    table = repo.table("delivery")
    statement = repo.query("delivery", state="sending").where(table.c.lease_expires_at <= at).limit(50).with_for_update(skip_locked=True)
    rows = jsonable_encoder([dict(row) for row in repo.connection.execute(statement).mappings()])
    for delivery in rows:
        uncertain = delivery["channel"] == "email"
        code = "SMTP_OUTCOME_UNKNOWN" if uncertain else "WORKER_LEASE_EXPIRED"
        repo.update("delivery", delivery["id"], state="unknown" if uncertain else "queued", error_code=code, owner_token=None, lease_expires_at=None, next_attempt_at=at)
        for attempt in repo.rows("delivery_attempt", delivery_id=delivery["id"], outcome="started"):
            repo.update("delivery_attempt", attempt["id"], outcome="unknown" if uncertain else "failed", error_code=code, finished_at=at)


def _claim_delivery(workspace_id: str) -> dict | None:
    with transaction(workspace_id) as repo:
        at = now()
        _recover_expired(repo, at)
        table = repo.table("delivery")
        statement = repo.query("delivery", state="queued").where(or_(table.c.next_attempt_at.is_(None), table.c.next_attempt_at <= at)).order_by(table.c.created_at, table.c.id).limit(1).with_for_update(skip_locked=True)
        rows = repo.connection.execute(statement).mappings().all()
        if not rows:
            return None
        delivery = jsonable_encoder(dict(rows[0]))
        version = repo.get("report_version", delivery["report_version_id"])
        report = repo.get("report", version["report_id"])
        try:
            recipient = _active_owner(repo, delivery["recipient_user_id"], research=False)
        except PharmaError:
            recipient = None
        if not recipient or report["state"] == "retracted" or report.get("retracted_at") or not report.get("published_version_id"):
            repo.update("delivery", delivery["id"], state="cancelled", error_code="DELIVERY_NOT_AUTHORIZED")
            return {"skipped": True}
        if delivery["attempt_count"] >= MAX_DELIVERY_ATTEMPTS:
            repo.update("delivery", delivery["id"], state="failed", error_code="ATTEMPTS_EXHAUSTED")
            return {"skipped": True}
        if delivery["channel"] == "email" and not email_available():
            repo.update("delivery", delivery["id"], state="failed", error_code="EMAIL_NOT_CONFIGURED")
            return {"skipped": True}
        attempt_no = delivery["attempt_count"] + 1
        payload = copy.deepcopy(delivery["rendered_payload"])
        if "recipient_email" not in payload:
            payload["recipient_email"] = recipient["email"]
        # The publish service owns rendered_payload; user/model input never
        # supplies a recipient, SMTP host, secret or delivery address.
        token = uid()
        claimed = repo.update("delivery", delivery["id"], state="sending", attempt_count=attempt_no, owner_token=token, lease_expires_at=at + DELIVERY_LEASE, rendered_payload=payload, error_code=None)
        attempt = repo.add("delivery_attempt", delivery_id=delivery["id"], attempt_no=attempt_no, outcome="started", started_at=at)
        claimed["attempt_id"] = attempt["id"]
        return claimed


class DeliveryFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False, unknown: bool = False):
        super().__init__(code)
        self.code, self.retryable, self.unknown = code, retryable, unknown


def _smtp_send(delivery: dict) -> str:
    if not email_available():
        raise DeliveryFailure("EMAIL_NOT_CONFIGURED")
    recipient = delivery["rendered_payload"]["recipient_email"]
    message = EmailMessage()
    message["From"] = os.environ["PHARMA_SMTP_FROM"]
    message["To"] = recipient
    message["Subject"] = re.sub(r"[\r\n]+", " ", delivery["rendered_payload"]["title"])
    message["Date"] = formatdate(localtime=False)
    message_id = f"<pharmascope-{delivery['id']}@pharmascope.local>"
    message["Message-ID"] = message_id
    payload = delivery["rendered_payload"]
    mode = "DEMO · 虚构资料 / 回放" if payload.get("runtime_mode") == "replay" else "LIVE · 公开研发资料"
    message.set_content(f"{mode}\n\n{payload['title']}\n报告 ID：{payload['report_id']}\n版本 ID：{payload['version_id']}\n请登录研究工作台查看已审核版本和证据。\n\n本平台用于公开研发信息研究，不用于诊断、治疗或用药决策。")
    smtp = None
    submitted = False
    try:
        smtp = smtplib.SMTP(os.environ["PHARMA_SMTP_HOST"], int(os.environ.get("PHARMA_SMTP_PORT", "1025")), timeout=20)
        if os.environ.get("PHARMA_SMTP_STARTTLS") == "1":
            smtp.starttls()
        username = os.environ.get("PHARMA_SMTP_USERNAME")
        if username:
            smtp.login(username, os.environ.get("PHARMA_SMTP_PASSWORD", ""))
        submitted = True
        refused = smtp.send_message(message)
        if refused:
            raise DeliveryFailure("SMTP_RECIPIENT_REJECTED")
        return message_id
    except DeliveryFailure:
        raise
    except smtplib.SMTPResponseException as exc:
        # A definite negative SMTP response means not accepted, unlike a
        # broken connection while waiting for the final response to DATA.
        raise DeliveryFailure("SMTP_REJECTED", retryable=400 <= exc.smtp_code < 500) from None
    except smtplib.SMTPRecipientsRefused:
        raise DeliveryFailure("SMTP_RECIPIENT_REJECTED") from None
    except (TimeoutError, OSError, smtplib.SMTPServerDisconnected):
        raise DeliveryFailure("SMTP_OUTCOME_UNKNOWN" if submitted else "SMTP_CONNECT_FAILED", retryable=not submitted, unknown=submitted) from None
    except smtplib.SMTPException:
        raise DeliveryFailure("SMTP_OUTCOME_UNKNOWN" if submitted else "SMTP_CONFIGURATION_ERROR", unknown=submitted) from None
    finally:
        if smtp is not None:
            # QUIT can itself time out after a successful DATA acknowledgement.
            # Closing the socket does not revoke that accepted acknowledgement.
            try:
                smtp.close()
            except OSError:
                pass


def _finish_delivery(workspace_id: str, claimed: dict, failure: DeliveryFailure | None = None, provider_message_id: str | None = None) -> bool:
    with transaction(workspace_id) as repo:
        version = repo.get("report_version", claimed["report_version_id"])
        report = repo.get("report", version["report_id"], lock=True)
        row = repo.get("delivery", claimed["id"], lock=True)
        if row["state"] != "sending" or row["owner_token"] != claimed["owner_token"] or _utc(row["lease_expires_at"]) <= now():
            return False
        at = now()
        if row["channel"] == "in_app" and (report["state"] == "retracted" or report.get("retracted_at")):
            repo.update("delivery", row["id"], state="cancelled", error_code="REPORT_RETRACTED", owner_token=None, lease_expires_at=None)
            repo.update("delivery_attempt", claimed["attempt_id"], outcome="failed", error_code="REPORT_RETRACTED", finished_at=at)
            return True
        if failure is None:
            _advance_cursors(repo, row)
            repo.update("delivery", row["id"], state="accepted", accepted_at=at, owner_token=None, lease_expires_at=None, error_code=None)
            repo.update("delivery_attempt", claimed["attempt_id"], outcome="accepted", provider_message_id=provider_message_id, finished_at=at)
        else:
            retry = failure.retryable and row["attempt_count"] < MAX_DELIVERY_ATTEMPTS
            state = "unknown" if failure.unknown else "queued" if retry else "failed"
            delay = min(3600, 30 * 2 ** (row["attempt_count"] - 1)) + random.uniform(0, 5)
            repo.update("delivery", row["id"], state=state, owner_token=None, lease_expires_at=None, error_code=failure.code, next_attempt_at=at + timedelta(seconds=delay) if retry else at)
            repo.update("delivery_attempt", claimed["attempt_id"], outcome="unknown" if failure.unknown else "failed", error_code=failure.code, finished_at=at)
        return True


def process_deliveries(workspace_id: str, batch_size: int = 20) -> dict[str, int]:
    """Commit claims before external calls; safe to rerun after worker restart."""
    counts = {"processed": 0, "accepted": 0, "failed": 0, "skipped": 0}
    for _ in range(max(0, min(batch_size, 100))):
        claimed = _claim_delivery(workspace_id)
        if claimed is None:
            break
        if claimed.get("skipped"):
            counts["skipped"] += 1
            continue
        failure = None
        provider_message_id = None
        if claimed["channel"] == "email":
            try:
                provider_message_id = _smtp_send(claimed)
            except DeliveryFailure as exc:
                failure = exc
            except (ValueError, KeyError, TypeError):
                failure = DeliveryFailure("SMTP_CONFIGURATION_ERROR")
        # The delivery table is the inbox itself. An in-app acceptance and
        # its event cursors commit atomically, with no external side effect.
        completed = _finish_delivery(workspace_id, claimed, failure, provider_message_id)
        counts["processed"] += 1
        if completed:
            counts["failed" if failure else "accepted"] += 1
    return counts
