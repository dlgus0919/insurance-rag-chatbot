# 114. GraphDB RAG 런타임 품질 보강 구현 보고서

## 1. 개요
본 문서는 `docs/113_GRAPHDB_RAG_RUNTIME_REVIEW_AND_HARDENING_SPEC.md`에 명시된 GraphDB RAG 런타임 품질 보강 및 보험금 계산 파이프라인 안전장치 구현 결과를 정리한 보고서이다.

기존 GraphDB RAG 연동은 빌드 및 기본적인 검색 패스는 성공했으나, 실제 비즈니스 관점의 세밀한 런타임 품질 통제(과잉 별표 조항 추출, 근거(evidence) 누락된 Confirmed 승격, 동일 등급 추천 무작위성 등)가 부족했다. 이를 해결하기 위해 정밀 파싱, SQL 가중치 정렬, context 필터링 및 계산 파이프라인 예외 처리 안전장치를 설계 사양에 맞춰 모두 반영하였다.

---

## 2. 변경 파일 목록

- `src/config.py`: GraphDB Context 최대 글자 수 제약 (`GRAPH_CONTEXT_MAX_CHARS=5000`) 설정 추가.
- `src/graph/query_planner.py`: 별표 세부 조항 번호를 추출하기 위한 `appendix_numbers` 필드 및 고정 너비 정규식 조항 파싱 로직 추가.
- `src/graph/retriever.py`:
  - 동일 등급 peer 질의 시 SQL 레벨에서 대분류 일치 여부 및 canonical_name 기준의 명시적 가중치 정렬(`ORDER BY`) 적용.
  - 별표 항목 번호 부재 시 별표 전체 반환을 방지하고 `POLICY_COVERS_PROCEDURE` 후보만 반환하도록 제한.
  - `DEFINED_IN_APPENDIX` 등 confirmed fact에 대해 evidence를 역조회하여 연결하고, evidence가 없는 confirmed fact는 candidate로 일괄 하향(강하)하는 후처리 로직 적용.
- `src/graph/context.py`: 질문 의도별 fact 필터링, 표 압축 포맷 지원, `GRAPH_CONTEXT_MAX_CHARS` 글자 수 한계 기반의 본문 절단 적용.
- `src/claim_calculation/pipeline.py`: evidence가 없는 confirmed 사실의 계산 근거 배제 및 candidate PAYS_BY_RATIO 단독 존재 시 `review_required=True` 강제 및 확정 지급 안내 배제 로직 추가.
- `eval/graph_qa.jsonl`: Q1 평가 케이스에 `forbidden_facts`, `max_facts_by_relation`, `requires_evidence_for_status` 검증 조건 추가.
- `scripts/eval_graph_qa.py`: 새로운 검증 조건(`forbidden_facts`, `max_facts_by_relation`, `requires_evidence_for_status`) 파싱 및 평가 로직 반영.
- `tests/test_graph_retriever.py`: retriever 변경(evidence 기반 confirmed 하향 로직)에 맞춘 DB 피스처 mocking 보강 및 `test_retriever_hard_query_2` 등 테스트 안정화.
- `tests/test_claim_calculation_pipeline.py`: confirmed evidence 누락 시 배제 검증 및 candidate 단독 검토 강제 처리를 확인하는 유닛 테스트 추가.

---

## 3. 결함 A~E 조치 내역

### 결함 A: 별표 항목 번호 파싱이 너무 넓음
- **원인**: 단순히 질문 내의 모든 숫자를 별표 조항 번호로 오인하여 불필요한 별표 fact들이 검색에 노입되는 현상.
- **해결**: `src/graph/query_planner.py` 내에 `appendix_numbers` 필드를 추가하고, `(?<!별표\s)(?<!별표)(\d{1,3})\s*(?:번\s*)?(?:항목|조항|항)\b|(\d{1,3})\s*번\b`와 같이 고정 너비 look-behind를 조합한 정규식으로 명시적인 항목 번호만 추출하도록 개선하였다.
- **결과**: `신1-5종`의 '1', '5'나 `3가지`의 '3'이 별표 번호로 추출되지 않아 과잉 검색이 방지됨.

### 결함 B: 평가셋의 과잉 검색 검증 누락
- **원인**: 기존 RAG 자동 평가가 단순히 기대하는 fact 존재 여부(recall)만 검증하여 관련 없는 과잉 fact를 걸러내지 못함.
- **해결**: `scripts/eval_graph_qa.py`를 수정하여 `forbidden_facts` (나타나면 안 되는 사실), `max_facts_by_relation` (관계당 최대 개수 초과 시 실패), `requires_evidence_for_status` (특정 등급에 대한 evidence 필수 검증)를 수행하도록 했다.
- **결과**: Q1 케이스에 별표7의 1번, 3번이 노출될 시 자동으로 오검색 실패 처리되도록 통제 강화.

### 결함 C: `DEFINED_IN_APPENDIX` confirmed fact에 evidence가 부재함
- **원인**: 별표 직접 조회 사실은 `confirmed`로 표시되지만 증빙용 evidence가 누락되어 RAG 신뢰성을 저해함.
- **해결**: `DEFINED_IN_APPENDIX` 에지를 조회할 때 에지에 매핑된 `source_evidence_id` 및 노드 증빙 데이터를 역조회하여 evidence를 할당하고, 최종 결과 반환 직전 evidence가 없는 모든 `confirmed` 사실은 `candidate` 등급으로 일괄 강하(하향) 처리하도록 후처리 로직을 추가했다.

### 결함 D: 동일 등급 peer 추천 기준 무작위성
- **원인**: 동일 수술 등급 조회 시 SQL `LIMIT`에 의존하여 대분류 연관성 여부와 상관없이 무작위로 수술명이 노출됨.
- **해결**: `src/graph/retriever.py`에서 peer 조회 쿼리 실행 시 `ORDER BY` 절에 가중치를 설정했다.
  - 대상 수술과 대분류(`category_large`)가 일치하는 경우 우선순위 가중치 1위
  - 대상 수술의 SOL 대분류와 매칭되는 조항일 경우 가중치 2위
  - evidence 존재 여부와 canonical_name 오름차순 정렬을 결합하여 고유하고 일관적인 peer 우선순위가 유지되도록 보장함.

### 결함 E: Graph context가 답변 프롬프트를 과도하게 오염시킬 위험
- **원인**: 모든 structure fact가 줄글 형태로 프롬프트에 들어가면서 프롬프트 토큰이 지나치게 길어지거나 LLM의 본래 질문 집중도를 떨어뜨림.
- **해결**:
  - 질문 의도별로 context fact 목록을 엄격히 제한.
  - 카테고리/등급 조회 결과는 마크다운 표 포맷으로 압축하여 토큰 소모를 줄임.
  - `GRAPH_CONTEXT_MAX_CHARS` (기본값 5000)를 초과할 경우 안전하게 절단하여 LLM 생성 오류 예방.

---

## 4. 검증 결과

### 4.1 자동 평가 결과
원격 DGX 환경(`ai-hang@100.88.5.57`)에서 `scripts/eval_graph_qa.py`를 실행하여 5개 강화 시나리오 모두를 통과시켰다.
```bash
Loading GraphRetriever with DB: data/index/graph/insurance_graph.sqlite
Loaded 5 evaluation test cases from eval/graph_qa.jsonl

[1/5] Evaluating case: graph_001_bronchial_esophageal_fistula_grade_peers
  Query: "기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. 그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘."
  PASS

[2/5] Evaluating case: graph_002_digestive_grade5_with_codes_and_payment_ratio
  Query: "신1-5종 수술분류표에서 5종(가장 중한 등급)에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘. 각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘."
  PASS

[3/5] Evaluating case: graph_003_robot_code_doc_split
  Query: "로봇 수술의 수가코드와 분류 지침을 알려주세요."
  PASS

[4/5] Evaluating case: graph_004_sol_appendix_18_19_split
  Query: "SOL 건강보험 별표7의 18번 항목과 19번 항목의 차이점과 각각 해당하는 수술종류를 알려주세요."
  PASS

[5/5] Evaluating case: graph_005_missing_fee_code_must_not_hallucinate
  Query: "존재하지않는가상의수술의 수가코드를 조회해줘."
  PASS

============================================================
Evaluation Summary: 5/5 cases passed.
============================================================
```

### 4.2 전체 pytest 유닛 테스트 결과
전체 328개 유닛 테스트가 경고 3건 외에 에러 없이 완벽히 패스함을 검증 완료하였다.
```bash
$ PYTHONPATH=. .venv/bin/pytest -q
........................................................................ [ 21%]
........................................................................ [ 43%]
........................................................................ [ 65%]
........................................................................ [ 87%]
........................................                                 [100%]
328 passed, 3 warnings in 3.53s
```

### 4.3 Streamlit 8501 수동 QA 시나리오 검증 결과 (RAG Context 수준 검증)
원격 환경에서 실제 RAG Context 생성 동작을 모킹 및 직접 실행하여 질의별 기대 동작을 수동 검증하였다.

1. **질문 1 (기관지 식도루 폐쇄술의 신1-5종 수술 및 동일 대분류)**:
   - *검증 결과*: `기관지 식도루 폐쇄술`은 `[CONFIRMED]` 신1-5종 4종으로 정상 출력.
   - *검증 결과*: 동일 등급 peer 수술로 `개흉적 기관 또는 기관지 이물제거술` 등 3가지가 정렬되어 `[CANDIDATE]`로 정상 노출.
   - *검증 결과*: 별표7의 1번, 3번 등 불필요한 별표 조항의 `[CONFIRMED]` facts는 완전 노출 배제됨 (Clean).
2. **질문 2 (별표7의 18번과 19번 차이점)**:
   - *검증 결과*: 명시적 조항 번호 18, 19가 Planner에 의해 파싱되어, 해당 조항들만 `[CONFIRMED]`로 정상 노출되며 `[근거: 자사_SOL건강 p.384]` 증빙이 정상적으로 추적 연결됨.
3. **질문 3 (5종 수술 소화기계 카테고리 나열, 수가코드, 지급 비율)**:
   - *검증 결과*: `간장 이식수술`, `췌장 이식수술`이 마크다운 압축 표 형태로 정상 출력됨.
   - *검증 결과*: 수가코드가 없는 것에 대해 임의 생성(환각) 없이 `[MISSING] (No MedicalFeeCode mapping found in GraphDB)`로 명확하게 표시됨.
   - *검증 결과*: 지급 비율은 `[CANDIDATE] 100%`로 명확하게 분류 표시됨.
4. **질문 4 (가상 수술 수가코드 조회)**:
   - *검증 결과*: 환각 없이 `[MISSING] 존재하지않는가상의수술 --(EXISTS)--> [누락/확인불가] (사유: Procedure node not found in graph database.)`로 안전하게 표시됨.

---

## 5. 리스크 및 향후 관리 계획
- 현재 8501 포트에서 Streamlit 오프라인 테스트용 데모 서버가 정상 구동 중이다.
- RAG 안전장치 및 계산 파이프라인 예외 처리가 모두 적용되었으므로, 차후 실서비스 반영 시 계산 로직의 `review_required=True` 플래그 및 Notes 표기 조건에 맞추어 프론트엔드 UI 가이드를 보강할 필요가 있다.
