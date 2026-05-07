# Codex 명세 — 사이드바 차단 버그 수정 및 다음 단계 구현

작성일: 2026-05-07
작성자: 기획·검토 에이전트
대상: Codex (개발 에이전트)

---

## 배경

베타 Stage 2(M-DB-2) 구현 후 Streamlit Cloud 앱에서 다음 증상이 확인됐다.

- 사이드바 "문서 개별 선택" 섹션에 체크박스가 전혀 표시되지 않음
- "상품 유형" 셀렉트박스가 "전체" 하나만 표시됨
- "최소 1개 문서를 선택해주세요." 경고가 뜨며 질문 채팅이 완전히 차단됨

### 근본 원인

`src/config.py` 121~124행:

```python
INDEXED_PDF_SOURCES: list[PdfSource] = [
    source for source in PDF_SOURCES if not source.requires_ocr and source.path.exists()
]
INDEXED_DOC_SHORT_ORDER: list[str] = [source.doc_short for source in INDEXED_PDF_SOURCES]
```

Streamlit Cloud 환경에서 PDF 원본은 `.gitignore`로 추적 제외돼 존재하지 않는다.
`source.path.exists()`가 모든 소스에 대해 `False`를 반환 → 두 상수가 빈 리스트가 된다.

`src/ui/streamlit_app.py` 에서:
- 973행: `for doc_short in config.INDEXED_DOC_SHORT_ORDER` → 루프가 한 번도 실행되지 않아 체크박스 0개
- 981행: `if not selected_docs: st.warning("최소 1개 문서를 선택해주세요.")`
- 1040행: `if not selected_docs: st.info(...); return` → 채팅 진입 차단

### 기획 결정 사항

> "문서나 데이터셋 필터링은 지금 당장은 필요하지 않으니 **항상 전체 데이터를 조회**하도록 한다."

따라서 이번 수정의 방향은 다음과 같다.

1. `INDEXED_PDF_SOURCES`의 `path.exists()` 조건을 제거하고 `cloud_safe`로 대체
2. 문서 개별 선택 체크박스 UI와 보험사/상품 유형 상위 필터를 사이드바에서 완전 제거
3. 검색 파이프라인에는 항상 `doc_filter=None`을 전달 (전체 인덱스 조회)
4. 관련 차단 검증 코드 삭제

---

## 구현 태스크

### M-fix-1 — `config.py`: `INDEXED_PDF_SOURCES` 조건 수정

**파일:** `src/config.py`

**변경 전:**
```python
INDEXED_PDF_SOURCES: list[PdfSource] = [
    source for source in PDF_SOURCES if not source.requires_ocr and source.path.exists()
]
INDEXED_DOC_SHORT_ORDER: list[str] = [source.doc_short for source in INDEXED_PDF_SOURCES]
```

**변경 후:**
```python
INDEXED_PDF_SOURCES: list[PdfSource] = [
    source for source in PDF_SOURCES if not source.requires_ocr and source.cloud_safe
]
INDEXED_DOC_SHORT_ORDER: list[str] = [source.doc_short for source in INDEXED_PDF_SOURCES]
```

**이유:**
클라우드 배포에서 PDF 파일은 존재하지 않지만 인덱스 자산(Chroma, BM25)은 Git에 포함돼 있다.
`cloud_safe=True`가 "이 문서는 인덱싱이 완료됐고 클라우드에서 조회 가능하다"는 올바른 신호다.
이 변경 후 `INDEXED_PDF_SOURCES`는 `[심평원, 약관, 자사_SOL건강, 자사_SOL운전자]` 4개를 담게 된다
(가이드북: `cloud_safe=False`, 실무가이드: `requires_ocr=True` + `cloud_safe=False`, 상담사례집: `requires_ocr=True`).

---

### M-fix-2 — `streamlit_app.py`: 문서 필터 UI 제거 및 doc_filter 고정

**파일:** `src/ui/streamlit_app.py`

#### 2-A. 사이드바 필터 섹션 전체 제거

아래 블록(약 954~983행, 정확한 행은 코드 참조)을 삭제한다:

```python
st.divider()
st.markdown("#### 문서 필터")
own_company_filter = st.radio(
    "보험사 구분",
    ["전체", "자사", "타사"],
    horizontal=True,
    key="own_company_filter",
)
available_product_types = sorted(
    {source.product_type for source in config.INDEXED_PDF_SOURCES if source.product_type}
)
product_type_filter = st.selectbox(
    "상품 유형",
    ["전체"] + available_product_types,
    key="product_type_filter",
)
st.markdown("---")
st.markdown("**문서 개별 선택**")
selected_docs = []
for doc_short in config.INDEXED_DOC_SHORT_ORDER:
    if st.checkbox(doc_short, value=True, key=f"doc_filter_{doc_short}"):
        selected_docs.append(doc_short)
effective_doc_filter = _get_doc_filter_from_meta(
    own_company_filter,
    product_type_filter,
    selected_docs,
)
if not selected_docs:
    st.warning("최소 1개 문서를 선택해주세요.")
```

삭제 후, 이 자리에 단순 안내 문구만 표시한다:

```python
st.divider()
st.markdown("#### 검색 범위")
st.caption("현재 전체 문서를 검색합니다.")
```

#### 2-B. 차단 분기 제거

아래 두 블록을 삭제한다.

**블록 1 (약 1040~1042행):**
```python
if not selected_docs:
    st.info("검색 대상 문서를 1개 이상 선택하면 질문할 수 있습니다.")
    return
```

**블록 2:** `selected_docs` 변수 선언 자체(위 2-A에서 이미 제거됨)와 관련된 모든 참조를 정리한다.

#### 2-C. `doc_filter` 고정

사이드바 섹션 제거로 `selected_docs`, `effective_doc_filter` 변수가 없어진다.
이 변수들이 사용되던 세 곳을 아래와 같이 교체한다.

| 위치 | 변경 전 | 변경 후 |
|------|---------|---------|
| 일반 질의 `_stream_answer` 호출 | `doc_filter=effective_doc_filter` | `doc_filter=None` |
| 퀵 코드 검색 `_handle_quick_code` 호출 | `effective_doc_filter or selected_docs` | `None` |
| 약관 정형 검색 `_handle_insurance_form` 호출 | `effective_doc_filter or selected_docs` | `None` |

로그 기록 용도(`selected_docs` 인자)는 빈 리스트 `[]` 또는 `None`으로 대체해도 무방하다.

#### 2-D. `_get_doc_filter_from_meta` 함수 제거

`src/ui/streamlit_app.py`의 `_get_doc_filter_from_meta()` 함수 정의 전체(약 504~522행)를 삭제한다.
이 함수를 import하거나 사용하는 코드가 없으면 삭제로 충분하다.

---

### M-fix-3 — 로그 `selected_docs` 필드 처리

`_build_query_log()` 및 `_build_answer_log_details()` 는 `selected_docs: list[str]` 인자를 받는다.
이 인자를 제거하지 않고 호출 시 빈 리스트 `[]`를 전달하도록 유지한다 (로그 스키마 호환).
필요하다면 `INDEXED_DOC_SHORT_ORDER`를 기본값으로 넘겨도 된다.

---

### M-fix-4 — 테스트 정비

`tests/test_streamlit_app.py`에서 `_get_doc_filter_from_meta`를 직접 테스트하는 케이스가 있다면 삭제한다.
`selected_docs`에 의존하는 기존 테스트는 `doc_filter=None`으로 대체해 수정한다.
이후 `pytest -q --ignore=tests/test_vector_store.py`가 전체 통과해야 한다.

---

## 검증 체크리스트

Codex는 구현 완료 후 아래 항목을 직접 확인하고 리포트에 기재할 것.

- [ ] `config.INDEXED_PDF_SOURCES`가 `[심평원, 약관, 자사_SOL건강, 자사_SOL운전자]` 4개인지 Python 셸에서 확인
- [ ] `config.INDEXED_PDF_SOURCES`가 PDF 파일 부재 시에도 빈 리스트가 아닌지 확인
  (테스트: `PdfSource.path`를 존재하지 않는 경로로 mock 후 리스트 길이 검증)
- [ ] Streamlit 앱 로컬 실행 후 사이드바에 체크박스·필터 없이 깔끔하게 표시되는지 확인
- [ ] 질문을 입력해 답변이 정상 반환되는지 확인 (doc_filter=None 경로)
- [ ] `pytest -q --ignore=tests/test_vector_store.py` 전체 통과
- [ ] Git diff에 PDF/XLSX/SQLite 바이너리가 포함되지 않는지 확인

---

## 다음 단계 계획 (M-next)

### 현황 요약

| 문서 | 인덱스 상태 | 클라우드 배포 |
|------|------------|------------|
| 심평원 (D1) | ✅ 2,286 청크 | ✅ |
| 약관 (D2) | ✅ 384 청크 | ✅ |
| 자사_SOL건강 (D3) | ✅ 1,494 청크 (로컬 인덱스) | ⚠️ 미확인 — 커밋 b730b4a 포함 여부 확인 필요 |
| 자사_SOL운전자 (D4) | ✅ 761 청크 (로컬 인덱스) | ⚠️ 미확인 |
| 가이드북 (D5) | ❌ 원본 미수령 | ❌ |
| 실무가이드 (D6) | ❌ OCR 필요 | ❌ |
| 상담사례집 (D7) | ❌ OCR 필요 | ❌ |
| 비급여표준모델 (D8) | ✅ SQLite 527,679행 | ❌ (cloud_safe=False) |

### M-next-1 — D3/D4 클라우드 인덱스 반영 확인

**확인 작업 (Codex):**

```bash
# 클라우드에 올라간 인덱스 실제 청크 수 확인
python -c "
import json
from pathlib import Path
counts = {}
for line in Path('data/processed/chunks.jsonl').open():
    doc = json.loads(line).get('doc_short', 'unknown')
    counts[doc] = counts.get(doc, 0) + 1
for k, v in sorted(counts.items()):
    print(f'{k}: {v}')
"
```

결과가 `자사_SOL건강: 1494`, `자사_SOL운전자: 761`을 포함하지 않으면:
→ `python scripts/ingest.py` 재실행 후 `data/processed/chunks.jsonl`, `data/index/bm25.pkl`, `data/index/chroma/` 커밋·푸시.

### M-next-2 — 비급여 코드 조회 UI 연결

`src/db/standard_codes.py`의 `search_by_name()` / `lookup_by_std_cd()` 함수가 구현돼 있다.
이를 Streamlit 사이드바 또는 별도 탭에서 사용자가 직접 조회할 수 있는 간단한 검색 UI를 추가한다.

- 입력: 시술명 키워드 또는 코드
- 출력: 코드, 명칭, 분류 표 형태로 표시
- 이 기능은 기존 RAG 파이프라인과 독립적으로 동작한다

### M-next-3 — OCR 파이프라인 설계 (다음 명세 별도 작성 예정)

D6 (실무가이드), D7 (상담사례집) 인덱싱을 위해:

- `scripts/ocr_ingest.py` 스크립트 신설
- `pytesseract` 또는 `paddleocr` 기반 텍스트 추출
- 추출 결과를 기존 `chunk_pages()` 파이프라인에 주입
- 완료 후 `INDEXED_PDF_SOURCES`에 자동 반영

> **이 태스크는 다음 명세(doc 31)에서 별도로 다룬다. 이번 Codex 구현 범위에서 제외한다.**

---

## 구현 우선순위 및 범위

이번 Codex 구현 범위:

1. **M-fix-1** (필수): `config.py` INDEXED_PDF_SOURCES 조건 수정
2. **M-fix-2** (필수): `streamlit_app.py` 필터 UI 제거 + doc_filter=None 고정
3. **M-fix-3** (필수): 로그 인자 정리
4. **M-fix-4** (필수): 테스트 정비
5. **M-next-1** (권장): D3/D4 클라우드 인덱스 반영 확인 및 필요 시 재인제스트

M-next-2, M-next-3은 이번 범위 밖이다.

구현 완료 후 `docs/31_SIDEBAR_FIX_REPORT.md`에 결과 리포트를 작성할 것.
