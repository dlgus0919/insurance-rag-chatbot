# 165. GraphDB Ontology 2차 확장 단계별 구현 계획

작성일: 2026-06-01
대상 프로젝트: `insurance-rag-chatbot`
대상 범위: 문서 기반 보험 ontology 2차 확장

## 1. 목적

현재 GraphRAG는 합병증, 미용 목적, 증빙, 실손 세대, 방문 구분 같은 review path 중심 판단 개념을 다룬다. 또한 `PolicyClause.properties.rule_types`에 `ExclusionRule`, `LimitRule`, `DeductibleRule`, `EvidenceGateRule` 같은 rule 성격을 저장한다.

2차 확장의 목적은 이 rule 성격을 더 실무적인 독립 판단 노드로 승격해, 보상 담당자가 다음 항목을 구조적으로 추적할 수 있게 하는 것이다.

- 왜 면책 또는 보상제외인지
- 어떤 한도와 공제가 적용되는지
- 어떤 서류가 있어야 확정 가능한지
- 자동차보험, 산재보험, 타보험과 어떻게 조정되는지
- 4세대, 5세대, 상품 세대 차이가 어떤 규칙에 영향을 주는지

핵심 원칙:

- 외부 의학 지식이나 외부 보험 ontology를 도입하지 않는다.
- 원문 약관, 사례집, 실무가이드, HIRA, 비급여 표준모델에서 직접 읽히는 사실만 graph에 적재한다.
- 자동 보상 확정보다는 근거 경로, 검토 조건, 부족 증빙, 사람 심사 이관을 우선한다.
- 기존 `PolicyClause` 기반 review path를 깨지 않고, 단계적으로 rule node를 병행 도입한다.

## 2. 현재 상태 요약

현재 구현된 주요 노드와 경로:

- `PolicyClause`
- `CaseExample`
- `ClaimCondition`
- `DecisionConcept`
- `EvidenceRequirement`
- `ComplicationConcept`
- `PolicyGeneration`
- `VisitContext`
- `FacilityContext`
- `ReviewAction`

현재 rule layer:

- `PolicyClause.properties.rule_types`
- `PolicyClause.properties.rule_summary`
- 지원 rule type:
  - `CoverageTriggerRule`
  - `ExclusionRule`
  - `LimitRule`
  - `DeductibleRule`
  - `EvidenceGateRule`
  - `PrecedenceRule`

최근 검증 상태:

- `scripts/eval_graph_review_paths.py` 기준 review path 평가 통과
- `v2_only / v1_v2_combined / GraphDB` canonical chunk identity 정렬 완료
- GraphDB evidence와 VectorStore 근거 연결은 canonical key 중심으로 회수 가능

남은 구조적 한계:

- rule type이 아직 `PolicyClause` 내부 속성에 머문다.
- 공제, 한도, 필요서류, 중복보상 조정 같은 개념을 독립적으로 검색하고 비교하기 어렵다.
- 보험금 계산 결과와 Graph rule 설명이 완전히 같은 노드 체계를 공유하지 않는다.

## 3. 2차 확장 대상 노드

### 3.1 ExclusionReason

의미:

- 면책 또는 보상제외 판단의 사유 노드

초기 canonical set:

- `미용 목적`
- `예방 목적`
- `건강검진`
- `약관상 보상제외 치료`
- `고의 또는 중대한 과실`
- `전쟁/폭동 등 일반 면책`
- `타 보험 선보상`
- `자동차보험 처리 대상`
- `산재보험 처리 대상`

주요 속성:

- `reason_code`
- `display_name`
- `reason_category`
- `source_priority`
- `requires_human_review`

### 3.2 BenefitLimit

의미:

- 보상 한도, 횟수 한도, 기간 한도, 회당 한도 노드

초기 대상:

- 도수치료, 체외충격파치료, 증식치료 한도
- MRI/MRA 한도
- 비급여 주사료 한도
- 상급병실료 차액 한도
- 통원 1회 한도
- 연간 한도

주요 속성:

- `limit_scope`
- `limit_amount`
- `limit_count`
- `limit_period`
- `applies_to_generation`
- `applies_to_visit`
- `applies_to_topic`
- `unit_text`

### 3.3 DeductibleRule

의미:

- 자기부담금, 공제금액, 공제율 노드

초기 대상:

- 4세대 실손 급여/비급여 공제
- 5세대 실손 급여/비급여 공제
- 3대비급여 공제
- 통원/입원/처방조제별 공제

주요 속성:

- `deductible_type`
- `rate`
- `fixed_amount`
- `min_amount`
- `max_amount`
- `basis_text`
- `generation_scope`
- `visit_scope`

### 3.4 RequiredDocument

의미:

- 보상 판단 또는 계산 확정을 위해 필요한 서류 노드

초기 canonical set:

- `진료비 영수증`
- `진료비 세부내역서`
- `진단서`
- `수술확인서`
- `입퇴원확인서`
- `처방전`
- `검사결과지`
- `판독결과지`
- `진료확인서`

주요 속성:

- `document_name`
- `document_category`
- `required_for`
- `blocks_auto_decision`
- `alternative_names`

### 3.5 CoordinationRule

의미:

- 자동차보험, 산재보험, 타보험, 공적 급여 등과의 보상 조정 규칙 노드

초기 대상:

- 자동차보험 처리 후 실손 청구
- 산재보험 처리 후 실손 청구
- 타보험 중복 보상 조정
- 국가/공공 보상과의 관계
- 이미 보상받은 금액 차감

주요 속성:

- `coordination_type`
- `primary_payer`
- `secondary_review_required`
- `deduct_prior_payment`
- `required_evidence`

### 3.6 RenewalOrGenerationRule

의미:

- 실손 세대, 상품 갱신, 약관 개정에 따라 달라지는 규칙 노드

초기 대상:

- 4세대 실손
- 5세대 실손
- 공통 규칙
- 상품/특약별 적용 시점
- 갱신 또는 개정 전후 차이

주요 속성:

- `generation`
- `effective_period_text`
- `policy_product`
- `rule_subject`
- `applies_to_topic`
- `requires_generation_confirmation`

## 4. 관계 설계

신규 edge 후보:

- `PolicyClause --HAS_EXCLUSION_REASON--> ExclusionReason`
- `PolicyClause --HAS_BENEFIT_LIMIT--> BenefitLimit`
- `PolicyClause --HAS_DEDUCTIBLE_RULE--> DeductibleRule`
- `PolicyClause --REQUIRES_DOCUMENT--> RequiredDocument`
- `PolicyClause --HAS_COORDINATION_RULE--> CoordinationRule`
- `PolicyClause --HAS_GENERATION_RULE--> RenewalOrGenerationRule`
- `CoverageItem --HAS_BENEFIT_LIMIT--> BenefitLimit`
- `CoverageItem --HAS_DEDUCTIBLE_RULE--> DeductibleRule`
- `ClaimCondition --TRIGGERS_EXCLUSION_REASON--> ExclusionReason`
- `ReviewAction --REQUESTS_DOCUMENT--> RequiredDocument`

기존 edge와의 관계:

- `REQUIRES_EVIDENCE`는 유지한다.
- 새 `REQUIRES_DOCUMENT`는 더 구체적인 문서 노드 연결로 사용한다.
- `APPLIES_TO_GENERATION`, `APPLIES_TO_VISIT`, `HAS_REVIEW_ACTION`은 계속 사용한다.

## 5. 단계별 구현 계획

## Phase 1. Schema and Canonical Set 병행 도입

목표:

- 기존 review path를 깨지 않고 새 rule node를 저장할 수 있게 한다.

작업:

1. `NodeType`에 다음 값을 추가한다.
   - `ExclusionReason`
   - `BenefitLimit`
   - `DeductibleRule`
   - `RequiredDocument`
   - `CoordinationRule`
   - `RenewalOrGenerationRule`
2. `EdgeType`에 신규 edge를 추가한다.
3. canonical set을 코드 상수로 정의한다.
4. rebuild 시 canonical node를 먼저 upsert한다.

검증:

- GraphDB rebuild 후 신규 node type count 확인
- 기존 `eval_graph_review_paths.py` 회귀 없음
- 기존 `PolicyClause` path 생성 회귀 없음

완료 기준:

- 신규 node type이 SQLite에 저장된다.
- 기존 review path 평가가 모두 통과한다.

## Phase 2. PolicyClause to Rule Node Extractor

목표:

- `PolicyClause.properties.rule_types`에 머물던 rule 성격을 독립 node로 연결한다.

작업:

1. `PolicyRuleNodeExtractor` 또는 기존 `PolicyReviewExtractor` 확장
2. 원문 키워드와 clause metadata를 기반으로 rule node 연결
3. 한 조항에 복수 rule node 연결 허용
4. 근거 없는 자동 rule 생성 금지

매핑 예시:

- `보상하지`, `면책`, `보상 제외` -> `ExclusionReason`
- `한도`, `연간`, `회당`, `50회`, `350만원` -> `BenefitLimit`
- `공제`, `자기부담`, `본인 부담` -> `DeductibleRule`
- `영수증`, `세부내역서`, `진단서`, `제출` -> `RequiredDocument`
- `자동차보험`, `산재`, `타 보험`, `이미 보상` -> `CoordinationRule`
- `4세대`, `5세대`, `개정`, `갱신` -> `RenewalOrGenerationRule`

검증:

- extractor unit test 추가
- rule node가 반드시 evidence를 가진 clause에서만 생성되는지 확인
- rule node 연결 count가 과도하지 않은지 샘플 검토

완료 기준:

- 주요 정책 조항에서 rule node 연결이 생성된다.
- 기존 `rule_types`와 새 node 연결이 모순되지 않는다.

## Phase 3. Retriever Review Path 확장

목표:

- 질문에 맞는 rule node를 review path에 직접 노출한다.

작업:

1. `GraphQueryPlanner`의 topic/condition 추출을 rule node와 연결
2. `GraphRetriever`가 다음 path type을 확장 또는 세분화한다.
   - `claim_condition_review`
   - `claim_calculation_review`
   - `coordination_review`
   - `generation_rule_review`
3. review path step에 rule node를 포함한다.
4. `confirmed`, `review_required`, `candidate` status 규칙을 재정의한다.

상태 규칙:

- 명시 exclusion reason + 입력 조건 직접 일치: `confirmed`
- 한도/공제 규칙은 세대/방문 구분이 확정될 때만 `confirmed`
- 필요한 서류가 입력에 없으면 `review_required`
- 자동차보험/산재/타보험 조정은 기본 `review_required`
- 세대가 불명확하면 `RenewalOrGenerationRule`은 `candidate` 또는 `review_required`

검증:

- 샘플 질의별 path type, status, required document 확인
- forbidden text 기반 과잉 확정 방지 테스트 유지

완료 기준:

- 답변 payload에 rule node 기반 review path가 포함된다.
- 미확정 조건에서 확정 지급/면책 문구가 생성되지 않는다.

## Phase 4. Claim Calculation Pipeline 연결

목표:

- 보험금 계산 결과와 Graph rule explanation을 같은 ontology로 설명한다.

작업:

1. 계산 context에 graph rule refs를 추가한다.
2. `DeductibleRule`, `BenefitLimit`를 계산 설명에 연결한다.
3. `ExclusionReason`이 confirmed면 면책 override를 명확히 기록한다.
4. `RequiredDocument` 미충족이면 자동 확정 상태를 차단한다.
5. `CoordinationRule`이 있으면 지급액 확정보다 review action을 우선한다.

중요 원칙:

- 계산 자체는 deterministic rule을 유지한다.
- Graph rule node는 계산 근거 설명과 review trigger로 사용한다.
- Graph rule만으로 금액을 임의 계산하지 않는다.

검증:

- 도수치료 4세대/5세대 공제
- MRI/MRA 한도
- 상급병실료 차액
- 면책 표준코드
- 자동차보험/산재 중복 조정

완료 기준:

- 계산 payload에 적용된 rule node와 부족 서류가 표시된다.
- 면책/보류/예상 계산 상태가 일관되게 유지된다.

## Phase 5. API and UI Audit View 확장

목표:

- 보상 담당자가 rule node 기반 판단 경로를 업무 화면에서 바로 읽을 수 있게 한다.

작업:

1. API payload에 다음 필드를 추가 또는 정리한다.
   - `exclusion_reasons`
   - `benefit_limits`
   - `deductible_rules`
   - `required_documents`
   - `coordination_rules`
   - `generation_rules`
2. UI의 `구조화 검토 경로` 섹션을 rule category별로 묶는다.
3. 내부 node type 이름을 그대로 노출하지 않고 업무형 라벨로 표시한다.
4. 대화 저장 요약에 핵심 rule path를 남긴다.

UI 섹션 예시:

- `적용 가능 면책 사유`
- `적용 한도`
- `적용 공제`
- `필요 서류`
- `중복 보상 조정`
- `세대/갱신 기준`
- `권장 검토 조치`

검증:

- 브라우저 또는 API payload 기반 E2E 확인
- 긴 원문 HTML/표가 그대로 노출되지 않는지 확인
- 모바일/좁은 화면에서 섹션이 겹치지 않는지 확인

완료 기준:

- 실무자가 다음 검토 조치를 UI에서 바로 확인할 수 있다.
- 기존 답변/출처/구조화 근거 렌더링이 깨지지 않는다.

## Phase 6. Evaluation Dataset and Rebuild Gate 확장

목표:

- 2차 ontology 확장이 실제로 실무 판단 품질을 높였는지 자동 검증한다.

작업:

1. `eval/graph_review_paths.jsonl` 확장
2. `scripts/eval_graph_review_paths.py`에 rule node 검증 항목 추가
3. 신규 fixture test 추가
4. GraphDB rebuild 후 count gate 추가
5. sync diagnostic과 review path 평가를 함께 실행

추가 평가 케이스:

- 건강검진 목적 MRI 실손 청구
- 5세대 통원 MRI 50만원 한도
- 도수치료 10만원 공제 설명
- 영수증만 있고 세부내역서 없음
- 자동차보험 처리 후 실손 청구
- 산재 처리 후 실손 청구
- 4세대/5세대 도수치료 차이
- 특약 가입 여부 불명확한 합병증 청구

PASS 기준:

- 필요한 rule node가 review path에 포함된다.
- 원문 근거 없는 rule node가 생성되지 않는다.
- 세대/방문/서류가 불명확하면 확정 상태로 승격되지 않는다.
- 문서 밖 의학 인과를 만들지 않는다.
- 계산 결과가 면책/보류 조건을 무시하지 않는다.

완료 기준:

- 확장 평가셋 전체 PASS
- 주요 GraphDB count와 샘플 path가 재현 가능
- 전체 회귀 테스트 통과

## 6. 구현 순서 제안

1. `RequiredDocument`와 `ExclusionReason`부터 구현한다.
   - 현재 review path와 가장 직접적으로 연결된다.
   - 실무자에게 즉시 가치가 있다.

2. `BenefitLimit`와 `DeductibleRule`을 구현한다.
   - 보험금 계산 설명력과 직접 연결된다.
   - 4세대/5세대 계산 로직 검증과 함께 묶어야 한다.

3. `CoordinationRule`을 구현한다.
   - 자동차보험/산재/타보험 조정은 실무 중요도가 높다.
   - 자동 계산보다 review action 중심으로 설계한다.

4. `RenewalOrGenerationRule`을 구현한다.
   - 세대별 약관 차이를 rule graph로 정리한다.
   - 기존 `PolicyGeneration` node와 중복되지 않도록 적용 규칙 중심으로 둔다.

## 7. 위험과 대응

### 위험 1. Rule node 과잉 생성

문제:

- 키워드만 보고 너무 많은 조항에 rule node가 붙을 수 있다.

대응:

- 원문 excerpt, clause type, source priority, topic match를 함께 본다.
- 초기에는 `candidate` status로 많이 두고, 확정 조건을 엄격하게 둔다.

### 위험 2. 계산 로직과 Graph rule 충돌

문제:

- Graph rule이 계산 엔진과 다른 결론을 암시할 수 있다.

대응:

- 금액 계산은 deterministic pipeline이 수행한다.
- Graph rule은 설명과 review trigger로만 사용한다.
- 충돌 시 `review_required`로 보류한다.

### 위험 3. 세대/상품 적용 범위 혼동

문제:

- 4세대/5세대, 자사 상품, 표준약관 규칙이 섞일 수 있다.

대응:

- `RenewalOrGenerationRule`에는 반드시 generation/product scope를 둔다.
- scope가 불명확하면 확정하지 않는다.

### 위험 4. 외부 지식 유입

문제:

- 자동차보험/산재/합병증 관련 일반 지식이 문서 근거 없이 들어갈 수 있다.

대응:

- extractor는 프로젝트 원천 문서에 등장한 문구만 rule node로 연결한다.
- 질의에서 주장된 사실은 session assertion으로만 취급한다.

## 8. 산출물 계획

구현 시 추가 또는 수정할 파일 후보:

- `src/graph/schema.py`
- `src/graph/extractors.py`
- `src/graph/retriever.py`
- `src/graph/query_planner.py`
- `src/claim_calculation/pipeline.py`
- `src/api/rag_service.py`
- `frontend/js/pages/chat.js`
- `eval/graph_review_paths.jsonl`
- `scripts/eval_graph_review_paths.py`
- `tests/test_graph_policy_rule_nodes.py`
- `tests/test_graph_review_path_retriever.py`
- `tests/test_claim_calculation_pipeline.py`

문서 산출물:

- 구현 보고서
- GraphDB rebuild 검증 보고서
- 평가 결과 보고서

## 9. 2차 확장 완료 기준

다음 조건을 모두 만족하면 2차 확장을 완료로 본다.

- 6개 신규 rule node type이 GraphDB에 저장된다.
- 주요 `PolicyClause`가 rule node와 evidence 기반으로 연결된다.
- review path가 rule node를 직접 포함한다.
- 보험금 계산 payload가 적용 한도, 공제, 필요서류, 보류 사유를 구조적으로 노출한다.
- 자동차보험/산재/타보험 조정 질의가 자동 확정보다 review action을 우선한다.
- 4세대/5세대 불명확 질의가 확정 계산으로 흐르지 않는다.
- 확장 평가셋과 기존 회귀 테스트가 모두 통과한다.
