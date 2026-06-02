from __future__ import annotations

from src.graph.retriever import GraphRetrievalResult
from src.config import GRAPH_CONTEXT_MAX_CHARS


GRAPH_SECTION_TITLES = (
    "■ 섹션 1️⃣  【확정 근거】",
    "■ 섹션 2️⃣  【검토 필요 사항】",
    "■ 섹션 3️⃣  【추가 확인 사항】",
    "■ 섹션 4️⃣  【권장 조치】",
)


def _conflicting_fact_groups(facts) -> list[tuple[tuple[str, str], list[str]]]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for fact in facts:
        if fact.object is None or fact.status == "missing":
            continue
        key = (fact.subject, fact.relation)
        value = str(fact.object)
        grouped.setdefault(key, [])
        if value not in grouped[key]:
            grouped[key].append(value)
    return [(key, values) for key, values in grouped.items() if len(values) > 1]


def _merge_table_cell(existing: str, value: str) -> str:
    if existing == "N/A":
        return value
    if existing.startswith("[MISSING]") and not value.startswith("[MISSING]"):
        return value
    if value.startswith("[MISSING]") and existing != "N/A":
        return existing
    values = existing.split(" / ")
    if value in values:
        return existing
    return f"{existing} / {value}"


def _source_label(evidence) -> str:
    page_start = getattr(evidence, "page_start", None)
    page_end = getattr(evidence, "page_end", page_start)
    if page_start is None:
        page_label = "p.?"
    elif page_end is not None and page_end != page_start:
        page_label = f"p.{page_start}-{page_end}"
    else:
        page_label = f"p.{page_start}"
    return f"{getattr(evidence, 'doc_short', '') or '문서'}, {page_label}"


def _is_candidate_confidence(fact) -> bool:
    """Return whether the confidence falls in the candidate-only range."""

    confidence = getattr(fact, "confidence", None)
    if confidence is None:
        return False
    return 0.8 <= float(confidence) <= 0.95


def _fact_value_for_review(fact) -> str:
    """Render candidate/missing facts without leaking sensitive candidate values."""

    if fact.status == "missing":
        return "[누락/확인불가]"
    if fact.status == "candidate":
        return "검토 후보(확정 대상 아님)"
    if _is_candidate_confidence(fact):
        return "신뢰도 0.8~0.95 후보 구간(확정 근거 제외)"
    return str(fact.object or "N/A")


def _candidate_reason(fact) -> str:
    reason = fact.properties.get("reason") if getattr(fact, "properties", None) else None
    if reason:
        return str(reason)
    matched_keyword = fact.properties.get("matched_keyword") if getattr(fact, "properties", None) else None
    if matched_keyword:
        return f"부분 키워드 매칭: {matched_keyword}"
    if _is_candidate_confidence(fact):
        return "confidence가 0.8~0.95 후보 구간이므로 확정 근거로 사용할 수 없습니다."
    if fact.status == "missing":
        return "GraphDB에서 연결 정보를 확인하지 못했습니다."
    return "부분 매칭 또는 입력 조건 확인이 필요한 GraphDB 항목입니다."


def build_graph_summary(result: GraphRetrievalResult) -> dict:
    """Group graph retrieval output into the four review template sections."""

    confirmed_facts = []
    review_required = []
    evidence_checklist = []
    review_actions = []

    for fact in result.facts:
        first_evidence = fact.evidence[0] if fact.evidence else None
        fact_payload = {
            "subject": fact.subject,
            "relation": fact.relation,
            "object": fact.object,
            "confidence": fact.confidence,
            "status": fact.status,
            "source": _source_label(first_evidence) if first_evidence else None,
            "reason": _candidate_reason(fact),
        }
        if fact.status == "confirmed" and fact.evidence and not _is_candidate_confidence(fact):
            confirmed_facts.append(fact_payload)
        else:
            fact_payload["object"] = _fact_value_for_review(fact)
            review_required.append(fact_payload)

    for path in getattr(result, "review_paths", []) or []:
        if getattr(path, "status", "") in {"candidate", "review_required", "missing"}:
            review_required.append(
                {
                    "topic": getattr(path, "path_type", "review_path"),
                    "status": getattr(path, "status", "review_required"),
                    "summary": getattr(path, "summary", ""),
                    "reason": "Graph review path가 자동 확정이 아닌 검토 대상으로 반환되었습니다.",
                }
            )
        for item in getattr(path, "required_evidence", []) or []:
            evidence_checklist.append(
                {
                    "name": item,
                    "requirement": item,
                    "status": "required",
                    "priority": "high",
                }
            )
        for action in getattr(path, "review_actions", []) or []:
            review_actions.append(
                {
                    "action": action,
                    "target": getattr(path, "path_type", "review_path"),
                    "priority": "high" if getattr(path, "status", "") in {"confirmed", "review_required"} else "medium",
                }
            )

    for item in getattr(result, "required_evidence", []) or []:
        evidence_checklist.append(
            {
                "name": item,
                "requirement": item,
                "status": "required",
                "priority": "high",
            }
        )
    for action in getattr(result, "review_actions", []) or []:
        review_actions.append(
            {
                "action": action,
                "target": "GraphDB review",
                "priority": "high",
            }
        )

    clarification_questions = list(getattr(result.plan, "clarification_questions", []) or [])
    for question in clarification_questions:
        evidence_checklist.append(
            {
                "name": "입력 조건 확인",
                "requirement": question,
                "status": "required",
                "priority": "high",
            }
        )

    def dedupe(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
        seen = set()
        unique = []
        for item in items:
            key = tuple(str(item.get(k, "")) for k in keys)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    review_actions = [
        {"order": index, **item}
        for index, item in enumerate(dedupe(review_actions, ("action", "target")), start=1)
    ]
    return {
        "confirmed_facts": dedupe(confirmed_facts, ("subject", "relation", "object")),
        "review_required": dedupe(review_required, ("subject", "relation", "object", "topic", "summary")),
        "evidence_checklist": dedupe(evidence_checklist, ("name", "requirement")),
        "review_actions": review_actions,
    }


def _render_graph_review_template(summary: dict) -> list[str]:
    lines = [
        "=== Graph Retrieval Summary: 담당자용 4개 섹션 템플릿 ===",
        "[지침] 아래 네 섹션은 최종 답변에서도 같은 순서와 제목으로 유지하십시오.",
        "[지침] 정보가 없는 섹션도 생략하지 말고 반드시 '해당 없음'이라고 쓰십시오.",
        "[지침] candidate 또는 confidence 0.8~0.95 항목은 어떠한 경우에도 섹션 1️⃣ 【확정 근거】에 쓰지 마십시오.",
        "",
        GRAPH_SECTION_TITLES[0],
    ]

    confirmed = summary["confirmed_facts"]
    if not confirmed:
        lines.append("해당 없음")
    else:
        for item in confirmed:
            source = f" (출처: {item['source']})" if item.get("source") else ""
            lines.append(f"- {item['subject']} --({item['relation']})--> {item['object']}{source}")

    lines.extend(["", GRAPH_SECTION_TITLES[1]])
    review_required = summary["review_required"]
    if not review_required:
        lines.append("해당 없음")
    else:
        for item in review_required:
            if item.get("topic"):
                lines.append(f"- 【{item.get('topic')}】 {item.get('summary') or '검토 필요'}")
            else:
                lines.append(f"- 【{item.get('subject')}】 {item.get('relation')} -> {item.get('object')}")
            lines.append(f"  ⚠️ 이유: {item.get('reason') or '입력 조건 또는 근거 확인 필요'}")
            lines.append("  ➜ 확인 필요: 원문 근거, 입력 조건, 상품/특약 적용 여부를 확인하십시오.")

    lines.extend(["", GRAPH_SECTION_TITLES[2]])
    checklist = summary["evidence_checklist"]
    if not checklist:
        lines.append("해당 없음")
    else:
        for item in checklist:
            lines.append(f"☐ {item['name']}: {item['requirement']}")
            lines.append(f"   현황: {item['status']} / 중요도: {item['priority']}")

    lines.extend(["", GRAPH_SECTION_TITLES[3]])
    actions = summary["review_actions"]
    if not actions:
        lines.append("해당 없음")
    else:
        for item in actions:
            lines.append(f"→ {item['order']}. {item['action']}")
            lines.append(f"   대상: {item['target']} / 우선순위: {item['priority']}")
    lines.append("")
    return lines


def build_graph_context(result: GraphRetrievalResult) -> str:
    clarification_questions = list(getattr(result.plan, "clarification_questions", []) or [])
    normalized_terms = dict(getattr(result.plan, "normalized_terms", {}) or {})
    term_candidates = list(getattr(result.plan, "term_correction_candidates", []) or [])
    review_paths = list(getattr(result, "review_paths", []) or [])
    required_evidence = list(getattr(result, "required_evidence", []) or [])
    review_actions = list(getattr(result, "review_actions", []) or [])
    if (
        not result.facts
        and not clarification_questions
        and not normalized_terms
        and not term_candidates
        and not review_paths
        and not required_evidence
        and not review_actions
    ):
        return ""

    intents = result.plan.intents
    if not intents:
        intents = ["ordinary_rag"]

    keep_indices = set()
    for intent in intents:
        if intent == "surgery_grade_lookup":
            for i, f in enumerate(result.facts):
                if f.relation == "HAS_GRADE":
                    keep_indices.add(i)
                elif f.relation == "POLICY_COVERS_PROCEDURE" and f.status == "candidate":
                    keep_indices.add(i)
        elif intent == "same_grade_surgery_list":
            peer_count = 0
            for i, f in enumerate(result.facts):
                if f.relation == "SAME_GRADE_PEER":
                    if peer_count < result.plan.requested_peer_count:
                        keep_indices.add(i)
                        peer_count += 1
                else:
                    keep_indices.add(i)
        elif intent == "category_grade_listing":
            for i, f in enumerate(result.facts):
                keep_indices.add(i)
        elif intent == "policy_appendix_payment_lookup":
            for i, f in enumerate(result.facts):
                if f.relation in ["DEFINED_IN_APPENDIX", "POLICY_COVERS_PROCEDURE", "PAYS_BY_RATIO"]:
                    keep_indices.add(i)
        elif intent == "hira_code_lookup":
            for i, f in enumerate(result.facts):
                if f.relation == "HAS_MEDICAL_FEE_CODE" or f.status == "missing":
                    keep_indices.add(i)
        else:
            for i, f in enumerate(result.facts):
                keep_indices.add(i)

    filtered_facts = [result.facts[i] for i in sorted(list(keep_indices))]

    summary = build_graph_summary(result)
    lines = _render_graph_review_template(summary)
    if clarification_questions:
        lines.append("=== 사용자 입력 명확화 필요 사항 ===")
        lines.append("[지침] 아래 항목은 현재 질문에서 빠졌거나 혼용될 수 있는 조건입니다. 최종 보상 가능 여부를 단정하지 말고 필요한 확인 질문으로 먼저 제시하십시오.")
        for question in clarification_questions:
            lines.append(f"- {question}")
        lines.append("")
    if normalized_terms:
        lines.append("=== 입력 용어 정규화 후보 ===")
        lines.append("[지침] 아래 정규화는 문서 기반 검색을 돕기 위한 후보입니다. 코드나 약관 판단을 임의로 확정하지 마십시오.")
        for raw, normalized in normalized_terms.items():
            lines.append(f"- {raw} -> {normalized}")
        lines.append("")
    if term_candidates:
        lines.append("=== 입력 용어 보정 후보 (미확정) ===")
        lines.append("[지침] 아래 항목은 자동 확정된 정규화가 아닙니다. 사용자가 의도한 용어인지 확인 질문으로 먼저 제시하고, 확인 전에는 보상 판단의 전제로 삼지 마십시오.")
        for item in term_candidates:
            raw = item.get("raw", "")
            normalized = item.get("normalized", "")
            reason = item.get("reason", "")
            lines.append(f"- {raw} -> {normalized} ({reason})")
        lines.append("")

    if not filtered_facts:
        context_str = "\n".join(lines)
        if len(context_str) > GRAPH_CONTEXT_MAX_CHARS:
            context_str = context_str[:GRAPH_CONTEXT_MAX_CHARS] + "\n... [일부 근거 생략됨 (GRAPH_CONTEXT_MAX_CHARS 초과)]"
        return context_str

    lines.append("=== 구조화 그래프 근거 (Structured Graph Facts) ===")
    lines.append("[지침] 아래 사실들은 규정 데이터베이스(GraphDB)에서 추출한 구조화 사실입니다.")
    lines.append("- 'confirmed' 상태는 문서에 명시된 확실한 정보로, 답변의 절대적 근거로 삼으십시오.")
    lines.append("- 'candidate' 상태는 부분 키워드 매치 등으로 추정한 '후보 조항'입니다. 절대로 확정된 지급 비율이나 절대적인 사실로 단정 지어 답변하지 마십시오. 반드시 '동일 대분류 후보 조항일 가능성이 있습니다'와 같이 후보임을 인지할 수 있는 가정을 포함하여 설명해야 합니다.")
    lines.append("- 'missing' 상태는 규정 데이터베이스에서 연결 정보를 확인하지 못한 정보(코드 미매핑 등)입니다. 임의로 보완하거나 존재한다고 환각(hallucination)을 일으키지 마십시오.\n")
    lines.append("- 같은 대상과 관계에 대해 서로 다른 값이 여러 개 있으면 하나의 값으로 통합하지 말고, 문서/근거/상태별 경우의 수를 모두 분리해 답하십시오.\n")

    conflicting_groups = _conflicting_fact_groups(filtered_facts)
    if conflicting_groups:
        lines.append("### GraphDB 복수 값/상충 후보")
        for (subject, relation), values in conflicting_groups:
            value_text = " | ".join(values)
            lines.append(f"- {subject} --({relation})--> {value_text}")
        lines.append("")

    if "category_grade_listing" in intents:
        surgery_info = {}
        excluded_candidate_facts = []
        for f in filtered_facts:
            subj = f.subject
            if subj not in surgery_info:
                surgery_info[subj] = {
                    "grade": "N/A",
                    "fee_code": "N/A",
                    "ratio": "N/A",
                }
            if f.relation == "HAS_GRADE":
                surgery_info[subj]["grade"] = f.object or "N/A"
            elif f.relation == "HAS_MEDICAL_FEE_CODE":
                if f.status == "missing":
                    reason = f.properties.get('reason', '데이터 연결 없음')
                    value = f"[MISSING] ({reason})"
                elif f.status == "confirmed" and f.evidence and not _is_candidate_confidence(f):
                    value = f.object or "N/A"
                else:
                    value = _fact_value_for_review(f)
                surgery_info[subj]["fee_code"] = _merge_table_cell(surgery_info[subj]["fee_code"], value)
            elif f.relation == "PAYS_BY_RATIO":
                if f.status == "candidate" or _is_candidate_confidence(f):
                    excluded_candidate_facts.append(f)
                    continue
                if f.status == "missing":
                    reason = f.properties.get('reason', '데이터 연결 없음')
                    value = f"[MISSING] ({reason})"
                else:
                    value = f"[{f.status.upper()}] {f.object}"
                surgery_info[subj]["ratio"] = _merge_table_cell(surgery_info[subj]["ratio"], value)

        lines.append("### 카테고리/등급 수술 목록 요약 표")
        lines.append("| 수술명 | 등급 | 수가코드 (Medical Fee Code) | SOL 지급비율 (Payment Ratio) |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for subj, info in surgery_info.items():
            lines.append(f"| {subj} | {info['grade']} | {info['fee_code']} | {info['ratio']} |")
        lines.append("")
        if excluded_candidate_facts:
            lines.append("### 확정 답변 산출에서 제외한 GraphDB 항목")
            for fact in excluded_candidate_facts:
                lines.append(f"- {fact.subject} --({fact.relation})--> candidate")
            lines.append("")
    else:
        confirmed_facts = [
            f
            for f in filtered_facts
            if f.status == "confirmed" and f.evidence and not _is_candidate_confidence(f)
        ]
        candidate_facts = [
            f
            for f in filtered_facts
            if f.status == "candidate" or (f.status == "confirmed" and _is_candidate_confidence(f)) or (f.status == "confirmed" and not f.evidence)
        ]
        missing_facts = [f for f in filtered_facts if f.status == "missing"]

        if confirmed_facts:
            lines.append("1. 확정된 사실 (Confirmed Facts):")
            for fact in confirmed_facts:
                evidence_str = ""
                if fact.evidence:
                    ev = fact.evidence[0]
                    page_info = f" p.{ev.page_start}" if ev.page_start is not None else ""
                    evidence_str = f" [근거: {ev.doc_short}{page_info}]"
                lines.append(f"  - [{fact.status.upper()}] {fact.subject} --({fact.relation})--> {fact.object or 'N/A'}{evidence_str}")
            lines.append("")

        if candidate_facts:
            lines.append("2. 검토 후보 (Candidate Facts - 확정 아님):")
            for fact in candidate_facts:
                evidence_str = ""
                if fact.evidence:
                    ev = fact.evidence[0]
                    page_info = f" p.{ev.page_start}" if ev.page_start is not None else ""
                    evidence_str = f" [근거: {ev.doc_short}{page_info}]"
                lines.append(
                    f"  - [CANDIDATE] {fact.subject} --({fact.relation})--> "
                    f"검토 후보(확정 대상 아님){evidence_str}"
                )
            lines.append("")

        if missing_facts:
            lines.append("3. 연결 누락 항목 (Missing Facts - 규정 정보 부재):")
            for fact in missing_facts:
                lines.append(f"  - [{fact.status.upper()}] {fact.subject} --({fact.relation})--> [누락/확인불가] (사유: {fact.properties.get('reason', '데이터 연결 없음')})")
            lines.append("")

    context_str = "\n".join(lines)
    if len(context_str) > GRAPH_CONTEXT_MAX_CHARS:
        context_str = context_str[:GRAPH_CONTEXT_MAX_CHARS] + "\n... [일부 근거 생략됨 (GRAPH_CONTEXT_MAX_CHARS 초과)]"
    return context_str
