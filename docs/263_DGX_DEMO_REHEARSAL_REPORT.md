# 263. DGX 사내 시연 리허설 보고서

작성일: 2026-07-05

## 목적

DGX에서 LLM 서버와 FastAPI + SPA 앱을 기동한 뒤, 사내 시연에 가까운 실무 사용 흐름을 API 기준으로 검증했다. 운영 사용자 비밀번호는 알 수 없어 live 사용자 파일은 변경하지 않았고, 별도 포트의 임시 사용자/임시 DB 인스턴스로 기능 흐름을 검증한 뒤 임시 앱 세션은 종료했다.

## 시나리오 설계

1. 운영 상태 확인
   - DGX 접속, wrapper 상태, 앱/LLM 포트, 모델 노출 확인
2. 일반 사용자 흐름
   - 로그인
   - 모델 목록 확인
   - 도수치료 보험금 계산
   - 계산 세션에서 후속 질문
   - 일반 RAG 질의
   - 세션 목록 및 내보내기
   - 로그아웃
3. 관리자 읽기 전용 흐름
   - 관리자 로그인
   - 시스템 요약
   - 사용자 목록
   - GraphDB sync 상태

## 실행 환경

- DGX host: authorized internal DGX host
- 운영 앱: `127.0.0.1:18080`, tmux `insurance-rag-api`
- LLM 서버: `127.0.0.1:30000/v1`, tmux `sglang-local`
- 모델: `qwen3-next-80b-a3b-instruct-fp8`
- 검증용 임시 앱: `127.0.0.1:18081`, tmux `insurance-rag-demo-api`
  - 검증 후 종료함.
  - 임시 사용자/DB는 `/tmp` 경로를 사용했으며 live `users.json`은 수정하지 않음.

## 결과 요약

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| 운영 wrapper 상태 | 통과 | `insurance-rag-status --json` 결과 `ok=true` |
| 운영 앱 health | 통과 | `api_health=ok`, `api_models=ok` |
| SGLang | 통과 | `/v1/models`에 `qwen3-next-80b-a3b-instruct-fp8` 노출 |
| Ollama | 통과 | `ollama=ok` |
| vLLM | 주의 | 현재 시연 경로가 SGLang이므로 `warn`은 예상 상태 |
| SPA shell | 통과 | `/` 응답 및 `#app` root 확인 |
| 일반 사용자 로그인 | 통과 | 임시 `demo_user` 인증 성공 |
| 보험금 계산 | 통과 | `MX122` 도수치료 150,000원 -> 지급 105,000원, 공제 45,000원 |
| 계산 후속 질문 | 통과 | "보상하지 않는다면" 후속 질문 -> 예상 지급 0원 |
| 일반 RAG 질의 | 통과 | 3대비급여 항목 질의 final 응답, source 4건 |
| 세션/내보내기 | 통과 | 일반 질의 2 messages, 계산 세션 4 messages, sources 포함 |
| 관리자 시스템 요약 | 통과 | chunks, graph, relational, users 및 3개 인덱스 확인 |
| 관리자 사용자 목록 | 통과 | 임시 사용자 2명 조회 |
| GraphDB 상태 | 통과 | available=true, nodes 545,223, edges 46,241 |

## 확인된 주의점

- 기존 live 운영 계정은 `testAdmin`, `koreaben777`, `dani`가 존재하지만 비밀번호는 확인하지 않았다.
- 공개 테스트 fixture 계정인 `user/user1234`, `admin/admin1234`는 DGX live 운영 사용자 파일에서는 실패했다. 실제 사내 시연 전에 사용할 계정의 비밀번호를 별도 확인하거나 명시적으로 reset해야 한다.
- 도수치료 계산은 표준코드 `MX122` 없이 항목명만 입력하면 `blocked_missing_info`로 보류된다. 이는 현재 정책상 정상 보류로 보이며, 자동 산정 시연에는 코드 또는 확정 후보 선택 흐름이 필요하다.
- SSE 클라이언트가 `done` 이벤트 직후 연결을 끊으면 서버의 후속 세션 저장이 취소될 수 있다. 실제 프론트엔드처럼 스트림 EOF까지 읽는 방식에서는 세션 저장과 export가 정상 확인됐다.

## 현재 상태

사내 시연용 운영 경로는 준비되어 있다.

```bash
ssh -N -L 18080:127.0.0.1:18080 <authorized-dgx-user>@<dgx-host>
```

브라우저:

```text
http://localhost:18080
```

DGX 상태:

```text
tmux: insurance-rag-api, sglang-local
app: 127.0.0.1:18080
llm: 127.0.0.1:30000/v1
model: qwen3-next-80b-a3b-instruct-fp8
```
