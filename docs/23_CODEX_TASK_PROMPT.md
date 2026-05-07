# Codex 개발자 태스크 — 미완료 항목 구현 (2026-05-07)

> 이 파일을 Codex에 그대로 붙여넣으세요.

---

## 역할 및 컨텍스트

당신은 보험 문서 RAG 챗봇 프로젝트의 개발자입니다. 이 프로젝트는 Python + Streamlit + Ollama(LLM) + ChromaDB(벡터 검색) + BM25로 구성된 한국어 보험 문서 Q&A 시스템입니다.

**프로젝트 경로:** `~/Documents/Claude/Projects/보험 문서 RAG 챗봇`

**기반 커밋:** `34da73a` (master HEAD)

**테스트 명령 (항상 이것으로 검증):**
```bash
pytest -q --ignore=tests/test_vector_store.py
```

---

## 이미 구현된 항목 (건드리지 말 것)

- `src/rag/pipeline.py`: `DebugInfo`, `StageHit`, `_hits_to_stage()`, `retrieve_hits()` → `tuple[list[Hit], DebugInfo | None]` 반환, `_expand_retrieval_query()` 교통사고·이륜자동차·음주 확장 ✓
- `src/ui/admin_page.py`: `🔍 검색 진단` 탭 ✓
- `src/ui/streamlit_app.py`: `_filter_cited_chunks()` ✓

---

## 구현할 항목 (5개 커밋)

상세 명세는 아래 파일을 참고하세요:
- `docs/21_CODEX_SPEC_ALPHA_FINAL.md` — M-α-4, M-α-5
- `docs/22_CODEX_SPEC_UX_FIXES.md` — M-ux-1, M-ux-2, M-ux-3/4

---

### 커밋 1: M-α-4 — smoke_qa v2

**파일 생성/수정:**

1. **`eval/smoke_qa_v2.jsonl`** 신규 생성 — 약관 정형 모드 10문항 (명세 §4-A 참고)

2. **`scripts/eval.py`** 수정:
   - `SMOKE_QA_V2_PATH = ROOT / "eval" / "smoke_qa_v2.jsonl"` 상수 추가
   - `answer_matches_verdict(answer, expected_verdict)` 함수 추가
   - `--v2` CLI 플래그 추가 (`argparse` 또는 기존 방식 따름)
   - `type == "coverage_judgment"` 문항 처리 분기 추가

3. **`tests/test_eval.py`** 수정 — 명세 §4-C의 테스트 3개 추가

**커밋 메시지:** `eval: add smoke_qa_v2.jsonl with 10 coverage-judgment items (M-α-4)`

---

### 커밋 2: M-α-5 — Streamlit 설정 + 로그 노이즈 축소

**파일 생성/수정:**

1. **`.streamlit/config.toml`** 신규 생성:
```toml
[server]
fileWatcherType = "watchdog"

[runner]
fastReruns = true

[logger]
level = "warning"
messageFormat = "%(asctime)s %(levelname)s %(name)s: %(message)s"
```

2. **`src/ui/streamlit_app.py`** 상단 임포트 블록 직후:
```python
import logging as _logging
_logging.getLogger("transformers.utils.versions").setLevel(_logging.ERROR)
_logging.getLogger("sentence_transformers").setLevel(_logging.WARNING)
```

3. **`requirements.txt`** 또는 `pyproject.toml`에 `watchdog>=3.0` 없으면 추가

**검증:** `python -c "import tomllib; tomllib.load(open('.streamlit/config.toml','rb'))"`

**커밋 메시지:** `config: add .streamlit/config.toml and suppress log noise (M-α-5)`

---

### 커밋 3: M-ux-1 — 검색 진단 체크박스 제거 + 항상 debug 수집

현재 `streamlit_app.py`에는 관리자 사이드바에 `st.checkbox("🔍 검색 디버그 활성화", key="debug_mode")`가 있고, 이 체크박스가 꺼진 채로 질의하면 `debug=None`이 되어 검색 진단 탭에 항상 "질의를 먼저 실행하세요."가 표시됩니다.

**수정 내용:**

1. **사이드바 체크박스 제거** (admin 사이드바에서 아래 라인 삭제):
```python
if role == ROLE_ADMIN:
    st.checkbox("🔍 검색 디버그 활성화", key="debug_mode")
```

2. **`_stream_answer()` 시그니처에서 `return_debug` 파라미터 제거**, 내부에서 `return_debug=True`로 고정:
```python
# 변경 후
def _stream_answer(pipeline, question, temperature, doc_filter=None):
    ...
    hits, debug = pipeline.retrieve_hits(question, doc_filter=doc_filter, return_debug=True)
```

3. **`main()` 에서 무조건 `last_debug` 저장** (`if debug_mode:` 조건 제거):
```python
answer, chunks, timing, debug = _stream_answer(pipeline, question, temperature, doc_filter)
st.session_state["last_debug"] = debug  # 항상
```

4. **로그아웃 키 목록에 `"last_debug"` 추가**:
```python
for key in ("authenticated", "user_id", "user_role", "user_display", "messages", "last_debug"):
```

5. **`admin_page.py`의 안내 메시지 개선** (명세 §1-D 참고):
```python
if debug is None:
    st.info("챗봇 페이지에서 일반 질의를 먼저 실행하면 단계별 결과가 여기에 표시됩니다.")
    st.caption("(퀵 코드·약관 정형 모드는 진단 데이터를 수집하지 않습니다.)")
```

**커밋 메시지:** `fix: always collect debug info, remove debug checkbox (M-ux-1)`

---

### 커밋 4: M-ux-2 — 물결표 취소선 수정

**수정 내용:**

1. **`src/ui/streamlit_app.py`** 헬퍼 함수 그룹에 추가:
```python
import re as _re

def _sanitize_answer_markdown(text: str) -> str:
    """LLM 답변의 물결표(~) 양측에 공백 추가해 취소선 렌더링 방지."""
    return _re.sub(r"(?<![~\s])~(?![~\s])", " ~ ", text)
```

2. **적용 위치 2곳:**
   - `_stream_answer()` 내부: `raw_answer = "".join(tokens).strip()` → `answer = append_retrieved_source_citations(_sanitize_answer_markdown(raw_answer), chunks)`
   - `_handle_quick_code()`, `_handle_insurance_form()` 내부: `answer = generate_*_answer(...)` 직후 `answer = _sanitize_answer_markdown(answer)`

3. **`tests/test_streamlit_app.py`** 에 추가:
```python
def test_sanitize_answer_markdown_adds_spaces_around_tilde() -> None:
    from src.ui.streamlit_app import _sanitize_answer_markdown
    assert _sanitize_answer_markdown("1~10") == "1 ~ 10"
    assert _sanitize_answer_markdown("p.38~42") == "p.38 ~ 42"
    assert _sanitize_answer_markdown("~~취소선~~") == "~~취소선~~"
    assert _sanitize_answer_markdown("1 ~ 10") == "1 ~ 10"
    assert _sanitize_answer_markdown("정상 텍스트") == "정상 텍스트"
```

**커밋 메시지:** `fix: add _sanitize_answer_markdown to prevent tilde strikethrough (M-ux-2)`

---

### 커밋 5: M-ux-3/4 — 계정별 채팅 영속화 + 멀티 채팅 사이드바

상세 구현은 `docs/22_CODEX_SPEC_UX_FIXES.md` §M-ux-3/M-ux-4 를 전체 참고하세요.

**파일 변경 요약:**

1. **`src/ui/chat_store.py`** 신규 생성 — 명세 내 전체 코드 그대로 구현 (save/load/list/delete/rename/new_chat_id)

2. **`src/ui/streamlit_app.py`** 수정:
   - `from src.ui.chat_store import ...` 임포트 추가
   - `_start_new_chat()`, `_switch_chat()`, `_auto_save()` 헬퍼 함수 추가
   - 세션 초기화 블록 추가 (`chat_list`, `current_chat_id`)
   - 사이드바: 기존 "대화 초기화" 버튼 제거, 채팅 목록 + "새 채팅" 버튼 추가
   - 어시스턴트 메시지 append 3곳 모두에서 `_auto_save(user_id)` 호출
   - 로그아웃 키 목록에 `"current_chat_id"`, `"chat_list"` 추가

3. **`tests/test_chat_store.py`** 신규 생성 — 명세 내 7개 테스트 전체 구현

4. **`.gitignore`** 에 `data/chat_history/` 추가

**커밋 메시지:** `feat: add per-account chat persistence and multi-thread sidebar (M-ux-3/4)`

---

## 최종 검증

```bash
# 전체 테스트 (test_vector_store.py 제외)
pytest -q --ignore=tests/test_vector_store.py

# 신규 파일 존재 확인
ls eval/smoke_qa_v2.jsonl .streamlit/config.toml src/ui/chat_store.py

# TOML 문법 검증
python -c "import tomllib; tomllib.load(open('.streamlit/config.toml','rb'))"

# gitignore 확인
grep "chat_history" .gitignore
```

모든 테스트 GREEN + 위 파일 존재 확인 후 커밋 완료.
