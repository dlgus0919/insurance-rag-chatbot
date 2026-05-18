# Codex Spec #65 — 비급여(N값) 행 C 주입 차단 + 중간점(·) 정규화 매칭

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **성격:** 버그 수정 × 2  
> **우선순위:** 🔴 높음 — eval [02] 영구 MISS 해결 포함

---

## 0. 배경

두 가지 독립적인 버그가 확인됐다.

### 버그 A — 중간점(·) 미처리로 수술명 조회 실패 (eval [02])

`data/index/surgery_grades.parquet` row 418: `'수 · 족골 적출술 (=수,족골 적제술)'`

- eval [02] 질의: "수족골 적출술의 1-3종·1-5종·신1-5종 수술종수는?"  
- 추출 수술명: `'수족골 적출술'`  
- `_normalize_lookup_text()`: `re.sub(r"\s+", "", ...)` — 공백은 제거하지만 **중간점(·)은 제거하지 않음**  
- 정규화 결과 저장값 = `'수·족골적출술(=수,족골적제술)'`, 쿼리 = `'수족골적출술'`  
- `'수족골적출술' in '수·족골적출술(=수,족골적제술)'` → **False** → C 조회 실패  
- 실제 종수 값: 1-3종=1, 1-5종=2, 신1-5종=2 (정답 데이터는 Parquet에 이미 존재)

### 버그 B — 비급여(N값) 행 반환으로 C 오주입

`data/index/surgery_grades.parquet` 中 **574행**은 세 grade 컬럼(`종_1_3`, `종_1_5`, `종_신1_5`) 이 모두 `'N'`인 **비급여(보험 비지급) 수술**이다.

현재 `lookup_surgery_grade()`는 부분 일치 검색 후 **첫 번째 행**을 반환한다. 질의 수술명이 비급여 수술명에 부분 일치하면 아래와 같은 잘못된 C 블록이 주입된다.

```
[구조화 데이터 — 직접 조회 (C)]
수술명: 절개술
1-3종: N | 1-5종: N | 신1-5종: N
출처: 실무가이드 p.25
```

이 경우 LLM은 "N"을 종수로 출력하거나 혼란을 겪어 grade_accuracy가 하락한다.

---

## 1. 수정 범위

### 1-1. `src/rag/table_store.py` — `_normalize_lookup_text()` 중간점 제거 (버그 A)

**수정 내용:** 정규화 함수에서 중간점(`·`)과 유사 Unicode 기호를 추가로 제거한다.

```python
# 기존 (수정 전)
def _normalize_lookup_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", "", text).lower()
```

```python
# 수정 후 — 중간점 계열 기호 추가 제거
_MIDDLE_DOT_PATTERN = re.compile(r"[\s·•·‧⋅･·・]")  # 공백 + 중간점 계열

def _normalize_lookup_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return _MIDDLE_DOT_PATTERN.sub("", text).lower()
```

> **포함 기호:** U+00B7 `·` (MIDDLE DOT), U+2022 `•` (BULLET), U+2027 `‧` (HYPHENATION POINT), U+22C5 `⋅` (DOT OPERATOR), U+FF65 `･` (HALFWIDTH KATAKANA MIDDLE DOT), U+30FB `･` (KATAKANA MIDDLE DOT), U+30FB `・` (KATAKANA MIDDLE DOT)  
> 실무가이드에서 확인된 기호는 U+00B7 `·`이며, 나머지는 방어적 포함이다.

**검증:**
```python
assert _normalize_lookup_text("수 · 족골 적출술\n(=수,족골 적제술)") == "수족골적출술(=수,족골적제술)"
assert _normalize_lookup_text("수족골 적출술") == "수족골적출술"
# 부분 일치 확인
assert "수족골적출술" in "수족골적출술(=수,족골적제술)"  # → True → 조회 성공
```

---

### 1-2. `src/rag/table_store.py` — `lookup_surgery_grade()` N값 필터 (버그 B)

**수정 내용:** 조회된 행의 세 grade 컬럼이 모두 `'N'`이면 `None`을 반환한다. 비급여 수술은 C 주입 대상에서 제외하는 것이 올바른 동작이다.

```python
# 기존 (수정 전) — hits.iloc[0]을 그대로 반환
hits = df[mask]
if hits.empty:
    return None
return _clean_record(hits.iloc[0].to_dict())
```

```python
# 수정 후 — 비급여(전 컬럼 N) 행을 건너뛰고 첫 번째 유효 행 반환
_GRADE_COLUMNS = ("종_1_3", "종_1_5", "종_신1_5")

hits = df[mask]
if hits.empty:
    return None

for _, row in hits.iterrows():
    if all(str(row.get(col, "N")) == "N" for col in _GRADE_COLUMNS if col in row.index):
        continue   # 비급여 행 스킵
    return _clean_record(row.to_dict())

# 모든 hit가 비급여이면 None 반환 (C 주입 차단)
return None
```

> **`_GRADE_COLUMNS`**: 모듈 상수로 정의. `lookup_surgery_grade()` 함수 외부 모듈 레벨에 위치.

---

## 2. 단위 테스트

`tests/test_table_store.py`에 아래 케이스를 추가한다.

```python
def _make_store(tmp_path, data: dict) -> "TableStore":
    import pandas as pd
    from src.rag.table_store import TableStore
    surgery_path = tmp_path / "surgery_grades.parquet"
    pd.DataFrame(data).to_parquet(surgery_path)
    disability_path = tmp_path / "disability_rates.parquet"
    pd.DataFrame({"장해분류": [], "지급률": []}).to_parquet(disability_path)
    return TableStore(surgery_path=surgery_path, disability_path=disability_path)

_BASE_COLS = {
    "수술명_원문": [], "수술해설": [],
    "source_page_label": [], "source_file": [],
    "table_type": [], "table_group_id": [],
    "group_page_range": [], "is_page_continued": [],
}

def test_normalize_removes_middle_dot():
    """_normalize_lookup_text가 중간점(·)을 제거하는지 검증한다."""
    from src.rag.table_store import _normalize_lookup_text
    assert _normalize_lookup_text("수 · 족골 적출술\n(=수,족골 적제술)") == "수족골적출술(=수,족골적제술)"
    assert _normalize_lookup_text("수족골 적출술") == "수족골적출술"

def test_lookup_surgery_grade_middle_dot_match(tmp_path):
    """중간점 포함 수술명('수 · 족골 적출술')이 '수족골 적출술' 쿼리로 매칭되는지 검증한다."""
    data = {
        "수술명": ["수 · 족골 적출술 (=수,족골 적제술)"],
        "수술명_원문": ["수 · 족골 적출술\n(=수,족골 적제술)"],
        "수술해설": [""],
        "종_1_3": ["1"], "종_1_5": ["2"], "종_신1_5": ["2"],
        "source_page_label": ["63"], "source_file": ["실무가이드"],
        "table_type": ["new"], "table_group_id": [0],
        "group_page_range": ["63-63"], "is_page_continued": [False],
    }
    store = _make_store(tmp_path, data)
    result = store.lookup_surgery_grade("수족골 적출술")
    assert result is not None, "중간점 포함 수술명이 매칭돼야 함"
    assert result["종_1_3"] == "1"
    assert result["종_1_5"] == "2"

def test_lookup_surgery_grade_skips_all_n_rows(tmp_path):
    """비급여(N, N, N) 행만 hit될 때 None 반환을 검증한다."""
    data = {
        "수술명": ["절개술", "충수절제술"],
        "수술명_원문": ["절개술", "충수절제술"],
        "수술해설": ["", ""],
        "종_1_3": ["N", "2"], "종_1_5": ["N", "3"], "종_신1_5": ["N", "2"],
        "source_page_label": ["25", "64"], "source_file": ["실무가이드", "실무가이드"],
        "table_type": ["new", "new"], "table_group_id": [0, 1],
        "group_page_range": ["25-25", "64-64"], "is_page_continued": [False, False],
    }
    store = _make_store(tmp_path, data)

    # "절개술"은 N행만 → None 반환해야 함
    assert store.lookup_surgery_grade("절개술") is None

    # "충수절제술"은 유효 행 → 결과 반환해야 함
    result = store.lookup_surgery_grade("충수절제술")
    assert result is not None
    assert result["종_1_3"] == "2"
```

---

## 3. 검증

### 3-1. 단위 테스트

```bash
pytest tests/test_table_store.py -v
pytest -q
```

**기대:** 전원 pass (`244 passed` 이상).

### 3-2. 영향 규모 확인

```bash
cd "/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇"
python3 -c "
import pandas as pd, re
df = pd.read_parquet('data/index/surgery_grades.parquet')
gc = ['종_1_3', '종_1_5', '종_신1_5']
all_n = df[gc].apply(lambda c: c.astype(str) == 'N').all(axis=1)
print(f'비급여 행 수: {all_n.sum()} / {len(df)}')
print(f'수정 후 유효 행 수: {(~all_n).sum()}')
"
```

### 3-3. eval 재실행 (선택)

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_TEMPERATURE=0 python scripts/eval.py --ocr
```

grade_accuracy, rate_accuracy 유지 또는 개선 확인.

---

## 4. 중단 조건

- pytest 실패 → 즉시 중단
- `lookup_surgery_grade("충수절제술")` 결과 `None` → 구현 오류, 재확인

---

## 5. 보고서 요구사항

`docs/65_N_VALUE_GUARD_REPORT.md`에 다음을 포함한다.

1. 버그 A: `_normalize_lookup_text()` 수정 전/후 `'수 · 족골 적출술'` 조회 결과 비교
2. 버그 B: 비급여 행 반환 동작 수정 전/후 비교
3. 추가된 단위 테스트 결과 (3개 케이스)
4. pytest 전체 결과 (`245 passed` 이상 기대)
5. (선택) eval [02] 항목 recall 변화 확인

---

## 6. 커밋

커밋 메시지: `Fix table_store: middle-dot normalization + skip all-N rows in surgery lookup (spec #65)`  
푸시: `origin/master`
