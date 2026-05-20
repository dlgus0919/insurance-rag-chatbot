from src.parser.chunker import Chunk
from src.rag.evidence import (
    append_evidence_validation_warning,
    build_strict_evidence_context,
    extract_code_evidence_facts,
    is_strict_evidence_query,
)


def _chunk(doc_short: str, page: int, text: str) -> Chunk:
    return Chunk(
        id=f"{doc_short}_{page}",
        text=text,
        metadata={"doc_short": doc_short, "page_start": page, "page_end": page},
    )


def test_strict_evidence_query_detects_code_comparison() -> None:
    assert is_strict_evidence_query("로봇 수술에 대한 코드를 문서별로 알려주세요") is True
    assert is_strict_evidence_query("계약 전 알릴 의무란?") is False


def test_extract_code_evidence_preserves_source_specific_robot_surgery_codes() -> None:
    chunks = [
        _chunk(
            "심평원",
            812,
            "분류번호 코 드 분 류\n"
            "조-961 QZ966 로봇 보조 수술 Robot-assisted Surgery\n"
            "조-962 QZ962 경두개자기자극술 Transcranial Magnetic Stimulation\n"
            "조-963 QZ965 열처리된 우유/계란을 이용한 경구면역요법",
        ),
        _chunk(
            "자사_SOL건강",
            300,
            "내용 수가코드\n로봇 보조 수술[시술시 소요재료 포함] QZ961\n- 다빈치 기기da Vinci",
        ),
    ]

    facts = extract_code_evidence_facts("로봇 수술에 대한 코드를 문서별로 검색하여 각각 알려주세요.", chunks)

    assert [(fact.doc_short, fact.code) for fact in facts] == [("심평원", "QZ966"), ("자사_SOL건강", "QZ961")]
    assert facts[0].classification_no == "조-961"
    assert "로봇 보조 수술" in facts[0].description


def test_build_strict_evidence_context_explains_not_to_unify_values() -> None:
    chunks = [_chunk("심평원", 812, "조-961 QZ966 로봇 보조 수술 Robot-assisted Surgery")]

    context = build_strict_evidence_context("로봇 수술 코드를 알려주세요", chunks)

    assert context is not None
    assert "문서별 값이 다르면 절대 통일하지 말고" in context
    assert "코드: QZ966" in context
    assert "분류번호: 조-961" in context


def test_append_evidence_validation_warning_flags_source_code_mismatch() -> None:
    chunks = [
        _chunk("심평원", 812, "조-961 QZ966 로봇 보조 수술 Robot-assisted Surgery"),
        _chunk("자사_SOL건강", 300, "로봇 보조 수술[시술시 소요재료 포함] QZ961"),
    ]
    answer = "| 심평원 | QZ961 | 로봇 보조 수술 |\n| 자사_SOL건강 | QZ961 | 다빈치로봇 수술 |"

    checked = append_evidence_validation_warning(answer, "로봇 수술에 대한 코드를 문서별로 알려주세요", chunks)

    assert "[근거 검증 경고]" in checked
    assert "심평원 근거에서 확인된 코드는 QZ966" in checked


def test_append_evidence_validation_warning_keeps_correct_source_codes() -> None:
    chunks = [
        _chunk("심평원", 812, "조-961 QZ966 로봇 보조 수술 Robot-assisted Surgery"),
        _chunk("자사_SOL건강", 300, "로봇 보조 수술[시술시 소요재료 포함] QZ961"),
    ]
    answer = "| 심평원 | QZ966 | 로봇 보조 수술 |\n| 자사_SOL건강 | QZ961 | 다빈치로봇 수술 |"

    checked = append_evidence_validation_warning(answer, "로봇 수술에 대한 코드를 문서별로 알려주세요", chunks)

    assert "[근거 검증 경고]" not in checked
