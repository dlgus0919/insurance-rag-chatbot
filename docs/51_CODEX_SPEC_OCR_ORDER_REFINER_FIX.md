# Codex 명세 #51 — CLOVA 읽기 순서 보존 + 수술종수 정제 프롬프트 개선

## 1) Goal

두 가지 잔여 OCR 품질 문제를 수정하고, 수정 결과를 테스트·시각화·보고서로 검증한다.

1. **`_fields_to_lines()` X-순서 오류**: Y-그룹 내 필드를 center_X로 재정렬하면서 CLOVA의 원본 읽기 순서가 파괴된다. 인접한 단어("원칙적으로"/"각각", "생기고"/"다른")의 bounding box X 좌표 정밀도 오차가 순서를 역전시킨다.

2. **`numeric_cell_refiner.py` 대형 테이블 처리 실패**: Vision LLM에게 17행 전체 table_json을 에코하도록 요구하면 max_tokens=3072를 초과해 JSON이 잘리고 shape 검증에서 실패한다. CLOVA native p064처럼 셀 내용이 긴 테이블에서 `numeric_refined: False`로 남는다.

---

## 2) Background

### 2-1. 단어 순서 문제 원인

```
현재 코드 (_fields_to_lines):
  sorted(fields, key=lambda v: (_field_center_y(v), _field_center_x(v)))

문제: CLOVA는 fields 배열에 좌→우 읽기 순서로 토큰을 저장한다.
      하지만 center_X로 재정렬하면, 인접 단어의 bbox X 좌표 정밀도 오차가
      순서를 역전시킨다.

증거: True Hybrid와 CLOVA native 양쪽 모두 동일한 단어 쌍이 동일하게 뒤바뀜
      → PP-Structure와 무관, _fields_to_lines() 내부 문제 확정.

p255 사례:
  OCR:  "지급률은 각각 원칙적으로 합산하되"
  원본: "지급률은 원칙적으로 각각 합산하되"
  
  OCR:  "기능장해가 다른 생기고 1관절에"
  원본: "기능장해가 생기고 다른 1관절에"
```

### 2-2. 수술종수 채우기 실패 원인

```
현재 프롬프트: LLM에게 전체 table_json 에코 + _corrections 메타 추가 요구
실제 응답: 17행 × 복잡한 수술해설 텍스트 → max_tokens(3072) 초과 → 잘림
결과: _extract_json_object 파싱 실패 or _same_table_shape_allow_metadata 검증 실패
      → numeric_refined: False (p064 CLOVA native)

True Hybrid p064: 성공 (12 corrections 적용) ← vision 정제 후 구조 단순화
CLOVA native p064: 실패 ← 원본 17행 그대로 prompt에 포함
```

---

## 3) Target Files

### 수정 허용
- `src/parser/clova_ocr.py` — `_fields_to_lines()` 수정
- `src/parser/numeric_cell_refiner.py` — 프롬프트 및 파싱 로직 수정

### 신규 생성
- `tests/test_clova_field_order.py` — X-순서 보존 단위 테스트
- `reports/ocr_method_compare_v51.html` — 수정 후 비교 결과 HTML
- `docs/51_OCR_ORDER_REFINER_REPORT.md` — 구현 및 검증 보고서

### 수정 금지
- `src/parser/ocr_engine.py`, `src/parser/ocr_chunker.py`, `src/parser/table_vision_cleaner.py`
- `src/config.py`, `scripts/ingest.py`
- `scripts/run_true_hybrid_local.py`, `scripts/run_clova_local.py`

---

## 4) Detailed Requirements

### 4-1. `_fields_to_lines()` 수정 — Y-그룹 내 CLOVA 원본 순서 보존

**핵심 원칙**: Y 좌표는 라인 경계 결정에만 사용하고, 같은 라인 내 필드 순서는 CLOVA의 원본 배열 인덱스로 결정한다.

```python
def _fields_to_lines(fields: list[dict], row_gap: float | None = None) -> str:
    """Y 좌표 간격 기반 라인 분리 + CLOVA 원본 순서 보존.

    같은 라인 내 단어 순서는 CLOVA가 반환한 fields 배열의 원본 인덱스(읽기 순서)를 사용한다.
    center_X로 재정렬하지 않는다.
    """
    if not fields:
        return ""
    # (원본_인덱스, field) 쌍으로 Y 기준 정렬만 수행 (X 정렬 없음)
    indexed = sorted(enumerate(fields), key=lambda pair: _field_center_y(pair[1]))

    if row_gap is None:
        row_gap = _adaptive_row_gap([f for _, f in indexed])

    lines: list[list[str]] = []
    current_line: list[tuple[int, str]] = []  # (원본_인덱스, text)
    prev_y: float | None = None

    for orig_idx, field in indexed:
        text = str(field.get("inferText", "")).strip()
        cy = _field_center_y(field)
        if prev_y is not None and (cy - prev_y) > row_gap:
            if current_line:
                # 원본 인덱스 기준 정렬로 CLOVA 읽기 순서 복원
                current_line.sort(key=lambda x: x[0])
                lines.append([t for _, t in current_line if t])
            current_line = []
        if text:
            current_line.append((orig_idx, text))
        prev_y = cy

    if current_line:
        current_line.sort(key=lambda x: x[0])
        lines.append([t for _, t in current_line if t])

    return "\n".join(" ".join(line) for line in lines)
```

> **중요**: `_group_fields_into_rows()`는 표 재구성에 사용되므로 수정하지 않는다 (표 컬럼 배치에는 center_X 정렬이 필요함).

### 4-2. `numeric_cell_refiner.py` — corrections-only delta 형식으로 변경

#### 4-2-1. VISION_PROMPT 교체

전체 table_json 에코 요구를 제거하고 delta-only 형식으로 변경한다.

```python
VISION_PROMPT = """당신은 보험 약관 표의 수술종수 컬럼 값을 판독하는 전문가입니다.
첨부 이미지는 같은 표의 전체 크롭과 수술종수 컬럼 영역 확대 크롭입니다.

이 표에서 수술종수 3개 컬럼은 도메인 규칙상 다음 둘 중 하나여야 합니다.
- 그림/공백 행: 3개 수술종수 컬럼이 모두 공란
- 텍스트 행: 3개 수술종수 컬럼이 모두 N 또는 숫자로 채워짐

아래 후보 행의 blank("") 또는 잘못 인식된 값이 실제 이미지에서 무엇인지 판독하세요.
세로선처럼 보이는 아주 얇은 획도 숫자 "1"일 수 있습니다.

규칙:
- 수술종수 이외 컬럼은 절대 변경하지 마세요.
- 후보 행의 대상 셀마다 가능한 한 반드시 값을 판정하세요.
- 허용 값:
  - 1-3종 역할 컬럼: "N", "1", "2", "3"
  - 1-5종 / 신1-5종 역할 컬럼: "N", "1", "2", "3", "4", "5"
- JSON 형식만 반환하고 다른 설명은 출력하지 마세요.
- **table_json 전체를 에코하지 마세요.** 변경/판독불가 셀만 아래 형식으로 반환하세요.

수술종수 컬럼 역할:
__GRADE_COLUMN_ROLES__

후보 row_index 및 각 행의 수술명:
__CANDIDATE_ROWS__

반환 형식 (이 JSON 구조만 반환):
{
  "corrections": [
    {"row_index": <int>, "col": "<컬럼명>", "to": "<값>", "confidence": "high|medium|low"}
  ],
  "unresolved": [
    {"row_index": <int>, "col": "<컬럼명>", "reason": "not_readable"}
  ]
}
"""
```

#### 4-2-2. `_build_prompt()` 수정

기존 전체 table_json 대신, 후보 행의 수술명만 요약 전달한다.

```python
def _build_prompt(table_json: dict, grade_roles: list[dict], candidate_indexes: list[int]) -> str:
    role_payload = [
        {"col": role["col"], "role": role["role"], "allowed_values": sorted(role["allowed"])}
        for role in grade_roles
    ]
    rows = table_json.get("rows", [])
    candidate_rows_summary = [
        {
            "row_index": idx,
            "수술명": str(rows[idx].get("수술명", ""))[:50] if idx < len(rows) else "",
            "현재값": {
                role["col"]: str(rows[idx].get(role["col"], "")) if idx < len(rows) else ""
                for role in grade_roles
            },
        }
        for idx in candidate_indexes
    ]
    return (
        VISION_PROMPT
        .replace("__GRADE_COLUMN_ROLES__", json.dumps(role_payload, ensure_ascii=False, indent=2))
        .replace("__CANDIDATE_ROWS__", json.dumps(candidate_rows_summary, ensure_ascii=False, indent=2))
    )
```

#### 4-2-3. `_parse_with_retry()` 검증 교체

`_same_table_shape_allow_metadata` 대신 delta 형식 유효성 검증으로 교체한다.

```python
def _is_valid_delta(parsed: dict | None) -> bool:
    """delta 형식 응답이 유효한지 검증한다."""
    if not isinstance(parsed, dict):
        return False
    corrections = parsed.get("corrections")
    unresolved = parsed.get("unresolved")
    # corrections와 unresolved 중 하나 이상이 리스트여야 함
    if corrections is None and unresolved is None:
        return False
    if corrections is not None and not isinstance(corrections, list):
        return False
    if unresolved is not None and not isinstance(unresolved, list):
        return False
    return True


def _parse_with_retry(
    block: LayoutBlock,
    page_image: Image.Image,
    client: Any,
    model: str,
    prompt: str,
) -> dict | None:
    for attempt in range(2):
        parsed = _call_vision(block, page_image, client, model, prompt)
        if _is_valid_delta(parsed):
            return parsed
        LOGGER.warning("Numeric cell refinement returned invalid delta format (attempt %s)", attempt + 1)
    return None
```

#### 4-2-4. `_extract_valid_corrections_and_unresolved()` 교체

delta 형식에서 직접 corrections를 추출한다.

```python
def _extract_valid_corrections_and_unresolved(
    original: dict,
    delta: dict,
    grade_roles: list[dict],
    candidate_indexes: list[int],
) -> tuple[list[dict], list[dict]]:
    corrections: list[dict] = []
    unresolved: list[dict] = []
    original_rows = original.get("rows", [])
    roles_by_col = {role["col"]: role for role in grade_roles}
    candidate_index_set = set(candidate_indexes)
    target_cols_by_row = {
        idx: set(_target_cells_for_row(original_rows[idx], grade_roles))
        for idx in candidate_indexes
        if idx < len(original_rows)
    }

    resolved: set[tuple[int, str]] = set()

    for item in delta.get("corrections", []) or []:
        if not isinstance(item, dict):
            continue
        row_index = item.get("row_index")
        col = str(item.get("col", ""))
        to_val = _normalize_grade_value(item.get("to", ""))
        if not isinstance(row_index, int) or row_index not in candidate_index_set:
            continue
        if col not in roles_by_col or col not in target_cols_by_row.get(row_index, set()):
            continue
        role = roles_by_col[col]
        if to_val not in role["allowed"]:
            unresolved.append({
                "row_index": row_index,
                "col": col,
                "from": str(original_rows[row_index].get(col, "")) if row_index < len(original_rows) else "",
                "reason": "invalid_vision_value",
            })
            continue
        corrections.append({
            "row_index": row_index,
            "col": col,
            "from": str(original_rows[row_index].get(col, "")) if row_index < len(original_rows) else "",
            "to": to_val,
            "method": "vision_llm",
            "reason": CORRECTION_REASON,
            "confidence": str(item.get("confidence", "medium")),
        })
        resolved.add((row_index, col))

    for item in delta.get("unresolved", []) or []:
        if not isinstance(item, dict):
            continue
        row_index = item.get("row_index")
        col = str(item.get("col", ""))
        if not isinstance(row_index, int) or (row_index, col) in resolved:
            continue
        if row_index in candidate_index_set and col in target_cols_by_row.get(row_index, set()):
            unresolved.append({
                "row_index": row_index,
                "col": col,
                "from": str(original_rows[row_index].get(col, "")) if row_index < len(original_rows) else "",
                "reason": str(item.get("reason", "not_readable")),
            })

    # LLM이 응답하지 않은 대상 셀은 missing으로 기록
    for row_index, target_cols in target_cols_by_row.items():
        for col in sorted(target_cols):
            if (row_index, col) not in resolved:
                if not any(u["row_index"] == row_index and u["col"] == col for u in unresolved):
                    unresolved.append({
                        "row_index": row_index,
                        "col": col,
                        "from": str(original_rows[row_index].get(col, "")) if row_index < len(original_rows) else "",
                        "reason": "missing_vision_correction",
                    })

    return corrections, unresolved
```

#### 4-2-5. max_tokens 조정

delta 형식으로 변경했으므로 max_tokens를 줄일 수 있다. 512로 설정한다.

```python
response = client.chat.completions.create(
    model=model,
    max_tokens=512,   # 기존 3072 → 512 (delta 형식)
    ...
)
```

---

## 5) Tests

### 5-1. `tests/test_clova_field_order.py` — 신규 (≥ 4 tests)

기존 `tests/test_clova_word_order.py`의 `make_field()` 헬퍼를 재사용한다.

| 테스트 이름 | 검증 내용 |
|---|---|
| `test_clova_original_order_preserved_over_x_sort` | X 좌표가 역순이어도 CLOVA 원본 인덱스 순서(왼쪽→오른쪽)가 유지됨 |
| `test_swapped_bbox_x_uses_original_index` | "각각"이 "원칙적으로"보다 center_X가 작아도 원본 순서 보존 |
| `test_two_rows_x_sort_not_applied` | 같은 Y-그룹 내에서 X로 정렬되지 않음을 확인 |
| `test_cross_row_order_still_correct` | 서로 다른 Y-그룹 간 순서는 Y 기준으로 올바르게 정렬 |

테스트 설계 예시:

```python
def test_clova_original_order_preserved_over_x_sort() -> None:
    # CLOVA 원본 순서: 원칙적으로(idx=0) → 각각(idx=1)
    # 하지만 center_X: 각각(X=50) < 원칙적으로(X=80)
    # → X 정렬 시 "각각 원칙적으로" 가 되어야 하지만,
    #   원본 인덱스 정렬 시 "원칙적으로 각각" 이 되어야 함.
    fields = [
        make_field(x1=70, y1=10, x2=110, y2=30, text="원칙적으로"),  # idx=0, center_X=90
        make_field(x1=40, y1=11, x2=65, y2=31, text="각각"),         # idx=1, center_X=52
    ]
    # 수정 전(X 정렬): "각각 원칙적으로"
    # 수정 후(원본 인덱스): "원칙적으로 각각"
    assert _fields_to_lines(fields, row_gap=5.0) == "원칙적으로 각각"
```

### 5-2. `tests/test_numeric_refiner_delta.py` — 신규 (≥ 3 tests)

| 테스트 이름 | 검증 내용 |
|---|---|
| `test_delta_format_corrections_applied` | delta {"corrections": [...]} 로부터 올바르게 보정값 추출 |
| `test_delta_format_invalid_value_rejected` | 허용값이 아닌 to 값은 unresolved로 이동 |
| `test_delta_format_missing_row_logged` | LLM이 응답하지 않은 대상 셀은 missing_vision_correction으로 기록 |

### 5-3. 기존 테스트 전체 회귀

```bash
pytest -q
# 목표: 0 failures (기존 212 + 신규 ≥ 7 = ≥ 219 passed)
```

---

## 6) OCR 재실행 및 HTML 시각화

### 6-1. 수정 후 재실행

아래 페이지들을 True Hybrid와 CLOVA native 양쪽으로 재실행하여 비교 데이터를 생성한다.

```bash
# True Hybrid
python scripts/run_full_ocr.py \
  --doc 실무가이드 --pages 64,65,68,74,151,255,279 \
  --force --yes \
  --output-dir reports/full_ocr_method_compare_v51/true_hybrid

python scripts/run_full_ocr.py \
  --doc 상담사례집 --pages 65,189,211,273 \
  --force --yes \
  --output-dir reports/full_ocr_method_compare_v51/true_hybrid

# CLOVA native
python scripts/run_full_ocr.py \
  --doc 실무가이드 --pages 64,65,68,74,151,255,279 \
  --clova-native --force --yes \
  --output-dir reports/full_ocr_method_compare_v51/clova_native

python scripts/run_full_ocr.py \
  --doc 상담사례집 --pages 65,189,211,273 \
  --clova-native --force --yes \
  --output-dir reports/full_ocr_method_compare_v51/clova_native
```

### 6-2. 비교 HTML 생성

`scripts/generate_ocr_image_compare_html.py` 또는 동등한 방식으로 아래 내용을 포함한 `reports/ocr_method_compare_v51.html` 을 생성한다.

포함 내용:
- 각 페이지별 섹션 (원본 이미지 + True Hybrid 결과 + CLOVA native 결과)
- 각 블록의 텍스트 내용을 나란히 표시
- 표(table) 블록은 HTML `<table>`로 렌더링
- `numeric_refined: True` 블록은 시각적으로 표시 (예: 녹색 배지)
- `vision_cleaned: True` 블록도 표시

검증 체크리스트 (HTML 생성 후 확인):
- [ ] p255 True Hybrid 텍스트 블록에서 "원칙적으로 각각" 순서 확인 (기존 "각각 원칙적으로" 반전 여부)
- [ ] p255 CLOVA native 텍스트 블록에서 동일 확인
- [ ] p064 CLOVA native 표에서 `numeric_refined: True` + "1-3종" 컬럼 채워짐 확인
- [ ] 기존에 정상이었던 p068, p074, p151 페이지 품질 유지 확인

---

## 7) Stop Rules

- 기존 `pytest -q`에서 1건이라도 실패 → 즉시 중단, 보고
- `_fields_to_lines()` 수정으로 기존 `test_clova_word_order.py` 5개 테스트 중 1건이라도 실패 → 즉시 중단, 보고
- `reconstruct_table_from_fields()`(표 재구성 로직)가 `_group_fields_into_rows()`를 사용하므로, 표 관련 기존 테스트 실패 → 즉시 중단, 보고
- OCR 재실행 시 CLOVA 401 → 중단, 보고
- OCR 재실행 시 네트워크 오류 (Codex 샌드박스 제한) → 네트워크 오류를 보고서에 명시하고 계속 (HTML 생성 단계는 이미 생성된 데이터로 진행)

---

## 8) Output Requirements

`docs/51_OCR_ORDER_REFINER_REPORT.md` 작성 후 커밋·푸시.

보고서 포함 항목:
1. 수정 함수 목록 (한 줄 설명)
2. `pytest -q` 전체 출력
3. `pytest tests/test_clova_field_order.py tests/test_numeric_refiner_delta.py -v` 출력
4. **Before/After 비교** (p255): 수정 전후 `_fields_to_lines()` 출력 비교 (테스트 필드 세트 사용)
5. **p064 CLOVA native** numeric_refined 결과: 수정 전후 corrections 수 비교
6. 비교 HTML 경로 및 주요 검증 체크리스트 통과 여부
7. 잔여 블로커 ("None" 또는 구체적 내용)

커밋 대상:
- `src/parser/clova_ocr.py`
- `src/parser/numeric_cell_refiner.py`
- `tests/test_clova_field_order.py`
- `tests/test_numeric_refiner_delta.py`
- `reports/ocr_method_compare_v51.html`
- `docs/51_OCR_ORDER_REFINER_REPORT.md`
