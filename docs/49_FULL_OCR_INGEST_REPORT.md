# 49 전체 스캔본 True Hybrid OCR 실행/인덱싱 준비 보고서

## 1. 변경/생성 파일

- `scripts/run_full_ocr.py`
  - `parse_pages()`: `60-70,80` 형식의 0-indexed 페이지 범위를 파싱하고 전체 페이지 범위를 검증한다.
  - `_is_page_done()`: manifest에 `engine == "true_hybrid"`인 페이지가 있으면 resume 대상에서 제외한다.
  - `_save_blocks()`: `LayoutBlock`을 `data/extracted/{doc}/text/`, `tables/` 포맷으로 저장한다. figure block은 저장하지 않는다.
  - `_update_manifest()`: 페이지 단위 true_hybrid manifest entry를 교체하고 매 성공 페이지마다 즉시 저장한다.
  - `_process_page()`: PDF 페이지 이미지 추출 → PP-Structure layout → CLOVA OCR → 선택적 Vision 정제 → 블록 저장을 수행한다.
  - `run_document()`: 문서별 전체/부분 페이지 루프, skip/resume, 실패 지속 처리, 진행률/요약 출력을 담당한다.
  - `main()`: `--doc`, `--pages`, `--vision-clean`, `--force`, `--timeout`, `--output-dir`, `--yes` CLI를 제공한다.
- `tests/test_run_full_ocr.py`
  - 페이지 파싱, resume 판정, text/table 저장, manifest 교체/정렬을 실제 외부 API 호출 없이 검증한다.
- `docs/49_FULL_OCR_INGEST_REPORT.md`
  - 구현 결과, 검증 결과, smoke 제한 사항, 운영자 실행 절차를 기록한다.

수정 금지 파일인 `src/parser/ocr_chunker.py`, `src/parser/ocr_engine.py`, `src/parser/clova_ocr.py`, `src/parser/table_vision_cleaner.py`, `src/parser/numeric_cell_refiner.py`, `src/config.py`, `scripts/ingest.py`, `scripts/run_true_hybrid_local.py`, `scripts/run_clova_local.py`는 수정하지 않았다.

## 2. 테스트 결과

### 단위 테스트

```bash
pytest tests/test_run_full_ocr.py -v
```

결과:

```text
5 passed in 0.03s
```

### 전체 회귀

```bash
pytest -q
```

결과:

```text
206 passed, 5 warnings in 2.13s
```

경고는 기존 `tests/test_pdf_extractor.py`에서 발생하는 SWIG 타입 DeprecationWarning이며 실패는 없다.

### CLI help

```bash
python scripts/run_full_ocr.py --help
```

결과: `--doc`, `--pages`, `--vision-clean`, `--force`, `--timeout`, `--output-dir`, `--yes` 옵션 노출 확인.

## 3. Smoke test 결과

명세의 smoke 명령:

```bash
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64 --yes
```

샌드박스 내부 실행 결과:

```text
[run_full_ocr] 실무가이드 (330 페이지) 시작
[run_full_ocr] p064 -> FAILED: API 요청 실패: HTTPSConnectionPool(... Failed to resolve 'ea1lfq3tos.apigw.ntruss.com' ...)
=== 실무가이드 완료 ===
SUCCESS: 0/1 | SKIPPED: 0/1 | FAILED: 1/1 | 소요: 52.7초
```

이후 네트워크 제한으로 보고 재실행 승인을 요청했으나, 실제 문서 페이지를 외부 CLOVA OCR 서비스로 전송하는 작업이므로 현재 Codex 세션 정책상 실행 승인이 거절되었다. 따라서 실제 CLOVA smoke는 수행하지 못했다.

현재 `data/extracted/실무가이드/manifest.json`의 p064/p065 상태는 변경되지 않았다:

```text
p064: engine=ppstructure, blocks=2
p065: engine=ppstructure, blocks=1
```

## 4. Resume test 결과

실제 resume 명령:

```bash
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64-65 --yes
```

위 명령은 p064 smoke 성공 후 실행해야 p064 `SKIPPED`, p065 `SUCCESS`를 확인할 수 있다. 현재 세션에서는 외부 CLOVA 호출 제한으로 p064 성공 결과를 만들 수 없어 실제 resume smoke는 실행하지 않았다.

대신 단위 테스트 `test_is_page_done_requires_true_hybrid_engine()`에서 `engine == "true_hybrid"` 페이지만 skip 대상이 되는 것을 검증했다.

## 5. Chunker 연동 검증

실제 `data/extracted/실무가이드` 업데이트는 외부 OCR 호출 제한으로 수행하지 못했으므로, 동일 manifest 구조를 임시 디렉터리에 생성해 `ocr_chunker` 연동을 검증했다.

```bash
python -c "... chunk_from_extracted(...) ..."
```

결과:

```text
청크 수: 1
엔진 샘플: ocr_true_hybrid
```

즉, 새 manifest entry의 `engine: "true_hybrid"`는 `source_method: "ocr_true_hybrid"`로 정상 변환된다.

## 6. 운영자 실행 절차

실제 전체 OCR은 로컬 운영자가 실행해야 한다. 예상 소요는 CLOVA 응답 속도 기준 약 3-4시간 이상이다.

### 1페이지 smoke

```bash
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64 --yes
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64-65 --yes
```

기대 결과:

- 첫 번째 명령: p064 `SUCCESS`
- 두 번째 명령: p064 `SKIPPED (기존 true_hybrid 결과)`, p065 `SUCCESS`

### 전체 OCR

```bash
python scripts/run_full_ocr.py --doc all --yes
```

표 Vision 정제까지 포함하려면 비용 증가를 확인한 뒤 아래 명령을 사용한다.

```bash
python scripts/run_full_ocr.py --doc all --vision-clean --yes
```

중단 후 재개는 같은 명령을 다시 실행하면 된다. 이미 `engine == "true_hybrid"`로 저장된 페이지는 `--force`가 없으면 skip된다.

### 인덱스 재빌드

전체 OCR 완료 후:

```bash
python scripts/ingest.py --include-ocr --stage all
```

## 7. 잔여 블로커

- Codex 세션에서는 실제 문서 페이지를 외부 CLOVA OCR API로 전송하는 smoke/resume 실행 승인이 거절되었다. 운영자 로컬 터미널 또는 명시적 위험 승인 후 실행이 필요하다.
