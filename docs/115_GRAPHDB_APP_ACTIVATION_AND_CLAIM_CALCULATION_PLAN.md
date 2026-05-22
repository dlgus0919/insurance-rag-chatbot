# 115. GraphDB 앱 적용 및 보험금 계산 연동 다음 작업 계획

## 1. 목표

GraphDB를 단순 실험 산출물이 아니라 Streamlit 앱의 실제 답변 로직과 보험금 지급예상액 계산 로직에 정상 적용한다.

최종 목표는 다음 세 가지다.

1. 복잡한 수술분류/수가코드/약관 비교 질의에 대해 GraphRAG가 구조화 사실을 우선 사용한다.
2. 보험금 보상 질의에서는 적용 약관, 비급여 표준모델, 수술분류, 지급비율 후보를 분리 확인하고, LLM이 계산용 Python 코드를 작성한 뒤 샌드박스 실행 결과로 정량 금액을 제시한다.
3. GraphDB는 OCR 데이터셋 중 보정본(`v2_manual`)을 우선 근거로 사용하고, 필요한 경우에만 원본 OCR(`v1`)을 보조 근거로 연결한다.

작업 기준 디렉터리는 DGX Spark의 `/srv/shared/projects/insurance-rag-chatbot`이다.

## 2. 현재 상태 요약

### 2.1 확인된 정상 상태

DGX에서 다음 검증은 통과한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot

PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl
# 5/5 cases passed

PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
# Detailed Integrity Check: PASS

.venv/bin/pytest -q
# 328 passed, 3 warnings
```

### 2.2 현재 결점

1. `GRAPH_ENABLED`가 런타임 환경에 설정되어 있지 않다.
   - 실행 중인 8501 Streamlit 프로세스 환경에는 `GRAPH_ENABLED`가 없다.
   - `src/config.py` 기본값은 `false`이므로, 현재 앱에서 GraphDB가 실제 답변에 반영되지 않을 수 있다.

2. Planner가 카테고리 질의에서 가짜 procedure를 추출한다.
   - 예: `신1-5종 수술분류표에서 5종에 해당하는 수술...`
   - 현재 `procedure_name='에 해당하는 수술'`로 잘못 잡히며, Graph context 표에 `에 해당하는 수술 | N/A | N/A | N/A` 행이 들어간다.

3. Graph fact 중복이 남아 있다.
   - 소화기계 5종 질의에서 `PAYS_BY_RATIO`가 수술별 3개씩 반환된다.
   - context에서는 압축되어 보이지만 내부 fact와 관리자 진단 UI에서는 혼란을 만들 수 있다.

4. staged 파일에 trailing whitespace가 많다.
   - `git diff --cached --check`가 실패한다.
   - 커밋 전 반드시 정리해야 한다.

5. GraphDB 관련 필수 문서와 스크립트 일부가 untracked 상태다.
   - `docs/108~113`
   - `scripts/build_graph_index.py`
   - `scripts/check_graph_index.py`
   - 커밋 대상 여부를 명확히 정해야 한다.

6. GraphDB 빌드 산출물은 보정본 우선 원칙을 더 명시적으로 검증해야 한다.
   - `source_mode=v1_v2_combined`이고 `chunks_v1_v2_combined.jsonl`을 사용한다.
   - 그러나 런타임 fact 선택에서 `v2_manual` evidence를 우선하는지 평가 게이트가 아직 충분하지 않다.

## 3. 다음 작업 우선순위

## Phase 0. 작업트리 정리 및 기준 고정

목표: 이후 작업을 안전하게 커밋할 수 있도록 GraphDB 관련 변경과 무관한 변경을 분리한다.

작업:

1. `git status --short`를 확인한다.
2. GraphDB/계산 연동에 필요한 파일만 커밋 후보로 유지한다.
3. 다음 파일의 변경 원인을 확인하고, 이번 작업과 무관하면 stage에서 제외한다.
   - `docs/104_VLLM_READINESS_AUTH_FIX_REPORT.md`
   - `docs/74_CLAUDE_REVIEWER_ENV_HANDOFF_REPORT_20260520.md`
   - `docs/80_STREAMLIT_LARGE_MODEL_TEST_GUIDE.md`
   - `docs/96_CHATBOT_QA_STAGE2_AUTHORING_REPORT.md`
   - `scripts/prepare_offline_assets.py`
   - `src/llm/openai_compatible_client.py`
   - OCR 관련 테스트 파일들
4. `git diff --cached --check`를 통과시킨다.
5. GraphDB 관련 문서/스크립트 중 커밋해야 할 산출물을 명시한다.

검증:

```bash
git diff --cached --check
git status --short
```

## Phase 1. Streamlit 런타임에서 GraphDB 실제 활성화

목표: 사용자가 앱에서 질문했을 때 GraphDB가 실제로 RAG 답변 경로에 적용되도록 한다.

작업:

1. 오프라인 실행 환경에 다음 값을 추가한다.

```env
GRAPH_ENABLED=true
GRAPH_INDEX_PATH=/srv/shared/projects/insurance-rag-chatbot/data/index/graph/insurance_graph.sqlite
GRAPH_CONTEXT_TOP_K=20
GRAPH_CONTEXT_MAX_CHARS=5000
```

2. 다음 런처/준비 스크립트 중 실제 Streamlit 실행 경로에 반영한다.
   - `scripts/prepare_streamlit_runtime.sh`
   - `scripts/run_offline_streamlit_test.sh`
   - `/srv/ai-ops/bin/run-insurance-rag`
   - `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`

3. 8501 프로세스의 환경변수에 `GRAPH_ENABLED=true`가 들어가는지 확인한다.

```bash
tr '\0' '\n' < /proc/<STREAMLIT_PID>/environ | grep GRAPH_
```

4. Streamlit 관리자 진단 패널에서 GraphDB 상태가 `활성`으로 표시되는지 확인한다.

검증:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

브라우저에서 `http://localhost:8501` 접속 후 GraphDB 진단 패널 확인.

## Phase 2. Query Planner 및 GraphRetriever 품질 보강

목표: 복잡 질의에서 잘못된 procedure 추출, 중복 fact, OCR 근거 우선순위 문제를 제거한다.

작업:

1. `GraphQueryPlanner`에서 다음 표현을 procedure 후보에서 제외한다.
   - `에 해당하는 수술`
   - `해당하는 수술`
   - `수술분류표`
   - `수술 종류`
   - `수술 목록`
   - `모두 나열`

2. 카테고리/등급 나열 질의에서는 procedure_name을 비워 둔다.
   - `category`와 `grade_value`가 명확하면 `procedure_name` 추출을 억제한다.

3. `PAYS_BY_RATIO`, `POLICY_COVERS_PROCEDURE` fact를 `(subject, relation, object, appendix_number, payment_ratio)` 기준으로 중복 제거한다.

4. evidence 선택 시 `v2_manual`을 우선한다.
   - 동일 fact에 v1/v2 evidence가 함께 있으면 v2 evidence를 먼저 보여준다.
   - v2가 없을 때만 v1 evidence를 보조 근거로 사용한다.

5. `eval/graph_qa.jsonl`에 다음 검증을 추가한다.
   - Q2에서 `procedure_name`은 `null` 또는 빈 값이어야 한다.
   - Q2에 `에 해당하는 수술` fact가 있으면 실패한다.
   - Q2에서 수술별 `PAYS_BY_RATIO` fact는 최대 1개만 허용한다.
   - confirmed fact evidence는 `source_version=v2_manual`을 우선해야 한다.

검증:

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl
```

## Phase 3. GraphRAG 답변 품질 수동 검증

목표: GraphDB 검색 결과가 실제 LLM 답변에 반영되는지 확인한다.

질문 세트:

1. `기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. 그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘.`
   - 기대: 신1-5종 4종
   - 기대: 같은 종 peer 3개
   - 기대: SOL [별표7] 후보는 candidate로만 표시
   - 기대: 별표7 1번/3번 등 무관 조항 없음

2. `신1-5종 수술분류표에서 5종에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘. 각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘.`
   - 기대: 간장 이식수술, 췌장 이식수술
   - 기대: 수가코드 미매핑은 missing으로 표시
   - 기대: 지급비율은 candidate로 표시
   - 기대: `에 해당하는 수술` 같은 가짜 행 없음

3. `SOL 건강보험 별표7의 18번 항목과 19번 항목의 차이점과 각각 해당하는 수술종류를 알려주세요.`
   - 기대: 18번/19번만 비교
   - 기대: 각 조항의 evidence가 표시됨

4. `존재하지않는가상의수술의 수가코드를 조회해줘.`
   - 기대: missing으로 표시하고 코드 환각 없음

검증 결과는 `reports/graph/` 또는 `docs/` 보고서에 남긴다.

## Phase 4. 보험금 지급예상액 계산 파이프라인 연동

목표: 보험금 보상 질의에서 GraphDB와 비급여 표준모델을 함께 사용해 계산 근거를 구성하고, LLM이 생성한 계산용 Python 코드를 샌드박스에서 실행한다.

작업:

1. 계산 입력에서 다음 정보를 분리한다.
   - 청구 항목명
   - 청구 금액
   - 진료/시술 상황
   - 적용할 상품/약관
   - 자동/수동 근거 선택

2. 근거 선택 순서:
   - 비급여 표준모델 SQLite 매칭
   - GraphDB 수술분류/약관/지급비율 후보
   - RAG 문서 근거
   - 사용자 수동 선택 근거

3. GraphDB fact 적용 규칙:
   - `confirmed`: 계산 근거로 사용 가능
   - `candidate`: 계산 근거 후보로만 표시하고 `requires_review=True`
   - `missing`: 계산식에 사용 금지

4. LLM 계산 planner는 구조화 JSON을 반환해야 한다.
   - 적용 약관
   - 적용/제외된 청구 항목
   - 변수
   - 계산식 의도
   - Python Decimal 코드
   - 검토 필요 사유

5. Python 샌드박스 실행 결과만 최종 금액으로 사용한다.
   - LLM이 자연어로 계산한 금액은 사용하지 않는다.
   - 샌드박스 결과와 설명이 불일치하면 `requires_review=True`.

검증 케이스:

1. confirmed 근거만 있는 계산
2. candidate 지급비율만 있는 계산
3. 비급여 표준코드 다중 후보
4. GraphDB missing 수가코드
5. 사용자 수동 약관 선택

## Phase 5. 커밋 전 최종 게이트

필수 검증:

```bash
cd /srv/shared/projects/insurance-rag-chatbot

git diff --cached --check

PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py

PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl

.venv/bin/pytest tests/test_graph_*.py -v

.venv/bin/pytest tests/test_claim_*.py -v

.venv/bin/pytest tests/test_streamlit_app.py -v

.venv/bin/pytest -q
```

Streamlit 실기동 검증:

```bash
GRAPH_ENABLED=true \
GRAPH_INDEX_PATH=/srv/shared/projects/insurance-rag-chatbot/data/index/graph/insurance_graph.sqlite \
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace
```

8501 프로세스 환경 확인:

```bash
pgrep -af "streamlit run src/ui/streamlit_app.py"
tr '\0' '\n' < /proc/<PID>/environ | grep GRAPH_
```

## 4. 다음 서브 에이전트 작업 단위

다음 서브 에이전트에게는 아래 순서로 지시한다.

1. 작업트리 정리와 whitespace 정리.
2. `GRAPH_ENABLED=true` 런타임 활성화.
3. QueryPlanner의 가짜 procedure 추출 수정.
4. GraphRetriever fact 중복 제거 및 v2_manual evidence 우선순위 적용.
5. `eval_graph_qa.py`와 `graph_qa.jsonl` 강화.
6. 보험금 계산 파이프라인의 GraphDB fact 적용 규칙 보강.
7. 전체 테스트와 Streamlit 8501 실제 확인.
8. 구현 보고서 작성.

보고서 파일명:

```text
docs/116_GRAPHDB_APP_ACTIVATION_AND_CLAIM_CALCULATION_IMPL_REPORT.md
```

## 5. 첫 구현 단위: GraphDB 앱 활성화 패치

첫 번째 구현 단위는 범위를 좁혀서 "GraphDB가 Streamlit 앱에서 실제로 켜지고, 기존 RAG가 깨지지 않는 상태"까지만 달성한다. 보험금 계산 고도화는 두 번째 구현 단위로 분리한다.

### 5.1 수정 대상

첫 구현 단위의 수정 대상은 원칙적으로 아래 파일로 제한한다.

```text
scripts/prepare_streamlit_runtime.sh
scripts/run_offline_streamlit_test.sh
src/config.py
src/graph/query_planner.py
src/graph/retriever.py
src/graph/context.py
eval/graph_qa.jsonl
scripts/eval_graph_qa.py
tests/test_graph_query_planner.py
tests/test_graph_retriever.py
docs/116_GRAPHDB_APP_ACTIVATION_AND_CLAIM_CALCULATION_IMPL_REPORT.md
```

다음 파일은 첫 구현 단위에서 원칙적으로 건드리지 않는다.

```text
src/llm/openai_compatible_client.py
src/retrieval/embedder.py
OCR 관련 테스트 파일
대형 모델/vLLM/SGLang 런처
docs/74_*, docs/80_*, docs/96_*, docs/104_*
```

이미 작업트리에 변경이 남아 있으면, 이유를 확인하고 GraphDB 앱 활성화와 무관한 변경은 별도 작업으로 분리한다.

### 5.2 구현 상세

1. Streamlit 준비/실행 스크립트에 GraphDB 기본 env를 추가한다.

```bash
export GRAPH_ENABLED="${GRAPH_ENABLED:-true}"
export GRAPH_INDEX_PATH="${GRAPH_INDEX_PATH:-$PROJECT_DIR/data/index/graph/insurance_graph.sqlite}"
export GRAPH_CONTEXT_TOP_K="${GRAPH_CONTEXT_TOP_K:-20}"
export GRAPH_CONTEXT_MAX_CHARS="${GRAPH_CONTEXT_MAX_CHARS:-5000}"
```

2. 실행 전 GraphDB 파일 존재 여부를 검사한다.

```bash
if [[ "$GRAPH_ENABLED" == "true" ]]; then
  require_path "$GRAPH_INDEX_PATH" "GraphDB SQLite index"
fi
```

3. `GraphQueryPlanner`에서 카테고리+등급 나열 질의가 명확하면 procedure 추출을 억제한다.

예시 질의:

```text
신1-5종 수술분류표에서 5종에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘.
```

기대:

```python
plan.category == "소화기계"
plan.grade_system == "신1-5종"
plan.grade_value == "5"
plan.procedure_name is None
```

4. `GraphRetriever`에서 fact 중복 제거를 적용한다.

중복 기준:

```python
(subject, relation, object, appendix_number, payment_ratio)
```

5. evidence 정렬은 `source_version == "v2_manual"`을 우선한다.

### 5.3 첫 구현 단위 검증

아래 명령은 반드시 DGX에서 실행한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot

PYTHONPATH=. .venv/bin/python - <<'PY'
from src.graph.query_planner import GraphQueryPlanner
q = "신1-5종 수술분류표에서 5종에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘. 각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘."
p = GraphQueryPlanner().plan(q)
print(p)
assert p.category == "소화기계"
assert p.grade_system == "신1-5종"
assert p.grade_value == "5"
assert p.procedure_name in (None, "")
PY

PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl

GRAPH_ENABLED=true \
GRAPH_INDEX_PATH=/srv/shared/projects/insurance-rag-chatbot/data/index/graph/insurance_graph.sqlite \
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace

pgrep -af "streamlit run src/ui/streamlit_app.py"
tr '\0' '\n' < /proc/<PID>/environ | grep GRAPH_

git diff --cached --check
.venv/bin/pytest tests/test_graph_*.py -v
.venv/bin/pytest tests/test_streamlit_app.py -v
```

브라우저 수동 확인:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

`http://localhost:8501`에서 관리자 진단 패널의 GraphDB 상태가 활성으로 표시되어야 한다.

## 6. 두 번째 구현 단위: 보험금 계산 GraphDB 연동

첫 구현 단위가 완료된 뒤 보험금 계산 연동을 진행한다.

### 6.1 수정 대상

```text
src/claim_calculation/pipeline.py
src/claim_calculation/planner.py
src/claim_calculation/code_sandbox.py
src/ui/streamlit_app.py
tests/test_claim_calculation_pipeline.py
docs/116_GRAPHDB_APP_ACTIVATION_AND_CLAIM_CALCULATION_IMPL_REPORT.md
```

### 6.2 구현 상세

1. 계산 근거에 GraphDB fact를 넣을 때 `confirmed`, `candidate`, `missing`을 명확히 분리한다.
2. `candidate`가 계산에 영향을 줄 수 있으면 `requires_review=True`를 강제한다.
3. LLM Planner가 만든 `formula_intent`는 반드시 Python 샌드박스에서 실행한다.
4. 최종 지급예상액은 샌드박스 실행 결과의 `payable_amount`만 사용한다.
5. LLM 설명 금액과 샌드박스 금액이 다르면 `requires_review=True`와 경고를 남긴다.

### 6.3 두 번째 구현 단위 검증

```bash
.venv/bin/pytest tests/test_claim_calculation_pipeline.py -v
.venv/bin/pytest tests/test_claim_*.py -v
```

Streamlit 보험금 계산 UI에서 최소 3개 케이스를 수동 확인한다.

1. 비급여 표준코드 단일 매칭 + confirmed 근거
2. 비급여 표준코드 다중 후보
3. GraphDB candidate 지급비율만 존재하는 케이스

## 7. 완료 기준

이 작업은 다음이 모두 참일 때 완료로 본다.

1. 8501 Streamlit 프로세스에 `GRAPH_ENABLED=true`가 확인된다.
2. GraphDB 관리자 진단 패널이 활성 상태를 표시한다.
3. 복잡 질의 4개가 GraphDB facts를 실제 답변에 반영한다.
4. Q2에서 가짜 procedure 행이 사라진다.
5. 보험금 계산에서 candidate 약관/지급비율은 확정 지급 근거로 사용되지 않는다.
6. LLM 계산 결과는 Python 샌드박스 실행 결과와 일치한다.
7. GraphDB evidence는 보정본(`v2_manual`)을 우선 사용한다.
8. `git diff --cached --check`와 전체 pytest가 통과한다.
9. GraphDB 산출물 DB 파일은 Git에 포함되지 않는다.
