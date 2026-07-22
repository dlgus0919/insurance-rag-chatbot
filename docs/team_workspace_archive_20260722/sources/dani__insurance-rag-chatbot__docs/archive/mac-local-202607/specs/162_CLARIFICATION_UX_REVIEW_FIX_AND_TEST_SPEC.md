# 162 Clarification UX Review Fix and Test Spec

## 1. 목적

이 문서는 `115_CLARIFICATION_UX_IMPLEMENTATION_SPEC.md`를 바탕으로 구현된 명확화 UX를 리뷰한 뒤 발견된 보완 사항을 정리한 추가 개발 지시서다.

Antigravity는 아래 항목을 수정/보완한 뒤, 명확화 UX가 실제 브라우저 테스트에서 검증되도록 만들어야 한다.

## 2. 현재 리뷰 결과 요약

명확화 UX 핵심 구현은 대부분 들어가 있다.

확인된 구현:
- `frontend/js/pages/chat.js`
  - 명확화 버튼 표시
  - 선택값 요약 칩
  - 선택 초기화
  - 자주 쓰는 조건 프리셋
  - synthetic selection
  - query 재작성
  - 자동 재검색
- `frontend/css/chat.css`
  - 명확화 버튼/칩/프리셋 스타일
- `src/api/schemas/chat.py`
  - `clarification: dict = Field(default_factory=dict)` 추가
- `src/api/routes/chat.py`
  - audit detail에 `clarification` 기록 추가
- `tests/e2e/chat.spec.js`
  - 명확화 버튼 선택 후 재검색 테스트 일부 추가

하지만 아래 문제가 남아 있어 아직 완료 상태로 판단할 수 없다.

## 3. 반드시 수정해야 할 문제

### 3.1 Playwright E2E 로그인 실패

현재 E2E 테스트는 모두 로그인 단계에서 실패한다.

실패 위치:
- `tests/e2e/chat.spec.js`

실패 현상:
```text
Expected: /chat
Received: /login
사용자명 또는 비밀번호가 올바르지 않습니다.
```

현재 테스트는 다음 계정으로 로그인한다.

```js
await page.fill('#lid', 'user');
await page.fill('#lpw', 'user1234');
```

하지만 테스트 서버에서 해당 계정이 보장되지 않는다.

#### 수정 요구

E2E 테스트가 실행될 때 항상 로그인 가능한 테스트 계정을 사용하도록 만들어야 한다.

권장 방식:
1. 테스트 전용 `users.json` fixture를 만든다.
2. Playwright webServer 실행 시 `USERS_JSON_PATH`를 fixture 파일로 지정한다.
3. fixture에는 `user / user1234` 또는 테스트 코드와 일치하는 계정을 넣는다.

대상 파일 후보:
- `playwright.config.js`
- `tests/e2e/fixtures/users.json`
- 필요 시 `tests/e2e/chat.spec.js`

#### 구현 방향 A: fixture 파일 사용

`tests/e2e/fixtures/users.json` 추가 예:

```json
{
  "version": 1,
  "users": [
    {
      "username": "user",
      "password_hash": "<pbkdf2_sha256 hash for user1234>",
      "role": "employee",
      "display_name": "테스트 사용자",
      "created_at": "2026-06-01T00:00:00+00:00",
      "password_updated_at": "2026-06-01T00:00:00+00:00",
      "email": null,
      "status": "active",
      "updated_at": "2026-06-01T00:00:00+00:00",
      "last_login": null
    }
  ]
}
```

주의:
- password hash는 반드시 현재 `src/auth/users.py`의 `pbkdf2_sha256.verify()`가 통과하는 값이어야 한다.
- 직접 평문 비밀번호를 JSON에 넣으면 안 된다.
- hash 생성은 로컬 Python helper 또는 기존 `users.add_user()`를 이용해도 된다.

`playwright.config.js`의 webServer command 예:

```js
webServer: {
  command: 'USERS_JSON_PATH=tests/e2e/fixtures/users.json API_COOKIE_SECURE=false API_RATE_LIMIT_DISABLED=true .venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000',
  url: 'http://127.0.0.1:8000/api/health',
  reuseExistingServer: !process.env.CI,
  timeout: 30000,
}
```

#### 구현 방향 B: 테스트 시작 전 계정 생성 스크립트

fixture hash 관리가 번거롭다면 테스트 전용 사용자 파일을 생성하는 스크립트를 둘 수 있다.

예:
- `scripts/create_e2e_users.py`

동작:
- `USERS_JSON_PATH`가 가리키는 파일에 `user / user1234` 계정 생성
- 이미 있으면 재생성하지 않음

단, Playwright webServer command가 너무 복잡해지지 않게 유지한다.

## 4. 명확화 UX 테스트 보완

현재 추가된 테스트는 `MRI 맞음 + 5세대 실손 + 통원 + 재검색`만 확인한다.

115번 명세에서 필수로 요구한 아래 테스트가 부족하다.

반드시 추가해야 한다.

### 4.1 선택값 요약 칩 테스트

대상 파일:
- `tests/e2e/chat.spec.js`

시나리오:
1. mock SSE `graph` 이벤트로 `term_correction_candidates`, `ambiguous_terms`를 내려준다.
2. `.msg-clarifications`가 표시되는지 확인한다.
3. 초기 summary에 `아직 선택된 조건이 없습니다.`가 표시되는지 확인한다.
4. `MRI 맞음` 클릭 후 summary에 `MRI` 표시 확인
5. `5세대 실손` 클릭 후 summary에 `5세대 실손` 표시 확인
6. `통원` 클릭 후 summary에 `통원` 표시 확인

현재 테스트에 일부 들어가 있으나, locator scope를 clarification block 안으로 제한해야 한다.

권장:
```js
const clarification = page.locator('.msg-clarifications').last();
await expect(clarification.locator('[data-clarify-summary]')).toContainText('MRI');
```

### 4.2 선택 초기화 테스트

신규 테스트를 추가한다.

시나리오:
1. 명확화 block 표시
2. `5세대 실손`, `통원` 선택
3. `선택값으로 다시 검색` 버튼 enabled 확인
4. `선택 초기화` 클릭
5. 선택 버튼에서 `.selected` 제거 확인
6. summary가 `아직 선택된 조건이 없습니다.`로 돌아오는지 확인
7. `선택값으로 다시 검색` 버튼 disabled 확인

검증 예:
```js
await expect(clarification.locator('[data-action="apply-clarification"]')).toBeDisabled();
await expect(clarification.locator('.clarify-option.selected')).toHaveCount(0);
```

### 4.3 프리셋 테스트

신규 테스트를 추가한다.

시나리오:
1. 명확화 block 표시
2. `5세대 + 통원` 프리셋 클릭
3. summary에 `5세대 실손`, `통원` 표시
4. `선택값으로 다시 검색` 버튼 enabled 확인
5. 재검색 버튼 클릭
6. 두 번째 `/api/chat/stream` request payload의 `query`에 아래 문자열 포함 확인
   - `[사용자 명확화]`
   - `5세대`
   - `통원`

주의:
- 프리셋 클릭만으로 자동 재검색하면 안 된다.
- 재검색은 사용자가 `선택값으로 다시 검색`을 눌렀을 때만 발생해야 한다.

### 4.4 synthetic selection 테스트

신규 테스트를 추가한다.

대상 프리셋:
- `도수/충격파 + 5세대 + 통원`

시나리오:
1. 명확화 block 표시
2. `도수/충격파 + 5세대 + 통원` 프리셋 클릭
3. 화면에 `coverage_topic` 원본 버튼이 없어도 summary에 `도수/충격파` 표시 확인
4. 재검색 버튼 클릭
5. 두 번째 request payload `query`에 아래 문자열 포함 확인
   - `도수치료 또는 체외충격파치료`
   - `5세대`
   - `통원`

검증 이유:
- 명세서 115번에서 synthetic selection을 요구했다.
- 화면에 없는 선택값도 query 재작성에 포함되어야 한다.

### 4.5 단일 선택 그룹 테스트

신규 테스트 또는 기존 테스트에 추가한다.

시나리오:
1. `4세대 실손` 클릭
2. `5세대 실손` 클릭
3. `4세대 실손`은 selected 해제
4. `5세대 실손`만 selected 상태

검증:
```js
await expect(fourthBtn).not.toHaveClass(/selected/);
await expect(fifthBtn).toHaveClass(/selected/);
```

### 4.6 복수 선택 그룹 테스트

현재 graph payload로 `증빙 서류` ambiguous term을 내려주는 테스트를 추가한다.

mock:
```json
{
  "plan": {
    "ambiguous_terms": ["증빙 서류"],
    "clarification_questions": ["진료비 영수증, 세부내역서, 진단서 등 어떤 증빙이 있는지 확인해 주세요."]
  }
}
```

시나리오:
1. `영수증` 클릭
2. `세부내역서` 클릭
3. 두 버튼 모두 selected 유지 확인
4. 재검색 query에 두 값 모두 포함 확인

## 5. 프론트 payload 보완

현재 백엔드에는 `ChatRequest.clarification` 필드가 추가되어 있고, audit log에도 기록한다.

하지만 프론트는 재검색 시 `clarification` 값을 보내지 않고 있다.

현재 동작:
- query만 재작성
- `clarification` payload는 `{}` 상태

수정 요구:
- `apply-clarification` 클릭 시 `streamChat()`에 clarification selections를 전달한다.
- `/api/chat/stream` payload에 `clarification` field를 포함한다.

권장 수정:

`streamChat()` signature를 아래처럼 확장한다.

```js
async function streamChat(query, mode = 'general', filters = {}, memo = '', clarification = {}) {
```

payload 구성에 추가:

```js
const payload = {
  query,
  session_id: currentSession,
  mode,
  model: getSelectedModel(),
  top_k: getTopK(),
  temperature: getTemperature(),
  filters,
  index_mode: getIndexMode(),
  clarification,
};
```

명확화 재검색 호출:

```js
const clarification = buildClarificationPayload(selections);
await streamChat(rewrittenQuery, payload.mode, payload.filters, payload.memo, clarification);
```

helper 예:

```js
function buildClarificationPayload(selections) {
  return {
    selections: selections.map((selection) => ({
      group: selection.group,
      label: selection.label,
      value: selection.value,
      display: selection.display,
      raw: selection.raw || '',
    })),
  };
}
```

테스트에서 확인:
```js
expect(chatRequestPayloads[1].clarification.selections).toEqual(
  expect.arrayContaining([
    expect.objectContaining({ group: 'policy_generation', value: '5세대' }),
    expect.objectContaining({ group: 'visit_type', value: '통원' }),
  ])
);
```

## 6. 테스트 안정성 보완

### 6.1 locator scope 제한

현재 테스트는 전역 locator를 많이 사용한다.

예:
```js
const applyBtn = page.locator('[data-action="apply-clarification"]');
```

여러 답변이 쌓이면 동일 버튼이 여러 개 생길 수 있다.

권장:
```js
const clarification = page.locator('.msg-clarifications').last();
const applyBtn = clarification.locator('[data-action="apply-clarification"]');
```

### 6.2 API route 중복 등록 주의

현재 `beforeEach`에서 `/api/chat/stream` route를 등록하고, 명확화 테스트 내부에서 같은 route를 다시 등록한다.

Playwright에서는 나중에 등록한 route가 먼저 적용될 수 있지만, 테스트 의도를 명확하게 하려면 구조를 정리한다.

권장 방식:
- `beforeEach`에는 로그인에 필요한 route만 둔다.
- 각 채팅 테스트에서 필요한 `/api/chat/stream` mock을 별도 등록한다.
- 또는 helper 함수 `mockChatStream(page, handler)`를 만든다.

### 6.3 `test-results/` 정리

현재 `test-results/`가 untracked 상태로 남아 있다.

요구:
- repository에 커밋하지 않는다.
- 테스트 완료 후 삭제하거나 `.gitignore`에 이미 있는지 확인한다.
- 이번 작업 커밋에는 포함하지 않는다.

## 7. 코드 품질 보완

### 7.1 trailing whitespace 제거

현재 `git diff --check` 실패:

```text
tests/e2e/chat.spec.js:62: trailing whitespace.
```

반드시 제거한다.

완료 전 확인:
```bash
git diff --check
```

### 7.2 inline style 제거 권장

현재 `frontend/js/pages/chat.js`에서 action button wrapper에 inline style이 있다.

현재:
```html
<div style="display: flex; gap: 8px; margin-top: 12px;">
```

권장:
- CSS class로 분리한다.

예:
```html
<div class="clarify-actions">
```

`frontend/css/chat.css`:
```css
.clarify-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
```

## 8. 실행해야 할 검증 명령

아래 명령을 모두 실행하고 결과를 보고한다.

### 8.1 백엔드 관련 테스트

```bash
cd /srv/shared/workspaces/dani/insurance-rag-chatbot
.venv/bin/python -m pytest tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py tests/test_graph_review_path_planner.py -q
```

기대:
```text
passed
```

### 8.2 프론트 빌드

```bash
cd /srv/shared/workspaces/dani/insurance-rag-chatbot
npm --prefix frontend run build
```

기대:
```text
Done
```

### 8.3 E2E 테스트

```bash
cd /srv/shared/workspaces/dani/insurance-rag-chatbot
npm run test:e2e -- tests/e2e/chat.spec.js --project=chromium
```

기대:
```text
passed
```

### 8.4 diff check

```bash
cd /srv/shared/workspaces/dani/insurance-rag-chatbot
git diff --check
```

기대:
```text
출력 없음
```

## 9. 완료 기준

아래 항목을 모두 만족해야 완료로 본다.

- E2E 로그인 fixture가 안정적으로 동작한다.
- `tests/e2e/chat.spec.js`가 chromium에서 통과한다.
- 명확화 버튼 선택 후 query 재작성 및 재검색이 검증된다.
- 선택값 요약 칩이 검증된다.
- 선택 초기화가 검증된다.
- 프리셋 선택이 검증된다.
- synthetic selection이 검증된다.
- 단일 선택 그룹 동작이 검증된다.
- 복수 선택 그룹 동작이 검증된다.
- 재검색 request payload에 `clarification.selections`가 포함된다.
- 백엔드 관련 테스트가 통과한다.
- `npm --prefix frontend run build`가 통과한다.
- `git diff --check`가 통과한다.
- `test-results/`는 커밋 대상에 포함하지 않는다.

## 10. 보고 형식

작업 완료 후 아래 형식으로 보고한다.

```md
## 변경 파일
- ...

## 구현 내용
- ...

## 테스트 결과
- `.venv/bin/python -m pytest ... -q`: passed
- `npm --prefix frontend run build`: passed
- `npm run test:e2e -- tests/e2e/chat.spec.js --project=chromium`: passed
- `git diff --check`: passed

## 남은 리스크
- ...
```
