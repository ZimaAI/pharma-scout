"""Published history, reader boundaries and report cutoff enforcement on PostgreSQL."""

import copy

import pytest
import test_pharma_api as api_cases

from app.pharma import db, reports
from app.pharma.errors import PharmaError

pytestmark = pytest.mark.integration
database = api_cases.database
repo = api_cases.repo
api_case = api_cases.api_case


def _publish(scoped, clients, report, version):
    params = {"workspace_id": scoped.workspace_id, "report_id": report["id"]}
    body = {"version_id": version["id"], "content_hash": version["content_hash"]}
    submitted = clients["analyst"].post(api_cases.route("reports_submit_review", **params), json=body)
    assert submitted.status_code == 200, submitted.text
    reviewed = clients["reviewer"].post(api_cases.route("reviews_decide", **params), json={**body, "decision": "approve", "note": "独立核对当前版本及引用，保留虚构资料限制。"})
    assert reviewed.status_code == 201, reviewed.text
    return api_cases.assert_schema(clients["analyst"].post(api_cases.route("reports_publish", **params), json=body, headers={"idempotency-key": "historical-publish-" + db.uid()}), "Report")


def _edit(scoped, clients, report, previous, title):
    content = copy.deepcopy(previous["content"])
    content["title"] = title
    return api_cases.assert_schema(
        clients["analyst"].post(
            api_cases.route("reports_new_version", scoped.workspace_id, report_id=report["id"]),
            json={"base_version_id": previous["id"], "content": content, "edit_note": "Synthetic historical visibility regression"},
        ),
        "ReportVersion",
        201,
    )


def test_reader_can_read_all_published_versions_but_never_the_new_draft(api_case):
    scoped, people, clients = api_case
    _, report, first = api_cases.start_replay(scoped, clients)
    _publish(scoped, clients, report, first)
    second = _edit(scoped, clients, report, first, "第二份已发布的虚构研究版本")
    _publish(scoped, clients, report, second)
    draft = _edit(scoped, clients, report, second, "不能向读者公开的新版草稿标题")
    params = {"workspace_id": scoped.workspace_id, "report_id": report["id"]}
    reader = clients["reader"]

    visible = api_cases.assert_schema(reader.get(api_cases.route("reports_get", **params)), "Report")
    assert visible["current_version_id"] is None
    assert visible["published_version_id"] == second["id"]
    assert visible["title"] == second["content"]["title"]
    assert visible["state"] == "published"
    versions = api_cases.assert_schema(reader.get(api_cases.route("reports_versions", **params)), "ReportVersionPage")
    assert {item["id"] for item in versions["items"]} == {first["id"], second["id"]}
    for version in (first, second):
        read = api_cases.assert_schema(reader.get(api_cases.route("reports_version_get", **params, version_id=version["id"])), "ReportVersion")
        assert read["content"] == version["content"]
        assert read["content_hash"] == version["content_hash"]
        api_cases.assert_schema(reader.get(api_cases.route("reports_version_claims", **params, version_id=version["id"])), "ClaimPage")
        exported = reader.get(api_cases.route("reports_export", **params), params={"format": "json", "version_id": version["id"]})
        assert exported.status_code == 200, exported.text
        assert exported.json()["content"] == version["content"]
    for operation in ("reports_version_get", "reports_version_claims"):
        response = reader.get(api_cases.route(operation, **params, version_id=draft["id"]))
        assert response.status_code == 404, response.text
        assert draft["content"]["title"] not in response.text
    assert reader.get(api_cases.route("reports_export", **params), params={"format": "json", "version_id": draft["id"]}).status_code == 404

    for version in (first, second, draft):
        scoped.add("report_notice", report_id=report["id"], version_id=version["id"], type="source_updated", message=version["content"]["title"], notice_key="test-history-" + version["id"])
    notices = api_cases.assert_schema(reader.get(api_cases.route("reports_notices", **params)), "ReportNoticePage")
    assert {item["version_id"] for item in notices["items"]} == {first["id"], second["id"]}
    assert all(draft["content"]["title"] not in item["message"] for item in notices["items"])

    other = scoped.add("workspace", name="Synthetic historical isolation workspace", settings={"data_mode": "demo"})
    db.Repository(scoped.connection, other["id"]).add("membership", user_id=people["reader"]["id"], role="reader")
    assert reader.get(api_cases.route("reports_version_get", other["id"], report_id=report["id"], version_id=first["id"])).status_code == 404


def test_reader_published_filter_uses_visible_state_when_an_author_has_a_new_draft(api_case):
    scoped, _, clients = api_case
    _, report, published = api_cases.start_replay(scoped, clients)
    _publish(scoped, clients, report, published)
    _edit(scoped, clients, report, published, "Synthetic current private draft")
    response = clients["reader"].get(api_cases.route("reports_list", scoped.workspace_id), params={"state": "published"})
    page = api_cases.assert_schema(response, "ReportPage")
    assert [item["id"] for item in page["items"]] == [report["id"]]
    assert page["items"][0]["state"] == "published"
    assert clients["reader"].get(api_cases.route("reports_list", scoped.workspace_id), params={"state": "draft"}).json()["items"] == []


def test_downgraded_creator_cannot_read_draft_and_still_has_a_working_report_list(api_case):
    scoped, people, clients = api_case
    _, report, version = api_cases.start_replay(scoped, clients)
    membership = scoped.table("membership")
    scoped.connection.execute(membership.update().where(membership.c.workspace_id == scoped.workspace_id, membership.c.user_id == people["analyst"]["id"]).values(role="reader"))
    params = {"workspace_id": scoped.workspace_id, "report_id": report["id"]}
    assert clients["analyst"].get(api_cases.route("reports_get", **params)).status_code == 404
    assert clients["analyst"].get(api_cases.route("reports_version_get", **params, version_id=version["id"])).status_code == 404
    listing = api_cases.assert_schema(clients["analyst"].get(api_cases.route("reports_list", scoped.workspace_id)), "ReportPage")
    assert listing["items"] == []


def _exclusive_boundary_case(scoped, run, version):
    boundary = "2026-09-16T08:00:00+00:00"
    stored_run = copy.deepcopy(scoped.get("research_run", run["id"]))
    stored_run["frozen_request"]["time_range"]["end_exclusive"] = boundary
    stored_run["research_state"]["scope"]["time_range"]["end_exclusive"] = boundary
    stored_run["research_state"]["scope"]["knowledge_cutoff"] = boundary
    content = copy.deepcopy(version["content"])
    content["scope"] = copy.deepcopy(stored_run["research_state"]["scope"])
    return stored_run, content


def test_report_rejects_claim_evidence_first_observed_exactly_at_exclusive_end(api_case):
    scoped, _, clients = api_case
    run, _, version = api_cases.start_replay(scoped, clients)
    stored_run, content = _exclusive_boundary_case(scoped, run, version)
    content["event_revision_ids"] = []  # Exercise the evidence boundary independently.
    with pytest.raises(PharmaError) as caught:
        reports.validate_content(scoped, stored_run, content)
    assert caught.value.code == "EVIDENCE_INVALID"


def test_report_rejects_event_exactly_at_exclusive_end_even_with_earlier_evidence(api_case):
    scoped, _, clients = api_case
    run, _, version = api_cases.start_replay(scoped, clients)
    stored_run, content = _exclusive_boundary_case(scoped, run, version)
    revision = scoped.get("event_revision", content["event_revision_ids"][0])
    before = scoped.get("source_observation", revision["before_observation_id"])
    evidence = next(scoped.get("evidence", identifier) for identifier in revision["evidence_ids"] if scoped.get("evidence", identifier)["snapshot_id"] == before["snapshot_id"])
    content["claims"] = [copy.deepcopy(content["claims"][0])]
    content["claims"][0]["statement"] = "虚构记录中的已观察字段。"
    content["claims"][0]["evidence_links"] = [{"evidence_id": evidence["id"], "relation": "supports"}]
    content["sections"] = [{"heading": "Synthetic earlier evidence", "text": "Earlier source field", "claim_keys": [content["claims"][0]["claim_key"]]}]
    content["event_revision_ids"] = [revision["id"]]
    with pytest.raises(PharmaError) as caught:
        reports.validate_content(scoped, stored_run, content)
    assert caught.value.code == "EVIDENCE_INVALID"
