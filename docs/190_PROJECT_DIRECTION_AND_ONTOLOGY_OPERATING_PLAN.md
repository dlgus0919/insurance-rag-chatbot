# 190. Project Direction and Insurance Ontology Operating Plan

## Summary

우리 프로젝트의 장기 목표는 단순한 보험 문서 RAG 챗봇이 아니라, **문서 기반 보험 판단 지식 운영 시스템**을 구축하는 것이다.

핵심 전제는 다음과 같다.

- raw 문서와 코드 로직만으로 완전 자동 보험 ontology를 확정 구축하는 것은 원리적으로 위험하다.
- 대신 raw 문서에서 후보 개념, 조항, rule, 관계를 추출하고, 실무자가 승인한 지식만 active ontology와 GraphDB에 반영하는 운영 구조를 목표로 한다.
- Python 코드에는 보험 개념을 직접 하드코딩하지 않고, 일반화된 schema, extractor, validator, retriever, planner만 둔다.
- 보험 지식은 ontology manifest, rule table, GraphDB, evidence metadata로 관리한다.
- LLM은 판단의 최종 권위가 아니라 질문 해석, 요약, 설명, 답변 표현을 담당한다.

## Target Product Direction

최종 앱은 다음 네 계층이 결합된 보상 업무 보조 시스템이어야 한다.

1. **문서 근거 검색**
   - 약관, 실무가이드, 상담사례집, HIRA, 비급여표준모델 등에서 원문 근거를 찾는다.
   - BM25/Vector/Reranker는 조항 후보와 문맥을 찾는 역할을 한다.

2. **보험 ontology**
   - 조항, 정의, 면책, 보장조건, 한도, 공제, 필요서류, 특약, 세대, 방문 구분, 통지의무, 알릴 의무 같은 보험 판단 단위를 구조화한다.
   - ontology는 개발자가 코드에 박는 개념 목록이 아니라, 실무 승인과 source evidence를 가진 운영 데이터여야 한다.

3. **Graph review path**
   - 질의에서 주장된 사실과 문서에서 확인된 근거를 경로로 보여준다.
   - `confirmed`, `review_required`, `candidate`, `missing` 상태를 명확히 구분한다.
   - 근거가 없을 때도 "없음"을 숨기지 않고 검토 경로로 드러낸다.

4. **RuleRegistry와 deterministic calculation**
   - 보험금 계산, 면책 우선순위, 한도, 공제, 세대별 규칙은 LLM이 생성하지 않고 승인된 rule table과 계산기로 처리한다.
   - LLM은 계산 결과를 설명하되, 계산 rule 자체를 발명하지 않는다.

## Operating Principle

### 1. Code is generic, insurance knowledge is data

코드에 남겨야 할 것은 보험 개념이 아니라 처리 방식이다.

코드에 둘 것:

- 문서 청킹, OCR 후처리
- 후보 개념 추출 schema
- pattern extractor, LLM-assisted extractor, validator
- GraphDB builder
- Graph retriever/planner
- Rule interpreter
- evaluation runner

데이터로 둘 것:

- concept manifest
- alias manifest
- clause/rule extraction 결과
- active/candidate ontology 상태
- rule decision table
- evidence source mapping
- 실무 평가 Q&A

### 2. Raw 문서 추출 결과는 바로 확정 지식이 아니다

raw 문서에서 추출한 후보는 항상 `candidate`로 시작한다.

```text
raw document
→ candidate concept / candidate clause / candidate relation / candidate rule
→ validation
→ human approval
→ active ontology / active rule table
→ GraphDB rebuild
→ evaluation
```

### 3. 문서에 없는 지식은 전역 GraphDB에 넣지 않는다

의학 일반지식, 질병 인과, 임상 상식, 외부 ontology는 프로젝트의 기본 원칙과 맞지 않는다.

허용:

- 문서에 명시된 용어, 조항, 조건, 한도, 증빙, 특약 관계
- 질문/청구 입력에서 명시적으로 주장된 사실을 session graph에 일시 반영

금지:

- `당뇨 -> 망막병증` 같은 외부 의학 인과를 전역 graph에 추가
- 문서 밖 KCD/SNOMED ontology를 자동 도입
- 증빙 없는 치료 목적 추론

## Phase Plan

## Phase 1. Structured Evidence Visibility Stabilization

목표:

- 구조화 단서가 있는 질문에서는 항상 구조화 검토 섹션이 노출되게 한다.
- GraphDB direct edge가 없더라도 `missing` review path를 내려준다.
- 일반 RAG 출처와 Graph review path를 UI에서 명확히 분리한다.

주요 작업:

- `GraphRetriever` fallback review path 강화
- `graph_review_paths`가 비어 있는 원인 진단 로그 추가
- 프론트에서 `missing`, `review_required`, `confirmed` 상태별 표시 개선
- 이전 세션 로딩 시 저장된 `graph_result` 복원 점검

완료 기준:

- 이륜자동차, 합병증, 진단코드, 하나의 질병 관련 질문에서 최소 review path가 표시된다.
- 직접 근거가 없으면 "직접 연결된 구조화 근거 없음"으로 보인다.
- 구조화 단서가 없는 단순 설명형 질문에는 불필요한 graph panel을 만들지 않는다.

## Phase 2. OntologyRegistry v2: 운영 가능한 manifest 계층

목표:

- 현재 `OntologyRegistry`를 단순 수동 JSON에서 운영 가능한 지식 관리 계층으로 확장한다.
- 새 보험 상품이나 약관 개정 시 코드 수정 없이 manifest 갱신으로 반영 가능한 구조를 만든다.

주요 작업:

- concept 상태 필드 추가: `candidate`, `approved`, `deprecated`, `rejected`
- source evidence 필드 추가: `doc_short`, `doc_name`, `page`, `clause_id`, `excerpt`, `chunk_id`
- alias 상태 분리: `candidate_alias`, `approved_alias`, `blocked_alias`
- concept provenance 기록: 자동 추출, 수동 등록, 실무 승인 여부
- `scripts/check_ontology_sync.py`를 운영 점검 스크립트로 확장
- 관리자 진단 탭에 manifest version, concept count, alias count, sync error 노출

완료 기준:

- concept 추가가 Python 코드 수정 없이 manifest 변경만으로 Planner와 retrieval expansion에 반영된다.
- 승인되지 않은 candidate concept는 운영 GraphDB 경로에 확정 근거로 쓰이지 않는다.

## Phase 3. Raw Document Candidate Extraction Pipeline

목표:

- raw 문서에서 보험 판단 지식 후보를 자동 추출한다.
- 추출 결과는 active ontology가 아니라 검토 대상 candidate로 저장한다.

추출 대상:

- 정의 조항
- 보장 개시/지급 조건
- 면책/보상 제외 조건
- 통지의무/알릴 의무
- 특약/부가 약관
- 보험금 한도
- 공제 규칙
- 필요서류
- 세대/방문/의료기관 맥락
- 사례집의 질문/검토 요지/결론 힌트

후보 데이터 타입:

- `CandidateConcept`
- `CandidateClause`
- `CandidateRelation`
- `CandidateRule`
- `CandidateEvidence`
- `CandidateAlias`

완료 기준:

- 신규 PDF 또는 XLSX를 넣으면 후보 개념과 후보 rule이 생성된다.
- 각 후보는 반드시 source excerpt와 page/chunk를 가진다.
- 후보는 승인 전까지 확정 판단 경로에 쓰이지 않는다.

## Phase 4. Human Approval Workflow

목표:

- 실무자가 후보 개념과 후보 rule을 검토하고 승인할 수 있는 운영 흐름을 만든다.
- 개발자가 테스트 질의에 맞춰 개념을 코드에 추가하는 작업을 없앤다.

주요 작업:

- 관리자 페이지에 candidate review 화면 추가
- 후보 concept 승인/반려/병합/분리 기능
- alias 승인/차단 기능
- 같은 개념 중복 후보 감지
- 문서 excerpt와 원문 page 확인 링크 제공
- 승인 이력과 reviewer 기록

실무자에게 요청할 작업:

- 개념 승인 작업
- 실무 수준 테스트용 문답 셋 제작

완료 기준:

- 개발자 개입 없이 실무자가 후보 개념을 active ontology로 승격할 수 있다.
- 승인된 개념만 GraphDB rebuild에 반영된다.

## Phase 5. RuleRegistry and Calculation Knowledge Separation

목표:

- 보험금 계산 지식을 코드에서 분리해 data-driven rule table로 이전한다.
- LLM이 계산식이나 면책 조건을 발명하지 못하게 한다.

대상:

- 실손 세대별 공제율
- 통원/입원 한도
- 3대비급여 한도/횟수
- MRI/MRA 한도
- 표준코드별 보상의견
- 면책 우선순위
- 특약 적용 여부
- 자동차보험/산재/타보험 중복 조정
- 예외/특례 조항

권장 구조:

```text
data/rules/
  deductible_rules.json
  benefit_limits.json
  exclusion_priority.json
  coordination_rules.json
  required_documents.json
```

완료 기준:

- 계산 관련 핵심 보험 지식을 Python 분기 대신 rule table에서 읽는다.
- rule table 변경 후 테스트를 통과하면 코드 수정 없이 계산 기준이 바뀐다.
- rule은 source evidence와 적용 범위를 가진다.

## Phase 6. Practice-Level Evaluation Dataset

목표:

- 실무자가 작성한 문답 셋으로 앱 품질을 측정한다.
- 키워드 매칭이 아니라 의미, 근거, review path, 계산 정확성을 함께 평가한다.

평가 데이터 필드:

- question
- expected_answer_summary
- required_sources
- required_review_paths
- forbidden_claims
- required_clarification_questions
- expected_calculation
- policy_generation
- visit_type
- product_scope
- difficulty
- reviewer_note

평가 축:

- 답변 요지 정확성
- 근거 문서/페이지 정확성
- 구조화 검토 경로 적절성
- 과단정/환각 금지
- 계산 정확성
- 추가 확인 질문 적절성
- 모델별 일관성

완료 기준:

- 신규 ontology/rule 반영 후 평가셋 회귀 테스트를 실행할 수 있다.
- 모델 교체 시 업무 품질 변화를 수치와 사례로 비교할 수 있다.

## Phase 7. GraphDB Rebuild and Release Pipeline

목표:

- 문서, ontology, rule 변경이 운영 앱에 안전하게 반영되는 빌드 파이프라인을 만든다.

권장 흐름:

```text
ingest raw docs
→ build canonical chunks
→ build vector indexes
→ extract candidate ontology/rules
→ approve candidates
→ build active ontology manifest
→ build GraphDB
→ run sync checks
→ run evaluation dataset
→ release
```

운영 스크립트:

- `insurance-rag-build-indexes`
- `insurance-rag-build-graph`
- `insurance-rag-check-ontology`
- `insurance-rag-run-eval`
- `insurance-rag-up`

완료 기준:

- DGX 부팅 후 2개 이하 명령으로 앱을 기동할 수 있다.
- 데이터 갱신 후 재빌드와 평가가 재현 가능하다.
- 실패 시 어느 단계에서 깨졌는지 진단 가능하다.

## Architecture Target

최종 구조는 다음 역할 분리를 지향한다.

```text
Raw Documents
  ↓
OCR / Parser / Chunker
  ↓
Candidate Extractor
  ↓
Human Approval
  ↓
OntologyRegistry + RuleRegistry
  ↓
GraphDB + VectorStore
  ↓
Planner / Retriever / Calculator
  ↓
LLM Explanation Layer
  ↓
UI Review Path + Answer
```

역할 정의:

- **LLM**: 질문 해석, 답변 문장화, 요약
- **RAG**: 원문 근거 검색
- **GraphDB**: 관계형 판단 경로
- **RuleRegistry**: 계산, 한도, 공제, 면책 우선순위
- **실무자**: ontology와 평가셋 품질 승인
- **개발자**: schema, extractor, validator, runtime 안정화

## Development Priority

단기 우선순위:

1. 구조화 근거 섹션 노출 안정화
2. OntologyRegistry v2 schema 설계
3. candidate extraction output schema 정의
4. 관리자 진단 탭에 ontology 상태 노출
5. 이륜자동차 등 개별 질의 기반 임시 개념 추가 중단

중기 우선순위:

1. candidate extraction pipeline
2. human approval workflow
3. RuleRegistry 분리
4. 실무 Q&A 평가 runner
5. GraphDB rebuild pipeline 안정화

장기 우선순위:

1. 상품/약관 개정 대응 자동화
2. 실무자 운영 UI 고도화
3. 모델별 답변 품질 비교
4. 보상 담당자 workflow와 audit log 통합

## Risks and Controls

### Risk 1. 자동 추출 오류

통제:

- 모든 자동 추출 결과는 candidate로 저장
- source excerpt 필수
- human approval 전까지 확정 경로 사용 금지

### Risk 2. ontology 비대화

통제:

- concept 병합/분리 workflow
- alias 승인/차단 상태 관리
- 중복 concept 감지

### Risk 3. 검색 확장 과다

통제:

- expansion term별 scope와 weight 관리
- 평가셋 기반 recall/precision 모니터링
- 관리자 진단 탭에서 query expansion trace 표시

### Risk 4. 계산 rule drift

통제:

- rule table source evidence 필수
- 세대/상품/방문 범위 필수
- 계산 회귀 테스트 필수

## Conclusion

이 프로젝트의 올바른 방향은 "문서 내용을 모두 자동 이해하는 LLM 챗봇"이 아니다.

목표는 **문서에서 후보 지식을 추출하고, 실무자가 승인하며, 승인된 ontology와 rule을 기반으로 근거 경로와 계산 결과를 제공하는 보험 지식 운영 시스템**이다.

따라서 향후 개발은 다음 원칙을 따라야 한다.

- 보험 개념은 코드가 아니라 데이터로 관리한다.
- raw 문서 추출 결과는 곧바로 확정 지식이 아니다.
- 실무자 승인과 평가셋이 품질의 기준이다.
- GraphDB는 답변 장식이 아니라 판단 경로의 운영 데이터다.
- LLM은 판단을 발명하지 않고, 승인된 근거와 rule을 설명한다.
