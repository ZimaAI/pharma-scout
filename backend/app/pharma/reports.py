"""Immutable reports, evidence authorization and hash-bound independent review."""

import re
from datetime import datetime

from .contract import validate
from .db import digest, now
from .domain import verify_evidence
from .errors import require


def report_access(repo, principal, report_id):
    report = repo.get("report", report_id)
    editor = (report["created_by"] == principal.user_id and principal.role == "analyst") or principal.role in ("reviewer", "admin")
    require(editor or report["published_version_id"])
    return report, editor


def visible_report(repo, principal, report):
    report, editor = report_access(repo, principal, report["id"])
    result = dict(report)
    if not editor:
        result["current_version_id"] = None
        published = repo.get("report_version", report["published_version_id"])
        result["title"] = published["content_json"]["title"]
        if result["state"] != "retracted":
            result["state"] = "published"
    return result


def published_version_ids(repo, report):
    versions = {report["published_version_id"]} if report["published_version_id"] else set()
    versions.update(item["details"]["version_id"] for item in repo.rows("audit_log", action="report.publish", target_id=report["id"], limit=10000) if item["details"].get("version_id"))
    return versions


def visible_version(repo, principal, report_id, version_id):
    report, editor = report_access(repo, principal, report_id)
    version = repo.get("report_version", version_id)
    require(version["report_id"] == report_id and (editor or version_id in published_version_ids(repo, report)))
    result = dict(version)
    result["content"] = result.pop("content_json")
    result["claim_ids"] = [c["id"] for c in repo.rows("claim", report_version_id=version_id)]
    return result


def validate_content(repo, run, content):
    validate("ResearchOutput", content)
    scope = content["scope"]
    require(set(scope["drug_ids"]) == set(run["frozen_request"]["drug_ids"]), "EVIDENCE_INVALID", "报告研究对象与任务范围不一致", 422)
    require(scope["time_range"] == run["frozen_request"]["time_range"], "EVIDENCE_INVALID", "报告时间范围与任务不一致", 422)
    expected_cutoff = run["research_state"]["scope"]["knowledge_cutoff"]
    require(datetime.fromisoformat(scope["knowledge_cutoff"].replace("Z", "+00:00")) == datetime.fromisoformat(expected_cutoff.replace("Z", "+00:00")), "EVIDENCE_INVALID", "报告资料截止时间与任务不一致", 422)
    allowed_sources = set(run["frozen_request"]["source_allowlist"])
    require({c["source"] for c in content["coverage"]} == allowed_sources, "EVIDENCE_INVALID", "报告来源覆盖与研究范围不一致", 422)
    keys = [c["claim_key"] for c in content["claims"]]
    require(len(keys) == len(set(keys)), "EVIDENCE_INVALID", "结论标识重复", 422)
    for section in content["sections"]:
        require(set(section["claim_keys"]) <= set(keys), "EVIDENCE_INVALID", "章节包含未知结论", 422)
    linked_records = {link["record_id"] for link in repo.rows("entity_link", limit=10000) if link["drug_id"] in scope["drug_ids"] and link["status"] == "approved"}
    authorized_evidence = set()
    checks = []
    for claim in content["claims"]:
        links = claim["evidence_links"]
        require(claim["category"] != "fact" or any(link["relation"] == "supports" for link in links), "EVIDENCE_INVALID", "事实结论必须有支持证据", 422)
        quotes = []
        for link in links:
            evidence = verify_evidence(repo, link["evidence_id"], scope["knowledge_cutoff"])
            snapshot = repo.get("source_snapshot", evidence["snapshot_id"])
            require(datetime.fromisoformat(snapshot["first_observed_at"]) < datetime.fromisoformat(scope["time_range"]["end_exclusive"].replace("Z", "+00:00")), "EVIDENCE_INVALID", "引用超出研究时间窗", 422)
            record = repo.get("source_record", snapshot["record_id"])
            require(record["source"] in allowed_sources and record["id"] in linked_records, "EVIDENCE_INVALID", "引用不属于本次研究对象或来源", 422)
            quotes.append(evidence["quoted_text"])
            authorized_evidence.add(evidence["id"])
        statement = claim["statement"]
        require(not (claim["category"] == "fact" and re.search(r"(证明.{0,6}(疗效|安全)|疗效优于|获批上市|治愈率|研发成功率)", statement)), "EVIDENCE_INVALID", "关键临床或监管结论需要专门核验，当前来源不支持此表述", 422)
        numbers = set(re.findall(r"(?<![\w-])\d+(?:\.\d+)?%?", statement))
        quoted_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", " ".join(quotes)))
        numeric = "not_applicable" if not numbers else "passed" if numbers <= quoted_numbers else "manual_check_required"
        status = "conflicted" if any(link["relation"] == "contradicts" for link in links) else "insufficient" if not links else "unverified"
        checks.append((claim, status, numeric))
    for revision_id in content["event_revision_ids"]:
        revision = repo.get("event_revision", revision_id)
        require(datetime.fromisoformat(revision["observed_at"]) <= datetime.fromisoformat(scope["knowledge_cutoff"].replace("Z", "+00:00")), "EVIDENCE_INVALID", "事件晚于资料截止时间", 422)
        require(datetime.fromisoformat(revision["observed_at"]) < datetime.fromisoformat(scope["time_range"]["end_exclusive"].replace("Z", "+00:00")), "EVIDENCE_INVALID", "事件超出研究时间窗", 422)
        require(set(revision["evidence_ids"]) & authorized_evidence, "EVIDENCE_INVALID", "不能将未在结论中呈现的事件记为已覆盖", 422)
    return checks


def create_version(repo, principal, run, content, report=None, edit_note="initial"):
    checks = validate_content(repo, run, content)
    if report is None:
        existing = repo.rows("report", run_id=run["id"])
        report = existing[0] if existing else repo.add("report", run_id=run["id"], created_by=run["created_by"], title=content["title"])
    report = repo.get("report", report["id"], lock=True)
    versions = repo.rows("report_version", report_id=report["id"])
    content_hash = digest(content)
    if versions and versions[0]["content_hash"] == content_hash:
        return report, versions[0]
    version = repo.add("report_version", report_id=report["id"], version_no=len(versions) + 1, created_by=principal.user_id, content_json=content, content_hash=content_hash, runtime_mode=run["runtime_mode"], edit_note=edit_note)
    for draft, status, numeric in checks:
        claim = repo.add(
            "claim",
            report_version_id=version["id"],
            claim_key=draft["claim_key"],
            statement=draft["statement"],
            category=draft["category"],
            qualifiers=draft["qualifiers"],
            verification_status=status,
            numeric_check=numeric,
            verification_meta={"structural_checks": "passed", "semantic_review": "human_required"},
        )
        for link in draft["evidence_links"]:
            repo.add("claim_evidence", claim_id=claim["id"], **link)
    report = repo.update("report", report["id"], title=content["title"], current_version_id=version["id"], state="draft", updated_at=now())
    return report, version


def current_action(repo, report_id, body):
    report = repo.get("report", report_id, lock=True)
    require(report["current_version_id"] == body["version_id"], "STALE_VERSION", "版本已更新，请刷新后重新审核", 409)
    version = repo.get("report_version", body["version_id"])
    require(version["report_id"] == report_id and version["content_hash"] == body["content_hash"], "STALE_VERSION", "内容哈希不匹配", 409)
    return report, version


def submit_review(repo, principal, report_id, body):
    report, version = current_action(repo, report_id, body)
    principal.owns(report)
    require(report["state"] != "retracted", "STALE_VERSION", "已撤回的报告不能重新送审", 409)
    run = repo.get("research_run", report["run_id"])
    validate_content(repo, run, version["content_json"])
    repo.audit(principal.user_id, "report.submit_review", "report", report_id, version_id=version["id"])
    return repo.update("report", report_id, state="in_review", updated_at=now())


def review(repo, principal, report_id, body):
    principal.require_role("reviewer")
    report, version = current_action(repo, report_id, body)
    require(principal.user_id not in (report["created_by"], version["created_by"]), "SELF_REVIEW_FORBIDDEN", "研究发起人和本版本编辑人不能审核自己的报告", 403)
    require(report["state"] == "in_review", "STALE_VERSION", "报告尚未提交审核", 409)
    run = repo.get("research_run", report["run_id"])
    validate_content(repo, run, version["content_json"])
    result = repo.add("review", report_id=report_id, version_id=version["id"], content_hash=version["content_hash"], reviewer_id=principal.user_id, decision=body["decision"], note=body["note"])
    repo.update("report", report_id, state="approved" if body["decision"] == "approve" else "changes_requested", updated_at=now())
    repo.audit(principal.user_id, "report.review", "report", report_id, decision=body["decision"], version_id=version["id"])
    return result


def publish(repo, principal, report_id, body):
    principal.require_role("analyst")
    report, version = current_action(repo, report_id, body)
    principal.owns(report)
    approvals = repo.rows("review", version_id=version["id"], content_hash=version["content_hash"])
    require(approvals and approvals[0]["decision"] == "approve" and report["state"] in ("approved", "published"), "REPORT_NOT_APPROVED", "请先由独立审核人批准当前版本", 409)
    require(approvals[0]["reviewer_id"] not in (report["created_by"], version["created_by"]), "SELF_REVIEW_FORBIDDEN", "不允许自审", 403)
    validate_content(repo, repo.get("research_run", report["run_id"]), version["content_json"])
    recipients = {(report["created_by"], "in_app"): None}
    occurrences = repo.rows("schedule_occurrence", run_id=report["run_id"])
    for occurrence in occurrences:
        sub = repo.get("subscription", occurrence["subscription_id"])
        for channel in occurrence["config_snapshot"]["channels"]:
            recipients[(sub["owner_id"], channel)] = sub["id"]
    for (recipient, channel), subscription_id in recipients.items():
        key = f"{version['id']}:{recipient}:{channel}"
        if not repo.rows("delivery", idempotency_key=key):
            repo.add(
                "delivery",
                report_version_id=version["id"],
                subscription_id=subscription_id,
                recipient_user_id=recipient,
                channel=channel,
                idempotency_key=key,
                rendered_payload={"title": content_title(version), "report_id": report_id, "version_id": version["id"], "runtime_mode": version["runtime_mode"]},
                covered_event_revisions=version["content_json"]["event_revision_ids"],
            )
    repo.audit(principal.user_id, "report.publish", "report", report_id, version_id=version["id"])
    return repo.update("report", report_id, published_version_id=version["id"], state="published", updated_at=now())


def content_title(version):
    return ("[DEMO] " if version["runtime_mode"] == "replay" else "") + version["content_json"]["title"]


def retract(repo, principal, report_id, body):
    principal.require_role("reviewer")
    report = repo.get("report", report_id, lock=True)
    require(report["published_version_id"] == body["version_id"], "STALE_VERSION", "只能撤回当前已发布版本", 409)
    key = f"retract:{body['version_id']}"
    if not repo.rows("report_notice", notice_key=key):
        repo.add("report_notice", report_id=report_id, version_id=body["version_id"], type="report_retracted", message=body["reason"], notice_key=key)
    for delivery in repo.rows("delivery", report_version_id=body["version_id"]):
        if delivery["state"] == "queued":
            repo.update("delivery", delivery["id"], state="cancelled")
    repo.audit(principal.user_id, "report.retract", "report", report_id, reason=body["reason"])
    return repo.update("report", report_id, state="retracted", retracted_at=now(), retraction_reason=body["reason"])


def export_markdown(version):
    content = version["content"]
    lines = [
        f"# {content['title']}",
        "",
        "DEMO · 虚构资料 / 回放" if version["runtime_mode"] == "replay" else "LIVE · 公开研究资料",
        f"资料截止：{content['scope']['knowledge_cutoff']}",
        f"版本：{version['version_no']} · SHA256 {version['content_hash']}",
        "",
        content["summary"],
    ]
    for section in content["sections"]:
        lines.extend(["", f"## {section['heading']}", section["text"]])
    for claim in content["claims"]:
        refs = " ".join(f"[证据 {link['evidence_id']}]" for link in claim["evidence_links"])
        lines.extend(["", f"{claim['claim_key']}: {claim['statement']} {refs}"])
    lines.extend(["", "## 资料限制", *[f"- {line}" for line in content["limitations"]], "", "本平台用于公开研发信息研究，不用于诊断、治疗或用药决策。"])
    return "\n".join(lines)
