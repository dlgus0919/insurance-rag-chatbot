# Codex 명세 — OCR 엔진 개선 v3: Hybrid OCR + CLOVA 타임아웃 수정

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)  
선행 보고서: `docs/36_OCR_V2_REPORT.md`

---

## 배경: 비교 테스트 결과 분석

### 엔진별 특성 확인

D6 p066 (수술분류표) 직접 비교:

| 항목 | Two-Pass OCR | CLOVA General OCR |
|------|-------------|-------------------|
| 표 구조 (셀 grid) | ✅ 있음 | ❌ 없음 (`tables=0`) |
| 한글 텍스트 정확도 | 보통 (오인식 다수) | **우수** (오인식 거의 없음) |
| 예시 오인식 | `신경철Ganglion적출술관절부` | `신경절(Ganglion)적출술(관절부)` ✅ |
| 예시 오인식 | `석술해내는 수출을 말한다` | `적출해내는 수술을 말한다` ✅ |
| 예시 오인식 | `피무를 설개하여 내뢰골에` | `피부를 절개하여 대퇴골에` ✅ |
| 예시 오인식 | `요골 골렁봉Osteocystohma` | 정확한 의학 용어 ✅ |
| 처리 속도 | ~47초/페이지 | ~7초/페이지 |

**핵심 결론:**
- Two-Pass는 **표 구조(셀 grid)**를 잡지만 **텍스트 품질이 낮다**
- CLOVA는 **텍스트 품질이 월등히 높지만** **표 구조를 반환하지 않는다**

### 최적 전략: Hybrid OCR

```
PP-Structure(lang='ch')
    → 레이아웃 탐지 (text / table / figure 영역 bbox)
    → 표 셀 bbox 구조 탐지

CLOVA OCR General (per-region 호출)
    → 각 region crop → CLOVA API 호출 → 고품질 한글 텍스트

결합:
    표 영역: PP-Structure 셀 bbox 구조 + CLOVA 텍스트 → 정확한 표 JSON
    본문 영역: CLOVA 텍스트 → 고품질 RAG 청크
    이미지 영역: PNG 저장 (캡션 플레이스홀더)
```

---

## 구현 명세

### M-ocr-v3-1: CLOVA OCR 타임아웃 수정

**파일:** `src/parser/clova_ocr.py`

변경 내용:
1. `_REQUEST_TIMEOUT_SEC = 30` → `_REQUEST_TIMEOUT_SEC = 60`
2. 타임아웃 재시도 1회 추가

```python
_REQUEST_TIMEOUT_SEC = 60
_MAX_RETRIES = 1

def clova_ocr_page(image: Image.Image, page_name: str = "page") -> list[LayoutBlock]:
    ...
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(
                CLOVA_OCR_URL,
                headers={"X-OCR-SECRET": CLOVA_OCR_SECRET},
                files={...},
                timeout=_REQUEST_TIMEOUT_SEC,
            )
            response.raise_for_status()
            break  # 성공 시 루프 종료
        except requests.Timeout as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                print(f"[clova_ocr] timeout, retrying ({attempt + 1}/{_MAX_RETRIES})...")
                continue
            raise ClovaOcrError(f"CLOVA OCR API 타임아웃 (재시도 {_MAX_RETRIES}회 초과): {exc}") from exc
        except requests.RequestException as exc:
            raise ClovaOcrError(f"CLOVA OCR API 요청 실패: {exc}") from exc
    ...
```

3. `scripts/ocr_compare.py`에 `--timeout` CLI 인수 추가:
```python
parser.add_argument("--timeout", type=int, default=60,
                    help="CLOVA OCR API 타임아웃 초 (기본 60)")
```
`clova_ocr_page()` 호출 시 timeout 인수로 전달 (함수 시그니처에도 추가).

---

### M-ocr-v3-2: Hybrid OCR 엔진 구현

**파일 신규 생성:** `src/parser/hybrid_ocr.py`

```python
"""Hybrid OCR: PP-Structure 레이아웃 + CLOVA OCR 텍스트."""
```

**전략:**
- PP-Structure(`lang='ch'`) → 레이아웃 bbox 탐지 (표/텍스트/이미지 영역 분리)
- 각 region crop 이미지 → `clova_ocr_page(region_image)` 호출
- 표 영역의 경우: PP-Structure 셀 bbox + CLOVA 텍스트를 병합하여 표 JSON 재구성

```python
from __future__ import annotations

import numpy as np
from PIL import Image

from src.parser.clova_ocr import ClovaOcrError, clova_ocr_page
from src.parser.ocr_engine import LayoutBlock, _get_structure_engine, _easyocr_fallback


def hybrid_ocr_page(image: Image.Image) -> list[LayoutBlock]:
    """PP-Structure 레이아웃 탐지 + CLOVA OCR 텍스트 인식."""
    img_array = np.array(image)
    structure_results = _get_structure_engine()(img_array)

    if not structure_results:
        return _easyocr_fallback(image)

    blocks: list[LayoutBlock] = []

    for region in structure_results:
        block_type = region.get('type', 'text')
        bbox = region.get('bbox')
        if bbox is None:
            continue

        x1, y1, x2, y2 = [int(v) for v in bbox]
        # 최소 크기 방어
        if x2 <= x1 or y2 <= y1:
            continue

        region_crop = image.crop((x1, y1, x2, y2))

        if block_type == 'figure':
            blocks.append(LayoutBlock(
                block_type='figure',
                bbox=(x1, y1, x2, y2),
                text='',
                confidence=None,
                source_method='ocr_hybrid',
            ))
            continue

        if block_type == 'table':
            block = _hybrid_table_block(region_crop, region, (x1, y1, x2, y2))
        else:
            block = _hybrid_text_block(region_crop, (x1, y1, x2, y2), block_type)

        if block is not None:
            blocks.append(block)

    if not blocks:
        return _easyocr_fallback(image)
    return blocks


def _hybrid_text_block(
    region_crop: Image.Image,
    bbox: tuple[int, int, int, int],
    block_type: str,
) -> LayoutBlock | None:
    """CLOVA OCR로 텍스트 영역 인식. 실패 시 None 반환."""
    try:
        clova_blocks = clova_ocr_page(region_crop, page_name=f"region_{bbox[0]}_{bbox[1]}")
        text = "\n".join(b.text for b in clova_blocks if b.text)
        if not text.strip():
            return None
        return LayoutBlock(
            block_type=block_type,
            bbox=bbox,
            text=text,
            confidence=clova_blocks[0].confidence if clova_blocks else None,
            source_method='ocr_hybrid',
        )
    except ClovaOcrError:
        return None


def _hybrid_table_block(
    region_crop: Image.Image,
    structure_region: dict,
    bbox: tuple[int, int, int, int],
) -> LayoutBlock | None:
    """PP-Structure 셀 구조 + CLOVA OCR 텍스트로 표 블록 생성."""
    from src.parser.ocr_engine import _table_html_to_text, _table_html_to_json
    from src.parser.ocr_postprocess import normalize_korean

    # 1) PP-Structure에서 셀 bbox 목록 추출
    res = structure_region.get('res', {})
    cell_bboxes: list[list[int]] = res.get('cell_bbox', [])
    html_raw: str = res.get('html', '')

    if not cell_bboxes:
        # 셀 bbox 없음 → 전체 region을 CLOVA 텍스트로 처리
        return _hybrid_text_block(region_crop, bbox, 'table')

    x1_off, y1_off = bbox[0], bbox[1]

    # 2) 각 셀 crop → CLOVA OCR로 텍스트 추출
    cell_texts: list[str] = []
    for cell_bbox in cell_bboxes:
        # cell_bbox: [x1, y1, x2, y2] (region 기준 좌표)
        cx1, cy1, cx2, cy2 = [int(v) for v in cell_bbox[:4]]
        cx1, cy1 = max(0, cx1), max(0, cy1)
        cx2 = min(cx2, region_crop.width)
        cy2 = min(cy2, region_crop.height)
        if cx2 <= cx1 or cy2 <= cy1:
            cell_texts.append('')
            continue
        cell_crop = region_crop.crop((cx1, cy1, cx2, cy2))
        try:
            clova_blocks = clova_ocr_page(
                cell_crop, page_name=f"cell_{x1_off + cx1}_{y1_off + cy1}"
            )
            raw_text = " ".join(b.text for b in clova_blocks if b.text).strip()
            cell_texts.append(normalize_korean(raw_text))
        except ClovaOcrError:
            cell_texts.append('')

    # 3) HTML에 CLOVA 텍스트 삽입하여 재구성
    html_reconstructed = _rebuild_html_with_texts(html_raw, cell_texts)
    table_json = _table_html_to_json(html_reconstructed)
    text = _table_html_to_text(html_reconstructed)

    return LayoutBlock(
        block_type='table',
        bbox=bbox,
        text=text,
        html=html_reconstructed,
        table_json=table_json,
        confidence=None,
        source_method='ocr_hybrid',
    )


def _rebuild_html_with_texts(html_raw: str, cell_texts: list[str]) -> str:
    """PP-Structure HTML의 각 <td>에 CLOVA 텍스트를 주입한다."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_raw, 'lxml')
    tds = soup.find_all('td')
    for i, td in enumerate(tds):
        td.clear()
        td.string = cell_texts[i] if i < len(cell_texts) else ''
    return str(soup)
```

**주의사항:**
- `_get_structure_engine()` 함수가 `ocr_engine.py`에서 module-level로 export되지 않으면 필요한 함수를 `hybrid_ocr.py`에 노출하도록 `ocr_engine.py` 수정
- `_table_html_to_text`, `_table_html_to_json` 함수도 동일하게 export 확인
- 셀 단위 CLOVA 호출은 API call이 많으므로 실 운영에서는 rate limit 고려 필요 (테스트 범위 내에서는 문제 없음)

---

### M-ocr-v3-3: 비교 스크립트에 hybrid 엔진 추가

**파일:** `scripts/ocr_compare.py` (수정)

1. `--engines` 선택지에 `hybrid` 추가:
```python
parser.add_argument(
    "--engines",
    choices=["twopass", "clova", "hybrid", "all"],
    default="all",
)
```

2. `all` 시 `["twopass", "clova", "hybrid"]` 실행

3. `_run_engine()` 함수에 hybrid 분기 추가:
```python
from src.parser.hybrid_ocr import hybrid_ocr_page

def _run_engine(engine: str, image: Image.Image, page_name: str) -> list[LayoutBlock]:
    if engine == "twopass":
        return ocr_page(image)
    if engine == "clova":
        return clova_ocr_page(image, page_name=page_name)
    if engine == "hybrid":
        return hybrid_ocr_page(image)
    raise ValueError(f"unknown engine: {engine}")
```

---

### M-ocr-v3-4: 단위 테스트

**파일:** `tests/test_hybrid_ocr.py` (신규)

```python
"""Hybrid OCR 단위 테스트 — 외부 API·엔진 호출은 mock 처리."""
```

테스트 항목:
1. `_rebuild_html_with_texts()`: cell_texts가 td보다 많을 때, 적을 때 경계 케이스
2. `hybrid_ocr_page()`: structure_results 비어 있을 때 easyocr 폴백 확인 (mock)
3. `_hybrid_text_block()`: ClovaOcrError 발생 시 None 반환 확인
4. `_hybrid_table_block()`: cell_bbox 비어 있을 때 텍스트 블록으로 폴백 확인

---

### M-ocr-v3-5: 검증 및 보고서

실행 순서:
```bash
# 1. 단위 테스트
pytest -q

# 2. 타임아웃 수정 확인 (전체 11페이지 완주 여부)
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines clova

# 3. Hybrid 테스트 (CLOVA 환경변수 설정 필요)
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines hybrid

# 4. 전체 비교
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines all
```

**보고서 `docs/37_OCR_HYBRID_REPORT.md`에 반드시 포함할 항목:**

1. D6 p066 표 헤더 3-way 비교

| 엔진 | 헤더 인식 결과 | 헤더 키워드 점수 |
|------|--------------|----------------|
| Two-Pass | (결과 기재) | (점수) |
| CLOVA General | (text만, 구조 없음) | — |
| **Hybrid** | (결과 기재) | (점수) |

2. 표 셀 텍스트 품질 비교 — p066 기준 5개 이상 셀
3. 전체 11페이지 처리 완주 여부 및 타임아웃 발생 페이지
4. 엔진별 처리 속도 (CLOVA/Hybrid는 API 레이턴시 포함)
5. `pytest -q` 결과
6. 권장 엔진 결론 및 `scripts/ocr_extract.py` 통합 방향 제안

---

## 제외 범위

- `scripts/ocr_extract.py` 전체 D6/D7 재처리 (이번 명세에서 제외, 비교 결과 확인 후 결정)
- CLOVA 커스텀 도메인 모델 학습
- D7 상담사례집 Hybrid 적용 (D6 검증 후 결정)
