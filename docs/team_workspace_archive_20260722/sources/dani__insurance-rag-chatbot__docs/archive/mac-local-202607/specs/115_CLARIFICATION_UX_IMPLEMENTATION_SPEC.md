# 115 Clarification UX Implementation Spec

## 1. 목적

챗봇 답변 품질을 안정화하기 위해, 질문이 모호할 때 시스템이 감지한 보정 후보와 부족 조건을 사용자가 버튼으로 선택할 수 있게 만든다. 사용자가 버튼을 선택하면 선택값을 원문 질문에 반영해 query를 재작성하고, 같은 채팅 세션에서 자동 재검색/재답변을 수행한다.

예시:
- 사용자가 "엠알아이 보상돼?"라고 질문
- 시스템이 "엠알아이 -> MRI", "실손 세대 필요", "방문 구분 필요"를 감지
- UI가 `MRI 맞음`, `4세대 실손`, `5세대 실손`, `입원`, `통원`, `처방조제` 버튼을 표시
- 사용자가 `MRI 맞음`, `5세대 실손`, `통원`을 선택
- 프론트가 query를 재작성
- 자동으로 `/api/chat/stream`에 재요청
- 최종 답변은 명확화된 조건을 기준으로 생성

## 2. 현재 코드 상태 요약

현재 백엔드는 명확화에 필요한 신호를 이미 일부 생성한다.

관련 파일:
- `src/graph/query_planner.py`
  - `GraphQueryPlan.clarification_questions`
  - `GraphQueryPlan.ambiguous_terms`
  - `GraphQueryPlan.term_correction_candidates`
  - `GraphQueryPlan.normalized_terms`
  - `policy_generation`, `visit_type`, `coverage_topics` 감지
- `src/api/rag_service.py`
  - `graph_result_to_payload()`에서 위 값을 `graph.plan` payload로 프론트에 전달
- `frontend/js/pages/chat.js`
  - `streamChat()`에서 SSE `graph` 이벤트를 수신
  - `renderClarificationHtml(graphResult)`가 현재 명확화 정보를 텍스트/리스트로 표시
  - 아직 버튼 선택, query 재작성, 자동 재검색 로직은 없음
- `frontend/css/chat.css`
  - `.msg-clarifications`, `.clarify-tags` 스타일이 있음
  - 명확화 버튼용 스타일은 추가 필요

## 3. 구현 범위

이번 작업의 목표는 "명확화 UX 완성"이다.

포함:
- 명확화 후보를 버튼으로 렌더링
- 버튼 클릭 시 선택 상태를 UI에 반영
- 선택값으로 query 재작성
- 자동 재검색 실행
- 재검색 결과를 같은 세션에 저장
- 필요한 테스트 추가

제외:
- 신규 RAG 알고리즘 개발
- GraphDB schema 변경
- 보험금 계산 로직 변경
- 모델 서버 실행/종료 자동화
- 관리자 페이지 기능 확장

## 4. 사용자 플로우

### 4.1 최초 질문

사용자가 일반 채팅 모드에서 질문한다.

예:
```text
엠알아이 찍었는데 실손 보상돼?
```

### 4.2 백엔드 응답

`/api/chat/stream` 응답 중 `graph` 이벤트에 다음 정보가 포함될 수 있다.

예상 payload 구조:
```json
{
  "plan": {
    "normalized_terms": {
      "엠알아이": "MRI"
    },
    "term_correction_candidates": [
      {
        "raw": "엠알아이",
        "normalized": "MRI",
        "confidence": 0.72,
        "source": "safe_candidate_rule",
        "reason": "문서 기반 canonical 용어와 유사하지만 자동 확정하지 않는 사용자 입력 표현입니다."
      }
    ],
    "ambiguous_terms": [
      "실손 세대",
      "방문 구분"
    ],
    "clarification_questions": [
      "어느 실손 세대(예: 4세대/5세대) 기준인지 확인해 주세요.",
      "입원/통원/처방조제 중 어떤 방문 구분인지 확인해 주세요."
    ]
  }
}
```

### 4.3 프론트 표시

답변 하단의 `추가 확인 필요` 영역에 버튼을 표시한다.

예:
```text
추가 확인 필요

용어 확인
[MRI 맞음]

실손 세대
[4세대 실손] [5세대 실손]

방문 구분
[입원] [통원] [처방조제]
```

### 4.4 사용자가 버튼 선택

사용자가 버튼을 클릭하면 해당 버튼은 선택 상태가 된다.

권장 동작:
- 단일 선택 그룹: `실손 세대`, `방문 구분`
- 복수 선택 가능 그룹: `증빙 서류`, `조건`, `용어 확인`

최소 구현에서는 각 버튼 클릭 즉시 재검색해도 된다. 다만 여러 조건을 한 번에 고르게 하려면 `선택값으로 다시 검색` 버튼을 둔다.

이번 명세의 권장 기본값:
- 버튼 클릭 즉시 재검색하지 않는다.
- 조건을 선택한 뒤 `선택값으로 다시 검색` 버튼을 누르면 자동 재검색한다.
- 단, `MRI 맞음`처럼 단일 용어 보정만 있는 경우에는 클릭 즉시 재검색해도 된다.

### 4.5 query 재작성

원문 질문은 보존하고, 명확화 블록을 뒤에 붙인다.

형식:
```text
{원문 질문}

[사용자 명확화]
- 용어 확인: 엠알아이 = MRI
- 실손 세대: 5세대
- 방문 구분: 통원
```

예:
```text
엠알아이 찍었는데 실손 보상돼?

[사용자 명확화]
- 용어 확인: 엠알아이 = MRI
- 실손 세대: 5세대
- 방문 구분: 통원
```

이 방식은 기존 `GraphQueryPlanner`가 `MRI`, `5세대`, `통원`을 그대로 감지할 수 있으므로 백엔드 변경을 최소화할 수 있다.

## 5. 프론트 구현 상세

대상 파일:
- `frontend/js/pages/chat.js`
- `frontend/css/chat.css`

### 5.1 `renderClarificationHtml(graphResult)` 수정

현재 함수는 질문/정규화/후보/모호 용어를 텍스트로 렌더링한다. 이를 버튼형 UI로 확장한다.

필수 요구:
- `plan.term_correction_candidates` 기반 용어 확인 버튼 생성
- `plan.ambiguous_terms` 기반 조건 선택 버튼 생성
- `plan.clarification_questions`는 안내 문구로 유지
- 각 버튼에 `data-action="select-clarification"` 또는 별도 class/data 속성 부여
- 재검색 버튼에 `data-action="apply-clarification"` 부여
- 원문 query를 알 수 있도록 container에 `data-original-query` 저장

예상 data 속성:
```html
<button
  type="button"
  class="clarify-option"
  data-action="select-clarification"
  data-clarify-group="policy_generation"
  data-clarify-label="5세대 실손"
  data-clarify-value="5세대"
>
  5세대 실손
</button>
```

### 5.2 명확화 버튼 그룹 매핑

`ambiguous_terms` 값을 기준으로 아래 버튼을 생성한다.

| ambiguous term | group | buttons |
| --- | --- | --- |
| `실손 세대` | `policy_generation` | `4세대 실손`, `5세대 실손` |
| `방문 구분` | `visit_type` | `입원`, `통원`, `처방조제` |
| `상품/특약` | `policy_product` | `SOL건강`, `실손의료보험`, `운전자보험` |
| `치료 목적` | `treatment_purpose` | `치료 목적`, `미용 목적`, `예방/검진 목적`, `합병증 치료` |
| `증빙 서류` | `evidence_tags` | `영수증`, `세부내역서`, `진단서`, `수술확인서`, `검사결과지` |
| `용어 보정 후보` | `term_correction` | `normalized 맞음` |

알 수 없는 `ambiguous_terms`는 텍스트 tag로만 표시한다.

### 5.3 클릭 이벤트 추가

`setupChatDelegatedHandlers()` 내부에 명확화 이벤트를 추가한다.

필수 동작:
- `select-clarification`
  - 같은 group의 기존 선택 해제
  - 클릭한 버튼에 `.selected` 클래스 추가
  - 복수 선택 그룹(`evidence_tags`)은 toggle 허용
- `apply-clarification`
  - 같은 clarification container 안의 선택값 수집
  - 원문 query와 선택값으로 rewritten query 생성
  - 사용자 메시지로 `[명확화 선택] ...` 표시
  - `streamChat(rewrittenQuery, originalMode, originalFilters, originalMemo)` 호출

주의:
- 기존 `candidate-btn`은 보험금 계산 후보 선택용이다. 명확화 버튼 class와 충돌하지 않게 한다.
- `activeAbort`가 있으면 기존 `streamChat()` 시작 시 이미 abort 처리된다.
- 현재 session id는 유지해야 하므로 `currentSession`을 그대로 사용한다.

### 5.4 `streamChat()` 수정

`streamChat(query, mode, filters, memo)`가 최종 렌더링 시 `renderClarificationHtml(graphResult)`를 호출한다.

필요 변경:
- `renderClarificationHtml(graphResult, query, mode, filters, memo)`처럼 원문 query와 mode 정보를 전달
- 렌더링된 clarification container에 원문 query/mode/filters/memo 정보를 data attribute 또는 안전한 in-memory map으로 보관

권장:
- 긴 query를 HTML data attribute에 직접 넣지 말고, module-level Map을 사용한다.
- 예: `clarificationPayloads.set(id, { query, mode, filters, memo, graphResult })`
- container에는 `data-clarification-id="{id}"`만 저장한다.

### 5.5 query 재작성 helper 추가

`frontend/js/pages/chat.js`에 helper를 추가한다.

예상 함수:
```js
function buildClarifiedQuery(originalQuery, selections) {
  const lines = [originalQuery.trim(), '', '[사용자 명확화]'];
  selections.forEach((selection) => {
    lines.push(`- ${selection.label}: ${selection.value}`);
  });
  return lines.join('\n');
}
```

선택값 label 예:
- `용어 확인`
- `실손 세대`
- `방문 구분`
- `상품/특약`
- `치료 목적`
- `증빙 서류`

## 6. 백엔드 구현 상세

최소 구현에서는 백엔드 변경 없이 가능하다.

다만 재현성과 감사 로그 품질을 높이려면 아래 변경을 권장한다.

대상 파일:
- `src/api/schemas/chat.py`
- `src/api/routes/chat.py`

### 6.1 `ChatRequest`에 optional field 추가

```python
clarification: dict = Field(default_factory=dict)
```

### 6.2 audit log에 clarification 저장

`src/api/routes/chat.py`의 `log_audit_event()` detail에 아래 추가:
```python
"clarification": chat_request.clarification,
```

### 6.3 백엔드 rewrite는 이번 단계에서 필수 아님

프론트에서 rewritten query를 만들어 보내면 현재 parser가 인식 가능하다.
백엔드 rewrite까지 넣으면 중복 로직이 생길 수 있으므로, 이번 작업에서는 프론트 rewrite를 우선한다.

## 7. CSS 구현 상세

대상 파일:
- `frontend/css/chat.css`

추가할 style 예:
```css
.clarify-option-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 5px 0 8px;
}

.clarify-option {
  border: 1px solid #b8ccff;
  background: #fff;
  color: #1d4ed8;
  border-radius: 999px;
  padding: 4px 9px;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
}

.clarify-option.selected {
  background: #1d4ed8;
  color: #fff;
  border-color: #1d4ed8;
}

.clarify-apply {
  margin-top: 6px;
  border: 0;
  background: var(--primary);
  color: #fff;
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
}

.clarify-apply:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

디자인 기준:
- 기존 `.msg-clarifications` 카드 내부에서만 동작
- 버튼이 길어져도 줄바꿈되어야 함
- 모바일 폭에서도 겹치지 않아야 함

## 8. 테스트 계획

### 8.1 프론트 E2E 테스트

대상:
- `tests/e2e/chat.spec.js`

추가 시나리오:
1. `/api/chat/stream` mock SSE에 `graph` 이벤트 포함
2. 답변 하단에 명확화 버튼 표시 확인
3. `5세대 실손`, `통원`, `MRI 맞음` 선택
4. `선택값으로 다시 검색` 클릭
5. `/api/chat/stream`가 두 번째로 호출되는지 확인
6. 두 번째 요청 payload의 `query`에 아래 문구가 포함되는지 확인
   - `[사용자 명확화]`
   - `5세대`
   - `통원`
   - `MRI`

### 8.2 백엔드 단위 테스트

기존 테스트 참고:
- `tests/test_graph_review_path_planner.py`
- `tests/test_api_rag_service_payload.py`
- `tests/test_api_chat_stream.py`

추가/보강:
- `GraphQueryPlanner`가 rewritten query에서 `5세대`, `통원`, `MRI`를 감지하는지 확인
- `graph_result_to_payload()`가 clarification 관련 필드를 누락하지 않는지 확인
- `ChatRequest.clarification`을 추가했다면 schema validation 테스트 추가

### 8.3 수동 검증 질문

아래 질문으로 UI를 확인한다.

```text
엠알아이 찍었는데 실손 보상돼?
```

기대:
- `MRI 맞음`
- `4세대 실손`
- `5세대 실손`
- `입원`
- `통원`
- `처방조제`

```text
도수치료 받았는데 보상 가능해?
```

기대:
- `4세대 실손`
- `5세대 실손`
- `입원`
- `통원`
- `영수증`
- `세부내역서`

```text
미용 목적 시술 후 부작용 치료도 보상돼?
```

기대:
- `치료 목적`
- `미용 목적`
- `합병증 치료`
- `진단서`
- `검사결과지`

## 9. 완료 기준

아래 조건을 모두 만족하면 완료로 본다.

- 모호한 질문 답변 하단에 명확화 버튼이 표시된다.
- 사용자가 버튼을 선택할 수 있다.
- 선택값이 UI에서 명확히 표시된다.
- 선택값으로 query가 재작성된다.
- 재작성 query로 자동 재검색된다.
- 재검색은 기존 채팅 session을 유지한다.
- 재검색 요청 payload에 원문 질문과 명확화 값이 모두 포함된다.
- 기존 보험금 계산 후보 버튼(`candidate-btn`) 동작이 깨지지 않는다.
- 기존 일반 채팅, 퀵코드, 정형 약관 모드가 깨지지 않는다.
- E2E 테스트 또는 수동 검증에서 2회차 `/api/chat/stream` 호출이 확인된다.

## 10. 구현 순서 권장

1. `frontend/js/pages/chat.js`에 clarification payload Map과 id generator 추가
2. `renderClarificationHtml()`를 버튼형 렌더링으로 확장
3. `setupChatDelegatedHandlers()`에 clarification 버튼 이벤트 추가
4. `buildClarifiedQuery()` helper 추가
5. `streamChat()`에서 원문 query/mode/filters/memo를 `renderClarificationHtml()`에 전달
6. `frontend/css/chat.css`에 버튼 스타일 추가
7. `tests/e2e/chat.spec.js`에 명확화 버튼 자동 재검색 테스트 추가
8. 필요 시 `src/api/schemas/chat.py`에 `clarification` field 추가
9. 필요 시 `src/api/routes/chat.py` audit detail에 clarification 기록 추가
10. `pytest`와 Playwright E2E 중 가능한 범위를 실행

## 11. 주의사항

- 명확화 선택은 답변을 확정하는 기능이 아니라, 검색 조건을 명확히 하는 기능이다.
- `MRI 맞음` 같은 용어 보정 후보는 자동 확정하지 말고 사용자 선택 이후에만 query에 반영한다.
- 버튼 label은 사용자에게 쉬운 한국어로 표시하되, query에 들어가는 값은 planner가 감지 가능한 표현이어야 한다.
- 예: `5세대 실손`, `통원`, `MRI`, `치료 목적`
- 사용자 선택이 없는 상태에서 `선택값으로 다시 검색` 버튼은 disabled 처리한다.
- 여러 clarification block이 동시에 있을 수 있으므로, 클릭한 block 내부의 선택값만 수집한다.
- HTML data attribute에 긴 원문 query를 직접 넣으면 escape/길이 문제가 생길 수 있다. 가능하면 Map을 사용한다.
- `frontend/dist/app.min.js`는 빌드 산출물일 수 있으므로 직접 수정하지 말고 원본 JS/CSS를 수정한 뒤 프로젝트의 기존 빌드 방식이 있으면 빌드한다.

## 12. 추가 UX 기능 구현 상세

아래 3개 기능은 이번 명확화 UX의 필수 확장 범위로 포함한다.

1. 선택값 요약 칩 고정 표시
2. 선택 초기화 / 다시 선택
3. 자주 쓰는 조건 프리셋

이 기능들은 모두 `frontend/js/pages/chat.js`와 `frontend/css/chat.css`에서 구현한다. 백엔드 변경은 필수가 아니다.

## 13. 선택값 요약 칩 고정 표시

### 13.1 목적

사용자가 어떤 조건을 선택했는지 한눈에 확인할 수 있게 한다.

예:
```text
선택된 조건
[MRI] [5세대 실손] [통원]
```

선택값 요약 칩은 같은 clarification block 안에서 항상 보이게 한다.

### 13.2 표시 위치

`추가 확인 필요` 영역 내부에서 다음 순서를 권장한다.

1. 제목: `추가 확인 필요`
2. 선택값 요약 칩 영역
3. 용어 확인 / 실손 세대 / 방문 구분 / 증빙 서류 등 선택 버튼
4. `선택값으로 다시 검색` 버튼
5. `선택 초기화` 버튼

초기 상태:
```text
선택된 조건
아직 선택된 조건이 없습니다.
```

선택 후:
```text
선택된 조건
[MRI] [5세대 실손] [통원]
```

### 13.3 DOM 구조 예시

```html
<div class="clarify-selected-summary" data-clarify-summary>
  <div class="clarify-subtitle">선택된 조건</div>
  <div class="clarify-selected-chips" data-clarify-selected-chips>
    <span class="clarify-empty">아직 선택된 조건이 없습니다.</span>
  </div>
</div>
```

선택 후:
```html
<div class="clarify-selected-chips" data-clarify-selected-chips>
  <span class="clarify-selected-chip" data-group="term_correction">MRI</span>
  <span class="clarify-selected-chip" data-group="policy_generation">5세대 실손</span>
  <span class="clarify-selected-chip" data-group="visit_type">통원</span>
</div>
```

### 13.4 JS 구현 함수

`frontend/js/pages/chat.js`에 아래 helper를 추가한다.

```js
function updateClarificationSummary(container) {
  const chips = container.querySelector('[data-clarify-selected-chips]');
  if (!chips) return;

  const selections = collectClarificationSelections(container);
  if (!selections.length) {
    chips.innerHTML = '<span class="clarify-empty">아직 선택된 조건이 없습니다.</span>';
    return;
  }

  chips.innerHTML = selections
    .map((item) => `<span class="clarify-selected-chip" data-group="${escapeHTML(item.group)}">${escapeHTML(item.display)}</span>`)
    .join('');
}
```

`collectClarificationSelections(container)`는 선택된 버튼을 읽어서 아래 형태로 반환한다.

```js
[
  {
    group: 'policy_generation',
    label: '실손 세대',
    value: '5세대',
    display: '5세대 실손'
  },
  {
    group: 'visit_type',
    label: '방문 구분',
    value: '통원',
    display: '통원'
  }
]
```

### 13.5 선택 이벤트와 연동

`select-clarification` 클릭 처리 후 반드시 호출한다.

```js
updateClarificationSummary(container);
updateClarificationApplyState(container);
```

`updateClarificationApplyState(container)`는 선택값이 하나 이상 있으면 `선택값으로 다시 검색` 버튼을 활성화한다.

## 14. 선택 초기화 / 다시 선택

### 14.1 목적

사용자가 잘못 선택한 조건을 쉽게 되돌릴 수 있게 한다.

필수 기능:
- 선택된 모든 버튼의 `.selected` 제거
- 선택값 요약 칩 초기화
- `선택값으로 다시 검색` 버튼 disabled 처리
- 이미 재검색 중이면 초기화 버튼은 disabled 처리

### 14.2 버튼 DOM 예시

```html
<button
  type="button"
  class="clarify-reset"
  data-action="reset-clarification"
>
  선택 초기화
</button>
```

### 14.3 이벤트 처리

`setupChatDelegatedHandlers()` 내부에 추가한다.

```js
const resetClarification = target.closest('[data-action="reset-clarification"]');
if (resetClarification) {
  const container = resetClarification.closest('[data-clarification-id]');
  if (!container) return;
  resetClarificationSelections(container);
  return;
}
```

### 14.4 JS 구현 함수

```js
function resetClarificationSelections(container) {
  container.querySelectorAll('.clarify-option.selected').forEach((button) => {
    button.classList.remove('selected');
    button.setAttribute('aria-pressed', 'false');
  });
  updateClarificationSummary(container);
  updateClarificationApplyState(container);
}
```

### 14.5 단일 선택 / 복수 선택 규칙

단일 선택 그룹:
- `policy_generation`
- `visit_type`
- `policy_product`
- `treatment_purpose`
- `term_correction`

복수 선택 그룹:
- `evidence_tags`
- 필요 시 `conditions`

단일 선택 그룹에서는 같은 group 안에서 하나만 선택되게 한다.

```js
if (!isMultiSelectClarificationGroup(group)) {
  container
    .querySelectorAll(`.clarify-option[data-clarify-group="${CSS.escape(group)}"]`)
    .forEach((button) => {
      button.classList.remove('selected');
      button.setAttribute('aria-pressed', 'false');
    });
}
```

주의:
- `CSS.escape`가 없는 구형 환경을 고려한다면 group 값은 영문/underscore만 사용한다.
- 현재 group 값은 `policy_generation`, `visit_type`처럼 안전한 값만 사용한다.

## 15. 자주 쓰는 조건 프리셋

### 15.1 목적

실제 테스트와 상담 흐름에서 자주 쓰는 조건 조합을 한 번에 선택하게 한다.

예:
```text
자주 쓰는 조건
[5세대 + 통원] [4세대 + 통원] [5세대 + 입원] [MRI + 5세대 + 통원]
```

### 15.2 표시 조건

프리셋은 항상 보여도 되지만, 과도하게 복잡해 보이지 않도록 아래 조건 중 하나를 만족할 때 표시한다.

- `ambiguous_terms`에 `실손 세대`가 있음
- `ambiguous_terms`에 `방문 구분`이 있음
- `coverage_topics`에 `실손`, `MRI`, `MRA`, `자기공명영상진단`, `도수치료`, `체외충격파치료`, `3대비급여` 중 하나가 있음
- `term_correction_candidates`에 `MRI` 또는 `MRA` 후보가 있음

최소 구현에서는 `msg-clarifications`가 렌더링될 때 항상 프리셋 섹션을 보여도 된다.

### 15.3 기본 프리셋 목록

아래 프리셋을 우선 구현한다.

| 버튼 label | 적용 selection |
| --- | --- |
| `5세대 + 통원` | `policy_generation=5세대`, `visit_type=통원` |
| `4세대 + 통원` | `policy_generation=4세대`, `visit_type=통원` |
| `5세대 + 입원` | `policy_generation=5세대`, `visit_type=입원` |
| `4세대 + 입원` | `policy_generation=4세대`, `visit_type=입원` |
| `MRI + 5세대 + 통원` | `term_correction=MRI`, `policy_generation=5세대`, `visit_type=통원` |
| `도수/충격파 + 5세대 + 통원` | `coverage_topic=도수치료 또는 체외충격파치료`, `policy_generation=5세대`, `visit_type=통원` |

### 15.4 프리셋 DOM 예시

```html
<div class="clarify-preset-section">
  <div class="clarify-subtitle">자주 쓰는 조건</div>
  <div class="clarify-preset-row">
    <button
      type="button"
      class="clarify-preset"
      data-action="apply-clarification-preset"
      data-preset-id="fifth-outpatient"
    >
      5세대 + 통원
    </button>
  </div>
</div>
```

### 15.5 프리셋 데이터 구조

`frontend/js/pages/chat.js` 상단 또는 helper 근처에 정의한다.

```js
const CLARIFICATION_PRESETS = {
  'fifth-outpatient': {
    label: '5세대 + 통원',
    selections: [
      { group: 'policy_generation', label: '실손 세대', value: '5세대', display: '5세대 실손' },
      { group: 'visit_type', label: '방문 구분', value: '통원', display: '통원' },
    ],
  },
  'fourth-outpatient': {
    label: '4세대 + 통원',
    selections: [
      { group: 'policy_generation', label: '실손 세대', value: '4세대', display: '4세대 실손' },
      { group: 'visit_type', label: '방문 구분', value: '통원', display: '통원' },
    ],
  },
  'fifth-inpatient': {
    label: '5세대 + 입원',
    selections: [
      { group: 'policy_generation', label: '실손 세대', value: '5세대', display: '5세대 실손' },
      { group: 'visit_type', label: '방문 구분', value: '입원', display: '입원' },
    ],
  },
  'fourth-inpatient': {
    label: '4세대 + 입원',
    selections: [
      { group: 'policy_generation', label: '실손 세대', value: '4세대', display: '4세대 실손' },
      { group: 'visit_type', label: '방문 구분', value: '입원', display: '입원' },
    ],
  },
  'mri-fifth-outpatient': {
    label: 'MRI + 5세대 + 통원',
    selections: [
      { group: 'term_correction', label: '용어 확인', value: 'MRI', display: 'MRI' },
      { group: 'policy_generation', label: '실손 세대', value: '5세대', display: '5세대 실손' },
      { group: 'visit_type', label: '방문 구분', value: '통원', display: '통원' },
    ],
  },
  'manual-shockwave-fifth-outpatient': {
    label: '도수/충격파 + 5세대 + 통원',
    selections: [
      { group: 'coverage_topic', label: '보장 항목', value: '도수치료 또는 체외충격파치료', display: '도수/충격파' },
      { group: 'policy_generation', label: '실손 세대', value: '5세대', display: '5세대 실손' },
      { group: 'visit_type', label: '방문 구분', value: '통원', display: '통원' },
    ],
  },
};
```

### 15.6 프리셋 클릭 동작

프리셋 클릭 시:
1. 기존 선택값을 초기화한다.
2. 프리셋의 selections를 버튼 선택 상태로 반영한다.
3. 선택값 요약 칩을 갱신한다.
4. `선택값으로 다시 검색` 버튼을 활성화한다.
5. 자동 재검색은 하지 않는다. 사용자가 최종 확인 버튼을 누르게 한다.

이유:
- 프리셋은 여러 조건을 한 번에 선택하므로, 사용자가 선택 내용을 보고 확인한 뒤 재검색하는 흐름이 안전하다.

이벤트 예:
```js
const presetButton = target.closest('[data-action="apply-clarification-preset"]');
if (presetButton) {
  const container = presetButton.closest('[data-clarification-id]');
  const preset = CLARIFICATION_PRESETS[presetButton.dataset.presetId];
  if (!container || !preset) return;
  applyClarificationPreset(container, preset);
  return;
}
```

구현 함수 예:
```js
function applyClarificationPreset(container, preset) {
  resetClarificationSelections(container);

  preset.selections.forEach((selection) => {
    const matchingButton = [...container.querySelectorAll('.clarify-option')]
      .find((button) =>
        button.dataset.clarifyGroup === selection.group
        && button.dataset.clarifyValue === selection.value
      );

    if (matchingButton) {
      matchingButton.classList.add('selected');
      matchingButton.setAttribute('aria-pressed', 'true');
    } else {
      addSyntheticClarificationSelection(container, selection);
    }
  });

  updateClarificationSummary(container);
  updateClarificationApplyState(container);
}
```

`addSyntheticClarificationSelection()`은 화면에 해당 선택 버튼이 없는 경우에도 프리셋 선택값을 query 재작성에 포함하기 위한 보조 장치다.

권장 구현:
- container 내부에 숨김 input 또는 hidden span을 추가한다.
- class는 `.clarify-option.selected.synthetic`로 맞추면 `collectClarificationSelections()` 재사용이 쉽다.

예:
```html
<span
  class="clarify-option selected synthetic"
  data-clarify-group="coverage_topic"
  data-clarify-label="보장 항목"
  data-clarify-value="도수치료 또는 체외충격파치료"
  data-clarify-display="도수/충격파"
  hidden
></span>
```

## 16. 추가 기능 반영 후 query 재작성 규칙

선택값 요약 칩, 초기화, 프리셋 모두 최종적으로 `collectClarificationSelections(container)` 결과를 사용한다.

최종 query 예:
```text
엠알아이 찍었는데 실손 보상돼?

[사용자 명확화]
- 용어 확인: MRI
- 실손 세대: 5세대
- 방문 구분: 통원
```

프리셋 적용 query 예:
```text
도수치료 받았는데 보상 가능해?

[사용자 명확화]
- 보장 항목: 도수치료 또는 체외충격파치료
- 실손 세대: 5세대
- 방문 구분: 통원
```

중복 selection은 제거한다.

중복 기준:
```text
group + value
```

예:
- `policy_generation=5세대`가 이미 있으면 다시 추가하지 않는다.

## 17. 추가 기능 테스트 항목

### 17.1 선택값 요약 칩 테스트

테스트 위치:
- `tests/e2e/chat.spec.js`

검증:
- 명확화 버튼이 표시된 뒤 초기 summary에 `아직 선택된 조건이 없습니다.` 표시
- `5세대 실손` 클릭 시 summary에 `5세대 실손` 칩 표시
- `통원` 클릭 시 summary에 `통원` 칩 추가

### 17.2 선택 초기화 테스트

검증:
- `5세대 실손`, `통원` 선택
- `선택 초기화` 클릭
- 두 버튼의 `.selected` 제거
- summary가 `아직 선택된 조건이 없습니다.`로 복귀
- `선택값으로 다시 검색` 버튼 disabled

### 17.3 프리셋 테스트

검증:
- `5세대 + 통원` 프리셋 클릭
- summary에 `5세대 실손`, `통원` 표시
- `선택값으로 다시 검색` 활성화
- 재검색 클릭 시 두 번째 `/api/chat/stream` payload query에 `5세대`, `통원`, `[사용자 명확화]` 포함

### 17.4 프리셋 synthetic selection 테스트

검증:
- `도수/충격파 + 5세대 + 통원` 프리셋 클릭
- 화면에 `coverage_topic` 버튼이 없어도 summary에 `도수/충격파` 표시
- 재검색 query에 `도수치료 또는 체외충격파치료` 포함

## 18. 추가 기능 완료 기준

아래 조건을 모두 만족해야 한다.

- 선택한 명확화 조건이 요약 칩으로 표시된다.
- 조건을 바꾸면 요약 칩도 즉시 갱신된다.
- 단일 선택 그룹에서는 하나만 선택된다.
- 복수 선택 그룹에서는 여러 개 선택 가능하다.
- `선택 초기화`가 모든 선택값과 synthetic selection을 제거한다.
- 선택값이 없으면 재검색 버튼이 disabled 상태다.
- 프리셋 클릭 시 여러 조건이 한 번에 선택된다.
- 프리셋 선택 후 바로 자동 재검색하지 않고, 사용자가 확인 버튼을 눌러 재검색한다.
- 프리셋에서 화면에 없는 조건도 query 재작성에 포함된다.
- 기존 보험금 계산 후보 선택 버튼(`candidate-btn`)과 충돌하지 않는다.
- 모바일 폭에서도 칩과 버튼이 겹치지 않는다.
