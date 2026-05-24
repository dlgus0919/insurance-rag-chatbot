import pytest
import re
from pathlib import Path
from dataclasses import dataclass

from scripts.eval_chatbot_model_index_matrix import (
    MATRIX_COLUMNS,
    _page_hit,
    _expected_source_recall,
    _split_csv,
    _matches_filter,
    matrix_id_for,
    _normalize_for_match,
    _contains_all,
    _contains_any,
    _contains_no_any,
    _regex_all,
    _line_contains_doc_and_term,
    _answer_contains_doc_and_term,
    _by_doc_ok,
    _forbidden_by_doc_ok,
    _min_docs_ok,
    _output_health_ok,
    evaluate_answer,
    classify_defect_type,
    _top_sources,
    CaseResult,
    score_weight_for_category,
    weighted_score,
)

@dataclass
class MockChunk:
    text: str
    metadata: dict

def test_page_hit():
    # hit에 metadata['page_start']와 metadata['page_end']가 있고, pages 리스트 중 하나라도 범위에 포함되는지 확인
    hit = MockChunk("test", {"page_start": 5, "page_end": 7})
    assert _page_hit(hit, [6]) is True
    assert _page_hit(hit, [4, 8]) is False
    assert _page_hit(hit, [5]) is True
    assert _page_hit(hit, [7]) is True

def test_expected_source_recall():
    hits = [
        MockChunk("test", {"doc_short": "policy", "page_start": 3, "page_end": 5}),
        MockChunk("test2", {"doc_short": "hira", "page_start": 10, "page_end": 12}),
    ]

    expected_sources_ok = [
        {"doc_short": "policy", "pages": [4]},
        {"doc_short": "hira", "pages": [11]}
    ]
    assert _expected_source_recall(hits, expected_sources_ok) is True

    expected_sources_fail = [
        {"doc_short": "policy", "pages": [6]}
    ]
    assert _expected_source_recall(hits, expected_sources_fail) is False

def test_normalize_for_match():
    assert _normalize_for_match("AA‐BB") == "AA-BB" # hyphens
    assert _normalize_for_match("99 %") == "99%" # spaces before %
    assert _normalize_for_match("hello   world") == "hello world" # multiple spaces
    assert _normalize_for_match("**1-3종**: 2종") == "1-3종: 2종"

def test_contains_logic():
    answer = "AA-BB의 수술종수는 1종이며 99% 확률입니다."
    assert _contains_all(answer, ["AA‐BB", "1종"]) is True
    assert _contains_all(answer, ["AA‐BB", "2종"]) is False

    assert _contains_any(answer, ["2종", "99 %"]) is True
    assert _contains_any(answer, ["2종", "3종"]) is False

    assert _contains_no_any(answer, ["2종", "3종"]) is True
    assert _contains_no_any(answer, ["1종"]) is False

def test_regex_all():
    answer = "전신성 복막염 수술"
    assert _regex_all(answer, [r"전신성", r"복막염"]) is True
    assert _regex_all(answer, [r"전신성", r"맹장염"]) is False
    assert _regex_all("**1-3종**: 2종", [r"1-3종\s*[:=은는 ]*\s*2종?"]) is True

def test_line_contains_doc_and_term():
    answer = "심평원 문서에 따르면 AA157 항목의 점수는 100점입니다.\n자사 약관에서는 보장하지 않습니다."
    assert _line_contains_doc_and_term(answer, "심평원", "AA157") is True
    assert _line_contains_doc_and_term(answer, "약관", "BB999") is False
    assert _line_contains_doc_and_term("심평원 기준 QZ966\n자사_SOL건강 기준 QZ961", "심평원", "QZ961") is False
    assert _answer_contains_doc_and_term("식도조루술은 Q2333입니다.\n[출처: 심평원, p.531]", "심평원", "Q2333") is True

def test_output_health_ok():
    # 너무 짧으면 False
    assert _output_health_ok("short") is False
    # <pad> 토큰 반복되면 False
    assert _output_health_ok("정상 답변입니다. <pad> <pad> <pad> <pad>") is False
    # 출처 제외 본문이 너무 짧으면 False
    assert _output_health_ok("[출처: 약관 p.3] 네") is False
    # 동일 토큰 과다 반복 False
    bad_repeat = " ".join(["동일토큰"] * 15)
    assert _output_health_ok(bad_repeat) is False
    # 정상
    assert _output_health_ok("이것은 RAG 시스템에서 출력하는 아주 정상적인 답변 본문입니다. [출처: 약관 p.3]") is True

def test_classify_defect_type():
    case = {"id": "qa2_smoke_001_hira_known_code"}

    # 1. retrieval_miss
    checks = {"retrieval_expected_sources": False}
    assert classify_defect_type(case, checks, None) == "retrieval_miss"

    # 2. citation_missing
    checks = {"retrieval_expected_sources": True, "source_citation": False}
    assert classify_defect_type(case, checks, None) == "citation_missing"

    # 3. empty_or_bad_output
    checks = {"retrieval_expected_sources": True, "source_citation": True, "output_health": False}
    assert classify_defect_type(case, checks, None) == "empty_or_bad_output"

    # 4. wrong_code_or_score (HIRA 관련 문항에서 term 누락)
    checks = {
        "retrieval_expected_sources": True,
        "source_citation": True,
        "output_health": True,
        "no_evidence_warning": True,
        "required_terms": False
    }
    assert classify_defect_type(case, checks, None) == "wrong_code_or_score"

    # 5. prompt_injection_followed
    checks = {
        "retrieval_expected_sources": True,
        "source_citation": True,
        "output_health": True,
        "no_evidence_warning": False
    }
    assert classify_defect_type(case, checks, None) == "prompt_injection_followed"

@dataclass
class MockHit:
    document: str
    metadata: dict

def test_top_sources():
    # Chunk object test (has 'text')
    chunks = [MockChunk("RAG text content", {"doc_short": "policy", "page_start": 3, "page_end": 5})]
    res = _top_sources(chunks)
    assert res[0]["preview"] == "RAG text content"
    assert res[0]["doc_short"] == "policy"

    # Hit object test (has 'document')
    hits = [MockHit("Hit document content", {"doc_short": "hira", "page_start": 10, "page_end": 10})]
    res_hit = _top_sources(hits)
    assert res_hit[0]["preview"] == "Hit document content"
    assert res_hit[0]["doc_short"] == "hira"


def test_cli_filter_helpers_and_matrix_ids():
    assert _split_csv("auto, manual,auto") == ["auto", "manual"]
    assert _matches_filter("smoke", ["all"]) is True
    assert _matches_filter("smoke", ["smoke", "hard"]) is True
    assert _matches_filter("standard", ["smoke", "hard"]) is False
    assert matrix_id_for("default", "vllm", "gemma-4-26b-a4b-nvfp4") == "default__vllm_gemma4"
    assert matrix_id_for("v2_only", "sglang", "gpt-oss-20b") == "v2_only__sglang_gpt_oss_20b"
    assert "v1_v2_combined__sglang_gpt_oss_20b" in MATRIX_COLUMNS


def _result(category: str, passed: bool, eligible: bool = True, error: str | None = None) -> CaseResult:
    return CaseResult(
        label="unit",
        case_id=f"case_{category}",
        category=category,
        question="q",
        difficulty="standard",
        review_type="auto",
        index_mode="default",
        matrix_id="default__vllm_gemma4",
        provider="vllm",
        model="gemma-4-26b-a4b-nvfp4",
        eligible=eligible,
        passed=passed,
        checks={},
        failures=[],
        answer="answer",
        top_sources=[],
        timing={},
        defect_type=None,
        error=error,
    )


def test_weighted_score_prioritizes_safety_and_structured_values():
    results = [
        _result("safety_legal_advice", True),
        _result("single_doc_hira_code_table", False),
        _result("unknown_category", True),
        _result("negative_control", True, eligible=False),
        _result("safety_prompt_injection", True, error="endpoint failed"),
    ]

    assert score_weight_for_category("safety_legal_advice") == 4
    assert score_weight_for_category("single_doc_hira_code_table") == 3
    assert score_weight_for_category("unknown_category") == 2
    earned, total, score = weighted_score(results)
    assert earned == 6
    assert total == 13
    assert score == pytest.approx(46.1538461538)
