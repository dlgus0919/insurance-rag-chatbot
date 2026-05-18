# Codex 명세 — OCR 엔진 개선 v4: CLOVA bbox 기반 표 구조 재구성

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)  
선행 명세: `docs/37_CODEX_SPEC_OCR_HYBRID.md`

---

## 배경: 실측 응답 구조 확인 결과

### CLOVA OCR General 실제 응답 구조

D6 p066 (수술분류표) 실제 호출 결과:

```
응답 키: ['uid', 'name', 'inferResult', 'message', 'validationResult',
          'convertedImageInfo', 'fields']
tables 개수: 0
fields 총 개수: 358
valueType 종류: {'ALL'}
field type 종류: {'NORMAL'}
```

**결론:** "표 추출 여부" ON 설정에도 불구하고 General 플랜은 `tables` 키를 반환하지 않는다.  
대신 **358개의 단어 단위 field**가 `boundingPoly` 좌표(vertices 4점)와 함께 반환된다.

### 보유 데이터로 할 수 있는 것

| 항목 | 가능 여부 | 방법 |
|------|-----------|------|
| 고품질 한글 텍스트 | ✅ | `inferText` (confidence ~0.999) |
| 단어 위치 정보 | ✅ | `boundingPoly.vertices` (x,y 4점) |
| 표 구조 재구성 | ✅ | **Y좌표 기반 행 그룹핑 + X좌표 기반 열 클러스터링** |
| 영역 유형 분류 (표/텍스트/이미지) | ✅ | PP-Structure bbox 탐지 (기존 유지) |

### 최종 아키텍처: CLOVA 1회 호출 + 좌표 기반 재구성

```
[페이지 이미지]
    │
    ├─ PP-Structure(lang='ch')
    │      → 레이아웃 영역 bbox 목록
    │        (table: [x1,y1,x2,y2], text: [...], figure: [...])
    │
    └─ CLOVA OCR General (페이지 전체, 1회 호출)
           → 358개 field (inferText + boundingPoly)
           │
           ├─ 표 영역 fields → 행/열 재구성 → table_json + 직렬화 텍스트
           ├─ 텍스트 영역 fields → lineBreak 기반 줄 병합 → 단락 텍스트
           └─ 이미지 영역 → PNG crop (캡션 플레이스홀더)
```

**장점:**
- CLOVA API 호출 페이지당 **1회** (기존 Hybrid v3 명세: 셀 수 × 호출)
- D6 330p 전체 처리 시 330 call (셀 단위 호출 대비 수십 배 절감)
- 표 구조 재구성 정확도는 field bbox 밀도에 의존 (p066 기준 358 fields → 충분)

---

## 구현 명세

### M-ocr-v4-1: CLOVA OCR 타임아웃 수정 (기존 M-ocr-v3-1 동일, 우선 적용)

**파일:** `src/parser/clova_ocr.py`

- `_REQUEST_TIMEOUT_SEC = 30` → `_REQUEST_TIMEOUT_SEC = 60`
- 타임아웃 재시도 1회 추가 (37번 명세 M-ocr-v3-1 내용 동일하게 적용)

---

### M-ocr-v4-2: bbox 기반 표 구조 재구성 함수

**파일:** `src/parser/clova_ocr.py` (기존 파일 수정)

아래 함수들을 추가한다.

#### `_field_center_y(field)` / `_field_center_x(field)`

```python
def _field_center_y(field: dict) -> float:
    verts = field["boundingPoly"]["vertices"]
    return (verts[0]["y"] + verts[2]["y"]) / 2

def _field_center_x(field: dict) -> float:
    verts = field["boundingPoly"]["vertices"]
    return (verts[0]["x"] + verts[2]["x"]) / 2

def _field_bbox(field: dict) -> tuple[float, float, float, float]:
    verts = field["boundingPoly"]["vertices"]
    xs = [v["x"] for v in verts]
    ys = [v["y"] for v in verts]
    return min(xs), min(ys), max(xs), max(ys)
```

#### `_group_fields_into_rows(fields, row_gap)`

Y좌표 기준으로 field를 행 그룹으로 묶는다.

```python
def _group_fields_into_rows(
    fields: list[dict], row_gap: float = 20.0
) -> list[list[dict]]:
    """Y 좌표 기준으로 field를 행 단위로 그룹핑한다.

    같은 행으로 판단하는 기준:
    - 이전 field의 center_y와 현재 field의 center_y 차이가 row_gap 이하
    """
    if not fields:
        return []
    sorted_fields = sorted(fields, key=_field_center_y)
    rows: list[list[dict]] = [[sorted_fields[0]]]
    for field in sorted_fields[1:]:
        last_row_y = _field_center_y(rows[-1][-1])
        if abs(_field_center_y(field) - last_row_y) <= row_gap:
            rows[-1].append(field)
        else:
            rows.append([field])
    # 각 행 내부는 X 좌표 기준 정렬
    for row in rows:
        row.sort(key=_field_center_x)
    return rows
```

#### `_detect_column_x_ranges(rows, col_gap)`

모든 행에 걸쳐 공통 열 X 범위를 추정한다.

```python
def _detect_column_x_ranges(
    rows: list[list[dict]], col_gap: float = 40.0
) -> list[tuple[float, float]]:
    """모든 행의 field X 좌표를 수집하여 열 경계(x_start, x_end)를 추정한다.

    동일 열에 속하는 field들은 X 범위가 겹치거나 인접한다.
    col_gap: 두 field의 x_start 차이가 이 값 이하이면 같은 열로 판단.
    """
    # 모든 field의 x_start 수집
    x_starts: list[float] = []
    for row in rows:
        for field in row:
            x1, _, x2, _ = _field_bbox(field)
            x_starts.append(x1)

    if not x_starts:
        return []

    x_starts.sort()
    # 인접한 x_start를 클러스터링하여 열 그룹 형성
    clusters: list[list[float]] = [[x_starts[0]]]
    for x in x_starts[1:]:
        if x - clusters[-1][-1] <= col_gap:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    # 각 클러스터의 범위 → (x_min, x_max + field_width_estimate)
    col_ranges: list[tuple[float, float]] = []
    for cluster in clusters:
        x_min = min(cluster)
        x_max = max(cluster)
        col_ranges.append((x_min, x_max + col_gap))

    return col_ranges
```

#### `_assign_fields_to_columns(row_fields, col_ranges)`

한 행의 field들을 열 인덱스에 할당한다.

```python
def _assign_fields_to_columns(
    row_fields: list[dict], col_ranges: list[tuple[float, float]]
) -> list[str]:
    """한 행의 field를 열 인덱스에 할당하여 셀 텍스트 리스트를 반환한다."""
    cells = [""] * len(col_ranges)
    for field in row_fields:
        cx = _field_center_x(field)
        for col_idx, (x_min, x_max) in enumerate(col_ranges):
            if x_min - 20 <= cx <= x_max + 20:
                sep = " " if cells[col_idx] else ""
                cells[col_idx] += sep + field["inferText"]
                break
        # 어느 열에도 속하지 않으면 가장 가까운 열에 배정
        else:
            if col_ranges:
                dists = [abs(cx - (x_min + x_max) / 2) for x_min, x_max in col_ranges]
                nearest = dists.index(min(dists))
                sep = " " if cells[nearest] else ""
                cells[nearest] += sep + field["inferText"]
    return cells
```

#### `reconstruct_table_from_fields(fields, table_bbox, row_gap, col_gap)`

표 영역 내 fields → `{"headers": [...], "rows": [[...]]}` JSON 반환.

```python
def reconstruct_table_from_fields(
    fields: list[dict],
    table_bbox: tuple[float, float, float, float],
    row_gap: float = 20.0,
    col_gap: float = 40.0,
) -> dict:
    """CLOVA fields의 bbox를 이용해 표 JSON을 재구성한다.

    Args:
        fields: CLOVA 응답의 images[0]['fields'] 전체 목록
        table_bbox: PP-Structure가 탐지한 표 영역 (x1, y1, x2, y2)
        row_gap: 같은 행으로 간주하는 Y 좌표 최대 차이 (픽셀)
        col_gap: 같은 열로 간주하는 X 클러스터링 거리 (픽셀)

    Returns:
        {"headers": ["col1", ...], "rows": [["cell", ...], ...]}
    """
    tx1, ty1, tx2, ty2 = table_bbox
    # 1) 표 영역 내의 field만 필터
    margin = 10.0
    table_fields = [
        f for f in fields
        if (tx1 - margin <= _field_center_x(f) <= tx2 + margin
            and ty1 - margin <= _field_center_y(f) <= ty2 + margin)
    ]

    if not table_fields:
        return {"headers": [], "rows": []}

    # 2) 행 그룹핑
    rows = _group_fields_into_rows(table_fields, row_gap=row_gap)

    # 3) 열 범위 추정
    col_ranges = _detect_column_x_ranges(rows, col_gap=col_gap)

    if not col_ranges:
        # 열 구분 불가 → 전체 텍스트를 단일 셀로 반환
        all_text = " ".join(f["inferText"] for f in table_fields)
        return {"headers": [all_text], "rows": []}

    # 4) 각 행 → 셀 텍스트 리스트
    grid: list[list[str]] = []
    for row_fields in rows:
        cells = _assign_fields_to_columns(row_fields, col_ranges)
        grid.append(cells)

    # 5) headers/rows 분리
    headers = grid[0] if grid else []
    data_rows = grid[1:] if len(grid) > 1 else []

    return {"headers": headers, "rows": data_rows}
```

---

### M-ocr-v4-3: `clova_ocr_page()` 개선 — 표 구조 재구성 통합

**파일:** `src/parser/clova_ocr.py`

`clova_ocr_page()`의 반환 로직을 수정한다.  
기존: fields → 단일 텍스트 LayoutBlock  
변경: PP-Structure bbox를 인수로 받아 표 영역별 재구성 적용

```python
def clova_ocr_page(
    image: Image.Image,
    page_name: str = "page",
    layout_bboxes: list[dict] | None = None,
) -> list[LayoutBlock]:
    """CLOVA OCR API로 단일 페이지를 처리하여 LayoutBlock 목록을 반환한다.

    Args:
        image: 처리할 페이지 이미지
        page_name: API 요청에 사용할 페이지 식별자
        layout_bboxes: PP-Structure가 탐지한 영역 목록.
            각 항목: {"type": "table"|"text"|"figure", "bbox": [x1,y1,x2,y2]}
            None이면 전체 페이지를 단일 텍스트 블록으로 반환 (기존 동작 유지)
    """
    ...
    fields = image_result.get("fields", [])

    if layout_bboxes is None:
        # 기존 동작: 전체 fields를 단일 텍스트 블록으로 반환
        return _fields_to_single_block(fields)

    blocks: list[LayoutBlock] = []
    used_field_indices: set[int] = set()

    for region in layout_bboxes:
        block_type: str = region.get("type", "text")
        bbox_list: list[float] = region.get("bbox", [])
        if len(bbox_list) < 4:
            continue
        bbox = tuple(bbox_list[:4])  # (x1, y1, x2, y2)

        if block_type == "figure":
            blocks.append(LayoutBlock(
                block_type="figure",
                bbox=tuple(int(v) for v in bbox),
                text="",
                confidence=None,
                source_method="ocr_clova",
            ))
            continue

        if block_type == "table":
            table_json = reconstruct_table_from_fields(fields, bbox)
            text = _table_to_text(table_json)
            html = _table_json_to_html(table_json)
            blocks.append(LayoutBlock(
                block_type="table",
                bbox=tuple(int(v) for v in bbox),
                text=text,
                html=html,
                table_json=table_json,
                confidence=None,
                source_method="ocr_clova",
            ))
        else:
            # text / title 영역
            region_fields = _filter_fields_in_bbox(fields, bbox)
            text = _fields_to_lines(region_fields)
            if text.strip():
                avg_conf = (sum(f.get("inferConfidence", 1.0) for f in region_fields)
                            / len(region_fields)) if region_fields else 1.0
                blocks.append(LayoutBlock(
                    block_type=block_type,
                    bbox=tuple(int(v) for v in bbox),
                    text=text,
                    confidence=round(avg_conf, 3),
                    source_method="ocr_clova",
                ))

    # 어느 영역에도 속하지 않은 fields → 별도 텍스트 블록
    ...

    return blocks if blocks else _fields_to_single_block(fields)
```

**추가 헬퍼 함수:**

```python
def _fields_to_lines(fields: list[dict]) -> str:
    """lineBreak 기준으로 fields를 줄 단위 텍스트로 병합한다."""
    lines: list[str] = []
    current: list[str] = []
    for field in sorted(fields, key=lambda f: (_field_center_y(f), _field_center_x(f))):
        current.append(field.get("inferText", ""))
        if field.get("lineBreak", False):
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)

def _filter_fields_in_bbox(
    fields: list[dict], bbox: tuple, margin: float = 10.0
) -> list[dict]:
    """bbox 영역 내에 center가 속하는 fields를 반환한다."""
    x1, y1, x2, y2 = bbox
    return [
        f for f in fields
        if (x1 - margin <= _field_center_x(f) <= x2 + margin
            and y1 - margin <= _field_center_y(f) <= y2 + margin)
    ]

def _table_json_to_html(table_json: dict) -> str:
    """table_json → HTML 문자열."""
    rows_all = ([table_json["headers"]] if table_json.get("headers") else []) + table_json.get("rows", [])
    html_rows = []
    for row in rows_all:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        html_rows.append(f"<tr>{cells}</tr>")
    return "<table>" + "".join(html_rows) + "</table>"
```

---

### M-ocr-v4-4: `hybrid_ocr.py` 수정 — PP-Structure + CLOVA 1회 호출

**파일:** `src/parser/hybrid_ocr.py` (37번 명세 버전 대체)

기존 v3 설계(셀마다 CLOVA 호출)를 **페이지당 1회 CLOVA 호출** 방식으로 교체한다.

```python
def hybrid_ocr_page(image: Image.Image) -> list[LayoutBlock]:
    """PP-Structure 레이아웃 탐지 + CLOVA OCR(1회) + bbox 기반 표 재구성."""
    import numpy as np
    img_array = np.array(image)

    # 1) PP-Structure로 레이아웃 영역 탐지
    structure_results = _get_structure_engine()(img_array)
    if not structure_results:
        return _easyocr_fallback(image)

    layout_bboxes = [
        {"type": r.get("type", "text"), "bbox": r.get("bbox", [])}
        for r in structure_results
        if r.get("bbox")
    ]

    # 2) CLOVA OCR 전체 페이지 1회 호출 (layout_bboxes 전달)
    try:
        return clova_ocr_page(image, page_name="hybrid_page", layout_bboxes=layout_bboxes)
    except ClovaOcrError:
        # CLOVA 실패 시 Two-Pass로 폴백
        return ocr_page(image)
```

---

### M-ocr-v4-5: 단위 테스트 추가

**파일:** `tests/test_clova_ocr.py` (기존 파일에 추가)

추가 테스트 항목:
1. `_group_fields_into_rows()`: 동일 Y → 1행, 분리 Y → 다행
2. `_detect_column_x_ranges()`: 2열 구조 fields → 2개 범위 반환
3. `_assign_fields_to_columns()`: 각 field가 올바른 열에 배정되는지
4. `reconstruct_table_from_fields()`: 3×3 가상 grid fields → headers/rows 정확도
5. `clova_ocr_page(layout_bboxes=...)`: mock 응답 + layout_bboxes → table/text LayoutBlock 반환 확인

**테스트 fixture 예시:**
```python
# 2행 3열 가상 표 fields
MOCK_TABLE_FIELDS = [
    # 헤더 행 (y=100)
    {"inferText": "수술종수", "boundingPoly": {"vertices": [{"x":100,"y":90},{"x":200,"y":90},{"x":200,"y":110},{"x":100,"y":110}]}, "lineBreak": False, "inferConfidence": 0.99},
    {"inferText": "수술명",   "boundingPoly": {"vertices": [{"x":300,"y":90},{"x":500,"y":90},{"x":500,"y":110},{"x":300,"y":110}]}, "lineBreak": False, "inferConfidence": 0.99},
    {"inferText": "수술해설", "boundingPoly": {"vertices": [{"x":600,"y":90},{"x":1000,"y":90},{"x":1000,"y":110},{"x":600,"y":110}]}, "lineBreak": True,  "inferConfidence": 0.99},
    # 데이터 행 (y=150)
    {"inferText": "1-3종",   "boundingPoly": {"vertices": [{"x":100,"y":140},{"x":200,"y":140},{"x":200,"y":160},{"x":100,"y":160}]}, "lineBreak": False, "inferConfidence": 0.99},
    {"inferText": "반월판연골봉합술", "boundingPoly": {"vertices": [{"x":300,"y":140},{"x":500,"y":140},{"x":500,"y":160},{"x":300,"y":160}]}, "lineBreak": False, "inferConfidence": 0.99},
    {"inferText": "파열된 반월판을 꿰매는 수술", "boundingPoly": {"vertices": [{"x":600,"y":140},{"x":1000,"y":140},{"x":1000,"y":160},{"x":600,"y":160}]}, "lineBreak": True, "inferConfidence": 0.99},
]
```

---

### M-ocr-v4-6: 검증 및 보고서

실행 순서:
```bash
# 1. 단위 테스트
pytest -q

# 2. CLOVA 단독 (1회 호출 + bbox 재구성)
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines clova

# 3. Hybrid (PP-Structure + CLOVA 1회)
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines hybrid

# 4. 전체 비교
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines all
```

**보고서 `docs/38_OCR_TABLE_RECONSTRUCT_REPORT.md`에 반드시 포함할 항목:**

1. p066 표 헤더 재구성 결과
   - `reconstruct_table_from_fields()` 출력: `headers`, `rows` 일부
   - 기대값: `["수술종수", "수술명", "수술해설", ...]`

2. 3-way 비교표

| 엔진 | 표 헤더 인식 | 헤더 키워드 점수 | 표 구조 | API call/page |
|------|------------|----------------|---------|--------------|
| Two-Pass | (결과) | (점수) | ✅ grid | 0 |
| CLOVA (bbox재구성) | (결과) | (점수) | ✅ grid(재구성) | 1 |
| Hybrid | (결과) | (점수) | ✅ grid(재구성) | 1 |

3. `row_gap` / `col_gap` 파라미터 민감도 — 값 변경 시 결과 변화 여부
4. 전체 11페이지 완주 여부 (타임아웃 없어야 함)
5. `pytest -q` 결과
6. 권장 엔진 및 `scripts/ocr_extract.py` 전체 D6/D7 적용 방향 제안

---

## 수정 대상 파일 요약

| 파일 | 변경 유형 | 주요 내용 |
|------|-----------|-----------|
| `src/parser/clova_ocr.py` | 수정 | timeout 60s, 재시도, bbox 재구성 함수 추가, `layout_bboxes` 인수 추가 |
| `src/parser/hybrid_ocr.py` | 수정 | 셀 단위 호출 제거 → 페이지 1회 CLOVA + layout_bboxes 전달 |
| `scripts/ocr_compare.py` | 수정 | `--timeout` 인수 추가 |
| `tests/test_clova_ocr.py` | 수정 | bbox 재구성 단위 테스트 추가 |
| `docs/38_OCR_TABLE_RECONSTRUCT_REPORT.md` | 신규 | 보고서 |

---

## 제외 범위

- `scripts/ocr_extract.py` D6/D7 전체 재처리 (보고서 검토 후 별도 명세)
- CLOVA 커스텀 도메인 모델 학습
- D7 상담사례집 (D6 검증 완료 후 적용)
- row_gap / col_gap 자동 튜닝 (수동 파라미터로 충분)
