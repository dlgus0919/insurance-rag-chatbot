# 264. 6세대 이상 실손 세대 지식 확장 가이드

기준 버전: `v1.0.22`
기준 저장소: DGX `/srv/shared/projects/insurance-rag-chatbot`

## 목적

현재 보험금 계산 기능은 4세대와 5세대 실손 계산 룰을 active rule manifest로 관리한다. `v1.0.22`에서는 현재 지원 세대 중 최신인 5세대를 기본값으로 사용한다.

이 문서는 향후 6세대 또는 그 이후 세대가 출시될 때, 개발팀이 하드코딩 지식 확장을 피하면서 신규 세대를 추가하기 위한 최소 작업 범위를 정리한다.

## 현재 상태

- 활성 룰 파일: `data/rules/claim_deductible_rules.active.json`
- 현재 활성 세대: `4th`, `5th`
- 현재 프론트엔드 세대 선택 UI: `4세대`, `5세대` 라디오버튼 정적 렌더링
- 현재 API 요청 스키마: `4th`, `5th`만 허용
- 현재 기본 세대: `5th`

따라서 현재 상태에서는 6세대 룰을 active manifest에 추가하더라도 프론트엔드 라디오버튼과 API 스키마가 자동으로 확장되지는 않는다.

## 원칙

1. 세대별 공제율, 보상률, 공제금액 같은 보험 지식은 코드 상수로 새로 박지 않는다.
2. 신규 세대 룰은 문서 근거 또는 실무자 승인 흐름을 거쳐 active rule manifest에 반영한다.
3. 코드는 룰을 해석하는 엔진 역할만 담당하고, 세대별 값은 승인된 룰 데이터에서 읽는다.
4. 신규 세대가 미승인 상태라면 앱은 계산을 진행하지 않거나 관리자 승인 필요 상태로 안내해야 한다.

## 권장 확장 방식

### 1. 활성 룰 기반 세대 목록 API 추가

관리자 또는 채팅 화면에서 사용할 수 있도록 active rule manifest에서 지원 세대 목록을 추출하는 API를 추가한다.

반환 예시:

```json
{
  "generations": [
    {"value": "4th", "label": "4세대 실손", "is_default": false},
    {"value": "5th", "label": "5세대 실손", "is_default": true}
  ]
}
```

기본값은 active rule manifest 안에서 가장 최신 세대 또는 명시된 `default_generation` 정책으로 결정한다.

### 2. 프론트엔드 라디오버튼 동적 렌더링

`frontend/html/chat.html`에 정적으로 박힌 세대 라디오버튼을 제거하고, API에서 받은 세대 목록으로 렌더링한다.

이렇게 하면 6세대 룰이 승인되어 active manifest에 들어간 뒤, 프론트엔드도 별도 코드 수정 없이 새 세대를 표시할 수 있다.

### 3. API 스키마 검증을 manifest 기반으로 전환

현재처럼 `Literal["4th", "5th"]`로 막으면 신규 세대가 자동 확장되지 않는다. 대신 요청값이 active rule manifest의 지원 세대 목록에 있는지 검증한다.

허용되지 않은 세대가 들어오면 최신 세대로 조용히 대체하지 말고, 사용자에게 지원되지 않는 세대라고 알려야 한다.

### 4. 신규 세대 룰 후보 생성 및 승인

문서 추가 또는 룰 후보 추출 단계에서 신규 세대 관련 후보를 생성한다.

실무자 승인 UI에서는 다음을 보여준다.

- 세대명
- 적용 범위: 입원/통원/처방 등
- 급여/비급여/3대비급여 등 분류
- 공제율, 최소공제금액, 보상률 등 후보 값
- 원문 근거
- 기존 4세대/5세대와 달라지는 점

승인된 룰만 active manifest에 반영한다.

### 5. 검증 기준

신규 세대 추가 시 최소 검증은 다음과 같다.

- active rule manifest schema 검증
- 신규 세대가 관리자 지식 확장 탭에서 확인되는지 검증
- 채팅 화면 세대 선택 UI에 신규 세대가 표시되는지 검증
- 신규 세대 계산 요청이 API에서 통과하는지 검증
- 미승인 또는 누락 룰이 있을 때 계산이 조용히 잘못 진행되지 않는지 검증
- 기존 4세대/5세대 회귀 테스트 통과

## 구현 대상 파일 안내

향후 6세대 자동 반영을 구현할 때 우선 확인할 파일은 다음과 같다.

- `data/rules/claim_deductible_rules.active.json`
- `src/claim_calculation/rule_registry.py`
- `src/claim_calculation/deductible_rules.py`
- `src/claim_calculation/pipeline.py`
- `src/api/schemas/claim.py`
- `src/api/routes/claim.py`
- `frontend/html/chat.html`
- `frontend/js/pages/chat.js`
- `frontend/js/modules/admin.js`
- `frontend/js/pages/admin.js`

## 현재 한계

`v1.0.22`는 현재 지원되는 최신 세대인 5세대를 기본값으로 선택하도록 고친 버전이다. 그러나 6세대 이상이 출시되었을 때 UI와 API가 자동으로 확장되는 구조까지는 아직 구현하지 않았다.

따라서 6세대 이상 자동 반영은 별도 후속 작업으로 처리해야 한다.
