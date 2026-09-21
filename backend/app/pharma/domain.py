"""Versioned observations, field evidence and deterministic research boundaries."""

import re
from datetime import datetime

from .db import canonical, digest, now, text_hash
from .errors import PharmaError, require

CATEGORIES = {
    "title": "record",
    "status": "status",
    "phases": "record",
    "conditions": "record",
    "sponsor": "record",
    "enrollment": "enrollment",
    "primary_outcomes": "endpoints",
    "has_results": "results",
    "start_date": "dates",
    "completion_date": "dates",
    "primary_completion_date": "dates",
    "interventions": "record",
    "authors": "record",
    "journal": "record",
    "doi": "record",
    "pmid": "record",
    "publication_date": "dates",
    "abstract_text": "literature",
    "publication_types": "record",
    "correction_relations": "correction",
}
IGNORED_FIELDS = {"source_updated", "raw_status", "fetched_at", "source_updated_at"}
# Persistence grouping keys remain stable so historical event/revision identities
# and their uniqueness constraint are preserved. Only API categories are public.
PUBLIC_EVENT_CATEGORIES = {
    "status": "status_change",
    "enrollment": "enrollment_change",
    "endpoints": "outcome_definition_change",
    "results": "results_available",
    "dates": "date_change",
    "literature": "other",
    "record": "other",
    "correction": "correction",
}
EVENT_TITLES = {
    "status_change": "招募状态变化",
    "enrollment_change": "入组信息变化",
    "date_change": "关键日期变化",
    "outcome_definition_change": "主要终点定义变化",
    "results_available": "结果结构变化",
    "publication_added": "新增文献记录",
    "correction": "文献更正关系变化",
    "other": "其他资料字段变化",
}


def event_category(category):
    return PUBLIC_EVENT_CATEGORIES.get(category, category if category in EVENT_TITLES else "other")


def event_title(external_id, category):
    return f"{external_id} · {EVENT_TITLES[event_category(category)]}"


def differences(before, after):
    changes = []
    for key in sorted(before.keys() | after.keys()):
        if key in IGNORED_FIELDS:
            continue
        if key in before and key in after and before[key] == after[key]:
            continue
        changes.append({"path": "/" + key.replace("~", "~0").replace("/", "~1"), "type": "added" if key not in before else "removed" if key not in after else "changed", "before": before.get(key), "after": after.get(key)})
    return changes


def extract_quote(snapshot, locator):
    try:
        if locator["kind"] == "json_pointer":
            value = snapshot
            for token in locator["path"].split("/")[1:]:
                token = token.replace("~1", "/").replace("~0", "~")
                value = value[int(token)] if isinstance(value, list) else value[token]
            return value if isinstance(value, str) else canonical(value)
        text = snapshot["normalized"][locator.get("field", "abstract_text")]
        start, end = locator["start"], locator["end"]
        require(0 <= start < end <= len(text), "EVIDENCE_INVALID", "原文定位无效", 422)
        return text[start:end]
    except (KeyError, IndexError, ValueError, TypeError):
        raise PharmaError("EVIDENCE_INVALID", "无法在快照中定位引用", 422) from None


def check_question(question):
    patterns = [r"(我|本人|我家|我爸|我妈|我的孩子).{0,35}(服用|用药|剂量|治疗|处方|确诊)", r"(给我|帮我).{0,20}(诊断|开药|治疗方案)", r"(my|i have).{0,50}(dose|dosage|prescribe|diagnos)", r"(?:身份证|病历号)\s*[:：]?\s*[\w-]+"]
    if any(re.search(p, question, re.I) for p in patterns):
        raise PharmaError("RESEARCH_SCOPE_REQUIRED", "本平台仅研究公开研发资料，请移除个人病情、身份信息和个体用药请求。", 422)


def add_evidence(repo, snapshot, path):
    locator = {"kind": "json_pointer", "path": "/normalized" + path}
    quote = extract_quote(snapshot, locator)
    for item in repo.rows("evidence", snapshot_id=snapshot["id"]):
        if item["locator"] == locator:
            return item
    return repo.add("evidence", snapshot_id=snapshot["id"], locator=locator, quoted_text=quote, snippet_hash=text_hash(quote), original_language="en", translation_text=None, extractor_version="pharma-pointer-v1")


def verify_evidence(repo, evidence_id, cutoff=None):
    item = repo.get("evidence", evidence_id)
    snapshot = repo.get("source_snapshot", item["snapshot_id"])
    require(digest(snapshot["raw_payload"]) == snapshot["content_hash"], "EVIDENCE_INVALID", "快照内容哈希不一致", 422)
    require(extract_quote(snapshot, item["locator"]) == item["quoted_text"] and text_hash(item["quoted_text"]) == item["snippet_hash"], "EVIDENCE_INVALID", "引用与快照定位不一致", 422)
    if cutoff:
        require(datetime.fromisoformat(snapshot["first_observed_at"]) <= datetime.fromisoformat(cutoff.replace("Z", "+00:00")), "EVIDENCE_INVALID", "引用晚于本次资料截止时间", 422)
    return item


def ingest(repo, envelope, operation_key, drug_id=None, observed_at=None):
    source, external_id = envelope["source"], envelope["external_id"]
    repo.advisory(f"ingest:{repo.workspace_id}:{source}:{external_id}")
    rows = repo.rows("source_record", source=source, external_id=external_id)
    record = (
        rows[0]
        if rows
        else repo.add(
            "source_record",
            source=source,
            external_id=external_id,
            kind=envelope.get("record_type", "trial" if source == "ctgov" else "publication"),
            canonical_url=envelope.get("url", f"demo://{external_id}"),
            is_demo=envelope.get("is_demo", False),
        )
    )
    previous = repo.get("source_observation", record["current_observation_id"]) if record["current_observation_id"] else None
    previous_snapshot = repo.get("source_snapshot", previous["snapshot_id"]) if previous else None
    duplicates = repo.rows("source_observation", record_id=record["id"], operation_key=operation_key)
    if duplicates:
        if drug_id and not repo.rows("entity_link", record_id=record["id"], drug_id=drug_id):
            repo.add("entity_link", record_id=record["id"], drug_id=drug_id, relation="unspecified" if source == "ctgov" else "mentions", note="检索召回，需审核关联依据", proposed_by=envelope["actor_id"], status="pending")
        return record, duplicates[0], []
    timestamp = observed_at or envelope.get("fetched_at") or now()
    content_hash = digest(envelope["raw_payload"])
    snapshots = repo.rows("source_snapshot", record_id=record["id"], content_hash=content_hash, normalizer_version=envelope["normalizer_version"])
    snapshot = (
        snapshots[0]
        if snapshots
        else repo.add(
            "source_snapshot",
            record_id=record["id"],
            content_hash=content_hash,
            normalizer_version=envelope["normalizer_version"],
            raw_payload=envelope["raw_payload"],
            normalized=envelope["normalized"],
            source_updated=envelope["source_updated"],
            first_observed_at=timestamp,
            is_demo=envelope.get("is_demo", False),
        )
    )
    outcome = "baseline" if not previous else "unchanged" if previous["snapshot_id"] == snapshot["id"] else "changed"
    seq = record["next_observation_seq"] + 1
    observation = repo.add("source_observation", record_id=record["id"], snapshot_id=snapshot["id"], observation_seq=seq, fetched_at=timestamp, outcome=outcome, operation_key=operation_key)
    changes = differences(previous_snapshot["normalized"], snapshot["normalized"]) if previous_snapshot else []
    grouped = {}
    for change in changes:
        grouped.setdefault(CATEGORIES.get(change["path"][1:], "record"), []).append(change)
    revisions = []
    for category, fields in grouped.items():
        events = repo.rows("intelligence_event", record_id=record["id"], category=category)
        event = events[0] if events else repo.add("intelligence_event", record_id=record["id"], category=category, title=event_title(external_id, category))
        evidence = []
        for field in fields:
            for snap in [previous_snapshot, snapshot]:
                if field["path"][1:] in snap["normalized"]:
                    evidence.append(add_evidence(repo, snap, field["path"])["id"])
        old = repo.rows("event_revision", event_id=event["id"])
        revision = repo.add(
            "event_revision",
            event_id=event["id"],
            revision_no=len(old) + 1,
            before_observation_id=previous["id"],
            after_observation_id=observation["id"],
            changes=fields,
            evidence_ids=list(dict.fromkeys(evidence)),
            severity="correction" if snapshots else "important",
            observed_at=timestamp,
        )
        repo.update("intelligence_event", event["id"], latest_revision_id=revision["id"], updated_at=now())
        revisions.append(revision)
        # A source update adds a separate notice; signed report content is untouched.
        affected = {e["id"] for e in repo.rows("evidence", snapshot_id=previous_snapshot["id"])}
        claim_ids = {link["claim_id"] for link in repo.rows("claim_evidence", limit=10000) if link["evidence_id"] in affected}
        version_ids = {c["report_version_id"] for c in repo.rows("claim", limit=10000) if c["id"] in claim_ids}
        for version_id in version_ids:
            version = repo.get("report_version", version_id)
            key = f"source:{version_id}:{revision['id']}"
            if not repo.rows("report_notice", notice_key=key):
                repo.add("report_notice", report_id=version["report_id"], version_id=version_id, event_revision_id=revision["id"], type="source_updated", message="引用资料已有新版本，请重新核对旧报告结论。", notice_key=key)
    for key in ["title", "status", "enrollment", "abstract_text", "has_results"]:
        if key in snapshot["normalized"] and snapshot["normalized"][key] is not None:
            add_evidence(repo, snapshot, "/" + key)
    record = repo.update("source_record", record["id"], current_snapshot_id=snapshot["id"], current_observation_id=observation["id"], next_observation_seq=seq, current_projection=snapshot["normalized"], updated_at=now())
    if drug_id and not repo.rows("entity_link", record_id=record["id"], drug_id=drug_id):
        # Official search hits are candidates. Never infer trial intervention role.
        repo.add("entity_link", record_id=record["id"], drug_id=drug_id, relation="unspecified" if source == "ctgov" else "mentions", note="检索召回，需审核关联依据", proposed_by=envelope["actor_id"], status="pending")
    return record, observation, revisions
