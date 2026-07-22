# 5세대 실손 산정특례/공제 방식 수정 개발 명세

작성일: 2026-07-09  
기준 프로젝트: DGX Spark `/srv/shared/workspaces/dani/insurance-rag-chatbot`  
기준 브랜치/커밋: `master` = `f5dbfb5`

## 1. 목적

보험금 계산 로직에 아래 두 가지 실무 피드백을 반영한다.

1. 5세대 실손에서 산정특례 적용 여부에 따라 3대 비급여 보장 여부를 다르게 처리한다.
2. 여러 항목 입력 시 항목별로 공제하지 않고, 같은 보장/공제 그룹끼리 합산한 뒤 공제한다.

## 2. 약관 기준

### 산정특례 적용

- 적용 약관: 특별약관1, 중증 비급여 실손의료비
- 보장 구조:
  - 상해비급여, 질병비급여, 3대비급여
  - 3대비급여는 산정특례 대상 질환에 대한 치료일 때 보상 가능
- 3대비급여 항목:
  - 근골격계 이학요법치료/체외충격파치료
  - 주사료
  - 자기공명영상진단(MRI/MRA)
- 공제:
  - 1회당 3만원과 보장대상의료비의 30% 중 큰 금액
- 원문 근거:
  - `data/processed/chunks.jsonl`의 `표준약관_ch_005379`
  - `표준약관_ch_005394`
  - `표준약관_ch_005395`
  - `표준약관_ch_005397`

### 산정특례 미적용

- 적용 약관: 특별약관2, 비중증 비급여 실손의료비
- 보장 구조:
  - 상해비급여
  - 질병비급여
  - 비급여 자기공명영상진단
- 상해/질병 비급여는 비급여 자기공명영상진단을 제외한다.
- MRI/MRA는 `비급여 자기공명영상진단`으로 별도 보상 가능 여부를 판단한다.
- 도수치료/체외충격파/증식치료에 해당하는 근골격계 이학요법치료, 체외충격파치료, 일반 비급여 주사료는 보상하지 않는 사항으로 처리한다.
- MRI/MRA 공제:
  - 1회당 5만원과 보장대상의료비의 50% 중 큰 금액
  - 연간 200만원 한도
- 원문 근거:
  - `data/processed/chunks.jsonl`의 `표준약관_ch_005421`
  - `표준약관_ch_005434`
  - `표준약관_ch_005435`
  - `표준약관_ch_005447`
  - `표준약관_ch_005452`

## 3. 사용자 입력 변경

5세대 실손 선택 시 사용자가 산정특례 적용 여부를 직접 선택할 수 있어야 한다.

권장 값:

```text
""             # 미선택/모름
"applied"     # 산정특례 적용
"not_applied" # 산정특례 미적용
```

사용자에게 보이는 문구:

```text
산정특례 여부
- 모름
- 적용
- 미적용
```

현재 항목명/금액만 입력받는 구조에서는 로직이 산정특례 여부를 자동 확정할 수 없다. 진단명/진단코드 기반 추정은 가능하지만 지급/부지급 확정 계산에는 쓰지 않는다. 미선택이면 검토 필요 또는 Human Task로 처리한다.

## 4. 수정 대상 파일

### 4.1 입력 모델

파일:

- `src/claim_calculation/models.py`
- `src/api/schemas/claim.py`

수정:

```python
special_calculation_status: str = ""
```

또는 Pydantic schema에는 Literal을 사용한다.

```python
special_calculation_status: Literal["", "applied", "not_applied"] = ""
```

### 4.2 API 매핑

파일:

- `src/api/routes/claim.py`

현재 `ClaimCaseContext(**payload.context.model_dump())` 방식이므로 schema와 dataclass 필드만 맞으면 별도 매핑 코드는 거의 필요 없다.

스냅샷 저장에는 context 전체가 들어가므로 `_claim_snapshot_source()`에서 context 필터링/표시 필드가 있다면 `special_calculation_status`를 포함한다.

### 4.3 프론트 입력

파일:

- `frontend/html/chat.html`
- `frontend/js/pages/chat.js`
- 필요 시 `frontend/css/chat.css`
- 배포 번들 사용 구조라면 `frontend/dist/app.min.js`도 빌드/갱신

수정:

1. 보험금 계산 패널에 `산정특례 여부` select 추가
2. `sendClaim()`의 context payload에 값 추가
3. 초기화 함수에서 선택값을 `""`로 초기화

예시 payload:

```js
context: {
  visit_type: visitType,
  coverage_topic: coverageTopic,
  diagnosis_code: diagnosisCode,
  situation_note: note,
  policy_generation: policyGeneration,
  special_calculation_status: specialCalculationStatus,
}
```

## 5. 계산 로직 변경

중심 파일:

- `src/claim_calculation/pipeline.py`

### 5.1 현재 문제

현재 `_classify_claim_category()`는 항목 텍스트에 `도수`, `체외충격파`, `증식`, `주사`, `MRI`, `MRA`가 있으면 바로 `3대비급여`로 분류한다.

문제:

- 5세대 산정특례 미적용 케이스에서도 도수치료/주사료가 `3대비급여`로 들어갈 수 있다.
- 그 결과 공제 후 지급액이 계산된다.

### 5.2 수정 방향

분류 자체를 크게 복잡하게 만들기보다, 5세대 보상 가능 여부를 `_calculate_line_items()` 공통 경로에서 한 번 걸러낸다.

권장 helper:

```python
def _is_three_major_like(item: ClaimItemInput, match: StandardMatch | None) -> bool:
    ...

def _is_mri_like(item: ClaimItemInput, match: StandardMatch | None) -> bool:
    ...

def _is_manual_or_injection_like(item: ClaimItemInput, match: StandardMatch | None) -> bool:
    ...

def _special_status(context: ClaimCaseContext) -> str:
    return context.special_calculation_status or ""
```

5세대 처리 규칙:

```text
if generation != "5th":
    기존 흐름 유지

if special_calculation_status == "applied":
    3대비급여 계산 허용

if special_calculation_status == "not_applied":
    MRI/MRA는 "비급여자기공명영상진단"으로 계산
    도수/체외충격파/증식/일반 주사료는 지급 0원, 보상 제외

if special_calculation_status == "":
    3대비급여 유사 항목은 자동 확정 계산하지 말고 Human Task 또는 검토 필요
```

### 5.3 보상 제외 처리

산정특례 미적용 + 도수/체외충격파/증식/일반 주사료:

```text
payable = 0
deductible = amount
calculation_status = "conditional_not_covered"
requires_review = true
rule_summary = "5세대 산정특례 미적용 비중증 비급여에서는 해당 3대비급여 항목을 보상하지 않음"
```

주의:

- `deductible = amount`는 총 청구액 대비 지급 0원으로 표현하기 위한 기존 패턴에 맞춘다.
- `excluded_from_calculation`은 현재 Human Task 용도로 쓰이므로, 보상 제외 확정/조건부 제외 표현과 혼동되지 않게 기존 UI 표시를 확인한다.

### 5.4 MRI/MRA 카테고리 추가

산정특례 미적용 + MRI/MRA는 `3대비급여`가 아니라 `비급여자기공명영상진단`으로 계산한다.

필요한 rule category:

```text
비급여자기공명영상진단
```

## 6. Rule manifest 변경

파일:

- `data/rules/claim_deductible_rules.active.json`

현재 문제:

- 5세대 `3대비급여`가 특별약관2 기준 50%, 최소공제 5만원처럼 정의되어 있다.
- 약관 기준상 산정특례 적용 3대비급여는 특별약관1 기준 30%, 최소공제 3만원이다.
- 산정특례 미적용 MRI/MRA는 별도 `비급여자기공명영상진단`으로 분리해야 한다.

수정 방향:

```text
5th / 3대비급여 / outpatient
→ copay_ratio 0.3
→ min_deductible 30000
→ source_clause 특별약관1 3대비급여
→ source_chunk_id 표준약관_ch_005394 또는 표준약관_ch_005395

5th / 3대비급여 / hospitalization
→ copay_ratio 0.3
→ min_deductible 0 또는 약관상 입원/통원 공제 단위 재확인 후 반영
→ source_clause 특별약관1 3대비급여

5th / 비급여자기공명영상진단 / outpatient
→ copay_ratio 0.5
→ min_deductible 50000
→ annual_limit 2000000
→ source_clause 특별약관2 비급여 자기공명영상진단
→ source_chunk_id 표준약관_ch_005435
```

기존 `비중증비급여` 규칙은 산정특례 미적용 일반 상해/질병 비급여에 사용한다.

## 7. 공제 방식 변경

### 7.1 현재 문제

현재 `_calculate_line_items()`는 각 item을 돌면서 즉시 공제한다.

관련 위치:

- `src/claim_calculation/pipeline.py`의 `_calculate_line_items()`
- 라인별 루프에서 `_line_deductible()` 또는 `_apply_standard_deductible()`을 바로 호출
- 각 라인의 deductible/payable을 바로 `total_*`에 누적

결과:

```text
주사료 100,000원
주사료 100,000원
```

위처럼 같은 공제 단위가 2개 입력되면 공제가 2번 들어갈 수 있다.

### 7.2 수정 방향

입력은 항목별로 유지한다. 계산 단계에서만 같은 보장/공제 그룹끼리 묶는다.

처리 순서:

```text
항목별 입력
→ 항목별 분류/보상 제외 여부 판단
→ 보상 가능한 항목을 공제 그룹으로 묶기
→ 그룹 합산금액 기준 공제 1회 적용
→ 그룹 지급액을 라인별 금액 비율로 배분하거나, 라인별 결과에 그룹 공제 요약 표시
→ 총 지급액/총 공제액 산출
```

권장 group key:

```python
(
    generation,
    context.visit_type or "outpatient",
    context.facility_grade or "",
    category,
    special_calculation_status,
)
```

도수/체외충격파/증식치료, 주사료, MRI/MRA는 약관상 공제/횟수 단위가 다르므로 필요하면 `deductible_subgroup`을 추가한다.

```text
manual_therapy_group
injection_group
mri_group
general_nonpay_group
benefit_group
```

Ponytail 권장: 처음 구현은 새 DB나 큰 설계 없이 `_calculate_line_items()` 내부 helper로 끝낸다. 별도 group result API는 나중에 UI가 필요하다고 할 때 추가한다.

## 8. 재계산 대화 경로 변경

파일:

- `src/claim_calculation/thread_recalculation.py`

현재:

- 사용자가 “3대비급여로 다시 계산”이라고 하면 `user_category_hint = "3대비급여"`로 바꾼다.

수정:

- 5세대이고 context의 `special_calculation_status`가 `not_applied`이면 `3대비급여` 재계산을 막는다.
- 이 경우 “산정특례 미적용 5세대에서는 도수/주사료 등 3대비급여 재계산이 불가하며 MRI/MRA만 별도 보장종목으로 판단한다”는 안내를 반환한다.
- `special_calculation_status`가 비어 있으면 산정특례 여부 확인을 요청한다.

## 9. 테스트 케이스

최소 테스트만 추가/수정한다.

### 필수 신규 테스트

1. 5세대 + 산정특례 미적용 + 십자인대파열 + 도수치료
   - 지급액 0원
   - 보상 제외 또는 조건부 보상 제외 상태
   - review reason에 산정특례 미적용 근거 포함

2. 5세대 + 산정특례 미적용 + 십자인대파열 + 일반 비급여 주사료
   - 지급액 0원
   - 보상 제외 처리

3. 5세대 + 산정특례 미적용 + MRI/MRA
   - `비급여자기공명영상진단`으로 계산
   - 5만원과 50% 중 큰 금액 공제
   - 연간 200만원 한도 문구 포함

4. 5세대 + 산정특례 적용 + 도수치료/주사료/MRI
   - `3대비급여`로 계산
   - 3만원과 30% 중 큰 금액 공제

5. 동일 그룹 2개 항목 합산 공제
   - 예: 산정특례 적용 주사료 100,000원 + 주사료 100,000원
   - 공제는 30,000원 2회가 아니라 합산 200,000원 기준 60,000원 1회

### 수정 필요한 기존 테스트

- `tests/test_claim_calculation_pipeline.py`의 다중 라인 공제 기대값
- `tests/test_logic_final_round_2.py`의 5세대 MRI 기대값

기존에는 항목별 공제와 5세대 3대비급여 50% 규칙이 기대값으로 들어가 있으므로, 새 약관 기준에 맞게 기대값을 교체한다.

## 10. 완료 기준

아래 조건을 모두 만족해야 한다.

- 사용자가 5세대 계산 시 산정특례 적용/미적용/모름을 선택할 수 있다.
- 산정특례 미적용 + 십자인대파열 + 도수치료/주사료는 지급 계산에서 제외된다.
- 산정특례 미적용 + MRI/MRA는 `비급여자기공명영상진단`으로 계산된다.
- 산정특례 적용 + 3대비급여는 특별약관1 기준으로 계산된다.
- 같은 보장/공제 그룹 항목은 합산 후 1회 공제된다.
- 관련 테스트가 통과한다.
- `git diff --check`가 통과한다.

## 11. 구현 순서

1. `ClaimCaseContext`와 API schema에 `special_calculation_status` 추가
2. 프론트에 산정특례 여부 select 추가 및 payload 연결
3. rule manifest의 5세대 `3대비급여`와 `비급여자기공명영상진단` 정리
4. `pipeline.py`에 5세대 산정특례 게이트 추가
5. `_calculate_line_items()`를 그룹 합산 후 공제 구조로 최소 수정
6. `thread_recalculation.py`의 3대비급여 재계산 경로에 산정특례 guard 추가
7. 테스트 수정/추가
8. `pytest`와 `git diff --check` 실행

