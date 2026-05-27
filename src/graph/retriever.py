from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional

from src.graph.query_planner import GraphQueryPlan, GraphQueryPlanner
from src.graph.store import GraphStore
from src.graph.normalizer import normalize_name


@dataclass
class GraphEvidence:
    evidence_id: str
    chunk_id: Optional[str] = None
    doc_short: str = ""
    doc_name: Optional[str] = None
    pdf_filename: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    source_version: Optional[str] = None
    row_text: Optional[str] = None
    confidence: float = 1.0


@dataclass
class GraphFact:
    subject: str
    relation: str
    object: Optional[str]
    confidence: float
    status: Literal["confirmed", "candidate", "missing"]
    evidence: List[GraphEvidence] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphRetrievalResult:
    plan: GraphQueryPlan
    facts: List[GraphFact] = field(default_factory=list)
    source_chunk_ids: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


def _grade_prefix_for_system(grade_system: str | None) -> str | None:
    if grade_system == "신1-5종":
        return "grade_new_1_5_"
    if grade_system == "1-5종":
        return "grade_1_5_"
    if grade_system == "1-3종":
        return "grade_1_3_"
    return None


def _sort_evidences(evidences: List[GraphEvidence]) -> List[GraphEvidence]:
    """Prefer manually corrected OCR evidence when the same fact has variants."""
    return sorted(
        evidences,
        key=lambda ev: (0 if ev.source_version == "v2_manual" else 1, ev.evidence_id),
    )


def _dedupe_facts(facts: List[GraphFact]) -> List[GraphFact]:
    """Collapse repeated graph facts while preserving first-seen ordering."""
    merged: dict[tuple[Any, ...], GraphFact] = {}
    order: list[tuple[Any, ...]] = []
    for fact in facts:
        if fact.relation == "PAYS_BY_RATIO":
            key = (
                fact.subject,
                fact.relation,
                fact.object,
                fact.properties.get("payment_ratio"),
            )
        else:
            key = (
                fact.subject,
                fact.relation,
                fact.object,
                fact.properties.get("appendix_number"),
                fact.properties.get("payment_ratio"),
            )
        if key not in merged:
            fact.evidence = _sort_evidences(fact.evidence)
            merged[key] = fact
            order.append(key)
            continue

        existing = merged[key]
        seen_evidence = {ev.evidence_id for ev in existing.evidence}
        for ev in fact.evidence:
            if ev.evidence_id not in seen_evidence:
                existing.evidence.append(ev)
                seen_evidence.add(ev.evidence_id)
        existing.evidence = _sort_evidences(existing.evidence)
        existing.confidence = max(existing.confidence, fact.confidence)

    return [merged[key] for key in order]


class GraphRetriever:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.planner = GraphQueryPlanner()

    def _get_evidence_by_id(self, store: GraphStore, evidence_id: str) -> Optional[GraphEvidence]:
        rows = store.query("SELECT * FROM graph_evidence WHERE evidence_id = ?", (evidence_id,))
        if not rows:
            return None
        row = rows[0]
        return GraphEvidence(
            evidence_id=row["evidence_id"],
            chunk_id=row["chunk_id"],
            doc_short=row["doc_short"],
            doc_name=row["doc_name"],
            pdf_filename=row["pdf_filename"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            source_version=row["source_version"],
            row_text=row["row_text"],
            confidence=row["confidence"]
        )

    def _get_node_evidences(self, store: GraphStore, node_id: str) -> List[GraphEvidence]:
        evidences = []
        rows = store.query(
            """
            SELECT ge.* 
            FROM graph_node_evidence gne
            JOIN graph_evidence ge ON gne.evidence_id = ge.evidence_id
            WHERE gne.node_id = ?
            """,
            (node_id,)
        )
        for r in rows:
            evidences.append(GraphEvidence(
                evidence_id=r["evidence_id"],
                chunk_id=r["chunk_id"],
                doc_short=r["doc_short"],
                doc_name=r["doc_name"],
                pdf_filename=r["pdf_filename"],
                page_start=r["page_start"],
                page_end=r["page_end"],
                source_version=r["source_version"],
                row_text=r["row_text"],
                confidence=r["confidence"]
            ))
        return evidences

    def _get_edge_evidences(self, store: GraphStore, edge_id: str) -> List[GraphEvidence]:
        evidences = []
        rows = store.query(
            """
            SELECT ge.* 
            FROM graph_edge_evidence gee
            JOIN graph_evidence ge ON gee.evidence_id = ge.evidence_id
            WHERE gee.edge_id = ?
            """,
            (edge_id,)
        )
        for r in rows:
            evidences.append(GraphEvidence(
                evidence_id=r["evidence_id"],
                chunk_id=r["chunk_id"],
                doc_short=r["doc_short"],
                doc_name=r["doc_name"],
                pdf_filename=r["pdf_filename"],
                page_start=r["page_start"],
                page_end=r["page_end"],
                source_version=r["source_version"],
                row_text=r["row_text"],
                confidence=r["confidence"]
            ))
        return evidences

    def retrieve(self, question: str) -> GraphRetrievalResult:
        plan = self.planner.plan(question)
        result = GraphRetrievalResult(plan=plan)
        
        # fallback 대비: db_path가 없으면 경고만 남기고 리턴
        if not self.db_path.exists():
            result.warnings.append(f"Graph DB file not found at {self.db_path}. Running with empty graph fallback.")
            return result

        try:
            # 116번 라인의 read-only 연결 사용
            store = GraphStore(self.db_path, readonly=True)
        except Exception as e:
            result.warnings.append(f"Failed to connect to Graph DB: {e}. Running with empty graph fallback.")
            return result

        try:
            facts: List[GraphFact] = []
            source_chunk_ids: Set[str] = set()
            debug_info: dict[str, Any] = {}

            # INTENT 1: surgery_grade_lookup / same_grade_surgery_list
            if plan.procedure_name:
                norm_proc = normalize_name(plan.procedure_name)
                # 수술 노드 조회
                proc_nodes = store.query(
                    """
                    SELECT * FROM graph_nodes 
                    WHERE node_type = 'SurgeryProcedure' 
                      AND (normalized_name = ? OR node_id IN (
                          SELECT node_id FROM graph_aliases WHERE normalized_alias = ?
                      ))
                    """,
                    (norm_proc, norm_proc)
                )

                is_fuzzy = False
                if not proc_nodes:
                    # exact/alias lookup 실패 시 fuzzy lookup fallback
                    fuzzy_param = f"%{norm_proc}%"
                    proc_nodes = store.query(
                        """
                        SELECT * FROM graph_nodes 
                        WHERE node_type = 'SurgeryProcedure' 
                          AND normalized_name LIKE ?
                        """,
                        (fuzzy_param,)
                    )
                    if proc_nodes:
                        is_fuzzy = True

                if not proc_nodes:
                    # Missing 수술 노드
                    facts.append(GraphFact(
                        subject=plan.procedure_name,
                        relation="EXISTS",
                        object=None,
                        confidence=0.0,
                        status="missing",
                        properties={"reason": "Procedure node not found in graph database."}
                    ))
                else:
                    proc_node = proc_nodes[0]
                    proc_id = proc_node["node_id"]
                    proc_canonical = proc_node["canonical_name"]
                    debug_info["matched_proc_node"] = dict(proc_node)
                    debug_info["is_fuzzy_match"] = is_fuzzy

                    # 수술 등급 조회
                    grade_prefix = _grade_prefix_for_system(plan.grade_system)
                    grade_edges = store.query(
                        """
                        SELECT e.edge_id, e.confidence as edge_confidence, e.source_evidence_id,
                               n.node_id as grade_id, n.canonical_name as grade_name, n.properties_json as grade_props
                        FROM graph_edges e
                        JOIN graph_nodes n ON e.target_node_id = n.node_id
                        WHERE e.source_node_id = ? AND e.edge_type = 'HAS_GRADE'
                          AND (? IS NULL OR n.node_id LIKE ?)
                        ORDER BY 
                          CASE 
                            WHEN n.node_id LIKE 'grade_new_1_5_%' THEN 1
                            WHEN n.node_id LIKE 'grade_1_5_%' THEN 2
                            WHEN n.node_id LIKE 'grade_1_3_%' THEN 3 
                            ELSE 4 
                          END ASC
                        """,
                        (proc_id, grade_prefix, f"{grade_prefix}%" if grade_prefix else None)
                    )

                    grade_node_id = None
                    if not grade_edges:
                        facts.append(GraphFact(
                            subject=proc_canonical,
                            relation="HAS_GRADE",
                            object=None,
                            confidence=0.0,
                            status="missing",
                            properties={"reason": "Grade relation missing for surgery."}
                        ))
                    else:
                        grade_node_id = grade_edges[0]["grade_id"]
                        for ge in grade_edges:
                            grade_canonical = ge["grade_name"]
                            
                            # Evidence 조회
                            evs = self._get_edge_evidences(store, ge["edge_id"])
                            if ge["source_evidence_id"]:
                                sev = self._get_evidence_by_id(store, ge["source_evidence_id"])
                                if sev and sev not in evs:
                                    evs.append(sev)

                            for ev in evs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            # 등급 Fact 추가
                            if is_fuzzy:
                                status = "candidate"
                                confidence = 0.5
                            else:
                                status = "confirmed" if ge["edge_confidence"] >= 1.0 and len(evs) > 0 else "candidate"
                                confidence = ge["edge_confidence"]

                            facts.append(GraphFact(
                                subject=proc_canonical,
                                relation="HAS_GRADE",
                                object=grade_canonical,
                                confidence=confidence,
                                status=status,
                                evidence=evs,
                                properties=json.loads(ge["grade_props"]) if ge["grade_props"] else {}
                            ))

                    # INTENT 2: same_grade_surgery_list (Peer 조회)
                    if "same_grade_surgery_list" in plan.intents and grade_node_id:
                        peers = store.query(
                            """
                            SELECT DISTINCT p.node_id, p.canonical_name, e.confidence as edge_confidence, e.edge_id,
                              -- 1. 질문 대상 수술과 동일 대분류 HAS_CATEGORY 공유 여부
                              (SELECT COUNT(*) FROM graph_edges e1 
                               JOIN graph_edges e2 ON e1.target_node_id = e2.target_node_id
                               WHERE e1.edge_type = 'HAS_CATEGORY' AND e2.edge_type = 'HAS_CATEGORY'
                                 AND e1.source_node_id = p.node_id AND e2.source_node_id = ?) as share_cat,
                                 
                              -- 2. SOL [별표7] 후보 조항과 같은 category_large에 속하는지 여부
                              (SELECT COUNT(*) FROM graph_edges e_cat
                               JOIN graph_nodes n_cat ON e_cat.target_node_id = n_cat.node_id
                               WHERE e_cat.source_node_id = p.node_id AND e_cat.edge_type = 'HAS_CATEGORY'
                                 AND n_cat.canonical_name IN (
                                     SELECT json_extract(n_rule.properties_json, '$.category_large')
                                     FROM graph_edges e_rule
                                     JOIN graph_nodes n_rule ON e_rule.source_node_id = n_rule.node_id
                                     WHERE e_rule.target_node_id = ? AND e_rule.edge_type = 'POLICY_COVERS_PROCEDURE'
                                 )) as share_rule_cat,
                                 
                              -- 3. evidence 존재 여부
                              (CASE WHEN e.source_evidence_id IS NOT NULL THEN 1
                                    WHEN EXISTS (SELECT 1 FROM graph_edge_evidence WHERE edge_id = e.edge_id) THEN 1
                                    ELSE 0 END) as has_evidence
                            FROM graph_edges e
                            JOIN graph_nodes p ON e.source_node_id = p.node_id
                            WHERE e.target_node_id = ? AND e.edge_type = 'HAS_GRADE' AND e.source_node_id != ?
                            ORDER BY 
                              share_cat DESC,
                              share_rule_cat DESC,
                              has_evidence DESC,
                              p.canonical_name ASC
                            LIMIT ?
                            """,
                            (proc_id, proc_id, grade_node_id, proc_id, plan.requested_peer_count)
                        )

                        if len(peers) < plan.requested_peer_count:
                            result.warnings.append(f"요청된 peer 개수({plan.requested_peer_count}개)보다 실제 반환할 수 있는 peer 후보({len(peers)}개)가 부족합니다.")

                        for peer in peers:
                            peer_id = peer["node_id"]
                            peer_canonical = peer["canonical_name"]
                            
                            # Peer evidences
                            peevs = self._get_edge_evidences(store, peer["edge_id"])
                            for ev in peevs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            # Peer 카테고리 정보 조회
                            cat_edges = store.query(
                                """
                                SELECT n.canonical_name 
                                FROM graph_edges e
                                JOIN graph_nodes n ON e.target_node_id = n.node_id
                                WHERE e.source_node_id = ? AND e.edge_type = 'HAS_CATEGORY'
                                """,
                                (peer_id,)
                            )
                            peer_cats = [c["canonical_name"] for c in cat_edges]

                            # Peer의 appendix 7 rule 번호 등 약관 매핑 정보 조회
                            rule_edges = store.query(
                                """
                                SELECT n_rule.canonical_name as rule_name, n_rule.properties_json as rule_props, e.confidence as edge_confidence
                                FROM graph_edges e
                                JOIN graph_nodes n_rule ON e.source_node_id = n_rule.node_id
                                WHERE e.target_node_id = ? AND e.edge_type = 'POLICY_COVERS_PROCEDURE'
                                """,
                                (peer_id,)
                            )
                            
                            rule_props = {}
                            if rule_edges:
                                rp = rule_edges[0]["rule_props"]
                                rule_props = json.loads(rp) if rp else {}

                            facts.append(GraphFact(
                                subject=peer_canonical,
                                relation="SAME_GRADE_PEER",
                                object=proc_canonical,
                                confidence=0.5 if is_fuzzy else peer["edge_confidence"],
                                status="candidate" if is_fuzzy else ("confirmed" if peer["edge_confidence"] >= 1.0 else "candidate"),
                                evidence=peevs,
                                properties={
                                    "categories": peer_cats,
                                    "grade_system": plan.grade_system or "신1-5종",
                                    "grade_value": plan.grade_value or "4",
                                    **rule_props
                                }
                            ))

                    # 약관 매핑 및 지급비율 조회 (POLICY_COVERS_PROCEDURE)
                    rule_edges = store.query(
                        """
                        SELECT e.edge_id, e.confidence as edge_confidence, e.source_evidence_id,
                               n_rule.node_id as rule_id, n_rule.canonical_name as rule_name, n_rule.properties_json as rule_props
                        FROM graph_edges e
                        JOIN graph_nodes n_rule ON e.source_node_id = n_rule.node_id
                        WHERE e.target_node_id = ? AND e.edge_type = 'POLICY_COVERS_PROCEDURE'
                        """,
                        (proc_id,)
                    )

                    if not rule_edges:
                        facts.append(GraphFact(
                            subject=proc_canonical,
                            relation="POLICY_COVERS_PROCEDURE",
                            object=None,
                            confidence=0.0,
                            status="missing",
                            properties={"reason": "Policy coverage mapping missing in graph DB."}
                        ))
                    else:
                        for re_edge in rule_edges:
                            rule_props = json.loads(re_edge["rule_props"]) if re_edge["rule_props"] else {}
                            
                            # Evidence
                            revs = self._get_edge_evidences(store, re_edge["edge_id"])
                            if re_edge["source_evidence_id"]:
                                rsev = self._get_evidence_by_id(store, re_edge["source_evidence_id"])
                                if rsev and rsev not in revs:
                                    revs.append(rsev)
                            
                            for ev in revs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            # POLICY_COVERS_PROCEDURE 엣지는 0.8 이하 신뢰도이므로 무조건 candidate로 취급해야 한다!
                            confidence = 0.5 if is_fuzzy else re_edge["edge_confidence"]
                            facts.append(GraphFact(
                                subject=re_edge["rule_name"],
                                relation="POLICY_COVERS_PROCEDURE",
                                object=proc_canonical,
                                confidence=confidence,
                                status="candidate",
                                evidence=revs,
                                properties=rule_props
                            ))

            # INTENT 3: category_grade_listing (소화기계 5종 등 카테고리별 나열)
            if "category_grade_listing" in plan.intents and plan.category and plan.grade_value:
                # 5종 코드 매칭
                grade_node_key = f"grade_new_1_5_{plan.grade_value}"
                
                procs = store.query(
                    """
                    SELECT DISTINCT p.node_id, p.canonical_name, e_grd.edge_id, e_grd.source_evidence_id, e_grd.confidence as edge_confidence
                    FROM graph_nodes p
                    JOIN graph_edges e_cat ON p.node_id = e_cat.source_node_id AND e_cat.edge_type = 'HAS_CATEGORY'
                    JOIN graph_edges e_grd ON p.node_id = e_grd.source_node_id AND e_grd.edge_type = 'HAS_GRADE'
                    WHERE e_cat.target_node_id IN (
                        SELECT node_id FROM graph_nodes WHERE node_type = 'SurgeryCategory' AND normalized_name LIKE ?
                    ) AND e_grd.target_node_id = ?
                    """,
                    (f"%{normalize_name(plan.category)}%", grade_node_key)
                )

                debug_info["category_grade_listing_count"] = len(procs)

                for p_row_raw in procs:
                    p_row = dict(p_row_raw)
                    proc_id = p_row["node_id"]
                    proc_canonical = p_row["canonical_name"]

                    # HAS_GRADE evidence 조회
                    gevs = []
                    if p_row.get("edge_id"):
                        gevs = self._get_edge_evidences(store, p_row["edge_id"])
                        if p_row.get("source_evidence_id"):
                            gsev = self._get_evidence_by_id(store, p_row["source_evidence_id"])
                            if gsev and gsev not in gevs:
                                gevs.append(gsev)

                    for ev in gevs:
                        if ev.chunk_id:
                            source_chunk_ids.add(ev.chunk_id)

                    # 1. 등급 관계 추가
                    facts.append(GraphFact(
                        subject=proc_canonical,
                        relation="HAS_GRADE",
                        object=f"{plan.grade_system or '신1-5종'} {plan.grade_value}종",
                        confidence=p_row["edge_confidence"] if p_row.get("edge_confidence") is not None else 1.0,
                        status="confirmed" if len(gevs) > 0 else "candidate",
                        evidence=gevs
                    ))

                    # 2. 수가코드 (MedicalFeeCode) 조회
                    fee_edges = store.query(
                        """
                        SELECT e.edge_id, e.confidence as edge_confidence,
                               n.node_id as fee_id,
                               n.canonical_name as fee_name,
                               json_extract(n.properties_json, '$.code') as fee_code
                        FROM graph_edges e
                        JOIN graph_nodes n ON e.target_node_id = n.node_id
                        WHERE e.source_node_id = ? AND e.edge_type = 'HAS_MEDICAL_FEE_CODE'
                        """,
                        (proc_id,)
                    )

                    if not fee_edges:
                        # 수가코드 missing 사실 기록 (환각 방지)
                        facts.append(GraphFact(
                            subject=proc_canonical,
                            relation="HAS_MEDICAL_FEE_CODE",
                            object=None,
                            confidence=0.0,
                            status="missing",
                            properties={"reason": f"No MedicalFeeCode mapping found in GraphDB for {proc_canonical}."}
                        ))
                    else:
                        for fe in fee_edges:
                            # Evidence
                            fevs = self._get_edge_evidences(store, fe["edge_id"])
                            for ev in fevs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            fee_object = fe["fee_code"] or fe["fee_name"]
                            if fe["fee_code"] and fe["fee_name"] and fe["fee_code"] != fe["fee_name"]:
                                fee_object = f"{fe['fee_code']} ({fe['fee_name']})"

                            facts.append(GraphFact(
                                subject=proc_canonical,
                                relation="HAS_MEDICAL_FEE_CODE",
                                object=fee_object,
                                confidence=fe["edge_confidence"],
                                status="confirmed" if fe["edge_confidence"] >= 0.95 and len(fevs) > 0 else "candidate",
                                evidence=fevs
                            ))

                    # 3. 약관 지급 비율 조회
                    rule_edges = store.query(
                        """
                        SELECT e.edge_id, e.confidence as edge_confidence, e.source_evidence_id,
                               n_rule.canonical_name as rule_name, n_rule.properties_json as rule_props
                        FROM graph_edges e
                        JOIN graph_nodes n_rule ON e.source_node_id = n_rule.node_id
                        WHERE e.target_node_id = ? AND e.edge_type = 'POLICY_COVERS_PROCEDURE'
                        """,
                        (proc_id,)
                    )

                    if not rule_edges:
                        facts.append(GraphFact(
                            subject=proc_canonical,
                            relation="PAYS_BY_RATIO",
                            object=None,
                            confidence=0.0,
                            status="missing",
                            properties={"reason": "No policy rule payment ratio mapping found."}
                        ))
                    else:
                        for re_edge in rule_edges:
                            rule_props = json.loads(re_edge["rule_props"]) if re_edge["rule_props"] else {}
                            ratio_val = rule_props.get("payment_ratio")
                            
                            revs = self._get_edge_evidences(store, re_edge["edge_id"])
                            if re_edge["source_evidence_id"]:
                                rsev = self._get_evidence_by_id(store, re_edge["source_evidence_id"])
                                if rsev and rsev not in revs:
                                    revs.append(rsev)
                            for ev in revs:
                                if ev.chunk_id:
                                    source_chunk_ids.add(ev.chunk_id)

                            # POLICY_COVERS_PROCEDURE 기반의 지급비율 정보이므로 candidate로 처리
                            facts.append(GraphFact(
                                subject=proc_canonical,
                                relation="PAYS_BY_RATIO",
                                object=ratio_val,
                                confidence=re_edge["edge_confidence"],
                                status="candidate",
                                evidence=revs,
                                properties=rule_props
                            ))

            # INTENT 4: policy_appendix_payment_lookup (별표7의 특정 항목 조회 등)
            if "policy_appendix_payment_lookup" in plan.intents and plan.appendix and plan.appendix_numbers:
                numbers = plan.appendix_numbers
                placeholders = ",".join(["?"] * len(numbers))
                rules = store.query(
                    f"""
                    SELECT * FROM graph_nodes 
                    WHERE node_type = 'PolicyBenefitRule'
                      AND json_extract(properties_json, '$.appendix_name') = ?
                      AND json_extract(properties_json, '$.appendix_number') IN ({placeholders})
                    """,
                    (plan.appendix, *numbers)
                )
                
                for rule in rules:
                    rule_id = rule["node_id"]
                    rule_props = json.loads(rule["properties_json"]) if rule["properties_json"] else {}
                    
                    # 4.3 DEFINED_IN_APPENDIX evidence 연결 및 status 하향 처리
                    evs = self._get_node_evidences(store, rule_id)
                    for ev in evs:
                        if ev.chunk_id:
                            source_chunk_ids.add(ev.chunk_id)
                            
                    status = "confirmed" if len(evs) > 0 else "candidate"
                    if len(evs) == 0:
                        result.warnings.append(f"주의: 규정 조항 '{rule_id}'에 연동된 근거(evidence) 문서가 존재하지 않아 검토 후보(candidate)로 하향 처리되었습니다.")
                    
                    facts.append(GraphFact(
                        subject=rule_id,
                        relation="DEFINED_IN_APPENDIX",
                        object=plan.appendix,
                        confidence=1.0 if len(evs) > 0 else 0.5,
                        status=status,
                        evidence=evs,
                        properties=rule_props
                    ))

            facts = _dedupe_facts(facts)

            # 모든 fact에 대해 confirmed 이지만 evidence가 없는 경우 candidate로 강하 처리
            for fact in facts:
                fact.evidence = _sort_evidences(fact.evidence)
                if fact.status == "confirmed" and not fact.evidence:
                    fact.status = "candidate"
                    fact.confidence = 0.5

            # Warnings 구성
            warnings = list(result.warnings)
            has_candidate = any(f.status == "candidate" for f in facts)
            has_missing = any(f.status == "missing" for f in facts)
            if has_candidate:
                warnings.append("주의: 약관 매칭(POLICY_COVERS_PROCEDURE)은 confidence 0.8 이하의 추정(candidate) 관계입니다. 공식 지급 여부 판단 시 검토용 후보로만 활용해야 합니다.")
            if has_missing:
                warnings.append("알림: 일부 요청 항목(수가코드 혹은 약관 매핑 등)에 대한 구조화 데이터(missing)가 존재하지 않습니다.")

            result.facts = facts
            result.source_chunk_ids = sorted(list(source_chunk_ids))
            result.warnings = warnings
            result.debug = debug_info

        except Exception as e:
            result.warnings.append(f"Error during graph retrieval query execution: {e}")
        finally:
            store.close()

        return result
