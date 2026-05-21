# 97. Claim Payout Calculation Pipeline Spec For Antigravity

작성일: 2026-05-21
작성 위치: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`
대상 작업자: Antigravity 서브 에이전트
작업 성격: 기능 확장 설계 및 구현 명세

## 1. 목적

챗봇에 “보험금 보상금 계산” 기능을 추가한다. 사용자가 텍스트로 청구 항목, 청구 금액, 선택적 보상 상황을 입력하면, 앱은 비급여 표준모델 데이터와 선택된 약관/문서 근거를 바탕으로 지급 가능 보험금을 계산하고, 계산 근거·산식·예외·불확실성을 함께 제시해야 한다.

이번 명세는 Antigravity가 코드 구현을 수행하기 위한 상세 작업 지시서다. Codex는 기획, 설계, 외부 기준 조사, 보험사 직원 관점의 검토를 수행했다.

## 2. 현재 저장소 전제

현재 기준 커밋:

```text
0e1b24d feat(ocr): integrate v1 v2 mapping workflow
```

관련 기존 자산:

```text
raw/비급여표준모델_전체판(23.12-25.07)_250723(신한EZ전달본).xlsx
scripts/build_relational_db.py
src/db/standard_codes.py
tests/test_standard_codes.py
src/rag/insurance_form.py
src/rag/quick_code.py
src/rag/pipeline.py
src/ui/streamlit_app.py
```

비급여 표준모델 적재 현황은 과거 보고서 기준 다음과 같다.

- 산출 DB: `data/index/relational/standard_codes.sqlite`
- 테이블: `nonpay_standard`
- XLSX 데이터 행: 529,020
- SQLite 적재 행: 527,679
- 주요 컬럼: `std_cd`, `std_cd_nm`, `mid_category_cd_nm`, `ins_care_type_cd_nm`, `medical_class_cd_nm`, `item_class_level*_nm`, `pay_opn_cd_nm`, `notes`, `apply_start_date`, `apply_end_date`

주의: 현재 비급여 표준모델 DB 스키마에는 병원별 실제 가격이나 보험금 지급액 컬럼이 없다. 따라서 계산 금액의 원천은 사용자가 입력한 청구금액이고, 표준모델은 항목 식별, 분류, 보상 의견, 특약 구분, 추가확인 필요 여부를 판정하는 기준 자산으로 사용한다.

## 3. 외부 기준 조사 요약

### 3.1 실손의료보험 계산의 기본 성격

보험다모아의 실손의료보험 설명은 실손의료보험이 질병·상해 치료 시 실제 부담한 의료비를 지급하는 상품이며, 요양급여 본인부담액과 비급여 합계액에서 약관상 자기부담금을 차감해 지급한다고 설명한다.

출처: [온라인 보험슈퍼마켓 보험다모아 - 실손의료보험](https://www.e-insmarket.or.kr/mins/minsInsIntro.knia)

설계 반영:

- 계산 입력은 “사용자 청구금액”을 기준으로 한다.
- 급여/비급여/3대비급여/특약 구분과 자기부담금, 한도, 면책 여부는 약관 근거로 결정한다.
- 계산 결과는 확정 지급이 아니라 “문서 기반 산출 보조”로 표시한다.

### 3.2 비급여 데이터의 공적 기준

보건복지부는 `비급여 진료비용 등의 보고 및 공개에 관한 기준`을 고시했고, 의료법 제45조의2 및 시행규칙 위임에 따라 비급여 항목·기준·금액·진료내역 보고에 대한 사항을 규정한다고 설명한다. 또한 2024년에는 비급여 보고제도가 의원급 이상 모든 의료기관으로 확대되었고, 의료기관이 비급여 항목, 기준, 금액, 진료내역 등을 의무 보고한다고 밝혔다.

출처:

- [보건복지부 고시 제2023-168호](https://www.mohw.go.kr/board.es?act=view&bid=0026&list_no=378100&mid=a10409020000&tag=)
- [2024년 비급여 보고의무 모든 의료기관으로 확대](https://www.mohw.go.kr/board.es?act=view&bid=0027&list_no=1480519&mid=a10503010100&nPage=1&tag=)

설계 반영:

- 비급여 표준모델은 단순 키워드 검색이 아니라 표준코드 중심의 구조화 조회를 우선한다.
- 사용자가 코드 없이 시술명만 입력하면 후보 표준코드를 제시하고, 모호하면 계산을 보류하거나 사용자 선택을 요구한다.
- 항목, 기준, 금액, 진료내역은 분리해서 다룬다. 현 단계에서는 금액은 사용자가 입력한다.

### 3.3 HIRA 비급여 공개의 의미

보건복지부/심평원 자료는 심평원이 의료기관별 비급여 진료비용 정보를 공개해 왔고, 관련 법령으로 의료법 제45조의2, 시행령/시행규칙, 보건복지부 고시를 제시한다.

출처: [병원의 비급여 진료비용은 심사평가원에서 확인하세요](https://www.mohw.go.kr/board.es?act=view&bid=0027&list_no=339008&mid=a10503010100&nPage=636&tag=)

설계 반영:

- 비급여 표준모델은 보험사 내부 계산 보조의 기준 자산으로 쓰되, 실제 의료기관 청구금액과 구분한다.
- 향후 영수증 OCR 단계에서는 병원 영수증의 금액/급여구분/코드와 표준모델 항목을 매칭하는 계층이 추가되어야 한다.

## 4. 기능 범위

### 4.1 이번 구현 범위

이번 구현은 텍스트 입력 기반 계산 MVP다.

포함:

- Streamlit에 새 모드 `보험금 계산` 추가
- 사용자가 청구 항목과 금액을 텍스트/폼으로 입력
- 선택적 상황 메모 입력
- 계산 기준 문서 선택
  - 자동
  - 약관
  - 자사_SOL건강
  - 자사_SOL운전자
  - 실무가이드
  - 상담사례집
  - 심평원
  - 비급여 표준모델
- 비급여 표준모델 DB에서 표준코드/항목 매칭
- RAG로 관련 약관/문서 조항 검색
- LLM이 계산 과정 초안을 구조화 JSON으로 작성
- LLM이 제한된 Python 코드 또는 산식 DSL을 생성
- 안전한 Python sandbox에서 금액 계산 실행
- 계산 결과, 산식, 적용 근거, 제외/보류 사유, 추가 확인 필요사항 표시

제외:

- 병원 영수증 이미지/PDF OCR
- 청구서 자동 파싱
- 실제 보험사 청구 시스템 연동
- 외부 API 결제/심사 연동
- 최종 지급 승인 자동화
- 대형 모델 기동 또는 GPU 점유 테스트

### 4.2 “자동” 기준 선택 의미

사용자가 `자동`을 선택하면 시스템이 다음 기준으로 문서를 선택한다.

1. 비급여 표준모델: 항상 사용
2. 사용자가 입력한 상품/담보/상황이 실손이면 `약관` 우선
3. SOL 건강/운전자 관련 키워드가 있으면 해당 자사 약관 추가
4. 수술종수·장해율·보상 실무 해석이 필요하면 `실무가이드` 추가
5. 사례성 분쟁/상담례가 필요하면 `상담사례집` 추가
6. 수가코드/행위코드/점수 확인이 필요하면 `심평원` 추가

자동 선택 결과는 UI에 표시하고 사용자가 수정할 수 있어야 한다.

## 5. 입력 모델

### 5.1 UI 입력 필드

필수:

- 청구 항목명 또는 표준코드
- 청구 금액

권장 필드:

- 수량/횟수
- 진료일
- 입원/통원
- 급여/비급여/3대비급여/모름
- 진단명/진단코드
- 사고/질병/상해 구분
- 선택 담보 또는 보장종목
- 이미 지급된 금액
- 연간 잔여 한도
- 회당 한도
- 자기부담금 정보가 알려진 경우
- 상황 메모

초기 MVP는 단일 항목부터 시작하고, 내부 데이터 구조는 다중 항목을 지원하게 만든다.

### 5.2 내부 데이터 구조 예시

```json
{
  "claim_id": "local-session-id",
  "basis_mode": "auto",
  "selected_basis_docs": ["약관", "비급여 표준모델"],
  "case_context": {
    "treatment_date": "2026-05-21",
    "visit_type": "outpatient",
    "coverage_topic": "3대비급여",
    "diagnosis_code": "",
    "situation_note": "도수치료 1회 청구"
  },
  "items": [
    {
      "line_id": "item_001",
      "input_name": "도수치료",
      "input_code": "",
      "claimed_amount": "150000",
      "quantity": "1",
      "user_category_hint": "3대비급여"
    }
  ]
}
```

금액은 float가 아니라 문자열로 받아 `Decimal`로 변환한다.

## 6. 계산 파이프라인 설계

### 6.1 전체 흐름

```text
사용자 입력
  -> 입력 정규화/검증
  -> 비급여 표준모델 exact/fuzzy 매칭
  -> 기준 문서 선택(auto/checkbox)
  -> RAG 근거 검색
  -> LLM 계산계획 JSON 생성
  -> 계산계획 검증
  -> LLM 제한 Python 생성 또는 DSL 생성
  -> sandbox 실행
  -> 산술 결과 검증
  -> 답변/표/감사 로그 출력
```

### 6.2 표준모델 매칭

우선순위:

1. `std_cd` exact match
2. `std_cd_nm` exact match
3. `std_cd_nm LIKE` 후보 검색
4. 사용자에게 후보 선택 요구
5. 후보가 없으면 계산 보류

매칭 결과에는 다음을 포함한다.

```json
{
  "std_cd": "050000011",
  "std_cd_nm": "...",
  "ins_care_type_cd_nm": "비급여_특약2",
  "medical_class_cd_nm": "주사료 약품비",
  "item_class_level1cd_nm": "...",
  "item_class_level2cd_nm": "...",
  "pay_opn_cd_nm": "추가확인",
  "notes": "...",
  "match_confidence": "exact|high|low",
  "requires_user_disambiguation": false
}
```

`pay_opn_cd_nm`이 `추가확인`, `확인필요`, 공란 등인 경우 계산은 가능하더라도 결과에 “추가 확인 필요”를 표시한다.

### 6.3 RAG 근거 검색

검색 쿼리는 다음을 조합한다.

```text
<항목명> <표준코드> <급여/비급여 구분> <담보> <입원/통원> <상황 메모> 보험금 자기부담금 한도 보상하지 않는 사항
```

검색 대상은 사용자가 선택한 문서에 한정한다. 자동 선택 시 위 4.2 기준을 따른다.

반드시 검색해야 하는 근거:

- 보상하는 사항
- 보상하지 않는 사항
- 자기부담금
- 한도
- 3대비급여 특약 조항
- 해당 항목의 표준모델 행

### 6.4 계산계획 JSON

LLM은 바로 Python 코드를 만들지 않는다. 먼저 계산계획 JSON을 만든다.

예시:

```json
{
  "decision": "calculable|needs_more_info|not_covered",
  "basis_summary": [
    {
      "source": "비급여 표준모델",
      "fact": "도수치료는 3대비급여/특약 항목으로 분류됨"
    },
    {
      "source": "약관",
      "fact": "보장대상의료비에서 자기부담금을 공제"
    }
  ],
  "variables": {
    "claimed_amount": "150000",
    "quantity": "1",
    "deductible_rate": "0.30",
    "min_deductible": "0",
    "per_visit_limit": null,
    "remaining_annual_limit": null
  },
  "calculation_steps": [
    "보장대상 금액을 청구금액으로 둔다.",
    "자기부담금은 청구금액의 30%로 둔다.",
    "지급예상액은 청구금액 - 자기부담금으로 계산한다."
  ],
  "formula_intent": "payable = max(0, claimed_amount - max(claimed_amount * deductible_rate, min_deductible))",
  "uncertainties": ["실제 약관 세대/특약 여부에 따라 자기부담률이 달라질 수 있음"]
}
```

계산계획 검증 실패 조건:

- 근거 source가 없음
- 금액 변수가 없음
- `decision=calculable`인데 산식이 없음
- 보상 제외 근거가 있는데 payable 산식을 생성함
- 사용자 입력 금액보다 큰 지급액을 설명 없이 허용함
- 약관/문서에 없는 자기부담률을 단정함

### 6.5 Python 코드 생성 및 실행

사용자 요구를 반영해 LLM이 Python 코드를 작성하되, 직접 실행 전에 강하게 제한한다.

원칙:

- 코드의 입력은 검증된 `variables` JSON뿐이다.
- `Decimal` 기반 계산만 허용한다.
- 파일, 네트워크, subprocess, import, eval, exec, open 금지.
- 함수명은 `calculate(variables)`로 고정한다.
- 반환값은 JSON-serializable dict로 고정한다.
- 실행 시간 제한을 둔다.
- 실패하면 “계산 불가/수동 확인 필요”로 fail-closed 처리한다.

허용 코드 형태 예시:

```python
def calculate(variables):
    from decimal import Decimal, ROUND_HALF_UP
    claimed_amount = Decimal(variables["claimed_amount"])
    deductible_rate = Decimal(variables["deductible_rate"])
    min_deductible = Decimal(variables.get("min_deductible") or "0")
    deductible = max(claimed_amount * deductible_rate, min_deductible)
    payable = max(Decimal("0"), claimed_amount - deductible)
    return {
        "claimed_amount": str(claimed_amount),
        "deductible": str(deductible.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        "payable": str(payable.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
    }
```

실제 구현에서는 `from decimal import ...`도 LLM 코드 내부 import가 아니라 sandbox 런타임에서 미리 주입하는 방식을 권장한다. LLM이 생성하는 코드에는 import를 허용하지 않는 것이 더 안전하다.

### 6.6 안전한 대안: Calculation DSL

LLM이 Python을 직접 만들도록 하되, 가능하면 내부적으로는 DSL로 변환한다.

DSL 예시:

```json
{
  "operations": [
    {"assign": "claimed", "decimal": "150000"},
    {"assign": "deductible", "max": [{"mul": ["claimed", "0.30"]}, "0"]},
    {"assign": "payable", "max": [{"sub": ["claimed", "deductible"]}, "0"]}
  ],
  "return": ["claimed", "deductible", "payable"]
}
```

권장 방향:

- MVP: 제한 Python sandbox
- 안정화: LLM Python 대신 DSL 생성으로 전환
- 장기: 검증된 rule primitive library와 DSL만 사용

## 7. UI 설계

### 7.1 Streamlit 검색 모드 추가

`SEARCH_MODES`에 추가:

```text
보험금 계산
```

### 7.2 UI 구성

- 항목 입력
  - 항목명/표준코드
  - 청구금액
  - 수량/횟수
- 보상 상황
  - 입원/통원
  - 급여/비급여/3대비급여/모름
  - 진단코드/진단명
  - 사고/질병/상해
  - 상황 메모
- 계산 기준 문서
  - `자동` checkbox 또는 radio
  - 개별 문서 checkbox
- 계산 실행 버튼
- 결과 영역
  - 표준모델 매칭 결과
  - 적용 문서/출처
  - 계산계획
  - 실행 산식
  - 지급예상액
  - 추가 확인 필요사항

### 7.3 출력 형식

```text
[계산 결과]
- 청구금액: 150,000원
- 보장대상 금액: 150,000원
- 자기부담금: 45,000원
- 지급예상액: 105,000원

[계산 과정]
1. 비급여 표준모델에서 <항목>을 <분류>로 매칭했습니다.
2. 선택한 약관 근거에 따라 자기부담률 <x>%를 적용했습니다.
3. 지급예상액 = 청구금액 - 자기부담금입니다.

[적용 근거]
- 비급여 표준모델: std_cd=..., 항목명=...
- 약관: <조항>, p.xx

[추가 확인 필요]
- 실제 가입 세대/특약/잔여 한도에 따라 달라질 수 있습니다.
```

## 8. 권장 신규 모듈

```text
src/claim_calculation/__init__.py
src/claim_calculation/models.py
src/claim_calculation/standard_matcher.py
src/claim_calculation/basis_selector.py
src/claim_calculation/planner.py
src/claim_calculation/code_sandbox.py
src/claim_calculation/pipeline.py
src/claim_calculation/formatting.py
```

### 8.1 `models.py`

Dataclass 또는 Pydantic 없이 표준 dataclass로 시작한다.

- `ClaimItemInput`
- `ClaimCaseContext`
- `BasisSelection`
- `StandardMatch`
- `CalculationPlan`
- `CalculationResult`

### 8.2 `standard_matcher.py`

`src/db/standard_codes.py`를 감싸는 계층이다.

기능:

- 코드 exact lookup
- 이름 exact/fuzzy search
- 후보 수 제한
- 모호성 판정
- `pay_opn_cd_nm` 기반 추가 확인 flag

### 8.3 `basis_selector.py`

자동 문서 선택 로직.

입력:

- 사용자 선택 checkbox
- 항목 분류
- 상황 메모
- 보험 종류/담보

출력:

- doc_filter
- selection_reason

### 8.4 `planner.py`

LLM 계산계획 JSON 생성 및 검증.

테스트에서는 fake LLM으로 대체한다. 실제 모델 호출 테스트는 수행하지 않는다.

### 8.5 `code_sandbox.py`

제한 Python 실행.

필수 보안 조건:

- AST whitelist
- timeout
- no file/network/subprocess
- no arbitrary import
- Decimal only
- stdout/stderr capture
- deterministic result

### 8.6 `pipeline.py`

전체 계산 흐름 조립.

```python
run_claim_calculation(
    pipeline: RagPipeline,
    claim_input: ClaimCalculationInput,
    selected_basis_docs: list[str] | None,
    auto_basis: bool,
) -> ClaimCalculationResult
```

## 9. 테스트 계획

Antigravity는 LLM/GPU 없이 단위 테스트를 작성한다.

권장 테스트 파일:

```text
tests/test_claim_standard_matcher.py
tests/test_claim_basis_selector.py
tests/test_claim_code_sandbox.py
tests/test_claim_calculation_pipeline.py
tests/test_streamlit_claim_calculation.py
```

필수 테스트:

1. 표준코드 exact match
2. 항목명 search 후보 반환
3. 후보가 2개 이상이면 disambiguation 필요
4. `pay_opn_cd_nm=추가확인`이면 `requires_review=True`
5. 자동 basis selector가 비급여/3대비급여 문항에서 약관+표준모델을 선택
6. sandbox가 정상 Decimal 계산 수행
7. sandbox가 `import os`, `open`, `subprocess`, `eval`, `exec`를 거부
8. 계산 결과가 청구금액을 초과하면 validation warning 또는 실패
9. 보상 제외 plan이면 payable=0 또는 calculation skipped
10. Streamlit helper가 입력 payload와 결과 표시 데이터를 만든다

## 10. Antigravity 구현 단계

### Phase 1. No-LLM 기반 골격

- 신규 모듈 생성
- dataclass 정의
- 표준모델 matcher 구현
- basis selector 구현
- sandbox 구현
- fake plan 기반 pipeline 테스트

### Phase 2. Streamlit UI 연결

- `보험금 계산` 모드 추가
- 단일 항목 입력 폼 추가
- 문서 기준 checkbox/auto 추가
- 표준모델 매칭 결과 표시
- fake plan 또는 deterministic simple plan으로 end-to-end UI helper 테스트

### Phase 3. LLM planner 연결

- 실제 LLM 호출부는 interface만 구현
- 테스트는 fake LLM으로 고정
- JSON schema validation 추가
- prompt는 “계산계획 JSON만 출력”으로 제한

### Phase 4. 제한 Python 실행 연결

- planner output -> sandbox code 생성
- AST validation
- Decimal 실행
- 결과 검증

### Phase 5. 보고서 작성

`docs/98_CLAIM_PAYOUT_CALCULATION_IMPL_REPORT.md` 작성.

포함:

- 변경 파일
- 계산 기능 흐름
- UI 사용법
- 테스트 결과
- 실행하지 않은 LLM/Streamlit/GPU 검증
- 남은 위험

## 11. 보험사 직원 관점의 자체 검토

### 11.1 좋은 점

- 계산식보다 먼저 근거와 계산계획을 만들기 때문에 설명 가능성이 높다.
- 비급여 표준모델 exact match를 우선해 항목 식별 오류를 줄인다.
- Python sandbox로 산술 자체는 deterministic하게 처리할 수 있다.
- `자동`과 checkbox를 모두 제공해 직원이 근거 문서를 통제할 수 있다.

### 11.2 실무 리스크

- 표준모델은 항목/분류 기준이지 실제 지급액 테이블이 아니다.
- 약관 세대, 특약 가입 여부, 연간/회당 잔여 한도, 이미 지급한 금액이 없으면 정확 계산이 불가능할 수 있다.
- 보상 제외/추가확인 항목을 LLM이 보상 가능으로 단정하면 업무 리스크가 크다.
- 사용자가 입력한 청구금액이 영수증과 다르면 결과도 틀린다.
- 문서 근거가 없는데도 계산을 강행하면 안 된다.

### 11.3 개선된 운영 원칙

- 계산 가능한 경우와 추가 정보가 필요한 경우를 명확히 분리한다.
- `계산 불가`는 실패가 아니라 안전한 결과로 취급한다.
- 지급예상액은 항상 “예상”으로 표시하고 최종 판정은 약관 원문과 사내 절차를 따르도록 안내한다.
- 표준모델 매칭 후보가 모호하면 사용자 선택 없이는 계산하지 않는다.
- 보상 제외 근거가 검색되면 산식 실행보다 제외 근거 표시를 우선한다.

## 12. Acceptance Criteria

구현 완료 기준:

- `pytest` 전체 통과
- 신규 claim calculation 테스트 통과
- LLM/GPU 없이 fake planner 기반 계산 pipeline 테스트 통과
- sandbox 보안 테스트 통과
- Streamlit에 `보험금 계산` 모드가 표시됨
- 사용자가 항목명+금액을 입력하면 표준모델 후보 또는 계산 결과가 표시됨
- 자동/checkbox 기준 문서 선택이 가능함
- 계산 결과에 출처, 산식, 추가확인 필요사항이 표시됨
- raw XLSX, SQLite DB, runtime 산출물은 Git에 포함하지 않음

## 13. Antigravity 금지사항

- 대형 모델 기동 금지
- SGLang/vLLM/Ollama 장시간 호출 금지
- 영수증 OCR 구현 착수 금지
- 기존 RAG retrieval/prompt의 대규모 리팩터링 금지
- raw XLSX 또는 SQLite 산출물 commit 금지
- secrets/env 출력 금지
- 계산 결과를 “확정 지급 보험금”으로 표현 금지

## 14. 참고 자료

- [온라인 보험슈퍼마켓 보험다모아 - 실손의료보험](https://www.e-insmarket.or.kr/mins/minsInsIntro.knia)
- [보건복지부 고시 제2023-168호 - 비급여 진료비용 등의 보고 및 공개에 관한 기준](https://www.mohw.go.kr/board.es?act=view&bid=0026&list_no=378100&mid=a10409020000&tag=)
- [보건복지부 - 2024년 비급여 보고의무 모든 의료기관으로 확대](https://www.mohw.go.kr/board.es?act=view&bid=0027&list_no=1480519&mid=a10503010100&nPage=1&tag=)
- [보건복지부/심평원 - 병원의 비급여 진료비용은 심사평가원에서 확인하세요](https://www.mohw.go.kr/board.es?act=view&bid=0027&list_no=339008&mid=a10503010100&nPage=636&tag=)
