# 145. GraphDB Ontology Improvement Stage Plan

작성일: 2026-05-28
대상 프로젝트: `insurance-rag-chatbot`
기준 문서: `docs/144_CLAIMS_HANDLER_GRAPHRAG_ONTOLOGY_IMPROVEMENT_REPORT.md`

## 1. 목표

보험회사 보상 업무 담당자가 실제로 사용할 수 있는 GraphRAG로 발전시키기 위해, 현재 구축된 판단 개념 노드와 review path를 단계적으로 고도화한다.

핵심 목표는 다음과 같다.

- 그래프가 문서 근거를 과잉 확정하지 않도록 한다.
- 약관 ontology를 보상 실무 규칙 단위로 분해한다.
- 보험금 계산, 서류 검토, 사람 심사 이관이 같은 판단 경로를 공유하게 한다.
- 각 단계는 `계획 -> 구현 -> 검토 -> 평가 -> 피드백` 루프를 따른다.

## 2. 단계별 추진 범위

### Stage 1. Review Path Precision and Safety

목적:

- `합병증`, `미용 목적`, `특약`, `실손` 등 판단 개념이 포함된 질의에서 관련 조항을 무차별적으로 확정하지 않는다.
- 입력 조건과 직접 맞는 조항만 `confirmed`로 승격하고, 나머지는 `candidate` 또는 `review_required`로 유지한다.
- UI와 프롬프트에 노출되는 review path 수를 제한해 실무자가 우선 검토할 근거를 먼저 보게 한다.

계획:

- planner의 합병증 신호 추출을 정밀화한다.
- retriever에 review path scoring/ranking을 추가한다.
- 조건 불일치 조항의 면책 판단을 확정으로 표시하지 않는다.

구현:

- `src/graph/query_planner.py`
- `src/graph/retriever.py`
- 관련 회귀 테스트

검토:

- `염증` 단독 질의가 합병증 review path를 만들지 않는지 확인한다.
- `합병증 특약` 질의에서 `실손` 면책 조항이 확정 면책으로 승격되지 않는지 확인한다.
- `미용 목적 수술 후 합병증`처럼 입력 조건이 직접 맞는 경우에는 확정 면책 경로가 유지되는지 확인한다.

평가:

- `tests/test_graph_review_path_planner.py`
- `tests/test_graph_review_path_retriever.py`

피드백 기준:

- 과잉 확정이 남아 있으면 scoring/gating 규칙을 강화한다.
- 필요한 조항이 누락되면 `source_priority`, topic, condition 가중치를 조정한다.

### Stage 2. Policy Rule Ontology Layer

목적:

- `PolicyClause`를 그대로 보여주는 수준에서 벗어나 보상 실무 규칙 단위로 정리한다.
- 약관의 판단 구조를 다음 rule type으로 분해한다.

권장 rule type:

- `CoverageTriggerRule`
- `ExclusionRule`
- `LimitRule`
- `DeductibleRule`
- `EvidenceGateRule`
- `PrecedenceRule`

계획:

- 기존 `PolicyClause.properties.clause_type`을 rule layer로 매핑한다.
- 새 SQLite node type을 무리하게 늘리기보다 v1에서는 `PolicyClause` properties와 `HAS_DECISION`, `APPLIES_WHEN`, `REQUIRES_EVIDENCE` edge를 활용한다.
- 확장 필요성이 검증되면 이후 별도 node type으로 승격한다.

구현:

- extractor의 `clause_type`, `decision_polarity`, `generation_scope`, `source_priority` 분류 개선
- rule summary 생성 helper 추가
- rule invariant test 추가

진행 메모:

- 2026-05-28 현재 v1 구현은 새 node type을 추가하지 않고 `PolicyClause.properties.rule_types`와 `PolicyClause.properties.rule_summary`를 추가하는 방식으로 적용했다.
- 이 방식은 기존 SQLite schema와 rebuild 파이프라인을 깨지 않으면서 `CoverageTriggerRule`, `ExclusionRule`, `LimitRule`, `DeductibleRule`, `EvidenceGateRule`, `PrecedenceRule` 성격을 보존한다.
- 향후 rule별 독립 검색/편집 UI가 필요해지면 별도 node type 승격을 검토한다.

검토:

- 하나의 조항이 coverage/exclusion/limit/deductible 중 어느 성격인지 과잉 중복 분류되지 않는지 확인한다.
- 원문 근거 없이 rule을 생성하지 않는지 확인한다.

평가:

- 약관 조항 샘플 기반 invariant test
- GraphDB rebuild 후 node/edge count diff와 샘플 질의 검증

피드백 기준:

- rule 중복률이 높으면 extractor 키워드를 strict matching으로 강화한다.
- 원문 근거가 약한 rule은 `candidate`로만 노출한다.

### Stage 3. Evidence Completeness and Human Task Routing

목적:

- 보상 담당자가 최종 판단 전에 어떤 서류와 확인 작업이 부족한지 바로 알 수 있게 한다.
- `review_actions`를 단순 표시가 아니라 실제 검토 queue의 입력 형태로 정리한다.

계획:

- `required_evidence`와 `context.evidence_tags`를 비교해 missing evidence를 구조화한다.
- review action을 중복 제거하고 우선순위를 둔다.
- 보험금 계산 결과에 `자동 계산 가능`, `예상 계산`, `사람 심사 필요`, `자동 계산 보류` 상태를 명확히 부여한다.

구현:

- `src/claim_calculation/pipeline.py`
- `src/graph/retriever.py`
- API payload와 UI rendering

진행 메모:

- 2026-05-28 현재 계산 결과에 `calculation_status`, `missing_evidence`, `review_actions`를 추가했다.
- `required_evidence`와 입력된 `evidence_tags`는 완전 일치뿐 아니라 포함 관계도 인정한다. 예를 들어 `진료비 세부내역서`는 `세부내역서` 요구를 충족할 수 있다.
- confirmed exclusion review path는 `notes`가 `exclusion; 입력 조건 직접 일치`처럼 확장되어도 면책 우선 로직이 작동하도록 보강했다.

검토:

- 증빙이 부족한데 확정 지급 문구가 나오지 않는지 확인한다.
- 사람 심사 필요 조건이 중복/과잉으로 표시되지 않는지 확인한다.

평가:

- 합병증 주장, 표준코드 모호성, 세대/통원/입원 누락, 특약 가입 여부 확인 케이스

피드백 기준:

- 자동 계산 가능 케이스까지 모두 보류되면 routing 조건을 완화한다.
- 사람 심사 필요 케이스가 자동 지급으로 노출되면 보류 조건을 강화한다.

### Stage 4. Claims Handler UI and Audit View

목적:

- 실무자가 답변만 보는 것이 아니라 판단 경로, 서류 부족, 검토 조치를 한 화면에서 추적하게 한다.

계획:

- `구조화 검토 경로` 섹션을 더 짧고 업무형으로 정리한다.
- `질문/입력에서 주장된 사실`, `문서 근거`, `추가 확인 필요`, `권장 검토 조치`를 분리한다.
- 저장되는 대화 요약에 review path summary를 남겨 사후 감사가 가능하게 한다.

구현:

- `src/api/rag_service.py`
- `src/ui/streamlit_app.py`
- 웹 UI 사용 시 해당하는 프론트엔드 파일

진행 메모:

- 2026-05-28 현재 API payload에 `path_type_label`, `status_label`을 추가했다.
- Streamlit의 구조화 검토 경로 표시는 내부 enum 대신 `합병증/후유증 검토 · 검토 필요` 같은 업무형 라벨을 우선 표시한다.
- 기존 저장 요약은 유지하되, summary/status 중심으로 감사 추적에 필요한 최소 정보를 계속 보존한다.

검토:

- candidate와 confirmed가 시각적으로 구분되는지 확인한다.
- 긴 표/HTML이 그대로 노출되지 않는지 확인한다.

평가:

- 실제 UI에서 보상 담당자 시나리오 5개 이상 수동 확인

피드백 기준:

- 담당자가 바로 다음 조치를 알 수 없으면 문구와 grouping을 조정한다.

### Stage 5. Evaluation and Rebuild Gate

목적:

- GraphDB rebuild와 코드 변경이 실제 GraphDB 품질을 개선했는지 자동으로 확인한다.

계획:

- `eval/graph_review_paths.jsonl`을 확대한다.
- `scripts/eval_graph_review_paths.py`가 review path status, forbidden causality, evidence requirement, review action을 함께 채점하게 한다.
- GraphDB rebuild 후 필수 node/edge count와 샘플 path를 검증한다.

구현:

- 평가셋 보강
- 평가 스크립트 보강
- rebuild verification command 정리

진행 메모:

- 2026-05-28 현재 `eval/graph_review_paths.jsonl`과 `scripts/eval_graph_review_paths.py`를 추가했다.
- 첫 DGX rebuild 검토에서 `PolicyReviewExtractor`가 build 파이프라인에 반영되지 않은 결점이 발견되어 `src/graph/build.py` 동기화 후 rebuild를 반복했다.
- 재실행 결과 `PolicyClause 3,995`, `rule_types 3,995`, `ReviewAction 7`을 SQLite에서 확인했다.
- `scripts/eval_graph_review_paths.py` 기준 5/5 PASS를 확인했다.

검토:

- 키워드만 맞춰도 PASS되는 허술한 평가가 아닌지 확인한다.
- 문서 밖 의학 인과가 생성되면 즉시 FAIL 처리한다.

평가:

- GraphDB rebuild
- targeted pytest
- review path evaluator

피드백 기준:

- false fail은 숫자/표현 정규화를 추가한다.
- false pass는 forbidden edge/phrase 검사를 강화한다.

## 3. 완료 기준

전체 목표는 다음 조건을 만족할 때 완료로 본다.

- Stage 1-5의 구현/검토/평가 루프가 모두 완료된다.
- 발견된 결점이 남아 있으면 해당 단계로 되돌아가 재수정한다.
- GraphDB rebuild 검증이 통과한다.
- 관련 문서와 테스트가 저장소에 반영된다.
- 최종 상태를 GitHub에 push한다.
