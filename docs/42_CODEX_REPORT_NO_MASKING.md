# True Hybrid figure 마스킹 제거 보고서 (v42)

## 1) 구현 결과
- `scripts/run_true_hybrid_local.py`에서 CLOVA OCR 입력 이미지를 `prep.masked_image`에서 원본 `image`로 변경했다.
- CLOVA OCR에 전달하는 `layout_regions`에서 `figure` 타입을 제외하도록 변경했다.
- `p{page_no:03d}_true_hybrid.json`의 `masked_image` 필드를 `None`으로 변경했다.
- `preprocess_page()` 호출, figure 메타데이터 수집, `summary.json`의 `engines.true_hybrid` 갱신 로직은 유지했다.

## 2) 변경 요약
```diff
- blocks = clova_ocr_page(
-     prep.masked_image,
-     page_name=page_name,
-     layout_regions=prep.regions,
-     timeout_sec=timeout_sec,
- )
+ layout_regions_no_fig = [region for region in prep.regions if region.block_type != "figure"]
+ blocks = clova_ocr_page(
+     image,
+     page_name=page_name,
+     layout_regions=layout_regions_no_fig,
+     timeout_sec=timeout_sec,
+ )
```

```diff
- "masked_image": f"p{page_no:03d}_masked.png",
+ "masked_image": None,
```

## 3) 테스트 변경 사항
- `tests/test_run_true_hybrid_local.py::test_run_true_hybrid_success`에 아래 검증을 추가했다.
  - `figure` 타입 region이 CLOVA `layout_regions`에서 제거되는지 확인
  - CLOVA 호출이 빨간색 fake `masked_image`가 아니라 원본 이미지를 받는지 확인
  - 출력 JSON의 `masked_image`가 `None`인지 확인

## 4) 테스트 결과
```bash
pytest tests/test_run_true_hybrid_local.py -v
```
- 결과: `4 passed`

```bash
python -c "import scripts.run_true_hybrid_local; print('import OK')"
```
- 결과: `import OK`

```bash
pytest -q
```
- 결과: `186 passed, 5 warnings in 1.85s`

## 5) 구현 시 판단 사항
1. PP-Structure의 bbox는 표 재구성에 필요하므로 `preprocess_page()`는 제거하지 않았다.
2. figure 오탐으로 인한 데이터 손실을 막기 위해 CLOVA에는 원본 이미지를 전달했다.
3. figure region은 layout 안내에서만 제외했다. 제외된 영역의 OCR field는 `clova_ocr_page()` 내부 remainder 경로로 처리될 수 있다.
4. 명세 범위에 따라 `run_clova_local.py`, `ocr_preprocessor.py`, `clova_ocr.py`는 수정하지 않았다.
5. 명세 주의사항에 따라 `run_true_hybrid_local.py`의 실제 CLOVA 호출 실행은 수행하지 않았다.

## 6) Git 반영 상태
- v42 구현 커밋 및 `origin/master` 푸시 완료.
