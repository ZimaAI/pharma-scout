"""Deterministic fictional timeline; only the requested day and earlier are ingested."""

import json
import uuid
from pathlib import Path

from .domain import ingest
from .errors import require


def fixture(name):
    return json.loads((Path(__file__).parent / "resources/fixtures" / name).read_text(encoding="utf-8"))


def seed(repo, actor_id, day=3):
    workspace = repo.get("workspace", repo.workspace_id)
    require(workspace["settings"].get("data_mode") == "demo", "DEMO_ONLY", "演示资料只能载入演示工作区", 403)
    drugs = fixture("01-drugs.json")
    for drug in drugs:
        drug["id"] = str(uuid.uuid5(uuid.UUID(repo.workspace_id), drug["id"]))
        if not repo.rows("drug", id=drug["id"]):
            repo.add("drug", **{key: value for key, value in drug.items() if key != "workspace_id"})
        if not repo.rows("drug_alias", drug_id=drug["id"]):
            repo.add(
                "drug_alias",
                drug_id=drug["id"],
                alias=drug["development_code"],
                normalized_alias=drug["development_code"].lower(),
                namespace="development_code",
                note="虚构演示代号",
                proposed_by=actor_id,
                reviewed_by=actor_id,
                status="approved",
            )
    snapshots = fixture("02-trial-snapshots.json")
    for index in range(day):
        snap = snapshots[[0, 0, 1, 2, 0][index]]
        env = {**snap, "source": "ctgov", "external_id": "DEMO-CT-001", "record_type": "trial", "url": "demo://DEMO-CT-001"}
        record, _, _ = ingest(repo, env, f"demo-day-{index + 1}", observed_at=f"2026-09-{14 + index:02}T08:00:00+00:00")
        if not repo.rows("entity_link", record_id=record["id"], drug_id=drugs[0]["id"]):
            repo.add("entity_link", record_id=record["id"], drug_id=drugs[0]["id"], relation="investigational", note="虚构干预关系", status="approved", proposed_by=actor_id, reviewed_by=actor_id)
    if day >= 4:
        snap = fixture("05-publication-snapshot.json")
        record, _, _ = ingest(repo, {**snap, "source": "pubmed", "external_id": "DEMO-PM-001", "record_type": "publication", "url": "demo://DEMO-PM-001"}, "demo-publication-D4", observed_at="2026-09-17T08:00:00+00:00")
        if not repo.rows("entity_link", record_id=record["id"], drug_id=drugs[0]["id"]):
            repo.add("entity_link", record_id=record["id"], drug_id=drugs[0]["id"], relation="mentions", note="虚构文献关系", status="approved", proposed_by=actor_id, reviewed_by=actor_id)
    settings = dict(workspace["settings"])
    settings["demo_day"] = max(day, settings.get("demo_day", 0))
    repo.update("workspace", workspace["id"], settings=settings)
