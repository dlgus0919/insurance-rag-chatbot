# 134. 4/5세대 실손 보험금 계산 강화 Phase 1 구현 보고

작성일: 2026-05-27

## 목적

보험금 계산 파이프라인의 공제 규칙을 실제 약관에 가까운 정밀 계산으로 강화했다. Phase 1 범위:
1. 통원 의료기관 등급별 최소공제금액 분화 (의원/병원/종합병원/상급종합)
2. 건당 한도 엔진 도입 (4세대 25만원, 5세대 20만원)
3. 처방약(약제비) 별도 공제 체계 분리 (8천원 고정 공제, 건당 5만원 한도)

## 핵심 변경

### 신규 모듈

- `src/claim_calculation/deductible_rules.py` (신규)
  - `DeductibleRule` 데이터클래스: 세대×카테고리×방문형태×의료기관등급 조합별 공제 규칙
  - `PrescriptionRule` 데이터클래스: 처방약 전용 공제 규칙
  - 4세대 규칙 테이블 4행, 5세대 규칙 테이블 10행, 처방약 규칙 2행
  - `lookup_rule()`: 인덱스 기반 O(1) 규칙 조회 + 4세대 비급여 alias 매핑 + fallback
  - `lookup_prescription_rule()`: 세대별 처방약 규칙 조회

### 데이터 모델 확장

- `models.py`
  - `ClaimItemInput`: `is_prescription: bool` 추가
  - `ClaimCaseContext`: `facility_grade: str` 추가
  - `CalculationResult`: `applied_limits: dict[str, str]` 추가

### 파이프라인 로직

- `pipeline.py`
  - `_line_deductible()`: 하드코딩 if/elif 50줄 → `deductible_rules.lookup_rule()` 기반 15줄로 교체
  - `_is_prescription()`: 사용자 명시(`is_prescription`, `user_category_hint`) 우선 + 키워드 자동 감지
  - `_prescription_deductible()`: 처방약 전용 공제 계산
  - `_calculate_line_items()`: 건당 한도 적용 분기 + 처방약 분기 추가
  - `run_claim_calculation()`: 결과에 `applied_limits` 정보 포함

### API 스키마

- `schemas/claim.py`
  - `ClaimItemRequest`: `is_prescription: bool` 추가
  - `ClaimCaseContextRequest`: `facility_grade: Literal` 추가
  - `ClaimCalculationResponse`: `applied_limits: dict` 추가

### SPA 프론트엔드

- `chat.html`: 의료기관 등급 드롭다운, 처방약 카테고리 옵션 추가
- `chat.js`: `facility_grade`, `is_prescription` 수집/전송, 한도 정보 표시

### 테스트

- `test_deductible_rules.py` (신규, 24개 테스트)
- `test_claim_calculation_pipeline.py` (기존 25 → 43개, 18개 추가)

## 의료기관 등급별 통원 최소공제 테이블

| 세대 | 카테고리 | 의원 | 병원 | 종합 | 상급종합 |
|---|---|---|---|---|---|
| 4세대 | 급여 | ₩10,000 | ₩15,000 | ₩20,000 | ₩20,000 |
| 4세대 | 비급여 | ₩30,000 | ₩30,000 | ₩30,000 | ₩30,000 |
| 5세대 | 급여 | ₩10,000 | ₩15,000 | ₩20,000 | ₩20,000 |
| 5세대 | 중증비급여 | ₩30,000 | ₩30,000 | ₩30,000 | ₩30,000 |
| 5세대 | 비중증/3대비급여 | ₩50,000 | ₩50,000 | ₩50,000 | ₩50,000 |

## 검증 결과

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_deductible_rules.py tests/test_claim_calculation_pipeline.py tests/test_api_claim_calculation.py -v
# 70 passed

PYTHONPATH=. .venv/bin/pytest -q
# 474 passed, 3 warnings

cd frontend && npm run build
# dist/app.min.js 48.3kb
```

## 설계 결정 사항

1. **미분류 항목의 fallback**: 이전에는 미분류 → 비급여(30%)였으나, 새 구조에서는 미분류 → 급여(20%) fallback으로 변경했다. 비급여를 추정 적용하면 과다 공제 위험이 있으므로, 보수적으로 급여 기본을 적용하고 검토 플래그를 남긴다.
2. **처방약 분류 우선순위**: `is_prescription` 플래그 > `user_category_hint == "처방약"` > input_name 키워드 자동 감지 순서.
3. **건당 한도 적용 시점**: 공제금액 산출 후, 건강보험 미적용 특례 적용 전에 한도를 적용한다.

## 남은 작업 (Phase 2~3)

- 5세대 3대비급여 선택형 특약별 한도/횟수 관리 (도수 350만/50회, MRI 350만, 주사 250만/50회)
- 연간 한도 잔여분 추적 (과거 청구 이력 연계 필요)
- 다수보험 비례보상 계산
- 보험가입금액/담보 정보 입력 UI
