# 229. 자동 RAG 파라미터 조절 기능 완료 보고

## 요약

- 일반 질의 자동 Top-K/temperature 조절 기능을 운영 경로와 평가 경로에 모두 연결했다.
- 기본 운영 정책은 `rule_auto`로 유지한다.
- reranker 점수 분포 기반 `threshold_auto`는 구현했지만, 전체 평가에서 baseline보다 우수하지 않고 일부 문항을 악화시켜 기본값으로 켜지 않는다.
- 모든 평가는 보정 OCR 편입 인덱스인 `v2_only` 기준으로 수행했다.

## 구현 내용

### 운영 로직

- `src/rag/auto_params.py`
  - 질의 profile별 Top-K/temperature 산출을 유지했다.
  - `rule` / `reranker_threshold` Top-K 전략을 분리했다.
  - `AdaptiveKDecision`과 reranker 점수 낙폭 기반 cutoff 로직을 추가했다.
  - GraphDB 근거 청크와 명시 문서 필터별 최소 근거가 cutoff로 제거되지 않도록 보존 로직을 추가했다.

- `src/rag/pipeline.py`, `src/api/rag_service.py`
  - 넓게 검색한 뒤 reranker 점수 분포에 따라 최종 후보를 줄이는 후처리 경로를 추가했다.
  - `DebugInfo.auto_cutoff`에 cutoff 결과를 기록한다.

- `src/api/routes/chat.py`
  - `AUTO_RAG_TOPK_STRATEGY`, `AUTO_RAG_TEMPERATURE_POLICY_PATH` 설정을 실제 채팅 경로에 연결했다.
  - 감사 로그에 `retrieval_top_k`, `final_top_k`, `rag_diagnostics.auto_cutoff`를 남긴다.
  - 기존 `top_k` 감사 필드는 정책상 목표값으로 유지했다.

- `config/auto_rag_temperature_policy.json`
  - profile별 보수 온도 정책을 파일로 분리했다.

### 평가 로직

- `scripts/eval_auto_rag_params.py`
  - `baseline_fixed`, `rule_auto`, `threshold_auto`, `temperature_grid_*` 전략을 같은 평가셋으로 비교한다.
  - 평가셋 기본값은 `eval/policy_xlsx_qa.jsonl`이다.
  - 인덱스 기본값은 `v2_only`로 고정했다.
  - 결과는 `reports/auto_rag_params_eval/*.jsonl`, `*.md`, `*.summary.json`에 저장된다.

## 전체 평가 결과

실행 명령:

```bash
.venv/bin/python scripts/eval_auto_rag_params.py \
  --cases eval/policy_xlsx_qa.jsonl \
  --models sglang:qwen3-next-80b-a3b-instruct-fp8 \
  --stage all \
  --temperature-grid 0,0.1,0.2 \
  --index-mode v2_only \
  --label full_auto_params_20260613_215957 \
  --max-tokens 700 \
  --embedder-device cpu \
  --stop-llm-after
```

결과 파일:

- `reports/auto_rag_params_eval/auto_rag_params_eval_full_auto_params_20260613_215957.jsonl`
- `reports/auto_rag_params_eval/auto_rag_params_eval_full_auto_params_20260613_215957.md`
- `reports/auto_rag_params_eval/auto_rag_params_eval_full_auto_params_20260613_215957.summary.json`

전략별 결과:

| strategy | pass | pass rate | avg quality | avg chars |
| --- | ---: | ---: | ---: | ---: |
| `rule_auto` | 29/40 | 72.50% | 0.993 | 745.4 |
| `temperature_grid_0` | 29/40 | 72.50% | 0.993 | 758.7 |
| `temperature_grid_0.1` | 29/40 | 72.50% | 0.993 | 754.5 |
| `baseline_fixed` | 28/40 | 70.00% | 0.993 | 789.6 |
| `threshold_auto` | 28/40 | 70.00% | 0.993 | 739.5 |
| `temperature_grid_0.2` | 28/40 | 70.00% | 0.993 | 747.4 |

주요 차이:

- `rule_auto`는 baseline 대비 `policy_xlsx_033`, `policy_xlsx_040`을 개선했다.
- `rule_auto`는 baseline 대비 `policy_xlsx_031`에서 악화됐다.
- `threshold_auto`는 `policy_xlsx_004`에서 `rule_auto` 대비 악화됐다.
- `temperature_grid_0.2`는 `policy_xlsx_040`에서 `rule_auto` 대비 악화됐다.

## 정책 판단

- 기본값은 `AUTO_RAG_PARAMS_MODE=apply`, `AUTO_RAG_TOPK_STRATEGY=rule`이 적절하다.
- `reranker_threshold`는 기능은 구현됐지만 기본값으로 사용하지 않는다.
  - 이유: pass rate가 70.00%로 baseline과 같고 `rule_auto`보다 낮다.
  - 일부 문항에서 근거 후보를 너무 줄여 필수 용어/숫자 누락을 만들었다.
- temperature는 현재 profile 기반 보수 정책을 유지한다.
  - coverage/judgment, 조항 조회, 코드 조회는 `0.0`이 적절하다.
  - ambiguous medical term은 `0.1`로 유지한다.
  - general explanation은 현재 `0.2`로 유지하되, 추가 반복 평가에서 `0.0` 또는 `0.1`이 안정적으로 우세하면 낮추는 것이 가능하다.

## 남은 위험

- `clause_detail_lookup` 2건은 모든 전략에서 0/2였다. 이는 자동 파라미터 문제가 아니라 조항 세부 검색/프롬프트/정형 근거 추출 문제로 분리해야 한다.
- 일부 실패는 답변이 의미상 맞아도 평가셋의 required term/number 조건을 충족하지 못한 경우가 있다. 평가셋 기준 검토와 검색 로직 개선을 분리해야 한다.
- 이번 전체 평가는 단일 모델, 단일 반복 기준이다. 운영 기본값 확정에는 충분하지만, threshold 전략을 기본값으로 승격하려면 반복 평가와 profile별 threshold 튜닝이 필요하다.

## 검증

- 로컬:
  - `python -m py_compile src/rag/auto_params.py src/rag/pipeline.py src/api/rag_service.py src/api/routes/chat.py scripts/eval_auto_rag_params.py`
  - `pytest tests/test_auto_rag_params.py tests/test_auto_rag_param_eval.py -q` → 12 passed

- DGX:
  - `.venv/bin/python -m py_compile src/rag/auto_params.py src/rag/pipeline.py src/api/rag_service.py src/api/routes/chat.py scripts/eval_auto_rag_params.py`
  - `.venv/bin/python -m pytest tests/test_auto_rag_params.py tests/test_auto_rag_param_eval.py tests/test_api_chat_stream.py::test_chat_stream_applies_auto_params_and_records_requested_values tests/test_api_chat_stream.py::test_rag_diagnostics_include_clarification_and_normalized_terms -q` → 14 passed, 1 warning
  - `.venv/bin/python -m pytest tests/test_auto_rag_param_eval.py -q` → 3 passed
  - 전체 평가 240 조합 완료, 평가 종료 후 SGLang 세션 정리 완료

