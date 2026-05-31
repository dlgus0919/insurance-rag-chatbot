# 157. Graph Review Path Evaluation Expansion Report

작성일: 2026-05-30
대상 단계: `156_GRAPHRAG_NEXT_DEVELOPMENT_PLAN.md`의 P1-P3 1차 적용
작업 경로: `/srv/shared/projects/insurance-rag-chatbot`

## 1. 작업 목적

GraphRAG의 review path가 실제 보상 담당자 질의에서 안전하게 작동하는지 확인하기 위해 평가셋을 5개에서 18개로 확장했다.

이번 확장은 단순 케이스 추가가 아니라 다음 세 가지를 함께 적용했다.

- 실무형 보상 검토 질문 확대
- 일반 질의에서도 모호한 조건을 확인 질문으로 되묻는 planner 보강
- 혼용 용어를 문서 기반 canonical topic/condition으로 정규화하는 1차 레이어 추가

## 2. 조사 기준

### 2.1 웹 조사

웹 조사는 평가 케이스의 쟁점 축을 찾는 용도로만 사용했다. 외부 자료의 내용을 전역 GraphDB 지식으로 넣지는 않았다.

참고한 공개 자료:

- 손해보험협회 실손의료보험 안내: 비급여, 상급병실료 차액, MRI/MRA 같은 실손 주요 용어와 중복계약 비례분담 개념 확인
  - https://kpub.knia.or.kr/productDisc/lostHealth/lostHealthInfo.do
- 손해보험협회 소비자 상담사례 자료: 4세대 전환, 3대비급여, 통원/처방조제 등 상담 쟁점 확인
  - https://www.knia.or.kr/file-manager/104989
  - https://www.knia.or.kr/file-manager/104953
- 보험연구원 실손의료보험 제도개선 공청회 자료: 도수치료, 체외충격파, 증식치료, 주사료, MRI/MRA가 실손 비급여 특약 쟁점임을 확인
  - https://www.kiri.or.kr/pdf/%EC%84%B8%EB%AF%B8%EB%82%98%EC%9E%90%EB%A3%8C/semina20201027_2.pdf

### 2.2 Raw 문서 탐색

DGX raw chunk에서 다음 쟁점을 확인했다.

- 실손 약관: 3대비급여, 도수치료/체외충격파/증식치료, MRI/MRA, 상급병실료 차액, 통원/입원, 청구서류
- 자사 SOL 건강보험 약관: 보험금 청구서류, 진단서, 수술확인서, 진료비 영수증, 진료비 세부내역서
- 심평원 고시 chunk: MRI/MRA 수가표와 의료기관/검사 관련 행
- 상담사례집/약관: 타 보험 보상, 단순 건강검진, 특약 가입 여부 등 실무 검토 축

대표 raw 근거:

- `약관_ch_002309`, `약관_ch_002310`: 3대비급여, 도수치료, MRI/MRA, 상급병실료 차액 등 실손 약관 쟁점
- `약관_ch_002317`: 보험금 청구 절차와 서류
- `자사_SOL건강_ch_002744`, `자사_SOL건강_ch_002746`: 진단서, 수술확인서, 진료비 영수증, 진료비 세부내역서
- `심평원_ch_000520` 이후 MRI/MRA 관련 수가표 chunk

## 3. 변경 파일

- `docs/156_GRAPHRAG_NEXT_DEVELOPMENT_PLAN.md`
- `docs/157_GRAPH_REVIEW_PATH_EVAL_EXPANSION_REPORT.md`
- `eval/graph_review_paths.jsonl`
- `scripts/eval_graph_review_paths.py`
- `src/graph/query_planner.py`
- `src/graph/context.py`
- `src/api/rag_service.py`
- `tests/test_graph_review_path_planner.py`
- `tests/test_api_rag_service_payload.py`

## 4. 평가셋 확대 내용

기존 5개 케이스:

- 미용 목적 수술 후 합병증
- 당뇨/망막 레이저/합병증 특약 질의의 인과 추론 금지
- `N39.3` 진단코드 약관 검토
- 상급병실료 차액 검토
- 도수치료 5세대 실손 통원 합병증 치료 claim review

신규 추가 케이스:

- 도수치료/체외충격파치료 최초 10회 이후 증빙 검토
- MRI/MRA 한도와 서류 확인
- 건강검진 중 이상 소견 없이 받은 MRI의 치료 목적 확인
- 자동차보험으로 이미 보상받은 치료비와 실손 중복 청구 검토
- 산재보험 처리 치료비와 실손 추가 청구 검토
- 미용 목적 쌍꺼풀 수술 보상 여부
- 치료 목적 유방재건술/미용 목적 성형 혼용 검토
- 상급종합병원 통원 5세대 실손 계산 시 증빙 확인
- 특약 가입 여부 불명확한 로봇수술 보상 질의
- 세부내역서 없이 영수증만 있는 도수치료 자동 계산 여부
- 망막 레이저 수술을 당뇨 합병증이라고 주장하는 케이스의 인과 추론 금지
- 비급여 주사료가 영양제인지 치료 목적 주사인지 불명확한 케이스
- 약국 처방조제 비용의 통원 실손 방문 구분 확인

최종 평가셋 규모:

```text
18 cases
```

## 5. 평가 스크립트 보강

`scripts/eval_graph_review_paths.py`에 다음 채점 항목을 추가했다.

- `required_plan_topics`
- `required_plan_conditions`
- `required_ambiguous_terms`
- `required_clarification_any`
- `required_normalized_terms`

이를 통해 Graph review path뿐 아니라 planner가 질문을 어떻게 이해했는지도 함께 검증한다.

## 6. Planner / 명확화 로직 보강

`src/graph/query_planner.py`에 다음 필드를 추가했다.

- `normalized_terms`
- `ambiguous_terms`
- `clarification_questions`

추가 정규화 예시:

| 사용자 표현 | canonical |
| --- | --- |
| `실비`, `실손보험`, `실손의료보험` | `실손` |
| `도수` | `도수치료` |
| `체외충격파` | `체외충격파치료` |
| `영양제`, `영양주사`, `주사료` | `비급여 주사료` |
| `자기공명영상`, `MRI`, `MRA` | `자기공명영상진단` 또는 개별 MRI/MRA topic |
| `상급병실`, `병실료 차액` | `상급병실료 차액` |
| `교통사고`, `차 사고` | `자동차보험` |
| `산재`, `산업재해` | `산재보험` |
| `세부내역서 없이`, `영수증만` | `증빙 부족` |

명확화 질문 예시:

- 어느 실손 세대(예: 4세대/5세대) 기준인지 확인해 주세요.
- 입원/통원/처방조제 중 어떤 방문 구분인지 확인해 주세요.
- 어떤 상품 또는 특약 가입 여부를 기준으로 볼지 확인해 주세요.
- 치료 목적인지 미용/예방 목적인지 확인할 수 있는 진단서 또는 의사소견이 있는지 확인해 주세요.
- 진료비 영수증, 진료비 세부내역서, 진단서 등 어떤 증빙이 있는지 확인해 주세요.

## 7. API / prompt context 반영

`src/api/rag_service.py`는 Graph payload에 다음 값을 포함한다.

- `plan.normalized_terms`
- `plan.ambiguous_terms`
- `plan.clarification_questions`

또한 명확화 질문이 있으면 warning code `CLARIFICATION_RECOMMENDED`를 추가한다.

`src/graph/context.py`는 구조화 fact가 없더라도 명확화 질문이나 정규화 후보가 있으면 prompt context에 포함한다. 따라서 일반 RAG 답변에서도 질문에 빠진 조건을 먼저 확인하도록 유도한다.

## 8. 검증 결과

### 8.1 Graph review path 확장 평가

명령:

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_review_paths.py   --graph data/index/graph/insurance_graph.sqlite   --eval eval/graph_review_paths.jsonl   --output reports/graph_review_paths/eval_graph_review_paths_expanded_20260530.jsonl
```

결과:

```text
Graph review path evaluation: 18/18 passed
```

### 8.2 관련 단위 테스트

명령:

```bash
PYTHONPATH=. .venv/bin/pytest   tests/test_graph_review_path_planner.py   tests/test_eval_graph_review_paths.py   tests/test_api_rag_service_payload.py -q
```

결과:

```text
10 passed in 0.30s
```

## 9. Self-review

점검 결과:

- 평가셋은 외부 의학 인과를 기대하지 않는다.
- `당뇨 -> 망막병증` 같은 문서 밖 인과 생성은 계속 forbidden text로 막는다.
- 모호한 실손 세대, 방문 구분, 증빙, 특약 가입 여부를 확인 질문으로 노출한다.
- 기존 5개 Graph review path 케이스는 회귀 없이 통과했다.
- 변경은 planner/evaluator/API payload/context/test 범위로 제한했다.

남은 위험:

- 명확화 질문은 아직 rule 기반이다. LLM을 이용한 사용자 입력 보정은 후보 생성 단계로만 제한해 별도 안전장치가 필요하다.
- 평가셋은 18개로 확대됐지만, 전체 상담사례집/약관 조합을 대표하기에는 아직 부족하다.
- GraphDB-VectorStore chunk 정합성 진단은 이번 단계에서 직접 구현하지 않았다. 다음 P4 작업으로 분리하는 것이 맞다.

## 10. 다음 작업 제안

1. 일반 RAG 답변에서 `CLARIFICATION_RECOMMENDED`가 있을 때 UI가 확인 질문을 별도 블록으로 보여주도록 개선한다.
2. `normalized_terms`를 관리자 검색 진단 탭에도 표시해 사용자가 어떤 용어로 정규화됐는지 볼 수 있게 한다.
3. `GraphDB evidence -> VectorStore chunk` 정합성 진단을 스크립트와 관리자 탭에 추가한다.
4. 상담사례집 기반 case path 평가셋을 별도 `eval/graph_case_examples.jsonl`로 분리한다.
