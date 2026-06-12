# 앱 기동 기본 모델 변경 보고서

## 1. 목적

`docs/225_GENERAL_QUERY_LLM_MODEL_SELECTION_REPORT.md`의 보정본 OCR 기반 일반 질의 평가 결과에 따라 앱 기동 및 기본 모델 선택 경로를 `qwen3-next-80b-a3b-instruct-fp8` 중심으로 정리했다.

## 2. 변경 사항

- FastAPI `/api/system/models`
  - 로컬 기본 모델 우선순위를 `SGLang -> vLLM -> Ollama`로 변경했다.
  - SGLang 기본 모델이 사용 가능하면 `sglang:qwen3-next-80b-a3b-instruct-fp8`가 로그인 화면과 인증 후 모델 선택 기본값이 된다.
- Chat API
  - 요청에 모델이 없을 때 Ollama fallback이 아니라 `sglang:{SGLANG_DEFAULT_MODEL}`를 사용한다.
- Claim calculation API
  - 요청에 모델이 없을 때 vLLM 기본값이 아니라 `sglang:{SGLANG_DEFAULT_MODEL}`를 사용한다.
- Frontend SPA
  - localStorage에 모델 선택값이 없을 때 fallback 기본값을 `sglang:qwen3-next-80b-a3b-instruct-fp8`로 변경했다.
  - Qwen3 Next 80B instruct 표시 라벨을 추가하고 번들 `frontend/dist/app.min.js`를 재빌드했다.
- DGX 운영 wrapper
  - `ops/bin/insurance-rag-common`, `ops/bin/insurance-rag-up`의 FastAPI + SPA 기동 기본값을 `qwen3-next-80b-a3b-instruct-fp8`로 변경했다.
- 환경/운영 스크립트
  - `.env.example`, `scripts/prepare_offline_assets.py`의 기본 모델 설정을 평가 결론과 맞췄다.
  - vLLM 기본 후보는 이미지 인식 후보인 `gemma-4-31b-it-nvfp4`로 축소했다.
- Streamlit legacy 경로
  - 현재 정식 앱은 FastAPI + SPA이므로 Streamlit UI 파일은 기본 모델 변경 대상으로 보지 않는다.
  - Streamlit 관련 코드는 명시 요청이 없는 한 앞으로 업데이트하지 않는다.

## 3. 80B Thinking 모델이 낮게 평가된 이유

`qwen3-next-80b-a3b-thinking-fp8`는 더 많은 추론 토큰을 쓰는 모델이지만, 이번 40문항 RAG 평가는 자유 추론 능력보다 근거 문서에서 필요한 약관 용어, 숫자, 조항 표현을 정확히 회수하고 짧게 답하는 능력을 더 강하게 본다.

낮은 평가의 주요 원인은 다음과 같다.

- 문제 유형 부적합
  - 보험 약관 RAG에서는 긴 사고 과정보다 검색 근거에 있는 정답 요소를 빠짐없이 보존하는 것이 중요하다.
  - Thinking 모델의 추가 추론은 정답 요소 보존보다 설명 구조 확장으로 이어질 수 있다.
- 출력 형식 비용
  - Thinking 모델은 답변이 더 장식적이거나 구조화가 과해지는 경향이 있었다.
  - 자동 채점에서는 필수 표현이나 숫자가 빠지면 긴 설명이 있어도 실패로 처리된다.
- 내부 추론 제어 부담
  - 이 프로젝트는 과거 thinking 출력의 `<think>`/내부 추론 노출 문제를 별도 패치로 다뤘다.
  - 필터링과 reasoning mode 제어는 안정성 비용을 만들며, 일반 질의 기본값에는 불리하다.
- RAG grounded answer와 reasoning answer의 차이
  - 이번 평가는 모델의 독립 추론이 아니라 보정본 OCR 검색 결과에 근거한 grounded answer 품질 평가다.
  - 근거 기반 답변에서는 Instruct 모델이 더 직접적이고 채점 기준에 맞는 응답을 생성했다.

따라서 Thinking 모델은 "더 똑똑한 일반 기본값"이 아니라, 사용자가 명시적으로 reasoning mode를 켜는 실험/특수 경로로만 남기는 것이 맞다.

## 4. 검증

DGX 기준 검증:

```bash
.venv/bin/python -m pytest tests/test_api_auth_system.py tests/test_api_chat_stream.py tests/test_api_claim_calculation.py tests/test_llm_factory.py -q
node --test tests/test_frontend_model_selection_sync.mjs
.venv/bin/python -m py_compile src/api/routes/system.py src/api/routes/chat.py src/api/routes/claim.py scripts/prepare_offline_assets.py
bash -n ops/bin/insurance-rag-common ops/bin/insurance-rag-up
git diff --check -- .env.example frontend/js/pages/chat.js frontend/dist/app.min.js scripts/prepare_offline_assets.py ops/bin/insurance-rag-common ops/bin/insurance-rag-up src/api/routes/system.py src/api/routes/chat.py src/api/routes/claim.py tests/test_api_auth_system.py tests/test_api_chat_stream.py tests/test_api_claim_calculation.py tests/test_frontend_model_selection_sync.mjs
```

결과:

- Python 테스트: `50 passed, 1 warning`
- Node 테스트: `2 passed`
- Python compile: 통과
- `git diff --check`: 통과

## 5. 남은 주의점

- `qwen3-next-80b-a3b-instruct-fp8`는 일반 질의 품질이 가장 좋지만 메모리 점유가 크다. 앱 기동 시 다른 대형 모델 서버와 동시에 올리지 않는 운영 규칙이 필요하다.
- `gemma-4-31b-it-nvfp4`는 기본 답변 모델이 아니라 이미지 인식 후보로 보존한다.
- `qwen3-next-80b-a3b-thinking-fp8`는 기본 후보에서 비활성화하되, reasoning 비교나 별도 실험이 필요할 때만 명시적으로 다룬다.
