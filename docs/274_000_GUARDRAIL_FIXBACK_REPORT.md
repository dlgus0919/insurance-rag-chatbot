# 000 개발 원칙 수정 회송 구현 보고서

- 작성일: 2026-07-18
- 기준: `cd82f9e2ff0fcd051847ff1bd27b74e46a9e884d` 기반 DGX 격리 작업공간
- 범위: 계산 권위, 출처 권위, 후보 생성 정책, 온톨로지 승인 경계, 격리 smoke 안전장치, no-match 최종 회송

## 결론

원시 항목명은 후보 탐색에만 사용하고, 지급 판단은 사용자 선택 표준코드 또는 승인된 구조화 근거가 있을 때만 수행하도록 경계를 고정했습니다. 활성 지식과 운영 데이터에는 이번 작업에서 쓰기 작업을 하지 않았습니다.

## 000 원칙 보완

### 1. 원시 명칭과 지급 판단 분리

- `도수치료`만 입력하면 표준코드 후보가 있으면 목록과 `needs_code_selection`을 반환합니다. 후보 조회가 비어 있어도 동일하게 코드 확인·검토 상태만 남기며, 공제액·예상 지급액은 `null` 또는 `산정 보류`로 표시합니다.
- 후보에서 선택하거나 직접 입력한 `MX122`는 구조화 `input_code`로 처리합니다. 4세대·통원·비급여 500,000원·산정특례 미확인에서는 승인된 active rule로 공제 150,000원, 예상 지급 350,000원을 산정하고 연간 한도·횟수·증빙 검토를 유지합니다.
- `51040`을 선택하면 해당 구조화 행의 면책·제외 결과를 유지합니다. 정확 룰이 없을 때만 `needs_rule_approval`으로 남깁니다.

### 2. 처리 정책 외부화

- MRI/MRA 별칭, 분류 제약, 고위험 분류의 코드 선택 요구를 버전 관리되는 `config/claim_processing_policy.json`으로 이동했습니다.
- 이 처리정책에는 지급률, 공제액, 한도 같은 보험 판단 값을 두지 않습니다.

### 3. 룰 후보 근거 명세 외부화

- 룰 후보 추출기의 고정 chunk ID, 세대, 분류, 치료명과 검토 조건을 `config/claim_rule_candidate_evidence_specs.json`의 evidence spec으로 이동했습니다.
- 금액·비율·한도는 계속 원문 근거에서 파싱하며, 산출물은 실무자 승인 전 `pending` 후보만 생성합니다.

### 4. 탈모 지식 승인 경계

- 활성 지식을 직접 수정하지 않고, 전체 payload와 직접 출처를 담은 교정 후보 artifact를 `pending` 상태로 준비했습니다.
- 과거 append-only 검토 로그는 수정·삭제하지 않았고, 과거 후보가 출처 태그만 가졌던 한계는 artifact의 교정 사유에 명시했습니다.

### 5. 격리 smoke fail-closed

- 격리 smoke는 명시적 격리 루트와 DB·사용자·로그 경로 override가 모두 없으면 실행을 거부합니다.
- 운영 DB·운영 로그를 기본값으로 해석할 수 있는 실행은 허용하지 않습니다.

### 6. 근거 조항 fallback 회귀

- 유효한 5세대 산정특례 후보 근거에 `article`이 없거나 비어 있어도 후보 생성을 중단하지 않고 canonical `source_chunk_id`를 `source_clause`로 기록합니다.
- 해당 fallback은 후보의 pending 권위, 근거 ID, 원문 파싱 비율·금액·한도와 active 적용 경계를 변경하지 않습니다.

### 7. 최종 no-match 및 5세대 fallback 회송

- `match_standard_code()=[]`인 고위험 항목도 처리정책의 코드 선택 요구를 적용합니다. 따라서 원시 명칭과 비급여 금액만으로 active 지급 룰에 도달하지 못합니다.
- 후보가 있는 원시 `도수치료`, 직접 입력한 `MX122`, 직접 입력한 `51040`의 기존 경계는 그대로 유지했습니다.
- 5세대 산정특례 추출기는 유효 chunk의 `article` 누락 시 `source_chunk_id:<chunk_id>`를 남기고 pending 후보를 생성합니다.

## 운영 데이터와 승인 경계

- `data/ontology/concepts.json`, active manifest, GraphDB, BM25/Chroma 인덱스, 후보 검토 로그는 변경하지 않았습니다.
- active candidate apply, GraphDB rebuild, 재인덱스, 보호 메인 반영, 앱·LLM 서비스 재시작을 수행하지 않았습니다.
- 기존 `LOGIN_FAILED` 감사 이벤트 2건은 보존했고, 이번 검증으로 운영 DB·로그에 쓰기 작업을 하지 않았습니다.
- 등록·provenance화되지 않은 외부 자료는 판단 근거로 사용하지 않고 교차검증 참고로만 취급합니다.

## 검증

- 실패 우선 신규 회귀 2건: 수정 전 `2 failed`(후보 없는 도수치료의 금액 산정, 5세대 누락 조항 `KeyError`)에서 수정 후 `2 passed`로 전환
- focused pytest: 172 passed, 1 warning
- 전체 pytest: 1002 passed, 3 warnings. DB·사용자·로그 경로는 임시 루트로 강제했고 종료 시 제거
- 온톨로지 동기화 검사: 통과, concepts=55, aliases=126, candidate_aliases=18, retrieval_rules=5
- `git diff --check` 및 `data/ontology/concepts.json`·active rule manifest 비변경 검사: 통과
- Playwright 격리 쓰기 E2E: 1 passed (4.3s). 후보 선택, `MX122` 전달, 공제 150,000원·예상 지급 350,000원, 동일 스레드 후속 질의를 임시 loopback·DB·계정으로 확인
- Playwright 보호 앱 읽기 전용 smoke: 1 passed (2.2s). `18080`에는 health·실행 LLM 상태·로그인 화면 GET만 수행
- 기존 범위의 `node --check frontend/js/pages/chat.js` 및 `npm --prefix frontend run build` 통과 결과는 유지되며, 이번 최종 회송은 프런트엔드 소스를 변경하지 않았습니다.

## 격리 브라우저 E2E와 터널 재사용

### 데이터 경계

- 격리 쓰기 실행은 임시 루트 아래의 대화 DB, 테스트 계정 파일, 로그, Playwright 산출물에만 쓸 수 있습니다. 운영 DB·운영 계정·운영 로그는 경로 검증이 하나라도 빠지면 시작 전에 거부됩니다.
- 표준코드 DB는 별도 `E2E_STANDARD_CODES_DB_PATH`로 명시해야 하며, 격리 모드에서는 SQLite 읽기 전용 연결로만 엽니다. 표준코드 DB 복사본을 만들지 않습니다.
- 보호 앱 `18080`은 아래 읽기 전용 smoke 외의 브라우저 쓰기 검증 대상이 아닙니다.

### DGX 격리 실행

```bash
export E2E_ROOT="$(mktemp -d)"
export E2E_PORT=<isolated-loopback-port>
export E2E_TEST_USERNAME=<runtime-only-test-user>
export E2E_TEST_PASSWORD=<runtime-only-test-password>
export E2E_PLAYWRIGHT_BIN=<playwright-cli>
export E2E_STANDARD_CODES_DB_PATH=<read-only-standard-codes-sqlite>
$PYTHON scripts/run_isolated_frontend_e2e.py \
  --mode isolated-write --root "$E2E_ROOT" --port "$E2E_PORT" --run
```

이 명령은 후보 선택 -> `input_code=MX122` -> 공제 150,000원·예상 지급 350,000원 -> 동일 스레드 후속 일반 질의까지 검증하고, 종료 시 격리 앱 프로세스를 정리합니다. 자격증명 값은 셸 환경에만 두며 코드·문서·로그에 저장하지 않습니다.

### Mac SSH 터널 재사용

DGX에서 같은 환경변수로 `--serve`를 사용해 격리 서버를 유지한 뒤, Mac에서 다음 터널을 엽니다.

```bash
ssh -N -L "$E2E_PORT:127.0.0.1:$E2E_PORT" dgx-codex
```

동일 리비전의 테스트 checkout에서 `E2E_ISOLATED_TARGET=1`, `INSURANCE_RAG_E2E_ALLOW_WRITES=1`, 같은 런타임 테스트 자격증명, `BASE_URL=http://127.0.0.1:$E2E_PORT`, 로컬 임시 `E2E_ARTIFACTS_DIR`를 주입하고 `playwright.isolated.config.js`를 실행하면 같은 시나리오를 터널 URL로 재사용할 수 있습니다. 설정은 loopback이 아니거나 `18080`을 가리키면 즉시 거부합니다.

### 보호 앱 읽기 전용 smoke

```bash
$PYTHON scripts/run_isolated_frontend_e2e.py \
  --mode read-only --base-url http://127.0.0.1:18080 \
  --artifacts-dir "$(mktemp -d)" --run
```

이 모드는 health, 실행 LLM 레이블, 로그인 페이지의 GET만 허용합니다. 쓰기 opt-in, 격리 write 플래그, 테스트 자격증명이 섞이면 fail-closed로 중단합니다. 따라서 사용자가 열어 둔 `localhost:18080` 터널은 운영 관찰용이며, 격리 작업공간의 미반영 코드를 검증한 근거로 사용하지 않습니다.

## 남은 위험과 별도 승인

- 탈모 전체 payload 교정 후보는 실무자 명시 승인 전까지 `pending`이며 active apply 또는 GraphDB rebuild를 해서는 안 됩니다.
- 다음 문서 재인제스트 때 evidence spec의 출처·분류가 실제 문서와 일치하는지 실무자 검토가 필요합니다.
- fail-closed preflight는 격리 브라우저 runner가 테스트 계정 생성과 앱 기동 전에 호출합니다. 회귀 테스트와 실제 격리 E2E에서 모두 통과했습니다.

## 롤백

- 이번 격리 작업공간의 소스·테스트·처리정책·후보 artifact·보고서만 되돌리면 됩니다. 활성 지식과 운영 데이터에는 이번 작업의 쓰기가 없어 데이터 롤백은 필요하지 않습니다.
