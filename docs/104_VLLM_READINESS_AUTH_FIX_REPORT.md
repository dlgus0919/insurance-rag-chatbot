# vLLM Readiness/Auth Mismatch 로그인 지연 수정 보고서

본 보고서는 Streamlit 로그인 버튼 클릭 후 로딩이 장시간 지속되는 현상을 해결하기 위해 vLLM 서버의 인증 헤더 mismatch 문제를 진단하고 조치한 내역을 정리한다.

---

## 1. 배경 및 문제 상황
- **증상**: Streamlit 로그인 후 대형 로컬 모델 로딩이 완료되었음에도 불구하고 대기 화면이 장시간 지속되며 로그인이 정상적으로 완료되지 않음.
- **원인**:
  - Gemma4 vLLM 서버가 기동될 때 보안을 위해 API Key(기본값 `EMPTY`)를 통한 Bearer 인증 요구 정책을 적용하고 있었으나, 모델의 준비 완료 여부를 검사하는 Readiness Probe들이 인증 헤더 없이 `/v1/models` 엔드포인트를 호출하여 `401 Unauthorized`를 반환받음.
  - 이로 인해 이미 vLLM 모델이 정상 기동되어 있음에도 불구하고 클라이언트는 "모델이 아직 준비되지 않았다"고 판단하여 무한 대기하거나 재전환 동작을 유발함.

---

## 2. 해결 방안 및 수정 내역

### 가. 런타임 운영 스크립트 수정 (Non-Git)
> [!NOTE]
> 해당 파일은 저장소(Git) 관리 대상 외 파일로, 원격 DGX Spark 서버 환경에서 직접 수정 및 배포를 완료하였습니다.

- **대상 파일**: `/srv/ai-ops/bin/switch-vllm-model`
- **수정 요약**:
  1. 스크립트 상단에 `VLLM_API_KEY="${VLLM_API_KEY:-EMPTY}"` 환경 변수를 기본값과 함께 정의.
  2. vLLM 서버 실행 명령(tmux 내)에 `--api-key "$VLLM_API_KEY"` 옵션을 명시적으로 지정하여 기동되도록 구성.
  3. 모든 `/v1/models` curl 호출에 `-H "Authorization: Bearer $VLLM_API_KEY"` 헤더 추가.
  4. `/v1/chat/completions` 테스트 시 사용되던 하드코딩된 `Bearer EMPTY`를 `$VLLM_API_KEY` 환경 변수를 사용하도록 변경.

### 나. 저장소 소스 코드 수정
- **대상 파일**: [streamlit_app.py](file:///srv/shared/projects/insurance-rag-chatbot/src/ui/streamlit_app.py)
  - `_served_models` 함수가 `api_key` 인자를 받도록 변경하고, HTTP GET 요청 시 `Authorization: Bearer <API_KEY>` 인증 헤더를 추가하도록 수정함.
  - `_ensure_selected_large_model_ready` 내에서 대형 모델 검사 시 프로바이더에 따라 `config.VLLM_API_KEY` 또는 `config.SGLANG_API_KEY`를 `_served_models`에 넘겨주도록 변경하여, 이미 기동되어 서빙 중인 모델이 존재할 경우 스크립트 재호출 없이 즉시 판단하고 넘어가도록 개선.
- **대상 파일**: [factory.py](file:///srv/shared/projects/insurance-rag-chatbot/src/llm/factory.py)
  - `_served_models_for_endpoint`가 `api_key`를 넘겨받아 `Authorization` 헤더를 태우도록 파라미터 및 로직 추가.
  - `_available_vllm_models` 및 `_available_sglang_models` 호출 시 각각 `config.VLLM_API_KEY` 및 `config.SGLANG_API_KEY`를 인자로 넘겨주도록 연동.
- **대상 파일**: [test_llm_factory.py](file:///srv/shared/projects/insurance-rag-chatbot/tests/test_llm_factory.py)
  - `_served_models_for_endpoint` 함수의 시그니처 변경에 따라, 테스트 코드 내 monkeypatch 모킹 람다 함수가 `api_key` 인자를 허용하도록 수정 (`lambda endpoint, api_key=None: ...`).

---

## 3. 검증 결과

### 가. 수동 엔드포인트 인증 검증 (curl)
원격 DGX Spark 서버에서 직접 포트 30001 엔드포인트에 대한 인증 처리를 검증한 결과는 다음과 같다.

- **인증 헤더가 없을 때 (401 Unauthorized 기대)**:
  ```bash
  $ curl -s -o /tmp/noauth.out -w '%{http_code}\n' http://127.0.0.1:30001/v1/models
  401
  ```
  -> **정상 동작 확인** (비인증 접근 시 401 차단)

- **정상 인증 헤더 `Bearer EMPTY` 포함 시 (200 OK 및 모델 목록 반환 기대)**:
  ```bash
  $ curl -s -o /tmp/auth.out -w '%{http_code}\n' -H 'Authorization: Bearer EMPTY' http://127.0.0.1:30001/v1/models
  200
  ```
  -> **정상 동작 확인** (정상 인증 시 200 OK와 함께 Gemma4 모델 ID 및 상세 속성 반환)

### 나. 자동화 테스트 결과 (pytest)
- **테스트 명령**: `pytest -q`
- **결과**: `304 passed, 3 warnings in 2.82s`
  - 수정된 UI 로직 및 LLM 팩토리 로직을 포함하여, 전체 304개의 테스트 스위트가 모두 차단 없이 통과 완료됨.

### 다. Streamlit 동작 검증
- `prepare_streamlit_runtime.sh --run-streamlit --replace` 실행 후, 로컬 터널을 열어 브라우저로 접속한 결과:
  - 이미 vLLM 기반 Gemma4 모델이 백그라운드에 로드되어 활성화되어 있는 상태이므로, 로그인 시도 시 `switch-vllm-model`이 중복 실행되거나 시간 초과 대기하지 않고 **수 초 내 즉시 로그인을 통과**하여 메인 화면으로 이동함을 검증 완료함.
