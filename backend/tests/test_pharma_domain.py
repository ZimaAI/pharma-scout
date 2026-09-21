import pytest

from app.pharma.domain import check_question, differences, extract_quote
from app.pharma.errors import PharmaError


def test_meaningful_changes_and_missing_are_distinct():
    before = {"status": "RECRUITING", "enrollment": {"count": 120, "type": "estimated"}, "source_updated": {"value": "2026-09-14"}}
    after = {"status": "RECRUITING", "enrollment": {"count": 120, "type": "actual"}, "source_updated": {"value": "2026-09-15"}}
    changes = differences(before, after)
    assert [c["path"] for c in changes] == ["/enrollment"]
    assert differences({"enrollment": None}, {})[0]["type"] == "removed"
    assert not differences(before, dict(before))


def test_evidence_pointer_and_codepoint_range():
    snap = {"normalized": {"enrollment": {"count": 120}, "abstract_text": "中文研究"}}
    assert extract_quote(snap, {"kind": "json_pointer", "path": "/normalized/enrollment/count"}) == "120"
    with pytest.raises(PharmaError):
        extract_quote(snap, {"kind": "json_pointer", "path": "/normalized/missing"})


def test_medical_request_boundary_preserves_research():
    check_question("整理公开试验中患者入组数量的变化及证据")
    with pytest.raises(PharmaError):
        check_question("我应该服用多少剂量，请给我用药建议")
