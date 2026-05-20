# Gemma4 SGLang Root Cause Report

## 요약

`gemma-4-26b-a4b-nvfp4`는 현재 DGX Spark의 native SGLang 경로에서 정상 답변 생성 모델로 사용할 수 없다. 모델은 `/v1/models`에 표시되고 weight load도 완료되지만, `/v1/chat/completions` direct call에서 본문 대신 `<pad>` 토큰을 반복 생성한다.

따라서 이번 조치에서는 Gemma4를 SGLang 운영 후보에서 기본 제외하고, Streamlit/LLM factory/운영 switch wrapper에서 깨진 모델을 정상 선택지처럼 노출하지 않도록 차단했다. 정상 운영 후보는 `gpt-oss-20b`로 복귀했다.

## 조사 근거

- NVIDIA `nvidia/Gemma-4-26B-A4B-NVFP4` 모델 카드는 NVFP4 체크포인트 사용 경로를 vLLM 중심으로 안내한다.
- SGLang Gemma4 문서는 Gemma4 사용 시 `sglang` main/gemma4 계열 설치와 Gemma4용 parser 옵션을 요구한다.
- DGX 현재 설치는 `sglang 0.5.12`, `transformers 5.6.0`, native venv 기반이다.
- parser 옵션(`--reasoning-parser gemma4 --tool-call-parser gemma4`)을 추가해 재기동해도 `<pad>` 반복이 해소되지 않았다.
- SGLang 로그상 ModelOpt NVFP4 checkpoint로 감지되고 `modelopt_fp4`로 로드되지만, direct generation이 실패한다.

## 재현 결과

Direct chat 호출:

```bash
curl -s http://127.0.0.1:30000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer EMPTY' \
  -d '{"model":"gemma-4-26b-a4b-nvfp4","messages":[{"role":"user","content":"한국어로 한 문장만 답하세요. 실손보험이란 무엇인가요?"}],"max_tokens":128,"temperature":0}'
```

관찰 결과:

- response status는 성공이다.
- `content`는 `<pad><pad>...` 반복이다.
- `finish_reason`은 `length`이다.
- RAG 평가에서도 12개 문항 모두 citation-only 또는 본문 없는 답변으로 실패했다.

## 적용 조치

### Repository code

- `src/config.py`
  - `SGLANG_DISABLED_MODELS` 설정 추가.
  - 기본값: `gemma-4-26b-a4b-nvfp4`.
- `src/llm/factory.py`
  - 비활성 SGLang 모델을 후보 목록에서 제외.
  - 명시적으로 `build_llm(..., provider="sglang")`를 호출해도 RuntimeError로 차단.
  - Gemma4 metadata를 `disabled` 상태로 변경.
- `scripts/eval_large_model_rag.py`
  - 기본 평가 대상의 hardcoded Gemma4 포함을 제거.
  - 기본값은 설정된 SGLang 후보 모델 기준으로 동작.
- `tests/test_llm_factory.py`
  - 비활성 SGLang 모델이 UI 후보에서 숨겨지고 명시 호출도 거부되는지 테스트 추가.
- `docs/82_LARGE_MODEL_RAG_EVAL_PLAN.md`
  - Gemma4는 기본 평가 후보가 아니라 별도 실험 대상으로 문서화.

### DGX operational wrapper

- `/srv/ai-ops/bin/switch-sglang-model`
  - 기본 상태에서 `gemma-4-26b-a4b-nvfp4` 전환을 exit code `4`로 차단.
  - 명시적 실험이 필요하면 `SGLANG_ALLOW_UNVALIDATED_MODELS=true`를 붙여 강제로 시도할 수 있게만 남겨두었다.

## 현재 운영 상태

- 활성 SGLang 모델: `gpt-oss-20b`
- `/srv/ai-ops/bin/check-sglang-local`: PASS
- `gemma-4-26b-a4b-nvfp4`: SGLang 기본 후보에서 제외

## 후속 해결 경로

Gemma4를 실제 운영 후보로 되살리려면 다음 중 하나가 필요하다.

1. NVIDIA NVFP4 모델 카드가 안내하는 vLLM 경로를 별도 provider로 검증한다.
2. SGLang main/gemma4 계열과 요구 transformers commit 조합을 별도 venv에서 재검증한다.
3. NVFP4가 아닌 SGLang 검증 완료 Gemma4 checkpoint를 새로 확보한다.
4. direct chat에서 `<pad>` 반복 없이 한국어 단문 응답이 정상 생성되는 것을 먼저 통과 조건으로 삼는다.

Gemma4가 이 direct generation gate를 통과하기 전에는 RAG 평가나 Streamlit 운영 후보에 넣지 않는다.

## 검증 명령

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
pytest tests/test_llm_factory.py tests/test_large_model_eval.py -q
pytest -q
/srv/ai-ops/bin/switch-sglang-model gpt-oss-20b
/srv/ai-ops/bin/check-sglang-local
/srv/ai-ops/bin/switch-sglang-model gemma-4-26b-a4b-nvfp4
```

기대 결과:

- pytest 통과
- `gpt-oss-20b` switch/check 통과
- Gemma4 switch는 기본 상태에서 차단 메시지와 함께 실패
