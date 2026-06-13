# 227. 일반 질의 Top-K/Temperature 자동 설정 조사 및 적용 계획

## 목적

현재 일반 질의 화면은 사용자가 `Top-K`와 `온도(temperature)`를 직접 조정한다. 이는 RAG 검색 폭과 LLM 샘플링을 이해하지 못하는 보험 실무자에게 불필요한 부담이다. 목표는 실무자에게는 기본적으로 "자동"만 보이게 하고, 시스템이 질의 유형과 검색 신호에 따라 안전한 값을 선택하도록 하는 것이다.

이 문서는 2026-06-13 기준 DGX 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot`를 검토한 뒤 작성한 조사/설계 보고서다.

## 현재 DGX 구현 요약

- API schema: `src/api/schemas/chat.py`
  - `top_k`: 기본 10, 범위 1~20
  - `temperature`: 기본 0.2, 범위 0.0~2.0
- API route: `src/api/routes/chat.py`
  - 사용자가 보낸 `top_k`가 `get_rag_pipeline()`과 `prepare_retrieved_context()`에 그대로 전달된다.
  - 사용자가 보낸 `temperature`가 LLM streaming 호출에 그대로 전달된다.
- Frontend: `frontend/html/chat.html`, `frontend/js/pages/chat.js`
  - Top-K/온도 슬라이더를 노출하고, 값 그대로 `/chat/stream` 요청에 포함한다.
- RAG pipeline: `src/rag/pipeline.py`, `src/rag/search_intent.py`
  - 이미 질의 intent 기반으로 dense/BM25 후보 폭과 가중치를 조정하는 로직이 있다.
  - 그러나 최종 context 개수(`final_top_k`)와 LLM sampling temperature는 아직 자동 결정되지 않는다.

따라서 신규 로직은 완전히 별도 추론기를 만들기보다, 기존 `SearchIntentPlan`을 확장해 최종 Top-K/temperature를 결정하는 방식이 가장 안전하다.

## 실무/연구 동향 정리

### 1. 고정 Top-K는 실무 RAG에서 한계가 있다

RAG 원 논문은 외부 메모리 검색을 통해 지식 집약 태스크의 factuality와 provenance 문제를 완화한다. 그러나 실무에서는 항상 같은 개수의 문서를 넣는 방식이 과소/과대 검색 문제를 만든다.

최근 연구 흐름은 "질문마다 검색 필요량과 검색 전략을 다르게 선택"하는 방향이다.

- `Adaptive-RAG`는 질문 복잡도에 따라 no retrieval, single-step RAG, multi-step RAG를 선택한다.
- `Self-RAG`는 모델이 필요 시 검색하고, 검색된 passage와 생성 답변을 스스로 비평하는 구조를 제안한다.
- `FLARE`는 생성 중 낮은 confidence 구간이 생기면 추가 검색을 수행한다.
- `CRAG`는 retrieved document 품질을 평가하고, 부정확하면 corrective action을 수행한다.
- 2026년 `Tail-Aware Adaptive-k`는 ranked similarity curve에서 noise-dominated tail의 시작점을 찾아 query-adaptive cutoff를 선택한다.
- 2026년 `Retriever Portfolios`와 domain-scoped RAG 계열 연구는 단일 retriever/단일 hyperparameter보다 질의 분포별 retriever/범위 선택이 낫다는 방향을 보인다.

우리 프로젝트는 이미 BM25 + Chroma + RRF + reranker + GraphDB를 사용하므로, agentic multi-step RAG를 바로 추가하기보다 "기존 검색 결과의 score/intent/debug 신호로 최종 Top-K를 자동 조절"하는 쪽이 현실적이다.

### 2. 실무 시스템은 hybrid retrieval, RRF, reranking, score debug를 많이 쓴다

Azure AI Search 문서는 hybrid search에서 RRF가 여러 ranked result를 결합하고, vector weighting과 score debug를 통해 하위 점수를 분석할 수 있다고 설명한다. 현재 우리 파이프라인도 RRF와 reranker를 사용하므로, 실무적인 확장 방향은 이미 갖춰진 구조와 맞다.

권장 방향:

- 기존 dense/BM25 후보 폭은 `SearchIntentPlan`에서 계속 결정한다.
- 최종 context Top-K는 reranker 후 점수 분포, 문서 coverage, GraphDB 근거 존재 여부로 결정한다.
- 사용자가 직접 고르는 값은 기본 UI에서 제거하고, 관리자/고급 설정에서만 override한다.

### 3. Temperature는 보험 질의에서는 낮게 고정하는 것이 안전하다

vLLM 문서는 temperature가 sampling randomness를 제어하며, 낮은 값은 더 deterministic하고 `0`은 greedy sampling이라고 정의한다. 보험 약관/실손 보상 질의는 창의적 문체보다 근거 충실성과 수치 정확성이 중요하므로 temperature를 높게 둘 이유가 약하다.

권장 방향:

- 보험금, 면책, 한도, 자기부담, 수가코드, 조문, 비교 질의: `temperature=0.0`
- 일반 설명형 질의: `temperature=0.1~0.2`
- 실무자-facing 기본값은 최대 `0.2`를 넘기지 않는다.
- 사용자가 "쉽게 설명", "요약", "문장 다듬기"를 요구한 경우에만 `0.2` 허용
- 보상 판단/계산/약관 근거 답변에서는 `0.0`을 기본으로 둔다.

## 우리 프로젝트 적용 브레인스토밍

### 제안 1. AutoRagParams 모듈 추가

신규 모듈 후보:

```text
src/rag/auto_params.py
```

핵심 dataclass:

```python
AutoRagParams(
    top_k: int,
    temperature: float,
    profile: str,
    reason: str,
    confidence: float,
)
```

입력:

- `question`
- `mode`
- `filters`
- `SearchIntentPlan`
- GraphDB plan/facts 요약
- reranker 사용 여부
- doc_filter 개수

출력:

- 최종 `top_k`
- 최종 `temperature`
- audit/debug용 사유

### 제안 2. 질의 유형별 conservative rule table

초기 버전은 LLM classifier 없이 규칙 기반으로 시작한다.

| Query profile | 조건 | 자동 Top-K | 자동 온도 | 이유 |
|---|---|---:|---:|---|
| `exact_code_lookup` | 수가코드/EDI/명시 코드 | 4~6 | 0.0 | 표/코드 질의는 잡음 context가 위험 |
| `clause_lookup` | 제n조, 별표, 조항, 청구서류 | 6~8 | 0.0 | 정확 조문 중심 |
| `coverage_judgment` | 보상/지급/면책/한도/자기부담 | 8~10 | 0.0 | 근거 충분성 필요, 생성 랜덤성 최소화 |
| `cross_doc_compare` | 문서별/비교/차이/각각 | 12~14 | 0.0 | 여러 문서 coverage 필요 |
| `ambiguous_medical_term` | MRI/MRA, 도수/충격파 등 | 10~12 | 0.0 | 동의어/표현 차이 보완 |
| `general_explanation` | 일반 설명형 | 6~8 | 0.1~0.2 | 설명 품질은 약간의 유연성 허용 |
| `formal` | 약관 정형 검색 | 6~10 | 0.0 | 선택 filter를 우선 |
| `quickcode` | 퀵 코드 검색 | 기존 전용 Top-K 유지 | 0.0 | 일반 질의 자동화 범위와 분리 |

### 제안 3. reranker score 기반 adaptive final-k

Phase 2에서는 고정 rule table만 쓰지 말고, reranker 이후 최종 후보의 점수 분포를 본다.

아이디어:

1. 기존처럼 dense/BM25/RRF 후보 pool을 만든다.
2. reranker는 `max(profile_top_k * 2, 12)` 정도의 후보를 평가한다.
3. score curve에서 급격한 하락점 또는 최소 score threshold를 찾는다.
4. `min_k <= adaptive_k <= max_k` 범위로 자른다.
5. GraphDB source chunk와 cross-doc coverage 후보는 항상 보존한다.

단, 초기에는 reranker 모델별 score scale이 안정적인지 확인해야 하므로 `observe` 모드로 로그만 쌓고, 실제 적용은 평가 후 켠다.

### 제안 4. UI 변경 방향

기본 실무자 화면:

- `Top-K`, `온도` 슬라이더 제거 또는 접기
- 대신 "검색/답변 설정: 자동" 배지 표시
- 응답 debug 또는 관리자 진단에 실제 적용값 표시

고급/관리자 화면:

- "자동 설정 사용" toggle
- 수동 override는 관리자/개발자 용도로만 유지
- audit log에 `requested_top_k`, `effective_top_k`, `requested_temperature`, `effective_temperature`, `auto_param_reason` 저장

### 제안 5. 평가 방법

기존 일반 질의 평가셋을 그대로 사용한다.

- `eval/policy_xlsx_qa.jsonl`
- `scripts/eval_large_model_rag.py`
- `--index-mode v2_only`

추가 지표:

- answer pass rate
- expected source recall
- source count
- context noise rate
- answer length
- output health
- latency
- route/profile distribution
- manual baseline 대비 개선/악화 문항

초기 acceptance gate:

- 기존 기본값 `top_k=10`, `temperature=0.2` 대비 pass rate 하락 없음
- 수치/조문/코드 질의에서 hallucination 증가 없음
- source recall 하락이 있으면 해당 profile은 자동 적용 보류
- latency는 cross-doc profile을 제외하고 평균 증가 10% 이내

## 단계별 구현 계획

### Phase 1. Observe-only 자동 파라미터 산출

- `src/rag/auto_params.py` 추가
- `SearchIntentPlan` 기반 rule table 구현
- API route에서 실제 적용은 하지 않고 audit/debug에 `suggested_top_k`, `suggested_temperature`만 기록
- 관련 unit test 추가

위험도: 낮음. 동작 변경 없이 관측만 한다.

### Phase 2. 일반 질의에만 자동 적용

- `ChatRequest`에 `auto_params: bool = True` 추가
- 일반 질의 `mode=general`에서만 자동값 적용
- `quickcode`, `formal`, `claim`은 기존 전용 로직 유지
- frontend 기본 UI는 자동 설정으로 전환, 고급 설정에 수동 override 보존

위험도: 중간 이하. 사용자가 직접 조정하던 경로의 기본 동작이 바뀌므로 평가가 필요하다.

### Phase 3. Reranker score adaptive-k

- reranker score payload를 debug 정보에 남김
- score drop/threshold 기반 adaptive final-k를 observe 모드로 검증
- 문서 coverage와 GraphDB source chunk 보존 규칙 추가
- 평가 통과 후 profile별 선택 적용

위험도: 중간. 잘못 자르면 필요한 근거가 빠질 수 있다.

## 확장 적용 계획: threshold 탐색 기반 adaptive-k

사용자 검토 의견에 따라, `adaptive-k`는 단일 고정 규칙으로 바로 편입하지 않는다. reranker 점수 분포에서 "몇 번째 후보 이후부터 관련성이 급격히 떨어지는가"를 판단하는 threshold 계열 로직을 만들고, 실제 평가 후 profile별 최적 후보값을 선택한다.

### 1. 조절 가능한 threshold 후보

초기 구현에서는 다음 파라미터를 feature flag와 환경변수로 분리한다.

| 파라미터 | 의미 | 초기 탐색 범위 | 비고 |
|---|---|---:|---|
| `min_k` | 어떤 경우에도 유지할 최소 context 수 | 4, 5, 6 | profile별 override |
| `max_k` | 어떤 경우에도 넘지 않을 최대 context 수 | 8, 10, 12, 14 | cross-doc은 더 높게 허용 |
| `score_floor` | 이 점수 미만 후보는 tail로 간주 | profile별 grid | reranker score scale 확인 후 결정 |
| `drop_abs` | `score[i] - score[i+1]` 절대 하락폭 | 0.05~0.25 | 급락점 탐지 |
| `drop_ratio` | 다음 후보와의 상대 하락비 | 0.10~0.40 | score scale 차이 보정 |
| `plateau_window` | 완만한 tail 감지를 위한 window 크기 | 2, 3 | 급락이 없는 경우 보조 |
| `coverage_required_docs` | 문서 비교에서 보존해야 할 문서 수 | 질문 기반 | 자동 cutoff보다 우선 |
| `graph_preserve` | GraphDB source chunk 보존 여부 | true | 항상 true 권장 |

초기 env/config 후보:

```text
AUTO_RAG_PARAMS_MODE=off|observe|apply
AUTO_RAG_TOPK_STRATEGY=rule|reranker_threshold
AUTO_RAG_RERANK_SCORE_FLOOR=...
AUTO_RAG_RERANK_DROP_ABS=...
AUTO_RAG_RERANK_DROP_RATIO=...
AUTO_RAG_MIN_K_BY_PROFILE=...
AUTO_RAG_MAX_K_BY_PROFILE=...
AUTO_RAG_TEMPERATURE_POLICY=conservative
```

### 2. adaptive-k 판단 원리

기본 흐름:

1. `SearchIntentPlan`으로 query profile을 정한다.
2. profile별 `min_k`, `base_k`, `max_k`를 선택한다.
3. dense/BM25/RRF 후보 pool을 기존보다 넓게 만든다.
4. reranker가 후보별 score를 반환한다.
5. 점수 내림차순 curve에서 cutoff 후보를 찾는다.
6. `min_k <= cutoff_k <= max_k`로 clamp한다.
7. GraphDB source chunk, 문서별 coverage chunk, exact code/chunk는 cutoff 이후라도 보존한다.
8. 보존 후 context 수가 `max_k`를 넘으면 낮은 신뢰도 일반 chunk부터 제거한다.

간단한 의사코드:

```python
scores = rerank(question, candidates, top_k=pool_k)
cutoff = base_k
for i in range(min_k - 1, min(len(scores) - 1, max_k - 1)):
    drop_abs = scores[i] - scores[i + 1]
    drop_ratio = drop_abs / max(abs(scores[i]), 1e-6)
    if scores[i + 1] < score_floor or drop_abs >= threshold_abs or drop_ratio >= threshold_ratio:
        cutoff = i + 1
        break
selected = preserve_required_hits(scores[:cutoff], graph_hits, coverage_hits, exact_hits)
selected = trim_noise_preserving_required(selected, max_k=max_k)
```

주의점:

- reranker score는 모델/배치/입력 길이에 따라 scale이 달라질 수 있으므로 절대 score만으로 결정하지 않는다.
- `drop_abs`, `drop_ratio`, `min/max_k`를 함께 사용한다.
- coverage 판단이 필요한 질문은 "관련성 낮아 보이는 chunk"라도 특정 문서의 유일한 근거일 수 있으므로 보존 규칙이 우선한다.

### 3. profile별 초기 가설

| Profile | 초기 전략 | threshold 적용 강도 |
|---|---|---|
| `exact_code_lookup` | 낮은 `max_k`, 높은 BM25/코드 보존 | 강하게 적용 |
| `clause_or_appendix_lookup` | exact 조문/별표 chunk 보존 | 중간 |
| `clause_detail_lookup` | 조문 본문 + 세부 조건 chunk 보존 | 중간 이하 |
| `coverage_judgment` | 근거 누락 위험이 높아 `min_k` 높게 유지 | 약하게 적용 |
| `cross_doc_compare` | 문서별 coverage가 우선 | 매우 약하게 적용 |
| `ambiguous_medical_term` | 동의어/표현 차이 때문에 후보 폭 유지 | 약하게 적용 |
| `general_explanation` | 잡음 감소 목적의 cutoff 유효 | 중간~강함 |

### 4. threshold 최적값 탐색 방법

`threshold 최적값`은 전체 질의에 하나로 고정하지 않는다. profile별로 후보값을 비교하고, pass rate와 위험 지표를 동시에 만족하는 Pareto 후보를 선택한다.

평가 입력:

- 기존 일반 질의 평가셋: `eval/policy_xlsx_qa.jsonl`
- 인덱스: `--index-mode v2_only`
- 모델: 기본 일반 질의 모델 `sglang:qwen3-next-80b-a3b-instruct-fp8`
- baseline: 현재 기본값 `top_k=10`, `temperature=0.2`

실험 matrix:

```text
strategy:
  - fixed_baseline
  - rule_only
  - reranker_threshold

temperature_policy:
  - current_0.2
  - conservative_by_profile
  - temperature_grid_by_profile

threshold_grid:
  min_k: [4, 5, 6, 8]
  max_k: [8, 10, 12, 14]
  drop_abs: [0.05, 0.10, 0.15, 0.20]
  drop_ratio: [0.10, 0.20, 0.30]
  score_floor: reranker score 분포 관측 후 후보 산정

temperature_grid:
  exact_code_lookup: [0.0, 0.05, 0.1]
  clause_or_appendix_lookup: [0.0, 0.05, 0.1]
  clause_detail_lookup: [0.0, 0.05, 0.1]
  coverage_judgment: [0.0, 0.05, 0.1, 0.2]
  cross_doc_compare: [0.0, 0.05, 0.1]
  ambiguous_medical_term: [0.0, 0.05, 0.1, 0.2]
  general_explanation: [0.0, 0.1, 0.2, 0.3]
```

산출물:

```text
reports/auto_rag_params_eval/<label>.jsonl
reports/auto_rag_params_eval/<label>.md
```

필수 지표:

- answer pass rate
- expected source recall
- required number/term/clause hit rate
- retrieval miss count
- context noise count
- average selected top_k
- average prompt context length
- latency
- output health
- profile별 개선/악화 문항

선택 기준:

1. baseline 대비 answer pass rate가 하락하지 않을 것
2. source recall이 하락하지 않을 것
3. 보상/면책/한도/수가/조문 질의에서 critical miss가 증가하지 않을 것
4. context noise와 평균 context 길이가 의미 있게 줄어들 것
5. latency가 악화되지 않거나, 악화되더라도 품질 개선 근거가 있을 것
6. profile별 결과가 불안정하면 해당 profile은 `rule_only` 또는 baseline 유지

### 4-1. temperature 최적값 탐색 방법

`temperature`도 `Top-K`와 별개로 profile별 탐색 대상에 포함한다. 특히 우리 프로젝트에는 실무자가 제시한 테스트 질문과 기대 답안 셋이 있으므로, 단순 문체 선호가 아니라 "기대 답안의 필수 수치/조항/조건을 얼마나 안정적으로 재현하는가"를 기준으로 평가할 수 있다.

기본 원칙:

- 보험금 지급, 면책, 감액, 한도, 자기부담금, 수가코드, 조문 질의는 낮은 temperature를 우선한다.
- 일반 설명형 질의는 답변 가독성/어조를 위해 약간 높은 후보도 평가한다.
- temperature 평가는 stochastic성이 있으므로 같은 설정을 1회만 돌려 결론 내리지 않는다.
- 답변 품질이 동률이면 더 낮은 temperature를 선택한다.

profile별 초기 가설:

| Profile | 후보 temperature | 1차 가설 |
|---|---:|---|
| `exact_code_lookup` | 0.0, 0.05, 0.1 | `0.0` 우선. 코드/점수/표 항목은 변형 여지가 작다. |
| `clause_or_appendix_lookup` | 0.0, 0.05, 0.1 | `0.0` 우선. 조문 번호와 조건 누락 방지가 중요하다. |
| `clause_detail_lookup` | 0.0, 0.05, 0.1 | `0.0~0.05` 후보. 문장 자연성보다 정확성이 우선이다. |
| `coverage_judgment` | 0.0, 0.05, 0.1, 0.2 | `0.0~0.1` 후보. 검토 필요/조건부 판단 표현 안정성이 중요하다. |
| `cross_doc_compare` | 0.0, 0.05, 0.1 | `0.0` 우선. 문서별 차이를 섞으면 안 된다. |
| `ambiguous_medical_term` | 0.0, 0.05, 0.1, 0.2 | `0.05~0.1` 후보. 용어 설명은 약간의 유연성이 유리할 수 있다. |
| `general_explanation` | 0.0, 0.1, 0.2, 0.3 | `0.1~0.2` 후보. 단, 근거 밖 표현 증가 시 낮춘다. |

평가 반복:

```text
temperature_eval_repeats:
  deterministic_profiles:
    exact_code_lookup: 2
    clause_or_appendix_lookup: 2
    cross_doc_compare: 2
  judgment_profiles:
    coverage_judgment: 3
    ambiguous_medical_term: 3
    general_explanation: 3
```

반복 실행을 두는 이유:

- `temperature=0.0`은 대부분 deterministic에 가깝지만 backend/model template에 따라 완전 동일하지 않을 수 있다.
- `temperature>0`은 같은 질문에서도 답변 길이, 조건 표현, 검토 필요 문구가 흔들릴 수 있다.
- 보험 실무 질의에서는 평균 점수보다 최악 반복 결과가 중요하다. 한 번이라도 근거 밖 단정이나 수치 오류가 나오면 해당 profile의 후보 temperature를 낮춘다.

평가 지표:

- `expected_answer_pass`: 기대 답안 필수 조건 충족 여부
- `required_number_pass`: 금액, 비율, 횟수, 코드, 조문 번호 일치
- `required_clause_pass`: 기대 조항/별표/문서 근거 포함
- `forbidden_claim_absent`: 기대 답안에 없는 보상 단정/면책 단정 미발생
- `tone_fit`: 실무자-facing 답변 어조, 과도한 장황함/모호함/마케팅 문구 여부
- `answer_length_fit`: profile별 권장 길이 범위
- `repeat_stability`: 반복 실행 간 필수 결론 일관성
- `worst_run_pass`: 반복 실행 중 최저 품질 결과도 gate 통과 여부

선택 기준:

1. profile별 `worst_run_pass`가 baseline 이상이어야 한다.
2. 필수 수치/조항/조건 정확도는 temperature 상승으로 절대 악화되면 안 된다.
3. 답변 어조/가독성 개선이 있더라도 factual score가 동률 이상일 때만 higher temperature를 선택한다.
4. `coverage_judgment`에서 "검토 필요"를 "지급 가능"으로 단정하는 사례가 나오면 해당 temperature 후보는 즉시 탈락한다.
5. `general_explanation`에서도 근거 밖 일반론이 늘어나면 `0.2` 이상은 배제한다.
6. 최종값은 전역 하나가 아니라 profile별 `temperature_policy`로 저장한다.

temperature 실험 산출물:

```text
reports/auto_rag_params_eval/<label>_temperature_grid.jsonl
reports/auto_rag_params_eval/<label>_temperature_grid.md
config/auto_rag_temperature_policy.json
```

`config/auto_rag_temperature_policy.json` 예시:

```json
{
  "default": 0.0,
  "profiles": {
    "exact_code_lookup": 0.0,
    "clause_or_appendix_lookup": 0.0,
    "coverage_judgment": 0.05,
    "ambiguous_medical_term": 0.1,
    "general_explanation": 0.2
  },
  "max_allowed": 0.2,
  "fallback_on_low_confidence": 0.0
}
```

### 4-2. Top-K와 temperature의 결합 평가

Top-K와 temperature는 독립 변수가 아니다. 낮은 Top-K로 근거가 부족한 상태에서 temperature가 높으면 근거 밖 추론이 늘 수 있고, 높은 Top-K로 잡음이 많은 상태에서 temperature가 높으면 엉뚱한 조건을 섞을 위험이 커진다.

따라서 최종 적용 전에는 다음 순서로 결합 평가한다.

1. `fixed_baseline`: 현재 `top_k=10`, `temperature=0.2`
2. `rule_topk + fixed_temp`: Top-K만 자동화하고 temperature는 0.2 유지
3. `fixed_topk + temp_policy`: Top-K는 10 유지, temperature만 profile별 자동화
4. `rule_topk + temp_policy`: deterministic rule 기반 통합 자동화
5. `threshold_topk + temp_policy`: threshold 기반 adaptive-k까지 포함

결합 평가에서 확인할 질문:

- 성능 개선이 Top-K 때문인지, temperature 때문인지 구분되는가?
- temperature를 낮춘 것만으로 hallucination이 줄었는가?
- adaptive-k가 context noise를 줄였지만 source recall을 낮추지는 않았는가?
- 두 자동화가 결합될 때 특정 profile에서 악화되는가?

최종 채택 기준:

- `rule_topk + temp_policy`가 baseline보다 안정적으로 좋으면 먼저 적용한다.
- `threshold_topk + temp_policy`는 추가 이득이 명확한 profile에만 제한 적용한다.
- 결합 평가에서 원인 분리가 안 되면 temperature 정책만 먼저 적용하고 adaptive-k는 observe에 남긴다.

### 5. 개발 단계

#### Step A. 계측 기반 확장

- reranker가 최종 score를 반환하도록 debug payload 확장
- `DebugInfo`에 `reranker_scores`, `candidate_rank`, `selected_by_auto_params`, `cutoff_reason` 추가
- API audit log에 다음 필드 추가
  - `auto_params_mode`
  - `requested_top_k`
  - `effective_top_k`
  - `suggested_top_k`
  - `requested_temperature`
  - `effective_temperature`
  - `suggested_temperature`
  - `temperature_policy`
  - `temperature_eval_profile`
  - `auto_profile`
  - `auto_cutoff_reason`

#### Step B. `AutoRagParams` 구현

- `src/rag/auto_params.py` 추가
- 입력은 `question`, `mode`, `filters`, `SearchIntentPlan`, reranker score summary
- 출력은 `AutoRagParams`
- 초기에는 `rule_only`와 `observe`만 구현
- `quickcode`, `formal`, `claim`은 적용 대상에서 제외하거나 별도 profile로 격리

#### Step C. 평가 스크립트 확장

- `scripts/eval_large_model_rag.py`에 자동 파라미터 모드 추가
- `--auto-params-mode off|observe|apply`
- `--auto-topk-strategy rule|reranker_threshold`
- `--threshold-grid` 또는 config JSON 입력 지원
- `--temperature-grid` 또는 temperature policy JSON 입력 지원
- `--repeat-per-case`로 temperature 후보 반복 실행 지원
- profile별 결과표와 악화 문항 목록 생성

#### Step D. UI 반영

- 기본 실무자 화면은 "자동 설정" badge만 표시
- 수동 Top-K/온도 슬라이더는 "고급 설정" 접힘 영역으로 이동
- 자동 적용값을 관리자 진단 또는 응답 metadata에서 확인 가능하게 표시
- 수동 override가 켜진 경우에는 badge를 "수동 설정"으로 표시

#### Step E. feature flag 적용

권장 rollout:

1. `AUTO_RAG_PARAMS_MODE=observe`
2. 평가셋과 실제 로그에서 suggested/effective 차이 분석
3. `rule_only`를 일부 profile에만 `apply`
4. `reranker_threshold`는 profile별로 제한 적용
5. 문제 발생 시 env만 바꿔 즉시 `off`로 rollback

### 6. 검증 단계

단위 테스트:

- `tests/test_auto_rag_params.py`
  - profile별 Top-K/temperature 선택
  - min/max clamp
  - exact/GraphDB/coverage 보존
  - threshold 급락점 탐지
  - threshold가 없을 때 base_k fallback

통합 테스트:

- `tests/test_api_chat_stream.py`
  - 자동 모드에서 `effective_top_k`, `effective_temperature`가 audit/debug에 남는지 확인
  - 수동 override가 기존 동작을 보존하는지 확인

평가:

```bash
.venv/bin/python scripts/eval_large_model_rag.py \
  --eval-set eval/policy_xlsx_qa.jsonl \
  --index-mode v2_only \
  --model sglang:qwen3-next-80b-a3b-instruct-fp8 \
  --auto-params-mode apply \
  --auto-topk-strategy rule \
  --temperature-policy conservative \
  --label auto_params_rule_v1
```

추가 threshold 평가:

```bash
.venv/bin/python scripts/eval_large_model_rag.py \
  --eval-set eval/policy_xlsx_qa.jsonl \
  --index-mode v2_only \
  --model sglang:qwen3-next-80b-a3b-instruct-fp8 \
  --auto-params-mode apply \
  --auto-topk-strategy reranker_threshold \
  --threshold-grid config/auto_rag_threshold_grid.json \
  --label auto_params_threshold_grid_v1
```

temperature grid 평가:

```bash
.venv/bin/python scripts/eval_large_model_rag.py \
  --eval-set eval/policy_xlsx_qa.jsonl \
  --index-mode v2_only \
  --model sglang:qwen3-next-80b-a3b-instruct-fp8 \
  --auto-params-mode apply \
  --auto-topk-strategy rule \
  --temperature-grid config/auto_rag_temperature_grid.json \
  --repeat-per-case 3 \
  --label auto_params_temperature_grid_v1
```

결합 평가:

```bash
.venv/bin/python scripts/eval_large_model_rag.py \
  --eval-set eval/policy_xlsx_qa.jsonl \
  --index-mode v2_only \
  --model sglang:qwen3-next-80b-a3b-instruct-fp8 \
  --auto-params-mode apply \
  --auto-topk-strategy reranker_threshold \
  --threshold-grid config/auto_rag_threshold_grid.json \
  --temperature-policy config/auto_rag_temperature_policy.json \
  --repeat-per-case 3 \
  --label auto_params_combined_grid_v1
```

수동 점검:

- baseline에서 맞고 자동 모드에서 틀린 문항 전수 확인
- source recall 하락 문항은 자동 적용 차단 profile로 되돌림
- 일반 설명형에서만 context noise 감소 이득이 있는지 확인
- temperature 상승 후보에서 근거 밖 단정, 과장 표현, 불필요한 장문 답변이 늘었는지 확인
- 반복 실행 중 한 번이라도 위험 답변이 나온 profile은 더 낮은 temperature로 되돌림

### 7. 피드백 루프

운영/개발 피드백은 다음 형태로 누적한다.

- 사용자 thumbs up/down 또는 "근거 부족" feedback
- 관리자 진단의 자동 parameter trace
- `CHAT_QUERY` audit log의 profile/effective parameter/result metadata
- 평가 실패 문항 회귀셋 편입

피드백 처리 원칙:

- 개별 실패를 즉시 threshold에 반영하지 않는다.
- 같은 profile/문서유형/실패유형이 반복될 때만 rule table 또는 threshold 후보를 조정한다.
- 조정 후 반드시 기존 40문항 평가셋과 새 회귀셋을 함께 돌린다.
- 최적값은 전역 하나가 아니라 profile별 config로 관리한다.

권장 정기 산출물:

```text
reports/auto_rag_params_eval/<date>_feedback_regression.md
```

포함 내용:

- profile별 요청 수
- 자동 선택 Top-K 분포
- 평균 temperature
- profile별 temperature 분포
- temperature별 negative feedback rate
- feedback negative rate
- source recall 하락 사례
- threshold 변경 제안
- temperature policy 변경 제안

### Phase 4. Corrective retrieval는 보류

CRAG/Self-RAG/FLARE식 반복 검색은 매력적이지만 현재 보험 실무 앱에는 즉시 적용하지 않는다.

보류 이유:

- LLM 호출 수와 latency 증가
- 망분리/오프라인 정책과 외부 web search 방식의 충돌 가능성
- 반복 생성 중 잘못된 query rewrite가 보험 판단 근거를 왜곡할 가능성
- 현재 병목은 이미 모델보다 retrieval/index 품질과 context 선택에 가깝다.

## 안정성 평가

### 편입 자체의 안정성

판단: `Phase 1~2는 안정적으로 편입 가능`, `Phase 3은 평가 후 제한 적용`, `Phase 4 agentic/corrective RAG는 현 시점 보류`.

근거:

- 현재 코드에 이미 `SearchIntentPlan`과 Dynamic RRF 관측 구조가 있어 자동 파라미터 산출 지점을 추가하기 쉽다.
- Top-K/temperature 자동화는 지식 체계 자체를 바꾸지 않으며, ontology/GraphDB/인덱스 산출물을 직접 변경하지 않는다.
- 보험 도메인에서는 temperature를 낮추는 방향이므로 hallucination 위험을 줄이는 쪽이다.
- 가장 큰 위험은 `top_k`를 너무 낮춰 근거를 누락하는 경우다. 따라서 초기 rule은 conservative하게 두고, cross-doc/coverage 계열은 현재 기본값보다 낮추지 않는다.

### 주요 위험과 완화

| 위험 | 설명 | 완화 |
|---|---|---|
| 근거 누락 | 자동 Top-K가 낮아져 필요한 조항/표가 빠짐 | profile별 min_k, source recall gate, GraphDB chunk 보존 |
| 잡음 증가 | 자동 Top-K가 높아져 관련 없는 예시/전화번호/보험료가 섞임 | exact/code/clause profile은 낮은 Top-K 유지 |
| 설명 불투명 | 실무자가 왜 값이 바뀌었는지 모름 | 자동 설정 배지와 관리자 debug/audit log |
| 평가셋 과적합 | 40문항 평가셋에만 맞춘 rule이 됨 | profile별 holdout, 실패 문항 회귀셋 축적 |
| latency 증가 | cross-doc/ambiguous에서 후보를 많이 검색 | profile별 latency budget, observe mode |
| 기능 충돌 | quickcode/formal 흡수 로직과 충돌 | Phase 2에서는 general path만 적용, 전용 모드 제외 |

## 권장 결론

바로 구현한다면 다음 범위가 적절하다.

1. `src/rag/auto_params.py`로 deterministic rule 기반 자동 Top-K/temperature 산출기를 만든다.
2. 기존 `classify_search_intent()` 결과를 재사용한다.
3. 기본 실무자 UI는 "자동"으로 바꾸고, 수동 슬라이더는 고급 설정에 둔다.
4. 초기 적용값은 보수적으로 둔다.
   - 보상/지급/면책/한도/코드/조문: `temperature=0.0`
   - 일반 설명형만 `0.1~0.2`
   - exact/code/clause는 Top-K를 줄이고, cross-doc/coverage는 충분히 유지한다.
5. 첫 배포는 observe-only 또는 feature flag로 시작하고, 기존 40문항 평가셋과 실제 로그로 검증한 뒤 기본 활성화한다.

이 방식은 최신 adaptive RAG 연구의 방향성과 맞지만, 우리 프로젝트에는 연구형 agentic RAG를 그대로 들여오는 것보다 기존 intent router와 reranker를 활용하는 경량 자동화가 더 안전하다.

## 참고 자료

- Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", 2020: https://arxiv.org/abs/2005.11401
- Azure AI Search, "Relevance scoring in hybrid search using Reciprocal Rank Fusion": https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking
- Jeong et al., "Adaptive-RAG", 2024: https://arxiv.org/abs/2403.14403
- Asai et al., "Self-RAG", 2023: https://arxiv.org/abs/2310.11511
- Jiang et al., "Active Retrieval Augmented Generation / FLARE", 2023: https://arxiv.org/abs/2305.06983
- Yan et al., "Corrective Retrieval Augmented Generation", 2024: https://arxiv.org/abs/2401.15884
- Wang et al., "TARG: Training-Free Adaptive Retrieval Gating for Efficient RAG", 2025: https://arxiv.org/abs/2511.09803
- Stouras et al., "Retriever Portfolios", 2026: https://arxiv.org/abs/2605.31176
- Subedi et al., "When More Documents Hurt RAG", 2026: https://arxiv.org/abs/2606.11350
- Song et al., "Tail-Aware Adaptive-k", 2026: https://arxiv.org/abs/2606.11907
- vLLM SamplingParams temperature documentation: https://docs.vllm.ai/en/latest/api/vllm/sampling_params/
