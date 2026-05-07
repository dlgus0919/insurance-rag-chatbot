# Codex 구현 명세 — 베타 Stage 2: D3·D4 인덱싱 + 사이드바 필터 보강 (M-DB-2)

> **작성:** 기획자 (검토자)
> **작성일:** 2026-05-07
> **기반 커밋:** `62cbda8` (master HEAD, 125 tests passing)
> **대상:** Codex 개발자 에이전트
> **선행 완료:** 베타 Stage 0 (D8 SQLite 적재, 메타 스키마, D3~D7 등록, 백업)
> **참고:** `docs/20_INTEGRATION_ROADMAP.md` §5.2 (Phase B M18·M20), `docs/26_RAW_DOCUMENTS_CATALOG.md`

---

## 0. 현황 및 목표

### 문제

Stage 0 완료 후 현재 인덱스 상태:

| 문서 | doc_short | 인덱스 상태 | 청크 수 |
|------|-----------|------------|---------|
| D1 심평원 | 심평원 | ✅ 인덱싱됨 | 2,286 |
| D2 신한 이지로운 실손 | 약관 | ✅ 인덱싱됨 | 384 |
| D3 SOL건강 (신규) | 자사_SOL건강 | ❌ **미인덱싱** | 0 |
| D4 SOL운전자 (신규) | 자사_SOL운전자 | ❌ **미인덱싱** | 0 |
| D5 보상가이드북 | 가이드북 | ⚠️ 파일 없음 | 0 |
| D6 실무가이드 | 실무가이드 | ❌ OCR 필요 | 0 |
| D7 상담사례집 | 상담사례집 | ❌ OCR 필요 | 0 |

D3·D4는 `PDF_SOURCES`에 등록됐으나 실제 인덱싱이 이뤄지지 않아 **질의해도 검색 결과가 없습니다.**

사이드바에는 `DOC_SHORT_ORDER` 기반으로 D3~D7 체크박스가 표시되지만, 실제 인덱스에 없으므로 선택해도 빈 결과가 반환됩니다 — **UX 문제**.

### 이번 단계 목표

1. **D3·D4 실제 인덱싱** — 자사 약관 2종을 VectorDB + BM25에 추가
2. **`requires_ocr` 소스 자동 제외** — D6·D7이 인덱싱 시도되지 않도록
3. **사이드바 필터 보강** — 인덱싱된 문서만 표시 + 자사/타사 토글 + 상품 유형 필터

---

## 작업 목록

| ID | 제목 | 난이도 | 핵심 변경 파일 |
|----|------|--------|----------------|
| M-DB-2a | `ingest.py` requires_ocr 제외 + D3·D4 인덱싱 실행 | 소 | `scripts/ingest.py`, `src/config.py` |
| M-DB-2b | 사이드바 인덱싱된 문서만 표시 | 소 | `src/config.py`, `src/ui/streamlit_app.py` |
| M-DB-2c | 사이드바 자사/타사 토글 + 상품 유형 필터 | 중 | `src/ui/streamlit_app.py` |

**커밋 전략:** M-DB-2a와 M-DB-2b는 함께 커밋 (인덱스 변경과 UI 수정 동시 적용). M-DB-2c는 독립 커밋.  
**테스트 요건:** `pytest -q --ignore=tests/test_vector_store.py` 기존 통과 수 이상 유지.

---

## M-DB-2a: `ingest.py` 수정 + D3·D4 인덱싱 실행

### 배경

현재 `ingest.py`의 `select_sources()` 함수는 `cloud_safe` 필터만 지원한다.  
D6·D7은 `requires_ocr=True`인데도 불러와 파싱을 시도하면 0자리 청크가 생성되거나 인덱스 노이즈가 생긴다.

### 수정 내용

#### A-1. `scripts/ingest.py` — `select_sources()` 수정

```python
# 변경 전
def select_sources(cloud_only: bool = False):
    return [source for source in config.PDF_SOURCES if (not cloud_only) or source.cloud_safe]

# 변경 후
def select_sources(cloud_only: bool = False, skip_ocr: bool = True):
    """인제스트 대상 PDF 소스를 선택한다.

    Args:
        cloud_only: True이면 cloud_safe=True인 소스만 선택.
        skip_ocr: True이면 requires_ocr=True인 소스를 제외 (기본값). OCR 파이프라인
                  구축 전까지 스캔본을 실수로 인덱싱하는 것을 방지한다.
    """
    sources = config.PDF_SOURCES
    if cloud_only:
        sources = [s for s in sources if s.cloud_safe]
    if skip_ocr:
        skipped = [s.doc_short for s in sources if s.requires_ocr]
        if skipped:
            print(f"[ingest] requires_ocr 소스 건너뜀 (OCR 파이프라인 미구축): {skipped}")
        sources = [s for s in sources if not s.requires_ocr]
    return sources
```

#### A-2. D3·D4 인덱싱 실행

수정 후 아래 명령을 직접 실행해 인덱스를 재생성한다:

```bash
cd ~/Documents/Claude/Projects/보험\ 문서\ RAG\ 챗봇
python scripts/ingest.py            # 전체 재인덱싱 (D1+D2+D3+D4, D5 건너뜀, D6·D7 건너뜀)
```

예상 산출:
- 총 청크: 약 3,800~4,200개 (D3 ~770청크, D4 ~420청크 추가)
- `data/processed/chunks.jsonl` 갱신
- `data/index/chroma/` 갱신
- `data/index/bm25.pkl` 갱신

인덱싱 완료 후 확인:

```bash
python -c "
import json
from pathlib import Path
shorts = {}
for line in open('data/processed/chunks.jsonl'):
    ds = json.loads(line)['metadata'].get('doc_short','?')
    shorts[ds] = shorts.get(ds, 0) + 1
print('총 청크:', sum(shorts.values()))
for k, v in sorted(shorts.items()):
    print(f'  {k}: {v}')
"
# 출력 예시:
#   심평원: 2286
#   약관: 384
#   자사_SOL건강: 770  ← 신규
#   자사_SOL운전자: 420  ← 신규
```

#### A-3. `tests/test_ingest.py` 또는 `tests/test_pipeline.py` 에 단위 테스트 추가

```python
def test_select_sources_excludes_requires_ocr() -> None:
    """skip_ocr=True (기본값)일 때 requires_ocr=True 소스가 제외된다."""
    from scripts.ingest import select_sources

    sources = select_sources(skip_ocr=True)
    assert all(not s.requires_ocr for s in sources)

def test_select_sources_includes_all_when_skip_ocr_false() -> None:
    """skip_ocr=False이면 requires_ocr 소스도 포함된다."""
    from scripts.ingest import select_sources

    all_sources = select_sources(skip_ocr=False)
    ocr_sources = select_sources(skip_ocr=True)
    assert len(all_sources) >= len(ocr_sources)
```

### 수용 기준

- `data/processed/chunks.jsonl`에 `자사_SOL건강`, `자사_SOL운전자` doc_short가 존재.
- `python -c "from scripts.ingest import select_sources; print([s.doc_short for s in select_sources()])"` 출력에 `실무가이드`, `상담사례집` 미포함.
- 기존 pytest 전체 통과 + 신규 테스트 GREEN.

---

## M-DB-2b: 사이드바 — 인덱싱된 문서만 표시

### 배경

현재 사이드바는 `DOC_SHORT_ORDER = [source.doc_short for source in PDF_SOURCES]` 기반이라 **인덱싱되지 않은 D6·D7도 체크박스로 나타난다**. 사용자가 "실무가이드"를 선택하면 검색 결과가 0건이 된다.

### 수정 내용

#### B-1. `src/config.py` — `INDEXED_PDF_SOURCES` 상수 추가

```python
# config.py 하단에 추가 (DOC_SHORT_ORDER 바로 아래)

# 실제 인덱싱된 소스 — requires_ocr=True이거나 파일이 없는 소스 제외
INDEXED_PDF_SOURCES: list[PdfSource] = [
    source for source in PDF_SOURCES
    if not source.requires_ocr and source.path.exists()
]

# 인덱싱된 문서의 표시 순서 (기존 DOC_SHORT_ORDER 대체 용도)
INDEXED_DOC_SHORT_ORDER: list[str] = [s.doc_short for s in INDEXED_PDF_SOURCES]
```

> **주의:** `DOC_SHORT_ORDER`는 그대로 유지한다. 기존 코드의 호환성을 위해 삭제하지 않는다.

#### B-2. `src/ui/streamlit_app.py` — 사이드바 문서 체크박스 교체

```python
# 변경 전
for doc_short in config.DOC_SHORT_ORDER:
    if st.checkbox(doc_short, value=True, key=f"doc_filter_{doc_short}"):
        selected_docs.append(doc_short)

# 변경 후
for doc_short in config.INDEXED_DOC_SHORT_ORDER:
    if st.checkbox(doc_short, value=True, key=f"doc_filter_{doc_short}"):
        selected_docs.append(doc_short)
```

### 수용 기준

- 사이드바에 "실무가이드", "상담사례집" 체크박스가 나타나지 않는다.
- "자사_SOL건강", "자사_SOL운전자" 체크박스가 나타난다 (M-DB-2a 완료 후).
- D3·D4 선택 후 관련 질의 시 검색 결과가 반환된다.

---

## M-DB-2c: 사이드바 자사/타사 토글 + 상품 유형 필터

### 배경

D3·D4 인덱싱 후 "자사 약관만 보기", "건강보험만 보기" 등의 필터가 필요하다.  
현재 구조는 체크박스 개별 선택뿐이라 문서가 늘어날수록 UX가 나빠진다.

현재 인덱싱 대상 소스별 메타:

| doc_short | insurance_company | is_own_company | product_type |
|-----------|-------------------|---------------|--------------|
| 심평원 | None | None | None |
| 약관 | 신한EZ | True | 실손 |
| 자사_SOL건강 | 신한EZ | True | 건강 |
| 자사_SOL운전자 | 신한EZ | True | 운전자 |
| 가이드북 | None | None | None |

### 구현 헬퍼 추가

`src/ui/streamlit_app.py` 또는 별도 헬퍼 파일에 아래 함수를 추가한다:

```python
def _get_doc_filter_from_meta(
    own_company: str,      # "전체" | "자사" | "타사"
    product_type: str,     # "전체" | "실손" | "건강" | "운전자" | ...
    selected_docs: list[str],  # 개별 체크박스 선택 결과
) -> list[str] | None:
    """자사/타사 토글과 상품 유형 필터를 반영해 doc_filter 목록을 생성한다.

    개별 체크박스 선택보다 상위 필터가 우선한다.
    """
    candidates = list(config.INDEXED_PDF_SOURCES)

    if own_company == "자사":
        candidates = [s for s in candidates if s.is_own_company is True]
    elif own_company == "타사":
        candidates = [s for s in candidates if s.is_own_company is False]

    if product_type != "전체":
        candidates = [s for s in candidates if s.product_type == product_type]

    # 상위 필터 결과와 개별 체크박스 교집합
    candidate_shorts = {s.doc_short for s in candidates}
    filtered = [d for d in selected_docs if d in candidate_shorts]

    return filtered if filtered else None  # None = 필터 없음 (전체 검색)
```

### 사이드바 UI 변경

기존 문서 체크박스 섹션 **위에** 아래 블록을 추가한다:

```python
# ─── 문서 필터 — 상위 토글 ───────────────────────────────────────────
st.sidebar.markdown("#### 📂 문서 필터")

own_company_filter = st.sidebar.radio(
    "보험사 구분",
    options=["전체", "자사", "타사"],
    horizontal=True,
    key="own_company_filter",
)

# 상품 유형 동적 생성 (인덱싱된 소스 기반)
available_product_types = sorted(set(
    s.product_type for s in config.INDEXED_PDF_SOURCES
    if s.product_type is not None
))
product_type_filter = st.sidebar.selectbox(
    "상품 유형",
    options=["전체"] + available_product_types,
    key="product_type_filter",
)

st.sidebar.markdown("---")
st.sidebar.markdown("**문서 개별 선택**")
# 기존 체크박스 (INDEXED_DOC_SHORT_ORDER 기반)
selected_docs = []
for doc_short in config.INDEXED_DOC_SHORT_ORDER:
    if st.sidebar.checkbox(doc_short, value=True, key=f"doc_filter_{doc_short}"):
        selected_docs.append(doc_short)
```

### 파이프라인 호출 수정

`main()` 함수에서 `doc_filter`를 결정할 때 `_get_doc_filter_from_meta()`를 호출한다:

```python
# 변경 전 (예: 일반 질의 핸들러)
doc_filter = selected_docs if selected_docs else None

# 변경 후
doc_filter = _get_doc_filter_from_meta(
    own_company=st.session_state.get("own_company_filter", "전체"),
    product_type=st.session_state.get("product_type_filter", "전체"),
    selected_docs=selected_docs,
)
```

> **주의:** `doc_filter`가 `None`이면 전체 문서 검색. `[]`(빈 리스트)가 되면 검색 결과 0건이므로, `_get_doc_filter_from_meta()`에서 반드시 빈 리스트 대신 `None`을 반환하도록 한다.

### 단위 테스트 추가

`tests/test_streamlit_app.py`에 추가:

```python
def test_get_doc_filter_from_meta_own_company() -> None:
    """자사 필터가 자사 약관만 반환한다."""
    from src.ui.streamlit_app import _get_doc_filter_from_meta

    selected = ["심평원", "약관", "자사_SOL건강", "자사_SOL운전자"]
    result = _get_doc_filter_from_meta("자사", "전체", selected)
    # 약관·자사_SOL건강·자사_SOL운전자만 포함 (심평원은 is_own_company=None)
    assert "심평원" not in (result or [])
    assert "약관" in (result or [])


def test_get_doc_filter_from_meta_product_type() -> None:
    """상품 유형 필터 적용 시 해당 유형만 반환한다."""
    from src.ui.streamlit_app import _get_doc_filter_from_meta

    selected = ["약관", "자사_SOL건강", "자사_SOL운전자"]
    result = _get_doc_filter_from_meta("전체", "건강", selected)
    assert result == ["자사_SOL건강"]


def test_get_doc_filter_returns_none_when_empty_after_filter() -> None:
    """필터 결과가 비면 None을 반환해 전체 검색으로 폴백한다."""
    from src.ui.streamlit_app import _get_doc_filter_from_meta

    result = _get_doc_filter_from_meta("타사", "전체", ["약관", "자사_SOL건강"])
    # 자사 약관만 있으므로 타사 필터 → 빈 결과 → None
    assert result is None
```

### 수용 기준

- "자사" 토글 선택 후 "SOL건강 보험료가 얼마인가요?" 질의 → 자사 약관 청크만 출처에 표시.
- "건강" 상품 유형 선택 → "자사_SOL건강" 청크만 검색 대상이 됨.
- "전체" 선택 시 모든 인덱싱된 문서 대상 검색.
- 필터 조합이 0건 결과를 만들지 않음 (빈 리스트 → None 폴백 보장).

---

## 통합 수용 기준 (전체 M-DB-2)

```bash
# 1. 전체 회귀 테스트
pytest -q --ignore=tests/test_vector_store.py
# 결과: 기존 125 + 신규 테스트 모두 GREEN

# 2. 인덱스 구성 확인
python -c "
import json
from pathlib import Path
shorts = {}
for line in open('data/processed/chunks.jsonl'):
    ds = json.loads(line)['metadata'].get('doc_short','?')
    shorts[ds] = shorts.get(ds, 0) + 1
print('문서별 청크 수:')
for k, v in sorted(shorts.items()):
    print(f'  {k}: {v}')
assert '자사_SOL건강' in shorts, 'D3 미인덱싱!'
assert '자사_SOL운전자' in shorts, 'D4 미인덱싱!'
assert '실무가이드' not in shorts, 'D6가 잘못 인덱싱됨!'
assert '상담사례집' not in shorts, 'D7이 잘못 인덱싱됨!'
print('인덱스 구성 정상')
"

# 3. OCR 소스 제외 확인
python -c "
from scripts.ingest import select_sources
shorts = [s.doc_short for s in select_sources()]
assert '실무가이드' not in shorts
assert '상담사례집' not in shorts
print('OCR 소스 제외:', [s for s in ['실무가이드','상담사례집'] if s not in shorts])
"

# 4. D3 내용 검색 가능 여부 (실제 임베더 없이 chunks.jsonl로 확인)
python -c "
import json
found = any(
    '자동갱신' in json.loads(line)['text']
    for line in open('data/processed/chunks.jsonl')
)
print('D3 내용 검색 가능:', found)
"

# 5. Streamlit 부팅 확인
streamlit run src/ui/streamlit_app.py --server.headless true --server.port 8501 &
sleep 8; curl -s http://localhost:8501 | head -3; kill %1
```

---

## 커밋 메시지

```
feat: index D3/D4 policies and add company/product sidebar filters (M-DB-2)

- Skip requires_ocr sources in ingest.py (D6/D7 excluded)
- Re-index: D1+D2+D3+D4 (~3,860 chunks, up from 2,670)
- Add INDEXED_PDF_SOURCES / INDEXED_DOC_SHORT_ORDER to config
- Sidebar shows only indexed docs (D6/D7 removed from checkboxes)
- Add is_own_company radio toggle (전체/자사/타사)
- Add product_type selectbox (전체/건강/실손/운전자)
- Add _get_doc_filter_from_meta() helper with fallback to None
- Tests: test_select_sources_excludes_requires_ocr, test_get_doc_filter_*
```

---

## ⚠️ 이 단계 이후 남은 결정 사항 (사용자 확인 필요)

아래 항목은 명세 작성 전 결정이 필요합니다:

| # | 항목 | 결정 내용 |
|---|------|----------|
| 1 | **D5 보상가이드북** | 원본 파일을 프로젝트 루트에 복구할 수 있나요? 있다면 다음 단계에서 인덱싱합니다. |
| 2 | **D6 cloud_safe 정책** | `Claim 실무종합가이드.pdf`는 사내 자료입니까? Streamlit Cloud에 인덱스 업로드 가능한가요? |
| 3 | **D7 출처** | `소비자 상담 주요 사례집.pdf`의 출처가 외부 공시(금감원/손보협회)인지 확인해주세요. |
| 4 | **OCR 도구** | 로드맵에서 PaddleOCR(무료·권장)을 1차로 제안했습니다. 이대로 진행할까요, 아니면 Upstage Document Parse(유료, 정확도 우선)를 검토하시겠습니까? |

결정이 오면 Stage 2b (OCR 파이프라인, M-DB-3) 명세를 작성합니다.

---

*다음 명세: Stage 2b OCR 파이프라인 착수 시 `29_CODEX_SPEC_BETA_OCR.md` 작성 예정.*
