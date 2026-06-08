# 187. Release 1.0.3 Llama Ollama Enablement Report

## 목적

`llama-3.3-70b-instruct-q4-k-m` GGUF 모델을 DGX 운영 앱에서 선택하고 기동할 수 있도록 Ollama 경로를 정식 지원했다.

## 변경 사항

- `ops/ollama/llama-3.3-70b-instruct-q4-k-m.Modelfile`
  - DGX GGUF 파일을 기준으로 Ollama 모델을 생성하는 Modelfile을 추가했다.
  - 기본 생성 파라미터에 `num_predict 4096`을 명시했다.
- `ops/bin/insurance-rag-up`
  - Ollama provider로 `llama-3.3-70b-instruct-q4-k-m`을 선택하면, 모델이 아직 Ollama에 등록되지 않은 경우 자동으로 `ollama create`를 수행하도록 추가했다.
- `ops/bin/insurance-rag-desktop-launcher`
  - 다운로드 완료된 Llama GGUF가 존재하면 런처 선택지에 `llama-3.3-70b-instruct-q4-k-m`을 노출하도록 추가했다.
- `ops/bin/insurance-rag-common`
  - 기본 Ollama 후보 목록에 Llama 70B를 포함하고, `OLLAMA_NUM_PREDICT=4096` 기본값을 운영 환경으로 전달하도록 추가했다.
- `src/config.py`
  - `OLLAMA_NUM_PREDICT` 설정을 추가했다.
  - `OLLAMA_CANDIDATE_MODELS`를 환경변수 기반으로 읽도록 변경해 wrapper와 `/api/system/models` 노출 결과가 일치하도록 수정했다.
- `src/llm/ollama_client.py`
  - non-stream/stream 요청 모두 `num_predict`를 전달하도록 수정했다.
  - Ollama가 `:latest` 태그를 붙여 반환하는 모델 이름을 tagless alias와 함께 인식하도록 보강했다.
- `tests/test_ollama_client.py`
  - `num_predict` 전송과 `:latest` alias 처리를 회귀 테스트로 추가했다.

## 검증

실행한 검증:

```bash
timeout 240 .venv/bin/pytest tests/test_ollama_client.py tests/test_llm_factory.py -q
bash -n ops/bin/insurance-rag-common
bash -n ops/bin/insurance-rag-up
bash -n ops/bin/insurance-rag-desktop-launcher
ops/install_ai_ops_wrappers.sh
/srv/ai-ops/bin/insurance-rag-up --replace --provider ollama --model llama-3.3-70b-instruct-q4-k-m
/srv/ai-ops/bin/insurance-rag-status
curl -fsS http://127.0.0.1:18080/api/system/models
curl -fsS http://127.0.0.1:11434/api/generate -H 'Content-Type: application/json' -d '{"model":"llama-3.3-70b-instruct-q4-k-m","prompt":"보험금 청구 안내를 한국어 한 문장으로 답하세요.","stream":false,"options":{"num_predict":128,"num_ctx":4096,"temperature":0.1}}'
```

검증 결과:

- 관련 단위 테스트 `21 passed`
- 런처 선택 목록에 `start|ollama|llama-3.3-70b-instruct-q4-k-m` 노출 확인
- Ollama 등록 완료 모델명:
  - `llama-3.3-70b-instruct-q4-k-m:latest`
- `/api/system/models` 기본 local 모델:
  - `ollama:llama-3.3-70b-instruct-q4-k-m`
- 실제 생성 응답 확인:
  - 한국어 한 문장 응답 정상 반환

## 운영 메모

- 이번 릴리즈의 핵심 조정값은 Ollama 출력 상한 `OLLAMA_NUM_PREDICT=4096`이다.
- Qwen Thinking의 내부 추론 비노출 정책과 관련 경로는 이번 변경에서 수정하지 않았다.
- 첫 `ollama create` 시 40GB GGUF를 Ollama blob 저장소로 복사하므로 수 분이 소요될 수 있다. 이후 재기동은 재생성 없이 기존 manifest를 재사용한다.
