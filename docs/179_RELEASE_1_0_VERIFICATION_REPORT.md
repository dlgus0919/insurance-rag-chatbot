# 179. Release 1.0 Verification Report

## 목적

DGX Spark 메인 저장소 기준 현재 버전을 `정식 1.0`으로 정의할 수 있는지 검토하고, 검증 근거와 제외 범위를 고정한다.

## 1.0 포함 범위

1. FastAPI + SPA 기반 앱 기동
2. 로그인/권한 기반 일반 사용자 및 관리자 사용 흐름
3. BM25 + Chroma + RRF + reranker 기반 하이브리드 RAG
4. SQLite GraphDB 기반 구조화 근거 및 review path
5. 보험금 계산 deterministic pipeline
6. 관리자 통계/시스템 상태/검색 진단 연결
7. DGX 운영 wrapper
   - `insurance-rag-up`
   - `insurance-rag-status`
   - `insurance-rag-desktop-launcher`
8. 로컬 LLM provider 선택
   - SGLang
   - vLLM
   - Ollama
9. Qwen Thinking 포함 신규 대형 LLM 기동 경로

## Qwen Thinking 기동 검증

검증 모델:

```text
qwen3-next-80b-a3b-thinking-fp8
```

기동 명령:

```bash
/srv/ai-ops/bin/insurance-rag-up --replace --provider sglang --model qwen3-next-80b-a3b-thinking-fp8
```

확인 결과:

```text
app: http://127.0.0.1:18080 ready
sglang: http://127.0.0.1:30000/v1 ready
/api/system/models default: sglang:qwen3-next-80b-a3b-thinking-fp8
/v1/models served model: qwen3-next-80b-a3b-thinking-fp8
```

`insurance-rag-status` 결과:

- `api_health`: ok
- `api_models`: ok
- `sglang`: ok
- 주요 BM25/Chroma index: ok
- GraphDB: ok
- standard code DB: ok
- users.json: ok

`vllm`은 동시에 띄우지 않았기 때문에 `warn`으로 표시된다. 현재 검증 대상이 SGLang Qwen Thinking 경로이므로 blocking 결함으로 보지 않는다.

## Qwen Thinking 응답 정규화

발견된 문제:

- Thinking 계열 모델이 내부 reasoning 문장과 `</think>` 토큰을 사용자 응답에 노출할 수 있었다.

조치:

- non-stream 응답은 `</think>` 이후의 최종 답변만 반환한다.
- stream 응답은 `</think>`가 관측될 때까지 출력을 보류한 뒤 최종 답변만 방출한다.
- GPT-OSS Harmony final-channel gating과 Nemotron thinking 비활성화 경로는 유지했다.

Live 검증 결과:

```text
visible output: 정상입니다.
reasoning leak check: true
```

## 회귀 테스트

DGX 메인 저장소에서 실행:

```bash
pytest tests/test_openai_compatible_client.py tests/test_llm_factory.py -q
pytest tests/ -q
```

결과:

```text
28 passed
548 passed, 3 warnings
```

경고는 passlib `crypt` deprecation 및 Pillow `getdata` deprecation으로, 이번 1.0 판단의 기능 실패는 아니다.

DGX 메인 저장소에는 현재 frontend `.mjs` 테스트 파일이 없어서 Node test는 실행 대상이 없었다.

## 운영 절차

CLI 기준 1.0 운영 절차:

```bash
/srv/ai-ops/bin/insurance-rag-up
/srv/ai-ops/bin/insurance-rag-status
```

모델 지정 예시:

```bash
/srv/ai-ops/bin/insurance-rag-up --replace --provider sglang --model qwen3-next-80b-a3b-thinking-fp8
```

DGX 데스크톱 사용자는 설치된 `.desktop` 아이콘을 더블클릭해 LLM 선택 창에서 동일한 기동 흐름을 사용할 수 있다.

Mac 사용자는 필요 시 터널을 연다.

```bash
ssh -N -L 18080:127.0.0.1:18080 ai-hang@100.88.5.57
```

## 1.0 제외 범위

다음 항목은 후속 확장 과제이며 1.0 blocking 결함으로 보지 않는다.

1. `gpt-oss-120b` 다운로드 완료 및 smoke 검증
2. GGUF Llama 70B의 Ollama/llama.cpp OpenAI-compatible 편입
3. 모델별 보험 RAG 품질/속도 정량 비교
4. 운영 환경에서 다중 사용자 부하 테스트
5. 외부 배포 패키징 또는 사내 SSO 연동

## 최종 판단

현재 DGX 메인 저장소 기준으로 다음 조건을 충족했다.

- Qwen Thinking 서버가 실제 기동된다.
- 앱이 해당 SGLang 서버를 기본 local LLM으로 인식한다.
- Thinking 계열 내부 reasoning 문장 노출을 차단했다.
- 전체 Python 회귀 테스트가 통과했다.
- 운영 wrapper와 데스크톱 launcher를 통해 1.0 수준의 단순 기동 흐름이 제공된다.

따라서 현재 버전은 `정식 1.0`으로 정의할 수 있다. 단, 위 제외 범위는 1.1 이후 모델 확장/운영 안정화 과제로 관리한다.
