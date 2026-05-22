from __future__ import annotations

from src.graph.retriever import GraphRetrievalResult
from src.config import GRAPH_CONTEXT_MAX_CHARS


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


def build_graph_context(result: GraphRetrievalResult) -> str:
    if not result.facts:
        return ""

    intents = result.plan.intents
    # 만약 intents가 비어있다면 ordinary_rag로 기본 동작
    if not intents:
        intents = ["ordinary_rag"]

    keep_indices = set()

    # 각 intent에 대해 살려야 할 fact들의 index를 수집
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
        else: # ordinary_rag 등
            for i, f in enumerate(result.facts):
                keep_indices.add(i)

    filtered_facts = [result.facts[i] for i in sorted(list(keep_indices))]

    if not filtered_facts:
        return ""

    lines = []
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

    # category_grade_listing일 경우 표 형태로 압축
    if "category_grade_listing" in intents:
        # 수술별 정보 수집
        surgery_info = {}
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
                    surgery_info[subj]["fee_code"] = f"[MISSING] ({reason})"
                else:
                    surgery_info[subj]["fee_code"] = f"[{f.status.upper()}] {f.object}"
            elif f.relation == "PAYS_BY_RATIO":
                if f.status == "missing":
                    reason = f.properties.get('reason', '데이터 연결 없음')
                    surgery_info[subj]["ratio"] = f"[MISSING] ({reason})"
                else:
                    surgery_info[subj]["ratio"] = f"[{f.status.upper()}] {f.object}"

        lines.append("### 카테고리/등급 수술 목록 요약 표")
        lines.append("| 수술명 | 등급 | 수가코드 (Medical Fee Code) | SOL 지급비율 (Payment Ratio) |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for subj, info in surgery_info.items():
            lines.append(f"| {subj} | {info['grade']} | {info['fee_code']} | {info['ratio']} |")
        lines.append("")
    else:
        # Group by status
        confirmed_facts = [f for f in filtered_facts if f.status == "confirmed"]
        candidate_facts = [f for f in filtered_facts if f.status == "candidate"]
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

                # 중요 속성 표시
                props_list = []
                if fact.properties:
                    for k, v in fact.properties.items():
                        if k in ["appendix_number", "grade_value", "payment_ratio", "matched_keyword"]:
                            props_list.append(f"{k}: {v}")
                props_str = f" (속성: {', '.join(props_list)})" if props_list else ""

                lines.append(f"  - [{fact.status.upper()}] {fact.subject} --({fact.relation})--> {fact.object or 'N/A'}{evidence_str}{props_str}")
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
