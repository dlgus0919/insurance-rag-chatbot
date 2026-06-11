from __future__ import annotations

import json
import textwrap
from typing import Any

from src.ontology.candidate_quality import CandidateQualityIssue, analyze_candidate_quality
from src.ontology.review_store import OntologyCandidate


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def unique_strings(values: list[str], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in result:
            result.append(text)
        if limit is not None and len(result) >= limit:
            break
    return result


def build_example_questions(
    *,
    canonical_name: str,
    node_type: str,
    similar_expressions: list[str],
    candidate_type: str,
    limit: int = 3,
) -> list[str]:
    name = _clean_text(canonical_name)
    first_similar = unique_strings(similar_expressions, limit=1)
    similar = first_similar[0] if first_similar else name

    if node_type == "Disease":
        questions = [
            f"{name} 진단을 받으면 어떤 담보를 확인해야 하나요?",
            f"{similar}도 {name}에 포함되나요?",
        ]
    elif node_type == "Procedure":
        questions = [
            f"{name}은 수술비 보장 대상인지 확인할 수 있나요?",
            f"{similar}도 {name}과 같은 처치로 보면 되나요?",
        ]
    elif node_type == "RequiredDocument":
        questions = [
            f"{name} 청구에는 어떤 서류가 필요한가요?",
            f"{similar} 관련 청구 서류도 함께 확인할 수 있나요?",
        ]
    elif candidate_type == "search_query_expansion":
        questions = [
            f"{name} 관련 약관 근거를 찾아줘",
            f"{similar} 표현으로 검색해도 {name} 관련 답변을 받을 수 있나요?",
        ]
    else:
        questions = [
            f"{name}에 해당하면 보험금을 받을 수 있나요?",
            f"{similar}도 {name}에 포함되나요?",
        ]
    return unique_strings(questions, limit=limit)


def build_display_metadata(
    *,
    canonical_name: str,
    node_type: str,
    candidate_type: str,
    similar_expressions: list[str],
    source_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    expressions = unique_strings(similar_expressions, limit=8)
    evidence = source_evidence[0] if source_evidence else {}
    doc_name = _clean_text(evidence.get("doc_short") or evidence.get("doc_name"))
    summary_suffix = "원문 근거에서 반복 확인된 표현을 기존 보험 업무 개념에 함께 묶어 검색하기 위한 후보입니다."
    if candidate_type == "evidence_tag":
        summary_suffix = "원문 근거를 더 잘 찾기 위해 evidence tag를 보강하는 후보입니다."
    elif candidate_type == "search_query_expansion":
        summary_suffix = "사용자 질문 표현과 약관 표현의 차이를 줄이기 위한 검색 확장 후보입니다."

    if doc_name:
        summary = f"{canonical_name} 관련 표현을 {doc_name} 근거와 연결합니다. {summary_suffix}"
    else:
        summary = f"{canonical_name} 관련 표현을 연결합니다. {summary_suffix}"

    return {
        "summary": summary,
        "similar_expressions": expressions,
        "example_questions": build_example_questions(
            canonical_name=canonical_name,
            node_type=node_type,
            similar_expressions=expressions,
            candidate_type=candidate_type,
        ),
        "approval_prompt": "위 표현들을 같은 보험 업무 개념으로 묶어도 될까요?",
    }


PRACTITIONER_DECISION_GUIDE = [
    "승인: 승인 대상 표현이 후보 개념과 같은 보험 업무 개념을 가리키고, 원문 근거의 사용 맥락도 그 개념과 맞으며, 다른 개념으로 해석될 가능성이 낮을 때 선택합니다.",
    "보류: 승인 대상 표현 자체는 쓸 만하지만 원문 근거가 다른 개념과 섞여 있거나, 소유권 충돌/문장 조각/추가 근거 확인이 필요할 때 선택합니다.",
    "거절: 승인 대상 표현이 너무 넓거나 지급·면책·감액·계산 판단으로 이어지거나, 후보 개념과 연결이 잘못됐거나, 단순 문장 조각일 때 선택합니다.",
    "근거는 후보 개념과 연결이 어긋났지만 승인 대상 표현은 적절해 보이면 바로 승인하지 말고 보류한 뒤 target concept 또는 표현 정제를 요청합니다.",
]


def _format_quality_issues(issues: list[CandidateQualityIssue]) -> list[str]:
    if not issues:
        return ["- 감지된 중복 후보/소유권 충돌/문장 조각 경고가 없습니다."]
    lines: list[str] = []
    for issue in issues:
        prefix = "주의" if issue.severity == "warning" else "차단"
        lines.append(f"- [{prefix}] {issue.message}")
        if issue.related:
            lines.append(f"  관련 후보: {', '.join(issue.related)}")
        if issue.recommendation:
            lines.append(f"  권장 판단: {issue.recommendation}")
    return lines


def _format_bullets(values: list[str]) -> list[str]:
    items = unique_strings(values)
    if not items:
        return ["-"]
    return [f"- {item}" for item in items]


def wrap_display_text(text: str, *, width: int = 82) -> str:
    if width <= 0:
        return text
    wrapped: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            wrapped.append("")
            continue
        indent = ""
        stripped = line
        if line.startswith("- "):
            indent = "  "
        elif line.startswith("  "):
            indent = "  "
            stripped = line.strip()
        wrapped.extend(
            textwrap.wrap(
                stripped,
                width=width,
                subsequent_indent=indent,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [line]
        )
    return "\n".join(wrapped)


def format_candidate_for_practitioner(
    candidate: OntologyCandidate,
    *,
    include_details: bool = False,
    all_candidates: list[OntologyCandidate] | None = None,
    wrap_width: int | None = 82,
) -> str:
    display = candidate.properties.get("display") if isinstance(candidate.properties.get("display"), dict) else {}
    evidence = candidate.source_evidence[0] if candidate.source_evidence else {}
    doc = _clean_text(evidence.get("doc_short") or evidence.get("doc_name")) or "-"
    page = _clean_text(evidence.get("page"))
    excerpt = _clean_text(evidence.get("excerpt")) or "-"
    page_text = f" / {page}쪽" if page else ""
    similar = display.get("similar_expressions") if isinstance(display.get("similar_expressions"), list) else []
    questions = display.get("example_questions") if isinstance(display.get("example_questions"), list) else []

    lines = [
        f"후보 개념: {candidate.canonical_name}",
        f"후보 ID: {candidate.candidate_id}",
        f"대상 concept: {candidate.concept_id}",
        "",
        "승인 대상 표현(후보 alias):",
        "아래 표현들을 이 후보 개념에 검색 alias/보강 표현으로 붙여도 되는지 판단합니다.",
        *_format_bullets(candidate.candidate_aliases),
        "",
        "설명:",
        _clean_text(display.get("summary")) or "-",
        "",
        "실무자 판단 기준:",
        *[f"- {item}" for item in PRACTITIONER_DECISION_GUIDE],
        "",
        "품질 경고:",
        *_format_quality_issues(
            analyze_candidate_quality(
                candidate,
                all_candidates=all_candidates,
            )
        ),
        "",
        "참고 유사 표현(자동 표시용):",
        "승인 대상과 같을 수 있지만, 화면 설명/예시 질문 생성을 위해 별도로 보관된 참고 표현입니다.",
        *_format_bullets([str(item) for item in similar]),
        "",
        "예시 질문:",
    ]
    if questions:
        lines.extend(f"- {_clean_text(question)}" for question in questions)
    else:
        lines.append("-")
    lines.extend(
        [
            "",
            "원문 근거:",
            f"[{doc}{page_text}]",
            f"\"{excerpt}\"",
            "",
            _clean_text(display.get("approval_prompt")) or "이 후보를 승인하시겠습니까?",
        ]
    )

    if include_details:
        detail = {
            "candidate_id": candidate.candidate_id,
            "concept_id": candidate.concept_id,
            "node_type": candidate.node_type,
            "status": candidate.status,
            "risk_flags": candidate.risk_flags,
            "candidate_type": candidate.properties.get("candidate_type"),
            "codex_dev_review": candidate.properties.get("codex_dev_review"),
        }
        lines.extend(["", "상세 metadata:", json.dumps(detail, ensure_ascii=False, indent=2, sort_keys=True)])

    text = "\n".join(lines)
    return wrap_display_text(text, width=wrap_width) if wrap_width else text
