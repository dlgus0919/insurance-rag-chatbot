# Codex 명세 — OCR 비교 파이프라인 최종 통합

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)  
통합 대상: `docs/37_CODEX_SPEC_OCR_HYBRID.md`, `docs/38_CODEX_SPEC_OCR_TABLE_RECONSTRUCT.md`  
선행 보고서: `docs/35_OCR_PIPELINE_REPORT.md`, `docs/36_OCR_V2_REPORT.md`

---

## 1. 목표

D6 실무가이드 스캔 PDF에 대해 두 OCR 엔진의 **표 구조 인식 품질을 비교**한다.

| 엔진 | 방식 |
|------|------|
| **Hybrid OCR** | PP-Structure bbox 탐지 + PaddleOCR `lang='korean'` 텍스트 인식 |
| **CLOVA OCR** | 전체 페이지 1회 CLOVA API 호출 + field bbox 좌표 기반 표 구조 재구성 |

비교 결과는 **기획·검토 에이전트(Claude)가 HTML 시각화 결과지를 생성할 수 있도록** 구조화된 JSON과 이미지 파일로 저장한다.

---

## 2. 공통 전처리: 이미지 마스킹

### 2-1. 배경

D6에는 표 셀 안에 해부학 도식·삽화가 포함되어 있다. 이 그림 영역을 OCR에 그대로 넘기면 그림의 픽셀 패턴이 노이즈 문자로 오인식된다.

### 2-2. 처리 방침

- 그림 영역(figure bbox)은 흰색으로 마스킹하여 OCR 전에 제거한다
- 마스킹 전 원본 figure crop을 PNG로 저장한다 (향후 활용 가능성 보존)
- **캡션 생성은 수행하지 않는다** (현 단계 제외)

### 2-3. 파일: `src/parser/ocr_preprocessor.py` (신규)

```python
"""OCR 공통 전처리: PP-Structure 레이아웃 탐지 + figure 마스킹."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

from src.parser.ocr_engine import _get_structure_engine

FIGURE_SHRINK_PX = 8  # 마스킹 박스를 안쪽으로 축소하는 픽셀 수 (인접 텍스트 보호)


@dataclass
class LayoutRegion:
    block_type: str          # "table" | "text" | "title" | "figure"
    bbox: tuple[int, int, int, int]   # (x1, y1, x2, y2)


@dataclass
class PreprocessResult:
    original_image: Image.Image
    masked_image: Image.Image          # figure 흰색 마스킹 적용
    regions: list[LayoutRegion]
    figure_paths: list[Path]           # 저장된 figure PNG 경로 목록


def preprocess_page(
    image: Image.Image,
    figure_save_dir: Path | None = None,
    page_name: str = "page",
) -> PreprocessResult:
    """PP-Structure로 레이아웃을 탐지하고, figure 영역을 마스킹한다.

    Args:
        image: 처리할 페이지 PIL Image
        figure_save_dir: figure PNG 저장 디렉터리. None이면 저장 안 함.
        page_name: 저장 파일명 접두어

    Returns:
        PreprocessResult (masked_image, regions, figure_paths)
    """
    img_array = np.array(image)
    structure_results = _get_structure_engine()(img_array)

    regions: list[LayoutRegion] = []
    figure_bboxes: list[tuple[int, int, int, int]] = []
    figure_paths: list[Path] = []

    for r in structure_results:
        bbox_raw = r.get("bbox")
        if bbox_raw is None:
            continue
        x1, y1, x2, y2 = (int(v) for v in bbox_raw)
        block_type: str = r.get("type", "text")
        regions.append(LayoutRegion(block_type=block_type, bbox=(x1, y1, x2, y2)))

        if block_type == "figure":
            figure_bboxes.append((x1, y1, x2, y2))

            # figure crop 저장
            if figure_save_dir is not None:
                figure_save_dir.mkdir(parents=True, exist_ok=True)
                fig_idx = len(figure_paths)
                fig_path = figure_save_dir / f"{page_name}_fig{fig_idx:02d}.png"
                crop = image.crop((x1, y1, x2, y2))
                crop.save(fig_path)
                figure_paths.append(fig_path)

    # figure 영역 마스킹 (FIGURE_SHRINK_PX 만큼 축소하여 인접 텍스트 보호)
    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    for x1, y1, x2, y2 in figure_bboxes:
        s = FIGURE_SHRINK_PX
        draw.rectangle([x1 + s, y1 + s, x2 - s, y2 - s], fill=(255, 255, 255))

    return PreprocessResult(
        original_image=image,
        masked_image=masked,
        regions=regions,
        figure_paths=figure_paths,
    )
```

---

## 3. 엔진 A: Hybrid OCR

### 3-1. 방식

PP-Structure bbox로 레이아웃을 탐지한 뒤, 마스킹된 이미지의 각 region crop에 `PaddleOCR(lang='korean')`을 적용한다.

- 표 영역: PP-Structure 셀 bbox 탐지 → 각 셀 crop → Korean OCR
- 텍스트 영역: 전체 region crop → Korean OCR
- 이미지 영역: 건너뜀 (마스킹 + PNG 저장은 전처리에서 완료)

### 3-2. 파일: `src/parser/hybrid_ocr.py` (신규 또는 기존 대체)

```python
"""Hybrid OCR: PP-Structure 레이아웃 + PaddleOCR Korean 텍스트 인식."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from PIL import Image

from src.parser.ocr_engine import (
    LayoutBlock, _get_korean_ocr, _get_structure_engine,
    _easyocr_fallback, _table_html_to_text, _table_html_to_json,
)
from src.parser.ocr_postprocess import normalize_korean
from src.parser.ocr_preprocessor import PreprocessResult


def hybrid_ocr_page(prep: PreprocessResult) -> list[LayoutBlock]:
    """전처리 결과를 받아 Hybrid OCR을 수행한다."""
    korean_ocr = _get_korean_ocr()
    blocks: list[LayoutBlock] = []

    for region in prep.regions:
        if region.block_type == "figure":
            continue  # 전처리에서 이미 저장됨

        x1, y1, x2, y2 = region.bbox
        region_crop = prep.masked_image.crop((x1, y1, x2, y2))

        if region.block_type == "table":
            block = _hybrid_table_block(region_crop, region.bbox, korean_ocr)
        else:
            block = _hybrid_text_block(region_crop, region.bbox, region.block_type, korean_ocr)

        if block is not None:
            blocks.append(block)

    return blocks if blocks else _easyocr_fallback(prep.masked_image)


def _hybrid_text_block(crop, bbox, block_type, korean_ocr) -> LayoutBlock | None:
    arr = np.array(crop)
    result = korean_ocr.ocr(arr, cls=False)
    lines = []
    if result and result[0]:
        for line in result[0]:
            if line and len(line) >= 2:
                lines.append(normalize_korean(line[1][0]))
    text = "\n".join(lines)
    if not text.strip():
        return None
    return LayoutBlock(
        block_type=block_type, bbox=bbox, text=text,
        confidence=None, source_method="ocr_ppstructure_twopass",
    )


def _hybrid_table_block(crop, bbox, korean_ocr) -> LayoutBlock | None:
    """PP-Structure 셀 bbox + PaddleOCR Korean으로 표 블록 생성."""
    from src.parser.ocr_engine import _get_structure_engine
    from bs4 import BeautifulSoup

    arr = np.array(crop)
    table_result = _get_structure_engine()(arr)

    if not table_result or table_result[0].get("type") != "table":
        return _hybrid_text_block(crop, bbox, "table", korean_ocr)

    res = table_result[0].get("res", {})
    cell_bboxes = res.get("cell_bbox", [])
    html_raw = res.get("html", "")

    if not cell_bboxes:
        return _hybrid_text_block(crop, bbox, "table", korean_ocr)

    cell_texts: list[str] = []
    for cb in cell_bboxes:
        cx1, cy1, cx2, cy2 = int(cb[0]), int(cb[1]), int(cb[2]), int(cb[3])
        cx1, cy1 = max(0, cx1), max(0, cy1)
        cx2 = min(cx2, crop.width)
        cy2 = min(cy2, crop.height)
        if cx2 <= cx1 or cy2 <= cy1:
            cell_texts.append("")
            continue
        cell_crop = crop.crop((cx1, cy1, cx2, cy2))
        cell_arr = np.array(cell_crop)
        cell_result = korean_ocr.ocr(cell_arr, cls=False)
        words = []
        if cell_result and cell_result[0]:
            for line in cell_result[0]:
                if line and len(line) >= 2:
                    words.append(normalize_korean(line[1][0]))
        cell_texts.append(" ".join(words))

    # HTML에 Korean 텍스트 주입
    soup = BeautifulSoup(html_raw, "lxml")
    for i, td in enumerate(soup.find_all("td")):
        td.clear()
        td.string = cell_texts[i] if i < len(cell_texts) else ""
    html_final = str(soup)
    table_json = _table_html_to_json(html_final)
    text = _table_html_to_text(html_final)

    return LayoutBlock(
        block_type="table", bbox=bbox, text=text,
        html=html_final, table_json=table_json,
        confidence=None, source_method="ocr_ppstructure_twopass",
    )
```

---

## 4. 엔진 B: CLOVA OCR (bbox 기반 표 재구성)

### 4-1. 방식

마스킹된 전체 페이지 이미지를 CLOVA OCR에 1회 호출한다. 반환된 358개 field의 (x, y) 좌표를 분석해 표 구조를 재구성한다.

- **CLOVA API 호출**: 페이지당 1회 (셀 단위 호출 없음)
- **표 구조 재구성**: Y좌표 클러스터링 → 행 그룹핑 / X좌표 클러스터링 → 열 탐지
- 표 영역 판별에는 PP-Structure bbox를 활용한다 (전처리 결과 재사용)

### 4-2. 파일: `src/parser/clova_ocr.py` (기존 파일 수정)

#### 타임아웃 및 재시도 수정

```python
_REQUEST_TIMEOUT_SEC = 60   # 30 → 60
_MAX_RETRIES = 1

# requests.post 호출부를 재시도 루프로 감싼다
for attempt in range(_MAX_RETRIES + 1):
    try:
        response = requests.post(..., timeout=_REQUEST_TIMEOUT_SEC)
        response.raise_for_status()
        break
    except requests.Timeout as exc:
        if attempt < _MAX_RETRIES:
            continue
        raise ClovaOcrError(f"타임아웃 재시도 초과: {exc}") from exc
    except requests.RequestException as exc:
        raise ClovaOcrError(f"API 요청 실패: {exc}") from exc
```

#### bbox 기반 표 재구성 함수 추가 (38번 명세 M-ocr-v4-2 전문 적용)

`_field_center_y`, `_field_center_x`, `_field_bbox`, `_group_fields_into_rows`,
`_detect_column_x_ranges`, `_assign_fields_to_columns`, `reconstruct_table_from_fields`
함수를 38번 명세 그대로 추가한다.

#### `clova_ocr_page()` 시그니처 변경

```python
def clova_ocr_page(
    image: Image.Image,
    page_name: str = "page",
    layout_regions: list | None = None,  # PreprocessResult.regions
) -> list[LayoutBlock]:
    """
    layout_regions 가 주어지면:
      - table 영역: reconstruct_table_from_fields() 로 구조 재구성
      - text/title 영역: fields 필터링 후 lineBreak 기반 텍스트 병합
      - figure 영역: 건너뜀
    layout_regions 가 None이면:
      - 전체 fields를 단일 텍스트 블록으로 반환 (기존 동작)
    """
```

---

## 5. 비교 실행 스크립트

### 5-1. 파일: `scripts/ocr_compare.py` (기존 수정)

#### CLI 변경

```
--engines  {hybrid|clova|all}   (기본: all)
--timeout  int                  CLOVA API 타임아웃 초 (기본: 60)
--save-images                   원본·마스킹 이미지 PNG 저장 여부 (기본: True)
```

`twopass` 옵션 제거. 이번 비교는 `hybrid` vs `clova` 로 단순화한다.

#### 실행 흐름

```python
for page_no in page_indices:
    image = extract_page_image(source.path, page_no)

    # 공통 전처리 (PP-Structure + figure 마스킹)
    figure_dir = output_dir / doc_short / f"p{page_no:03d}_figures"
    prep = preprocess_page(image, figure_save_dir=figure_dir, page_name=f"p{page_no:03d}")

    # 이미지 저장
    image.save(output_dir / doc_short / f"p{page_no:03d}_original.png")
    prep.masked_image.save(output_dir / doc_short / f"p{page_no:03d}_masked.png")

    for engine in engines:
        t0 = time.perf_counter()
        if engine == "hybrid":
            blocks = hybrid_ocr_page(prep)
        elif engine == "clova":
            blocks = clova_ocr_page(
                prep.masked_image,
                page_name=f"p{page_no:03d}",
                layout_regions=prep.regions,
            )
        elapsed = time.perf_counter() - t0

        # 결과 JSON 저장
        result = _build_page_result(engine, page_no, blocks, prep, elapsed)
        json_path = output_dir / doc_short / f"p{page_no:03d}_{engine}.json"
        json_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
```

### 5-2. 저장 JSON 구조 (HTML 시각화 기준)

`{engine}_p{page:03d}.json` 파일의 구조를 아래와 같이 확정한다.  
Claude가 이 파일과 이미지를 읽어 HTML 결과지를 생성한다.

```json
{
  "engine": "hybrid",
  "doc_short": "실무가이드",
  "page_no": 66,
  "elapsed_sec": 12.3,
  "original_image": "p066_original.png",
  "masked_image": "p066_masked.png",
  "figures": [
    {"bbox": [100, 200, 400, 600], "saved_path": "p066_figures/p066_fig00.png"}
  ],
  "blocks": [
    {
      "block_type": "table",
      "bbox": [80, 250, 2200, 2800],
      "text": "수술종수 | 수술명 | 수술해설\n1-3종 | 반월판연골 봉합술 | ...",
      "table_json": {
        "headers": ["수술종수", "수술명", "수술해설", "col_4", "col_5"],
        "rows": [
          ["1-3종", "반월판연골 봉합술", "반월판의 급성손상이 ...", "N", "2"]
        ]
      },
      "source_method": "ocr_ppstructure_twopass",
      "quality": {
        "korean_ratio": 0.604,
        "noise_ratio": 0.050,
        "grade": "PASS"
      }
    },
    {
      "block_type": "text",
      "bbox": [80, 100, 2200, 240],
      "text": "제1장 수술분류표 해설",
      "table_json": null,
      "source_method": "ocr_ppstructure_twopass",
      "quality": {
        "korean_ratio": 0.71,
        "noise_ratio": 0.02,
        "grade": "PASS"
      }
    }
  ],
  "metrics": {
    "total_blocks": 3,
    "table_blocks": 1,
    "text_blocks": 2,
    "figure_blocks": 1,
    "avg_korean_ratio": 0.58,
    "avg_noise_ratio": 0.06,
    "grade_pass": 2,
    "grade_marginal": 1,
    "grade_fail": 0,
    "header_score_avg": 0.40
  }
}
```

`quality` 계산: 기존 `scripts/ocr_verify.quality_metrics()` 재활용.  
`header_score_avg`: 표 블록의 `score_table_header()` 평균.

### 5-3. `summary.json` 구조

```json
{
  "run_at": "2026-05-08T11:30:00",
  "doc_short": "실무가이드",
  "pages": [60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70],
  "engines": {
    "hybrid": {
      "avg_elapsed_sec": 47.2,
      "avg_korean_ratio": 0.543,
      "avg_noise_ratio": 0.114,
      "table_blocks": 10,
      "header_score_avg": 0.280,
      "grade": {"PASS": 7, "MARGINAL": 0, "FAIL": 4}
    },
    "clova": {
      "avg_elapsed_sec": 7.1,
      "avg_korean_ratio": 0.721,
      "avg_noise_ratio": 0.038,
      "table_blocks": 10,
      "header_score_avg": 0.0,
      "grade": {"PASS": 10, "MARGINAL": 1, "FAIL": 0}
    }
  }
}
```

---

## 6. 단위 테스트

### 6-1. `tests/test_ocr_preprocessor.py` (신규)

| 테스트 | 내용 |
|--------|------|
| `test_preprocess_no_figures` | figure 없는 페이지 → masked_image = original_image (픽셀 동일) |
| `test_preprocess_figure_masking` | mock figure bbox → 해당 영역이 흰색으로 채워졌는지 확인 |
| `test_preprocess_figure_saved` | figure_save_dir 지정 시 PNG 파일 생성 확인 |
| `test_preprocess_shrink` | FIGURE_SHRINK_PX 만큼 축소되는지 경계 픽셀 확인 |

### 6-2. `tests/test_clova_ocr.py` 추가 테스트 (38번 명세 M-ocr-v4-5 전문 적용)

`_group_fields_into_rows`, `_detect_column_x_ranges`, `_assign_fields_to_columns`,
`reconstruct_table_from_fields`, `clova_ocr_page(layout_regions=...)` 테스트.

### 6-3. `tests/test_hybrid_ocr.py` (신규)

| 테스트 | 내용 |
|--------|------|
| `test_hybrid_text_block` | Korean OCR mock → LayoutBlock 반환 |
| `test_hybrid_figure_skip` | figure region은 blocks에 포함되지 않음 |
| `test_hybrid_fallback` | structure_results 비어 있을 때 easyocr 폴백 (mock) |

---

## 7. 검증 및 보고서

### 실행 순서

```bash
# 1. 단위 테스트
pytest -q

# 2. D6 60~70p 비교 실행 (환경변수 필요)
python scripts/ocr_compare.py \
  --doc 실무가이드 \
  --pages 60-70 \
  --engines all \
  --output-dir reports/ocr_compare/

# 3. (선택) D7 일부 확인
python scripts/ocr_compare.py \
  --doc 상담사례집 \
  --pages 0-4 \
  --engines all \
  --output-dir reports/ocr_compare/
```

### 보고서 `docs/39_OCR_COMPARE_REPORT.md` 필수 포함 항목

1. `pytest -q` 결과
2. D6 60~70p 기준 `summary.json` 내용 (그대로 인용)
3. p066 표 헤더 비교

| 엔진 | 헤더 인식 결과 | 키워드 점수 |
|------|--------------|------------|
| Hybrid | (실제 결과) | (점수/5) |
| CLOVA | (실제 결과) | (점수/5) |

4. figure 마스킹 효과 — 마스킹 전후 p066 한글 비율 변화 (가능하면)
5. 처리 속도 비교 (엔진별 페이지당 평균 초)
6. 권장 엔진 결론

### HTML 시각화용 파일 체크리스트

보고서 작성 후 아래 파일이 `reports/ocr_compare/실무가이드/` 에 모두 존재하는지 확인한다:

```
p060_original.png  p060_hybrid.json  p060_clova.json
p061_original.png  p061_hybrid.json  p061_clova.json
...
p070_original.png  p070_hybrid.json  p070_clova.json
summary.json
```

이 파일들이 준비되면 기획·검토 에이전트(Claude)가 HTML 비교 결과지를 생성한다.  
**Codex는 HTML을 직접 생성하지 않는다.**

---

## 8. 수정 대상 파일 최종 목록

| 파일 | 변경 | 내용 |
|------|------|------|
| `src/parser/ocr_preprocessor.py` | **신규** | PP-Structure 레이아웃 탐지 + figure 마스킹 |
| `src/parser/hybrid_ocr.py` | **신규** | PP-Structure bbox + PaddleOCR Korean |
| `src/parser/clova_ocr.py` | **수정** | timeout 60s, 재시도, bbox 재구성 함수, `layout_regions` 인수 |
| `scripts/ocr_compare.py` | **수정** | `hybrid`/`clova` 엔진, `--timeout`, 구조화 JSON 출력 |
| `tests/test_ocr_preprocessor.py` | **신규** | 전처리 단위 테스트 |
| `tests/test_hybrid_ocr.py` | **신규** | Hybrid OCR 단위 테스트 |
| `tests/test_clova_ocr.py` | **수정** | bbox 재구성 테스트 추가 |
| `docs/39_OCR_COMPARE_REPORT.md` | **신규** | 구현·비교 결과 보고서 |

---

## 9. 제외 범위

- figure 캡션 생성 (Vision LLM 활용) — 명시적 보류
- D6/D7 전체 OCR 재처리 및 RAG 인덱싱 — 비교 결과 확인 후 별도 명세
- CLOVA 커스텀 도메인 모델 학습
- `twopass` 엔진(구버전 Two-Pass) 비교 포함 — 현 Hybrid로 대체됨

---

## 10. 코드 검토 교정사항 ← 구현 전 반드시 확인

명세 작성 후 기존 코드를 검토한 결과 아래 세 가지를 수정해야 한다.

### 교정 1: `run_easyocr_fallback` 함수명

명세 섹션 3의 `hybrid_ocr.py`에서 `_easyocr_fallback` 으로 import하도록 기술했으나,
`src/parser/ocr_engine.py`의 실제 함수명은 `run_easyocr_fallback`(line 534)이다.

```python
# 잘못됨 (명세 원문)
from src.parser.ocr_engine import _easyocr_fallback

# 올바름
from src.parser.ocr_engine import run_easyocr_fallback
```

모든 호출부에서 `run_easyocr_fallback(prep.masked_image)` 로 수정할 것.

### 교정 2: `_hybrid_table_block` 재구현 불필요 — `_extract_table_twopass` 재활용

`src/parser/ocr_engine.py`에 `_extract_table_twopass(region_array, korean_ocr, offset)`
함수(line 373)가 이미 완전히 구현되어 있다. 이 함수는 명세의 `_hybrid_table_block`이
하려는 작업(PP-Structure 셀 bbox + Korean OCR + HTML/JSON 재조립)을 **그대로** 수행한다.

`hybrid_ocr.py`의 `_hybrid_table_block`을 새로 구현하지 말고 아래와 같이 위임한다:

```python
from src.parser.ocr_engine import (
    _extract_table_twopass, _get_korean_ocr,
    _table_html_to_text, run_easyocr_fallback,
)

def _hybrid_table_block(crop: Image.Image, bbox, korean_ocr) -> LayoutBlock | None:
    arr = np.array(crop)
    x1, y1 = bbox[0], bbox[1]
    html, table_json, _ = _extract_table_twopass(arr, korean_ocr, offset=(x1, y1))
    text = _table_html_to_text(html)
    if not text.strip():
        return None
    return LayoutBlock(
        block_type="table", bbox=bbox, text=text,
        html=html, table_json=table_json,
        confidence=None, source_method="ocr_ppstructure_twopass",
    )
```

### 교정 3: `table_json` rows 형식 통일

`_extract_table_twopass` 및 `_table_html_to_json`은 rows를
`[{"헤더1": "값", "헤더2": "값", ...}, ...]` (dict 리스트) 형식으로 반환한다.

반면 `clova_ocr.py`의 `_table_to_json` 및 `reconstruct_table_from_fields`는 rows를
`[["값1", "값2", ...], ...]` (list 리스트) 형식으로 반환한다.

**통일 기준**: `_table_html_to_json`의 dict 리스트 형식을 기준으로 통일한다.
`clova_ocr.py`의 `reconstruct_table_from_fields` 및 관련 함수에서
rows 반환 형식을 `[dict(zip(headers, row)) for row in grid[1:]]` 로 변경할 것.

이렇게 해야 `ocr_compare.py`의 `_build_page_result()`에서 두 엔진 결과를
동일한 JSON 구조로 처리할 수 있다.
