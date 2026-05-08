# CLOVA OCR 로컬 실행 스크립트 구현 보고서 (v40)

## 1) 구현 결과
- 신규 스크립트: `scripts/run_clova_local.py`
  - CLI 인수: `--doc`, `--pages`, `--output-dir`, `--timeout`
  - 입력: `reports/ocr_compare/{doc_short}/p{page:03d}_original.png`
  - CLOVA 호출: `clova_ocr_page(image, page_name=..., timeout_sec=...)` 재사용
  - 출력: `p{page:03d}_clova.json` 저장
  - `summary.json`의 `engines.clova` 섹션만 재계산/갱신
  - `.env` 로딩: `load_dotenv(Path(__file__).parent.parent / ".env")` 사용 (`find_dotenv()` 미사용)
- 신규 테스트: `tests/test_run_clova_local.py`
  - `_block_quality()`
  - `_header_score()`
  - `_update_summary()`
  - `parse_pages()`

## 2) 테스트 결과

신규 테스트:
```bash
pytest tests/test_run_clova_local.py -q
```
- 결과: `5 passed`

전체 테스트:
```bash
pytest -q
```
- 결과: `182 passed, 5 warnings in 2.24s`

문법/import 확인:
```bash
python -c "import scripts.run_clova_local; print('import OK')"
```
- 결과: `import OK`

## 3) 로컬 실행 방법 (사용자용)
아래 명령을 그대로 실행하면 됩니다:

```bash
python scripts/run_clova_local.py --doc 실무가이드 --pages 60-70
```

옵션 예시:
```bash
python scripts/run_clova_local.py --doc 실무가이드 --pages 60,62,66 --timeout 90
```

## 4) 실행 결과 예상 출력 형식
```text
[run_clova_local] p060 -> SUCCESS (3블록, 7.1초)
[run_clova_local] p061 -> SUCCESS (4블록, 8.3초)
[run_clova_local] p062 -> SKIPPED (타임아웃 또는 API 오류)
...
[run_clova_local] summary.json 업데이트 완료
=== 완료 ===
SUCCESS: 10/11 | SKIPPED: 1/11 | 총 소요: 82.4초
저장 위치: reports/ocr_compare/실무가이드
```

## 5) 생성/갱신 파일 위치
- 페이지별 결과:
  - `reports/ocr_compare/실무가이드/p060_clova.json`
  - ...
  - `reports/ocr_compare/실무가이드/p070_clova.json`
- 요약 갱신:
  - `reports/ocr_compare/실무가이드/summary.json` (`engines.clova` 섹션)

## 6) 구현 시 판단 사항
1. `layout_regions` 없이 전체 페이지 단위 CLOVA 호출:
   - 명세 요구사항을 따라 `clova_ocr_page(..., timeout_sec=...)`만 사용.
2. `masked_image`/`figures` 필드:
   - 기존 `p{page}_hybrid.json`이 있으면 해당 값을 복사해 JSON 스키마 일관성 유지.
   - 없으면 기본값(`p{page}_masked.png`, `[]`) 사용.
3. SKIPPED 처리:
   - `ClovaOcrError` 또는 원본 PNG 누락 시 해당 페이지만 SKIPPED로 기록하고 다음 페이지 계속 진행.
4. `summary.json` 업데이트:
   - 기존 구조를 유지하고 `engines.clova`만 교체하도록 구현.

## 7) Git 반영 상태
- 구현 완료 후 커밋/푸시 완료 (최종 커밋 해시는 종료 메시지에 명시)

