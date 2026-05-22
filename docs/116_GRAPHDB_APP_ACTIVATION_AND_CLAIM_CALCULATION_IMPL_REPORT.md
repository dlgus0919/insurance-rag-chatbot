# 116. GraphDB 앱 활성화 1차 구현 보고서

## 1. 개요

`docs/115_GRAPHDB_APP_ACTIVATION_AND_CLAIM_CALCULATION_PLAN.md`의 첫 구현 단위에 따라 GraphDB가 Streamlit 런타임에서 실제 활성화될 수 있도록 실행 스크립트를 보강하고, GraphRAG 복합 질의에서 발견된 QueryPlanner 및 GraphRetriever 결함을 수정했다.

이번 범위는 GraphDB 앱 활성화와 복잡 질의 검색 품질 보강까지이며, 보험금 계산 파이프라인의 LLM 기반 계산 고도화는 후속 구현 단위로 남긴다.

## 2. 변경 파일

- `scripts/run_offline_streamlit_test.sh`
- `scripts/prepare_streamlit_runtime.sh`
- `src/graph/query_planner.py`
- `src/graph/retriever.py`
- `scripts/eval_graph_qa.py`
- `eval/graph_qa.jsonl`
- `tests/test_graph_query_planner.py`
- `tests/test_graph_retriever.py`

## 3. 핵심 변경

1. Streamlit 런타임 GraphDB 기본 활성화
   - `GRAPH_ENABLED=true`
   - `GRAPH_INDEX_PATH=/srv/shared/projects/insurance-rag-chatbot/data/index/graph/insurance_graph.sqlite`
   - `GRAPH_CONTEXT_TOP_K=20`
   - `GRAPH_CONTEXT_MAX_CHARS=5000`
   - GraphDB 파일이 없으면 준비 스크립트에서 명확히 실패하도록 검증 경로를 추가했다.

2. QueryPlanner 가짜 procedure 추출 방지
   - 카테고리와 등급이 명확한 나열 질의에서는 procedure 추출을 억제한다.
   - `신1-5종 수술분류표에서 5종에 해당하는 수술...` 질의가 더 이상 `procedure_name='에 해당하는 수술'`을 만들지 않는다.

3. GraphRetriever 중복 fact 제거
   - `PAYS_BY_RATIO` 중복 fact를 수술명, relation, object, 지급비율 기준으로 병합한다.
   - 소화기계 5종 질의에서 지급비율 fact가 수술별 3개씩 반환되던 문제가 수술별 1개로 줄었다.

4. 보정본 evidence 우선 정렬
   - `GraphEvidence`에 `source_version`을 포함하고, evidence 목록에서 `v2_manual`을 먼저 사용하도록 정렬한다.
   - 별표7 18/19번 조항 evidence는 `v2_manual` 근거를 우선 반환한다.

5. Graph QA 평가 강화
   - Q2에서 `procedure_name`이 `None`이어야 함을 검증한다.
   - Q2에서 `에 해당하는 수술` fact가 나오면 실패하도록 forbidden fact를 추가했다.
   - Q4에서 confirmed 별표 조항 fact가 `v2_manual` evidence를 가져야 함을 검증한다.

## 4. 실행한 검증

```bash
cd /srv/shared/projects/insurance-rag-chatbot

PYTHONPATH=. .venv/bin/python - <<'PY'
from src.graph.query_planner import GraphQueryPlanner
q = '신1-5종 수술분류표에서 5종에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘. 각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘.'
p = GraphQueryPlanner().plan(q)
print(p)
assert p.category == '소화기계'
assert p.grade_system == '신1-5종'
assert p.grade_value == '5'
assert p.procedure_name in (None, '')
PY
```

결과: 통과.

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl
```

결과: `Evaluation Summary: 5/5 cases passed.`

```bash
.venv/bin/pytest tests/test_graph_query_planner.py tests/test_graph_retriever.py -v
```

결과: `8 passed`.

```bash
bash -n scripts/run_offline_streamlit_test.sh
bash -n scripts/prepare_streamlit_runtime.sh
```

결과: 통과.

```bash
bash scripts/prepare_streamlit_runtime.sh --skip-offline-assets --skip-v2-handoff-import
```

결과: 기존 OCR/인덱스/GraphDB 산출물을 모두 감지하고 준비 완료. GraphDB SQLite index도 존재 확인.

```bash
git diff --check -- \
  scripts/run_offline_streamlit_test.sh \
  scripts/prepare_streamlit_runtime.sh \
  src/graph/query_planner.py \
  src/graph/retriever.py \
  scripts/eval_graph_qa.py \
  eval/graph_qa.jsonl \
  tests/test_graph_query_planner.py \
  tests/test_graph_retriever.py
```

결과: 통과.

## 5. 실행하지 않은 검증 및 남은 위험

- Streamlit 8501 프로세스 재시작은 수행하지 않았다. 현재 실행 중인 앱을 끊지 않기 위해 런타임 env 반영은 다음 재기동 시 적용된다.
- 전체 `git diff --cached --check`는 기존 staged 파일들의 trailing whitespace 때문에 아직 실패한다. 이번 수정 파일 범위에서는 통과한다.
- 전체 pytest는 이번 범위에서 실행하지 않았다. GraphDB 핵심 테스트와 평가 스크립트는 통과했다.
- 보험금 계산 파이프라인의 LLM Planner 및 샌드박스 결과 불일치 검증은 후속 구현 단위로 남아 있다.

## 6. 다음 작업

1. Streamlit을 `prepare_streamlit_runtime.sh --run-streamlit --replace`로 재기동하여 8501 프로세스에 `GRAPH_ENABLED=true`가 들어가는지 확인한다.
2. 브라우저에서 GraphDB 관리자 진단 패널이 활성 상태로 표시되는지 확인한다.
3. 복잡 질의 4개를 실제 앱에서 테스트한다.
4. 보험금 계산 파이프라인의 GraphDB fact 적용 규칙과 LLM 계산 코드 실행 검증을 진행한다.
