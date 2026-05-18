# Codex 명세 — OCR 엔진 개선 v2: Two-Pass OCR + CLOVA OCR 비교 테스트

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)  
선행 명세: `docs/34_CODEX_SPEC_OCR_PIPELINE.md`  
선행 보고서: `docs/35_OCR_PIPELINE_REPORT.md`

---

## 배경: 이슈 분석

### 근본 원인

PaddleOCR 2.10.0의 `PPStructure` 클래스는 `lang="korean"` 인수를 받아들이지 않는다. 내부적으로 `ch`(중국어) 레이아웃 모델과 텍스트 인식 모델로 폴백한다. 결과:

| 항목 | 상태 | 영향 |
|------|------|------|
| 레이아웃 영역 탐지(bbox) | ✅ 정상 | 표/텍스트/이미지 영역 위치는 올바름 |
| 영역 내 텍스트 인식 | ❌ `ch` 모델 적용 | 한글이 `'舍'`, `col_2` 등 중국어/임의값으로 오인식 |
| 표 셀 bbox 구조 | ✅ 정상 | 셀 경계는 탐지됨 |
| 표 셀 텍스트 | ❌ `ch` 모델 적용 | 헤더 `수술종수 / 수술명 / 수술해설` → `['舍', 'col_2', 'col_3', 'col_4', 'col_5']` |

**핵심 통찰:** 레이아웃 탐지와 텍스트 인식을 분리하면 된다. PP-Structure의 `ch` 레이아웃 모델로 bbox를 추출하고, 각 region crop에 `PaddleOCR(lang='korean')`을 별도 적용하는 **Two-Pass 방식**으로 한글 인식 품질을 복구할 수 있다.

### 개선 전략

```
[현재] PPStructure(lang='ch') → 레이아웃 bbox + ch 텍스트 인식 (한글 오인식)
                                                                      ↓
[개선 A] PPStructure(lang='ch') → bbox 추출만  →  각 region crop → PaddleOCR(lang='korean') → 한글 텍스트
[개선 B] CLOVA OCR API → 한국어 특화 레이아웃+인식 (표 셀 구조 포함) → 비교 벤치마크
```

---

## 구현 명세

### M-ocr-v2-1: Two-Pass OCR 구현

**파일:** `src/parser/ocr_engine.py` (수정)

#### 변경 내용

현재 `ocr_engine.py`는 `PPStructure`를 단일 pass로 실행한다. 이를 **두 단계**로 분리한다:

**1단계: 레이아웃 감지 (기존 ch 모델 유지)**

```python
# 기존: PPStructure(lang='ch') 로 초기화 (레이아웃 bbox만 신뢰)
_structure_engine = PPStructure(
    table=True,
    ocr=False,          # ← 텍스트 인식 비활성화 (bbox만 추출)
    show_log=False,
    lang='ch',
)
```

`ocr=False` 옵션으로 PP-Structure가 레이아웃 영역 감지만 수행하고 텍스트 인식은 건너뛰게 한다. 반환된 `result[i]['bbox']`와 `result[i]['type']` 만 사용한다.

**2단계: 영역별 한국어 OCR**

```python
# 신규: PaddleOCR(lang='korean') 싱글턴
_korean_ocr_engine: PaddleOCR | None = None

def _get_korean_ocr() -> PaddleOCR:
    global _korean_ocr_engine
    if _korean_ocr_engine is None:
        _korean_ocr_engine = PaddleOCR(lang='korean', show_log=False)
    return _korean_ocr_engine
```

**`ocr_page()` 함수 수정 흐름:**

```python
def ocr_page(image: Image.Image) -> list[LayoutBlock]:
    img_array = np.array(image)
    structure_results = _get_structure_engine()(img_array)   # bbox 탐지만
    korean_ocr = _get_korean_ocr()
    blocks: list[LayoutBlock] = []

    for region in structure_results:
        block_type = region.get('type', 'text')
        bbox = region.get('bbox')           # [x1, y1, x2, y2]
        if bbox is None:
            continue

        x1, y1, x2, y2 = [int(v) for v in bbox]
        region_img = image.crop((x1, y1, x2, y2))
        region_array = np.array(region_img)

        if block_type == 'table':
            html, json_data = _extract_table_twopass(region_array, korean_ocr, (x1, y1))
            blocks.append(LayoutBlock(
                block_type='table',
                bbox=(x1, y1, x2, y2),
                text=_table_html_to_text(html),
                html=html,
                table_json=json_data,
                confidence=None,
                source_method='ocr_ppstructure_twopass',
            ))
        elif block_type == 'figure':
            blocks.append(LayoutBlock(
                block_type='figure',
                bbox=(x1, y1, x2, y2),
                text='',
                confidence=None,
                source_method='ocr_ppstructure_twopass',
            ))
        else:
            # text / title
            ocr_result = korean_ocr.ocr(region_array, cls=False)
            lines = []
            if ocr_result and ocr_result[0]:
                for line in ocr_result[0]:
                    if line and len(line) >= 2:
                        lines.append(line[1][0])   # (bbox, (text, conf))
            text = '\n'.join(lines)
            blocks.append(LayoutBlock(
                block_type=block_type,
                bbox=(x1, y1, x2, y2),
                text=text,
                confidence=None,
                source_method='ocr_ppstructure_twopass',
            ))

    # EasyOCR 폴백은 Two-Pass 실패(빈 결과) 시에만 적용
    if not blocks:
        return _easyocr_fallback(image)
    return blocks
```

**`_extract_table_twopass()` 내부 구현:**

```python
def _extract_table_twopass(
    region_array: np.ndarray,
    korean_ocr: PaddleOCR,
    offset: tuple[int, int] = (0, 0),
) -> tuple[str, dict]:
    """PP-Structure 표 셀 구조 탐지 + PaddleOCR Korean 텍스트 재인식."""
    # 1) TableStructureRecognizer 또는 PP-Structure table 전용으로 셀 bbox 탐지
    # PP-Structure를 table_only 모드로 실행하여 셀 bbox 추출
    table_engine = PPStructure(table=True, ocr=False, lang='ch', show_log=False)
    result = table_engine(region_array)

    # 결과가 없으면 전체 region을 단일 텍스트로 처리
    if not result or result[0].get('type') != 'table':
        ocr_result = korean_ocr.ocr(region_array, cls=False)
        text = _flatten_ocr_result(ocr_result)
        return f"<table><tr><td>{text}</td></tr></table>", {'headers': [], 'rows': [[text]]}

    # 2) HTML에서 셀 bbox 파싱 (BeautifulSoup)
    html_raw = result[0].get('res', {}).get('html', '')
    soup = BeautifulSoup(html_raw, 'lxml')
    cells = soup.find_all('td')

    # 3) 각 셀 bbox에 Korean OCR 적용
    cell_texts: list[str] = []
    for cell in cells:
        # cell bbox는 result[0]['res']['cell_bbox']에 순서대로 매핑됨
        ...  # 셀 crop → korean_ocr.ocr() → 텍스트 추출

    # 4) HTML/JSON 재조립
    ...
    return html_reconstructed, json_data
```

**구현 참고사항:**
- `PPStructure(table=True, ocr=False, lang='ch')` 초기화 시 `ocr=False`가 실제로 지원되지 않을 경우: `PPStructure(lang='ch')`로 실행 후 `result[i]['res']['html']`의 텍스트만 무시하고 `result[i]['res']['cell_bbox']`만 추출한 뒤 Korean OCR 재적용
- `PaddleOCR(lang='korean')`은 싱글턴으로 한 번만 초기화 (모델 로딩 비용)
- `LayoutBlock.source_method`에 `'ocr_ppstructure_twopass'` 값 추가 (기존 `'ocr_ppstructure'`와 구분)

---

### M-ocr-v2-2: CLOVA OCR 클라이언트 모듈

**파일 신규 생성:** `src/parser/clova_ocr.py`

#### CLOVA OCR API 규격

**엔드포인트:** `POST https://{apigw-url}/custom/v1/{api-uuid}/{secret}/general`

**요청 헤더:**
```
X-OCR-SECRET: {CLOVA_OCR_SECRET 환경변수}
Content-Type: multipart/form-data
```

**요청 바디 (`multipart/form-data`):**
- `message` 파트 (application/json):
```json
{
  "version": "V2",
  "requestId": "<uuid4>",
  "timestamp": 0,
  "images": [
    {
      "format": "jpg",
      "name": "page_xxx"
    }
  ]
}
```
- `file` 파트: JPEG 바이너리 (이미지 파일)

**응답 구조:**
```json
{
  "version": "V2",
  "requestId": "...",
  "timestamp": 1234567890,
  "images": [
    {
      "uid": "...",
      "name": "page_xxx",
      "inferResult": "SUCCESS",
      "message": "...",
      "fields": [
        {
          "valueType": "ALL",
          "boundingPoly": {
            "vertices": [
              {"x": 100, "y": 50},
              {"x": 400, "y": 50},
              {"x": 400, "y": 80},
              {"x": 100, "y": 80}
            ]
          },
          "inferText": "수술종수",
          "inferConfidence": 0.9912,
          "type": "NORMAL",
          "lineBreak": false
        }
      ],
      "tables": [
        {
          "cells": [
            {
              "rowIndex": 0,
              "columnIndex": 0,
              "rowSpan": 1,
              "columnSpan": 1,
              "cellTextLines": [
                {
                  "words": [{"text": "수술종수", "boundingPoly": {...}}]
                }
              ],
              "boundingPoly": {"vertices": [...]}
            }
          ]
        }
      ]
    }
  ]
}
```

#### 구현

```python
"""CLOVA OCR API 클라이언트 — LayoutBlock 인터페이스 호환."""
from __future__ import annotations

import io
import json
import os
import uuid
from pathlib import Path

import requests
from PIL import Image

from src.parser.ocr_engine import LayoutBlock


CLOVA_OCR_URL = os.getenv("CLOVA_OCR_URL", "")
CLOVA_OCR_SECRET = os.getenv("CLOVA_OCR_SECRET", "")
_REQUEST_TIMEOUT_SEC = 30


class ClovaOcrError(RuntimeError):
    pass


def _vertices_to_bbox(vertices: list[dict]) -> tuple[int, int, int, int]:
    """CLOVA boundingPoly vertices → (x1, y1, x2, y2)."""
    xs = [v["x"] for v in vertices]
    ys = [v["y"] for v in vertices]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def _table_to_json(table: dict) -> dict:
    """CLOVA table 응답 → {'headers': [...], 'rows': [[...]]} JSON."""
    cells = table.get("cells", [])
    if not cells:
        return {"headers": [], "rows": []}

    max_row = max(c["rowIndex"] + c.get("rowSpan", 1) - 1 for c in cells)
    max_col = max(c["columnIndex"] + c.get("columnSpan", 1) - 1 for c in cells)

    grid: list[list[str]] = [[""] * (max_col + 1) for _ in range(max_row + 1)]
    for cell in cells:
        r, c_ = cell["rowIndex"], cell["columnIndex"]
        words = []
        for line in cell.get("cellTextLines", []):
            words.extend(w["text"] for w in line.get("words", []))
        grid[r][c_] = " ".join(words)

    headers = grid[0] if grid else []
    rows = grid[1:] if len(grid) > 1 else []
    return {"headers": headers, "rows": rows}


def _table_to_text(table_json: dict) -> str:
    """표 JSON → BM25 검색용 직렬화 텍스트."""
    parts = []
    if table_json.get("headers"):
        parts.append(" | ".join(table_json["headers"]))
    for row in table_json.get("rows", []):
        parts.append(" | ".join(row))
    return "\n".join(parts)


def clova_ocr_page(image: Image.Image, page_name: str = "page") -> list[LayoutBlock]:
    """CLOVA OCR API로 단일 페이지를 처리하여 LayoutBlock 목록을 반환한다.

    환경변수 CLOVA_OCR_URL, CLOVA_OCR_SECRET가 설정되어 있어야 한다.
    미설정 시 ClovaOcrError를 발생시킨다.
    """
    if not CLOVA_OCR_URL or not CLOVA_OCR_SECRET:
        raise ClovaOcrError(
            "CLOVA_OCR_URL 또는 CLOVA_OCR_SECRET 환경변수가 설정되지 않았습니다."
        )

    # 이미지 → JPEG 바이트
    buf = io.BytesIO()
    rgb = image.convert("RGB") if image.mode not in ("RGB", "L") else image
    rgb.save(buf, format="JPEG", quality=95)
    buf.seek(0)

    message = json.dumps(
        {
            "version": "V2",
            "requestId": str(uuid.uuid4()),
            "timestamp": 0,
            "images": [{"format": "jpg", "name": page_name}],
        },
        ensure_ascii=False,
    )

    try:
        response = requests.post(
            CLOVA_OCR_URL,
            headers={"X-OCR-SECRET": CLOVA_OCR_SECRET},
            files={
                "message": (None, message, "application/json"),
                "file": (f"{page_name}.jpg", buf, "image/jpeg"),
            },
            timeout=_REQUEST_TIMEOUT_SEC,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ClovaOcrError(f"CLOVA OCR API 요청 실패: {exc}") from exc

    data = response.json()
    images = data.get("images", [])
    if not images or images[0].get("inferResult") != "SUCCESS":
        msg = images[0].get("message", "unknown") if images else "empty response"
        raise ClovaOcrError(f"CLOVA OCR 인식 실패: {msg}")

    image_result = images[0]
    blocks: list[LayoutBlock] = []

    # 1) 표 블록
    for table in image_result.get("tables", []):
        cells = table.get("cells", [])
        if not cells:
            continue
        all_vertices = []
        for cell in cells:
            all_vertices.extend(cell.get("boundingPoly", {}).get("vertices", []))
        bbox = _vertices_to_bbox(all_vertices) if all_vertices else (0, 0, 0, 0)
        table_json = _table_to_json(table)
        text = _table_to_text(table_json)
        blocks.append(
            LayoutBlock(
                block_type="table",
                bbox=bbox,
                text=text,
                html=None,
                table_json=table_json,
                confidence=None,
                source_method="ocr_clova",
            )
        )

    # 2) 텍스트 블록 — lineBreak 기준으로 줄 단위 그루핑
    fields = image_result.get("fields", [])
    if fields:
        lines: list[str] = []
        current_line: list[str] = []
        for field in fields:
            current_line.append(field.get("inferText", ""))
            if field.get("lineBreak", False):
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = []
        if current_line:
            lines.append(" ".join(current_line))

        if lines:
            # 전체 페이지 fields의 bbox
            all_v = []
            for f in fields:
                all_v.extend(f.get("boundingPoly", {}).get("vertices", []))
            bbox = _vertices_to_bbox(all_v) if all_v else (0, 0, 0, 0)
            avg_conf = sum(f.get("inferConfidence", 1.0) for f in fields) / len(fields)
            blocks.append(
                LayoutBlock(
                    block_type="text",
                    bbox=bbox,
                    text="\n".join(lines),
                    confidence=round(avg_conf, 3),
                    source_method="ocr_clova",
                )
            )

    return blocks
```

**환경변수 설정 방법 (`.env` 또는 시스템 환경):**
```
CLOVA_OCR_URL=https://xxxx.apigw.ntruss.com/custom/v1/{api-uuid}/{secret}/general
CLOVA_OCR_SECRET={X-OCR-SECRET 값}
```

`.env` 파일을 `python-dotenv`로 로드하거나, `scripts/ocr_compare.py` 실행 전 환경변수를 직접 설정한다. `.env`는 `.gitignore`에 이미 포함되어 있어야 한다 (없으면 추가).

---

### M-ocr-v2-3: OCR 엔진 비교 테스트 스크립트

**파일 신규 생성:** `scripts/ocr_compare.py`

```python
#!/usr/bin/env python3
"""Two-Pass OCR vs CLOVA OCR 엔진 비교 테스트."""
```

**CLI 인수:**
```
--doc   {실무가이드|상담사례집}   (기본: 실무가이드)
--pages {start}-{end}             (기본: 60-70, D6 수술분류표 구간)
--engines {twopass|clova|all}     (기본: all)
--output-dir                      (기본: reports/ocr_compare/)
```

**실행 흐름:**

1. `src/config.PDF_SOURCES`에서 대상 문서 path 확인
2. `src/parser/pdf_extractor.extract_page_image()`로 page 이미지 추출
3. 선택 엔진별로 OCR 실행:
   - `twopass`: `src/parser/ocr_engine.ocr_page()` (Two-Pass 개선 버전)
   - `clova`: `src/parser/clova_ocr.clova_ocr_page()`
4. 결과를 `reports/ocr_compare/{doc_short}/` 에 저장:
   - `{engine}_p{page:03d}_blocks.json`: LayoutBlock 목록 (JSON)
   - `{engine}_p{page:03d}_text.txt`: 전체 텍스트 (가독성)
   - `{engine}_p{page:03d}_tables.txt`: 표만 추출한 텍스트
5. `reports/ocr_compare/summary.txt` 생성

**summary.txt 포함 항목:**
- 엔진별 처리 시간 (페이지당 평균 초)
- 한글 비율 (`quality_metrics()` 재활용)
- 표 블록 수 / 셀 수
- 표 헤더 기대값 매칭 점수 (D6 60~70p 대상: `수술종수`, `수술명`, `수술해설` 포함 여부)
- PASS/MARGINAL/FAIL 통계

**표 헤더 기대값 검증 함수:**
```python
EXPECTED_TABLE_KEYWORDS = {"수술종수", "수술명", "수술해설", "수술방법", "분류"}

def score_table_header(table_json: dict) -> float:
    """헤더에 기대 키워드가 몇 개 포함됐는지 0~1 점수로 반환."""
    headers_text = " ".join(table_json.get("headers", []))
    matched = sum(1 for kw in EXPECTED_TABLE_KEYWORDS if kw in headers_text)
    return round(matched / len(EXPECTED_TABLE_KEYWORDS), 2)
```

---

### M-ocr-v2-4: 단위 테스트

**파일:** `tests/test_clova_ocr.py` (신규)

```python
"""CLOVA OCR 클라이언트 단위 테스트 — API 호출은 mock 처리."""
```

테스트 항목:
1. `_vertices_to_bbox()`: 정상 케이스, 빈 리스트
2. `_table_to_json()`: rowIndex/columnIndex 정렬, cellTextLines 병합
3. `_table_to_text()`: headers + rows 직렬화
4. `clova_ocr_page()` — 환경변수 미설정 시 `ClovaOcrError` 발생 확인
5. `clova_ocr_page()` — `requests.post` mock: SUCCESS 응답 → LayoutBlock 변환 검증
6. `clova_ocr_page()` — API 502 오류 시 `ClovaOcrError` 발생 확인

**파일:** `tests/test_ocr_engine.py` (기존 파일에 Two-Pass 관련 테스트 추가)

추가 테스트:
- `_get_korean_ocr()`: 싱글턴 보장 (동일 객체 반환)
- `source_method='ocr_ppstructure_twopass'` 확인

---

### M-ocr-v2-5: 검증 및 보고서

실행 순서:
```bash
# 1. 단위 테스트
pytest -q

# 2. Two-Pass OCR 비교 실행 (CLOVA 없이)
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines twopass

# 3. CLOVA OCR 비교 실행 (환경변수 설정 필요)
export CLOVA_OCR_URL="..."
export CLOVA_OCR_SECRET="..."
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines clova

# 4. 전체 비교 (환경변수 설정 시)
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines all
python scripts/ocr_compare.py --doc 상담사례집 --pages 0-4 --engines all
```

**보고서 `docs/36_OCR_V2_REPORT.md`에 반드시 포함할 항목:**

1. Two-Pass OCR 개선 결과
   - D6 p066 표 헤더: 이전(`'舍'`, `col_2`) → 이후(실제 한글)
   - 표 셀 텍스트 before/after 비교 5개 이상
   - 한글 비율 변화

2. CLOVA OCR 결과 (환경변수 설정 시)
   - 동일 구간 표 헤더 인식 결과
   - 표 셀 품질 점수 (`score_table_header()` 결과)
   - 처리 속도 (API 레이턴시)

3. 엔진 비교 요약표

| 항목 | Two-Pass(이전) | Two-Pass(개선) | CLOVA OCR |
|------|---------------|--------------|-----------|
| 표 헤더 한글 인식 | ❌ `'舍'` | (결과 기재) | (결과 기재) |
| 헤더 키워드 매칭 | 0/5 | (결과 기재) | (결과 기재) |
| 한글 비율 | (기재) | (기재) | (기재) |
| 처리 속도 | (기재) | (기재) | (기재) |
| 로컬 실행 | ✅ | ✅ | ❌ (API) |

4. 권장 엔진 결론 및 다음 단계 제안

5. `pytest -q` 결과

---

## 구현 순서 요약

| 단계 | 파일 | 내용 |
|------|------|------|
| M-ocr-v2-1 | `src/parser/ocr_engine.py` | Two-Pass OCR: PP-Structure bbox + PaddleOCR Korean |
| M-ocr-v2-2 | `src/parser/clova_ocr.py` | CLOVA OCR API 클라이언트 (LayoutBlock 호환) |
| M-ocr-v2-3 | `scripts/ocr_compare.py` | 엔진 비교 테스트 스크립트 |
| M-ocr-v2-4 | `tests/test_clova_ocr.py` + `tests/test_ocr_engine.py` 수정 | 단위 테스트 |
| M-ocr-v2-5 | `docs/36_OCR_V2_REPORT.md` | 비교 결과 보고서 |

---

## 참고: CLOVA OCR API 연동 주의사항

1. **API URL 형식:** `https://{apigw-domain}/custom/v1/{api-uuid}/{secret}/general`  
   네이버 클라우드 콘솔 → AI Services → CLOVA OCR → API Gateway 탭에서 URL 확인

2. **이미지 제한:** CLOVA OCR General은 이미지 1장당 1회 API 호출 (D6 330p 전체 처리 시 330 call)

3. **테스트 범위:** `scripts/ocr_compare.py`는 D6 60~70p (11페이지) 기준으로 비교. 전체 처리는 품질 검증 후 결정

4. **CLOVA 미설정 시 동작:** `clova_ocr_page()`는 `ClovaOcrError`를 발생시키고, `ocr_compare.py`는 해당 엔진을 건너뛰고 나머지 엔진만 실행하여 테스트가 실패하지 않도록 처리할 것

5. **보안:** `CLOVA_OCR_URL`과 `CLOVA_OCR_SECRET`는 환경변수 또는 `.env`로만 관리. 코드에 하드코딩 금지. `.env`는 `.gitignore`에 포함

---

## 제외 범위

- CLOVA OCR 커스텀 도메인 모델 학습 (추후 범위)
- D6 전체 330p OCR 재처리 (비교 테스트 결과 후 결정)
- GPT-4o Vision 캡션 생성 (별도 명세 예정)
- D7 상담사례집 Two-Pass 전체 재처리 (현재 EasyOCR 품질 양호)
