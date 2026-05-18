# Codex 명세 — True Hybrid OCR 구현 (v41)

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)  
선행 보고서: `docs/40_CODEX_REPORT_CLOVA_LOCAL.md`

---

## 배경 및 목적

### 현재까지 확인된 엔진별 특성

| 지표 | Hybrid (PP-Structure + PaddleOCR) | CLOVA (layout 없음) |
|------|----------------------------------|---------------------|
| 표 구조 (행/열 JSON) | ✅ 10개 | ❌ 0개 |
| 평균 한글비율 | 62.6% | **84.8%** |
| 평균 노이즈율 | 1.10% | **0.24%** |
| p066 의료용어 정확도 | 오인식 多 | ✅ 전항목 정확 |
| 텍스트 읽기 순서 | ✅ 정상 | ❌ 열 단위 혼재 |
| 처리속도 | 40.6초/page | **9.1초/page** |

### 목표: True Hybrid

PP-Structure의 레이아웃 구조 + CLOVA의 텍스트 품질을 결합한다.

```
preprocess_page(image)
    → masked_image   (figure 마스킹된 이미지)
    → regions        (PP-Structure bbox: table/text/figure)
         ↓
clova_ocr_page(masked_image, layout_regions=regions)
    → 표 영역  : reconstruct_table_from_fields(fields, table_bbox)
    → 텍스트 영역 : _fields_to_lines(region_fields)  [좌→우, 위→아래 정렬]
    → 이미지 영역 : 자동 skip (figure는 masked_image에서 이미 흰색)
```

### 이미 구현된 것 — 재사용

- `src/parser/ocr_preprocessor.py` → `preprocess_page()` ✅
- `src/parser/clova_ocr.py` → `clova_ocr_page(layout_regions=...)` ✅
- `src/parser/clova_ocr.py` → `reconstruct_table_from_fields()` ✅
- `src/parser/clova_ocr.py` → `_normalize_layout_region()` → `LayoutRegion` 객체 처리 가능 ✅
- `scripts/run_clova_local.py` → `_block_quality()`, `_header_score()`, `_build_metrics()`, `_serialize_blocks()`, `_update_summary()`, `parse_pages()` ✅

**새로 구현할 코드는 두 함수를 호출하는 스크립트 뼈대뿐이다.**

---

## 구현 명세

### 파일: `scripts/run_true_hybrid_local.py` (신규)

#### CLI 인터페이스

```bash
python scripts/run_true_hybrid_local.py \
    --doc 실무가이드 \
    --pages 60-70 \
    --output-dir reports/ocr_compare/ \
    --timeout 60
```

인수: `--doc` / `--pages` / `--output-dir` / `--timeout` — `run_clova_local.py`와 동일.

#### 핵심 구현 — `run_true_hybrid_local()` 함수

```python
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image

from src.parser.ocr_preprocessor import preprocess_page
from src.parser.clova_ocr import clova_ocr_page, ClovaOcrError

# run_clova_local.py에서 재사용
from scripts.run_clova_local import (
    parse_pages,
    _block_quality,
    _header_score,
    _build_metrics,
    _serialize_blocks,
    _update_summary,
)

def run_true_hybrid_local(doc_short: str, pages_arg: str, output_dir: Path, timeout_sec: int) -> None:
    doc_dir = output_dir / doc_short
    pages = parse_pages(pages_arg)
    results = []

    for page_no in pages:
        original_path = doc_dir / f"p{page_no:03d}_original.png"
        if not original_path.exists():
            result = _write_page_json(doc_short, doc_dir, page_no, 0.0,
                                      status="SKIPPED",
                                      error=f"원본 이미지 없음: {original_path.name}",
                                      blocks=[], figures=[])
            results.append(result)
            continue

        figure_save_dir = doc_dir / f"p{page_no:03d}_true_hybrid_figures"
        page_name = f"p{page_no:03d}"
        started = time.perf_counter()
        try:
            with Image.open(original_path) as image:
                image.load()
                # Step 1: PP-Structure 레이아웃 탐지 + figure 마스킹
                prep = preprocess_page(image,
                                       figure_save_dir=figure_save_dir,
                                       page_name=page_name)
                # Step 2: CLOVA API (레이아웃 안내 포함)
                blocks = clova_ocr_page(
                    prep.masked_image,
                    page_name=page_name,
                    layout_regions=prep.regions,   # LayoutRegion 리스트
                    timeout_sec=timeout_sec,
                )

            elapsed = time.perf_counter() - started
            figures = [
                {"bbox": list(r.bbox), "saved_path": str(fp.relative_to(doc_dir))}
                for r, fp in zip(
                    [reg for reg in prep.regions if reg.block_type == "figure"],
                    prep.figure_paths,
                )
            ]
            block_payload = _serialize_blocks(blocks)
            result = _write_page_json(doc_short, doc_dir, page_no, elapsed,
                                      status="SUCCESS", error=None,
                                      blocks=block_payload, figures=figures)
            results.append(result)
            print(f"[run_true_hybrid_local] p{page_no:03d} -> SUCCESS ({len(block_payload)}블록, {elapsed:.1f}초)")

        except ClovaOcrError as exc:
            elapsed = time.perf_counter() - started
            result = _write_page_json(doc_short, doc_dir, page_no, elapsed,
                                      status="SKIPPED", error=str(exc),
                                      blocks=[], figures=[])
            results.append(result)
            print(f"[run_true_hybrid_local] p{page_no:03d} -> SKIPPED ({exc})")

    _update_summary(output_dir, doc_short, results, engine_key="true_hybrid")
```

#### `_write_page_json()` 함수

```python
def _write_page_json(doc_short, doc_dir, page_no, elapsed_sec, *, status, error, blocks, figures):
    metrics = _build_metrics(blocks, figure_blocks=len(figures))
    payload = {
        "engine": "true_hybrid",
        "doc_short": doc_short,
        "page_no": page_no,
        "elapsed_sec": round(elapsed_sec, 3),
        "status": status,
        "error": error,
        "original_image": f"p{page_no:03d}_original.png",
        "masked_image": f"p{page_no:03d}_masked.png",   # 호환성 유지
        "figures": figures,
        "blocks": blocks,
        "metrics": metrics,
    }
    out = doc_dir / f"p{page_no:03d}_true_hybrid.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
```

#### `_update_summary()` 확장

`run_clova_local.py`의 `_update_summary()`는 `engines.clova`를 하드코딩한다. `run_true_hybrid_local.py`에서는 `engine_key` 파라미터를 추가하여 `engines.true_hybrid`를 갱신하도록 수정한다.

**방법 1** (추천): `run_clova_local.py`의 `_update_summary()`에 `engine_key: str = "clova"` 인수를 추가하고 `run_true_hybrid_local.py`에서 `engine_key="true_hybrid"`로 호출.

```python
# run_clova_local.py 수정: 시그니처 변경
def _update_summary(output_dir: Path, doc_short: str, clova_results: list[dict],
                    engine_key: str = "clova") -> None:
    ...
    summary["engines"][engine_key] = { ... }
    if engine_key == "clova":
        summary["clova_rerun_at"] = ...
    else:
        summary[f"{engine_key}_run_at"] = ...
```

**방법 2** (독립): `run_true_hybrid_local.py` 내부에 별도 `_update_summary_true_hybrid()` 구현. 코드 중복 발생하므로 방법 1을 권장.

---

### 출력 파일 구조

```
reports/ocr_compare/실무가이드/
  p060_true_hybrid.json   ← 신규
  p061_true_hybrid.json
  ...
  p070_true_hybrid.json
  p063_true_hybrid_figures/
    p063_fig00.png
  p064_true_hybrid_figures/
    ...
  summary.json             ← engines.true_hybrid 섹션 추가
```

기존 `p0{xx}_hybrid.json`, `p0{xx}_clova.json` 파일은 **절대 수정하지 않는다**.

---

### 단위 테스트: `tests/test_run_true_hybrid_local.py` (신규)

외부 API와 PP-Structure 엔진은 모두 mock 처리한다.

**테스트 항목 4개:**

1. **`test_run_true_hybrid_success()`** — `preprocess_page`와 `clova_ocr_page` 모두 mock, SUCCESS 경로 확인:
   - `p0{xx}_true_hybrid.json` 생성됨
   - `engine` 필드가 `"true_hybrid"`
   - `blocks` 직렬화 정상

2. **`test_run_true_hybrid_clova_error()`** — `clova_ocr_page`에서 `ClovaOcrError` 발생 시 SKIPPED 처리 확인

3. **`test_run_true_hybrid_missing_png()`** — 원본 PNG 없을 때 SKIPPED 처리 확인

4. **`test_update_summary_true_hybrid_key()`** — `_update_summary(... engine_key="true_hybrid")` 호출 시 `summary.json`의 `engines.true_hybrid`만 갱신되고 `engines.clova`, `engines.hybrid` 섹션은 보존됨

---

## 검증 순서

```bash
# 1. 기존 테스트 전체 통과 확인 (run_clova_local.py 수정으로 인한 회귀 검사)
pytest -q

# 2. 신규 테스트
pytest tests/test_run_true_hybrid_local.py -q

# 3. import 확인 (DNS 없어도 됨)
python -c "import scripts.run_true_hybrid_local; print('import OK')"
```

**Codex 환경에서 `run_true_hybrid_local.py`를 직접 실행하지 않는다** — DNS 차단으로 CLOVA 호출이 불가.

---

## 보고서 작성 요구사항

구현 완료 후 `docs/41_CODEX_REPORT_TRUE_HYBRID.md`를 작성한다.

**필수 포함 항목:**

1. `pytest -q` 결과 (전체 통과 수)

2. 사용자가 즉시 실행할 수 있는 명령어:
   ```bash
   python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 60-70
   ```

3. `run_clova_local.py` 수정 사항 명시 (`_update_summary` 시그니처 변경 여부)

4. 구현 시 판단 사항

---

## 주의사항

- `find_dotenv()` 사용 금지 → `Path(__file__).parent.parent / ".env"` 사용
- `preprocess_page()`는 PP-Structure 엔진을 초기화하므로 첫 페이지가 느릴 수 있음 — 정상 동작
- `figure_save_dir`은 `p{page_no:03d}_true_hybrid_figures`로 지정하여 기존 hybrid figures와 디렉터리 충돌 방지
- `_update_summary()` 수정 시 기존 `run_clova_local.py`의 5개 테스트(`test_run_clova_local.py`)가 모두 통과해야 함
- HTML 결과지 재생성은 Codex 범위 외 — 기획·검토 에이전트가 담당
