"""Offline adapter contracts. All payloads below are synthetic fixtures."""

import copy
import json
import os
from pathlib import Path

import httpx
import jsonschema
import pytest

from app.pharma.sources import PharmaSources, SourceError, normalize_ctgov, normalize_date, normalize_pubmed


def trial_payload():
    return {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Synthetic source adapter trial"},
            "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-08"}},
            "designModule": {"phases": ["PHASE2", "PHASE1"], "enrollmentInfo": {"count": 120, "type": "ESTIMATED"}},
            "conditionsModule": {"conditions": ["Synthetic B", "Synthetic A"]},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Synthetic sponsor"}},
            "outcomesModule": {"primaryOutcomes": [{"measure": "Synthetic endpoint", "timeFrame": "12 weeks"}]},
        },
        "hasResults": False,
    }


PUBMED_XML = b"""<?xml version="1.0"?>
<!DOCTYPE PubmedArticleSet SYSTEM "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID>
<DateRevised><Year>2026</Year><Month>08</Month><Day>19</Day></DateRevised>
<Article><ArticleTitle>Synthetic <i>publication</i> title</ArticleTitle>
<Journal><Title>Synthetic Journal</Title><JournalIssue><PubDate><Year>2026</Year><Month>Aug</Month></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Example</LastName><ForeName>Alex</ForeName></Author><Author><CollectiveName>Synthetic Group</CollectiveName></Author></AuthorList>
<Abstract><AbstractText Label="BACKGROUND">Synthetic background.</AbstractText><AbstractText Label="RESULTS">Synthetic record update only.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article>
<CommentsCorrectionsList><CommentsCorrections RefType="ErratumIn"><PMID>23456789</PMID></CommentsCorrections></CommentsCorrectionsList>
</MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.0000/synthetic</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""


def assert_projection_schema(envelope):
    path = Path(__file__).parents[2] / "docs/reference/pharma-intelligence/contracts/source-snapshot.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    kind = "TrialProjection" if envelope["source"] == "ctgov" else "PublicationProjection"
    jsonschema.Draft202012Validator({"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]}).validate(envelope["normalized"])


@pytest.mark.parametrize(
    ("raw", "value", "precision"),
    [(None, None, "unknown"), ("2026", "2026", "year"), ("2026-08", "2026-08", "month"), ("2026-08-19", "2026-08-19", "day"), ("2026-02-31", None, "unknown"), ("2026-13", None, "unknown"), ("unknown", None, "unknown")],
)
def test_date_precision_never_invents_days(raw, value, precision):
    result = normalize_date(raw)
    assert result["value"] == value
    assert result["precision"] == precision


def test_ctgov_schema_and_hash_exclude_observation_time():
    first = normalize_ctgov(trial_payload(), fetched_at="2026-08-20T00:00:00Z")
    second = normalize_ctgov(trial_payload(), fetched_at="2026-08-21T00:00:00Z")
    assert first["content_hash"] == second["content_hash"]
    assert first["fetched_at"] != second["fetched_at"]
    assert first["normalized"]["source_updated"]["precision"] == "month"
    assert first["normalized"]["has_results"] is False
    assert first["url"] == "https://clinicaltrials.gov/study/NCT00000001"
    assert_projection_schema(first)
    changed = trial_payload()
    changed["protocolSection"]["designModule"]["enrollmentInfo"]["type"] = "ACTUAL"
    assert normalize_ctgov(changed)["content_hash"] != first["content_hash"]


def test_ctgov_unknown_status_and_missing_results_remain_unknown():
    raw = trial_payload()
    raw["protocolSection"]["statusModule"]["overallStatus"] = "NEW_UPSTREAM_STATUS"
    del raw["hasResults"]
    normalized = normalize_ctgov(raw)["normalized"]
    assert normalized["status"] == "OTHER"
    assert normalized["raw_status"] == "NEW_UPSTREAM_STATUS"
    assert normalized["has_results"] is None


def test_ctgov_interventions_and_trial_dates_preserve_scope_precision_and_kind():
    raw = trial_payload()
    raw["protocolSection"]["armsInterventionsModule"] = {"interventions": [{"name": "Synthetic comparator", "type": "DRUG", "armGroupLabels": ["Comparator"]}]}
    raw["protocolSection"]["statusModule"].update({"startDateStruct": {"date": "2026-08", "type": "ACTUAL"}, "completionDateStruct": {"date": "2027", "type": "ESTIMATED"}})
    item = normalize_ctgov(raw)
    assert item["normalized"]["start_date"] == {"value": "2026-08", "precision": "month", "kind": "actual"}
    assert item["normalized"]["completion_date"] == {"value": "2027", "precision": "year", "kind": "estimated"}
    assert item["normalized"]["primary_completion_date"]["value"] is None
    assert item["normalized"]["interventions"][0]["arm_group_labels"] == ["Comparator"]
    assert "relation" not in item["normalized"]["interventions"][0]
    assert_projection_schema(item)


def test_ctgov_invalid_required_record_is_explicit_schema_error():
    with pytest.raises(SourceError, match="schema"):
        normalize_ctgov({"protocolSection": {}})


def test_pubmed_schema_mixed_content_corrections_and_month_precision():
    item = normalize_pubmed(PUBMED_XML)[0]
    assert item["external_id"] == "12345678"
    projection = item["normalized"]
    assert projection["title"] == "Synthetic publication title"
    assert projection["authors"] == ["Alex Example", "Synthetic Group"]
    assert projection["publication_date"] == {"value": "2026-08", "precision": "month", "kind": "source_reported"}
    assert item["source_updated"]["value"] == "2026-08-19"
    assert projection["correction_relations"] == [{"relation": "ErratumIn", "external_id": "23456789"}]
    assert projection["abstract_text"].startswith("BACKGROUND: Synthetic background.")
    assert_projection_schema(item)


def test_pubmed_missing_abstract_is_null_and_ambiguous_date_not_a_day():
    xml = (
        b"<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID><Article><ArticleTitle>Synthetic</ArticleTitle>"
        b"<Journal><JournalIssue><PubDate><MedlineDate>2025 Dec-2026 Jan</MedlineDate></PubDate></JournalIssue></Journal>"
        b"</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"
    )
    item = normalize_pubmed(xml)[0]
    assert item["normalized"]["abstract_text"] is None
    assert item["normalized"]["publication_date"]["value"] is None
    assert item["source_updated"]["value"] is None


def test_pubmed_xml_entities_are_rejected():
    xml = b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><PubmedArticleSet>&secret;</PubmedArticleSet>'
    with pytest.raises(SourceError) as exc:
        normalize_pubmed(xml)
    assert exc.value.code == "schema_changed"


def adapter(handler, **kwargs):
    return PharmaSources(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), rate_limits={"ctgov": 0, "pubmed": 0}, **kwargs)


@pytest.mark.asyncio
async def test_search_ctgov_reports_truncation_and_uses_official_token():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"studies": [trial_payload()], "totalCount": 100, "nextPageToken": "opaque-next"})

    async with adapter(handler) as sources:
        result = await sources.search("ctgov", "synthetic query", limit=1, cursor="previous-token")
    assert result["coverage"]["status"] == "truncated"
    assert result["coverage"]["total"] == 100
    assert result["next_cursor"] == "opaque-next"
    assert requests[0].url.host == "clinicaltrials.gov"
    assert requests[0].url.params["pageToken"] == "previous-token"


@pytest.mark.asyncio
async def test_pubmed_search_batches_fetch_and_propagates_missing_records():
    def handler(request):
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"count": "2", "idlist": ["12345678", "23456789"]}})
        assert request.url.params["id"] == "12345678,23456789"
        return httpx.Response(200, content=PUBMED_XML)

    async with adapter(handler) as sources:
        result = await sources.search("pubmed", "synthetic", limit=2)
    assert len(result["items"]) == 1
    assert result["coverage"]["status"] == "partial"
    assert "missing_records" in result["coverage"]["limitations"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("source", "identifier"), [("ctgov", "DEMO-CT-001"), ("pubmed", "DEMO-PM-001"), ("ctgov", "https://127.0.0.1/"), ("pubmed", "1&api_key=x")])
async def test_untrusted_identifiers_never_issue_requests(source, identifier):
    def handler(request):
        pytest.fail("Invalid identifier reached network")

    async with adapter(handler) as sources:
        with pytest.raises(SourceError) as exc:
            await sources.fetch(source, identifier)
    assert exc.value.code == "invalid_request"


@pytest.mark.asyncio
async def test_demo_queries_never_reach_live_sources():
    async with adapter(lambda request: pytest.fail("Demo query reached network")) as sources:
        with pytest.raises(SourceError):
            await sources.search("ctgov", "DEMO-CT-001")


@pytest.mark.asyncio
async def test_retry_after_is_respected_without_leaking_credentials():
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "2"}) if len(calls) == 1 else httpx.Response(200, content=PUBMED_XML)

    async def sleep(delay):
        sleeps.append(delay)

    async with adapter(handler, sleep=sleep, ncbi_api_key="private-test-key") as sources:
        result = await sources.fetch("pubmed", "12345678")
    assert len(calls) == 2
    assert sleeps[0] >= 2
    assert "private-test-key" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "code"), [(404, "not_found"), (403, "auth"), (302, "unsafe_redirect"), (503, "unavailable"), (429, "rate_limited")])
async def test_failures_are_not_empty_successes(status, code):
    async def sleep(_):
        pass

    async with adapter(lambda request: httpx.Response(status, headers={"Location": "http://169.254.169.254/"}), sleep=sleep) as sources:
        with pytest.raises(SourceError) as exc:
            await sources.fetch("ctgov", "NCT00000001")
    assert exc.value.code == code


@pytest.mark.asyncio
async def test_response_size_is_bounded():
    async with adapter(lambda request: httpx.Response(200, content=b"x" * 100), max_response_bytes=50) as sources:
        with pytest.raises(SourceError) as exc:
            await sources.fetch("ctgov", "NCT00000001")
    assert exc.value.code == "response_too_large"


@pytest.mark.asyncio
async def test_mismatched_external_id_cannot_be_bound_to_requested_record():
    raw = copy.deepcopy(trial_payload())
    raw["protocolSection"]["identificationModule"]["nctId"] = "NCT00000002"
    async with adapter(lambda request: httpx.Response(200, json=raw)) as sources:
        with pytest.raises(SourceError) as exc:
            await sources.fetch("ctgov", "NCT00000001")
    assert exc.value.code == "schema_changed"


@pytest.mark.asyncio
async def test_search_cap_cannot_be_bypassed_by_limit_or_pubmed_cursor():
    async with adapter(lambda request: pytest.fail("Invalid budget reached network")) as sources:
        for kwargs in ({"limit": 201}, {"limit": 0}, {"cursor": "200"}):
            with pytest.raises(SourceError) as exc:
                await sources.search("pubmed", "synthetic", **kwargs)
            assert exc.value.code == "invalid_request"


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("DEER_FLOW_RUN_LIVE_TESTS") != "1", reason="Real official API requests require explicit opt-in")
@pytest.mark.parametrize("source", ["ctgov", "pubmed"])
async def test_live_source_search_fetch_contract(source):
    async with PharmaSources() as sources:
        page = await sources.search(source, "metformin", limit=1)
        assert page["items"]
        assert page["coverage"]["status"] in {"complete", "truncated"}
        assert_projection_schema(page["items"][0])
        record = await sources.fetch(source, page["items"][0]["external_id"])
        assert record["external_id"] == page["items"][0]["external_id"]
        assert_projection_schema(record)
