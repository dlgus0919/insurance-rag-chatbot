# 156. GraphRAG Next Development Plan

작성일: 2026-05-30
대상 프로젝트: `insurance-rag-chatbot`
기준 경로: `/srv/shared/projects/insurance-rag-chatbot`

## 1. 현재 기준 상태

현재 GraphRAG는 기존 `수술/수가/별표` 중심 그래프에서 보상 실무 판단을 보조하는 review path 그래프로 확장되어 있다.

현재 확인된 주요 적재 현황:

```text
graph_nodes:     545,136
graph_edges:      35,835
graph_evidence:   27,015
graph_aliases:   528,090

PolicyClause:          3,995
CaseExample:           1,138
DiagnosisCode:           695
ComplicationConcept:       6
EvidenceRequirement:       4
ReviewAction:              7
```

현재 `eval/graph_review_paths.jsonl`은 5개 핵심 케이스만 포함하며, `PYTHONPATH=. .venv/bin/python scripts/eval_graph_review_paths.py ...` 기준 5/5 PASS 상태다.

## 2. 개발 원칙

- 전역 GraphDB에는 원문 문서에서 직접 도출 가능한 사실과 판단 개념만 적재한다.
- 질병-합병증-시술 인과는 외부 의학 지식으로 생성하지 않는다.
- 질문이나 청구 입력에 명시된 사실은 세션 assertion으로만 취급한다.
- 불확실한 보상 판단은 확정 답변보다 `추가 확인 필요`, `권장 검토 조치`, `필요 증빙`을 우선 노출한다.
- 일반 질의에서도 질문이 모호하면 바로 답하지 않고 필요한 확인 질문을 생성한다.
- LLM 기반 보정은 보조 수단으로만 사용하고, 최종 판단에는 GraphDB/RAG 근거와 결정론 규칙을 함께 요구한다.

## 3. 우선순위 작업

### P0. 기준선 고정 및 회귀 게이트 정리

목적:

- 현재 GraphDB와 평가 도구가 정상 작동하는 기준선을 명확히 한다.
- 이후 변경이 GraphRAG/계산/일반 RAG를 깨지 않았는지 빠르게 확인할 수 있게 한다.

작업:

- `eval_graph_review_paths` 실행 명령에 `PYTHONPATH=.` 필요성을 문서화한다.
- GraphDB 필수 node/edge count smoke check 명령을 정리한다.
- 평가 결과 산출 경로를 `reports/graph_review_paths/`로 통일한다.

검증:

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_review_paths.py   --graph data/index/graph/insurance_graph.sqlite   --eval eval/graph_review_paths.jsonl   --output reports/graph_review_paths/eval_graph_review_paths_latest.jsonl
```

Self-review:

- 기존 5개 케이스가 계속 통과하는가?
- 평가 명령이 재현 가능한가?

### P1. Graph review path 평가셋 확대

목적:

- 현재 5개 케이스 수준의 smoke 평가를 실무자가 실제로 물어볼 만한 보상 검토 케이스로 확장한다.
- 웹 조사와 raw 문서 탐색을 병행하되, 평가 기대값은 우리 원천 문서와 GraphDB가 확인할 수 있는 범위로 제한한다.

대상 케이스 축:

- 도수치료/체외충격파/증식치료의 횟수·증빙·3대비급여 검토
- MRI/MRA 한도와 세대별 계산 맥락
- 상급병실료 차액
- 건강보험 미적용/비급여 특례
- 미용 목적 및 미용 목적 후 합병증
- 자동차보험/산재보험 등 타 제도 보상과 실손 보상 관계
- 진단서/세부내역서/수술확인서 등 증빙 요구
- 특약 가입 여부 확인
- 상담사례집 기반 유사 사례 검토

산출물:

- `eval/graph_review_paths.jsonl` 케이스 확대
- 필요 시 `scripts/eval_graph_review_paths.py` 채점 항목 보강
- `docs/157_GRAPH_REVIEW_PATH_EVAL_EXPANSION_REPORT.md`

검증:

- 확장 평가셋 전체 PASS 또는 실패 원인 분류
- 기존 5개 케이스 회귀 없음

Self-review:

- 문서 밖 의학 인과를 요구하지 않는가?
- 금지해야 할 확정 문구를 충분히 막는가?
- 실무자가 실제 검토할 만한 질문인가?

### P2. 일반 질의 명확화/되묻기 로직 개선

목적:

- 보험금 계산 기능뿐 아니라 일반 RAG 질의에서도 핵심 조건이 빠지거나 용어가 모호하면 되묻는다.

대상 모호성:

- 세대 불명확: `실손`, `도수치료`, `MRI` 질문인데 4세대/5세대 기준 누락
- 방문 맥락 불명확: 입원/통원 누락
- 보장 맥락 불명확: 실손/특약/자사 건강보험/운전자보험 혼용
- 목적 불명확: 치료 목적/미용 목적/예방 목적 구분 누락
- 증빙 불명확: 영수증/세부내역서/진단서/수술확인서 정보 누락
- 코드·행위명 혼용: 수가코드, 약관 코드, 비급여 표준코드가 섞인 질문

구현 방향:

- `GraphQueryPlanner` 또는 RAG 입력 전처리 단계에서 `clarification_questions`를 생성한다.
- 질문이 너무 일반적이면 답변 전 `확인 질문`을 우선 반환한다.
- 근거 검색은 수행하되, 최종 문구는 `현재 정보만으로는 확정 불가`를 유지한다.

검증:

- 일반 질의 smoke 테스트 추가
- 기존 명확한 질문은 불필요하게 막지 않는지 확인

Self-review:

- 과도한 되묻기로 사용성이 떨어지지 않는가?
- 모호한 질문에 확정 보상 판단을 하지 않는가?

### P3. 혼용 용어 보정 레이어 적용

목적:

- 사용자가 쓰는 일상 표현과 문서/DB의 표준 표현 사이의 간극을 줄인다.
- 단, 임의 지식 확장은 금지한다.

대상 예시:

- `MRI`, `MRA`, `자기공명영상진단`
- `도수치료`, `도수`, `체외충격파`, `증식치료`
- `상급병실`, `상급병실료 차액`
- `비급여`, `건강보험 미적용`, `표준모델`
- `로봇수술`, `로봇 보조 수술`, `다빈치`
- `특약`, `수술특약`, `합병증 특약`

구현 방향:

- 우선 canonical synonym dictionary를 문서 기반으로 구축한다.
- LLM 보정은 후보 생성용으로만 사용하고, 최종 매핑은 dictionary/Graph alias/검색 근거로 검증한다.
- 보정 결과는 API payload에 `normalized_terms` 또는 debug/audit 필드로 남긴다.

검증:

- 혼용 표현 입력 시 동일한 coverage topic/condition/session assertion으로 정규화되는지 확인
- 잘못된 용어 확장을 하지 않는지 forbidden test 추가

Self-review:

- 문서 밖 동의어를 과하게 추가하지 않았는가?
- 수가코드/약관코드/비급여 표준코드가 혼동되지 않는가?

### P4. GraphDB-VectorStore 근거 정합성 진단

목적:

- GraphDB evidence chunk가 현재 BM25/Chroma index에서 실제로 찾아지는지 검증한다.

작업:

- Graph evidence `chunk_id` 샘플을 VectorStore에서 확인하는 진단 스크립트 또는 관리자 탭 확장
- `_v2_manual`, `_v1_original`, `_v1_v2_combined` fallback이 실제로 어느 정도 작동하는지 수치화

검증:

- GraphDB evidence sample hit rate
- 누락 chunk 목록과 문서/페이지 fallback 성공률

Self-review:

- 경고만 숨기지 않고 실제 sync 문제를 드러내는가?

## 4. 단계별 실행 순서

1. P0 기준선 명령과 현재 상태를 재확인한다.
2. P1 평가셋을 먼저 확장한다. 검증이 있어야 이후 로직 변경의 안전성을 판단할 수 있다.
3. P2 일반 질의 명확화 로직을 구현한다.
4. P3 혼용 용어 보정 레이어를 최소 dictionary 기반으로 적용한다.
5. P4 GraphDB-VectorStore 정합성 진단을 관리자/스크립트로 확장한다.

## 5. 완료 기준

1차 완료:

- Graph review path 평가셋이 15개 이상으로 확대된다.
- 확장 평가셋이 실행 가능하고, 실패 시 원인이 명확히 분류된다.
- 일반 질의에서 최소 세대/입원통원/보장상품/증빙 누락에 대한 확인 질문이 생성된다.

2차 완료:

- 혼용 용어 보정이 일반 질의와 보험금 계산 양쪽에서 재사용된다.
- 관리자 진단에서 GraphDB evidence와 VectorStore 정합성을 확인할 수 있다.

최종 목표:

- 보상 담당자가 모호한 질문을 던졌을 때 챗봇이 무리하게 확정하지 않고, 필요한 조건·증빙·검토 경로를 먼저 정리해주는 GraphRAG 기반 실무 보조 시스템으로 동작한다.
