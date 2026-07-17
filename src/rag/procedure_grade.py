"""Source-grounded surgery-grade resolution without implicit procedure aliases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from src.graph.query_planner import GraphQueryPlan, GraphQueryPlanner
from src.rag.table_store import TableStore


_DEFAULT_GRADE_SYSTEM = "1-5종"
_GRADE_SYSTEMS = ("1-3종", "1-5종", "신1-5종")
_ROW_GRADE_COLUMNS = {
    "1-3종": "종_1_3",
    "1-5종": "종_1_5",
    "신1-5종": "종_신1_5",
}
_GRADE_INTENT_RX = re.compile(r"몇\s*종|어떤\s*종|종수|등급")


@dataclass(frozen=True)
class ProcedureGradeCandidate:
    canonical_name: str
    grades: dict[str, str]
    source_doc: str
    source_page: str
    match_kind: Literal["exact", "approved_alias", "candidate"]
    distinction: str = ""


@dataclass(frozen=True)
class ProcedureGradeResolution:
    status: Literal["confirmed", "candidate_pending", "not_found"]
    query_name: str
    requested_system: str | None
    selected: ProcedureGradeCandidate | None
    candidates: tuple[ProcedureGradeCandidate, ...] = ()
    clarification_question: str = ""


def _grade_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "N":
        return ""
    return text if text.endswith("종") else f"{text}종"


def _grades_from_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        system: label
        for system, column in _ROW_GRADE_COLUMNS.items()
        if (label := _grade_label(row.get(column)))
    }


def _candidate_from_row(row: dict[str, Any], *, match_kind: Literal["exact", "candidate"]) -> ProcedureGradeCandidate:
    return ProcedureGradeCandidate(
        canonical_name=str(row.get("수술명", "")).strip(),
        grades=_grades_from_row(row),
        source_doc=str(row.get("source_doc") or "실무가이드").strip(),
        source_page=str(row.get("source_page_label") or "").strip(),
        match_kind=match_kind,
        distinction=str(row.get("수술해설") or "").strip(),
    )


def _candidate_from_confirmed_graph_fact(graph_result: Any, plan: GraphQueryPlan) -> ProcedureGradeCandidate | None:
    debug = getattr(graph_result, "debug", {}) or {}
    match_kind = debug.get("procedure_match_kind")
    if match_kind not in {"exact", "approved_alias"}:
        return None

    facts = [
        fact
        for fact in getattr(graph_result, "facts", [])
        if getattr(fact, "relation", "") == "HAS_GRADE"
        and getattr(fact, "status", "") == "confirmed"
        and getattr(fact, "object", None)
    ]
    if not facts:
        return None

    grades: dict[str, str] = {}
    for fact in facts:
        object_name = str(getattr(fact, "object", ""))
        for system in _GRADE_SYSTEMS:
            match = re.search(rf"{re.escape(system)}\s*([1-5])종", object_name)
            if match:
                grades[system] = f"{match.group(1)}종"
    requested_system = plan.grade_system or _DEFAULT_GRADE_SYSTEM
    if requested_system not in grades:
        return None

    evidence = next((item for fact in facts for item in getattr(fact, "evidence", []) or []), None)
    return ProcedureGradeCandidate(
        canonical_name=str(getattr(facts[0], "subject", plan.procedure_name or "")).strip(),
        grades=grades,
        source_doc=str(getattr(evidence, "doc_short", "") or "실무가이드").strip(),
        source_page=str(getattr(evidence, "page_start", "") or "").strip(),
        match_kind=match_kind,
    )


def _candidate_clarification(candidates: tuple[ProcedureGradeCandidate, ...]) -> str:
    distinctions = " ".join(item.distinction for item in candidates)
    if "개복" in distinctions and ("결장경" in distinctions or "내시경" in distinctions):
        return "수술기록지에서 개복 수술인지 결장경 또는 내시경을 이용한 수술인지 확인해 주세요."
    return "수술기록지의 정확한 수술명과 수술 방법을 확인해 주세요."


def _distinct_grade_candidates(
    rows: list[dict[str, Any]],
    requested_system: str,
    *,
    limit: int = 3,
) -> tuple[ProcedureGradeCandidate, ...]:
    """Keep the strongest source-backed candidate for each possible grade."""

    candidates: list[ProcedureGradeCandidate] = []
    seen_grades: set[str] = set()
    for row in rows:
        candidate = _candidate_from_row(row, match_kind="candidate")
        grade = candidate.grades.get(requested_system)
        if not grade or grade in seen_grades:
            continue
        candidates.append(candidate)
        seen_grades.add(grade)
        if len(candidates) >= limit:
            break
    return tuple(candidates)


def _is_surgery_grade_request(plan: GraphQueryPlan, question: str) -> bool:
    return "surgery_grade_lookup" in plan.intents or bool(plan.hira_code and _GRADE_INTENT_RX.search(question))


def resolve_procedure_grade(
    question: str,
    *,
    table_store: TableStore | None,
    graph_result: Any | None = None,
) -> ProcedureGradeResolution | None:
    """Resolve only source-confirmed procedure grades; leave fuzzy names for confirmation."""

    plan = getattr(graph_result, "plan", None) or GraphQueryPlanner().plan(question)
    if not _is_surgery_grade_request(plan, question):
        return None

    requested_system = plan.grade_system or _DEFAULT_GRADE_SYSTEM
    query_name = str(plan.procedure_name or plan.hira_code or "").strip()
    if not plan.procedure_name:
        if plan.hira_code:
            return ProcedureGradeResolution(
                status="candidate_pending",
                query_name=query_name,
                requested_system=requested_system,
                selected=None,
                clarification_question="수가코드와 수술종수표 수술명의 승인된 연결 근거를 확인해 주세요.",
            )
        return ProcedureGradeResolution(
            status="not_found",
            query_name=query_name,
            requested_system=requested_system,
            selected=None,
            clarification_question="수술기록지의 정확한 수술명을 확인해 주세요.",
        )

    graph_candidate = _candidate_from_confirmed_graph_fact(graph_result, plan) if graph_result is not None else None
    if graph_candidate is not None:
        return ProcedureGradeResolution(
            status="confirmed",
            query_name=query_name,
            requested_system=requested_system,
            selected=graph_candidate,
        )

    if table_store is not None and table_store.is_available():
        exact = table_store.lookup_surgery_grade_exact(plan.procedure_name)
        if exact:
            candidate = _candidate_from_row(exact, match_kind="exact")
            if requested_system in candidate.grades:
                return ProcedureGradeResolution(
                    status="confirmed",
                    query_name=query_name,
                    requested_system=requested_system,
                    selected=candidate,
                )

        candidates = _distinct_grade_candidates(
            table_store.search_surgery_grade_candidates(plan.procedure_name, limit=6),
            requested_system,
        )
        if candidates:
            return ProcedureGradeResolution(
                status="candidate_pending",
                query_name=query_name,
                requested_system=requested_system,
                selected=None,
                candidates=candidates,
                clarification_question=_candidate_clarification(candidates),
            )

    return ProcedureGradeResolution(
        status="not_found",
        query_name=query_name,
        requested_system=requested_system,
        selected=None,
        clarification_question="수술기록지의 정확한 수술명 또는 수술코드를 확인해 주세요.",
    )


def format_procedure_grade_answer(result: ProcedureGradeResolution) -> str:
    """Return the canonical user-facing deterministic answer for a resolution."""

    if result.status == "confirmed" and result.selected is not None:
        system = result.requested_system or _DEFAULT_GRADE_SYSTEM
        grade = result.selected.grades.get(system)
        if grade:
            source = f" (실무가이드 p.{result.selected.source_page})" if result.selected.source_page else ""
            return f"{result.selected.canonical_name}은 {system} 기준 {grade}입니다.{source}"

    if result.status == "candidate_pending":
        lines = [f"'{result.query_name}'은 수술종수표에서 단일 수술명으로 확정할 수 없습니다."]
        system = result.requested_system or _DEFAULT_GRADE_SYSTEM
        for candidate in result.candidates[:3]:
            grade = candidate.grades.get(system, "확인 필요")
            source = f", 실무가이드 p.{candidate.source_page}" if candidate.source_page else ""
            lines.append(f"- {candidate.canonical_name}: {system} {grade}{source}")
        if result.clarification_question:
            lines.append(result.clarification_question)
        return "\n".join(lines)

    return "수술종수표에서 정확한 수술명을 찾지 못했습니다. 수술기록지의 정확한 수술명 또는 수술코드를 확인해 주세요."
