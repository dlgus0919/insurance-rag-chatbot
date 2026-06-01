# 170. One Disease Concept GraphRAG Ontology Expansion Plan

작성일: 2026-06-01
대상 프로젝트: `insurance-rag-chatbot`
대상 workspace: `/srv/shared/projects/insurance-rag-chatbot`
작성 목적: 손해보험 보상 실무에서 중요한 `하나의 질병` 판단 개념을 현재 GraphRAG Ontology에 어떻게 안전하게 확장할지 설계한다.

---

## 1. 결론 요약

현재 GraphDB에는 `하나의 질병`, `동일한 질병`, `하나의 상해`와 관련된 원문 약관 조항이 `PolicyClause`로 일부 적재되어 있다. 다만 이 개념이 별도 ontology node나 review path로 구조화되어 있지는 않다.

따라서 지금 상태의 GraphRAG는 다음은 가능하다.

- `하나의 질병`이라는 문구가 포함된 조항을 검색 근거로 찾기
- 해당 조항을 `통원`, `입원`, `합병증`, `공제`, `한도`, `세대` 같은 기존 노드와 일부 연결
- 합병증 주장이 있는 질문에서 검토 필요 경로를 만드는 것

하지만 다음은 아직 부족하다.

- 여러 진단/치료/수술이 `하나의 질병`으로 묶이는지 판단하는 별도 경로
- `동일 원인`, `의학상 중요한 관련`, `치료 중 발생한 합병증`, `새로 발견된 질병 병행 치료` 같은 grouping criterion의 구조화
- 질병수술비, 후유장해, 실손 통원/입원 한도 등 상품별로 서로 다른 `하나의 질병` 적용 범위 구분
- 질의/영수증/세부내역서에서 주장된 사실을 전역 GraphDB에 저장하지 않고 세션 단위로만 검토하는 구조

권장 방향은 `하나의 질병`을 의학 인과 ontology로 만들지 않는 것이다. 대신 약관 원문에서 직접 확인되는 판단 단위로 승격한다.

```text
PolicyClause
  -> DiseaseGroupingRule
  -> DiseaseRelationCriterion
  -> ClaimUnitConcept
  -> ReviewAction / RequiredDocument / BenefitLimit / DeductibleRule
```

---

## 2. 현재 근거 확인

DGX 기준 GraphDB와 raw/processed 문서를 교차 확인했다.

### 2.1 GraphDB 현황

현재 GraphDB에는 아래 주요 node type이 있다.

```text
PolicyClause
ClaimCondition
ComplicationConcept
DecisionConcept
EvidenceRequirement
DiagnosisCode
PolicyGeneration
VisitContext
FacilityContext
ReviewAction
BenefitLimit
DeductibleRule
CoordinationRule
RenewalOrGenerationRule
RequiredDocument
ExclusionReason
```

`OneDisease`, `DiseaseEpisode`, `DiseaseGroupingRule` 같은 전용 node type은 없다.

Phase 1 inventory 스크립트 기준으로 `PolicyClause` 중 `하나의 질병`, `동일한 질병`, `하나의 상해` 관련 표현이 포함된 조항은 현재 10건 확인되었다.

대표 조항:

- 실손 약관 p.31, p.71: 전환/재개 전후 `하나의 질병` 입원·통원 보상기간, 180일, 방문 90회/처방전 90건
- 자사 SOL 건강 p.258, p.261: `동일한 질병`으로 두 종류 이상의 질병수술 또는 같은 종류의 수술을 2회 이상 받은 경우 하나의 질병수술비만 지급
- 자사 SOL 건강 p.109: `하나의 질병`으로 인한 후유장해보험금 한도
- 표준약관 p.350: `하나의 질병`의 정의. 동일 발생 원인, 의학상 중요한 관련, 2회 이상 치료, 치료 중 발생한 합병증, 새로 발견된 질병 병행 치료, 의학상 관련 없는 여러 질병의 통원 처리 기준 포함

### 2.2 현재 edge 연결 상태

일부 `하나의 질병` 관련 조항은 이미 다음 노드들과 연결되어 있다.

- `CoverageItem`: 실손, 3대비급여, 합병증 치료
- `ClaimCondition`: 통원, 입원, 치료 목적 확인
- `PolicyGeneration`: 공통
- `VisitContext`: 입원, 통원
- `ReviewAction`: 질병/상해 구분 확인
- `BenefitLimit`: 통원 1회 한도 등
- `DeductibleRule`: 4세대/5세대/3대비급여/통원/입원 공제
- `ComplicationConcept`: 합병증
- `DiagnosisCode`: 일부 임신/출산 관련 코드 range

이는 기본적인 조항 연결은 되어 있다는 뜻이다. 그러나 `왜 하나의 질병으로 묶이는지`, `어떤 claim unit에 적용되는지`, `어떤 증빙이 있어야 하는지`는 별도 구조로 표현되지 않는다.

### 2.3 raw 문서에서 보이는 실무 의미

원문 문서에서 `하나의 질병`은 단순 질병명 node가 아니다. 보상 단위를 정하는 판단 개념이다.

주요 적용 맥락:

- 실손 통원/입원에서 한도와 보상기간을 계산하는 단위
- 같은 치료 목적의 반복 치료를 하나로 볼지 판단하는 단위
- 전환/재개 전후 계약에서 이전 계약 보상기간 연장으로 볼지 판단하는 단위
- 질병수술비에서 같은 질병으로 여러 수술을 받은 경우 지급 횟수를 제한하는 단위
- 질병 후유장해보험금에서 한도 적용 단위
- 합병증 또는 새로 발견된 질병의 병행 치료를 하나의 질병으로 간주할지 검토하는 단위

---

## 3. 설계 원칙

### 3.1 도입하지 않을 것

다음은 전역 GraphDB에 넣지 않는다.

- 당뇨 -> 망막병증 같은 질병 간 일반 의학 인과
- 특정 질병이 특정 합병증을 유발한다는 외부 임상 지식
- KCD 전체 ontology
- SNOMED/ICD 외부 질병 계층
- 질의에 없는 질병-시술 관계 추론

이유는 명확하다. 현재 프로젝트의 신뢰 근거는 약관, 실무가이드, 상담사례집, HIRA, 비급여표준모델 등 내부 원천 데이터다. 외부 의학 지식으로 질병 인과를 전역 그래프에 넣으면 보험 약관 판단과 의학 판단이 섞이고, 챗봇이 문서 밖 결론을 확정적으로 말할 위험이 커진다.

### 3.2 도입할 것

다음은 약관 원문에서 직접 도출 가능하므로 GraphRAG ontology에 올릴 수 있다.

- `하나의 질병`이라는 판단 개념
- 하나의 질병으로 묶는 기준
- 하나의 상해와의 병렬 구조
- 입원/통원/수술/후유장해별 적용 단위
- 세대/상품/조항별 적용 범위
- 필요한 증빙과 review action
- 질의 또는 청구 입력에서 주장된 질병·치료·합병증 관계를 세션 그래프에만 올리는 구조

---

## 4. Ontology 확장안

### 4.1 신규 NodeType

#### `ClaimUnitConcept`

보상 계산과 지급 횟수 산정의 단위를 나타낸다.

초기 canonical node:

- `하나의 질병`
- `하나의 상해`
- `하나의 통원`
- `하나의 입원`
- `하나의 질병수술`
- `하나의 후유장해 지급한도`

#### `DiseaseGroupingRule`

여러 질병/치료/수술을 하나의 질병으로 묶을 수 있는 약관상 규칙이다.

예:

- `동일 발생 원인 기준`
- `의학상 중요한 관련 기준`
- `동일 질병 2회 이상 치료 기준`
- `질병 치료 중 발생한 합병증 병행 기준`
- `새로 발견된 질병 병행 치료 기준`
- `관련 없는 여러 질병의 같은 통원 처리 기준`
- `동일 질병 다중 수술 지급 제한 기준`

#### `DiseaseRelationCriterion`

`DiseaseGroupingRule`의 하위 판단 기준이다.

초기 canonical node:

- `발생 원인 동일`
- `의학상 중요한 관련`
- `2회 이상 치료`
- `치료 중 발생한 합병증`
- `새로 발견된 질병`
- `의학상 관련 없는 여러 질병`
- `같은 치료 목적`
- `동일 질병 다중 수술`
- `같은 종류 수술 반복`

#### `TreatmentEpisodeContext`

세션 단위 청구 상황에서만 쓰는 치료 episode 맥락이다. 전역 GraphDB에는 canonical context만 두고, 개별 질병/치료 조합은 세션 메모리에만 둔다.

초기 canonical node:

- `동일일자 통원`
- `반복 통원`
- `계속 입원`
- `재입원`
- `전환/재개 전후 계속 치료`
- `질병수술 반복`
- `합병증 병행 치료`

### 4.2 신규 EdgeType

권장 edge:

- `DEFINES_CLAIM_UNIT`: `PolicyClause -> ClaimUnitConcept`
- `HAS_GROUPING_RULE`: `PolicyClause -> DiseaseGroupingRule`
- `HAS_RELATION_CRITERION`: `DiseaseGroupingRule -> DiseaseRelationCriterion`
- `APPLIES_TO_CLAIM_UNIT`: `DiseaseGroupingRule -> ClaimUnitConcept`
- `APPLIES_TO_TREATMENT_CONTEXT`: `DiseaseGroupingRule -> TreatmentEpisodeContext`
- `LIMITS_BY_CLAIM_UNIT`: `BenefitLimit/DeductibleRule -> ClaimUnitConcept`
- `REQUIRES_GROUPING_REVIEW`: `PolicyClause -> ReviewAction`
- `REQUIRES_GROUPING_EVIDENCE`: `DiseaseGroupingRule -> RequiredDocument`

기존 edge와 병행:

- `APPLIES_TO_GENERATION`
- `APPLIES_TO_VISIT`
- `HAS_TOPIC`
- `HAS_BENEFIT_LIMIT`
- `HAS_DEDUCTIBLE_RULE`
- `RELATES_TO_COMPLICATION`
- `HAS_REVIEW_ACTION`

### 4.3 Session graph 확장

전역 DB에 저장하지 않는 runtime dataclass를 추가한다.

#### `DiseaseEpisodeAssertion`

필드:

- `diagnosis_codes`
- `diagnosis_names`
- `procedure_names`
- `fee_codes`
- `treatment_dates`
- `visit_type`
- `claim_unit_candidate`
- `relation_claimed`
- `relation_source`
- `confidence`
- `notes`

`relation_claimed` 예:

- `same_disease_claimed`
- `complication_claimed`
- `same_treatment_purpose_claimed`
- `newly_found_disease_claimed`
- `unrelated_multiple_diseases_claimed`

`relation_source` 예:

- `question`
- `claim_form`
- `receipt_parser`
- `detail_statement_parser`
- `diagnosis_certificate_parser`
- `human_input`

중요한 제약:

- 세션 assertion은 SQLite GraphDB에 영구 저장하지 않는다.
- 질병 간 인과는 자동 생성하지 않는다.
- 사용자가 말한 `당뇨 때문에 망막 레이저`는 `주장된 사실`로만 저장한다.
- 약관 조항은 판단 경로를 제공하지만, 의학적 관련성 확정은 증빙 또는 human review로 넘긴다.

---

## 5. Retriever / Planner 적용 계획

### 5.1 Query planner 확장

`src/graph/query_planner.py`에 다음 필드를 추가한다.

- `one_disease_terms`
- `claim_unit_terms`
- `disease_grouping_requested`
- `same_disease_claimed`
- `same_treatment_purpose_claimed`
- `recurrent_or_continuing_treatment`
- `newly_found_disease_claimed`

신규 intent:

- `one_disease_policy_lookup`
- `disease_grouping_review`
- `claim_unit_limit_review`
- `recurrent_treatment_review`
- `same_disease_surgery_review`

트리거 예:

- `하나의 질병`, `같은 질병`, `동일 질병`, `동일한 질병`
- `합병증`, `새로 발견`, `재발`, `전이`, `후유증`
- `같은 치료 목적`, `반복 치료`, `재입원`, `계속 입원`
- `두 번 수술`, `여러 수술`, `같은 수술`, `수술비 한 번만`
- `180일`, `90회`, `통원 1회`, `입원 한도`

### 5.2 Retriever 확장

`src/graph/retriever.py`는 자유 path search가 아니라 bounded retrieval로 유지한다.

우선순위:

1. 질의/폼에서 `DiseaseEpisodeAssertion` 생성
2. `ClaimUnitConcept` 관련 clause 조회
3. `DiseaseGroupingRule`과 `DiseaseRelationCriterion` 조회
4. 세대, 상품, 입원/통원 context로 필터
5. 합병증 또는 새로 발견된 질병이 주장되면 기존 `ComplicationConcept` path와 병합
6. 수술/수가/질병코드가 있으면 기존 수술 graph, HIRA graph, diagnosis lookup과 병합
7. `GraphReviewPath`로 조립

신규 `GraphReviewPath.path_type`:

- `one_disease_review`
- `disease_grouping_review`
- `claim_unit_limit_review`
- `same_disease_surgery_review`
- `recurrent_treatment_review`

status 규칙:

- 질병 간 관계가 질문에만 있으면 `review_required`
- 원문 약관 clause는 확인됐지만 증빙이 없으면 `review_required`
- 동일 질병 여부가 세부내역서/진단서에서 명시되지 않으면 `candidate`
- 약관상 지급 제한 문구가 직접 확인되고 세션 입력이 그 조건을 명확히 충족하면 `confirmed`
- 외부 의학 인과만으로는 절대 `confirmed`를 만들지 않는다.

---

## 6. 보험금 계산 파이프라인 적용

`ClaimCaseContext`에 다음 필드를 추가한다.

- `same_disease_claimed: bool = False`
- `disease_episode_notes: str = ""`
- `treatment_dates: list[str] = field(default_factory=list)`
- `claim_unit_context: str = ""`
- `relation_evidence_tags: list[str] = field(default_factory=list)`

계산 규칙:

1. `same_disease_claimed=True` 자체로 지급액을 줄이거나 늘리지 않는다.
2. 먼저 Graph review path를 호출한다.
3. 하나의 질병 여부가 불명확하면 계산은 `예상`으로 유지하고 `review_required=True`를 붙인다.
4. `confirmed` 지급 제한 path가 있으면 같은 질병수술비 반복 지급 등은 제한 적용 가능하다.
5. 단, 확정 제한 적용은 상품/특약/세대/방문 맥락이 모두 맞을 때만 한다.
6. 청구서류가 부족하면 `RequiredDocument`와 `ReviewAction`을 결과 payload에 노출한다.

Human task 조건:

- 같은 질병인지 사용자가 주장했지만 진단서/세부내역서 근거가 없는 경우
- 합병증/후유증/새로 발견된 질병이 병행된 경우
- 반복 수술 또는 여러 수술이 같은 질병인지 불명확한 경우
- 전환/재개 전후 계속 치료인지 불명확한 경우
- 통원 1회/하루 2회 치료/처방전 묶음 여부가 불명확한 경우

---

## 7. UI/API 표현

API 응답에 추가:

- `disease_episode_assertions`
- `claim_unit_review_paths`
- `disease_grouping_rules`
- `relation_criteria`
- `required_documents`
- `review_actions`

UI 섹션:

- `하나의 질병 검토 경로`
- `질문/청구 입력에서 주장된 사실`
- `약관에서 확인된 판단 기준`
- `증빙 필요`
- `권장 검토 조치`

허용 문구:

- `질문에서 동일 질병 또는 합병증 관계가 주장되어 관련 약관 기준을 검토했습니다.`
- `현재 근거만으로 두 치료가 하나의 질병에 해당한다고 확정하지 않습니다.`
- `진단서, 진료비 세부내역서, 수술확인서에서 동일 질병 또는 치료 목적이 확인되어야 합니다.`

금지 문구:

- `당뇨 때문에 망막병증이 발생했습니다.`
- `이 수술은 당연히 같은 질병 치료입니다.`
- `합병증이므로 자동 보상됩니다.`
- `의학적으로 관련 있으므로 하나의 질병입니다.`

---

## 8. 단계별 구현 계획

### Phase 1. Evidence inventory

목표:

- `하나의 질병`, `동일한 질병`, `하나의 상해`, `같은 치료 목적`, `180일`, `90회` 관련 조항을 manifest로 추출한다.

산출물:

- `reports/graph/one_disease_policy_clause_inventory.csv`
- `reports/graph/one_disease_policy_clause_inventory.md`

검증:

- 현재 inventory 기준 10개 PolicyClause가 누락 없이 포함되어야 한다.
- `표준약관 p.350` 정의 조항은 반드시 포함한다.

### Phase 2. Schema extension

목표:

- 신규 node/edge type을 schema에 추가한다.

수정 대상:

- `src/graph/schema.py`
- 관련 builder/extractor 테스트

추가 node:

- `ClaimUnitConcept`
- `DiseaseGroupingRule`
- `DiseaseRelationCriterion`
- `TreatmentEpisodeContext`

추가 edge:

- `DEFINES_CLAIM_UNIT`
- `HAS_GROUPING_RULE`
- `HAS_RELATION_CRITERION`
- `APPLIES_TO_CLAIM_UNIT`
- `APPLIES_TO_TREATMENT_CONTEXT`
- `LIMITS_BY_CLAIM_UNIT`
- `REQUIRES_GROUPING_REVIEW`
- `REQUIRES_GROUPING_EVIDENCE`

### Phase 3. Extractor

목표:

- raw/processed chunks와 `PolicyClause` excerpt에서 deterministic pattern 기반으로 grouping rule을 만든다.

규칙:

- 새 canonical concept 자동 생성 금지
- 초기 canonical set만 사용
- 문서명, 페이지, clause_id, excerpt를 반드시 evidence로 연결
- 조항 제목이 틀려도 excerpt/page 기반으로 연결 가능해야 한다.

주의:

- 현재 `표준약관 p.350` 조항의 canonical title이 `제43조(예금보험...)`로 보이는 문제가 있다. 이는 clause heading extraction 오류일 가능성이 있으므로, 이번 extractor는 title만 믿지 않고 `doc_short + page + excerpt`를 primary evidence로 사용해야 한다.

### Phase 4. Review path retrieval

목표:

- 하나의 질병 관련 질문에서 `GraphReviewPath`를 생성한다.

테스트 질문:

- `당뇨 진단 후 망막 레이저 수술을 받았는데 합병증 특약 보상이 되나요?`
- `같은 질병으로 두 번 수술하면 질병수술비를 두 번 받을 수 있나요?`
- `하루에 같은 치료 목적으로 두 번 통원하면 통원 횟수는 어떻게 보나요?`
- `전환 전 계약에서 같은 질병으로 90회 통원했으면 재개 후 계약에서 어떻게 보나요?`

### Phase 5. Claim calculation integration

목표:

- 보험금 계산 결과가 `하나의 질병` 여부를 자동 확정하지 않고, review path와 증빙 요구를 함께 노출한다.

적용 위치:

- `src/claim_calculation/models.py`
- `src/claim_calculation/pipeline.py`

### Phase 6. UI/API

목표:

- `하나의 질병 검토 경로`를 사용자에게 이해 가능한 형태로 보여준다.

UI 원칙:

- 확정/후보/검토필요를 명확히 구분
- 의학 인과를 단정하지 않음
- 필요한 서류와 검토 조치를 같이 표시

### Phase 7. Evaluation

신규 평가셋:

- `eval/one_disease_review_paths.jsonl`
- `scripts/eval_one_disease_review_paths.py`

PASS 기준:

- 외부 의학 인과 edge 생성 없음
- `하나의 질병` clause path 포함
- 적용 상품/세대/방문 맥락 포함
- 증빙 부족 시 `review_required`
- 같은 질병 반복 수술 지급 제한 path 생성
- 기존 수술/HIRA/실손 계산 회귀 없음

---

## 9. 자체 검토 및 첨삭

### 검토 1. 외부 의학 지식 도입 위험

위험:

- `당뇨 -> 망막병증` 같은 관계를 graph에 넣으면 문서 밖 판단이 된다.

보완:

- 전역 GraphDB에는 질병 인과 edge를 만들지 않는다.
- 질의/서류에 적힌 관계는 `SessionAssertion`으로만 둔다.
- 답변은 `주장된 사실`과 `문서에서 확인된 약관 기준`을 분리한다.

판정: 결점 없음.

### 검토 2. 상품별 의미 혼합 위험

위험:

- 실손의 `하나의 질병`, 질병수술비의 `동일한 질병`, 후유장해의 `하나의 질병`은 적용 효과가 다르다.

보완:

- `ClaimUnitConcept`과 `DiseaseGroupingRule`을 `PolicyProduct`, `CoverageItem`, `PolicyGeneration`, `VisitContext`와 함께 연결한다.
- review path summary에는 적용 조항과 보장 항목을 반드시 표기한다.

판정: 결점 없음.

### 검토 3. 조항 제목 extraction 오류

위험:

- 현재 표준약관 p.350의 `하나의 질병` 정의 조항이 제목상 `제43조(예금보험...)`로 보인다.

보완:

- extractor는 `canonical_name`만 사용하지 않고 `doc_short + page + excerpt`를 근거로 삼는다.
- Phase 1 inventory에서 heading mismatch를 별도 품질 이슈로 기록한다.

판정: 구현 시 주의점은 있으나 계획 결점은 아님.

### 검토 4. 자동 계산 과단정 위험

위험:

- `same_disease_claimed=True`를 계산에 바로 적용하면 지급액을 잘못 제한할 수 있다.

보완:

- 동일 질병 여부는 기본적으로 review path로만 반영한다.
- 확정 지급 제한은 약관 조항과 세션 증빙이 모두 명확한 경우에만 허용한다.

판정: 결점 없음.

### 검토 5. 기존 GraphRAG 회귀 위험

위험:

- 새 review path가 수술종수/HIRA/비급여 검색에 끼어들어 기존 답변 품질을 떨어뜨릴 수 있다.

보완:

- planner intent를 별도 분리한다.
- 기존 surgery/HIRA path에는 one-disease review를 보조 근거로만 병합한다.
- 회귀 테스트에 기존 수술/HIRA/실손 계산 질문을 포함한다.

판정: 결점 없음.

---

## 10. 최종 적용 판단

이 계획은 현재 프로젝트 원칙과 맞다.

- 원천 문서에서 직접 확인되는 약관 판단 개념만 전역 GraphDB에 올린다.
- 질병 인과나 합병증 원인 같은 외부 의학 지식은 전역 DB에 넣지 않는다.
- 질의/서류에서 주장된 관계는 세션 그래프에만 반영한다.
- 보험금 계산은 `하나의 질병` 여부를 자동 확정하지 않고, review path와 증빙 요구를 통해 실무 검토로 연결한다.

따라서 다음 개발 작업은 Phase 1부터 진행하는 것이 적절하다.

우선순위:

1. `하나의 질병` 조항 inventory 생성
2. schema 확장
3. deterministic extractor
4. review path retriever
5. 보험금 계산 연동
6. UI/API 표기
7. 평가셋 및 회귀 테스트
