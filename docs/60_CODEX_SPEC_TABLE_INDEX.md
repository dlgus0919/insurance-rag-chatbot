# Codex Spec #60 — Approach C: 수술종수표·장해분류표 Parquet 인덱스 구축

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **성격:** 구현 (신규 스크립트 + 신규 모듈 + pipeline 연동)  
> **우선순위:** 🔴 높음 — grade_accuracy 0.294, rate_accuracy 0.429 모두 목표 미달

---

## 1. 배경 및 설계 근거

### 1-1. 실제 표 구조 (사전 분석 완료)

**수술종수표** (`data/extracted/실무가이드/tables/p032_t00.json` ~ `p175_t00.json`)

- **총 192개** 청크 파일, **p33~p175 연속 1개 거대 표** (실무가이드 수술종수 섹션)
- 기본 헤더: `['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']` — 175개 (92%)
- 변형 헤더 패턴:

| 패턴 | 빈도 | 처리 방법 |
|---|---|---|
| `수술명_2`, `수술해설_2` suffix 중복 | 10개 | 값이 동일하면 중복 제거, 다르면 별도 행 |
| `수술해설_2`, `수술해설_3` (긴 설명 분할) | 10개 | 텍스트 합쳐 단일 `수술해설` 컬럼으로 |
| `산1-5종` (OCR 오타) | 1개 | `신1-5종`으로 정규화 |
| `col_3` (1-3종 인식 실패) | 1개 | `종_1_3`으로 매핑 후 저장 |
| `col_1` (번호 컬럼) | 1개 | 해당 컬럼 무시 |

**장해분류표** (`p235_t00.json` ~ `p278_t00.json`, 총 13개 파일)

아래 매핑은 인접 텍스트 블록에서 직접 확인한 신체부위 라벨이다:

| source_file | page_label | 신체부위 | headers 특이사항 |
|---|---|---|---|
| p235_t00 | 236 | 눈의 장해 | 표준 |
| p241_t00 | 242 | 귀의 장해 | 표준 |
| p244_t00 | 245 | 코의 장해 | `[그림]` 행 포함 |
| p246_t00 | 247 | 씹어먹거나 말하는 장해 | 복합 지급률 행 |
| p250_t00 | 251 | 척추(등뼈)의 장해 | 표준 |
| p253_t00 | 254 | 체간골의 장해 | `[그림]` 행 포함 |
| p256_t00 | 257 | 다리의 장해 | 표준 |
| p263_t00 | 264 | 손가락의 장해 | 표준 |
| p265_t00 | 266 | 발가락의 장해 | 표준 |
| p267_t00 | 268 | 신경계·정신행동 장해 | 표준 + 범위값 |
| p270_t00 | 271 | 신경계·정신행동 장해 (ADL표) | 헤더 비표준: `['유 형', '제한정도에 따른 지급률']` |
| p276_t00 | 277 | 정신행동 장해 (지급률별 기준표) | rows 전체 공백 — **스킵** |
| p278_t00 | 279 | 정신행동 장해 (GAF 척도) | 헤더 비표준: `['GAF 점수', '판 단 기 준', '장해율']` |

### 1-2. OCR 노이즈 패턴

실제 데이터에서 확인된 노이즈:

```
"5\n10%"    → 지급률이 두 행에 걸쳐 OCR된 것 → 별도 행 2개로 분리
"80\n40%"   → 동일 → 분리
"10~100"    → 범위형 지급률 → rate_range = (10, 100), rate = null
"[그림]"    → 이미지 셀 → null 처리
""          → 빈 수술명 행 → 스킵
```

---

## 2. 구현 파일 목록

| 파일 | 유형 | 내용 |
|---|---|---|
| `scripts/build_table_index.py` | **신규** | Parquet 인덱스 생성 스크립트 |
| `data/index/surgery_grades.parquet` | **생성물** | 수술종수표 전체 행 |
| `data/index/disability_rates.parquet` | **생성물** | 장해분류표 전체 행 |
| `src/rag/table_store.py` | **신규** | Parquet 조회 인터페이스 |
| `src/rag/pipeline.py` | **수정** | `table_store` 파라미터 활성화 |
| `tests/test_table_store.py` | **신규** | 단위 테스트 |

---

## 3. Task 1 — `scripts/build_table_index.py`

### 3-1. 실행 방법

```bash
python scripts/build_table_index.py
# 출력: data/index/surgery_grades.parquet
#       data/index/disability_rates.parquet
```

`data/index/` 디렉토리가 없으면 자동 생성.

### 3-2. 수술종수표 파싱 규칙

**식별 조건:** headers에 `1-3종` 또는 `1-5종` 이 포함된 테이블 청크.

**출력 컬럼:**

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `수술명` | str | 정규화된 수술명 (줄바꿈→공백, 앞뒤 공백 제거) |
| `수술명_원문` | str | 원본 수술명 그대로 |
| `수술해설` | str | 수술 설명 (수술해설_2 등 suffix 합산) |
| `종_1_3` | str | 1-3종 값 (숫자 문자열 또는 'N', '') |
| `종_1_5` | str | 1-5종 값 |
| `종_신1_5` | str | 신1-5종 값 |
| `source_page_label` | int | 페이지 번호 (책 기준) |
| `source_file` | str | 원본 JSON 파일명 (예: `p032_t00.json`) |
| `table_type` | str | `"surgery_grade"` 고정 |
| `table_group_id` | str | `"수술종수표"` 고정 |
| `group_page_range` | str | `"33-175"` (수술종수표 전체 범위) |
| `is_page_continued` | bool | True이면 앞 페이지와 이어진 표 |

**헤더 정규화 로직:**

```python
def normalize_surgery_headers(headers):
    """헤더 리스트 → (수술명컬럼, 수술해설컬럼들, grade컬럼 매핑) 반환"""
    # 1-3종 컬럼 식별 (col_3 fallback 포함)
    col_13 = next((h for h in headers if '1-3종' in h or h == 'col_3'), None)
    col_15 = next((h for h in headers if '1-5종' in h), None)
    col_s15 = next((h for h in headers if '신1-5종' in h or '산1-5종' in h), None)
    
    # 수술명 컬럼들 (수술명, 수술명_2)
    name_cols = [h for h in headers if h.startswith('수술명')]
    # 수술해설 컬럼들
    desc_cols = [h for h in headers if h.startswith('수술해설')]
    
    return name_cols, desc_cols, col_13, col_15, col_s15
```

**행 분리 규칙 (수술명_2 처리):**

```python
def expand_row(row, name_cols, desc_cols, col_13, col_15, col_s15):
    """수술명_2가 수술명과 다를 경우 두 행으로 분리"""
    rows_out = []
    primary_name = row.get('수술명', '').strip()
    secondary_name = row.get('수술명_2', '').strip() if '수술명_2' in row else ''
    
    # 빈 수술명 행 스킵
    if not primary_name and not secondary_name:
        return []
    
    # 수술해설 합산
    desc = ' '.join(
        row.get(c, '').strip() for c in desc_cols if row.get(c, '').strip()
    )
    desc = desc.replace('[그림]', '').strip()
    
    grade_vals = {
        '종_1_3': row.get(col_13, '') if col_13 else '',
        '종_1_5': row.get(col_15, '') if col_15 else '',
        '종_신1_5': row.get(col_s15, '') if col_s15 else '',
    }
    
    # primary 행
    if primary_name:
        rows_out.append({'수술명': primary_name.replace('\n', ' '),
                         '수술명_원문': primary_name,
                         '수술해설': desc, **grade_vals})
    
    # secondary 행 (primary와 다를 때만)
    if secondary_name and secondary_name != primary_name:
        rows_out.append({'수술명': secondary_name.replace('\n', ' '),
                         '수술명_원문': secondary_name,
                         '수술해설': desc, **grade_vals})
    
    return rows_out
```

**연속 표 탐지:**

```python
# 수술종수표가 연속 페이지에 걸쳐 있는지 판단
# 첫 번째 수술종수표 페이지 = is_page_continued=False
# 이후 연속 페이지 = is_page_continued=True
first_surgery_page = min(p['source_page_label'] for p in all_surgery_rows)
for row in all_surgery_rows:
    row['is_page_continued'] = (row['source_page_label'] > first_surgery_page)
```

### 3-3. 장해분류표 파싱 규칙

**식별 조건:** headers가 `['장해의 분류', '지급률']` 이거나, source_file이 아래 하드코딩 목록에 포함.

**신체부위 라벨 매핑** (하드코딩 — 사전 분석으로 확인 완료):

```python
DISABILITY_BODY_PART_MAP = {
    'p235_t00.json': '눈의 장해',
    'p241_t00.json': '귀의 장해',
    'p244_t00.json': '코의 장해',
    'p246_t00.json': '씹어먹거나 말하는 장해',
    'p250_t00.json': '척추(등뼈)의 장해',
    'p253_t00.json': '체간골의 장해',
    'p256_t00.json': '다리의 장해',
    'p263_t00.json': '손가락의 장해',
    'p265_t00.json': '발가락의 장해',
    'p267_t00.json': '신경계·정신행동 장해',
    'p270_t00.json': '신경계·정신행동 장해 (ADL)',
    'p276_t00.json': None,   # rows 전체 공백 → 스킵
    'p278_t00.json': '정신행동 장해 (GAF)',
}
```

**출력 컬럼:**

| 컬럼명 | 타입 | 설명 |
|---|---|---|
| `신체부위` | str | 위 매핑에서 가져온 라벨 |
| `장해분류` | str | 정규화된 장해 분류 원문 |
| `장해분류_원문` | str | 원본 그대로 |
| `지급률` | str | 정규화된 지급률 숫자 문자열 (예: `"60"`) |
| `지급률_원문` | str | 원본 (예: `"60%"`, `"5\n10%"`) |
| `지급률_범위_최소` | float | 범위형일 때 최솟값 (예: `10.0`), 단일값이면 null |
| `지급률_범위_최대` | float | 범위형일 때 최댓값, 단일값이면 null |
| `source_page_label` | int | 페이지 번호 |
| `source_file` | str | 원본 JSON 파일명 |
| `table_type` | str | `"disability_rate"` 고정 |
| `table_group_id` | str | 신체부위와 동일 |
| `is_page_continued` | bool | 해당 신체부위 표에서 두 번째 이후 파일이면 True |

**지급률 정규화 로직:**

```python
import re

def parse_rate(raw: str):
    """
    "60%"      → rate="60", min=null, max=null
    "5\n10%"   → 두 행으로 분리: ("5", null, null), ("10", null, null)
    "80\n40%"  → 분리: ("80", ...), ("40", ...)
    "10~100"   → rate=null, min=10.0, max=100.0
    "[그림]"   → rate=null, min=null, max=null  (스킵)
    ""         → 스킵
    """
    raw = raw.strip()
    if not raw or raw == '[그림]':
        return []
    
    # 줄바꿈으로 여러 값 분리
    parts = [p.strip() for p in raw.replace('%', '').split('\n') if p.strip()]
    results = []
    for part in parts:
        if '~' in part:
            nums = re.findall(r'\d+', part)
            if len(nums) >= 2:
                results.append({'지급률': None,
                                 '지급률_원문': raw,
                                 '지급률_범위_최소': float(nums[0]),
                                 '지급률_범위_최대': float(nums[1])})
        else:
            nums = re.findall(r'\d+', part)
            if nums:
                results.append({'지급률': nums[0],
                                 '지급률_원문': raw,
                                 '지급률_범위_최소': None,
                                 '지급률_범위_최대': None})
    return results
```

**장해분류 행 분리 규칙:**

지급률 셀에 `\n`이 포함된 경우, 해당 행의 장해분류 셀도 `\n`으로 분리되어 여러 항목이 합산된 것으로 간주한다.

```python
def expand_disability_row(row):
    """장해분류와 지급률이 복합 셀인 경우 분리"""
    classification = row.get('장해의 분류', '') or row.get(headers[0], '')
    rate_raw = row.get('지급률', '') or row.get(headers[1], '')
    
    # 장해분류 줄바꿈 분리
    class_parts = [c.strip() for c in classification.split('\n') if c.strip()]
    rate_results = parse_rate(rate_raw)
    
    if not class_parts or not rate_results:
        # 하나라도 비어있으면 장해분류를 하나로 합치고 지급률 각각 적용
        combined_class = ' '.join(class_parts) if class_parts else ''
        return [{'장해분류': combined_class, **r} for r in rate_results]
    
    # 장해분류와 지급률 수가 같으면 1:1 매핑
    if len(class_parts) == len(rate_results):
        return [{'장해분류': c, **r} for c, r in zip(class_parts, rate_results)]
    
    # 수가 다르면 장해분류를 합쳐서 각 지급률에 반복
    combined_class = ' / '.join(class_parts)
    return [{'장해분류': combined_class, **r} for r in rate_results]
```

**비표준 헤더 테이블 처리:**

- `p270_t00.json` (ADL표): `['유 형', '제한정도에 따른 지급률']`
  - `장해분류 = row['유 형']`
  - `지급률_원문 = row['제한정도에 따른 지급률']`
  - 지급률은 텍스트 서술형 → `지급률 = null`, `지급률_원문` 보존
- `p278_t00.json` (GAF표): `['GAF 점수', '판 단 기 준', '장해율']`
  - `장해분류 = row['GAF 점수'] + " " + row['판 단 기 준']`
  - `지급률 = row['장해율']` (parse_rate 적용)
- `p276_t00.json`: rows 전체 공백 → **파일 전체 스킵**

---

## 4. Task 2 — `src/rag/table_store.py`

```python
"""
TableStore: Parquet 기반 수술종수·장해분류 직접 조회 인터페이스

사용 예:
    store = TableStore()
    result = store.lookup_surgery_grade("충수절제술")
    # → {"수술명": "충수절제술", "종_1_3": "1", "종_1_5": "2", "종_신1_5": "2", "source_page_label": 109}

    result = store.lookup_disability_rate("한 팔의 손목 이상을 잃었을 때")
    # → {"장해분류": "...", "지급률": "60", "신체부위": "팔의 장해", "source_page_label": 255}
"""

import pandas as pd
from pathlib import Path
from functools import lru_cache

SURGERY_GRADES_PATH = Path("data/index/surgery_grades.parquet")
DISABILITY_RATES_PATH = Path("data/index/disability_rates.parquet")


class TableStore:
    def __init__(self,
                 surgery_path: Path = SURGERY_GRADES_PATH,
                 disability_path: Path = DISABILITY_RATES_PATH):
        self._surgery_df: pd.DataFrame | None = None
        self._disability_df: pd.DataFrame | None = None
        self._surgery_path = surgery_path
        self._disability_path = disability_path

    def _load_surgery(self):
        if self._surgery_df is None:
            self._surgery_df = pd.read_parquet(self._surgery_path)

    def _load_disability(self):
        if self._disability_df is None:
            self._disability_df = pd.read_parquet(self._disability_path)

    def lookup_surgery_grade(self, surgery_name: str) -> dict | None:
        """
        수술명으로 수술종수 행 조회.
        부분 일치(str.contains) 사용. 첫 번째 매칭 행 반환.
        매칭 없으면 None 반환.
        """
        self._load_surgery()
        df = self._surgery_df
        # 정규화된 수술명에서 부분 일치
        mask = df['수술명'].str.contains(
            surgery_name.replace('(', r'\(').replace(')', r'\)'),
            na=False, regex=True
        )
        if not mask.any():
            # 더 넓은 매칭: 각 단어 부분 포함
            for token in surgery_name.split():
                if len(token) >= 2:
                    mask = df['수술명'].str.contains(token, na=False)
                    if mask.any():
                        break
        hits = df[mask]
        if hits.empty:
            return None
        row = hits.iloc[0].to_dict()
        return row

    def lookup_disability_rate(self, query_region: str) -> dict | None:
        """
        장해 부위/유형 문자열로 장해분류 행 조회.
        부분 일치 사용. 첫 번째 매칭 행 반환.
        매칭 없으면 None 반환.
        """
        self._load_disability()
        df = self._disability_df
        # 지급률이 있는 행만 (null 제외)
        valid = df[df['지급률'].notna() & (df['지급률'] != '')]
        mask = valid['장해분류'].str.contains(
            query_region.replace('(', r'\(').replace(')', r'\)'),
            na=False, regex=True
        )
        if not mask.any():
            for token in query_region.split():
                if len(token) >= 2:
                    mask = valid['장해분류'].str.contains(token, na=False)
                    if mask.any():
                        break
        hits = valid[mask]
        if hits.empty:
            return None
        row = hits.iloc[0].to_dict()
        return row

    def is_available(self) -> bool:
        return self._surgery_path.exists() and self._disability_path.exists()
```

---

## 5. Task 3 — `src/rag/pipeline.py` 수정

`_build_structured_context()` 의 `table_store=None` 파라미터를 실제로 활성화한다.

### 5-1. 기존 C hook 코드 확인 (spec #58에서 작성됨)

```python
def _build_structured_context(
    question: str,
    chunks: list[Chunk],
    table_store=None,   # ← C 예약 파라미터
) -> str | None:
    ...
    if table_store is not None:   # ← C hook (현재 주석/미구현)
        ...
```

### 5-2. C hook 구현

`table_store is not None` 분기에서 아래 로직을 구현한다:

```python
if table_store is not None and table_store.is_available():
    # 수술종수 직접 조회 (B의 table_json 조회보다 우선)
    surgery_name = _extract_surgery_name_from_query(question)
    if surgery_name:
        result = table_store.lookup_surgery_grade(surgery_name)
        if result:
            lines = [
                "[구조화 데이터 — 직접 조회 (C)]",
                f"수술명: {result['수술명']}",
                f"1-3종: {result['종_1_3']} | 1-5종: {result['종_1_5']} | 신1-5종: {result['종_신1_5']}",
                f"출처: 실무가이드 p.{result['source_page_label']}",
            ]
            return '\n'.join(lines)
    
    # 장해 지급률 직접 조회
    region = _extract_disability_region_from_query(question)
    if region:
        result = table_store.lookup_disability_rate(region)
        if result:
            rate_str = f"{result['지급률']}%" if result.get('지급률') else \
                       f"{result['지급률_범위_최소']}~{result['지급률_범위_최대']}%"
            lines = [
                "[구조화 데이터 — 직접 조회 (C)]",
                f"신체부위: {result['신체부위']}",
                f"장해 분류: {result['장해분류']}",
                f"지급률: {rate_str}",
                f"출처: 실무가이드 p.{result['source_page_label']}",
            ]
            return '\n'.join(lines)

# C 조회 실패 시 기존 B 로직(table_json)으로 fallback
```

### 5-3. `answer()` 함수 수정

`TableStore`를 싱글턴으로 생성하여 `_build_structured_context()`에 전달한다.

```python
# pipeline.py 모듈 상단 또는 RagPipeline.__init__에서
from src.rag.table_store import TableStore

# RagPipeline 클래스 내
def __init__(self, ...):
    ...
    self._table_store = TableStore()  # Parquet이 없으면 is_available()=False

def answer(self, question: str, ...) -> str:
    chunks = self.retrieve_hits(question, ...)
    structured_ctx = _build_structured_context(
        question, chunks, table_store=self._table_store
    )
    prompt = build_user_prompt(question, chunks)
    if structured_ctx:
        prompt = f"{structured_ctx}\n\n{prompt}"
    ...
```

---

## 6. Task 4 — `tests/test_table_store.py`

아래 테스트를 작성한다. Parquet 파일이 없는 환경에서도 테스트가 통과해야 하므로, `tmp_path` fixture로 임시 Parquet을 만들어 사용한다.

```python
import pandas as pd
import pytest
from pathlib import Path
from src.rag.table_store import TableStore

@pytest.fixture
def sample_surgery_df(tmp_path):
    df = pd.DataFrame([
        {"수술명": "충수절제술(맹장 수술)", "수술명_원문": "충수절제술",
         "수술해설": "맹장과 충수를 절제하는 수술",
         "종_1_3": "1", "종_1_5": "2", "종_신1_5": "2",
         "source_page_label": 109, "source_file": "p108_t00.json",
         "table_type": "surgery_grade", "table_group_id": "수술종수표",
         "group_page_range": "33-175", "is_page_continued": True},
    ])
    path = tmp_path / "surgery_grades.parquet"
    df.to_parquet(path)
    return path

@pytest.fixture
def sample_disability_df(tmp_path):
    df = pd.DataFrame([
        {"신체부위": "다리의 장해",
         "장해분류": "한 팔의 손목 이상을 잃었을 때",
         "장해분류_원문": "한 팔의 손목 이상을 잃었을 때",
         "지급률": "60", "지급률_원문": "60%",
         "지급률_범위_최소": None, "지급률_범위_최대": None,
         "source_page_label": 255, "source_file": "p254_t00.json",
         "table_type": "disability_rate",
         "table_group_id": "팔의 장해", "is_page_continued": False},
    ])
    path = tmp_path / "disability_rates.parquet"
    df.to_parquet(path)
    return path

def test_lookup_surgery_grade_exact(sample_surgery_df, sample_disability_df):
    store = TableStore(surgery_path=sample_surgery_df, disability_path=sample_disability_df)
    result = store.lookup_surgery_grade("충수절제술")
    assert result is not None
    assert result["종_1_5"] == "2"
    assert result["source_page_label"] == 109

def test_lookup_surgery_grade_no_match(sample_surgery_df, sample_disability_df):
    store = TableStore(surgery_path=sample_surgery_df, disability_path=sample_disability_df)
    result = store.lookup_surgery_grade("우주유영수술")
    assert result is None

def test_lookup_disability_rate_exact(sample_surgery_df, sample_disability_df):
    store = TableStore(surgery_path=sample_surgery_df, disability_path=sample_disability_df)
    result = store.lookup_disability_rate("손목 이상을 잃었을 때")
    assert result is not None
    assert result["지급률"] == "60"
    assert result["신체부위"] == "다리의 장해"

def test_table_store_unavailable_when_no_parquet(tmp_path):
    store = TableStore(
        surgery_path=tmp_path / "nonexistent.parquet",
        disability_path=tmp_path / "nonexistent2.parquet"
    )
    assert not store.is_available()

def test_lookup_returns_none_when_unavailable(tmp_path):
    store = TableStore(
        surgery_path=tmp_path / "nonexistent.parquet",
        disability_path=tmp_path / "nonexistent2.parquet"
    )
    # is_available()=False이면 lookup이 안전하게 None 반환
    assert store.lookup_surgery_grade("충수절제술") is None
```

> **주의:** `is_available() == False`일 때 `lookup_*` 함수는 예외를 던지지 않고 `None`을 반환해야 한다.

---

## 7. 검증 절차

### 7-1. 스크립트 실행 및 기본 확인

```bash
python scripts/build_table_index.py

# 행 수 확인
python -c "
import pandas as pd
sg = pd.read_parquet('data/index/surgery_grades.parquet')
dr = pd.read_parquet('data/index/disability_rates.parquet')
print(f'surgery_grades: {len(sg)}행')
print(f'disability_rates: {len(dr)}행')
print()
print('=== surgery_grades 컬럼 ===')
print(sg.columns.tolist())
print(sg[['수술명','종_1_3','종_1_5','종_신1_5','source_page_label','is_page_continued']].head(5).to_string())
print()
print('=== disability_rates 신체부위별 행 수 ===')
print(dr.groupby('신체부위').size().to_string())
print()
print('=== 지급률 샘플 ===')
print(dr[['신체부위','장해분류','지급률','source_page_label']].dropna(subset=['지급률']).head(10).to_string())
"
```

**기대 범위:**
- `surgery_grades`: **1,500행 이상** (192개 파일 × 평균 약 10행, 중복 행 제거 후)
- `disability_rates`: **100행 이상** (12개 유효 파일 × 평균 약 9행)

### 7-2. 핵심 조회 테스트

```bash
python -c "
from src.rag.table_store import TableStore
store = TableStore()

# 수술종수 조회
r = store.lookup_surgery_grade('충수절제술')
assert r is not None, '충수절제술 조회 실패'
assert r['종_1_5'] == '2', f'1-5종 기대값 2, 실제: {r[\"종_1_5\"]}'
print(f'충수절제술 조회 OK: 1-5종={r[\"종_1_5\"]}, p.{r[\"source_page_label\"]}')

# 장해 지급률 조회
r = store.lookup_disability_rate('두 눈이 멀었을 때')
assert r is not None, '두 눈 실명 조회 실패'
assert r['지급률'] == '100', f'지급률 기대 100, 실제: {r[\"지급률\"]}'
print(f'두 눈 실명 조회 OK: 지급률={r[\"지급률\"]}%, p.{r[\"source_page_label\"]}')

r = store.lookup_disability_rate('한 팔의 손목 이상')
assert r is not None
print(f'한 팔 손목 이상 조회 OK: 지급률={r[\"지급률\"]}%')

r = store.lookup_disability_rate('두 귀의 청력을 완전히 잃었을 때')
assert r is not None
assert r['지급률'] == '80'
print(f'두 귀 청력 상실 조회 OK: 지급률={r[\"지급률\"]}%')

print('모든 핵심 조회 PASS')
"
```

### 7-3. 전체 테스트

```bash
pytest -q
```

**기대:** 기존 235 passed + 신규 테스트 (최소 5건) → 240 passed 이상, 0 failures

### 7-4. OCR retrieval eval (회귀 확인)

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py --ocr
```

**기대:** recall@8 = 1.000 유지

---

## 8. 보고서 요구사항

`docs/60_TABLE_INDEX_REPORT.md`에 다음을 포함한다:

1. 생성된 Parquet 파일 행 수 및 컬럼 목록
2. 신체부위별 장해분류 행 수 집계
3. 수술종수표 `is_page_continued` 분포 (첫 페이지 1건, 이후 연속 페이지 N건)
4. 핵심 조회 테스트 결과 (충수절제술, 두 눈 실명, 한 팔 손목, 두 귀 청력)
5. pytest 전체 결과
6. OCR retrieval eval recall@8 결과
7. 미처리 행 목록: `[그림]` 스킵, 빈 수술명 스킵 건수

---

## 9. 중단 조건

- `pytest -q` 실패 → 즉시 중단
- `surgery_grades.parquet` 행 수 < 500 → 파싱 오류 가능성, 즉시 중단 및 보고
- `disability_rates.parquet` 행 수 < 50 → 즉시 중단 및 보고
- `두 눈이 멀었을 때` 조회 결과 지급률 ≠ `"100"` → 즉시 중단

---

## 10. 커밋

커밋 메시지: `Add Parquet table index and TableStore for deterministic grade/rate lookup (spec #60)`  
푸시: `origin/master`
