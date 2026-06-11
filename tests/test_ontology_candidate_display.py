from __future__ import annotations

from src.ontology.candidate_display import build_display_metadata, format_candidate_for_practitioner
from src.ontology.review_store import OntologyCandidate


def test_display_metadata_contains_summary_examples_and_prompt() -> None:
    display = build_display_metadata(
        canonical_name="교통사고 상해",
        node_type="ClaimCondition",
        candidate_type="alias_or_expansion",
        similar_expressions=["교통상해", "자동차 사고"],
        source_evidence=[{"doc_short": "약관", "excerpt": "교통사고로 인한 상해"}],
    )

    assert "교통사고 상해" in display["summary"]
    assert display["similar_expressions"] == ["교통상해", "자동차 사고"]
    assert any("교통사고 상해" in item for item in display["example_questions"])
    assert "묶어도 될까요" in display["approval_prompt"]


def test_format_candidate_for_practitioner_uses_display_metadata() -> None:
    candidate = OntologyCandidate(
        candidate_id="cand",
        concept_id="cond.traffic",
        canonical_name="교통사고 상해",
        node_type="ClaimCondition",
        properties={
            "display": {
                "summary": "교통 관련 상해 표현을 묶는 후보입니다.",
                "similar_expressions": ["교통상해"],
                "example_questions": ["교통상해도 교통사고 상해에 포함되나요?"],
                "approval_prompt": "같은 개념으로 묶어도 될까요?",
            }
        },
        source_evidence=[
            {
                "doc_short": "약관",
                "page": 12,
                "excerpt": "교통사고로 인한 상해",
            }
        ],
    )

    text = format_candidate_for_practitioner(candidate)

    assert "후보 개념: 교통사고 상해" in text
    assert "승인 대상 표현(후보 alias)" in text
    assert "교통 관련 상해 표현" in text
    assert "교통상해" in text
    assert "[약관 / 12쪽]" in text


def test_format_candidate_for_practitioner_includes_guide_quality_warning_and_wraps() -> None:
    candidate = OntologyCandidate(
        candidate_id="cand-a",
        concept_id="cov.a",
        canonical_name="A 개념",
        candidate_aliases=["즉 비급여 도수치료"],
        source_evidence=[{"doc_short": "약관", "excerpt": "즉 비급여 도수치료"}],
    )
    other = OntologyCandidate(
        candidate_id="cand-b",
        concept_id="cov.b",
        canonical_name="B 개념",
        candidate_aliases=["즉 비급여 도수치료"],
    )

    text = format_candidate_for_practitioner(candidate, all_candidates=[candidate, other], wrap_width=46)

    assert "승인 대상 표현(후보 alias)" in text
    assert "실무자 판단 기준" in text
    assert "품질 경고" in text
    assert "문장 조각" in text
    assert "여러 후보 concept" in text
    assert "보류한 뒤 target concept" in text
    assert max(len(line) for line in text.splitlines()) <= 46


def test_format_candidate_hides_reference_similar_expressions_when_same_as_aliases() -> None:
    candidate = OntologyCandidate(
        candidate_id="cand",
        concept_id="cov.rider",
        canonical_name="특약",
        candidate_aliases=["특약 등", "운전자한정특약"],
        properties={
            "display": {
                "similar_expressions": ["운전자한정특약", "특약 등"],
                "example_questions": [],
            }
        },
    )

    text = format_candidate_for_practitioner(candidate)

    assert "승인 대상 표현(후보 alias)" in text
    assert "참고 유사 표현" not in text


def test_format_candidate_shows_reference_similar_expressions_when_different_from_aliases() -> None:
    candidate = OntologyCandidate(
        candidate_id="cand",
        concept_id="cov.rider",
        canonical_name="특약",
        candidate_aliases=["특약 등"],
        properties={
            "display": {
                "similar_expressions": ["운전자한정특약"],
                "example_questions": [],
            }
        },
    )

    text = format_candidate_for_practitioner(candidate)

    assert "참고 유사 표현(자동 표시용)" in text
    assert "운전자한정특약" in text
