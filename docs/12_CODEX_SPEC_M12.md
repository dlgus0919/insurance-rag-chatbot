# Codex 개발자 명세 — M12 (인증 · 내보내기 · 로깅)

> **문서 유형:** Codex 전달용 개발자 명세
> **작성일:** 2026-05-04
> **기반 상태:** M11 완료 (스트리밍, 캐시 분리, 모델 선택 적용)
> **배경:** 사내 임직원 대상 챗봇으로 전환 — 접근 통제, 감사 로그, 대화 내보내기 기능 필요

---

## 섹션 0 — Codex에게 전달할 프롬프트 (복사 붙여넣기용)

```
당신은 시니어 Python 개발자입니다.
"보험 문서 RAG 챗봇" 프로젝트 M11이 완료된 상태에서 아래 3가지 기능을 구현해주세요.
사내 임직원 전용 챗봇이므로 접근 통제, 감사 로그, 대화 내보내기가 필요합니다.

---

## M12-1. 백엔드 로깅 모듈

### 파일: `src/utils/logger.py` (신규 생성)

프로젝트 루트의 `logs/` 디렉터리에 날짜별 JSONL 파일로 이벤트를 기록하는 로거를 작성하세요.

```python
"""사내 챗봇 감사 로그 모듈.

logs/chat_YYYY-MM-DD.jsonl 형식으로 저장. 각 줄은 독립적인 JSON 객체.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))

# 기록할 이벤트 유형
EVENT_APP_ACCESS      = "APP_ACCESS"       # 페이지 접속
EVENT_LOGIN_SUCCESS   = "LOGIN_SUCCESS"    # 로그인 성공
EVENT_LOGIN_FAILURE   = "LOGIN_FAILURE"    # 로그인 실패 (비밀번호 불일치)
EVENT_QUESTION        = "QUESTION"         # 사용자 질문 입력
EVENT_ANSWER          = "ANSWER"           # 답변 생성 완료
EVENT_EXPORT          = "EXPORT"           # 대화 내보내기


def _get_logger() -> logging.Logger:
    """날짜별 로테이션 JSONL 파일 로거를 반환한다 (싱글톤)."""
    logger = logging.getLogger("rag_chat_audit")
    if logger.handlers:
        return logger  # 이미 초기화됨

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"chat_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"

    handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=90,       # 90일 보관
        encoding="utf-8",
        utc=True,
    )
    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(event: str, session_id: str, details: dict | None = None) -> None:
    """이벤트를 JSONL 형식으로 기록한다."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "session_id": session_id,
        "details": details or {},
    }
    _get_logger().info(json.dumps(record, ensure_ascii=False))
```

`src/utils/__init__.py`도 빈 파일로 생성하세요.

---

## M12-2. 설정 추가

### `.env` 및 `.env.example` 수정

```
APP_PASSWORD=insure1234    # 임직원 공통 접속 비밀번호 (필수 변경)
LOG_DIR=logs               # 로그 저장 디렉터리 (기본: 프로젝트 루트/logs)
```

### `src/config.py` 수정

기존 설정 아래에 아래 두 줄을 추가하세요:

```python
APP_PASSWORD: str = os.getenv("APP_PASSWORD", "")
LOG_DIR: str = os.getenv("LOG_DIR", "logs")
```

> ⚠️ `APP_PASSWORD`가 빈 문자열이면 비밀번호 없이 접속 가능한 상태로 동작합니다.
> 실제 배포 전 반드시 `.env`에 비밀번호를 설정하세요.

### `.gitignore` 확인

`logs/` 디렉터리가 `.gitignore`에 포함되어 있지 않다면 추가하세요:
```
logs/
```

---

## M12-3. 비밀번호 인증

### `src/ui/streamlit_app.py` 수정

`main()` 함수 상단에 인증 게이트를 추가하세요. 인증되지 않은 경우 로그인 화면만 표시하고 나머지 UI를 렌더링하지 않습니다.

**세션 ID 생성 (앱 접속 시 1회):**

```python
import uuid

def _ensure_session_id() -> str:
    """세션 고유 ID를 생성하거나 기존 값을 반환한다."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]  # 앞 8자리로 축약
    return st.session_state.session_id
```

**인증 함수:**

```python
from src.utils.logger import log_event, EVENT_APP_ACCESS, EVENT_LOGIN_SUCCESS, EVENT_LOGIN_FAILURE


def _check_auth(session_id: str) -> bool:
    """인증 상태를 확인하고 로그인 화면을 렌더링한다.

    인증 완료 시 True, 미완료 시 False를 반환한다.
    APP_PASSWORD가 비어 있으면 인증을 건너뛴다.
    """
    if not config.APP_PASSWORD:
        return True  # 비밀번호 미설정 시 인증 생략

    if st.session_state.get("authenticated"):
        return True

    # 로그인 화면
    st.title("보험 고시 문서 RAG 챗봇")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔐 임직원 전용 서비스")
        password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
        if st.button("로그인", use_container_width=True, type="primary"):
            if password == config.APP_PASSWORD:
                st.session_state.authenticated = True
                log_event(EVENT_LOGIN_SUCCESS, session_id)
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
                log_event(EVENT_LOGIN_FAILURE, session_id, {"reason": "wrong_password"})
    return False
```

**`main()` 함수 수정 — 인증 게이트 삽입:**

```python
def main() -> None:
    st.set_page_config(page_title="보험 고시 문서 RAG 챗봇")

    session_id = _ensure_session_id()

    # 최초 접속 로그 (session_id 새로 생성된 경우에만)
    if st.session_state.get("_access_logged") is not True:
        log_event(EVENT_APP_ACCESS, session_id)
        st.session_state._access_logged = True

    # 인증 게이트
    if not _check_auth(session_id):
        st.stop()

    # 이하 기존 main() 코드 그대로 유지
    st.title("보험 고시 문서 RAG 챗봇")
    ...
```

---

## M12-4. 대화 내보내기

### 내보내기 형식 3종

| 형식 | 내용 | 용도 |
|------|------|------|
| TXT | 사람이 읽기 쉬운 대화 전문 | 인쇄, 공유 |
| CSV | 테이블 형식 (질문·답변·모델·시간) | 데이터 분석 |
| JSON | 청크 메타데이터 포함 전체 구조 | 개발·디버깅 |

### 내보내기 헬퍼 함수 (파일 상단에 추가)

```python
import csv
import io


def _export_txt(messages: list[dict], model: str) -> str:
    """대화 내용을 사람이 읽을 수 있는 텍스트로 변환한다."""
    lines = [
        "=" * 60,
        "보험 고시 문서 RAG 챗봇 — 대화 내보내기",
        f"모델: {model}",
        f"내보낸 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
    ]
    turn = 1
    for msg in messages:
        if msg["role"] == "user":
            lines += [f"[Q{turn}] {msg['content']}", ""]
        else:
            lines += [f"[A{turn}] {msg['content']}", ""]
            if msg.get("timing"):
                t = msg["timing"]
                lines.append(
                    f"  ⏱ 검색 {t['retrieve_ms']:.0f}ms · "
                    f"생성 {t['llm_ms']:.0f}ms · "
                    f"합계 {t['total_ms'] / 1000:.1f}초"
                )
            if msg.get("chunks"):
                lines.append("  📄 참조 출처:")
                for chunk in msg["chunks"][:3]:
                    lines.append(f"    - {_source_title(chunk)}")
            lines.append("-" * 40)
            turn += 1
    return "\n".join(lines)


def _export_csv(messages: list[dict], model: str) -> str:
    """대화 내용을 CSV 문자열로 변환한다."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["순번", "역할", "내용", "모델", "검색(ms)", "생성(ms)", "합계(초)", "주요출처"])
    turn = 1
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg["role"] == "user":
            q_content = msg["content"]
            # 다음 assistant 메시지 탐색
            if i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                a_msg = messages[i + 1]
                t = a_msg.get("timing", {})
                chunks = a_msg.get("chunks", [])
                source = _source_title(chunks[0]) if chunks else ""
                writer.writerow([
                    turn, "Q", q_content, "", "", "", "", "",
                ])
                writer.writerow([
                    turn, "A", a_msg["content"], model,
                    f"{t.get('retrieve_ms', 0):.0f}",
                    f"{t.get('llm_ms', 0):.0f}",
                    f"{t.get('total_ms', 0) / 1000:.1f}",
                    source,
                ])
                turn += 1
                i += 2
                continue
        i += 1
    return output.getvalue()


def _export_json(messages: list[dict], model: str) -> str:
    """대화 내용을 JSON 문자열로 변환한다. 청크 메타데이터 포함."""
    from datetime import datetime as _dt
    export_data = {
        "exported_at": _dt.now().isoformat(),
        "model": model,
        "turn_count": sum(1 for m in messages if m["role"] == "user"),
        "messages": [],
    }
    for msg in messages:
        entry: dict = {"role": msg["role"], "content": msg["content"]}
        if msg["role"] == "assistant":
            if msg.get("timing"):
                entry["timing"] = msg["timing"]
            if msg.get("chunks"):
                entry["sources"] = [
                    {
                        "id": c.id,
                        "doc_short": c.metadata.get("doc_short"),
                        "pdf_filename": c.metadata.get("pdf_filename"),
                        "page_start": c.metadata.get("page_start"),
                        "page_end": c.metadata.get("page_end"),
                    }
                    for c in msg["chunks"]
                ]
        export_data["messages"].append(entry)
    return json.dumps(export_data, ensure_ascii=False, indent=2)
```

### 사이드바에 내보내기 버튼 추가

기존 사이드바 `with st.sidebar:` 블록 안, "대화 초기화" 버튼 아래에 추가하세요:

```python
with st.sidebar:
    ...  # 기존 슬라이더, 모델 선택 등

    st.divider()
    st.markdown("**대화 내보내기**")

    has_messages = bool(st.session_state.get("messages"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    col_txt, col_csv, col_json = st.columns(3)
    with col_txt:
        st.download_button(
            label="TXT",
            data=_export_txt(st.session_state.get("messages", []), model) if has_messages else "",
            file_name=f"chat_{ts}.txt",
            mime="text/plain",
            disabled=not has_messages,
            use_container_width=True,
        )
    with col_csv:
        st.download_button(
            label="CSV",
            data=_export_csv(st.session_state.get("messages", []), model) if has_messages else "",
            file_name=f"chat_{ts}.csv",
            mime="text/csv",
            disabled=not has_messages,
            use_container_width=True,
        )
    with col_json:
        st.download_button(
            label="JSON",
            data=_export_json(st.session_state.get("messages", []), model) if has_messages else "",
            file_name=f"chat_{ts}.json",
            mime="application/json",
            disabled=not has_messages,
            use_container_width=True,
        )
```

> 대화 내용이 없을 때는 버튼이 비활성화(disabled)됩니다.
> `datetime` import가 아직 없다면 파일 상단에 추가하세요: `from datetime import datetime`

---

## M12-5. 질문·답변 이벤트 로깅

`streamlit_app.py`의 질문 처리 블록에 로그 호출을 추가하세요.

```python
from src.utils.logger import (
    log_event,
    EVENT_APP_ACCESS, EVENT_LOGIN_SUCCESS, EVENT_LOGIN_FAILURE,
    EVENT_QUESTION, EVENT_ANSWER, EVENT_EXPORT,
)

# 질문 입력 시
if question and pipeline is not None:
    log_event(EVENT_QUESTION, session_id, {
        "question": question,
        "model": model,
        "top_k": top_k,
        "temperature": temperature,
    })
    ...

    # 답변 생성 완료 후
    answer, chunks, timing = _stream_answer(pipeline, question, temperature)
    log_event(EVENT_ANSWER, session_id, {
        "model": model,
        "question_preview": question[:100],
        "answer_preview": answer[:100],
        "retrieve_ms": round(timing["retrieve_ms"]),
        "llm_ms": round(timing["llm_ms"]),
        "total_ms": round(timing["total_ms"]),
        "chunk_count": len(chunks),
        "sources": [
            {
                "doc_short": c.metadata.get("doc_short"),
                "page_start": c.metadata.get("page_start"),
                "page_end": c.metadata.get("page_end"),
            }
            for c in chunks[:3]
        ],
    })
```

내보내기 버튼 클릭 시 로그를 남기려면 `st.download_button`의 `on_click` 콜백을 사용하세요:

```python
def _log_export(fmt: str, session_id: str, model: str, turn_count: int):
    log_event(EVENT_EXPORT, session_id, {
        "format": fmt,
        "model": model,
        "turn_count": turn_count,
    })
```

> ⚠️ Streamlit의 `st.download_button`은 클릭 시 전체 페이지를 리런하므로,
> on_click 콜백 내에서 session_state의 값을 사용해야 합니다.
> 구현이 복잡해지면 다운로드 후 별도 "내보내기 기록" 버튼을 두어도 됩니다.

---

## 섹션 1 — 파일별 변경 요약

| 파일 | 변경 유형 | 내용 |
|------|---------|------|
| `src/utils/__init__.py` | 신규 | 빈 파일 |
| `src/utils/logger.py` | 신규 | JSONL 감사 로그 모듈 |
| `src/config.py` | 수정 | `APP_PASSWORD`, `LOG_DIR` 추가 |
| `.env` | 수정 | `APP_PASSWORD`, `LOG_DIR` 추가 |
| `.env.example` | 수정 | 동일 |
| `.gitignore` | 수정 | `logs/` 추가 |
| `src/ui/streamlit_app.py` | 수정 | 인증 게이트, 내보내기, 로그 호출 |

---

## 섹션 2 — 로그 파일 형식 예시

```jsonl
{"timestamp": "2026-05-04T08:00:01Z", "event": "APP_ACCESS",     "session_id": "a1b2c3d4", "details": {}}
{"timestamp": "2026-05-04T08:00:05Z", "event": "LOGIN_SUCCESS",   "session_id": "a1b2c3d4", "details": {}}
{"timestamp": "2026-05-04T08:00:20Z", "event": "QUESTION",        "session_id": "a1b2c3d4", "details": {"question": "AA157은 어떤 기관의 초진 진찰료인가요?", "model": "exaone3.5:7.8b", "top_k": 8, "temperature": 0.2}}
{"timestamp": "2026-05-04T08:00:35Z", "event": "ANSWER",          "session_id": "a1b2c3d4", "details": {"model": "exaone3.5:7.8b", "retrieve_ms": 312, "llm_ms": 14200, "total_ms": 14512, "chunk_count": 8}}
{"timestamp": "2026-05-04T08:01:10Z", "event": "LOGIN_FAILURE",   "session_id": "e5f6g7h8", "details": {"reason": "wrong_password"}}
{"timestamp": "2026-05-04T08:05:00Z", "event": "EXPORT",          "session_id": "a1b2c3d4", "details": {"format": "csv", "model": "exaone3.5:7.8b", "turn_count": 3}}
```

---

## 섹션 3 — 구현 순서

```
M12-1 (logger.py)  →  M12-2 (config + .env)  →  M12-3 (인증 게이트)
                                               →  M12-4 (내보내기)
                                               →  M12-5 (이벤트 로그)
```

M12-1과 M12-2는 나머지 모든 작업의 선행 조건입니다.
M12-3·M12-4·M12-5는 M12-2 완료 후 병렬 구현 가능합니다.

---

## 섹션 4 — 완료 검증

```bash
# 1. pytest 통과 확인
pytest

# 2. Streamlit 실행 후 수동 확인
streamlit run src/ui/streamlit_app.py
```

**수동 확인 체크리스트:**
- [ ] 비밀번호 입력 화면이 먼저 표시된다
- [ ] 틀린 비밀번호 입력 시 에러 메시지와 함께 `logs/` 파일에 `LOGIN_FAILURE` 이벤트가 기록된다
- [ ] 올바른 비밀번호 입력 후 채팅 화면으로 전환된다
- [ ] 사이드바에 TXT·CSV·JSON 버튼이 표시된다 (대화 없으면 비활성화)
- [ ] 질문 후 버튼이 활성화되고, 클릭 시 파일이 다운로드된다
- [ ] `logs/chat_YYYY-MM-DD.jsonl`에 QUESTION, ANSWER 이벤트가 기록된다
- [ ] `APP_PASSWORD=` (빈 값)으로 설정 시 비밀번호 화면 없이 바로 채팅이 열린다

---

## 섹션 5 — 사용자(범준 님)가 직접 해야 하는 작업

> Codex 구현 완료 후 아래를 직접 수행하세요.

1. **`.env` 비밀번호 설정**: `APP_PASSWORD=insure1234` 부분을 실제 사용할 비밀번호로 변경하세요. `.env` 파일은 `.gitignore`에 포함되어야 합니다.

2. **비밀번호 공유**: 임직원에게 비밀번호를 별도 채널(메신저, 이메일 등)로 전달하세요. 챗봇 화면에 비밀번호 힌트를 남기지 마세요.

3. **로그 접근 권한**: `logs/` 디렉터리는 서버 관리자만 접근하도록 권한을 설정하세요. 대화 내용이 포함되므로 개인정보 보호 정책을 확인하세요.

---

## 섹션 6 — Codex 완료 보고서 형식

```
## M12 완료 보고

### 변경된 파일
- [파일 경로]: [변경 내용]

### 구현된 기능
- [ ] 비밀번호 인증 게이트
- [ ] 로그인 성공/실패 로깅
- [ ] 접속 로깅 (APP_ACCESS)
- [ ] 질문/답변 이벤트 로깅
- [ ] TXT 내보내기
- [ ] CSV 내보내기
- [ ] JSON 내보내기

### pytest 결과
[통과 수] passed

### 수동 확인 결과
[체크리스트 항목별 결과]

### 이슈 및 특이사항
[없으면 "없음"]
```
```

---

*이 명세는 기획자가 `src/ui/streamlit_app.py`, `src/config.py`, `.env.example` 현재 코드를 검토한 후 작성하였습니다.*
