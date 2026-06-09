# 196. 보험금 계산 영수증형 분리 입력 개편 보고

## 배경

기존 보험금 계산은 항목별 `청구금액` 하나만 입력받아 표준모델 보상의견을 전체 금액에 적용했다. 이 구조에서는 `L1213 마취료`처럼 실제 영수증상 급여 본인부담금만 발생한 건도 비급여표준모델의 `급여외 산정불가` 또는 면책성 의견이 전체 금액에 적용되어 지급예상액이 0원으로 산출될 수 있었다.

## 변경 내용

- 보험금 계산 입력 항목을 `항목명`, `코드`, `급여 본인부담금`, `비급여 금액`, `기타 추가 정보` 중심으로 확장했다.
- API와 내부 모델에 `insured_copay_amount`, `nonpay_amount`, `extra_info`를 추가했다.
- 기존 `claimed_amount` 단일 입력은 호환용으로 유지했다.
- 새 분리 입력이 들어오면 총 청구금액은 `급여 본인부담금 + 비급여 금액`으로 계산한다.
- 비급여표준모델의 `hira_care_type_cd_nm`, `ins_care_type_cd_nm`, `medical_class_cd_nm`, 항목 분류, `pay_opn_cd_nm`을 함께 읽어 표준모델 의견의 적용 범위를 판단한다.
- `급여외 산정불가` 또는 비급여 산정 제한 의견은 비급여 금액에 우선 적용하고, 급여 본인부담금은 세대/입원통원 기준 급여 실손 규칙으로 계산한다.
- 보험금 계산 탭에서는 하단 일반 질의 채팅 입력창을 숨기도록 했다.
- `frontend/index.html`과 `frontend/js/app.js`의 정적 리소스 버전을 갱신해 DGX 브라우저가 최신 계산 UI/JS를 로드하도록 했다.

## 대표 케이스

입력:

- 항목명: `마취료`
- 코드: `L1213`
- 급여 본인부담금: `23,434원`
- 비급여 금액: `0원`
- 조건: `5세대 실손`, `입원`
- 표준모델 보상의견: `급여외 산정불가`

결과:

- 총 청구금액: `23,434원`
- 예상 공제금액: `4,687원`
- 예상 지급금액: `18,747원`
- 해석: 비급여 금액은 0원이므로 표준모델의 급여외 산정 제한으로 전체 면책 처리하지 않고, 급여 본인부담금에 입원 급여 80% 보상 기준을 적용한다.

## 검증

- `pytest tests/test_claim_calculation_pipeline.py tests/test_claim_standard_matcher.py tests/test_logic_final_round_2.py -q`
  - `44 passed`
- `pytest tests/test_claim_calculation_pipeline.py::test_split_receipt_l1213_covers_insured_copay_even_when_nonpay_unavailable tests/test_claim_calculation_pipeline.py::test_split_receipt_standard_opinion_excludes_only_nonpay_part tests/test_logic_final_round_2.py::test_final_round_2_exclusion_code_hard_stops_before_llm -q`
  - `3 passed`
- `node --check frontend/js/pages/chat.js`
  - 통과
- `python -m py_compile src/claim_calculation/models.py src/claim_calculation/standard_matcher.py src/claim_calculation/pipeline.py src/api/schemas/claim.py src/api/routes/claim.py`
  - 통과

## DGX Live 검증

- DGX 프로젝트 venv:
  - `.venv/bin/pytest tests/test_claim_calculation_pipeline.py::test_split_receipt_l1213_covers_insured_copay_even_when_nonpay_unavailable tests/test_claim_calculation_pipeline.py::test_split_receipt_standard_opinion_excludes_only_nonpay_part tests/test_api_claim_calculation.py::test_claim_calculation_route_accepts_split_receipt_amounts -q`
  - `3 passed`
- DGX 문법/컴파일:
  - `.venv/bin/python -m py_compile src/claim_calculation/models.py src/claim_calculation/standard_matcher.py src/claim_calculation/pipeline.py src/api/schemas/claim.py src/api/routes/claim.py`
  - `node --check frontend/js/app.js frontend/js/pages/chat.js`
  - 통과
- DGX 운영 앱 재기동:
  - `/srv/ai-ops/bin/insurance-rag-up --replace --no-llm-switch --provider sglang --model gpt-oss-20b`
  - 앱 ready 확인
- Live API 입력 `L1213 / 급여 본인부담금 23434 / 비급여 0 / 5세대 / 입원`:
  - 총 청구금액 `23,434원`
  - 예상 공제금액 `4,687원`
  - 예상 지급금액 `18,747원`
- Live 프론트 입력 동일 케이스:
  - `급여 본인부담금`, `비급여 금액`, `기타 추가 정보` 필드 노출 확인
  - 보험금 계산 모드에서 하단 일반 채팅 입력창 숨김 확인
  - 결과 카드에서 `예상 지급금액 18,747원` 확인
