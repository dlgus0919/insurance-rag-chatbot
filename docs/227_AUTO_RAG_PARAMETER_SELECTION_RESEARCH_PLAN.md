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
