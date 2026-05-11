# 53 CLOVA Native OCR Workflow Report

## 1. 변경 배경

전체 스캔본 OCR 워크플로우를 우선 `CLOVA Native` 방식으로 확정했다. 다만 추후 `True Hybrid`를 다시 채택할 가능성을 남기기 위해 관련 코드는 삭제하지 않고 CLI 플래그로 보존했다.

## 2. 변경 사항

- `scripts/run_full_ocr.py`
  - 기본 OCR 엔진을 `clova_native`로 변경했다.
  - `--clova-native`는 기본값을 명시하는 플래그로 유지했다.
  - `--true-hybrid`를 추가해 기존 PP-Structure layout + CLOVA OCR 경로를 계속 실행할 수 있게 했다.
  - manifest의 `engine` 값을 실행 방식에 맞게 기록한다.
    - 기본: `clova_native`
    - `--true-hybrid`: `true_hybrid`
  - 재개/스킵 판단도 현재 실행 엔진 기준으로 동작하도록 수정했다.
  - 로그에 현재 엔진을 출력한다.

- `tests/test_run_full_ocr.py`
  - 기본 CLI가 CLOVA Native인지 검증하는 테스트를 추가했다.
  - `--true-hybrid` 플래그가 기존 경로를 선택하는지 검증했다.
  - manifest engine 기록과 skip 판단이 엔진별로 동작하는지 검증했다.

## 3. 검증

```text
pytest tests/test_run_full_ocr.py -q
9 passed in 0.03s
```

```text
pytest -q
224 passed, 5 warnings in 1.77s
```

## 4. 운영 메모

전체 OCR 실행은 이제 별도 플래그 없이도 CLOVA Native 방식으로 동작한다.

```text
python scripts/run_full_ocr.py --doc all --yes
```

True Hybrid가 필요할 때만 다음처럼 명시한다.

```text
python scripts/run_full_ocr.py --doc all --true-hybrid --yes --output-dir reports/true_hybrid_full_run
```

기본 출력 경로는 `data/extracted`이며, 중단 후 같은 명령을 다시 실행하면 완료된 `clova_native` 페이지는 skip된다.

## 5. Git

- Implementation commit hash: `db30423`
- Push: 완료 (`master -> origin/master`)
