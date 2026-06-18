from pathlib import Path

from src.graph import extractors


def test_graph_marker_policy_loads_active_manifest() -> None:
    assert "3대비급여 연간 한도" in extractors.BENEFIT_LIMITS
    assert "5세대 실손 공제" in extractors.DEDUCTIBLE_RULES
    assert extractors.BENEFIT_LIMITS["3대비급여 연간 한도"]["marker_only"] is True
    assert extractors.DEDUCTIBLE_RULES["5세대 실손 공제"]["approval_status"] == "active"
    assert extractors.BENEFIT_LIMITS["상급병실료 차액 한도"]["source_refs"][0]["source_chunk_id"]
    assert extractors.SOL_APPENDIX_GRADE_RATIO_MAP["4"]["payment_ratio"] == "100%"


def test_graph_marker_policy_filters_non_active_entries() -> None:
    payload = {
        "benefit_limits": {
            "active": {"approval_status": "active"},
            "pending": {"approval_status": "pending"},
        }
    }

    assert extractors._active_marker_section(payload, "benefit_limits") == {
        "active": {"approval_status": "active"}
    }


def test_graph_marker_values_are_not_inline_extractor_constants() -> None:
    source = Path(extractors.__file__).read_text(encoding="utf-8")

    assert '"3대비급여 연간 한도"' not in source
    assert '"상급병실료 차액 한도"' not in source
    assert '"5세대 실손 공제"' not in source
    assert '"350만원"' not in source
    assert '("10%", 0.1)' not in source
    assert '("30%", 0.3)' not in source
