from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
import pandas as pd

from src.graph.schema import Node, Edge, Evidence, Alias, NodeType, EdgeType
from src.graph.normalizer import normalize_name, normalize_code


POLICY_REVIEW_SOURCE_PRIORITY = {
    "약관": "high",
    "자사_SOL건강": "high",
    "자사_SOL운전자": "high",
    "표준약관": "high",
    "상담사례집": "medium",
    "실무가이드": "medium",
    "심평원": "low",
}

POLICY_REVIEW_DOCS = {
    "약관",
    "자사_SOL건강",
    "자사_SOL운전자",
    "표준약관",
    "상담사례집",
    "실무가이드",
    "심평원",
}

COMPLICATION_CONCEPTS = {
    "합병증": ["합병증"],
    "합병증 치료": ["합병증 치료"],
    "수술 후 합병증": ["수술 후", "합병증"],
    "부작용": ["부작용"],
    "후유증": ["후유증"],
    "미용 목적 시술 후 합병증": ["미용 목적", "합병증"],
}

CLAIM_CONDITIONS = {
    "미용 목적": ["미용 목적", "미용"],
    "선천성": ["선천성"],
    "기왕증": ["기왕증", "기왕력"],
    "건강보험 미적용": ["건강보험 미적용", "요양급여 미적용", "건강보험 적용받지 못"],
    "상급병실료 차액": ["상급병실", "병실료 차액"],
    "통원": ["통원"],
    "입원": ["입원"],
    "추가 치료": ["추가 치료", "추후 치료"],
    "특약 가입 여부 확인": ["특약"],
    "세부내역서 확인 필요": ["세부내역서"],
    "진단서 확인 필요": ["진단서"],
    "진단코드 일치 확인": ["진단코드"],
    "치료 목적 확인": ["치료 목적", "목적"],
    "타 보험 보상": ["자동차보험", "산재보험", "이미 보상", "타 보험", "다른 보험"],
    "자동차보험": ["자동차보험", "자동차 보험", "교통사고"],
    "산재보험": ["산재보험", "산재", "산업재해"],
}

DECISION_CONCEPTS = {
    "보상 가능": ["보상 가능", "보상한다", "지급한다"],
    "면책": ["면책", "보상하지 않는", "보상하지 아니", "보상 제외", "지급하지 않는"],
    "조건부 보상": ["경우에 한하여", "조건", "단서"],
    "추가 심사 필요": ["추가 확인", "확인 필요", "심사 필요", "검토 필요"],
    "증빙 필요": ["증빙", "제출", "첨부", "확인서"],
    "자동 계산 보류": ["계산 보류", "산출 보류"],
}

EVIDENCE_REQUIREMENTS = {
    "진단서": ["진단서"],
    "영수증": ["영수증"],
    "세부내역서": ["세부내역서"],
    "수술확인서": ["수술확인서"],
}

POLICY_GENERATIONS = {
    "4세대": ["4세대", "4th"],
    "5세대": ["5세대", "5th"],
    "공통": [],
}

VISIT_CONTEXTS = {
    "입원": ["입원"],
    "통원": ["통원"],
}

FACILITY_CONTEXTS = {
    "상급종합병원": ["상급종합병원"],
    "종합병원": ["종합병원"],
    "병원": ["병원"],
    "의원": ["의원"],
    "약국": ["약국"],
}

REVIEW_ACTIONS = {
    "인간 심사 필요": ["심사 필요", "검토 필요"],
    "세부내역서 요청": ["세부내역서"],
    "진단서 요청": ["진단서"],
    "수술확인서 요청": ["수술확인서"],
    "표준코드 재확인": ["표준코드", "수가코드"],
    "특약 가입 여부 확인": ["특약"],
    "질병/상해 구분 확인": ["상해", "질병"],
}

EXCLUSION_REASONS = {
    "미용 목적": {
        "keywords": ["미용 목적", "미용", "성형 목적"],
        "reason_code": "cosmetic",
        "reason_category": "treatment_purpose",
        "source_priority": "high",
        "requires_human_review": True,
    },
    "예방 목적": {
        "keywords": ["예방 목적", "검진 목적", "건강검진", "질병 치료를 직접 목적으로 하지"],
        "reason_code": "preventive",
        "reason_category": "treatment_purpose",
        "source_priority": "high",
        "requires_human_review": True,
    },
    "건강검진": {
        "keywords": ["건강검진", "검진"],
        "reason_code": "screening",
        "reason_category": "screening",
        "source_priority": "high",
        "requires_human_review": True,
    },
    "약관상 보상제외 치료": {
        "keywords": ["보상하지", "지급하지", "보상 제외", "면책"],
        "reason_code": "policy_exclusion",
        "reason_category": "policy",
        "source_priority": "high",
        "requires_human_review": True,
    },
    "고의 또는 중대한 과실": {
        "keywords": ["고의", "중대한 과실"],
        "reason_code": "intentional_or_gross_negligence",
        "reason_category": "general_exclusion",
        "source_priority": "medium",
        "requires_human_review": True,
    },
    "전쟁/폭동 등 일반 면책": {
        "keywords": ["전쟁", "폭동", "소요", "사변"],
        "reason_code": "war_or_riot",
        "reason_category": "general_exclusion",
        "source_priority": "medium",
        "requires_human_review": True,
    },
    "타 보험 선보상": {
        "keywords": ["타 보험", "다른 보험", "이미 보상", "먼저 보상"],
        "reason_code": "other_insurance_primary",
        "reason_category": "coordination",
        "source_priority": "medium",
        "requires_human_review": True,
    },
    "자동차보험 처리 대상": {
        "keywords": ["자동차보험", "자동차 보험", "교통사고"],
        "reason_code": "auto_insurance",
        "reason_category": "coordination",
        "source_priority": "medium",
        "requires_human_review": True,
    },
    "산재보험 처리 대상": {
        "keywords": ["산재보험", "산업재해", "산재"],
        "reason_code": "workers_compensation",
        "reason_category": "coordination",
        "source_priority": "medium",
        "requires_human_review": True,
    },
}

BENEFIT_LIMITS = {
    "3대비급여 연간 한도": {
        "keywords": ["3대비급여", "도수치료", "체외충격파", "증식치료", "50회", "350만원", "연간"],
        "limit_scope": "annual",
        "limit_amount": "3500000",
        "limit_count": "50",
        "limit_period": "1년",
        "applies_to_topic": "3대비급여",
        "unit_text": "연간 350만원/50회 등 문서 기준 확인",
    },
    "도수치료 횟수 한도": {
        "keywords": ["도수치료", "50회", "10회"],
        "limit_scope": "count",
        "limit_count": "50",
        "limit_period": "1년",
        "applies_to_topic": "도수치료",
        "unit_text": "문서상 회차 조건 확인",
    },
    "MRI/MRA 한도": {
        "keywords": ["MRI", "MRA", "자기공명영상", "한도"],
        "limit_scope": "topic",
        "applies_to_topic": "MRI/MRA",
        "unit_text": "자기공명영상진단 한도",
    },
    "상급병실료 차액 한도": {
        "keywords": ["상급병실", "병실료 차액", "10만원", "50%"],
        "limit_scope": "daily",
        "limit_amount": "100000",
        "applies_to_topic": "상급병실료 차액",
        "unit_text": "1일 평균 10만원 한도 내 비급여 병실료의 50%",
    },
    "통원 1회 한도": {
        "keywords": ["통원", "1회", "한도"],
        "limit_scope": "per_visit",
        "applies_to_visit": "통원",
        "unit_text": "통원 1회 한도",
    },
}

DEDUCTIBLE_RULES = {
    "4세대 실손 공제": {
        "keywords": ["4세대", "공제", "자기부담", "본인 부담"],
        "deductible_type": "generation",
        "generation_scope": "4th",
        "basis_text": "4세대 실손 공제 규칙",
    },
    "5세대 실손 공제": {
        "keywords": ["5세대", "공제", "자기부담", "본인 부담"],
        "deductible_type": "generation",
        "generation_scope": "5th",
        "basis_text": "5세대 실손 공제 규칙",
    },
    "3대비급여 공제": {
        "keywords": ["3대비급여", "도수치료", "주사료", "MRI", "MRA", "공제"],
        "deductible_type": "topic",
        "basis_text": "3대비급여 공제 규칙",
    },
    "통원 공제": {
        "keywords": ["통원", "공제", "자기부담"],
        "deductible_type": "visit",
        "visit_scope": "outpatient",
        "basis_text": "통원 공제 규칙",
    },
    "입원 공제": {
        "keywords": ["입원", "공제", "자기부담"],
        "deductible_type": "visit",
        "visit_scope": "hospitalization",
        "basis_text": "입원 공제 규칙",
    },
}

REQUIRED_DOCUMENTS = {
    "진료비 영수증": ["진료비 영수증", "영수증"],
    "진료비 세부내역서": ["진료비 세부내역서", "세부내역서"],
    "진단서": ["진단서"],
    "수술확인서": ["수술확인서", "수술 확인서"],
    "입퇴원확인서": ["입퇴원확인서", "입원확인서", "퇴원확인서"],
    "처방전": ["처방전"],
    "검사결과지": ["검사결과지", "검사 결과지"],
    "판독결과지": ["판독결과지", "판독 결과지"],
    "진료확인서": ["진료확인서", "진료 확인서"],
}

COORDINATION_RULES = {
    "자동차보험 처리 후 실손 청구": {
        "keywords": ["자동차보험", "자동차 보험", "교통사고"],
        "coordination_type": "auto_insurance",
        "primary_payer": "자동차보험",
        "secondary_review_required": True,
        "deduct_prior_payment": True,
        "required_evidence": ["자동차보험 지급내역", "진료비 영수증", "진료비 세부내역서"],
    },
    "산재보험 처리 후 실손 청구": {
        "keywords": ["산재보험", "산재", "산업재해"],
        "coordination_type": "workers_compensation",
        "primary_payer": "산재보험",
        "secondary_review_required": True,
        "deduct_prior_payment": True,
        "required_evidence": ["산재보험 지급내역", "진료비 영수증", "진료비 세부내역서"],
    },
    "타보험 중복 보상 조정": {
        "keywords": ["타 보험", "다른 보험", "중복 보상", "이미 보상"],
        "coordination_type": "other_insurance",
        "primary_payer": "타보험",
        "secondary_review_required": True,
        "deduct_prior_payment": True,
        "required_evidence": ["타보험 지급내역"],
    },
}

RENEWAL_OR_GENERATION_RULES = {
    "4세대 실손 적용 규칙": {
        "keywords": ["4세대", "4th"],
        "generation": "4th",
        "rule_subject": "실손 세대별 적용",
        "requires_generation_confirmation": True,
    },
    "5세대 실손 적용 규칙": {
        "keywords": ["5세대", "5th"],
        "generation": "5th",
        "rule_subject": "실손 세대별 적용",
        "requires_generation_confirmation": True,
    },
    "공통 실손 적용 규칙": {
        "keywords": ["실손", "실손의료보험"],
        "generation": "common",
        "rule_subject": "공통 실손 적용",
        "requires_generation_confirmation": False,
    },
    "갱신/개정 전후 적용 규칙": {
        "keywords": ["갱신", "개정", "변경", "적용 시점"],
        "generation": "unknown",
        "rule_subject": "갱신 또는 개정 전후",
        "requires_generation_confirmation": True,
    },
}

POLICY_REVIEW_TOPICS = {
    "실손": ["실손"],
    "3대비급여": ["3대비급여", "도수치료", "주사료", "mri", "mra", "체외충격파", "증식치료"],
    "상급병실료 차액": ["상급병실", "병실료 차액"],
    "건강보험 미적용 특례": ["건강보험 미적용", "요양급여 미적용"],
    "합병증 치료": ["합병증 치료", "합병증"],
    "미용 목적 치료": ["미용 목적", "미용"],
    "자동차보험": ["자동차보험", "자동차 보험", "교통사고"],
    "산재보험": ["산재보험", "산재", "산업재해"],
    "타보험 중복 보상": ["타 보험", "다른 보험", "중복 보상", "이미 보상"],
}

DIAGNOSIS_CODE_RX = re.compile(r"\b([A-Z][0-9]{2}(?:\.[0-9]+)?(?:~[A-Z]?[0-9]{2}(?:\.[0-9]+)?)?)\b")

STRICT_ALL_KEY_MATCHES = {
    "수술 후 합병증",
    "미용 목적 시술 후 합병증",
    "상급병실료 차액",
}


def _chunk_lookup_payload(meta: dict[str, Any], chunk_id: str) -> tuple[str, dict[str, Any]]:
    canonical_chunk_id = str(meta.get("canonical_chunk_id") or meta.get("source_chunk_id") or chunk_id)
    payload = {
        "canonical_chunk_id": canonical_chunk_id,
        "source_chunk_id": str(meta.get("source_chunk_id") or canonical_chunk_id),
    }
    return canonical_chunk_id, payload


class SurgeryGradeExtractor:
    """Reads surgery_grades.parquet and extracts SurgeryProcedure, SurgeryGrade, SurgeryCategory nodes and edges."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, chunks_path: str | Path, parquet_path: str | Path) -> None:
        self.store.begin()
        chunks_path = Path(chunks_path)
        parquet_path = Path(parquet_path)

        # 1. Build page to category mapping from chunks
        page_to_category: dict[int, tuple[str, str]] = {}
        large_pattern = re.compile(
            r"("
            r"피부,\s*유방의?\s*(?:수술)?|"
            r"호흡기계\s*,\s*흉부의?\s*(?:수술)?|호흡기계\s*(?:및\s*흉부)?\s*(?:의?\s*수술)?|"
            r"순환기계\s*(?:,\s*비장)?\s*(?:의?\s*수술)?|"
            r"소화기계\s*(?:의?\s*수술)?|"
            r"비뇨기계\s*(?:,\s*생식기계)?\s*(?:의?\s*수술)?|"
            r"눈의?\s*(?:수술)?|"
            r"귀\s*,\s*코의?\s*(?:수술)?|"
            r"뇌\s*,\s*척수의?\s*(?:수술)?|"
            r"골\s*,\s*관절의?\s*(?:수술)?|사지관절의?\s*(?:수술)?|"
            r"근골격계\s*(?:의?\s*수술)?|"
            r"구강\s*,\s*인두\s*,\s*인후의?\s*(?:수술)?|"
            r"상기\s*이외의\s*수술"
            r")"
        )
        medium_pattern = re.compile(r"^(\d+(?:-\d+)?)\.\s*(.*)")

        current_large = "일반 수술"
        current_medium = "일반"

        # Scan chunks sequentially by page to establish current categories
        chunks: list[dict] = []
        if chunks_path.exists():
            with open(chunks_path, encoding="utf-8") as f:
                for line in f:
                    c = json.loads(line)
                    if c["metadata"]["doc_short"] == "실무가이드":
                        chunks.append(c)

        # Sort chunks by page_start
        chunks.sort(key=lambda x: x["metadata"]["page_start"] or 0)

        for chunk in chunks:
            page = chunk["metadata"]["page_start"]
            if not page:
                continue
            text = chunk["text"]
            is_code_table = chunk["metadata"].get("is_code_table", False)

            if not is_code_table:
                for line in text.split("\n"):
                    line_clean = line.strip()
                    if not line_clean:
                        continue
                    # Match large category
                    large_match = large_pattern.search(line_clean)
                    if large_match:
                        current_large = large_match.group(1).strip()
                    # Match medium category
                    medium_match = medium_pattern.match(line_clean)
                    if medium_match:
                        current_medium = f"{medium_match.group(1)}. {medium_match.group(2).strip()}"

            page_to_category[page] = (current_large, current_medium)

        # 2. Read parquet and load nodes/edges
        df = pd.read_parquet(parquet_path)
        for _, row in df.iterrows():
            proc_name = str(row["수술명"]).strip()
            proc_name_raw = str(row["수술명_원문"]).strip()
            desc = str(row["수술해설"]).strip()
            g_13 = str(row["종_1_3"]).strip()
            g_15 = str(row["종_1_5"]).strip()
            g_s15 = str(row["종_신1_5"]).strip()
            page = int(row["source_page_label"])
            source_file = str(row["source_file"])

            # Normalized name
            norm_proc_name = normalize_name(proc_name)
            node_id = f"proc_{norm_proc_name}"

            # Create SurgeryProcedure Node
            proc_node = Node(
                node_id=node_id,
                node_type=NodeType.SurgeryProcedure,
                canonical_name=proc_name,
                normalized_name=norm_proc_name,
                properties={
                    "procedure_name": proc_name,
                    "procedure_name_raw": proc_name_raw,
                    "description": desc,
                    "grade_1_3": g_13,
                    "grade_1_5": g_15,
                    "grade_new_1_5": g_s15,
                    "source_doc_priority": "실무가이드",
                    "source_page_label": page,
                    "source_file": source_file,
                },
                confidence=1.0,
            )
            self.store.upsert_node(proc_node)

            # Link with Evidence
            ev_id = f"ev_proc_{norm_proc_name}_{page}"
            evidence = Evidence(
                evidence_id=ev_id,
                doc_short="실무가이드",
                doc_name="Claim 실무종합가이드",
                pdf_filename="Claim 실무종합가이드.pdf",
                page_start=page,
                page_end=page,
                source_version="v2_manual" if "v2" in source_file else "v1",
                source_method="table_index",
                row_text=f"{proc_name} | {desc} | {g_13} | {g_15} | {g_s15}",
                confidence=1.0,
            )
            self.store.upsert_evidence(evidence)
            self.store.link_node_evidence(node_id, ev_id, role="source")

            # Create alias if raw name is different
            if proc_name != proc_name_raw and proc_name_raw:
                norm_raw = normalize_name(proc_name_raw)
                alias_id = f"alias_proc_{norm_proc_name}_raw"
                alias_obj = Alias(
                    alias_id=alias_id,
                    node_id=node_id,
                    alias=proc_name_raw,
                    normalized_alias=norm_raw,
                    source="실무가이드_raw",
                    confidence=1.0,
                )
                self.store.add_alias(alias_obj)

            # Connect Category with preceding page fallback
            cat_large, cat_medium = "일반 수술", "일반"
            sorted_pages = sorted(page_to_category.keys())
            for p in sorted_pages:
                if p <= page:
                    cat_large, cat_medium = page_to_category[p]
                else:
                    break

            large_cat_id = f"cat_{normalize_name(cat_large)}"
            medium_cat_id = f"cat_{normalize_name(cat_medium)}"

            # Upsert Category Nodes
            self.store.upsert_node(
                Node(
                    node_id=large_cat_id,
                    node_type=NodeType.SurgeryCategory,
                    canonical_name=cat_large,
                    normalized_name=normalize_name(cat_large),
                )
            )
            self.store.upsert_node(
                Node(
                    node_id=medium_cat_id,
                    node_type=NodeType.SurgeryCategory,
                    canonical_name=cat_medium,
                    normalized_name=normalize_name(cat_medium),
                )
            )

            # Link categories
            edge_cat_relation_id = f"edge_cat_sub_{normalize_name(cat_medium)}_{normalize_name(cat_large)}"
            self.store.upsert_edge(
                Edge(
                    edge_id=edge_cat_relation_id,
                    source_node_id=medium_cat_id,
                    target_node_id=large_cat_id,
                    edge_type=EdgeType.SAME_CATEGORY_AS,
                    properties={"relationship": "subclass_of"},
                )
            )

            # Link procedure to medium category
            edge_proc_cat_id = f"edge_proc_cat_{norm_proc_name}_{normalize_name(cat_medium)}"
            self.store.upsert_edge(
                Edge(
                    edge_id=edge_proc_cat_id,
                    source_node_id=node_id,
                    target_node_id=medium_cat_id,
                    edge_type=EdgeType.HAS_CATEGORY,
                )
            )

            # Link procedure to large category directly as well
            edge_proc_large_cat_id = f"edge_proc_cat_{norm_proc_name}_{normalize_name(cat_large)}"
            self.store.upsert_edge(
                Edge(
                    edge_id=edge_proc_large_cat_id,
                    source_node_id=node_id,
                    target_node_id=large_cat_id,
                    edge_type=EdgeType.HAS_CATEGORY,
                )
            )

            # Connect Grades
            grades_to_link = [
                ("1-3종", g_13, "grade_1_3"),
                ("1-5종", g_15, "grade_1_5"),
                ("신1-5종", g_s15, "grade_new_1_5"),
            ]
            for grade_system, grade_val, prefix in grades_to_link:
                if not grade_val or grade_val in ("N", "", "nan", "None"):
                    continue
                grade_node_id = f"{prefix}_{grade_val}"
                grade_canonical = f"{grade_system} {grade_val}종"

                # Upsert Grade Node
                self.store.upsert_node(
                    Node(
                        node_id=grade_node_id,
                        node_type=NodeType.SurgeryGrade,
                        canonical_name=grade_canonical,
                        normalized_name=normalize_name(grade_canonical),
                        properties={"grade_system": grade_system, "grade_value": grade_val},
                    )
                )

                # Link procedure to grade
                edge_grade_id = f"edge_grade_{norm_proc_name}_{prefix}_{grade_val}"
                self.store.upsert_edge(
                    Edge(
                        edge_id=edge_grade_id,
                        source_node_id=node_id,
                        target_node_id=grade_node_id,
                        edge_type=EdgeType.HAS_GRADE,
                        source_evidence_id=ev_id,
                    )
                )
        self.store.commit()


class PolicyAppendixExtractor:
    """Extracts PolicyProduct, PolicyAppendix, PolicyBenefitRule nodes and edges from 자사_SOL건강 Appendix 7 chunks."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, chunks_path: str | Path) -> None:
        self.store.begin()
        chunks_path = Path(chunks_path)
        if not chunks_path.exists():
            return

        # 1. Ensure PolicyProduct and PolicyAppendix Nodes exist
        product_id = "prod_sol_health"
        product_node = Node(
            node_id=product_id,
            node_type=NodeType.PolicyProduct,
            canonical_name="신한 SOL 처음건강보험(무배당)(자동갱신형)",
            normalized_name=normalize_name("신한 SOL 처음건강보험"),
        )
        self.store.upsert_node(product_node)

        appendix_id = "app_sol_health_별표7"
        appendix_node = Node(
            node_id=appendix_id,
            node_type=NodeType.PolicyAppendix,
            canonical_name="[별표7] 1-5종 수술분류표",
            normalized_name=normalize_name("별표7 1-5종 수술분류표"),
        )
        self.store.upsert_node(appendix_node)

        # Link appendix to product
        self.store.upsert_edge(
            Edge(
                edge_id="edge_app_appears_in_prod",
                source_node_id=appendix_id,
                target_node_id=product_id,
                edge_type=EdgeType.APPEARS_IN,
            )
        )

        # 2. Parse Appendix Chunks
        large_cats = [
            "피부, 유방의 수술", "호흡기계·흉부의 수술", "호흡기계, 흉부의 수술", "호흡기계ㆍ흉부의 수술", "호흡기계·흉부",
            "순환기계, 비장의 수술", "순환기계, 비장(변식)의 수술", "소화기계의 수술", "비뇨기계·생식기계의 수술",
            "눈의 수술", "귀, 코의 수술", "뇌, 척수의 수술", "골, 관절의 수술", "사지, 골, 관절, 근육의 수술",
            "사지관절의 수술", "근골격계의 수술", "구강, 인두, 인후의 수술"
        ]

        large_pattern_str = "|".join(re.escape(cat) for cat in large_cats)
        rule_pattern = re.compile(
            r"(\d+(?:-\d+)?)\.\s*(.+?)\s+([1-5N])(?=\s+\d+(?:-\d+)?\.\s*|\s*(?:" + large_pattern_str + r")|\s*$)"
        )
        cat_pattern = re.compile(
            r"(" + large_pattern_str + r"|[가-힣\w\s,·ㆍ]+계의?\s*수술|[가-힣\w\s,·ㆍ]+기[가-힣\w\s,·ㆍ]*의\s*수술|상기\s*이외의\s*수술)"
        )

        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                meta = c["metadata"]
                # Only process Appendix 7 of 자사_SOL건강
                if meta["doc_short"] == "자사_SOL건강" and "별표7" in str(meta["section"]):
                    raw_text = c["text"]

                    # Preprocess to move lonely grades to the end of their respective item chunks
                    # e.g., "\n4\n" inside item 18 should be moved to the end of item 18's section.
                    parts = re.split(r"(?:^|\n)(?=\d+(?:-\d+)?\.)", raw_text)
                    processed_parts = []

                    # The first part is usually header text before the first item number (e.g. "호흡기계·흉부의 수술")
                    if parts:
                        processed_parts.append(parts[0])

                    grade_lonely_pattern = re.compile(r"(?:\n|^)\s*([1-5N])\s*(?:\n|$)")

                    for part in parts[1:]:
                        grade_match = grade_lonely_pattern.search(part)
                        if grade_match:
                            grade_val = grade_match.group(1)
                            # Remove the lonely grade from its original position
                            part_clean = grade_lonely_pattern.sub("\n", part)
                            # Append it to the end of this part (item)
                            part_fixed = f"{part_clean.rstrip()} {grade_val}"
                            processed_parts.append(part_fixed)
                        else:
                            processed_parts.append(part)

                    # Reconstruct text with newlines before replacing them with spaces
                    text = "\n".join(processed_parts)
                    text = text.replace("\n", " ")
                    text = re.sub(r"\s+", " ", text)
                    chunk_id = c["id"]
                    page = meta["page_start"]
                    canonical_chunk_id, lookup_metadata = _chunk_lookup_payload(meta, chunk_id)

                    # Find all category positions in clean text
                    cat_positions: list[tuple[int, str]] = []
                    for m in cat_pattern.finditer(text):
                        cat_positions.append((m.start(), m.group(1).strip()))
                    cat_positions.sort()

                    # Find all rule matches
                    for m in rule_pattern.finditer(text):
                        pos = m.start()
                        num = m.group(1)
                        name = m.group(2).strip()
                        grade = m.group(3)

                        # Determine category for this rule
                        current_large = "일반"
                        for c_pos, cat in cat_positions:
                            if c_pos < pos:
                                current_large = cat
                            else:
                                break

                        # Create PolicyBenefitRule Node
                        norm_rule_name = normalize_name(name)
                        rule_node_id = f"rule_sol_health_별표7_{num}"

                        # Grade payment mapping
                        grade_ratio_map = {
                            "1": ("10%", 0.1),
                            "2": ("30%", 0.3),
                            "3": ("50%", 0.5),
                            "4": ("100%", 1.0),
                            "5": ("100%", 1.0),
                            "N": ("0%", 0.0),
                        }
                        ratio_str, ratio_val = grade_ratio_map.get(grade, ("0%", 0.0))

                        rule_node = Node(
                            node_id=rule_node_id,
                            node_type=NodeType.PolicyBenefitRule,
                            canonical_name=name,
                            normalized_name=norm_rule_name,
                            properties={
                                "product_name": "신한 SOL 처음건강보험(무배당)(자동갱신형)",
                                "appendix_name": "별표7",
                                "benefit_name": name,
                                "payment_ratio": ratio_str,
                                "payment_ratio_numeric": ratio_val,
                                "grade_value": grade,
                                "appendix_number": num,
                                "category_large": current_large,
                            },
                        )
                        self.store.upsert_node(rule_node)

                        # Create Evidence
                        ev_id = f"ev_rule_sol_health_별표7_{num}_{page}"
                        evidence = Evidence(
                            evidence_id=ev_id,
                            chunk_id=chunk_id,
                            canonical_chunk_id=canonical_chunk_id,
                            doc_short="자사_SOL건강",
                            doc_name="신한 SOL 처음건강보험 약관",
                            pdf_filename="2.약관_신한 SOL 처음건강보험(무배당)(자동갱신형)_20260101.pdf",
                            page_start=page,
                            page_end=page,
                            source_version="v2_manual",
                            source_method="regex_appendix_extractor",
                            row_text=f"[{current_large}] {num}. {name} {grade}",
                            metadata_json=lookup_metadata,
                        )
                        self.store.upsert_evidence(evidence)
                        self.store.link_node_evidence(rule_node_id, ev_id, role="source")

                        # Link rule to appendix
                        self.store.upsert_edge(
                            Edge(
                                edge_id=f"edge_rule_def_{num}",
                                source_node_id=rule_node_id,
                                target_node_id=appendix_id,
                                edge_type=EdgeType.DEFINED_IN_APPENDIX,
                                source_evidence_id=ev_id,
                            )
                        )

                        # Link rule to grade node if exists
                        if grade != "N":
                            grade_node_id = f"grade_1_5_{grade}"
                            grade_canonical = f"1-5종 {grade}종"
                            self.store.upsert_node(
                                Node(
                                    node_id=grade_node_id,
                                    node_type=NodeType.SurgeryGrade,
                                    canonical_name=grade_canonical,
                                    normalized_name=normalize_name(grade_canonical),
                                    properties={"grade_system": "1-5종", "grade_value": grade},
                                )
                            )
                            self.store.upsert_edge(
                                Edge(
                                    edge_id=f"edge_rule_pays_{num}_{grade}",
                                    source_node_id=rule_node_id,
                                    target_node_id=grade_node_id,
                                    edge_type=EdgeType.PAYS_BY_RATIO,
                                    source_evidence_id=ev_id,
                                )
                            )
        self.store.commit()


class HiraCodeExtractor:
    """Extracts MedicalFeeCode nodes and edges from 심평원 chunks."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, chunks_path: str | Path) -> None:
        self.store.begin()
        chunks_path = Path(chunks_path)
        if not chunks_path.exists():
            return

        # Ensure Document node exists
        doc_id = "doc_심평원"
        self.store.upsert_node(
            Node(
                node_id=doc_id,
                node_type=NodeType.Document,
                canonical_name="건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수",
                normalized_name=normalize_name("건강보험 행위 급여비급여 목록표 및 상대가치점수"),
            )
        )

        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                meta = c["metadata"]
                if meta["doc_short"] == "심평원" and meta.get("codes"):
                    text = c["text"]
                    chunk_id = c["id"]
                    page = meta["page_start"]
                    canonical_chunk_id, lookup_metadata = _chunk_lookup_payload(meta, chunk_id)

                    for code in meta["codes"]:
                        for l in text.split("\n"):
                            if code in l:
                                parts = l.split(code)
                                if len(parts) >= 2:
                                    left = parts[0].strip()
                                    right = parts[1].strip()

                                    # Parse classification number (e.g., 조-961)
                                    class_match = re.search(r"([가-힣\w]+-\d+(?:-\d+)?)", left)
                                    class_no = class_match.group(1) if class_match else ""

                                    # Clean name
                                    name_match = re.match(r"^([가-힣\s\(\),·\-+]+)", right)
                                    name = name_match.group(1).strip() if name_match else right

                                    # Remove English names
                                    eng_start = re.search(r"\b[A-Za-z][A-Za-z\s\-,\(\)/]{3,}\b", name)
                                    if eng_start and eng_start.start() > 0:
                                        name = name[:eng_start.start()].strip()

                                    # Remove trailing numbers
                                    name = re.sub(r"\s*\d+.*$", "", name).strip()

                                    # Upsert MedicalFeeCode Node
                                    code_node_id = f"hira_{normalize_code(code)}"
                                    self.store.upsert_node(
                                        Node(
                                            node_id=code_node_id,
                                            node_type=NodeType.MedicalFeeCode,
                                            canonical_name=name,
                                            normalized_name=normalize_code(code),
                                            properties={
                                                "code": code,
                                                "code_system": "HIRA",
                                                "name": name,
                                                "doc_specific": True,
                                                "classification_no": class_no,
                                            },
                                        )
                                    )

                                    # Create Evidence
                                    ev_id = f"ev_hira_{normalize_code(code)}_{page}"
                                    evidence = Evidence(
                                        evidence_id=ev_id,
                                        chunk_id=chunk_id,
                                        canonical_chunk_id=canonical_chunk_id,
                                        doc_short="심평원",
                                        doc_name="건강보험 행위 급여·비급여 목록표",
                                        pdf_filename="BZ202603053039374.pdf",
                                        page_start=page,
                                        page_end=page,
                                        source_version="v1",
                                        source_method="regex_hira_extractor",
                                        row_text=l.strip(),
                                        metadata_json=lookup_metadata,
                                    )
                                    self.store.upsert_evidence(evidence)
                                    self.store.link_node_evidence(code_node_id, ev_id, role="source")

                                    # Link code to document
                                    self.store.upsert_edge(
                                        Edge(
                                            edge_id=f"edge_hira_app_{normalize_code(code)}",
                                            source_node_id=code_node_id,
                                            target_node_id=doc_id,
                                            edge_type=EdgeType.APPEARS_IN,
                                            source_evidence_id=ev_id,
                                        )
                                    )
        self.store.commit()


class NonpayStandardExtractor:
    """Extracts NonpayStandardCode nodes from standard_codes.sqlite."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, standard_db_path: str | Path, batch_size: int = 10000) -> None:
        self.store.begin()
        standard_db_path = Path(standard_db_path)
        if not standard_db_path.exists():
            return

        conn = sqlite3.connect(str(standard_db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                std_cd, std_cd_nm, mid_category_cd_nm, hira_care_type_cd_nm,
                ins_care_type_cd_nm, medical_class_cd_nm, item_class_level1cd_nm,
                item_class_level2cd_nm, pay_opn_cd_nm, notes, remarks,
                apply_start_date, apply_end_date
            FROM nonpay_standard;
            """
        )

        nodes_batch = []
        aliases_batch = []
        count = 0

        for row in cursor:
            code = str(row["std_cd"]).strip()
            name = str(row["std_cd_nm"]).strip()

            node_id = f"std_{normalize_code(code)}"
            nodes_batch.append(
                Node(
                    node_id=node_id,
                    node_type=NodeType.NonpayStandardCode,
                    canonical_name=name,
                    normalized_name=normalize_code(code),
                    properties={
                        "std_cd": code,
                        "std_cd_nm": name,
                        "mid_category": str(row["mid_category_cd_nm"] or "").strip(),
                        "hira_care_type": str(row["hira_care_type_cd_nm"] or "").strip(),
                        "ins_care_type": str(row["ins_care_type_cd_nm"] or "").strip(),
                        "medical_class": str(row["medical_class_cd_nm"] or "").strip(),
                        "item_class_level1": str(row["item_class_level1cd_nm"] or "").strip(),
                        "item_class_level2": str(row["item_class_level2cd_nm"] or "").strip(),
                        "pay_opinion": str(row["pay_opn_cd_nm"] or "").strip(),
                        "notes": str(row["notes"] or "").strip(),
                        "remarks": str(row["remarks"] or "").strip(),
                        "apply_start_date": str(row["apply_start_date"] or "").strip(),
                        "apply_end_date": str(row["apply_end_date"] or "").strip(),
                    },
                )
            )

            # Create alias
            alias_id = f"alias_std_{normalize_code(code)}_nm"
            aliases_batch.append(
                Alias(
                    alias_id=alias_id,
                    node_id=node_id,
                    alias=name,
                    normalized_alias=normalize_name(name),
                    source="standard_codes",
                )
            )

            count += 1
            if count % batch_size == 0:
                self.store.upsert_nodes_bulk(nodes_batch)
                self.store.add_aliases_bulk(aliases_batch)
                self.store.commit()
                nodes_batch.clear()
                aliases_batch.clear()
                print(f"[INFO] Ingested {count} non-pay standard codes...")
                self.store.begin()

        # Process remaining
        if nodes_batch:
            self.store.upsert_nodes_bulk(nodes_batch)
            self.store.add_aliases_bulk(aliases_batch)
            self.store.commit()
            print(f"[INFO] Ingested {count} non-pay standard codes (Final batch).")
        else:
            self.store.commit()

        conn.close()


class PolicyReviewExtractor:
    """Extract document-grounded policy review nodes and relations from processed chunks."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, chunks_path: str | Path) -> None:
        self.store.begin()
        chunks_path = Path(chunks_path)
        if not chunks_path.exists():
            self.store.commit()
            return

        self._seed_canonical_nodes()

        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                chunk = json.loads(line)
                meta = chunk.get("metadata", {})
                doc_short = str(meta.get("doc_short") or "").strip()
                if doc_short not in POLICY_REVIEW_DOCS:
                    continue
                text = str(chunk.get("text") or "").strip()
                if not text:
                    continue

                if doc_short == "상담사례집":
                    self._extract_case_example(chunk, text, meta)
                    continue

                if self._should_extract_clause(text, meta):
                    self._extract_policy_clause(chunk, text, meta)

        self.store.commit()

    def _seed_canonical_nodes(self) -> None:
        self._seed_nodes(NodeType.ComplicationConcept, COMPLICATION_CONCEPTS.keys(), "comp")
        self._seed_nodes(NodeType.ClaimCondition, CLAIM_CONDITIONS.keys(), "cond")
        self._seed_nodes(NodeType.DecisionConcept, DECISION_CONCEPTS.keys(), "decision")
        self._seed_nodes(NodeType.EvidenceRequirement, EVIDENCE_REQUIREMENTS.keys(), "evidence_req")
        self._seed_nodes(NodeType.PolicyGeneration, POLICY_GENERATIONS.keys(), "generation")
        self._seed_nodes(NodeType.VisitContext, VISIT_CONTEXTS.keys(), "visit")
        self._seed_nodes(NodeType.FacilityContext, FACILITY_CONTEXTS.keys(), "facility")
        self._seed_nodes(NodeType.ReviewAction, REVIEW_ACTIONS.keys(), "review_action")
        self._seed_nodes(NodeType.CoverageItem, POLICY_REVIEW_TOPICS.keys(), "cov")
        self._seed_rule_nodes(NodeType.ExclusionReason, EXCLUSION_REASONS, "exclusion_reason")
        self._seed_rule_nodes(NodeType.BenefitLimit, BENEFIT_LIMITS, "benefit_limit")
        self._seed_rule_nodes(NodeType.DeductibleRule, DEDUCTIBLE_RULES, "deductible_rule")
        self._seed_required_document_nodes()
        self._seed_rule_nodes(NodeType.CoordinationRule, COORDINATION_RULES, "coordination_rule")
        self._seed_rule_nodes(NodeType.RenewalOrGenerationRule, RENEWAL_OR_GENERATION_RULES, "generation_rule")

    def _seed_nodes(self, node_type: NodeType, names: Any, prefix: str) -> None:
        for name in names:
            normalized = normalize_name(name)
            self.store.upsert_node(
                Node(
                    node_id=f"{prefix}_{normalized}",
                    node_type=node_type,
                    canonical_name=name,
                    normalized_name=normalized,
                )
            )

    def _seed_rule_nodes(self, node_type: NodeType, mapping: dict[str, dict[str, Any]], prefix: str) -> None:
        for name, spec in mapping.items():
            normalized = normalize_name(name)
            properties = {key: value for key, value in spec.items() if key != "keywords"}
            properties.setdefault("display_name", name)
            self.store.upsert_node(
                Node(
                    node_id=f"{prefix}_{normalized}",
                    node_type=node_type,
                    canonical_name=name,
                    normalized_name=normalized,
                    properties=properties,
                )
            )

    def _seed_required_document_nodes(self) -> None:
        for name, aliases in REQUIRED_DOCUMENTS.items():
            normalized = normalize_name(name)
            self.store.upsert_node(
                Node(
                    node_id=f"required_doc_{normalized}",
                    node_type=NodeType.RequiredDocument,
                    canonical_name=name,
                    normalized_name=normalized,
                    properties={
                        "document_name": name,
                        "document_category": "claim_evidence",
                        "required_for": "claim_review",
                        "blocks_auto_decision": True,
                        "alternative_names": aliases,
                    },
                )
            )

    def _should_extract_clause(self, text: str, meta: dict[str, Any]) -> bool:
        scope_fields = " ".join(
            str(meta.get(key) or "")
            for key in ("part", "chapter", "section", "clause_type", "coverage_category")
        )
        if re.search(r"제\s*\d+\s*조|\[별표\s*\d+\]", text):
            return True
        if any(token in scope_fields for token in ("별표", "제", "조", "특별약관", "약관")):
            return True
        if any(keyword in text for keyword in (
            "합병증", "후유증", "부작용", "상급병실", "병실료 차액", "건강보험 미적용",
            "진단서", "세부내역서", "특약", "보상하지", "보상 가능", "지급",
        )):
            return True
        if DIAGNOSIS_CODE_RX.search(text):
            return True
        return False

    def _extract_policy_clause(self, chunk: dict[str, Any], text: str, meta: dict[str, Any]) -> None:
        chunk_id = chunk["id"]
        doc_short = str(meta.get("doc_short") or "")
        page_start = meta.get("page_start")
        page_end = meta.get("page_end", page_start)
        clause_id_text = self._extract_clause_id(text, meta)
        clause_title = self._derive_clause_title(text, meta)
        normalized_title = normalize_name(f"{doc_short} {clause_id_text} {clause_title}".strip())
        node_id = f"clause_{normalized_title}_{page_start}"
        clause_type = self._classify_clause_type(text)
        decision_polarity = self._classify_decision_polarity(text)
        rule_types = self._classify_rule_types(text)
        rule_summary = self._build_rule_summary(text, rule_types, decision_polarity)
        generation_scope = self._classify_generation_scope(text)
        source_priority = POLICY_REVIEW_SOURCE_PRIORITY.get(doc_short, "low")

        clause_node = Node(
            node_id=node_id,
            node_type=NodeType.PolicyClause,
            canonical_name=clause_title,
            normalized_name=normalized_title,
            properties={
                "doc_short": doc_short,
                "doc_name": meta.get("doc_name"),
                "policy_product": meta.get("product_name") or doc_short,
                "clause_id_text": clause_id_text,
                "clause_title": clause_title,
                "clause_type": clause_type,
                "page_start": page_start,
                "page_end": page_end,
                "section_path": self._section_path(meta),
                "excerpt": text[:240],
                "generation_scope": generation_scope,
                "decision_polarity": decision_polarity,
                "rule_types": rule_types,
                "rule_summary": rule_summary,
                "source_priority": source_priority,
            },
        )
        self.store.upsert_node(clause_node)

        evidence_id = f"ev_{node_id}"
        canonical_chunk_id, lookup_metadata = _chunk_lookup_payload(meta, chunk_id)
        evidence = Evidence(
            evidence_id=evidence_id,
            chunk_id=chunk_id,
            canonical_chunk_id=canonical_chunk_id,
            doc_short=doc_short,
            doc_name=meta.get("doc_name"),
            pdf_filename=meta.get("pdf_filename"),
            page_start=page_start,
            page_end=page_end,
            source_version=meta.get("source_version") or meta.get("version"),
            source_method="policy_review_chunk_extractor",
            row_text=text[:800],
            metadata_json={
                "section_path": self._section_path(meta),
                **lookup_metadata,
            },
        )
        self.store.upsert_evidence(evidence)
        self.store.link_node_evidence(node_id, evidence_id, role="source")

        self._link_policy_review_metadata(node_id, text, meta, evidence_id, for_case=False)

    def _extract_case_example(self, chunk: dict[str, Any], text: str, meta: dict[str, Any]) -> None:
        if not any(keyword in text for keyword in ("질문", "상담", "사례", "합병증", "실손", "특약", "보상")):
            return
        chunk_id = chunk["id"]
        page_start = meta.get("page_start")
        page_end = meta.get("page_end", page_start)
        case_no = self._extract_case_no(text, chunk_id)
        case_title = self._derive_clause_title(text, meta)
        normalized = normalize_name(f"{case_no} {case_title}".strip())
        node_id = f"case_{normalized}_{page_start}"
        topic_tags = self._matched_keys(text, POLICY_REVIEW_TOPICS)
        decision_hint = self._classify_decision_polarity(text)

        case_node = Node(
            node_id=node_id,
            node_type=NodeType.CaseExample,
            canonical_name=case_title,
            normalized_name=normalized,
            properties={
                "case_no": case_no,
                "case_title": case_title,
                "question_summary": text[:180],
                "review_summary": text[:240],
                "page_start": page_start,
                "page_end": page_end,
                "topic_tags": topic_tags,
                "decision_hint": decision_hint,
            },
        )
        self.store.upsert_node(case_node)

        evidence_id = f"ev_{node_id}"
        canonical_chunk_id, lookup_metadata = _chunk_lookup_payload(meta, chunk_id)
        evidence = Evidence(
            evidence_id=evidence_id,
            chunk_id=chunk_id,
            canonical_chunk_id=canonical_chunk_id,
            doc_short="상담사례집",
            doc_name=meta.get("doc_name"),
            pdf_filename=meta.get("pdf_filename"),
            page_start=page_start,
            page_end=page_end,
            source_version=meta.get("source_version") or meta.get("version"),
            source_method="case_example_chunk_extractor",
            row_text=text[:800],
            metadata_json=lookup_metadata,
        )
        self.store.upsert_evidence(evidence)
        self.store.link_node_evidence(node_id, evidence_id, role="source")

        self._link_policy_review_metadata(node_id, text, meta, evidence_id, for_case=True)

    def _link_policy_review_metadata(
        self,
        source_node_id: str,
        text: str,
        meta: dict[str, Any],
        evidence_id: str,
        for_case: bool,
    ) -> None:
        for topic in self._matched_keys(text, POLICY_REVIEW_TOPICS):
            self._link(source_node_id, f"cov_{normalize_name(topic)}", EdgeType.HAS_TOPIC, evidence_id)
            if for_case:
                self._link(source_node_id, f"cov_{normalize_name(topic)}", EdgeType.SIMILAR_CASE_FOR, evidence_id)

        for condition in self._matched_keys(text, CLAIM_CONDITIONS):
            self._link(source_node_id, f"cond_{normalize_name(condition)}", EdgeType.APPLIES_WHEN, evidence_id)

        for concept in self._matched_keys(text, COMPLICATION_CONCEPTS):
            self._link(source_node_id, f"comp_{normalize_name(concept)}", EdgeType.RELATES_TO_COMPLICATION, evidence_id)

        for requirement in self._matched_keys(text, EVIDENCE_REQUIREMENTS):
            self._link(source_node_id, f"evidence_req_{normalize_name(requirement)}", EdgeType.REQUIRES_EVIDENCE, evidence_id)

        for decision in self._matched_keys(text, DECISION_CONCEPTS):
            self._link(source_node_id, f"decision_{normalize_name(decision)}", EdgeType.HAS_DECISION, evidence_id)

        for generation, keywords in POLICY_GENERATIONS.items():
            if generation == "공통" or any(keyword in text for keyword in keywords):
                self._link(source_node_id, f"generation_{normalize_name(generation)}", EdgeType.APPLIES_TO_GENERATION, evidence_id)

        for visit in self._matched_keys(text, VISIT_CONTEXTS):
            self._link(source_node_id, f"visit_{normalize_name(visit)}", EdgeType.APPLIES_TO_VISIT, evidence_id)

        for facility in self._matched_keys(text, FACILITY_CONTEXTS):
            self._link(source_node_id, f"facility_{normalize_name(facility)}", EdgeType.APPLIES_TO_FACILITY, evidence_id)

        for action in self._matched_keys(text, REVIEW_ACTIONS):
            self._link(source_node_id, f"review_action_{normalize_name(action)}", EdgeType.HAS_REVIEW_ACTION, evidence_id)

        self._link_policy_rule_nodes(source_node_id, text, evidence_id)

        diagnosis_codes = []
        for code in meta.get("codes") or []:
            code_str = str(code).strip()
            if DIAGNOSIS_CODE_RX.fullmatch(code_str):
                diagnosis_codes.append(code_str)
        for match in DIAGNOSIS_CODE_RX.findall(text):
            diagnosis_codes.append(match)

        seen_codes = set()
        for code in diagnosis_codes:
            normalized = normalize_code(code)
            if normalized in seen_codes:
                continue
            seen_codes.add(normalized)
            node_id = f"diag_{normalized}"
            self.store.upsert_node(
                Node(
                    node_id=node_id,
                    node_type=NodeType.DiagnosisCode,
                    canonical_name=code,
                    normalized_name=normalized,
                    properties={"code": code},
                )
            )
            self._link(source_node_id, node_id, EdgeType.RELATES_TO_DIAGNOSIS, evidence_id)

    def _link_policy_rule_nodes(self, source_node_id: str, text: str, evidence_id: str) -> None:
        exclusion_reasons = self._matched_spec_keys(text, EXCLUSION_REASONS)
        for reason in exclusion_reasons:
            target_id = f"exclusion_reason_{normalize_name(reason)}"
            self._link(source_node_id, target_id, EdgeType.HAS_EXCLUSION_REASON, evidence_id)
            condition_id = f"cond_{normalize_name(reason)}"
            if reason in CLAIM_CONDITIONS:
                self._link(condition_id, target_id, EdgeType.TRIGGERS_EXCLUSION_REASON, evidence_id)

        for limit in self._matched_spec_keys(text, BENEFIT_LIMITS):
            self._link(source_node_id, f"benefit_limit_{normalize_name(limit)}", EdgeType.HAS_BENEFIT_LIMIT, evidence_id)

        for rule in self._matched_spec_keys(text, DEDUCTIBLE_RULES):
            self._link(source_node_id, f"deductible_rule_{normalize_name(rule)}", EdgeType.HAS_DEDUCTIBLE_RULE, evidence_id)

        for doc in self._matched_keys(text, REQUIRED_DOCUMENTS):
            doc_id = f"required_doc_{normalize_name(doc)}"
            self._link(source_node_id, doc_id, EdgeType.REQUIRES_DOCUMENT, evidence_id)
            if doc == "진료비 세부내역서":
                self._link(f"review_action_{normalize_name('세부내역서 요청')}", doc_id, EdgeType.REQUESTS_DOCUMENT, evidence_id)
            elif doc == "진단서":
                self._link(f"review_action_{normalize_name('진단서 요청')}", doc_id, EdgeType.REQUESTS_DOCUMENT, evidence_id)
            elif doc == "수술확인서":
                self._link(f"review_action_{normalize_name('수술확인서 요청')}", doc_id, EdgeType.REQUESTS_DOCUMENT, evidence_id)

        for rule in self._matched_spec_keys(text, COORDINATION_RULES):
            self._link(source_node_id, f"coordination_rule_{normalize_name(rule)}", EdgeType.HAS_COORDINATION_RULE, evidence_id)

        for rule in self._matched_spec_keys(text, RENEWAL_OR_GENERATION_RULES):
            self._link(source_node_id, f"generation_rule_{normalize_name(rule)}", EdgeType.HAS_GENERATION_RULE, evidence_id)

    def _link(self, source_node_id: str, target_node_id: str, edge_type: EdgeType, evidence_id: str) -> None:
        edge_id = f"edge_{edge_type.value.lower()}_{source_node_id}_{target_node_id}"
        self.store.upsert_edge(
            Edge(
                edge_id=edge_id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                edge_type=edge_type,
                source_evidence_id=evidence_id,
            )
        )
        self.store.link_edge_evidence(edge_id, evidence_id, role="source")

    def _matched_keys(self, text: str, mapping: dict[str, list[str]]) -> list[str]:
        lowered = text.lower()
        matched = []
        for key, keywords in mapping.items():
            if not keywords:
                continue
            key_lower = key.lower()
            if key_lower in lowered:
                matched.append(key)
                continue

            if key in STRICT_ALL_KEY_MATCHES:
                if all(keyword.lower() in lowered for keyword in keywords):
                    matched.append(key)
                continue

            if any(keyword.lower() in lowered for keyword in keywords):
                matched.append(key)
        return matched

    def _matched_spec_keys(self, text: str, mapping: dict[str, dict[str, Any]]) -> list[str]:
        lowered = text.lower()
        matched = []
        for key, spec in mapping.items():
            keywords = spec.get("keywords") or []
            if key.lower() in lowered:
                matched.append(key)
                continue
            if any(str(keyword).lower() in lowered for keyword in keywords):
                matched.append(key)
        return matched

    def _extract_clause_id(self, text: str, meta: dict[str, Any]) -> str:
        match = re.search(r"(제\s*\d+\s*조|\[별표\s*\d+\])", text)
        if match:
            return match.group(1).replace(" ", "")
        section = str(meta.get("section") or "")
        if section:
            return section[:60]
        chapter = str(meta.get("chapter") or "")
        return chapter[:60] if chapter else "chunk"

    def _derive_clause_title(self, text: str, meta: dict[str, Any]) -> str:
        for key in ("section", "chapter", "part"):
            value = str(meta.get(key) or "").strip()
            if value:
                return value
        first_line = text.splitlines()[0].strip()
        return first_line[:120] if first_line else "정책 조항"

    def _classify_clause_type(self, text: str) -> str:
        if any(token in text for token in ("면책", "보상하지", "지급하지 않는", "보상 제외")):
            return "exclusion"
        if any(token in text for token in ("한도", "최대", "횟수")):
            return "limit_rule"
        if any(token in text for token in ("공제", "부담", "자기부담")):
            return "deductible_rule"
        if any(token in text for token in ("세부내역서", "진단서", "영수증", "확인서", "제출", "첨부")):
            return "evidence_requirement"
        if any(token in text for token in ("정의", "뜻은 다음과 같다")):
            return "definition"
        if any(token in text for token in ("추가 확인", "심사 필요", "검토 필요")):
            return "review_required"
        if any(token in text for token in ("보장", "지급사유", "보험금")):
            return "coverage_trigger"
        return "special_case"

    def _classify_rule_types(self, text: str) -> list[str]:
        rule_types: list[str] = []
        has_exclusion = any(token in text for token in ("면책", "보상하지", "지급하지 않는", "보상 제외"))
        if has_exclusion:
            rule_types.append("ExclusionRule")
        if not has_exclusion and any(token in text for token in ("보장", "지급사유", "보험금", "보상 가능", "지급한다", "보상한다")):
            rule_types.append("CoverageTriggerRule")
        if any(token in text for token in ("한도", "최대", "횟수", "연간", "회당")):
            rule_types.append("LimitRule")
        if any(token in text for token in ("공제", "자기부담", "본인 부담", "부담한 의료비")):
            rule_types.append("DeductibleRule")
        if any(token in text for token in ("세부내역서", "진단서", "영수증", "확인서", "제출", "첨부", "증빙")):
            rule_types.append("EvidenceGateRule")
        if any(token in text for token in ("우선", "다만", "제외하고", "불구하고", "한하여", "경우에 한하여")):
            rule_types.append("PrecedenceRule")
        return rule_types or ["PolicyClause"]

    def _build_rule_summary(self, text: str, rule_types: list[str], decision_polarity: str) -> str:
        clean = " ".join(text.split())
        excerpt = clean[:140]
        return f"{'/'.join(rule_types)} | {decision_polarity} | {excerpt}"

    def _classify_decision_polarity(self, text: str) -> str:
        if any(token in text for token in ("면책", "보상하지", "지급하지 않는", "보상 제외")):
            return "exclusion"
        if any(token in text for token in ("추가 확인", "심사 필요", "검토 필요", "증빙")):
            return "review"
        if any(token in text for token in ("진단서", "영수증", "세부내역서", "확인서")):
            return "evidence"
        if any(token in text for token in ("보장", "지급", "보험금")):
            return "coverage"
        return "unknown"

    def _classify_generation_scope(self, text: str) -> str:
        lowered = text.lower()
        has_4th = "4세대" in text or "4th" in lowered
        has_5th = "5세대" in text or "5th" in lowered
        if has_4th and not has_5th:
            return "4th"
        if has_5th and not has_4th:
            return "5th"
        return "common"

    def _section_path(self, meta: dict[str, Any]) -> str:
        parts = [str(meta.get(key) or "").strip() for key in ("part", "chapter", "section")]
        return " / ".join(part for part in parts if part)

    def _extract_case_no(self, text: str, chunk_id: str) -> str:
        match = re.search(r"(사례\s*\d+|Q\d+|A\d+)", text)
        if match:
            return match.group(1).replace(" ", "")
        return chunk_id


class SilsonCoverageExtractor:
    """Extracts CoverageItem hierarchy (e.g. 비급여 -> 3대비급여) for 4th/5th generation policies."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self) -> None:
        self.store.begin()

        # Define nodes
        hierarchy = {
            "급여": [],
            "비급여": ["3대비급여", "비중증 비급여", "중증 비급여"],
            "3대비급여": ["도수치료", "체외충격파치료", "증식치료", "주사료", "자기공명영상진단(MRI/MRA)"],
            "실손": ["3대비급여", "상급병실료 차액", "건강보험 미적용 특례", "합병증 치료", "미용 목적 치료"],
        }

        # Create nodes
        for parent, children in hierarchy.items():
            parent_id = f"cov_{normalize_name(parent)}"
            self.store.upsert_node(
                Node(
                    node_id=parent_id,
                    node_type=NodeType.CoverageItem,
                    canonical_name=parent,
                    normalized_name=normalize_name(parent),
                )
            )
            for child in children:
                child_id = f"cov_{normalize_name(child)}"
                self.store.upsert_node(
                    Node(
                        node_id=child_id,
                        node_type=NodeType.CoverageItem,
                        canonical_name=child,
                        normalized_name=normalize_name(child),
                    )
                )

                # Link child to parent
                edge_id = f"edge_cov_sub_{normalize_name(child)}_{normalize_name(parent)}"
                self.store.upsert_edge(
                    Edge(
                        edge_id=edge_id,
                        source_node_id=child_id,
                        target_node_id=parent_id,
                        edge_type=EdgeType.HAS_CATEGORY,
                        properties={"relationship": "subcategory_of"}
                    )
                )

        self.store.commit()
