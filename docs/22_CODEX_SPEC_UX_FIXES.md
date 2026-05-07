# Codex 구현 명세 — UX 버그 수정 + 채팅 영속화 (M-ux-1 ~ M-ux-4)

> **작성:** 기획자 (검토자)
> **작성일:** 2026-05-07
> **기반 커밋:** `34da73a` (master HEAD)
> **대상:** Codex 개발자 에이전트

---

## 0. 작업 목록

| ID | 제목 | 난이도 | 핵심 변경 파일 |
|----|------|--------|----------------|
| M-ux-1 | 검색 진단 탭 "질의 먼저 실행" 버그 수정 | 소 | `src/rag/pipeline.py`, `src/ui/streamlit_app.py`, `src/ui/admin_page.py` |
| M-ux-2 | 물결표(`~`) 취소선 렌더링 수정 | 소 | `src/ui/streamlit_app.py` |
| M-ux-3 | 계정별 채팅 내역 영속화 | 중 | `src/ui/chat_store.py` (신규), `src/ui/streamlit_app.py` |
| M-ux-4 | 멀티 채팅 스레드 (사이드바 채팅 목록) | 중 | `src/ui/chat_store.py`, `src/ui/streamlit_app.py` |

**커밋 전략:** M-ux-1, M-ux-2는 독립 커밋. M-ux-3과 M-ux-4는 같은 파일을 변경하므로 하나의 커밋으로 묶는다.
**테스트 요건:** `pytest -q --ignore=tests/test_vector_store.py` 기존 통과 수 이상 유지.

---

## M-ux-1: 검색 진단 탭 "질의 먼저 실행하세요" 버그 수정

### 근본 원인

현재 `_stream_answer()`는 `return_debug: bool = False` 파라미터를 받고, 사이드바 체크박스(`st.session_state.debug_mode`)가 `True`일 때만 `return_debug=True`로 전달한다. 체크박스가 꺼진 채로 질의를 수행하면 `debug=None`이 반환되고, 관리자 탭의 `last_debug` 키가 설정되지 않는다.

결과적으로 관리자가 직접 질의를 실행해도 체크박스를 사전에 체크하지 않으면 검색 진단 탭은 항상 "질의를 먼저 실행하세요."를 표시한다.

### 수정 내용

#### 1-A. 사이드바 체크박스 제거

`streamlit_app.py`의 사이드바에서 아래 라인을 **제거**한다:

```python
# 제거 대상
if role == ROLE_ADMIN:
    st.checkbox("🔍 검색 디버그 활성화", key="debug_mode")
```

디버그 데이터 수집을 UI 체크박스와 분리한다. 수집은 항상 수행하고, 표시는 관리자 탭에서 담당한다.

#### 1-B. `_stream_answer()` — 항상 debug 수집

`streamlit_app.py`의 `_stream_answer()` 시그니처에서 `return_debug` 파라미터를 제거하고, 내부 호출을 `return_debug=True`로 고정한다.

```python
# 변경 전
def _stream_answer(
    pipeline, question, temperature, doc_filter=None, return_debug=False
) -> tuple[str, list, dict, DebugInfo | None]:
    ...
    hits, debug = pipeline.retrieve_hits(question, doc_filter=doc_filter, return_debug=return_debug)

# 변경 후
def _stream_answer(
    pipeline, question, temperature, doc_filter=None
) -> tuple[str, list, dict, DebugInfo | None]:
    ...
    hits, debug = pipeline.retrieve_hits(question, doc_filter=doc_filter, return_debug=True)
```

#### 1-C. `main()` — 매 질의 후 `last_debug` 무조건 저장

`_stream_answer()` 반환 후 아래 라인을 항상 실행한다 (`if debug_mode` 조건 없이):

```python
answer, chunks, timing, debug = _stream_answer(pipeline, question, temperature, doc_filter)
st.session_state["last_debug"] = debug  # 항상 저장
```

퀵 코드·약관 정형 모드는 `_stream_answer()`를 거치지 않으므로, 해당 핸들러에서도 `retrieve_hits()` 후 동일하게 `debug`를 저장한다. 퀵코드와 약관 정형 모드는 내부적으로 `pipeline.retrieve_hits()`를 직접 호출하지 않고 `retrieve_quick_code_chunks` / `retrieve_insurance_form_chunks`를 사용하므로, 이 두 함수에 debug를 반환하도록 수정하거나, 별도로 `pipeline.retrieve_hits(question, return_debug=True)`를 호출해 `last_debug`만 저장한다. **이 중 가장 단순한 방법을 선택한다**:

- 퀵코드/약관정형 핸들러 (`_handle_quick_code`, `_handle_insurance_form`)에서 chunks 확정 후 아래를 추가:
  ```python
  # 검색 진단 탭을 위한 debug 저장 (일반 모드와 동일)
  _, debug = pipeline.retrieve_hits(question, doc_filter=applied_doc_filter, return_debug=True)
  st.session_state["last_debug"] = debug
  ```
  단, 이 경우 retrieve가 한 번 더 실행된다. **대안으로**, `last_debug`를 None으로 설정해 "이 모드는 진단 미지원" 메시지를 표시하는 방법도 수용 가능.

#### 1-D. `admin_page.py` — `last_debug` None 처리 개선

```python
# 변경 전
if "last_debug" not in st.session_state or st.session_state.last_debug is None:
    st.info("질의를 먼저 실행하세요.")

# 변경 후
debug = st.session_state.get("last_debug")
if debug is None:
    st.info("챗봇 페이지에서 일반 질의를 먼저 실행하면 단계별 결과가 여기에 표시됩니다.")
    st.caption("(퀵 코드·약관 정형 모드는 진단 데이터를 수집하지 않습니다.)")
else:
    # 기존 4단계 표시 코드
    ...
```

#### 1-E. 로그아웃 시 `last_debug` 정리

`streamlit_app.py`의 로그아웃 처리에서 `last_debug`도 제거한다:

```python
# 변경 전
for key in ("authenticated", "user_id", "user_role", "user_display", "messages"):

# 변경 후
for key in ("authenticated", "user_id", "user_role", "user_display", "messages", "last_debug"):
```

### 수용 기준

- 관리자 계정으로 일반 질의 실행 후 → 관리자 탭 → 검색 진단 탭: 4단계 결과 표시.
- 직원 계정으로 질의 후 관리자 계정으로 재로그인해 질의 없이 검색 진단 탭 접근: 올바른 안내 메시지 ("먼저 실행하면 여기에 표시됩니다") 표시.
- 기존 `test_pipeline.py` 전체 통과.

---

## M-ux-2: 물결표(`~`) 취소선 렌더링 수정

### 원인

Streamlit의 `st.markdown()`은 일부 마크다운 변형에서 `~텍스트~` 패턴을 취소선(`<del>`)으로 렌더링한다. LLM이 한국어 범위 표기(`1~10`, `p.38~42` 등)를 출력할 때 이 문제가 발생한다.

### 수정 내용

#### 2-A. `_sanitize_answer_markdown()` 함수 추가

`streamlit_app.py`의 헬퍼 함수 그룹에 아래를 추가한다:

```python
def _sanitize_answer_markdown(text: str) -> str:
    """LLM 답변의 물결표(~) 양측에 공백을 추가해 취소선 렌더링을 방지한다.

    대상: 양측에 공백이 없는 단일 물결표 (예: 1~10 → 1 ~ 10)
    비대상: 이중 물결표(~~취소선~~), 이미 공백이 있는 경우.
    """
    # (?<![~\s]) : 앞이 ~나 공백이 아닌 경우
    # ~
    # (?![~\s])  : 뒤가 ~나 공백이 아닌 경우
    return _re.sub(r"(?<![~\s])~(?![~\s])", " ~ ", text)
```

#### 2-B. 적용 위치

총 2곳에 적용한다.

**위치 1 — `_stream_answer()` 내부, `append_retrieved_source_citations()` 호출 직전:**

```python
# 변경 전
answer = append_retrieved_source_citations("".join(tokens).strip(), chunks)

# 변경 후
raw_answer = "".join(tokens).strip()
answer = append_retrieved_source_citations(_sanitize_answer_markdown(raw_answer), chunks)
```

**위치 2 — `_handle_quick_code()`, `_handle_insurance_form()` 내부:**

각 핸들러에서 `answer = generate_*_answer(...)` 직후:

```python
answer = _sanitize_answer_markdown(answer)
answer = append_retrieved_source_citations(answer, chunks)  # 기존 라인
```

> **주의:** `_export_txt`, `_export_csv`, `_export_json`에는 적용하지 않는다. 내보내기는 원본 텍스트를 보존해야 한다. 이미 메시지로 저장된 내용에 `_sanitize_answer_markdown()`이 적용되어 있으므로 추가 처리가 불필요하다.

#### 2-C. 단위 테스트 추가

`tests/test_streamlit_app.py`에 추가:

```python
def test_sanitize_answer_markdown_adds_spaces_around_tilde() -> None:
    from src.ui.streamlit_app import _sanitize_answer_markdown

    assert _sanitize_answer_markdown("1~10") == "1 ~ 10"
    assert _sanitize_answer_markdown("p.38~42") == "p.38 ~ 42"
    assert _sanitize_answer_markdown("~~취소선~~") == "~~취소선~~"   # 이중 물결표 보존
    assert _sanitize_answer_markdown("1 ~ 10") == "1 ~ 10"          # 이미 공백 있는 경우 변경 없음
    assert _sanitize_answer_markdown("정상 텍스트") == "정상 텍스트"
```

### 수용 기준

- `"1~10"` → `"1 ~ 10"` 변환 확인.
- `"~~취소선~~"` 유지 확인.
- UI에서 범위 표기(`p.38~42` 등)가 취소선 없이 정상 표시.

---

## M-ux-3 & M-ux-4: 계정별 채팅 영속화 + 멀티 채팅 스레드

두 기능은 동일한 인프라를 공유하므로 하나의 커밋으로 구현한다.

### 설계 개요

| 항목 | 현재 | 변경 후 |
|------|------|---------|
| 저장소 | `st.session_state.messages` (인메모리) | `data/chat_history/<user_id>/<chat_id>.json` (디스크) |
| 생명주기 | 로그아웃/새로고침 시 소멸 | 계정별 영속, 로그인 후 복원 |
| 채팅 수 | 세션당 1개 | 계정당 최대 50개 (자동 정렬·관리) |
| 사이드바 | 없음 | 채팅 목록 + 새 채팅 버튼 + 삭제 |
| Cloud 주의 | — | Streamlit Community Cloud는 재시작 시 ephemeral 저장소 초기화됨 → 채팅 내역 휘발 가능. 로컬 실행에서는 완전 영속 |

### 데이터 모델

```
data/
  chat_history/
    <user_id>/
      <chat_uuid8>.json    # 채팅 1건당 파일 1개
```

**채팅 파일 스키마:**

```json
{
  "chat_id": "a1b2c3d4",
  "user_id": "범준",
  "title": "N39.3 보상 여부는?",
  "created_at": "2026-05-07T10:00:00+09:00",
  "updated_at": "2026-05-07T10:05:30+09:00",
  "message_count": 4,
  "messages": [
    {"role": "user", "content": "N39.3 보상 여부는?"},
    {
      "role": "assistant",
      "content": "N39.3(요실금)은 ...",
      "timing": {"retrieve_ms": 230.4, "llm_ms": 3100.2, "total_ms": 3330.6},
      "model": "gpt-5.2-chat-latest",
      "chunks": [
        {
          "id": "약관_ch_000042",
          "text": "N39.3 ...",
          "metadata": {"doc_short": "약관", "page_start": 38, "page_end": 38}
        }
      ]
    }
  ]
}
```

> **직렬화 주의:** `messages`의 `chunks` 필드는 `Chunk` 객체이므로 저장 시 dict로 변환, 로드 시 `Chunk`로 복원한다.

### 신규 파일: `src/ui/chat_store.py`

아래 전체 내용을 그대로 구현한다.

```python
"""계정별 채팅 내역 저장소."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.parser.chunker import Chunk

CHAT_HISTORY_DIR = config.ROOT_DIR / "data" / "chat_history"
MAX_CHATS_PER_USER = 50


def _chat_dir(user_id: str) -> Path:
    path = CHAT_HISTORY_DIR / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_chat_id() -> str:
    """8자리 UUID 생성."""
    return str(uuid.uuid4())[:8]


def _auto_title(messages: list[dict]) -> str:
    """첫 사용자 메시지 앞 30자를 채팅 제목으로 사용한다."""
    for msg in messages:
        if msg.get("role") == "user":
            return msg["content"][:30].replace("\n", " ")
    return "새 채팅"


# ─── 직렬화 / 역직렬화 ─────────────────────────────────────────────────────

def _chunk_to_dict(chunk: Chunk) -> dict:
    return {"id": chunk.id, "text": chunk.text, "metadata": chunk.metadata}


def _dict_to_chunk(d: dict) -> Chunk:
    return Chunk(id=d["id"], text=d["text"], metadata=d.get("metadata", {}))


def _serialize_messages(messages: list[dict]) -> list[dict]:
    """st.session_state 형식 → JSON 저장 형식."""
    result = []
    for msg in messages:
        entry: dict = {"role": msg["role"], "content": msg["content"]}
        if msg["role"] == "assistant":
            for key in ("timing", "model"):
                if key in msg:
                    entry[key] = msg[key]
            if "chunks" in msg:
                entry["chunks"] = [_chunk_to_dict(c) for c in msg["chunks"]]
        result.append(entry)
    return result


def _deserialize_messages(messages: list[dict]) -> list[dict]:
    """JSON 저장 형식 → st.session_state 형식."""
    result = []
    for msg in messages:
        entry: dict = {"role": msg["role"], "content": msg["content"]}
        if msg["role"] == "assistant":
            for key in ("timing", "model"):
                if key in msg:
                    entry[key] = msg[key]
            if "chunks" in msg:
                entry["chunks"] = [_dict_to_chunk(c) for c in msg["chunks"]]
        result.append(entry)
    return result


# ─── CRUD ──────────────────────────────────────────────────────────────────

def save_chat(
    user_id: str,
    chat_id: str,
    messages: list[dict],
    title: str | None = None,
) -> None:
    """채팅을 디스크에 저장한다. 이미 존재하면 내용을 갱신한다."""
    path = _chat_dir(user_id) / f"{chat_id}.json"
    now = datetime.now(timezone.utc).isoformat()

    # created_at은 최초 생성 시각을 보존
    created_at = now
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            created_at = existing.get("created_at", now)
        except Exception:
            pass

    data = {
        "chat_id": chat_id,
        "user_id": user_id,
        "title": title or _auto_title(messages),
        "created_at": created_at,
        "updated_at": now,
        "message_count": len(messages),
        "messages": _serialize_messages(messages),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_chat(user_id: str, chat_id: str) -> dict | None:
    """저장된 채팅을 로드한다. 파일이 없거나 손상된 경우 None 반환."""
    path = _chat_dir(user_id) / f"{chat_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["messages"] = _deserialize_messages(data.get("messages", []))
        return data
    except Exception:
        return None


def list_user_chats(user_id: str) -> list[dict]:
    """사용자의 채팅 목록을 최신순으로 반환한다 (messages 필드 제외)."""
    chats: list[dict] = []
    for path in _chat_dir(user_id).glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            chats.append({
                "chat_id": raw["chat_id"],
                "title": raw.get("title", "제목 없음"),
                "updated_at": raw.get("updated_at", ""),
                "message_count": raw.get("message_count", 0),
            })
        except Exception:
            continue
    chats.sort(key=lambda x: x["updated_at"], reverse=True)
    return chats[:MAX_CHATS_PER_USER]


def delete_chat(user_id: str, chat_id: str) -> bool:
    """채팅 파일을 삭제한다. 성공 여부를 반환한다."""
    path = _chat_dir(user_id) / f"{chat_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def rename_chat(user_id: str, chat_id: str, new_title: str) -> bool:
    """채팅 제목을 변경한다."""
    path = _chat_dir(user_id) / f"{chat_id}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["title"] = new_title[:40]  # 최대 40자
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False
```

### `streamlit_app.py` 수정

#### 3-A. 임포트 추가

```python
from src.ui.chat_store import (
    delete_chat, list_user_chats, load_chat, new_chat_id, save_chat,
)
```

#### 3-B. 세션 초기화 헬퍼 추가

`main()` 함수 내 인증 성공 후 (`if not _check_auth(...)` 다음), 아래 블록을 추가한다:

```python
user_id = st.session_state.get("user_id", "")

# 채팅 세션 초기화 (로그인 직후 1회)
if "chat_list" not in st.session_state:
    st.session_state.chat_list = list_user_chats(user_id)
if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
```

#### 3-C. 채팅 관리 헬퍼 함수 추가

```python
def _start_new_chat() -> None:
    """새 채팅을 시작한다. 현재 메시지와 chat_id를 초기화한다."""
    st.session_state.current_chat_id = None
    st.session_state.messages = []


def _switch_chat(user_id: str, chat_id: str) -> None:
    """저장된 채팅을 불러와 현재 세션에 적용한다."""
    chat = load_chat(user_id, chat_id)
    if chat:
        st.session_state.current_chat_id = chat_id
        st.session_state.messages = chat["messages"]


def _auto_save(user_id: str) -> None:
    """어시스턴트 메시지 추가 후 채팅을 자동 저장하고 목록을 갱신한다."""
    if not st.session_state.messages:
        return
    if st.session_state.current_chat_id is None:
        st.session_state.current_chat_id = new_chat_id()
    save_chat(user_id, st.session_state.current_chat_id, st.session_state.messages)
    st.session_state.chat_list = list_user_chats(user_id)
```

#### 3-D. 사이드바 채팅 목록 렌더링

기존 사이드바의 **"대화 초기화" 버튼 위에** 아래 블록을 삽입한다:

```python
# ─── 채팅 목록 (M-ux-3/4) ─────────────────────────────────────
st.subheader("💬 채팅 목록")
if st.button("+ 새 채팅", use_container_width=True, type="primary"):
    _start_new_chat()
    st.rerun()

chat_list = st.session_state.get("chat_list", [])
if not chat_list:
    st.caption("저장된 채팅이 없습니다.")
else:
    for meta in chat_list:
        cid = meta["chat_id"]
        is_active = cid == st.session_state.get("current_chat_id")
        # 날짜 축약 (updated_at의 날짜 부분만)
        date_str = meta.get("updated_at", "")[:10]
        label = meta["title"]

        col_btn, col_del = st.columns([5, 1])
        with col_btn:
            btn_type = "primary" if is_active else "secondary"
            if st.button(
                label,
                key=f"chat_sel_{cid}",
                use_container_width=True,
                type=btn_type,
                help=f"{date_str} · {meta['message_count']}개 메시지",
            ):
                if not is_active:
                    _switch_chat(user_id, cid)
                    st.rerun()
        with col_del:
            if st.button("🗑", key=f"chat_del_{cid}", help="삭제"):
                delete_chat(user_id, cid)
                if is_active:
                    _start_new_chat()
                st.session_state.chat_list = list_user_chats(user_id)
                st.rerun()

st.divider()
# ─── 기존 "대화 초기화" 버튼은 제거 또는 유지 ───────────────────
# 기존 st.button("대화 초기화") 는 제거한다.
# "새 채팅" 버튼이 동일한 역할을 하므로 중복.
```

#### 3-E. 자동 저장 트리거

어시스턴트 메시지를 `st.session_state.messages.append()` 하는 **모든 3곳** (일반 질의, 퀵 코드, 약관 정형)에서 append 직후 `_auto_save(user_id)` 호출을 추가한다.

```python
# 변경 전 (예: 일반 질의 핸들러)
st.session_state.messages.append({
    "role": "assistant",
    "content": answer,
    "chunks": cited_chunks,
    "timing": timing,
    "model": model,
})

# 변경 후
st.session_state.messages.append({
    "role": "assistant",
    "content": answer,
    "chunks": cited_chunks,
    "timing": timing,
    "model": model,
})
_auto_save(user_id)  # ← 추가
```

#### 3-F. 로그아웃 시 채팅 세션 키 정리

```python
# 변경 전
for key in ("authenticated", "user_id", "user_role", "user_display", "messages", "last_debug"):

# 변경 후
for key in (
    "authenticated", "user_id", "user_role", "user_display",
    "messages", "last_debug", "current_chat_id", "chat_list",
):
```

### 단위 테스트: `tests/test_chat_store.py` (신규)

```python
import json
from pathlib import Path

import pytest

from src.ui.chat_store import (
    delete_chat, list_user_chats, load_chat, new_chat_id, rename_chat, save_chat,
    CHAT_HISTORY_DIR,
)
from src.parser.chunker import Chunk


@pytest.fixture(autouse=True)
def isolated_chat_dir(tmp_path, monkeypatch):
    """테스트마다 독립된 임시 chat_history 디렉터리를 사용한다."""
    import src.ui.chat_store as cs
    monkeypatch.setattr(cs, "CHAT_HISTORY_DIR", tmp_path / "chat_history")


def _make_messages():
    chunk = Chunk(
        id="약관_ch_001",
        text="N39.3은 보상하지 않습니다.",
        metadata={"doc_short": "약관", "page_start": 38, "page_end": 38},
    )
    return [
        {"role": "user", "content": "N39.3 보상 여부는?"},
        {
            "role": "assistant",
            "content": "보상하지 않습니다.",
            "timing": {"retrieve_ms": 100.0, "llm_ms": 2000.0, "total_ms": 2100.0},
            "model": "gpt-5.2-chat-latest",
            "chunks": [chunk],
        },
    ]


def test_save_and_load_chat_roundtrip() -> None:
    messages = _make_messages()
    save_chat("user1", "abc12345", messages)

    loaded = load_chat("user1", "abc12345")

    assert loaded is not None
    assert loaded["chat_id"] == "abc12345"
    assert loaded["title"] == "N39.3 보상 여부는?"
    assert len(loaded["messages"]) == 2
    # Chunk 역직렬화 확인
    assistant_msg = loaded["messages"][1]
    assert len(assistant_msg["chunks"]) == 1
    assert assistant_msg["chunks"][0].id == "약관_ch_001"
    assert assistant_msg["model"] == "gpt-5.2-chat-latest"


def test_list_user_chats_returns_sorted_by_updated_at() -> None:
    save_chat("user1", "old_chat", [{"role": "user", "content": "오래된 질의"}])
    import time; time.sleep(0.01)
    save_chat("user1", "new_chat", [{"role": "user", "content": "최신 질의"}])

    chat_list = list_user_chats("user1")

    assert chat_list[0]["chat_id"] == "new_chat"
    assert chat_list[1]["chat_id"] == "old_chat"


def test_delete_chat_removes_file() -> None:
    save_chat("user1", "to_delete", [{"role": "user", "content": "삭제 테스트"}])
    assert delete_chat("user1", "to_delete") is True
    assert load_chat("user1", "to_delete") is None


def test_load_chat_returns_none_for_missing() -> None:
    assert load_chat("user1", "nonexistent") is None


def test_created_at_preserved_on_update() -> None:
    messages = _make_messages()
    save_chat("user1", "stable", messages)
    first = load_chat("user1", "stable")
    first_created = first["created_at"]

    import time; time.sleep(0.01)
    messages.append({"role": "user", "content": "추가 질의"})
    save_chat("user1", "stable", messages)
    second = load_chat("user1", "stable")

    assert second["created_at"] == first_created
    assert second["updated_at"] > first_created


def test_rename_chat() -> None:
    save_chat("user1", "rename_me", [{"role": "user", "content": "원래 제목"}])
    assert rename_chat("user1", "rename_me", "새 제목") is True
    loaded = load_chat("user1", "rename_me")
    assert loaded["title"] == "새 제목"


def test_new_chat_id_has_8_chars() -> None:
    assert len(new_chat_id()) == 8
```

### `.gitignore` 추가

`data/chat_history/` 경로를 `.gitignore`에 추가해 사용자 채팅 내역이 GitHub에 커밋되지 않도록 한다:

```
data/chat_history/
```

### Cloud 배포 주의사항 (README 또는 배포 가이드에 추가)

```markdown
### 채팅 내역 영속성 (Cloud 환경)

Streamlit Community Cloud는 서버 재시작 시 `data/` 디렉터리가 초기화됩니다.
채팅 내역은 같은 서버 세션 중에는 유지되지만, 서버가 재시작되면 삭제됩니다.
로컬 실행 환경에서는 완전한 영속성을 보장합니다.

Cloud에서 영속 저장이 필요한 경우, Phase B 이후 외부 객체 저장소(S3/R2)
연동을 고려하세요.
```

---

## 통합 수용 기준 (전체 M-ux)

1. `pytest -q --ignore=tests/test_vector_store.py` — 기존 통과 수 + 신규 테스트 모두 GREEN.
2. 관리자 계정으로 일반 질의 1회 실행 후 관리자 탭 → 검색 진단: 4단계 결과 표시.
3. LLM 답변에서 `1~10` → `1 ~ 10` 렌더링, `~~취소선~~` 그대로 표시.
4. 로그아웃 후 재로그인 → 이전 채팅 목록이 사이드바에 복원됨.
5. 새 채팅 버튼 → 빈 채팅 시작, 기존 채팅 목록은 유지.
6. 채팅 목록에서 기존 채팅 클릭 → 이전 대화 내용이 채팅창에 로드됨.
7. 채팅 삭제 버튼 → 해당 채팅이 목록과 디스크에서 제거됨.
8. `data/chat_history/` 가 `.gitignore`에 추가됨.
