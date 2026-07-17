from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from src.ontology.registry import OntologyRegistry, get_default_ontology_registry, matches_ontology_alias


@dataclass
class GraphQueryPlan:
    intents: List[str] = field(default_factory=list)
    procedure_name: Optional[str] = None
    grade_system: Optional[str] = None
    grade_value: Optional[str] = None
    category: Optional[str] = None
    policy_product: Optional[str] = None
    appendix: Optional[str] = None
    appendix_numbers: list[str] = field(default_factory=list)
    hira_code: Optional[str] = None
    requested_peer_count: int = 3
    diagnosis_codes: List[str] = field(default_factory=list)
    diagnosis_names: List[str] = field(default_factory=list)
    coverage_topics: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    complication_asserted: bool = False
    treatment_purpose: Optional[str] = None
    evidence_tags: List[str] = field(default_factory=list)
    policy_generation: Optional[str] = None
    visit_type: Optional[str] = None
    facility_type: Optional[str] = None
    one_disease_terms: List[str] = field(default_factory=list)
    claim_unit_terms: List[str] = field(default_factory=list)
    disease_grouping_requested: bool = False
    same_disease_claimed: bool = False
    same_treatment_purpose_claimed: bool = False
    recurrent_or_continuing_treatment: bool = False
    newly_found_disease_claimed: bool = False
    normalized_terms: dict[str, str] = field(default_factory=dict)
    term_correction_candidates: list[dict[str, Any]] = field(default_factory=list)
    ambiguous_terms: List[str] = field(default_factory=list)
    clarification_questions: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)


class GraphQueryPlanner:
    def __init__(self, ontology_registry: OntologyRegistry | None = None) -> None:
        self.ontology_registry = ontology_registry or get_default_ontology_registry()
        # 등급 시스템 정규식 (예: 신1-5종, 1-5종, 1-3종)
        self.grade_system_rx = re.compile(r"(신\s*1[-~∼]5종|1[-~∼]5종|1[-~∼]3종)")
        # 등급 값 정규식 (예: 4종, 5종 등)
        self.grade_value_rx = re.compile(r"([1-5])\s*종")
        self.grade_intent_rx = re.compile(r"몇\s*종|어떤\s*종|종수|등급")
        # 카테고리 목록
        self.categories = ["소화기계", "호흡기계", "흉부", "비뇨기계", "신경계", "순환기계", "근골격계"]
        # 수가코드 정규식
        self.hira_code_rx = re.compile(r"(?<![A-Z0-9.])([A-Z]{1,2}\d{3,4})(?![A-Z0-9.])")
        # 약관/상품 키워드
        self.products = ["SOL", "처음건강보험", "이지로운", "실손의료보험", "운전자보험", "자사_SOL건강"]
        self.appendices = ["별표7", "별표15", "별표"]
        self.coverage_topics = self.ontology_registry.coverage_topics
        self.conditions = self.ontology_registry.conditions
        self.evidence_tags = self.ontology_registry.evidence_tags
        self.term_aliases = self.ontology_registry.term_aliases
        self.condition_aliases = self.ontology_registry.condition_aliases
        self.term_candidate_aliases = self.ontology_registry.term_candidate_aliases
        self.facility_types = ["상급종합병원", "종합병원", "병원", "의원", "약국"]
        self.claim_unit_aliases = self.ontology_registry.claim_unit_aliases
        # 별표 조항/항목 번호 정규식
        self.appendix_number_rx = re.compile(r"(?<!별표\s)(?<!별표)(\d{1,3})\s*(?:번\s*)?(?:항목|조항|항)\b|(\d{1,3})\s*번\b")
        self.diagnosis_code_rx = re.compile(r"\b([A-Z][0-9]{2}(?:\.[0-9]+)?)\b")

        # 일반 수술 명칭 후보 정규식 매칭을 위한 키워드
        self.keywords = ["수술", "폐쇄술", "이식", "절제술", "성형술", "소작술", "술"]
        self.procedure_stop_phrases = [
            "에 해당하는 수술",
            "해당하는 수술",
            "수술분류표",
            "수술 종류",
            "수술종류",
            "수술 목록",
            "수술목록",
            "모두 나열",
        ]

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

    def _extract_grade_request(self, query: str) -> tuple[str | None, str | None]:
        """등급 체계를 먼저 제외해 독립적으로 지정한 종수만 읽는다."""

        system_match = self.grade_system_rx.search(query)
        grade_system = None
        value_source = query
        if system_match:
            grade_system = re.sub(r"\s+", "", system_match.group(1)).replace("~", "-").replace("∼", "-")
            value_source = f"{query[:system_match.start()]} {query[system_match.end():]}"

        value_match = self.grade_value_rx.search(value_source)
        return grade_system, value_match.group(1) if value_match else None

    def _append_candidate(
        self,
        plan: GraphQueryPlan,
        *,
        raw: str,
        normalized: str,
        reason: str,
        confidence: float = 0.72,
    ) -> None:
        if raw in plan.normalized_terms:
            return
        if any(item.get("raw") == raw and item.get("normalized") == normalized for item in plan.term_correction_candidates):
            return
        plan.term_correction_candidates.append(
            {
                "raw": raw,
                "normalized": normalized,
                "confidence": confidence,
                "source": "safe_candidate_rule",
                "reason": reason,
            }
        )
        self._append_unique(plan.ambiguous_terms, "용어 보정 후보")
        self._append_unique(
            plan.clarification_questions,
            f"'{raw}' 표현이 '{normalized}'을 의미하는지 확인해 주세요.",
        )

    def _apply_aliases(self, query: str, plan: GraphQueryPlan) -> None:
        for canonical, aliases in self.term_aliases.items():
            for alias in aliases:
                if matches_ontology_alias(query, alias):
                    self._append_unique(plan.coverage_topics, canonical)
                    if alias != canonical:
                        plan.normalized_terms[alias] = canonical
        for canonical, aliases in self.condition_aliases.items():
            for alias in aliases:
                if matches_ontology_alias(query, alias):
                    self._append_unique(plan.conditions, canonical)
                    if alias != canonical:
                        plan.normalized_terms[alias] = canonical

    def _apply_term_correction_candidates(self, query: str, plan: GraphQueryPlan) -> None:
        for normalized, aliases in self.term_candidate_aliases.items():
            for alias in aliases:
                if matches_ontology_alias(query, alias):
                    self._append_candidate(
                        plan,
                        raw=alias,
                        normalized=normalized,
                        reason="문서 기반 canonical 용어와 유사하지만 자동 확정하지 않는 사용자 입력 표현입니다.",
                    )

    def _apply_clarification(self, plan: GraphQueryPlan, clarification: dict | None) -> None:
        if not isinstance(clarification, dict):
            return
        selections = clarification.get("selections")
        if not isinstance(selections, list):
            return

        confirmed_groups: set[str] = set()
        for selection in selections:
            if not isinstance(selection, dict):
                continue
            group = str(selection.get("group") or "").strip()
            value = str(selection.get("value") or "").strip()
            raw = str(selection.get("raw") or "").strip()
            if not group or not value:
                continue

            confirmed_groups.add(group)
            if group == "policy_generation":
                if "5" in value:
                    plan.policy_generation = "5th"
                elif "4" in value:
                    plan.policy_generation = "4th"
            elif group == "visit_type":
                visit_map = {"입원": "hospitalization", "통원": "outpatient", "처방조제": "pharmacy"}
                plan.visit_type = visit_map.get(value, value)
            elif group == "policy_product":
                plan.policy_product = value
            elif group in {"evidence_tag", "evidence_tags"}:
                self._append_unique(plan.evidence_tags, value)
            elif group in {"condition", "conditions"}:
                self._append_unique(plan.conditions, value)
            elif group in {"coverage_topic", "coverage_topics"}:
                self._append_unique(plan.coverage_topics, value)
            elif group == "treatment_purpose":
                purpose_map = {
                    "치료 목적": "treatment",
                    "미용 목적": "cosmetic",
                    "예방/검진 목적": "preventive",
                    "예방 목적": "preventive",
                    "합병증 치료": "complication_treatment",
                }
                plan.treatment_purpose = purpose_map.get(value, value)
                if value in self.conditions:
                    self._append_unique(plan.conditions, value)
            elif group == "term_correction":
                if raw:
                    plan.normalized_terms[raw] = value
                    plan.term_correction_candidates = [
                        item for item in plan.term_correction_candidates
                        if not (item.get("raw") == raw and item.get("normalized") == value)
                    ]
                    plan.clarification_questions = [
                        question for question in plan.clarification_questions
                        if raw not in question or value not in question
                    ]
                if value in self.coverage_topics or value in {"MRI", "MRA"}:
                    self._append_unique(plan.coverage_topics, value)

        ambiguous_by_group = {
            "policy_generation": "실손 세대",
            "visit_type": "방문 구분",
            "policy_product": "상품/특약",
            "treatment_purpose": "치료 목적",
            "evidence_tag": "증빙 서류",
            "evidence_tags": "증빙 서류",
            "term_correction": "용어 보정 후보",
        }
        resolved = {ambiguous_by_group[group] for group in confirmed_groups if group in ambiguous_by_group}
        if not plan.term_correction_candidates:
            resolved.add("용어 보정 후보")
        if resolved:
            plan.ambiguous_terms = [term for term in plan.ambiguous_terms if term not in resolved]

    def _add_clarification_questions(self, plan: GraphQueryPlan, query: str) -> None:
        judgment_tokens = (
            "보상", "청구", "계산", "지급", "가능", "한도", "공제", "자기부담",
            "검토", "판단", "확인", "봐야", "되나요", "받을 수",
        )
        if any(token in query for token in judgment_tokens):
            generation_sensitive = {
                "실손", "도수치료", "체외충격파치료", "증식치료", "비급여 주사료",
                "MRI", "MRA", "자기공명영상진단", "상급병실료 차액", "3대비급여",
            }
            if generation_sensitive.intersection(plan.coverage_topics) and not plan.policy_generation:
                self._append_unique(plan.clarification_questions, "어느 실손 세대(예: 4세대/5세대) 기준인지 확인해 주세요.")
                self._append_unique(plan.ambiguous_terms, "실손 세대")

            visit_sensitive = generation_sensitive | {"건강보험 미적용"}
            if visit_sensitive.intersection(plan.coverage_topics) and not plan.visit_type:
                self._append_unique(plan.clarification_questions, "입원/통원/처방조제 중 어떤 방문 구분인지 확인해 주세요.")
                self._append_unique(plan.ambiguous_terms, "방문 구분")

            if ("특약" in plan.coverage_topics or "특약 가입 여부 확인" in plan.conditions) and not plan.policy_product:
                self._append_unique(plan.clarification_questions, "어떤 상품 또는 특약 가입 여부를 기준으로 볼지 확인해 주세요.")
                self._append_unique(plan.ambiguous_terms, "상품/특약")

            if (
                "미용 목적" in plan.coverage_topics
                or "미용 목적" in plan.conditions
                or "건강검진" in plan.coverage_topics
                or "예방 목적" in plan.conditions
            ) and "치료 목적" not in plan.conditions:
                self._append_unique(plan.clarification_questions, "치료 목적인지 미용/예방 목적인지 확인할 수 있는 진단서 또는 의사소견이 있는지 확인해 주세요.")
                self._append_unique(plan.ambiguous_terms, "치료 목적")

            if not plan.evidence_tags and any(topic in plan.coverage_topics for topic in generation_sensitive | {"실손", "건강보험 미적용"}):
                self._append_unique(plan.clarification_questions, "진료비 영수증, 진료비 세부내역서, 진단서 등 어떤 증빙이 있는지 확인해 주세요.")
                self._append_unique(plan.ambiguous_terms, "증빙 서류")

        questions, evidence = self.ontology_registry.planner_guidance(
            plan.coverage_topics,
            plan.conditions,
        )
        for question in questions:
            self._append_unique(plan.clarification_questions, question)
        for item in evidence:
            self._append_unique(plan.required_evidence, item)

    def plan(self, query: str, clarification: dict | None = None) -> GraphQueryPlan:
        plan = GraphQueryPlan()

        # 1. Entity Extraction
        # 1.1 Grade System
        plan.grade_system, plan.grade_value = self._extract_grade_request(query)

        # 1.3 Category
        for cat in self.categories:
            if cat in query:
                plan.category = cat
                break

        # 1.4 HIRA code
        hira_match = self.hira_code_rx.search(query)
        if hira_match:
            plan.hira_code = hira_match.group(1)

        # 1.5 Product / Appendix
        for prod in self.products:
            if prod in query:
                plan.policy_product = prod
                break
        for app in self.appendices:
            if app in query:
                plan.appendix = app
                break

        # 1.5.1 Appendix Numbers
        for m in self.appendix_number_rx.finditer(query):
            num = m.group(1) or m.group(2)
            if num and num not in plan.appendix_numbers:
                plan.appendix_numbers.append(num)

        category_grade_listing_query = bool(
            plan.category
            and plan.grade_value
            and any(token in query for token in ("수술분류표", "카테고리", "나열", "목록", "모두"))
        )

        # 1.6 Procedure Name extraction
        matched_proc = None

        if not category_grade_listing_query:
            # 1) 따옴표로 묶인 이름 우선 추출
            quote_match = re.search(r"['\"]([^'\"]+)['\"]", query)
            if quote_match:
                matched_proc = quote_match.group(1)
            else:
                # 2) 조사 없이 수술 키워드로 끝나는 단어/구절 매칭
                # 예: "기관지 식도루 폐쇄술" "간장 이식수술" 등
                pattern = rf"\b([가-힣]+(?:\s+[가-힣]+)*?(?:{'|'.join(self.keywords)}))\b"
                rx_proc = re.compile(pattern)

                candidates = rx_proc.findall(query)
                for cand in candidates:
                    cand_clean = cand.strip()
                    # Stopwords 필터
                    stopwords = [
                        "차이점", "공통점", "수술종류", "수술 종류", "수술분류",
                        "수술 분류", "수술종수", "수술 종수", "수술기록",
                        "수술종은", "수술종", "수술에", "수술의", "수술은", "수술을", "수술이",
                    ]
                    if not any(sw in cand_clean for sw in stopwords) and cand_clean not in self.categories and not any(p in cand_clean for p in self.products):
                        if cand_clean in self.keywords or cand_clean in ["이식수술", "수술명", "수술종류", "수술분류"]:
                            continue
                        if len(cand_clean) >= 2:
                            matched_proc = cand_clean
                            break

                # 3) 만약 여전히 없다면, 조사를 이용한 매칭
                if not matched_proc:
                    for marker in ["의", "은", "는", "이", "가", "에", "을", "를", "에서", "으로"]:
                        rx = re.compile(rf"\b([가-힣\s]{{2,20}}){marker}\b")
                        m = rx.search(query)
                        if m:
                            candidate = m.group(1).strip()
                            if candidate not in self.categories and not any(p in candidate for p in self.products):
                                if any(kw in candidate for kw in self.keywords):
                                    stopwords = [
                                        "차이점", "공통점", "수술종류", "수술 종류", "수술분류",
                                        "수술 분류", "수술종수", "수술 종수", "수술기록",
                                        "수술종은", "수술종",
                                    ]
                                    if not any(sw in candidate for sw in stopwords):
                                        if candidate in self.keywords or candidate in ["이식수술", "수술명", "수술종류", "수술분류"]:
                                            continue
                                        matched_proc = candidate
                                        break

        if matched_proc:
            matched_proc = matched_proc.strip()
            for kw in self.keywords:
                if f"{kw}과" in matched_proc:
                    matched_proc = matched_proc.split(f"{kw}과")[0].strip() + f" {kw}"
                    break
                if f"{kw}와" in matched_proc:
                    matched_proc = matched_proc.split(f"{kw}와")[0].strip() + f" {kw}"
                    break
            if matched_proc in self.keywords or matched_proc in ["이식수술", "수술명", "수술종류", "수술분류"]:
                matched_proc = None
            if matched_proc and any(phrase in matched_proc for phrase in self.procedure_stop_phrases):
                matched_proc = None

        if matched_proc:
            plan.procedure_name = matched_proc.strip()

        # 1.7 Diagnosis codes
        for match in self.diagnosis_code_rx.finditer(query):
            code = match.group(1)
            if code not in plan.diagnosis_codes:
                plan.diagnosis_codes.append(code)

        # 1.8 Coverage topics / conditions / evidence tags
        lowered_query = query.lower()
        for topic in self.coverage_topics:
            if topic.lower() in lowered_query and topic not in plan.coverage_topics:
                plan.coverage_topics.append(topic)
        for condition in self.conditions:
            if condition.lower() in lowered_query and condition not in plan.conditions:
                plan.conditions.append(condition)
        self._apply_aliases(query, plan)
        self._apply_term_correction_candidates(query, plan)
        for tag in self.evidence_tags:
            if tag.lower() in lowered_query and tag not in plan.evidence_tags:
                plan.evidence_tags.append(tag)
        for facility in self.facility_types:
            if facility in query:
                plan.facility_type = facility
                break
        for canonical, aliases in self.claim_unit_aliases.items():
            if any(alias in query for alias in aliases):
                self._append_unique(plan.claim_unit_terms, canonical)
                self._append_unique(plan.one_disease_terms, canonical)
                plan.disease_grouping_requested = True
                if canonical == "하나의 질병":
                    plan.same_disease_claimed = True
        if any(token in query for token in ("같은 치료 목적", "동일한 치료 목적", "같은 치료를 목적")):
            plan.same_treatment_purpose_claimed = True
            plan.disease_grouping_requested = True
        if any(token in query for token in ("2회 이상", "반복 치료", "재입원", "계속 입원", "계속 치료", "90회", "90건", "180일")):
            plan.recurrent_or_continuing_treatment = True
            plan.disease_grouping_requested = True
        if any(token in query for token in ("새로 발견된 질병", "새로 발견", "병행 치료")):
            plan.newly_found_disease_claimed = True
            plan.disease_grouping_requested = True

        if "입원" in query:
            plan.visit_type = "hospitalization"
        elif "통원" in query:
            plan.visit_type = "outpatient"

        if "5세대" in query or "5th" in lowered_query:
            plan.policy_generation = "5th"
        elif "4세대" in query or "4th" in lowered_query:
            plan.policy_generation = "4th"

        explicit_complication_keywords = ["합병증", "부작용", "후유증"]
        post_treatment_keywords = ["수술 후", "시술 후", "처치 후"]
        post_treatment_problem_keywords = ["염증", "통증", "부작용", "후유증", "합병증", "치료"]
        if any(keyword in query for keyword in explicit_complication_keywords) or (
            any(keyword in query for keyword in post_treatment_keywords)
            and any(keyword in query for keyword in post_treatment_problem_keywords)
        ):
            plan.complication_asserted = True
        if "합병증 치료" in query:
            plan.treatment_purpose = "complication_treatment"
        elif "미용 목적" in query or "미용" in query:
            plan.treatment_purpose = "cosmetic"
        elif "치료 목적" in query or "치료목적" in query:
            plan.treatment_purpose = "treatment"
        elif "예방 목적" in query or "검진 목적" in query:
            plan.treatment_purpose = "preventive"

        self._apply_clarification(plan, clarification)

        # 2. Intent Classification
        intents = []

        # 2.1 surgery_grade_lookup: 수술명과 등급 시스템이 질문에 있고 등급을 조회하는 뉘앙스
        if plan.procedure_name and self.grade_intent_rx.search(query):
            intents.append("surgery_grade_lookup")

        # 2.2 same_grade_surgery_list: 동일한 종, 동일한 등급, 다른 수술 목록을 묻는 경우
        if "같은 종" in query or "동일한 종" in query or "동일한 등급" in query or "다른 수술" in query or "peer" in query:
            intents.append("same_grade_surgery_list")

        # 2.3 category_grade_listing: 카테고리와 등급 정보가 있을 때 나열 요청
        if plan.category and plan.grade_value and ("나열" in query or "알려줘" in query or "목록" in query or "모두" in query):
            intents.append("category_grade_listing")

        # 2.4 policy_appendix_payment_lookup: 지급비율, 보험금 비율 등 조회
        if "지급률" in query or "지급비율" in query or "보험금 비율" in query or "지급되는" in query or "보험금" in query or "별표" in query or "수술분류표" in query:
            intents.append("policy_appendix_payment_lookup")

        # 2.5 hira_code_lookup: 수가코드
        if "수가코드" in query or "수가" in query or "코드" in query:
            intents.append("hira_code_lookup")

        # 2.6 claim_policy_basis_lookup: 약관 근거 등
        if "약관 근거" in query or "청구 근거" in query or "근거" in query or "증빙" in query:
            intents.append("claim_policy_basis_lookup")

        if plan.complication_asserted:
            intents.append("complication_policy_lookup")
        if plan.disease_grouping_requested or plan.claim_unit_terms:
            intents.append("one_disease_policy_lookup")
            intents.append("disease_grouping_review")
        if plan.recurrent_or_continuing_treatment:
            intents.append("recurrent_treatment_review")
        if any(term in plan.claim_unit_terms for term in ("하나의 질병수술", "하나의 후유장해 지급한도")):
            intents.append("claim_unit_limit_review")
        if plan.diagnosis_codes:
            intents.append("diagnosis_policy_lookup")
        if plan.conditions:
            intents.append("claim_condition_lookup")
        if "사례" in query or "상담" in query:
            intents.append("case_example_lookup")
        if (
            plan.complication_asserted
            or plan.diagnosis_codes
            or plan.conditions
            or any(token in query for token in ("보상되나요", "가능하나요", "계산해줘", "특약", "청구", "지급", "확인"))
        ):
            intents.append("session_claim_path_review")

        # Peer count
        peer_match = re.search(r"(\d+)\s*(가지|개|개수|명)", query)
        if peer_match:
            plan.requested_peer_count = int(peer_match.group(1))

        self._add_clarification_questions(plan, query)
        if plan.clarification_questions:
            intents.append("session_claim_path_review")
            intents.append("ordinary_rag")
        if not intents:
            intents.append("ordinary_rag")
        plan.intents = list(dict.fromkeys(intents))
        return plan
