"""Bounded, read-only official source adapters for the PharmaScope domain.

Only identifiers and search terms cross the tool boundary; endpoint selection,
credentials, limits and retry policy remain server owned. These envelopes do
not carry tenant/database identities: the authenticated ingestion service adds
those when persisting a snapshot and its separate observation.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import json
import random
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

CTGOV_BASE = "https://clinicaltrials.gov/api/v2"
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_CANDIDATES = 200
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
NORMALIZER_VERSIONS = {"ctgov": "ctgov-v2-1", "pubmed": "pubmed-xml-1"}
TRIAL_STATUSES = frozenset({"NOT_YET_RECRUITING", "RECRUITING", "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING", "SUSPENDED", "TERMINATED", "COMPLETED", "WITHDRAWN", "UNKNOWN", "OTHER"})
_ID_PATTERNS = {"ctgov": re.compile(r"NCT[0-9]{8}"), "pubmed": re.compile(r"[1-9][0-9]{0,11}")}
_RATE_LOCK = threading.Lock()
_NEXT_REQUEST: dict[str, float] = {}


class SourceError(Exception):
    """Safe structured failure; never includes upstream bodies, URLs or keys."""

    def __init__(self, code: str, message: str, source: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.source = source
        self.retry_after = retry_after

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "source": self.source, "retry_after": self.retry_after}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalize_date(value: str | None, *, kind: str = "source_reported") -> dict[str, Any]:
    """Preserve source precision; invalid/ambiguous values never become dates."""
    unknown = {"value": None, "precision": "unknown", "kind": "unknown"}
    if not isinstance(value, str):
        return unknown
    value = value.strip()
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            date.fromisoformat(value)
            precision = "day"
        elif re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
            date.fromisoformat(value + "-01")
            precision = "month"
        elif re.fullmatch(r"[0-9]{4}", value):
            date(int(value), 1, 1)
            precision = "year"
        else:
            return unknown
    except ValueError:
        return unknown
    return {"value": value, "precision": precision, "kind": kind}


def _validate_source(source: str) -> None:
    if source not in _ID_PATTERNS:
        raise SourceError("invalid_request", "Unsupported official source.", str(source))


def _validate_id(source: str, external_id: str) -> None:
    _validate_source(source)
    if not isinstance(external_id, str) or not _ID_PATTERNS[source].fullmatch(external_id):
        raise SourceError("invalid_request", "Invalid live source identifier; demo identifiers are not accepted.", source)


def _envelope(source: str, external_id: str, raw_payload: dict, normalized: dict, source_updated: dict, fetched_at: str | None) -> dict[str, Any]:
    content = json.dumps(raw_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return {
        "source": source,
        "external_id": external_id,
        "record_type": "trial" if source == "ctgov" else "publication",
        "url": f"https://clinicaltrials.gov/study/{external_id}" if source == "ctgov" else f"https://pubmed.ncbi.nlm.nih.gov/{external_id}/",
        "raw_payload": raw_payload,
        "normalized": normalized,
        "source_updated": source_updated,
        "fetched_at": fetched_at or _now(),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "normalizer_version": NORMALIZER_VERSIONS[source],
        "is_demo": False,
    }


def _object(value: Any) -> dict:
    if not isinstance(value, dict):
        raise TypeError("Expected object")
    return value


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError("Expected string array")
    return value


def _text_or_none(value: Any) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError("Expected text")
    return value


def normalize_ctgov(payload: dict[str, Any], *, fetched_at: str | None = None) -> dict[str, Any]:
    """Map the API v2 study to the contracted projection; retain original JSON."""
    try:
        protocol = _object(payload["protocolSection"])
        identity = _object(protocol["identificationModule"])
        external_id = identity["nctId"]
        _validate_id("ctgov", external_id)
        title = identity["briefTitle"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Missing title")
        status = _object(protocol.get("statusModule", {}))
        raw_status = _text_or_none(status.get("overallStatus"))
        updated = normalize_date(_object(status.get("lastUpdatePostDateStruct", {})).get("date"))
        design = _object(protocol.get("designModule", {}))
        enrollment_raw = design.get("enrollmentInfo")
        enrollment = None
        if enrollment_raw is not None:
            enrollment_raw = _object(enrollment_raw)
            count = enrollment_raw.get("count")
            if count is not None:
                if type(count) is not int or count < 0:
                    raise ValueError("Invalid enrollment")
                enrollment_type = enrollment_raw.get("type", "UNKNOWN")
                enrollment = {"count": count, "type": {"ESTIMATED": "estimated", "ACTUAL": "actual"}.get(enrollment_type, "unknown")}
        has_results = payload.get("hasResults")
        if has_results is not None and type(has_results) is not bool:
            raise ValueError("Invalid results flag")
        outcomes = _object(protocol.get("outcomesModule", {})).get("primaryOutcomes", [])
        if not isinstance(outcomes, list):
            raise TypeError("Invalid outcomes")
        primary_outcomes = []
        for item in outcomes:
            item = _object(item)
            measure = item["measure"]
            if not isinstance(measure, str):
                raise TypeError("Invalid outcome measure")
            primary_outcomes.append({"measure": measure, "description": _text_or_none(item.get("description")), "time_frame": _text_or_none(item.get("timeFrame"))})
        sponsor = _object(_object(protocol.get("sponsorCollaboratorsModule", {})).get("leadSponsor", {})).get("name")
        interventions = []
        for intervention in _object(protocol.get("armsInterventionsModule", {})).get("interventions", []):
            intervention = _object(intervention)
            if not isinstance(intervention.get("name"), str):
                raise ValueError("Invalid intervention name")
            interventions.append(
                {"name": intervention["name"], "type": _text_or_none(intervention.get("type")), "description": _text_or_none(intervention.get("description")), "arm_group_labels": _strings(intervention.get("armGroupLabels", []))}
            )
        normalized = {
            "title": title,
            "raw_status": raw_status,
            "status": raw_status if raw_status in TRIAL_STATUSES else ("UNKNOWN" if raw_status is None else "OTHER"),
            "phases": sorted(set(_strings(design.get("phases", [])))),
            "conditions": sorted(set(_strings(_object(protocol.get("conditionsModule", {})).get("conditions", [])))),
            "sponsor": _text_or_none(sponsor),
            "enrollment": enrollment,
            "has_results": has_results,
            "source_updated": updated,
            "primary_outcomes": primary_outcomes,
            "interventions": interventions,
        }
        for field, upstream in (("start_date", "startDateStruct"), ("primary_completion_date", "primaryCompletionDateStruct"), ("completion_date", "completionDateStruct")):
            raw_date = _object(status.get(upstream, {}))
            normalized[field] = normalize_date(raw_date.get("date"), kind={"ESTIMATED": "estimated", "ACTUAL": "actual"}.get(raw_date.get("type"), "source_reported"))
        return _envelope("ctgov", external_id, payload, normalized, updated, fetched_at)
    except (KeyError, TypeError, ValueError, SourceError) as exc:
        raise SourceError("schema_changed", "ClinicalTrials.gov response does not match the supported schema.", "ctgov") from exc


def _xml_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    return "".join(element.itertext()).strip() or None


def _xml_date(element: ET.Element | None) -> dict[str, Any]:
    if element is None:
        return normalize_date(None)
    year = _xml_text(element.find("Year"))
    month = _xml_text(element.find("Month"))
    day = _xml_text(element.find("Day"))
    if year is None:
        # MedlineDate can contain seasons/ranges. Only an unambiguous ISO year
        # is usable without inventing precision; the original remains in XML.
        return normalize_date(_xml_text(element.find("MedlineDate")))
    if month:
        months = {name.lower(): index for index, name in enumerate(calendar.month_abbr) if name}
        if month.isdigit() and 1 <= int(month) <= 12:
            month_number = int(month)
        else:
            month_number = months.get(month.lower()[:3])
        if month_number is None:
            return normalize_date(year)
        value = f"{year}-{month_number:02d}"
        if day:
            if not day.isdigit():
                return normalize_date(None)
            value += f"-{int(day):02d}"
        return normalize_date(value)
    return normalize_date(year)


def normalize_pubmed(payload: bytes | str, *, fetched_at: str | None = None) -> list[dict[str, Any]]:
    """Read article metadata/abstracts only; no external DTD or entity loading."""
    try:
        xml = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
        if "\x00" in xml or "<!ENTITY" in xml:
            raise ValueError("Unsupported XML entity/encoding")
        root = ET.fromstring(xml)
        if root.tag != "PubmedArticleSet" or root.find(".//ERROR") is not None:
            raise ValueError("Invalid article response")
        items = []
        for entry in root:
            if entry.tag != "PubmedArticle":
                # Book records have a different schema. Fail visibly rather
                # than returning an apparently complete set of articles.
                raise ValueError("Unsupported PubMed record kind")
            citation = entry.find("MedlineCitation")
            if citation is None:
                raise ValueError("Missing citation")
            external_id = _xml_text(citation.find("PMID"))
            _validate_id("pubmed", external_id)
            article = citation.find("Article")
            if article is None:
                raise ValueError("Missing article")
            title = _xml_text(article.find("ArticleTitle"))
            if title is None:
                raise ValueError("Missing title")
            authors = []
            for author in article.findall("AuthorList/Author"):
                name = _xml_text(author.find("CollectiveName"))
                if not name:
                    name = " ".join(part for part in (_xml_text(author.find("ForeName")) or _xml_text(author.find("Initials")), _xml_text(author.find("LastName"))) if part)
                if name:
                    authors.append(name)
            abstract = []
            for fragment in article.findall("Abstract/AbstractText"):
                text = _xml_text(fragment)
                if text:
                    label = fragment.get("Label")
                    abstract.append(f"{label}: {text}" if label else text)
            doi = None
            for identifier in entry.findall("PubmedData/ArticleIdList/ArticleId"):
                if identifier.get("IdType") == "doi":
                    doi = _xml_text(identifier)
                    break
            corrections = []
            for correction in citation.findall("CommentsCorrectionsList/CommentsCorrections"):
                target_id = _xml_text(correction.find("PMID"))
                relation = correction.get("RefType")
                if target_id and relation:
                    _validate_id("pubmed", target_id)
                    corrections.append({"relation": relation, "external_id": target_id})
            publication_date = _xml_date(article.find("Journal/JournalIssue/PubDate"))
            if publication_date["precision"] == "unknown":
                electronic = article.find("ArticleDate[@DateType='Electronic']")
                if electronic is not None:
                    publication_date = _xml_date(electronic)
            normalized = {
                "title": title,
                "authors": authors,
                "journal": _xml_text(article.find("Journal/Title")) or _xml_text(article.find("Journal/ISOAbbreviation")),
                "doi": doi,
                "pmid": external_id,
                "publication_date": publication_date,
                "abstract_text": "\n".join(abstract) or None,
                "publication_types": sorted(set(filter(None, (_xml_text(item) for item in article.findall("PublicationTypeList/PublicationType"))))),
                "correction_relations": corrections,
            }
            updated = _xml_date(citation.find("DateRevised"))
            # Isolate this article from the batch; ordering of other returned
            # articles must not change its content identity.
            raw = {"xml": ET.tostring(entry, encoding="unicode")}
            items.append(_envelope("pubmed", external_id, raw, normalized, updated, fetched_at))
        return items
    except (ET.ParseError, UnicodeError, TypeError, ValueError, SourceError) as exc:
        raise SourceError("schema_changed", "PubMed response does not match the supported XML schema.", "pubmed") from exc


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        if seconds >= 0 and seconds < float("inf"):
            return seconds
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
        return max(0.0, (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


class PharmaSources:
    """One request scope of clients; rate reservations are shared process-wide.

    ``rate_limits`` is a server/test override in seconds between requests. The
    deployment uses one Gateway process; multiple processes need a shared egress
    limiter to keep the aggregate budget. Credentials are never in envelopes.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        ncbi_api_key: str | None = None,
        ncbi_email: str | None = None,
        ncbi_tool: str = "pharmascope",
        rate_limits: dict[str, float] | None = None,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        request_budget: float = 60.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False, trust_env=False, headers={"User-Agent": "PharmaScope/1.0 (public research metadata)"})
        self._ncbi_params = {"db": "pubmed", "tool": ncbi_tool}
        if ncbi_api_key:
            self._ncbi_params["api_key"] = ncbi_api_key
        if ncbi_email:
            self._ncbi_params["email"] = ncbi_email
        self._rate_limits = rate_limits if rate_limits is not None else {"ctgov": 1.0, "pubmed": 0.2 if ncbi_api_key else 0.5}
        self._max_response_bytes = max_response_bytes
        self._request_budget = request_budget
        self._sleep = sleep

    async def __aenter__(self) -> PharmaSources:
        return self

    async def __aexit__(self, *_args) -> None:
        await self._client.aclose()

    async def _throttle(self, source: str) -> None:
        interval = self._rate_limits.get(source, 1.0)
        if interval <= 0:
            return
        # A tiny in-memory reservation works across event loops without an
        # event-loop-bound lock. The wait itself never blocks the event loop.
        with _RATE_LOCK:
            now = time.monotonic()
            slot = max(now, _NEXT_REQUEST.get(source, now))
            _NEXT_REQUEST[source] = slot + interval
        if slot > now:
            await self._sleep(slot - now)

    async def _request(self, source: str, path: str, params: dict[str, Any]) -> bytes:
        base = CTGOV_BASE if source == "ctgov" else PUBMED_BASE
        deadline = time.monotonic() + self._request_budget
        try:
            async with asyncio.timeout(self._request_budget):
                for attempt in range(3):
                    await self._throttle(source)
                    error = None
                    try:
                        async with self._client.stream("GET", base + path, params=params, follow_redirects=False) as response:
                            status = response.status_code
                            if 300 <= status < 400:
                                raise SourceError("unsafe_redirect", "Official source redirected; redirects are disabled.", source)
                            if status == 404:
                                raise SourceError("not_found", "Official source record was not found.", source)
                            if status in {401, 403}:
                                raise SourceError("auth", "Official source denied access.", source)
                            if status == 429 or status >= 500:
                                code = "rate_limited" if status == 429 else "unavailable"
                                error = SourceError(code, "Official source request could not be completed.", source, retry_after=_retry_after(response.headers.get("Retry-After")))
                            elif status >= 400:
                                raise SourceError("invalid_request", "Official source rejected the query.", source)
                            else:
                                length = response.headers.get("Content-Length", "")
                                if length.isdigit() and int(length) > self._max_response_bytes:
                                    raise SourceError("response_too_large", "Official source response exceeds the size limit.", source)
                                chunks = []
                                total = 0
                                async for chunk in response.aiter_bytes():
                                    total += len(chunk)
                                    if total > self._max_response_bytes:
                                        raise SourceError("response_too_large", "Official source response exceeds the size limit.", source)
                                    chunks.append(chunk)
                                return b"".join(chunks)
                    except httpx.TimeoutException:
                        error = SourceError("timeout", "Official source request timed out.", source)
                    except httpx.HTTPError:
                        error = SourceError("unavailable", "Official source is unavailable.", source)
                    if attempt == 2:
                        raise error
                    delay = max(2**attempt, error.retry_after or 0.0) + random.uniform(0.0, 0.25)
                    if time.monotonic() + delay >= deadline:
                        raise error
                    await self._sleep(delay)
        except TimeoutError as exc:
            raise SourceError("timeout", "Official source exceeded the total request budget.", source) from exc
        raise SourceError("unavailable", "Official source is unavailable.", source)

    async def _json(self, source: str, path: str, params: dict[str, Any]) -> dict:
        raw = await self._request(source, path, params)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
            if "error" in payload:
                raise SourceError("unavailable", "Official source returned an error payload.", source)
            return payload
        except (ValueError, UnicodeError) as exc:
            raise SourceError("schema_changed", "Official source returned invalid JSON.", source) from exc

    async def fetch(self, source: str, external_id: str) -> dict[str, Any]:
        _validate_id(source, external_id)
        if source == "ctgov":
            payload = await self._json(source, "/studies/" + external_id, {"format": "json"})
            result = normalize_ctgov(payload)
        else:
            raw = await self._request(source, "/efetch.fcgi", {**self._ncbi_params, "id": external_id, "retmode": "xml"})
            items = normalize_pubmed(raw)
            if not items:
                raise SourceError("not_found", "PubMed record was not found.", source)
            if len(items) != 1:
                raise SourceError("schema_changed", "PubMed returned an unexpected record count.", source)
            result = items[0]
        if result["external_id"] != external_id:
            raise SourceError("schema_changed", "Official source returned a different record identifier.", source)
        return result

    async def search(self, source: str, query: str, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        _validate_source(source)
        if not isinstance(query, str) or not query.strip() or len(query) > 1000 or re.search(r"\bDEMO[-_]", query, re.IGNORECASE):
            raise SourceError("invalid_request", "Provide a bounded live query without demo identifiers.", source)
        if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
            raise SourceError("invalid_request", "Search limit must be between 1 and 200.", source)
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 4096):
            raise SourceError("invalid_request", "Invalid source cursor.", source)
        try:
            async with asyncio.timeout(self._request_budget):
                return await self._search(source, query.strip(), limit, cursor)
        except TimeoutError as exc:
            raise SourceError("timeout", "Official source search exceeded its request budget.", source) from exc

    async def _search(self, source: str, query: str, limit: int, cursor: str | None) -> dict[str, Any]:
        limitations = []
        try:
            if source == "ctgov":
                params = {"query.term": query, "format": "json", "pageSize": limit, "countTotal": "true"}
                if cursor:
                    params["pageToken"] = cursor
                payload = await self._json(source, "/studies", params)
                studies = payload["studies"]
                if not isinstance(studies, list) or len(studies) > limit:
                    raise ValueError("Invalid studies array")
                observed = _now()
                items = [normalize_ctgov(item, fetched_at=observed) for item in studies]
                total = payload.get("totalCount")
                next_cursor = payload.get("nextPageToken")
                if total is not None and (type(total) is not int or total < 0):
                    raise ValueError("Invalid total count")
                if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 4096):
                    raise ValueError("Invalid page token")
                truncated = bool(next_cursor) or (total is not None and total > len(items))
            else:
                if cursor is not None and (not re.fullmatch(r"[0-9]{1,3}", cursor) or int(cursor) >= MAX_CANDIDATES):
                    raise SourceError("invalid_request", "PubMed cursor exceeds the 200-candidate query budget.", source)
                offset = int(cursor or "0")
                page_size = min(limit, MAX_CANDIDATES - offset)
                payload = await self._json(source, "/esearch.fcgi", {**self._ncbi_params, "term": query, "retmax": page_size, "retstart": offset, "retmode": "json", "sort": "pub_date"})
                result = _object(payload["esearchresult"])
                if result.get("ERROR") or result.get("errorlist"):
                    raise SourceError("invalid_request", "PubMed could not interpret the source query.", source)
                total = int(result["count"])
                identifiers = _strings(result["idlist"])
                if total < 0 or len(identifiers) > page_size or len(set(identifiers)) != len(identifiers):
                    raise ValueError("Invalid candidate list")
                for external_id in identifiers:
                    _validate_id(source, external_id)
                items = []
                if identifiers:
                    raw = await self._request(source, "/efetch.fcgi", {**self._ncbi_params, "id": ",".join(identifiers), "retmode": "xml"})
                    items = normalize_pubmed(raw, fetched_at=_now())
                    returned = {item["external_id"] for item in items}
                    if len(returned) != len(items) or not returned.issubset(set(identifiers)):
                        raise ValueError("Unexpected returned IDs")
                    if len(returned) < len(identifiers):
                        limitations.append("missing_records")
                next_offset = offset + len(identifiers)
                truncated = total > next_offset
                next_cursor = str(next_offset) if truncated and next_offset < MAX_CANDIDATES and identifiers else None
                if total > MAX_CANDIDATES:
                    limitations.append("candidate_limit_200")
                if not identifiers and offset < total:
                    limitations.append("missing_records")
            if truncated:
                limitations.append("query_truncated_narrow_scope")
            return {
                "items": items,
                "coverage": {"source": source, "status": "partial" if "missing_records" in limitations else "truncated" if truncated else "complete", "retrieved": len(items), "total": total, "limitations": limitations},
                "next_cursor": next_cursor,
                "request_meta": {"source": source, "operation": "search", "candidate_limit": MAX_CANDIDATES, "cache_hit": False},
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError("schema_changed", "Official source search response changed schema.", source) from exc

    async def health(self, source: str) -> dict[str, Any]:
        """Perform a small real request, returning explicit availability/error."""
        _validate_source(source)
        checked_at = _now()
        try:
            if source == "ctgov":
                await self._json(source, "/version", {})
            else:
                await self._json(source, "/einfo.fcgi", {**self._ncbi_params, "retmode": "json"})
        except SourceError as exc:
            return {"source": source, "status": "unavailable", "checked_at": checked_at, "error": exc.to_dict()}
        return {"source": source, "status": "available", "checked_at": checked_at, "error": None}


async def search(source: str, query: str, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
    async with PharmaSources() as adapter:
        return await adapter.search(source, query, limit, cursor)


async def fetch(source: str, external_id: str) -> dict[str, Any]:
    async with PharmaSources() as adapter:
        return await adapter.fetch(source, external_id)
