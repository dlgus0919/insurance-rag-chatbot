# 172. Clarification Follow-up Panel Fix Report

작성일: 2026-06-02
대상 프로젝트: `insurance-rag-chatbot`
대상 환경: DGX Spark 메인 프로젝트 `/srv/shared/projects/insurance-rag-chatbot`

## 배경

일반 질의의 GraphRAG 명확화 패널에서 다음 문제가 확인되었다.

1. 같은 확인 항목이 버튼 섹션과 질문 문구로 동시에 반복 노출됨
2. 개별 선택지로 제공되지 않는 값을 포함한 프리셋이 `자주 쓰는 조건`에 노출될 수 있음
3. 사용자는 실제로 선택할 수 없는 조건을 프리셋에서 보게 되어 오해할 수 있음

## 원인

### 1. 질문 중복 노출
프론트엔드 `renderClarificationHtml()`은 `ambiguous_terms`를 기반으로 인터랙션 버튼을 만들면서도, 동일 의미의 `clarification_questions`를 그대로 다시 출력하고 있었다.

예:
- `상품/특약` 버튼 섹션 노출
- 동시에 `어떤 상품 또는 특약 가입 여부를 기준으로 볼지 확인해 주세요.` 문구 재노출

### 2. 프리셋 노출 조건이 느슨함
`getApplicableClarificationPresets()`는 프리셋의 group이 현재 required group에 속하는지만 확인했고, 해당 selection이 실제 패널에서 버튼으로 선택 가능한지는 검증하지 않았다.

이 때문에 `coverage_topic`처럼 현재 패널에서 직접 선택 UI가 없는 값을 포함한 프리셋이 노출될 여지가 있었다.

## 수정 내용

### 프론트엔드
수정 파일:
- `frontend/js/pages/chat.js`

적용 사항:
- `filterClarificationQuestions()` 추가
  - 현재 패널에서 버튼으로 제공되는 확인 항목과 동일 의미의 질문 문구는 숨김
- `questionCoveredByClarificationGroup()` 추가
  - `실손 세대`, `방문 구분`, `상품/특약`, `치료 목적`, `증빙 서류`, `용어 확인` 계열 질문을 그룹별로 판정
- `isRenderableClarificationSelection()` 추가
  - 프리셋의 각 selection이 현재 패널에서 실제로 선택 가능한지 검증
- `getApplicableClarificationPresets()` 강화
  - 실제 선택 가능한 항목만 포함한 프리셋만 노출
- `renderClarificationHtml()` 호출부 보강
  - clarification 문맥을 함께 전달하도록 정리

## 기대 효과

- 사용자는 같은 내용을 두 번 읽지 않게 됨
- `자주 쓰는 조건`이 실제 선택 가능한 항목 집합과 일치하게 됨
- 패널의 의미가 `추가 확인 필요`에서 `실제 선택 가능한 확인 절차`로 정리됨

## 검증

실행 명령:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
node --check frontend/js/pages/chat.js
node --check tests/e2e/chat.spec.js
```

결과:
- JS 문법 검사 통과

추가 회귀 보강:
- `tests/e2e/chat.spec.js`
  - 버튼으로 제공된 확인 항목이 질문 목록에 중복 노출되지 않는 케이스 추가

## 남은 점

- 실제 브라우저 Playwright 실행까지는 이번 단계에서 돌리지 않았다.
- 후속으로는 실사용 시나리오 기준으로
  - `합병증 특약`
  - `MRI 실손`
  - `도수치료`
  질의에서 패널 구성이 기대대로 정리되는지 확인하면 된다.
