# DGX Spark SGLang 전환 C단계 실행 계획 및 Provider UI 확장 설계

작성일: 2026-05-20  
대상 프로젝트: `/srv/shared/projects/insurance-rag-chatbot`  
현재 상태: C단계(SGLang 설치/실행 준비) 진행 중

## 1. 목적

- 현재 handoff 1차 패키지(`llm_stage1_20260519`)를 사용해 DGX Spark에서 로컬 LLM provider를 단계적으로 전환한다.
- 운영 리스크를 최소화하기 위해 **Ollama fallback을 유지**한다.
- 추후 UI 개선으로 모델 드롭다운과 별도로 **LLM Provider(Ollama/SGLang) 드롭다운**을 도입할 수 있도록 설계 기준을 정의한다.

## 2. 현재 기준(변경 전)

- Streamlit 앱의 로컬 모델 경로는 Ollama 중심으로 동작.
- `scripts/eval.py`, `scripts/cli.py`는 Ollama 직접 의존 경로가 남아 있음.
- handoff 1차 패키지에는 다음이 포함됨:
  - `downloads/models/gpt-oss-20b`
  - `downloads/models/Gemma-4-26B-A4B-NVFP4`
  - `downloads/sglang_wheelhouse`
  - 무결성 체크섬 및 전송 가이드

## 3. C단계 실행 체크리스트 (진행 중인 작업)

### C-1) SGLang 런타임 설치

1. venv 생성/활성화
2. 온라인 설치 우선 시도
3. 실패 시 wheelhouse fallback 설치

완료 기준:
- `python -m sglang.launch_server --help` 정상 출력

### C-2) 모델 실행 사전 검증

1. 모델 경로 존재 확인:
   - `/srv/ai-ops/llm/models/gpt-oss-20b`
2. SGLang 서버 기동 테스트:
   - 포트 `30000`
3. OpenAI-compatible endpoint 확인:
   - `/v1/models`
   - `/v1/chat/completions`

완료 기준:
- 테스트 프롬프트 1건 이상 응답 성공

## 4. C단계 이후 즉시 적용할 운영 전환 순서

1. `.env`에서 OpenAI 경로를 SGLang endpoint로 지정
   - `OPENAI_BASE_URL=http://127.0.0.1:30000/v1`
   - `OPENAI_API_KEY=EMPTY`
   - `OPENAI_DEFAULT_MODEL=gpt-oss-20b`
2. `ALLOW_OLLAMA=true` 유지
3. Streamlit 재시작 후 로컬 질의 3건 검증
4. 실패 시 즉시 Ollama 기본 모델로 복귀

## 5. 롤백 정책 (필수)

다음 조건 중 하나라도 발생하면 즉시 롤백:

- 5분 이상 응답 지연이 반복
- 동일 질의 대비 품질 저하가 명확
- 서버 불안정(프로세스 반복 종료, OOM, 5xx 증가)

롤백 방법:

1. SGLang 서버 중지
2. `.env`의 기본 모델/표시를 Ollama 기준으로 복귀
3. Streamlit 재기동
4. 회귀 테스트 3건 재실행

## 6. 추후 UI 확장: Provider 드롭다운 + 모델 드롭다운 분리

## 6.1 목표 UX

- 기존: 모델만 선택
- 변경: **Provider 선택** + **Provider별 모델 선택**

권장 UI:
- `LLM Provider`: `Ollama`, `SGLang(OpenAI-compatible)`
- `Model`: 선택된 Provider에 맞는 후보만 표시

## 6.2 동작 규칙

1. Provider=`Ollama`:
   - 기존 `OLLAMA_CANDIDATE_MODELS` 기반 표시
2. Provider=`SGLang`:
   - `LOCAL_LLM_CANDIDATE_MODELS`(신규 env) 기반 표시
3. 선택값 session state 분리:
   - `selected_provider`
   - `selected_model_by_provider`(provider별 마지막 선택 기억)
4. 잘못된 조합 방지:
   - Provider 변경 시 모델 목록 자동 재로딩
   - 현재 모델이 후보군에 없으면 provider 기본 모델로 강제 교체

## 6.3 환경변수 확장안(추후 코드 반영)

- `LOCAL_LLM_PROVIDER=sglang|ollama`
- `LOCAL_LLM_BASE_URL=http://127.0.0.1:30000/v1`
- `LOCAL_LLM_API_KEY=EMPTY`
- `LOCAL_LLM_MODEL=gpt-oss-20b`
- `LOCAL_LLM_CANDIDATE_MODELS=gpt-oss-20b`
- `ALLOW_OLLAMA=true`

주의:
- 물리 경로(`/models/...`)를 앱 model명으로 직접 노출하지 않는다.
- served model name(논리 이름) 기준으로 앱에서 선택한다.

## 6.4 로그/관측 항목

각 응답 로그에 최소 포함:

- `provider`
- `model`
- `latency_ms`
- `prompt_tokens`/`completion_tokens`(가능 시)
- 오류 시 `error_type`/`error_message`(민감정보 제외)

## 6.5 테스트 범위(추후 코드 반영 시)

1. Provider 변경 시 모델 목록 필터링 테스트
2. 잘못된 provider-model 조합 자동 보정 테스트
3. SGLang 미기동 시 사용자 오류 메시지 테스트
4. Ollama fallback 경로 회귀 테스트

## 7. 권장 운영 원칙

- 1차 운영 기본 모델은 `gpt-oss-20b`로 고정하고 안정화 후 확장.
- `Gemma-4-26B-A4B-NVFP4`는 2차 검증 대상으로 분리.
- 코드 전환(`eval.py`, `cli.py` provider 추상화)은 C단계 안정화 완료 후 진행.

## 8. 완료 정의(이번 단계)

이번 문서 기준 완료 조건:

1. C단계 설치/기동 확인 완료
2. Streamlit에서 SGLang 경유 응답 확인
3. Ollama 롤백 경로 검증
4. Provider 드롭다운 분리 구현을 위한 명세 확정

