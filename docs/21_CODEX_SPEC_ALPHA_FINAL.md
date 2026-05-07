# Codex 구현 명세 — Phase A 알파 종료 보정 (M-α-1 ~ M-α-5)

> **작성:** 기획자 (검토자)
> **작성일:** 2026-05-07
> **기반 커밋:** `34da73a` (master HEAD)
> **참고:** [20_INTEGRATION_ROADMAP.md](./20_INTEGRATION_ROADMAP.md) §2.2, [19_PROJECT_STATUS_SUMMARY.md](./19_PROJECT_STATUS_SUMMARY.md) §7
> **대상:** Codex 개발자 에이전트

---

## 0. 배경 및 목적

M1~M17로 알파 기능이 완성됐다. 베타 진입 전 외부 문서 의존 없이 처리 가능한 보정 5건을 이번 마일스톤(M-α)에서 완결한다. 이후 Phase B(100개 약관 입수 후)와 Phase C(스캔본 입수 후)로 이어진다.

**작업 범위 — 5개 항목, 스캔본·외부 문서 불필요**

| ID | 제목 | 핵심 변경 파일 |
|----|------|----------------|
| M-α-1 | RAG 단계별 디버그 로그 | `src/rag/pipeline.py`, `src/ui/admin_page.py`, `src/ui/streamlit_app.py` |
| M-α-2 | 출처 첨부 로직 개선 | `src/ui/streamlit_app.py` |
| M-α-3 | 교통사고·이륜자동차 검색 쿼리 확장 | `src/rag/pipeline.py` |
| M-α-4 | smoke_qa v2 (약관 정형 모드 10문항) | `eval/smoke_qa_v2.jsonl`, `tests/test_eval.py` |
| M-α-5 | Cloud 로그 노이즈 축소 | `.streamlit/config.toml` (신규 생성), `src/ui/streamlit_app.py` |

**커밋 전략:** 각 M-α-# 별로 독립 커밋. 전체 테스트 (`pytest -q --ignore=tests/test_vector_store.py`) 통과 후 순차 머지.

---

## M-α-1: RAG 단계별 디버그 로그

### 배경

`pipeline.py`의 `retrieve_hits()`는 Dense → BM25 → RRF → Rerank 4단계를 수행하지만 중간 결과가 어디에도 노출되지 않는다. 검색 품질 문제를 진단하려면 단계별 hit·점수를 관리자가 볼 수 있어야 한다.

### 구현 상세

#### 1-A. `src/rag/pipeline.py` — `DebugInfo` 데이터클래스 추가

파일 상단 `@dataclass RagAnswer` 바로 위에 아래 두 클래스를 추가한다.

```python
@dataclass
class StageHit:
    """단일 검색 단계의 hit 정보 (디버그용)."""
    chunk_id: str
    doc_short: str
    score: float
    page_start: int | None
    page_end: int | None
    text_preview: str  # 원문 앞 100자


@dataclass
class DebugInfo:
    """RAG 4단계의 중간 검색 결과 (디버그용)."""
    dense_hits: list[StageHit]
    bm25_hits: list[StageHit]
    rrf_hits: list[StageHit]
    final_hits: list[StageHit]
```

`RagAnswer`에 선택적 필드를 추가한다.

```python
@dataclass
class RagAnswer:
    answer: str
    chunks: list[Chunk]
    timing: dict
    debug: DebugInfo | None = None  # ← 추가
```

#### 1-B. `pipeline.py` — `_hits_to_stage(hits) -> list[StageHit]` 헬퍼 추가

```python
def _hits_to_stage(hits: list[Hit]) -> list[StageHit]:
    return [
        StageHit(
            chunk_id=h.id,
            doc_short=h.metadata.get("doc_short", ""),
            score=round(h.score, 4),
            page_start=h.metadata.get("page_start"),
            page_end=h.metadata.get("page_end"),
            text_preview=h.document[:100],
        )
        for h in hits
    ]
```

#### 1-C. `pipeline.py` — `retrieve_hits()` 시그니처 변경

```python
def retrieve_hits(
    self,
    question: str,
    top_k: int | None = None,
    doc_filter: list[str] | None = None,
    return_debug: bool = False,
) -> tuple[list[Hit], DebugInfo | None]:
```

반환 타입을 **`tuple[list[Hit], DebugInfo | None]`** 로 변경한다.

내부에서 각 단계 직후 hit 목록을 저장하고, `return_debug=True`이면 `DebugInfo`를 생성해 반환한다. `return_debug=False`이면 `(hits, None)` 반환.

단계별 캡처 포인트:

| 변수 이름 | 캡처 시점 |
|-----------|-----------|
| `_debug_dense` | `dense_hits` 확정 직후 (`_is_low_value_wide_range` 필터 전) |
| `_debug_bm25` | `bm25_hits` 확정 직후 (필터 전) |
| `_debug_rrf` | `rrf_fuse()` 호출 직후 |
| `_debug_final` | `reranker.rerank()` 또는 슬라이싱 직후 |

`answer()` 메서드도 동일하게 `return_debug` 파라미터를 받아 `retrieve_hits`에 전달하고, 결과를 `RagAnswer.debug`에 담는다.

> **기존 호출부 호환성**: `retrieve_hits()`의 반환 타입이 바뀌므로, 해당 함수를 호출하는 모든 곳을 일괄 수정해야 한다. `answer()` 내부에서만 사용되므로 공개 API 파괴는 없다. `tests/test_pipeline.py`의 `pipeline.retrieve_hits(...)` 반환값 처리를 `hits, _ = pipeline.retrieve_hits(...)` 형식으로 수정한다.

#### 1-D. `src/ui/admin_page.py` — 디버그 패널 탭 추가

기존 관리자 페이지의 탭 목록(`로그`, `통계`, `사용자`, `시스템`)에 `🔍 검색 진단` 탭을 추가한다.

탭 내부 구현:

```python
st.markdown("### RAG 검색 진단")
st.caption("최근 질의의 단계별 검색 결과를 표시합니다.")

if "last_debug" not in st.session_state or st.session_state.last_debug is None:
    st.info("질의를 먼저 실행하세요.")
else:
    debug: DebugInfo = st.session_state.last_debug
    for stage_name, stage_hits in [
        ("① Dense (BGE-M3)", debug.dense_hits),
        ("② BM25 (키워드)", debug.bm25_hits),
        ("③ RRF 융합", debug.rrf_hits),
        ("④ Rerank 후 최종", debug.final_hits),
    ]:
        with st.expander(f"{stage_name} — {len(stage_hits)}건", expanded=(stage_name.startswith("④"))):
            if stage_hits:
                import pandas as pd
                df = pd.DataFrame([
                    {
                        "chunk_id": h.chunk_id,
                        "문서": h.doc_short,
                        "점수": h.score,
                        "페이지": f"p.{h.page_start}" if h.page_start else "-",
                        "본문 미리보기": h.text_preview,
                    }
                    for h in stage_hits
                ])
                st.dataframe(df, use_container_width=True)
            else:
                st.write("(결과 없음)")
```

#### 1-E. `src/ui/streamlit_app.py` — 디버그 활성화 연동

- 관리자(`role == "admin"`) 사용자의 사이드바에 `st.sidebar.checkbox("🔍 검색 디버그 활성화", key="debug_mode")` 추가.
- 파이프라인 `answer()` 호출 시 `return_debug=st.session_state.get("debug_mode", False)` 전달.
- 답변 후 `st.session_state["last_debug"] = result.debug` 저장.

### 수용 기준

- `pytest tests/test_pipeline.py -q` 전체 통과.
- `DebugInfo`가 None이어도 기존 `answer()` 흐름이 동일하게 동작.
- 관리자 로그인 후 질의 실행 → 검색 진단 탭에서 4단계 결과 확인 가능.
- 비관리자(employee) 사이드바에 디버그 체크박스가 표시되지 않음.

---

## M-α-2: 출처 첨부 로직 개선

### 배경

현재 `streamlit_app.py`는 top-k 청크 전체를 출처로 표시한다. LLM이 실제로 인용한 청크만 출처로 표시하면 사용자 혼란이 줄고 품질 신뢰도가 높아진다.

### 구현 상세

#### 2-A. `src/ui/streamlit_app.py` — `_filter_cited_chunks()` 추가

기존 헬퍼 함수 그룹(예: `_source_title`, `_format_timing` 근처)에 아래 함수를 추가한다.

```python
import re as _re

def _filter_cited_chunks(answer: str, chunks: list) -> list:
    """답변의 [출처: <doc_short>, ...] 블록에 언급된 청크만 반환한다.

    인용 블록을 찾지 못하면 원본 chunks를 그대로 반환해 안전하게 폴백한다.
    """
    cited_docs = {
        m.strip()
        for m in _re.findall(r"\[출처:\s*([^,\]\n]+)", answer)
    }
    if not cited_docs:
        return chunks  # 폴백: 인용 없으면 전체 표시
    filtered = [c for c in chunks if c.metadata.get("doc_short") in cited_docs]
    return filtered if filtered else chunks  # 폴백: 매칭 실패 시 전체 표시
```

#### 2-B. 호출 위치

`streamlit_app.py`에서 LLM 답변이 완성된 직후 (`answer()` 반환 또는 스트리밍 완료 후), `messages.append()`에 저장하는 `chunks` 값을 아래와 같이 교체한다.

```python
# 변경 전
"chunks": result.chunks,

# 변경 후
"chunks": _filter_cited_chunks(result.answer, result.chunks),
```

스트리밍 모드에서는 스트리밍 완료 후 누적된 `full_answer`를 기준으로 동일하게 필터링한다.

### 수용 기준

- 답변에 `[출처: 약관, ...]`만 있으면 `doc_short="심평원"` 청크는 출처 expander에 나타나지 않는다.
- 답변에 `[출처:` 블록이 전혀 없으면 원본 청크가 그대로 표시된다 (폴백).
- `tests/test_streamlit_app.py`에 `test_filter_cited_chunks_returns_only_cited_docs` 테스트 추가:
  - 시나리오 A: 답변에 `[출처: 약관, p.38]` → `doc_short="약관"` 청크만 반환.
  - 시나리오 B: 답변에 인용 없음 → 원본 청크 전체 반환.
  - 시나리오 C: 답변에 `[출처: 없는문서]` → 매칭 실패 → 원본 청크 전체 반환.

---

## M-α-3: 교통사고·이륜자동차 검색 쿼리 확장

### 배경

`_expand_retrieval_query()`는 현재 `3대비급여` 케이스 하나만 처리한다. 교통사고·이륜자동차 질의는 "상해급여", "보험금을 지급하지 않는 사유" 등 약관 핵심 용어와 간격이 커서 BM25 매칭이 약하다.

### 구현 상세

`src/rag/pipeline.py`의 `_expand_retrieval_query()` 함수 내부에 아래 블록을 기존 `3대비급여` 조건 앞에 추가한다.

```python
# 교통사고 / 자동차 관련
if any(keyword in question for keyword in ["교통사고", "자동차사고", "차량사고", "차 사고"]):
    return (
        f"{question} "
        "상해급여 상해비급여 보장개시일 자동차보험 산재보험 "
        "본인부담의료비 보험금을 지급하지 않는 사유"
    )

# 이륜자동차 / 오토바이 관련
if any(keyword in question for keyword in ["이륜자동차", "오토바이", "원동기", "스쿠터"]):
    return (
        f"{question} "
        "이륜자동차 부담보 특별약관 보험금을 지급하지 않는 사유 "
        "상해 탑승 운전 알릴 의무 통지"
    )

# 음주 관련 상해
if any(keyword in question for keyword in ["음주", "만취", "술"]) and any(
    keyword in question for keyword in ["사고", "상해", "다쳤", "부상"]
):
    return (
        f"{question} "
        "보험금을 지급하지 않는 사유 면책 고의 중대한 과실 상해"
    )
```

### 수용 기준

- `tests/test_pipeline.py`에 아래 3개 테스트 추가:
  ```python
  def test_expand_retrieval_query_for_traffic_accident(): ...
  def test_expand_retrieval_query_for_motorcycle(): ...
  def test_expand_retrieval_query_for_drunk_injury(): ...
  ```
  각 테스트는 확장 후 문자열에 핵심 확장어가 포함됨을 assert.
- 기존 `test_expand_retrieval_query_for_three_major_non_covered_items` 계속 통과.

---

## M-α-4: smoke_qa v2 — 약관 정형 모드 10문항

### 배경

`scripts/eval.py`는 `eval/smoke_qa.jsonl`을 읽어 평가한다. 현재 파일에는 코드 조회(심평원)와 일반 Q&A 위주로만 문항이 있다. 약관 정형(보상 판정) 시나리오가 없어 해당 파이프라인의 품질을 자동 평가할 수 없다.

### 구현 상세

#### 4-A. `eval/smoke_qa_v2.jsonl` 신규 생성

아래 10문항을 JSONL 형식으로 생성한다. 각 항목은 `scripts/eval.py`의 기존 `load_questions()` 포맷을 따른다.

```jsonl
{"question": "N39.3 진단을 받아 질병급여 청구를 하려 합니다. 보상 가능한가요?", "expected_pages": [38], "expected_codes": ["N39.3"], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "불가"}
{"question": "M79.3 (근막통증증후군)으로 물리치료를 받았는데 질병비급여에서 보상이 되나요?", "expected_pages": [80], "expected_codes": ["M79.3"], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "판정필요"}
{"question": "정기 건강검진(Z01.0)을 받았습니다. 실손의료비로 청구할 수 있나요?", "expected_pages": [38, 80], "expected_codes": ["Z01.0"], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "불가"}
{"question": "이륜자동차를 운전하다가 사고가 났습니다. 상해보험금을 받을 수 있나요?", "expected_pages": [88, 89], "expected_codes": [], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "불가"}
{"question": "술을 마신 상태에서 넘어져 골절이 됐습니다. 상해급여에서 보상되나요?", "expected_pages": [5, 6], "expected_codes": [], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "판정필요"}
{"question": "선천성 심장질환(Q21.1)으로 수술을 받았는데 실손 청구가 가능한가요?", "expected_pages": [38], "expected_codes": ["Q21.1"], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "불가"}
{"question": "MRI(자기공명영상) 검사를 받았습니다. 3대비급여에서 보상받을 수 있나요?", "expected_pages": [82, 83], "expected_codes": [], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "판정필요"}
{"question": "보험 가입 후 3일째 되는 날 발생한 교통사고로 입원했습니다. 보장개시일 관련 규정을 설명해주세요.", "expected_pages": [14, 15], "expected_codes": [], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "판정필요"}
{"question": "미용 목적 쌍꺼풀 수술 후 염증이 생겼습니다. 합병증 치료비를 실손으로 받을 수 있나요?", "expected_pages": [38, 80], "expected_codes": [], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "불가"}
{"question": "직장 동료가 저를 폭행해 상해를 입었습니다. 상해급여로 보상이 가능한가요?", "expected_pages": [5, 6], "expected_codes": [], "doc_sources": ["약관"], "type": "coverage_judgment", "expected_verdict": "판정필요"}
```

> **`expected_verdict` 필드**: `"불가"` = 명시적 면책, `"판정필요"` = 약관 조항 확인 필요(보상 가능성 있음). 평가 스크립트가 이 필드를 사용해 답변에서 해당 키워드 포함 여부를 체크한다.

#### 4-B. `scripts/eval.py` — v2 평가 지원 추가

기존 평가 스크립트에 아래 수정을 가한다:

1. **`SMOKE_QA_V2_PATH`** 상수 추가:
   ```python
   SMOKE_QA_V2_PATH = ROOT / "eval" / "smoke_qa_v2.jsonl"
   ```

2. **verdict 평가 함수 추가:**
   ```python
   def answer_matches_verdict(answer: str, expected_verdict: str) -> bool:
       """답변이 기대 판정(불가/판정필요)과 일치하는지 확인한다."""
       if expected_verdict == "불가":
           return any(kw in answer for kw in ["보상하지 않", "지급하지 않", "면책", "보상 불가", "청구 불가"])
       elif expected_verdict == "판정필요":
           return any(kw in answer for kw in ["약관", "조항", "확인", "판정", "경우에 따라"])
       return True
   ```

3. **`--v2` CLI 플래그 추가:** `--v2` 옵션 사용 시 `SMOKE_QA_V2_PATH` 파일을 로드해 평가.

4. **`type == "coverage_judgment"` 문항 처리:** 기존 `type == "code"` 평가 로직과 분리해, `coverage_judgment` 타입은 `expected_verdict` + `doc_sources` 기준으로 평가.

#### 4-C. `tests/test_eval.py` — v2 평가 유닛 테스트 추가

```python
def test_answer_matches_verdict_not_covered() -> None:
    assert answer_matches_verdict("이 경우 보상하지 않습니다.", "불가") is True
    assert answer_matches_verdict("보상이 가능합니다.", "불가") is False

def test_answer_matches_verdict_needs_judgment() -> None:
    assert answer_matches_verdict("약관 조항을 확인해야 합니다.", "판정필요") is True

def test_smoke_qa_v2_file_loads_ten_items(tmp_path) -> None:
    """smoke_qa_v2.jsonl에 정확히 10문항이 있어야 한다."""
    from scripts.eval import SMOKE_QA_V2_PATH, load_questions
    items = load_questions(SMOKE_QA_V2_PATH)
    assert len(items) == 10
    for item in items:
        assert item["type"] == "coverage_judgment"
        assert "expected_verdict" in item
        assert item["doc_sources"] == ["약관"]
```

### 수용 기준

- `eval/smoke_qa_v2.jsonl` 파일이 존재하며 10문항 모두 `type == "coverage_judgment"`.
- `python scripts/eval.py --v2` 실행 시 오류 없이 종료 (실제 검색 결과 품질은 별도 평가).
- `test_eval.py` 신규 테스트 3개 통과.

---

## M-α-5: Cloud 로그 노이즈 축소 + `.streamlit/config.toml` 생성

### 배경

현재 `.streamlit/config.toml`이 존재하지 않는다. Streamlit의 기본 파일 watcher가 `sentence_transformers`·`transformers` 패키지 내 선택적 모듈(`torchvision` 등)을 탐색하며 WARNING 로그를 생성한다. Cloud 운영 가독성 저하 원인이다.

### 구현 상세

#### 5-A. `.streamlit/config.toml` 신규 생성

프로젝트 루트에 `.streamlit/` 디렉터리와 `config.toml`을 생성한다.

```toml
[server]
# 파일 변경 감지 방식 지정 (watchdog: 효율적, none: 완전 비활성화)
# 개발 중 hot-reload를 유지하면서 불필요한 패키지 탐색을 방지한다.
fileWatcherType = "watchdog"

[runner]
# 빠른 rerun 허용 (기본값과 동일, 명시적으로 표기)
fastReruns = true

[logger]
# INFO 이상만 출력 (기본값 "info", Cloud에서는 warning으로 상향)
level = "warning"
messageFormat = "%(asctime)s %(levelname)s %(name)s: %(message)s"
```

#### 5-B. `src/ui/streamlit_app.py` 상단 — 로거 필터 추가

파일 상단 임포트 블록 직후, 다른 코드보다 앞에 추가한다.

```python
import logging as _logging
# Streamlit file watcher가 선택적 의존성 탐색 시 발생하는 노이즈 억제
_logging.getLogger("transformers.utils.versions").setLevel(_logging.ERROR)
_logging.getLogger("sentence_transformers").setLevel(_logging.WARNING)
```

#### 5-C. `requirements.txt` 또는 `pyproject.toml` 확인

`watchdog` 패키지가 의존성 목록에 없으면 추가한다.

```
watchdog>=3.0
```

### 수용 기준

- `.streamlit/config.toml` 파일이 생성되고 올바른 TOML 문법 확인 (`python -c "import tomllib; tomllib.load(open('.streamlit/config.toml','rb'))"` 통과).
- 로컬에서 `streamlit run src/ui/streamlit_app.py` 실행 시 `torchvision` 관련 WARNING이 표준 출력에 나타나지 않음.
- 기존 기능 영향 없음.

---

## 통합 수용 기준 (전체 M-α)

1. `pytest -q --ignore=tests/test_vector_store.py` — 기존 통과 수 이상 유지 (추가 테스트 모두 GREEN).
2. 관리자 계정으로 로그인 후 질의 → 검색 진단 탭에서 4단계 결과 확인.
3. 교통사고·이륜자동차 질의에서 `_expand_retrieval_query()` 확장어 포함 확인 (단위 테스트).
4. 출처 expander에 LLM이 언급하지 않은 문서의 청크가 표시되지 않음 (단위 테스트 + 수동 확인).
5. `eval/smoke_qa_v2.jsonl` 10문항 로딩 및 `scripts/eval.py --v2` 실행 성공.
6. `.streamlit/config.toml` 존재, Cloud 배포 시 Streamlit 노이즈 로그 감소.

## 비범위 (Phase B 이후)

- 메타 스키마 확장 (`insurance_company`, `is_own_company` 등) — 100개 약관 입수 후 M18
- 자동 배치 인덱싱 (`scripts/ingest_batch.py`) — M19
- 약관 비교 모드 — M21
- OCR 파이프라인 — 스캔본 입수 후 M22

---

*다음 명세: Phase B 착수 시 `22_CODEX_SPEC_BETA1.md` 작성 예정.*
