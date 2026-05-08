# True Hybrid OCR 구현 보고서 (v41)

## 1) 구현 결과
- 신규 스크립트: `scripts/run_true_hybrid_local.py`
  - `preprocess_page()`로 PP-Structure 레이아웃/figure 마스킹 수행
  - `clova_ocr_page(..., layout_regions=prep.regions)`로 CLOVA OCR 호출
  - 페이지별 `p{page_no:03d}_true_hybrid.json` 저장
  - `summary.json`의 `engines.true_hybrid` 섹션 갱신
- 기존 스크립트 수정: `scripts/run_clova_local.py`
  - `_update_summary(..., engine_key: str = "clova")` 파라미터 추가
  - 기본값을 `clova`로 유지하여 기존 동작 호환
- 신규 테스트: `tests/test_run_true_hybrid_local.py`
  - SUCCESS 경로
  - CLOVA 오류 시 SKIPPED 처리
  - 원본 PNG 누락 시 SKIPPED 처리
  - `engines.true_hybrid` 요약 갱신 및 기존 엔진 섹션 보존

## 2) 테스트 결과
```bash
pytest tests/test_run_clova_local.py -q
```
- 결과: `5 passed`

```bash
pytest tests/test_run_true_hybrid_local.py -q
```
- 결과: `4 passed`

```bash
python -c "import scripts.run_true_hybrid_local; print('import OK')"
```
- 결과: `import OK`

```bash
pytest -q
```
- 결과: `186 passed, 5 warnings in 2.13s`

## 3) 로컬 실행 명령
```bash
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 60-70
```

## 4) 실행 시도 결과
- Codex 기본 샌드박스에서 위 명령을 실행함.
- PP-Structure 전처리 단계는 진행되었으나, CLOVA API Gateway 도메인 DNS 해석이 차단되어 11페이지 모두 SKIPPED됨.
- 결과 요약: `SUCCESS: 0/11 | SKIPPED: 11/11`
- 로컬 네트워크 권한 재실행은 원본 페이지 이미지가 외부 CLOVA OCR 서비스로 전송되는 작업이라 보안 검토에서 추가 사용자 승인이 필요하다고 차단됨.

## 5) 구현 시 판단 사항
1. `summary.json` 갱신은 기존 `clova` 하드코딩을 `engine_key` 기반으로 일반화했다.
2. `run_clova_local.py`의 기존 호출부는 수정하지 않고 기본값으로 호환성을 유지했다.
3. `figure_save_dir`는 명세대로 `p{page_no:03d}_true_hybrid_figures`를 사용해 기존 hybrid figure 폴더와 분리했다.
4. 기존 `p{page_no:03d}_hybrid.json`, `p{page_no:03d}_clova.json` 파일은 수정하지 않았다.

## 6) Git 반영 상태
- v41 구현 커밋 및 `origin/master` 푸시 완료.
