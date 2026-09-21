"""Canonical event contracts preserve opaque historical grouping identities."""

import copy

import pytest
from support.pharma import database as database
from support.pharma import repo as repo
from test_pharma_api import api_case as api_case
from test_pharma_api import assert_schema, route

from app.pharma.contract import specification
from app.pharma.domain import CATEGORIES, IGNORED_FIELDS, event_category, ingest
from app.pharma.seed import seed


def test_every_observed_projection_root_has_an_explicit_canonical_category():
    schemas = specification()["components"]["schemas"]
    roots = set(schemas["TrialProjection"]["properties"]) | set(schemas["PublicationProjection"]["properties"])
    assert roots - IGNORED_FIELDS <= CATEGORIES.keys()
    assert {event_category(category) for category in CATEGORIES.values()} <= set(schemas["Event"]["properties"]["category"]["enum"])


@pytest.mark.integration
def test_event_list_and_detail_validate_against_the_public_contract(api_case):
    scoped, _, clients = api_case
    client = clients["reader"]
    events = assert_schema(client.get(route("events_list", scoped.workspace_id)), "EventPage")["items"]
    assert {event["category"] for event in events} == {"status_change", "enrollment_change"}
    for event in events:
        detail = assert_schema(client.get(route("events_get", scoped.workspace_id, event_id=event["id"])), "Event")
        assert detail == event
        assert "状态变化" in event["title"] or "入组信息变化" in event["title"]
        revisions = assert_schema(client.get(route("events_revisions", scoped.workspace_id, event_id=event["id"])), "EventRevisionPage")
        assert revisions["items"]
        assert all(revision["evidence_ids"] for revision in revisions["items"])


@pytest.mark.integration
def test_trial_result_structure_and_endpoint_changes_have_separate_public_categories(api_case):
    scoped, people, clients = api_case
    record = scoped.rows("source_record", source="ctgov")[0]
    previous = scoped.get("source_snapshot", record["current_snapshot_id"])
    updated = copy.deepcopy(previous["normalized"])
    updated.update(has_results=True, primary_outcomes=[{"measure": "Synthetic amended endpoint", "description": None, "time_frame": "Week 12"}])
    envelope = {
        "source": "ctgov",
        "external_id": record["external_id"],
        "normalized": updated,
        "raw_payload": {"synthetic": updated},
        "normalizer_version": previous["normalizer_version"],
        "source_updated": previous["source_updated"],
        "is_demo": True,
        "actor_id": people["analyst"]["id"],
    }
    _, observation, revisions = ingest(scoped, envelope, "synthetic-results-and-endpoint")
    assert len(revisions) == 2
    events = assert_schema(clients["reader"].get(route("events_list", scoped.workspace_id)), "EventPage")["items"]
    new_events = [event for event in events if event["latest_revision_id"] in {revision["id"] for revision in revisions}]
    assert {event["category"] for event in new_events} == {"results_available", "outcome_definition_change"}
    assert {event["title"].split(" · ", 1)[1] for event in new_events} == {"结果结构变化", "主要终点定义变化"}
    for revision in revisions:
        assert revision["after_observation_id"] == observation["id"]
        assert len(revision["evidence_ids"]) == 2


@pytest.mark.integration
def test_publication_baseline_has_no_fabricated_change_and_later_changes_are_classified(repo):
    scoped, actor = repo
    seed(scoped, actor, 4)
    record = scoped.rows("source_record", source="pubmed")[0]
    assert scoped.rows("source_observation", record_id=record["id"])[0]["outcome"] == "baseline"
    assert scoped.rows("intelligence_event", record_id=record["id"]) == []
    previous = scoped.get("source_snapshot", record["current_snapshot_id"])
    updated = copy.deepcopy(previous["normalized"])
    updated.update(
        title="Synthetic corrected metadata",
        abstract_text="Synthetic changed abstract",
        correction_relations=[{"relation": "ErratumIn", "external_id": "12345"}],
        publication_date={"value": "2026-10", "precision": "month", "kind": "source_reported"},
    )
    envelope = {
        "source": "pubmed",
        "external_id": record["external_id"],
        "record_type": "publication",
        "normalized": updated,
        "raw_payload": {"synthetic": updated},
        "normalizer_version": previous["normalizer_version"],
        "source_updated": previous["source_updated"],
        "is_demo": True,
        "actor_id": actor,
    }
    _, observation, revisions = ingest(scoped, envelope, "synthetic-publication-update")
    events = scoped.rows("intelligence_event", record_id=record["id"])
    assert {event_category(event["category"]) for event in events} == {"other", "correction", "date_change"}
    assert len(revisions) == 4
    literature = next(item for item in revisions if scoped.get("intelligence_event", item["event_id"])["category"] == "literature")
    assert {change["path"] for change in literature["changes"]} == {"/abstract_text"}
    assert all(revision["before_observation_id"] != observation["id"] and revision["after_observation_id"] == observation["id"] for revision in revisions)
    assert ingest(scoped, envelope, "synthetic-publication-update")[2] == []


@pytest.mark.integration
def test_public_projection_preserves_distinct_historical_groups_and_immutable_revisions(api_case):
    scoped, _, clients = api_case
    events = scoped.rows("intelligence_event")
    # Multiple opaque groups can project to the same public category. Reads
    # must never merge their event identities or mutate their signed evidence.
    record = scoped.get("source_record", events[0]["record_id"])
    for event, legacy in zip(events, ("literature", "record"), strict=True):
        scoped.update("intelligence_event", event["id"], category=legacy, title=f"{record['external_id']} · {legacy} 字段变化")
    protected = {table: scoped.rows(table) for table in ("event_revision", "source_observation", "source_snapshot", "evidence")}
    event_before = {event["id"]: event for event in scoped.rows("intelligence_event")}
    converted = assert_schema(clients["reader"].get(route("events_list", scoped.workspace_id)), "EventPage")["items"]
    assert {event["id"] for event in converted} == set(event_before)
    assert {event["category"] for event in converted} == {"other"}
    assert all(event["title"] == f"{record['external_id']} · 其他资料字段变化" for event in converted)
    for event in converted:
        assert event["latest_revision_id"] == event_before[event["id"]]["latest_revision_id"]
        assert event["updated_at"] == event_before[event["id"]]["updated_at"]
    assert {table: scoped.rows(table) for table in protected} == protected
    assert {event["id"]: event for event in scoped.rows("intelligence_event")} == event_before
