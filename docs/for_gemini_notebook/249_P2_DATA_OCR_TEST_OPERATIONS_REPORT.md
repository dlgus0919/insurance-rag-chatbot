# P2 Data/OCR Test Operations Report

## Summary

P2 작업은 운영 데이터와 OCR 테스트 산출물을 안전하게 다루기 위한 경계를 추가하는 데 한정했다.

- 런타임 산출물 삭제/보존 판단은 `scripts/audit_runtime_artifacts.py`의 읽기 전용 분류로만 수행한다.
- 병원 영수증 OCR row는 원본 source row와 bbox가 추적되고 검증 상태가 `verified`인 경우에만 보험금 계산 입력 초안으로 승격한다.
- LLM/DGX/장시간 runtime 테스트를 pytest marker로 분리할 수 있도록 marker 체계를 등록했다.
- 원본 OCR 샘플, 운영 DB, 운영 인덱스, LLM 서버, DGX 프로세스는 수정하지 않았다.

## Files Changed

- `scripts/audit_runtime_artifacts.py`
- `src/hospital_receipt_ocr/__init__.py`
- `src/hospital_receipt_ocr/claim_adapter.py`
- `src/hospital_receipt_ocr/validation.py`
- `tests/test_audit_runtime_artifacts.py`
- `tests/test_hospital_receipt_claim_promotion.py`
- `pyproject.toml`
- `docs/247_P2_DATA_OCR_TEST_OPERATION_CHECKLIST.md`
- `docs/249_P2_DATA_OCR_TEST_OPERATIONS_REPORT.md`

## Operational Checklist

운영 경계와 테스트 명령 선택 기준은 `docs/247_P2_DATA_OCR_TEST_OPERATION_CHECKLIST.md`에 별도로 정리했다.

현재 브랜치의 OCR/LLM 관련 테스트 대부분은 monkeypatch 기반 단위 테스트라서, 실제 외부 runtime을 쓰지 않는 테스트는 무리하게 `slow`로 묶지 않았다. 이후 DGX 모델 기동, 실제 OCR batch, 장시간 평가 테스트를 추가할 때 `llm`, `dgx`, `slow`를 붙여 기본 로컬 루프에서 제외한다.

## Validation

통과:

```bash
python -m pytest tests/test_audit_runtime_artifacts.py tests/test_hospital_receipt_claim_promotion.py tests/test_claim_calculation_pipeline.py -q
# 48 passed

python -m pytest --markers
# P2 marker 등록 확인

python -m py_compile scripts/audit_runtime_artifacts.py src/hospital_receipt_ocr/claim_adapter.py src/hospital_receipt_ocr/validation.py

python scripts/audit_runtime_artifacts.py --root . --output /tmp/insurance-rag-artifact-audit.json
```

전체 non-heavy 루프 확인:

```bash
python -m pytest -m "not llm and not dgx and not slow" -q
```

결과: 현재 임시 worktree의 로컬 Python 환경에 `fastapi`, `aiosqlite`가 없어 API 테스트 수집 단계에서 중단되었다. 이는 P2 변경으로 발생한 실패가 아니라 로컬 의존성 환경 차이다. 변경 범위 검증은 위의 좁은 테스트로 완료했다.

## Ponytail Review

- 병원 영수증 OCR claim 승격 로직은 별도 registry나 복잡한 상태 머신 없이 단일 adapter 함수로 제한했다.
- artifact audit는 삭제 기능을 넣지 않고 분류 리포트만 생성한다.
- 새 외부 의존성은 추가하지 않았다.
- 검증 helper는 현재 필요한 최소 함수만 두었다.
- `row_id`가 없는 verified row가 자동 승격되지 않도록 추가로 차단했다.

## Remaining Risks

- 현재 branch는 P1 worktree에서 분기되어 최신 메인 checkout의 일부 문서 번호와 파일 상태를 모두 포함하지 않는다. 병합 전 최신 master 기준 rebase 또는 cherry-pick 검토가 필요하다.
- 실제 DGX OCR run 산출물에 대해 artifact audit를 돌리는 검증은 이번 P2 범위에서 수행하지 않았다.
- API 전체 테스트는 이 로컬 worktree 의존성 부족으로 실행하지 못했다. DGX 또는 완성된 `.venv` 환경에서 재검증해야 한다.

## Self-Inspection

- 요청 범위 밖의 운영 DB, 원본 데이터, LLM 서버, DGX 프로세스는 수정하지 않았다.
- 하드코딩 지식 금지 원칙을 위반하는 보험 지급 판단, 수치, 상품별 규칙은 추가하지 않았다.
- OCR row 승격은 source evidence와 검증 상태 기반으로 제한했다.
- 디버그 출력이나 삭제 기능은 남기지 않았다.
