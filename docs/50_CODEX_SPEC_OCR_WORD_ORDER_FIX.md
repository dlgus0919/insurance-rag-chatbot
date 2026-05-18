# Codex 명세 #50 — OCR 단어 순서 오류 수정

## 1) Goal

`src/parser/clova_ocr.py`의 `_fields_to_lines()` 함수에서 발생하는 단어 순서 오류를 수정한다.
현재 구현은 CLOVA의 `lineBreak` 플래그를 Y-정렬 이후에 적용하는 구조적 버그가 있으며,
이로 인해 시각적으로 같은 줄에 있는 단어들이 분열되고, 다른 줄의 단어가 합쳐지는 현상이 발생한다.

---

## 2) Background

### 현재 버그 (`_fields_to_lines()`)

```python
# 현재 코드 (line 360–373)
def _fields_to_lines(fields):
    for field in sorted(fields, key=lambda v: (_field_center_y(v), _field_center_x(v))):
        text = ...
        if text:
            current.append(text)
        if field.get("lineBreak", False):   # ← 버그: Y-정렬 후 lineBreak는 위치가 틀림
            lines.append(" ".join(current))
            current = []
```

**버그 설명**: CLOVA는 `lineBreak=True`를 자체 내부 순서 기준으로 각 줄 마지막 토큰에 설정한다.
함수는 필드를 (center_Y, center_X)로 재정렬한 후 이 플래그를 확인하는데,
재정렬로 인해 `lineBreak=True` 토큰이 시각적 줄의 중간에 올 수 있다.
결과로 한 줄이 두 줄로 분열되거나, 서로 다른 줄의 단어가 한 줄로 합쳐진다.

### 부수적 문제

| 문제 | 원인 | 영향 |
|---|---|---|
| 같은 줄 단어 분열 | 스캔 기울기로 center_Y가 최대 34px 차이 → row_gap(20px) 초과 | 중간 |
| 다단 텍스트 교차 | Y-정렬이 좌단·우단 필드를 교차 삽입 | 중간 |
| Remainder 블록 혼합 | 페이지 전체의 미매칭 필드를 하나로 묶음 | 낮음 |

---

## 3) Target Files

### 수정 허용
- `src/parser/clova_ocr.py` — 버그 수정 대상

### 신규 생성
- `tests/test_clova_word_order.py` — 단어 순서 관련 단위 테스트

### 수정 금지
- `src/parser/ocr_engine.py`
- `src/parser/ocr_chunker.py`
- `src/parser/table_vision_cleaner.py`
- `src/parser/numeric_cell_refiner.py`
- `src/config.py`
- `scripts/ingest.py`
- `scripts/run_true_hybrid_local.py`
- `scripts/run_clova_local.py`
- `scripts/run_full_ocr.py`

---

## 4) Detailed Requirements

### 4-1. `_fields_to_lines()` 수정 (필수)

`lineBreak` 플래그를 완전히 제거하고, 연속 필드 간 Y 좌표 차이만으로 줄바꿈을 결정한다.

**구현 명세:**

```python
def _fields_to_lines(fields: list[dict], row_gap: float | None = None) -> str:
    """Y-좌표 간격 기반으로 CLOVA field 목록을 텍스트 줄로 변환한다.

    lineBreak 플래그를 사용하지 않는다. 연속 필드 간 center_Y 차이가
    row_gap을 초과하면 새 줄로 분리한다.

    Args:
        fields: CLOVA 응답의 field dict 목록
        row_gap: 줄바꿈 기준 Y 픽셀 간격. None이면 필드 높이 중앙값 × 0.6
                 (최소 8px)으로 자동 계산한다.
    """
    if not fields:
        return ""
    sorted_fields = sorted(
        fields, key=lambda f: (_field_center_y(f), _field_center_x(f))
    )
    if row_gap is None:
        heights = [
            _field_bbox(f)[3] - _field_bbox(f)[1]
            for f in sorted_fields
            if _field_bbox(f)[3] - _field_bbox(f)[1] > 0
        ]
        median_h = sorted(heights)[len(heights) // 2] if heights else 20.0
        row_gap = max(8.0, median_h * 0.6)

    lines: list[list[str]] = []
    current: list[str] = []
    prev_y: float | None = None

    for field in sorted_fields:
        text = str(field.get("inferText", "")).strip()
        if not text:
            continue
        cy = _field_center_y(field)
        if prev_y is not None and (cy - prev_y) > row_gap:
            if current:
                lines.append(current)
            current = []
        current.append(text)
        prev_y = cy

    if current:
        lines.append(current)
    return "\n".join(" ".join(line) for line in lines)
```

> **주의**: 함수 시그니처에 `row_gap` 파라미터가 추가되지만, 기존 호출부는 모두 인수 없이 호출하므로 하위 호환성이 유지된다. 기존 `row_gap=20.0` 기본값은 제거하고 `None` 기본값으로 대체한다.

### 4-2. `_group_fields_into_rows()` row_gap 적응형 수정 (필수)

고정 20px 대신 필드 높이 중앙값 기반으로 자동 계산한다.

```python
def _group_fields_into_rows(
    fields: list[dict], row_gap: float | None = None
) -> list[list[dict]]:
    if not fields:
        return []
    sorted_fields = sorted(
        fields, key=lambda f: (_field_center_y(f), _field_center_x(f))
    )
    if row_gap is None:
        heights = [
            _field_bbox(f)[3] - _field_bbox(f)[1]
            for f in sorted_fields
            if _field_bbox(f)[3] - _field_bbox(f)[1] > 0
        ]
        median_h = sorted(heights)[len(heights) // 2] if heights else 20.0
        row_gap = max(8.0, median_h * 0.6)

    rows: list[list[dict]] = [[sorted_fields[0]]]
    for field in sorted_fields[1:]:
        last_row_y = _field_center_y(rows[-1][-1])
        if abs(_field_center_y(field) - last_row_y) <= row_gap:
            rows[-1].append(field)
        else:
            rows.append([field])
    for row in rows:
        row.sort(key=_field_center_x)
    return rows
```

> **주의**: `reconstruct_table_from_fields()`가 `row_gap` 인수를 `_group_fields_into_rows()`에 전달하고 있다. 해당 호출부도 함께 수정해 기본값(`None`)을 사용하도록 한다.

### 4-3. Remainder 블록 Y-gap 분리 (권장)

현재 Remainder 블록은 페이지 전체의 미매칭 필드를 하나로 묶는다.
`_group_fields_into_rows()`를 활용해 Y-gap으로 나뉜 여러 독립 블록으로 분리한다.

`clova_ocr_page()` 내 Remainder 처리 부분:

```python
# 현재 (단일 블록):
remainder_text = _fields_to_lines(remainder)
if remainder_text.strip():
    blocks.append(LayoutBlock(block_type="text", bbox=..., text=remainder_text, ...))

# 수정 후 (복수 블록):
if remainder:
    rem_rows = _group_fields_into_rows(remainder)   # Y-gap 기준 행 그룹
    # 행 그룹 간 큰 Y-gap을 기준으로 다시 단락으로 묶음
    para_gap = _compute_para_gap(rem_rows)          # 행 간 Y 간격 중앙값 × 2
    paragraphs: list[list[list[dict]]] = [[rem_rows[0]]]
    for row in rem_rows[1:]:
        prev_row_y = _field_center_y(paragraphs[-1][-1][-1])
        curr_row_y = _field_center_y(row[0])
        if curr_row_y - prev_row_y > para_gap:
            paragraphs.append([])
        paragraphs[-1].append(row)
    for para_rows in paragraphs:
        para_fields = [f for row in para_rows for f in row]
        para_text = "\n".join(" ".join(
            str(f.get("inferText", "")).strip() for f in row if f.get("inferText", "").strip()
        ) for row in para_rows)
        if not para_text.strip():
            continue
        all_verts = [v for f in para_fields
                     for v in f.get("boundingPoly", {}).get("vertices", [])]
        blocks.append(LayoutBlock(
            block_type="text",
            bbox=list(_vertices_to_bbox(all_verts)),
            text=para_text,
            confidence=_avg_confidence(para_fields),
            source_method="ocr_clova",
            raw={"remainder": True},
        ))
```

`_compute_para_gap()` 헬퍼:
```python
def _compute_para_gap(rows: list[list[dict]]) -> float:
    if len(rows) < 2:
        return 40.0
    gaps = [
        _field_center_y(rows[i + 1][0]) - _field_center_y(rows[i][-1])
        for i in range(len(rows) - 1)
    ]
    gaps.sort()
    median_gap = gaps[len(gaps) // 2]
    return max(median_gap * 2.0, 30.0)
```

> **주의**: Remainder 단락 분리는 복잡도가 있으므로, 4-1과 4-2 수정 후에도 HTML 결과에서 페이지 번호 침투가 계속될 경우에만 구현한다.

---

## 5) Validation

```bash
# 1. 단위 테스트
pytest tests/test_clova_word_order.py -v
# 최소 5개 테스트 (아래 명세 참조)

# 2. 기존 테스트 전체 회귀
pytest -q
# 목표: 0 failures (기존 206개 + 신규 ≥ 5개)

# 3. 수정 전후 비교 smoke
python scripts/run_full_ocr.py --doc 실무가이드 --pages 71,81 --force --yes
# → data/extracted/실무가이드/text/p071_b*.txt, p081_b*.txt 확인
# → 페이지 번호("71", "81")가 본문 블록에 포함되지 않는지 확인
```

### 단위 테스트 명세 (`tests/test_clova_word_order.py`)

| 테스트 이름 | 검증 내용 |
|---|---|
| `test_linebreak_in_middle_does_not_split` | lineBreak=True가 Y-정렬 후 줄 중간에 있어도 분열 없음 |
| `test_same_line_words_different_y` | center_Y가 row_gap 미만으로 다른 필드들이 같은 줄로 합쳐짐 |
| `test_two_lines_separated_by_y_gap` | center_Y 차이가 row_gap 초과이면 줄 분리 |
| `test_adaptive_row_gap_uses_field_height` | row_gap=None 시 필드 높이 중앙값 기반으로 자동 계산 |
| `test_group_fields_into_rows_adaptive` | `_group_fields_into_rows()`가 row_gap=None으로 적응형 동작 |

테스트는 실제 CLOVA API 호출 없이 더미 field dict로 작성한다.

더미 필드 생성 헬퍼:
```python
def make_field(x1, y1, x2, y2, text, line_break=False):
    return {
        "inferText": text,
        "lineBreak": line_break,
        "inferConfidence": 0.99,
        "boundingPoly": {"vertices": [
            {"x": x1, "y": y1}, {"x": x2, "y": y1},
            {"x": x2, "y": y2}, {"x": x1, "y": y2},
        ]},
    }
```

---

## 6) Stop Rules

- 기존 `pytest -q`에서 1건이라도 실패 → 즉시 중단, 보고
- `_fields_to_lines()` 수정으로 `reconstruct_table_from_fields()` 동작이 달라져야 하는 경우 → 중단, 보고 (해당 함수는 `_group_fields_into_rows()`를 사용하므로 `_fields_to_lines()`와 무관)
- `src/parser/ocr_chunker.py` 수정 없이 기존 chunker 연동이 깨지는 경우 → 중단, 보고

---

## 7) Output Requirements

구현 완료 후 `docs/50_WORD_ORDER_FIX_REPORT.md`를 작성한다.

포함 항목:
1. 수정된 함수 목록 (한 줄 설명)
2. `pytest -q` 전체 출력
3. 단위 테스트 결과 (`pytest tests/test_clova_word_order.py -v` 출력)
4. Before/After 비교: 테스트 필드 세트로 수정 전후 `_fields_to_lines()` 출력 비교
5. 잔여 블로커 ("None" 또는 구체적 내용)

커밋 대상: `src/parser/clova_ocr.py`, `tests/test_clova_word_order.py`, `docs/50_WORD_ORDER_FIX_REPORT.md`
