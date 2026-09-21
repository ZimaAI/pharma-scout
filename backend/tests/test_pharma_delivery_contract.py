"""Delivery navigation identifies the frozen report version through the real API."""

import pytest
from support.pharma import database as database
from support.pharma import repo as repo
from test_pharma_api import api_case as api_case
from test_pharma_api import assert_schema, route

from app.pharma import db

pytestmark = pytest.mark.integration


def delivery_fixture(scoped, actor):
    run = scoped.add("research_run", created_by=actor, question="Synthetic delivery navigation", runtime_mode="replay", frozen_request={}, prompt_version="test")
    report = scoped.add("report", run_id=run["id"], created_by=actor, title="Synthetic report")
    versions = [scoped.add("report_version", report_id=report["id"], version_no=number, created_by=actor, content_json={"title": "Synthetic report"}, content_hash=db.digest({"version": number}), runtime_mode="replay") for number in (1, 2)]
    scoped.update("report", report["id"], state="published", current_version_id=versions[1]["id"], published_version_id=versions[1]["id"])
    delivery = scoped.add(
        "delivery",
        report_version_id=versions[0]["id"],
        recipient_user_id=actor,
        channel="in_app",
        state="accepted",
        accepted_at=db.now(),
        idempotency_key=db.uid(),
        # Navigation must come from the tenant-scoped version relationship,
        # including legacy payloads that did not contain a report identifier.
        rendered_payload={"title": "Synthetic report"},
        covered_event_revisions=[],
    )
    return delivery, report, versions[0]


def test_all_delivery_responses_identify_the_frozen_report_version(api_case):
    scoped, people, clients = api_case
    delivery, report, version = delivery_fixture(scoped, people["analyst"]["id"])
    client = clients["analyst"]
    for operation in ("inbox_list", "deliveries_list"):
        result = assert_schema(client.get(route(operation, scoped.workspace_id)), "DeliveryPage")
        assert len(result["items"]) == 1
        assert result["items"][0]["report_id"] == report["id"]
        assert result["items"][0]["report_version_id"] == version["id"]
    detail = assert_schema(client.get(route("deliveries_get", scoped.workspace_id, delivery_id=delivery["id"])), "Delivery")
    assert detail["report_id"] == report["id"]
    assert detail["report_version_id"] == version["id"]
    assert detail["read_at"] is None
    marked = assert_schema(client.post(route("inbox_mark_read", scoped.workspace_id, delivery_id=delivery["id"])), "Delivery")
    assert marked["report_id"] == report["id"]
    assert marked["report_version_id"] == version["id"]
    assert marked["read_at"] is not None


def test_delivery_report_reference_preserves_recipient_and_workspace_scope(api_case):
    scoped, people, clients = api_case
    delivery, _, _ = delivery_fixture(scoped, people["analyst"]["id"])
    for operation in ("inbox_list", "deliveries_list"):
        assert clients["reader"].get(route(operation, scoped.workspace_id)).json()["items"] == []
    assert clients["reader"].get(route("deliveries_get", scoped.workspace_id, delivery_id=delivery["id"])).status_code == 404
    assert clients["reader"].post(route("inbox_mark_read", scoped.workspace_id, delivery_id=delivery["id"])).status_code == 404
    assert clients["analyst"].get(route("deliveries_get", db.uid(), delivery_id=delivery["id"])).status_code == 404
    assert scoped.get("delivery", delivery["id"])["read_at"] is None
