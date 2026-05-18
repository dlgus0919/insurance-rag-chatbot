# Codex 개발자 프롬프트 — True Hybrid figure 마스킹 제거 (v42)

## 역할

당신은 이 프로젝트의 개발자입니다. 기획·검토 에이전트가 작성한 명세를 구현하고, 구현 결과를 보고서로 작성합니다.

---

## 배경

True Hybrid OCR 파이프라인(v41)에서 PP-Structure가 표를 "figure"로 잘못 분류하는 오탐이 발생하여 페이지의 28~63%가 마스킹되는 문제가 확인되었습니다.

현재 코드의 문제:
```python
# run_true_hybrid_local.py — 현재 (문제)
blocks = clova_ocr_page(
    prep.masked_image,           # figure 영역이 흰 사각형으로 덮임 → 텍스트 소실
    layout_regions=prep.regions, # figure 타입 region → clova_ocr_page 내부에서 skip
    ...
)
```

수정 방향:
```python
# run_true_hybrid_local.py — 수정 후
layout_regions_no_fig = [r for r in prep.regions if r.block_type != "figure"]
blocks = clova_ocr_page(
    image,                            # 원본 이미지 (마스킹 없음)
    layout_regions=layout_regions_no_fig,  # figure 타입 제외
    ...
)
```

**이 수정은 `run_true_hybrid_local.py`와 `tests/test_run_true_hybrid_local.py` 두 파일만 변경합니다.**

---

## 구현 명세

`docs/42_CODEX_SPEC_NO_MASKING.md`를 정독하고 아래 순서로 구현하세요.

### 구현 순서

1. **`scripts/run_true_hybrid_local.py` 수정**
   - `run_true_hybrid_local()` 내 `clova_ocr_page()` 호출부: `prep.masked_image` → `image`, `prep.regions` → `layout_regions_no_fig`
   - `_write_page_json()` 내 `masked_image` 필드: `f"p{page_no:03d}_masked.png"` → `None`

2. **`tests/test_run_true_hybrid_local.py` 수정**
   - `_CallRecorder`에 `received_image` 필드 추가
   - `test_run_true_hybrid_success()` 강화:
     - figure 타입이 `layout_regions`에서 제거되었는지 확인
     - `clova_ocr_page`가 원본 image를 받았는지 확인 (masked_image와 구분 가능하도록 fake_preprocess_page 수정)
     - `output["masked_image"] is None` 확인

3. **검증 실행**
   - `pytest -q` (전체, 회귀 포함)
   - `python -c "import scripts.run_true_hybrid_local; print('import OK')"`

---

## 보고서 작성 요구사항

구현 완료 후 `docs/42_CODEX_REPORT_NO_MASKING.md`를 작성하세요.

필수 포함 항목:
1. `pytest -q` 결과
2. `run_true_hybrid_local.py` 변경 사항 요약
3. 테스트 변경 사항
4. 구현 시 판단 사항

---

## 주의사항

- `find_dotenv()` 사용 금지 → `Path(__file__).parent.parent / ".env"` 사용 (기존 코드 그대로)
- `preprocess_page()` 호출 제거 금지 — 레이아웃 bbox는 여전히 필요
- `run_clova_local.py`, `ocr_preprocessor.py`, `clova_ocr.py` 수정 금지
- Codex 환경에서 `run_true_hybrid_local.py` 직접 실행 금지 (DNS 차단)
- 기존 `p0{xx}_hybrid.json`, `p0{xx}_clova.json` 파일 수정 금지
