from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


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


class GraphQueryPlanner:
    def __init__(self) -> None:
        # 등급 시스템 정규식 (예: 신1-5종, 1-5종, 1-3종)
        self.grade_system_rx = re.compile(r"(신\s*1[-~]5종|1[-~]5종|1[-~]3종)")
        # 등급 값 정규식 (예: 4종, 5종 등)
        self.grade_value_rx = re.compile(r"([1-5])\s*종")
        # 카테고리 목록
        self.categories = ["소화기계", "호흡기계", "흉부", "비뇨기계", "신경계", "순환기계", "근골격계"]
        # 수가코드 정규식
        self.hira_code_rx = re.compile(r"\b([A-Z]{1,2}\d{3,4})\b")
        # 약관/상품 키워드
        self.products = ["SOL", "처음건강보험", "이지로운", "실손의료보험", "운전자보험", "자사_SOL건강"]
        self.appendices = ["별표7", "별표15", "별표"]
        # 별표 조항/항목 번호 정규식
        self.appendix_number_rx = re.compile(r"(?<!별표\s)(?<!별표)(\d{1,3})\s*(?:번\s*)?(?:항목|조항|항)\b|(\d{1,3})\s*번\b")

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

    def plan(self, query: str) -> GraphQueryPlan:
        plan = GraphQueryPlan()

        # 1. Entity Extraction
        # 1.1 Grade System
        gs_match = self.grade_system_rx.search(query)
        if gs_match:
            plan.grade_system = gs_match.group(1).replace(" ", "")

        # 1.2 Grade Value
        gv_match = self.grade_value_rx.search(query)
        if gv_match:
            plan.grade_value = gv_match.group(1)

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

        # 2. Intent Classification
        intents = []

        # 2.1 surgery_grade_lookup: 수술명과 등급 시스템이 질문에 있고 등급을 조회하는 뉘앙스
        if plan.procedure_name and ("종수" in query or "등급" in query or "몇 종" in query or "어떤 종" in query or "종은" in query):
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

        if not intents:
            intents.append("ordinary_rag")

        plan.intents = intents

        # Peer count
        peer_match = re.search(r"(\d+)\s*(가지|개|개수|명)", query)
        if peer_match:
            plan.requested_peer_count = int(peer_match.group(1))

        return plan
