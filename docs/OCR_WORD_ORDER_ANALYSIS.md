# OCR 단어 순서 오류 원인 분석

> 작성일: 2026-05-11  
> 분석 대상: `reports/full_ocr_smoke_compare.html` (True Hybrid OCR 결과)  
> 관련 파일: `src/parser/clova_ocr.py`

---

## 1. 증상

`reports/full_ocr_smoke_compare.html`에서 확인된 단어 순서 이상 사례:

| 페이지 | 비정상 출력 | 문제 유형 |
|---|---|---|
| p071 | `'수술분류표\n71\n수술분류표 해설\n제1장'` | 페이지 번호("71") 본문 중간 침투 |
| p081 | `'흉부(끄럼\n호흡기계, 수술분류표\n81\n해설\n제1장 수술분류표'` | 페이지 번호("81") + 단어 분열("끄럼") |
| 다수 | `'근본수술(654)\n만성부비강염| 15.'` | 서로 다른 단락 필드 혼합 |

---

## 2. 코드 경로

```
clova_ocr_page()
  └─ fields = image_result.get("fields", [])  # CLOVA 응답의 word-level 토큰 목록
  └─ for raw_region in layout_regions:
       └─ region_fields = _filter_fields_in_bbox(fields, bbox)
       └─ text = _fields_to_lines(region_fields)   ← 핵심 문제 함수
  └─ remainder = [field not in used_indices]
  └─ remainder_text = _fields_to_lines(remainder)  ← 2차 문제
```

---

## 3. 근본 원인 — `_fields_to_lines()`의 `lineBreak` 플래그 오용

### 현재 코드 (line 360–373)

```python
def _fields_to_lines(fields: list[dict]) -> str:
    lines: list[str] = []
    current: list[str] = []
    for field in sorted(fields, key=lambda v: (_field_center_y(v), _field_center_x(v))):
        text = str(field.get("inferText", "")).strip()
        if text:
            current.append(text)
        if field.get("lineBreak", False):   # ← 문제
            if current:
                lines.append(" ".join(current))
                current = []
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)
```

### 오류 메커니즘

CLOVA는 `lineBreak=True` 플래그를 **CLOVA 자체 내부 순서 기준**으로 각 줄의 마지막 토큰에 설정한다.

그런데 `_fields_to_lines()`는 필드를 `(center_Y, center_X)` 기준으로 **재정렬**한 후 `lineBreak`를 확인한다.
재정렬 후에는 `lineBreak=True`가 붙은 필드가 시각적 줄의 중간에 나타날 수 있어, **줄 중간에 강제 줄바꿈**이 발생한다.

```
CLOVA 내부 순서 (인식 순서):   A → B → C(lineBreak) → D → E → F(lineBreak)
Y-정렬 후 순서:                D → A → B → C(lineBreak) → E → F(lineBreak)
                                         ↑여기서 강제 줄바꿈 → A,B,C 하나의 줄 → 사실 D-A-B는 한 줄이어야 함
```

**결과**: 하나의 시각적 줄이 두 줄로 분열되고, 서로 다른 줄의 단어가 한 줄로 합쳐진다.

---

## 4. 2차 원인 — 스캔 페이지 기울기 (Page Skew)

스캔본 문서는 미세한 회전이 있다 (통상 0.5°–2°). 해상도 ~1965px 너비 기준:

```
1965px × sin(1°) ≈ 34px Y 편차
```

즉, **같은 줄에 있는 단어들의 center_Y가 최대 34px까지 차이**날 수 있다.

`_group_fields_into_rows()`의 row_gap=20px보다 큰 편차가 생기면, 같은 줄의 단어가 다른 줄로 분류된다. 이것이 단어 분열(예: `'흉부(끄럼'`)의 원인 중 하나다.

---

## 5. 3차 원인 — 다단(Multi-Column) 텍스트 처리 부재

Y 기준 정렬은 2단 페이지에서 왼쪽 단과 오른쪽 단을 교차 삽입한다.

```
실제 레이아웃:     | 정렬 결과:
좌단 1행 → 우단 1행 |  좌단 1행
좌단 2행 → 우단 2행 |  우단 1행   ← 교차됨
...                |  좌단 2행
                   |  우단 2행
```

---

## 6. 4차 원인 — 나머지(Remainder) 블록의 전체 페이지 혼합

PP-Structure bbox에 매칭되지 않은 모든 fields는 `remainder` 블록 하나로 묶인다.
여기에는 **페이지 번호, 헤더, 푸터, 마진 텍스트** 등이 모두 포함되어, `_fields_to_lines()` 처리 시 전체 페이지에 흩어진 필드들이 Y-정렬로 뒤섞인다.

---

## 7. 오류 영향 범주 요약

| 원인 | 영향 정도 | 수정 난이도 |
|---|---|---|
| `lineBreak` 플래그 오용 | **높음** — 모든 텍스트 블록 영향 | 낮음 (함수 교체) |
| 스캔 기울기 (row_gap 부족) | **중간** — 고해상도 스캔본에서 빈번 | 낮음 (gap 적응형 계산) |
| 다단 텍스트 교차 | **중간** — 다단 페이지에서만 발생 | 중간 (컬럼 감지 로직 추가) |
| Remainder 블록 혼합 | **낮음** — 주요 블록은 정상 | 낮음 (Y-gap으로 분리) |

---

## 8. 해결 방안

### 방안 A (필수): `_fields_to_lines()`에서 `lineBreak` 제거, Y-gap 기반으로 전환

```python
def _fields_to_lines(fields: list[dict], row_gap: float | None = None) -> str:
    """Y-좌표 간격 기반으로 CLOVA field 목록을 텍스트 줄로 변환한다."""
    if not fields:
        return ""
    sorted_fields = sorted(fields, key=lambda f: (_field_center_y(f), _field_center_x(f)))
    # row_gap이 없으면 필드 높이의 중앙값 × 0.6 을 사용 (스캔 기울기 허용)
    if row_gap is None:
        heights = [
            _field_bbox(f)[3] - _field_bbox(f)[1]
            for f in fields
            if (_field_bbox(f)[3] - _field_bbox(f)[1]) > 0
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

> 핵심: `lineBreak` 플래그를 완전히 제거하고, 연속 필드 간 Y 좌표 차이만으로 줄바꿈 결정.

### 방안 B (권장): `_group_fields_into_rows()`의 row_gap을 적응형으로

```python
def _group_fields_into_rows(fields: list[dict], row_gap: float | None = None) -> list[list[dict]]:
    if not fields:
        return []
    sorted_fields = sorted(fields, key=lambda f: (_field_center_y(f), _field_center_x(f)))
    if row_gap is None:
        heights = [
            _field_bbox(f)[3] - _field_bbox(f)[1]
            for f in sorted_fields
            if (_field_bbox(f)[3] - _field_bbox(f)[1]) > 0
        ]
        median_h = sorted(heights)[len(heights) // 2] if heights else 20.0
        row_gap = max(8.0, median_h * 0.6)
    # ... 이하 동일
```

### 방안 C (선택): 다단 텍스트 컬럼별 정렬

`_fields_to_lines()`에서 X 분포를 분석해 2단 이상이면 컬럼별로 읽는 순서로 처리.
`_detect_column_x_ranges()`를 재활용할 수 있다.

### 방안 D (선택): Remainder 블록을 Y-gap으로 분리

단일 Remainder 블록 대신, Y-gap으로 나뉜 여러 텍스트 블록을 생성.
페이지 번호, 헤더 등이 독립 블록으로 분리되어 본문 오염을 줄인다.

---

## 9. 검증 방법

1. `pytest tests/test_clova_ocr.py -v` — 기존 테스트 전체 통과 확인
2. 새 단위 테스트:
   - `test_fields_to_lines_no_linebreak_in_middle`: lineBreak가 중간에 있어도 Y-gap 기준으로만 분리
   - `test_fields_to_lines_skewed_same_line`: Y가 20px 차이나도 같은 줄로 처리
   - `test_fields_to_lines_two_column`: 2단 필드가 컬럼별로 올바르게 정렬
3. `python scripts/run_full_ocr.py --doc 실무가이드 --pages 71,81 --force --yes` 재실행 후 HTML 비교

---

## 10. 수정 금지 범위

이번 수정에서 아래 파일은 수정하지 않는다:

- `src/parser/ocr_engine.py`
- `src/parser/ocr_chunker.py`
- `src/config.py`
- `scripts/ingest.py`
