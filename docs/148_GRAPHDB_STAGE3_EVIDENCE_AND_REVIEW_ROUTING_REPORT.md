# 148. GraphDB Stage 3 Evidence and Review Routing Report

작성일: 2026-05-28
대상 단계: `145_GRAPHDB_ONTOLOGY_IMPROVEMENT_STAGE_PLAN.md`의 Stage 3

## 1. 작업 목적

Stage 3의 목적은 GraphRAG review path가 보험금 계산 결과와 직접 연결되어, 보상 담당자가 다음을 즉시 확인할 수 있게 하는 것이다.

- 자동 계산이 가능한지
- 예상 계산은 가능하지만 심사 검토가 필요한지
- 정보/코드 부족으로 자동 계산을 보류해야 하는지
- 면책/보상제외 근거가 있어 지급예상액을 0원으로 보수 처리했는지
- 어떤 증빙과 검토 조치가 필요한지

## 2. 변경 내용

### 2.1 CalculationResult 구조화 필드 추가

수정 파일:

- `src/claim_calculation/models.py`

추가 필드:

- `calculation_status`
- `missing_evidence`
- `review_actions`

`calculation_status` 값:

- `auto_calculated`
- `estimated_review_required`
- `blocked_missing_info`
- `not_covered`

### 2.2 Evidence completeness checker 추가

수정 파일:

- `src/claim_calculation/pipeline.py`

변경 내용:

- Graph review path의 `required_evidence`와 입력 context의 `evidence_tags`를 비교한다.
- 단순 완전 일치뿐 아니라 포함 관계도 인정한다.
- 누락된 증빙은 `missing_evidence`로 구조화해 반환한다.

예:

- 요구: `세부내역서`
- 입력: `진료비 세부내역서`
- 처리: 충족

### 2.3 Review action 구조화

수정 파일:

- `src/claim_calculation/pipeline.py`

변경 내용:

- Graph review path의 `review_actions`를 `CalculationResult.review_actions`로 별도 반환한다.
- 기존 `review_reasons`에도 사람이 읽는 문구를 유지해 UI 호환성을 보존했다.

### 2.4 Confirmed exclusion 감지 보강

수정 파일:

- `src/claim_calculation/pipeline.py`

변경 내용:

- Stage 1에서 `GraphPathStep.notes`가 `exclusion; 입력 조건 직접 일치`처럼 확장되면서 기존 exact match 방식이 깨질 수 있었다.
- 이제 `RELATES_TO_COMPLICATION` step의 notes가 `exclusion`으로 시작하면 confirmed exclusion으로 처리한다.
- confirmed exclusion이면 지급예상액은 `0원`, 공제금액은 청구금액 전액으로 보수 처리한다.

### 2.5 API/UI 반영

수정 파일:

- `src/api/schemas/claim.py`
- `src/ui/streamlit_app.py`

변경 내용:

- API response에 `calculation_status`, `missing_evidence`, `review_actions`를 포함했다.
- API request context에 `complication_asserted`, `treatment_purpose`, `evidence_tags`, `facility_type`, `facility_grade`를 받을 수 있게 했다.
- Streamlit 보험금 계산 결과 화면에서 추가 확인 필요 서류와 권장 검토 조치를 분리해 표시한다.

## 3. 검증 결과

실행 명령:

```bash
python -m py_compile src/claim_calculation/models.py src/claim_calculation/pipeline.py src/api/schemas/claim.py src/ui/streamlit_app.py
python -m pytest tests/test_claim_complication_review.py tests/test_claim_calculation_pipeline.py::test_pipeline_candidate_pays_by_ratio_without_confirmed_forces_review -q
```

결과:

```text
2 passed in 0.58s
```

검증한 사항:

- 미용 목적 수술 후 합병증 면책 경로에서 지급액이 `0원`으로 유지된다.
- 누락 증빙이 `진단서`, `세부내역서`로 구조화된다.
- 권장 검토 조치가 `진단서 요청`, `세부내역서 요청`으로 구조화된다.
- candidate 지급비율만 있는 경우 기존 review 강제 로직이 유지된다.

## 4. 남은 작업

다음 단계는 Stage 4 `Claims Handler UI and Audit View`다.

중점:

- chat UI의 구조화 검토 경로를 업무형 문구로 더 압축한다.
- candidate/confirmed/review_required 상태를 더 분명하게 보여준다.
- 저장되는 대화 요약에도 review path summary를 감사 가능한 형태로 유지한다.
