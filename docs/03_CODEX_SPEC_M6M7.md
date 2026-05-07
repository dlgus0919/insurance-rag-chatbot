# Codex 개발자 명세서 — M6·M7: 멀티 문서 RAG 확장

> **이 문서는 Codex 에이전트(개발자)가 받아 구현하는 명세입니다.**
> 기획·검토는 별도 에이전트가 담당하며, 본 명세를 임의로 변경하지 마세요.
> 결정 변경이 필요한 사안이 발생하면 변경 사유와 옵션을 PR 설명에 명시하고 검토자에게 알리세요.

---

## 0. Codex에게 전달할 프롬프트 (이 섹션을 그대로 Codex에 붙여넣으세요)

```
당신은 시니어 Python 개발자입니다. 이미 Alpha M1-M5가 완료된 "보험 문서 RAG 챗봇" 프로젝트에 멀티 문서 RAG 지원을 추가합니다. 아래 명세(docs/03_CODEX_SPEC_M6M7.md)에 따라 M6과 M7을 순서대로 구현하세요.

원칙:
1. 기존 M1-M5 코드의 동작을 절대 깨뜨리지 마세요. 심평원 단독 인덱싱/검색이 여전히 동작해야 합니다.
2. M6 → M7 순서대로 작업하고, 각 마일스톤마다 커밋·요약을 남기세요.
3. 기존 smoke_qa.jsonl(10문항)의 내용을 수정하거나 삭제하지 마세요. 필드 추가와 신규 항목 추가만 허용합니다.
4. 테스트는 PDF 없이 동작해야 하며, 외부 모델 다운로드가 발생하면 안 됩니다.
5. 약관 PDF 경로: 프로젝트 루트의 `2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf` (이미 존재).
6. 보상가이드북은 아직 없으므로 코드에서 존재 여부를 확인 후 건너뛰는 로직을 구현하세요.
7. 코드 주석과 docstring은 한국어 우선.

먼저 이 명세 전체를 읽고, docs/qa_reference.md도 참고한 후 M6부터 순차적으로 진행하세요.
각 마일스톤 완료 시 명세 6장 "마일스톤별 완료 기준"을 자가 검증한 결과를 함께 보고하세요.
```

---

## 1. 배경 및 범위

### 현황 (Alpha M1-M5 완료 상태)
- **단일 PDF 지원**: 심평원 고시 1,429페이지(`BZ202603053039374.pdf`)
- **M1 결과**: 2,402 chunks, 평균 555.7자, 코드 포함 71.3%
- **M2 상태**: BM25 인덱스 생성 완료 / BGE-M3 미캐시로 Dense 인덱싱 미완료
- **M3~M5**: pytest 13개 통과, Ollama 연결 시 CLI/UI 동작 확인

### 이번 작업 범위 (M6-M7)
- **추가 PDF**: 약관 PDF (`2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf`, 172페이지)
- **예약 PDF**: 보상가이드북 (미입수 — 파일 존재 시 자동 포함, 없으면 건너뜀)
- **변경 범위**: config, chunker, ingest, prompt, eval/smoke_qa.jsonl
- **비변경 범위**: retrieval(hybrid/bm25/vector_store), llm/ollama_client, UI (기존 동작 보존)

---

## 2. M6 — 멀티 문서 인제스천 & 청커 개선

### 2.1 `src/config.py` 변경

`PdfSource` 데이터클래스를 추가하고, `PDF_SOURCES` 목록으로 모든 PDF를 관리한다.
기존 `PDF_PATH` 상수는 **하위 호환을 위해 유지**한다 (= `PDF_SOURCES[0].path`로 별칭).

```python
from dataclasses import dataclass

@dataclass
class PdfSource:
    path: Path
    doc_type: str   # "policy_act" | "insurance_policy" | "guide_book"
    doc_name: str   # 답변 인용 시 표시할 문서 전체 이름
    doc_short: str  # chunk ID 접두사 및 메타데이터 식별자 (예: "심평원", "약관", "가이드북")

PDF_SOURCES: list[PdfSource] = [
    PdfSource(
        path=ROOT_DIR / "BZ202603053039374.pdf",
        doc_type="policy_act",
        doc_name="건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수",
        doc_short="심평원",
    ),
    PdfSource(
        path=ROOT_DIR / "2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf",
        doc_type="insurance_policy",
        doc_name="신한 이지로운 실손의료보험(무배당) 약관",
        doc_short="약관",
    ),
    PdfSource(
        path=ROOT_DIR / "보상가이드북.pdf",   # 파일 없으면 ingest 시 건너뜀
        doc_type="guide_book",
        doc_name="보상가이드북",
        doc_short="가이드북",
    ),
]

# 하위 호환 별칭
PDF_PATH: Path = PDF_SOURCES[0].path
```

### 2.2 `src/parser/chunker.py` 변경

#### 2.2.1 코드 패턴 추가

기존 `CODE_RE`에 **ICD-10 진단코드 패턴**(소수점 포함)을 추가한다.

```python
# 기존 패턴 (변경 없음)
PROC_CODE_RE = re.compile(r"\b[A-Z]{1,3}\d{2,5}\b|\b\d{5}\b")

# 신규: ICD-10 진단코드 (예: N39.3, Q00~Q04, K60, E66)
ICD10_RE = re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b")

# 통합 (추출 시 두 패턴 모두 적용)
def _extract_codes(text: str) -> list[str]:
    codes = set(PROC_CODE_RE.findall(text))
    codes.update(ICD10_RE.findall(text))
    return sorted(codes)
```

> ⚠️ `PROC_CODE_RE`와 `ICD10_RE`는 일부 중복 매칭(예: N39, K60 등)이 발생할 수 있으나, `set()`으로 중복 제거하므로 문제없다.

#### 2.2.2 문서 유형별 헤더 패턴

`doc_type`에 따라 다른 헤더 패턴을 사용하는 내부 헬퍼를 추가한다.

```python
# 심평원 (policy_act) — 기존과 동일
POLICY_ACT_HEADERS = {
    "volume": re.compile(r"^\s*제\s*\d+\s*편\b.*"),
    "part":   re.compile(r"^\s*제\s*\d+\s*부\b.*"),
    "chapter":re.compile(r"^\s*제\s*\d+\s*장\b.*"),
    "section":re.compile(r"^\s*제\s*\d+\s*절\b.*"),
}

# 약관 (insurance_policy) — 관/조 구조
INSURANCE_HEADERS = {
    "volume": re.compile(r"^\s*제\s*\d+\s*관\b.*"),     # 제1관, 제2관
    "chapter":re.compile(r"^\s*제\s*\d+\s*조\s*[（(（].*[）)）]"),  # 제3조(조문명)
    "section":re.compile(r"^\s*\[?별표\s*\d*\]?\s*\S+"),           # [별표1] 등
}

# 가이드북 (guide_book) — 장/절 구조 사용 (policy_act와 동일 패턴 사용)
GUIDE_BOOK_HEADERS = POLICY_ACT_HEADERS

HEADER_PATTERNS = {
    "policy_act": POLICY_ACT_HEADERS,
    "insurance_policy": INSURANCE_HEADERS,
    "guide_book": GUIDE_BOOK_HEADERS,
}
```

#### 2.2.3 `chunk_pages()` 시그니처 변경

```python
from src.config import PdfSource  # 순환참조 주의 — config에서 dataclass만 import

def chunk_pages(
    pages: list[tuple[int, str]],
    target_chars: int = 800,
    overlap_chars: int = 100,
    doc_source: PdfSource | None = None,   # NEW: 문서 출처 정보
    id_offset: int = 0,                    # NEW: 청크 ID 시작 번호 (문서 간 중복 방지)
) -> list[Chunk]:
    """
    페이지를 순회하며 헤더 컨텍스트를 누적·전파한다.
    doc_source가 주어지면 해당 doc_type에 맞는 헤더 패턴을 사용하고
    chunk metadata에 doc_short, doc_name, doc_type을 포함한다.
    """
```

#### 2.2.4 Chunk metadata 스키마 변경

```json
{
  "id": "약관_ch_000001",
  "text": "...",
  "metadata": {
    "doc_short": "약관",
    "doc_name": "신한 이지로운 실손의료보험(무배당) 약관",
    "doc_type": "insurance_policy",
    "page_start": 38,
    "page_end": 38,
    "volume": "제1관 ...",
    "part": null,
    "chapter": "제3조(보장종목별 보상내용)",
    "section": null,
    "codes": ["N39.3", "N39.4", "R32"],
    "char_count": 612
  }
}
```

**ID 규칙:** `{doc_short}_ch_{번호:06d}` — 번호는 문서 내 순번(0부터), `id_offset`으로 전역 중복 방지.

**기존 심평원 청크 ID 호환:** 심평원은 `doc_short="심평원"` 이므로 `심평원_ch_000000` 형태로 변경됨.
이미 생성된 `chunks.jsonl`은 `--stage all` 재실행 시 덮어쓰므로 마이그레이션 불필요.

#### 2.2.5 backward-compatible 기본값

기존 코드에서 `doc_source=None`으로 호출하면 `policy_act` 패턴과 ID 형식 `ch_{번호:06d}`(기존 형식)를 유지한다. 이렇게 하면 기존 테스트가 수정 없이 통과한다.

### 2.3 `scripts/ingest.py` 변경

```python
def build_chunks() -> None:
    """PDF_SOURCES를 순회하며 모든 청크를 하나의 chunks.jsonl에 통합한다."""
    all_chunks = []
    id_offset = 0

    for source in config.PDF_SOURCES:
        if not source.path.exists():
            print(f"[M6] 파일 없음, 건너뜀: {source.path.name}")
            continue

        print(f"[M6] PDF 파싱: {source.doc_short} ({source.path.name})")
        pages = parse_pdf(source.path)
        chunks = chunk_pages(
            pages,
            target_chars=config.CHUNK_TARGET_CHARS,
            overlap_chars=config.CHUNK_OVERLAP_CHARS,
            doc_source=source,
            id_offset=id_offset,
        )
        all_chunks.extend(chunks)
        id_offset += len(chunks)
        print(f"[M6] {source.doc_short}: {len(chunks):,} 청크")

    save_chunks(all_chunks, config.CHUNKS_PATH)
    # 통계 로그: 문서별 청크 수, 전체 청크 수, 평균 길이, 코드 추출 비율
```

`build_index()` 함수는 변경 없음 — chunks.jsonl을 읽어 인덱싱하므로 자동으로 멀티 문서를 처리한다.

### 2.4 테스트 (`tests/test_chunker.py` 추가)

기존 테스트를 유지하면서 다음 케이스를 추가한다:

```python
def test_insurance_policy_headers():
    """약관 헤더 패턴이 제N조(...) 형식을 올바르게 인식한다."""
    sample = [
        (37, "제3조(보장종목별 보상내용)\n① 회사는 이 약관..."),
        (38, "5. 요실금(N39.3, N39.4, R32)\n다음 사유는 보상하지 않습니다"),
    ]
    from src.config import PdfSource
    from pathlib import Path
    dummy_source = PdfSource(path=Path("dummy.pdf"), doc_type="insurance_policy",
                              doc_name="테스트 약관", doc_short="테스트약관")
    chunks = chunk_pages(sample, doc_source=dummy_source)
    assert any(c.metadata.get("chapter", "").startswith("제3조") for c in chunks)

def test_icd10_code_extraction():
    """ICD-10 코드(소수점 포함)가 metadata.codes에 추출된다."""
    sample = [(1, "요실금(N39.3, N39.4, R32)은 보상하지 않습니다.")]
    from src.config import PdfSource
    from pathlib import Path
    dummy_source = PdfSource(path=Path("dummy.pdf"), doc_type="insurance_policy",
                              doc_name="테스트", doc_short="테스트")
    chunks = chunk_pages(sample, doc_source=dummy_source)
    codes = chunks[0].metadata["codes"]
    assert "N39.3" in codes

def test_chunk_id_includes_doc_short():
    """멀티 문서 청크 ID에 doc_short가 포함된다."""
    sample = [(1, "테스트 내용입니다.")]
    from src.config import PdfSource
    from pathlib import Path
    dummy_source = PdfSource(path=Path("dummy.pdf"), doc_type="insurance_policy",
                              doc_name="테스트", doc_short="약관")
    chunks = chunk_pages(sample, doc_source=dummy_source)
    assert chunks[0].id.startswith("약관_")

def test_missing_pdf_skipped(tmp_path):
    """존재하지 않는 PDF는 ingest 시 건너뛰고 에러를 발생시키지 않는다."""
    # ingest.py의 build_chunks()에서 source.path.exists() 체크 로직 단위 검증
    from src.config import PdfSource
    missing = PdfSource(path=tmp_path / "없는파일.pdf", doc_type="guide_book",
                         doc_name="없음", doc_short="가이드북")
    assert not missing.path.exists()  # 파일이 없음을 확인
```

### 2.5 M6 완료 기준

```
pytest tests/test_chunker.py                          # 기존 + 신규 테스트 모두 통과
python scripts/ingest.py --stage chunks               # 심평원 + 약관 합산 청크 생성
```

통과 조건:
- 전체 테스트 통과
- chunks.jsonl에 `doc_short="심평원"` 청크와 `doc_short="약관"` 청크 모두 존재
- 약관 청크에서 N39.3 코드가 추출된 청크 1개 이상
- 가이드북 파일 없음 시 에러 없이 건너뜀 확인 (로그 메시지 출력)

---

## 3. M7 — 프롬프트 개선 & Q&A 데이터셋 확장

### 3.1 `src/llm/prompt.py` 변경

#### 3.1.1 SYSTEM_PROMPT 업데이트

멀티 문서를 명시하고 인용 형식을 문서명 포함으로 변경한다.
**3B 모델 친화 원칙 유지**: 규칙은 5개 이내, 예시 없음.

```python
SYSTEM_PROMPT = """당신은 보험사 직원의 질문에 답하는 어시스턴트입니다. \
참고 문서에는 건강보험 고시(심평원), 실손의료보험 약관, 보상가이드북 등이 포함될 수 있습니다.
규칙:
1. 반드시 제공된 참고 문맥(컨텍스트) 안의 정보만 사용해 답하세요.
2. 컨텍스트에 답이 없거나 모호하면 "제공된 문서에서 확인되지 않습니다."라고 답하세요.
3. 추측하거나 외부 지식을 사용하지 마세요.
4. 답변 마지막에 사용한 출처를 [출처: 문서명, 조문/절, p.페이지] 형식으로 나열하세요.
5. 한국어로 간결하고 정확하게 답하세요."""
```

#### 3.1.2 `_context_label()` 함수 변경

```python
def _context_label(metadata: dict) -> str:
    doc_name = metadata.get("doc_name") or metadata.get("doc_short", "")
    parts = [
        doc_name,
        metadata.get("volume"),
        metadata.get("part"),
        metadata.get("chapter"),
        metadata.get("section"),
        _page_label(metadata),
    ]
    return " / ".join(str(p) for p in parts if p)
```

기존 청크(doc_name 없음)도 처리되어야 하므로 `.get("doc_name")` fallback 처리.

### 3.2 `eval/smoke_qa.jsonl` 확장

#### 3.2.1 기존 10개 항목에 `doc_sources` 필드 추가

기존 항목을 변경하되, question/expected_pages/expected_codes/type 필드는 수정하지 않는다.
기존 항목 전체에 `"doc_sources": ["심평원"]` 필드를 추가한다.

#### 3.2.2 신규 5개 항목 추가

다음 5개를 기존 10개 뒤에 추가한다:

**항목 11 (약관, code):**
```json
{
  "question": "N39.3 진단이 실손의료비 약관에서 보상가능한지 알려줘.",
  "expected_pages": [38, 80, 82],
  "expected_codes": ["N39.3"],
  "doc_sources": ["약관"],
  "type": "code"
}
```
> ※ expected_pages는 PDF 파일 1-based 인덱스. 실제 Q2333 위치는 Codex가 ingest 결과로 확인 후 기재할 것.

**항목 12 (심평원, code):**
```json
{
  "question": "식도조루술의 코드를 알려줘.",
  "expected_pages": [],
  "expected_codes": ["Q2333"],
  "doc_sources": ["심평원"],
  "type": "code",
  "note": "expected_pages는 Codex가 실제 PDF에서 Q2333 위치를 확인 후 채울 것"
}
```

**항목 13 (심평원+가이드북, cross_doc):**
```json
{
  "question": "식도조루술의 수술코드, 수술해설과 1-5종 해당여부를 알려줘.",
  "expected_pages": [],
  "expected_codes": ["Q2333"],
  "doc_sources": ["심평원", "가이드북"],
  "type": "cross_doc",
  "note": "가이드북 미인덱싱 시 종별 정보 없는 부분 답변 허용. 가이드북 추가 후 expected_pages 업데이트 필요."
}
```

**항목 14 (약관, semantic):**
```json
{
  "question": "실손의료보험 약관에서 3대비급여에 해당하는 항목은 무엇인가요?",
  "expected_pages": [],
  "expected_codes": [],
  "doc_sources": ["약관"],
  "type": "semantic",
  "note": "Codex가 약관 PDF에서 3대비급여 정의 위치(페이지 인덱스) 확인 후 expected_pages 채울 것"
}
```

**항목 15 (약관, semantic):**
```json
{
  "question": "본인부담금 상한제로 환급받은 금액이 실손보험에서 보상되나요?",
  "expected_pages": [],
  "expected_codes": [],
  "doc_sources": ["약관"],
  "type": "semantic",
  "note": "Codex가 약관 PDF에서 관련 조문 위치 확인 후 expected_pages 채울 것"
}
```

> **Codex 작업 지시**: 항목 12~15의 `expected_pages`는 비어 있습니다. `scripts/ingest.py --stage chunks` 실행 후 해당 코드/내용이 포함된 청크의 `page_start` 값을 찾아 채우세요. 단, Q2333이 심평원 PDF의 정확히 몇 번째 페이지(1-based 인덱스)에 있는지 확인하는 것이 핵심입니다.

### 3.3 `scripts/eval.py` 변경

`doc_sources` 필드가 있는 항목은 해당 문서의 청크에서만 recall을 계산하도록 필터링 로직 추가.
`doc_sources` 필드가 없는 항목(기존 항목)은 기존과 동일하게 전체 청크 대상.

```python
# eval.py 내 recall 계산 시 필터 적용 예시
def filter_chunks_by_doc(chunks, doc_sources):
    if not doc_sources:
        return chunks
    return [c for c in chunks if c.metadata.get("doc_short") in doc_sources]
```

`cross_doc` 타입은 복수 doc_sources 전체 대상으로 recall 계산.

### 3.4 테스트 (`tests/test_pipeline.py` 확인)

기존 mock 기반 테스트가 여전히 통과하는지 확인. 새로 추가할 것은 없으나, `_context_label()`이 `doc_name` 없는 구 메타데이터도 처리하는지 테스트 fixture를 확인한다:

```python
def test_context_label_backward_compat():
    """doc_name 없는 구 메타데이터(심평원 M1 생성분)도 context label 생성 가능."""
    from src.llm.prompt import _context_label
    old_meta = {"page_start": 101, "page_end": 101, "volume": "제1편", "section": "재진"}
    label = _context_label(old_meta)
    assert "p.101" in label
    # doc_name 없어도 에러 없음
```

### 3.5 M7 완료 기준

```
pytest                                                # 전체 테스트 통과 (기존 13개 이상 유지)
python scripts/ingest.py --stage chunks               # 심평원+약관 청크 통합 확인
```

통과 조건:
- 기존 13개 테스트 포함 전체 통과
- smoke_qa.jsonl에 15개 항목 존재, 기존 10개의 `doc_sources` 필드 추가됨
- 약관 관련 항목(11, 14, 15)의 `expected_pages`가 실제 PDF 인덱스 값으로 채워져 있음
- Q2333 위치 확인 후 항목 12의 `expected_pages` 채워져 있음
- `python scripts/cli.py` 실행 시 약관 청크가 검색 결과에 포함되는 것 확인

---

## 4. 변경 파일 목록 요약

| 파일 | M6 | M7 | 비고 |
|---|---|---|---|
| `src/config.py` | ✅ 변경 | — | PdfSource 추가, PDF_SOURCES 목록 |
| `src/parser/chunker.py` | ✅ 변경 | — | ICD-10 패턴, 약관 헤더, doc_source 파라미터 |
| `scripts/ingest.py` | ✅ 변경 | — | PDF_SOURCES 루프, 파일 없음 건너뜀 |
| `src/llm/prompt.py` | — | ✅ 변경 | 시스템 프롬프트, _context_label |
| `eval/smoke_qa.jsonl` | — | ✅ 변경 | doc_sources 필드 추가, 신규 5개 항목 |
| `scripts/eval.py` | — | ✅ 변경 | doc_sources 기반 필터 |
| `tests/test_chunker.py` | ✅ 변경 | — | 약관 헤더, ICD-10, ID 포맷 테스트 추가 |
| `tests/test_pipeline.py` | — | ✅ 확인 | backward compat 테스트 추가 |
| `src/retrieval/*.py` | ❌ 변경 없음 | ❌ 변경 없음 | 메타데이터 자동 통과 |
| `src/ui/streamlit_app.py` | ❌ 변경 없음 | ❌ 변경 없음 | 향후 출처 필터 UI는 베타 |

---

## 5. 모호성 해소 규칙

1. **약관 헤더 인식 실패율이 높은 경우**: 약관 PDF는 인쇄 레이아웃상 제N조 패턴이 줄 앞에 오지 않을 수 있다. 첫 100페이지에서 패턴 매칭율을 로그로 출력하고, 매칭이 10건 미만이면 PR 설명에 기재하고 검토자에게 알릴 것.
2. **ICD-10 오탐(false positive)**: `[A-Z]\d{2}(?:\.\d{1,2})?` 패턴이 수술코드(예: A00, B01)와 겹칠 수 있다. 중복은 `set()`으로 통합하므로 기능상 문제없다. 중복 제거 후에도 코드가 너무 많이 추출되는 청크(20개 이상)는 경고 로그 출력.
3. **보상가이드북 cross_doc 평가**: 가이드북 미인덱싱 시 항목 13의 recall 계산을 건너뛰고 `"skipped(가이드북 미인덱싱)"` 로그만 남길 것.
4. **청크 ID 충돌**: `doc_source=None` 기존 호출 시 ID는 기존 `ch_{번호:06d}` 유지. `doc_source` 지정 시 `{doc_short}_ch_{번호:06d}` 사용.

---

## 6. 마일스톤별 완료 기준 (자가 검증)

| M | 검증 명령 | 통과 조건 |
|---|---|---|
| M6 | `pytest tests/test_chunker.py && python scripts/ingest.py --stage chunks` | 신규 테스트 포함 통과 / 약관 청크 생성 / N39.3 추출 확인 / 가이드북 건너뜀 로그 |
| M7 | `pytest && python scripts/ingest.py --stage chunks` | 전체 테스트 통과 / smoke_qa.jsonl 15항목 / Q2333 페이지 확인 완료 |

---

## 7. PR 보고서 양식

```
## M{N} 완료 보고
- 변경 파일: ...
- 자가 검증 결과:
  - [테스트]: pytest X개 통과
  - [청크 통계]: 심평원 X청크 / 약관 X청크 / 합계 X청크
  - [약관 N39.3 추출]: 해당 코드 포함 청크 X개
  - [Q2333 페이지]: PDF 인덱스 p.XXX
  - [가이드북]: 파일 없음 → 건너뜀 확인
- 알파 명세 외 추가/생략 사항: ...
- 검토자 확인 필요 항목: ...
```
