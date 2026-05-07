# Codex 개발자 명세 — M15 · M16 · M17 (역할 인증 · OpenAI 통합 · 클라우드 배포 준비)

> **작성:** 기획자
> **작성일:** 2026-05-06
> **기반 상태:** M14 완료 (카테고리 필터·퀵 코드·약관 정형 검색·PDF 미리보기 적용된 Streamlit 앱)
> **참고:** [15_IMPROVEMENT_PLAN_v3.md](./15_IMPROVEMENT_PLAN_v3.md)

---

## 섹션 0 — Codex에게 전달할 프롬프트 (복사 붙여넣기용)

```
당신은 시니어 Python 개발자입니다.
"보험 문서 RAG 챗봇" 프로젝트는 현재 M14까지 완료된 상태입니다.
다음 세 마일스톤(M15·M16·M17)을 본 명세에 따라 순서대로 구현하세요.

원칙:
1. 명세 외 항목(사용자 삭제, SSO, 세션 만료, 클라우드 로그 영속 등)은 임의 구현 금지.
2. M15 → M16 → M17 순서로 작업하고, 각 마일스톤 완료 시 PR을 분리하여 자가 검증 결과를 보고하세요.
3. 기존 동작(일반 질의·퀵 코드·약관 정형·PDF 미리보기·내보내기·일반 모드 검색)은 절대 깨지면 안 됩니다.
   회귀 테스트: pytest 전체 통과 + Streamlit 수동 확인 체크리스트 통과.
4. 모호함 해결 순서: (a) 본 명세, (b) 기존 코드 컨벤션, (c) 가장 단순한 해법.
5. 신규/수정 모듈은 단위 테스트와 함께 제출. UI 코드는 헬퍼 함수로 분리해 테스트 가능하게.
6. 한국어 docstring/주석 일관 유지. 외부 사용자 노출 메시지는 한국어.
7. 외부 네트워크 호출(OpenAI)은 단위 테스트에서 mock 처리. 실제 API 키 사용 금지.
8. 작업 디렉토리: 본 명세 파일이 위치한 프로젝트 루트.

산출물: 본 문서 섹션 1(M15) · 섹션 2(M16) · 섹션 3(M17)의 모든 변경.
시작 전 다음 파일을 먼저 읽고 코드 컨벤션을 파악하세요:
- src/ui/streamlit_app.py
- src/llm/ollama_client.py
- src/utils/logger.py
- src/config.py
- requirements.txt
- .env.example
```

---

## 섹션 1 — M15: 역할 기반 인증 + 관리자 대시보드

### 1.1 사용자 저장소

#### 1.1.1 `users.json` 스키마 (프로젝트 루트, gitignore)

```json
{
  "version": 1,
  "users": [
    {
      "username": "admin",
      "password_hash": "$pbkdf2-sha256$...",
      "role": "admin",
      "display_name": "시스템 관리자",
      "created_at": "2026-05-06T00:00:00Z",
      "password_updated_at": "2026-05-06T00:00:00Z"
    },
    {
      "username": "employee01",
      "password_hash": "$pbkdf2-sha256$...",
      "role": "employee",
      "display_name": "직원 1",
      "created_at": "2026-05-06T00:00:00Z",
      "password_updated_at": "2026-05-06T00:00:00Z"
    }
  ]
}
```

규칙:
- `username`: 영숫자 + `_`, 3~32자 (정규식 `^[a-zA-Z0-9_]{3,32}$`)
- `role`: `"employee"` | `"admin"` 만 허용
- `password_hash`: passlib `pbkdf2_sha256` 해시 (bcrypt 대신, 순수 Python, 의존성 단순)
- `display_name`: 1~64자
- 시각은 UTC ISO8601

`.gitignore`에 `users.json` 추가.

#### 1.1.2 새 모듈 `src/auth/__init__.py` (빈 파일) 및 `src/auth/users.py`

```python
"""사용자 저장소와 비밀번호 검증."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from passlib.hash import pbkdf2_sha256

from src import config

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
PASSWORD_MIN_LEN = 8
ROLE_EMPLOYEE = "employee"
ROLE_ADMIN = "admin"
VALID_ROLES = {ROLE_EMPLOYEE, ROLE_ADMIN}


@dataclass
class User:
    username: str
    password_hash: str
    role: str
    display_name: str
    created_at: str
    password_updated_at: str

    def public_dict(self) -> dict:
        """비밀번호 해시를 제외한 공개 표현."""
        return {k: v for k, v in asdict(self).items() if k != "password_hash"}


class UserStoreError(Exception):
    """사용자 저장소 오류."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _users_path() -> Path:
    return Path(os.getenv("USERS_JSON_PATH", str(config.ROOT_DIR / "users.json")))


def _load_raw() -> dict:
    path = _users_path()
    if not path.exists():
        return {"version": 1, "users": []}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(data: dict) -> None:
    path = _users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except (PermissionError, OSError):
        pass  # 윈도우/일부 FS에서는 무시


def list_users() -> list[User]:
    raw = _load_raw()
    return [User(**u) for u in raw.get("users", [])]


def get_user(username: str) -> User | None:
    return next((u for u in list_users() if u.username == username), None)


def validate_password_strength(password: str) -> None:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LEN:
        raise UserStoreError(f"비밀번호는 최소 {PASSWORD_MIN_LEN}자 이상이어야 합니다.")


def add_user(username: str, password: str, role: str,
             display_name: str | None = None) -> User:
    if not USERNAME_RE.match(username or ""):
        raise UserStoreError("사용자명은 영문/숫자/_ 조합 3~32자여야 합니다.")
    if role not in VALID_ROLES:
        raise UserStoreError(f"role은 {VALID_ROLES} 중 하나여야 합니다.")
    validate_password_strength(password)
    if get_user(username) is not None:
        raise UserStoreError(f"이미 존재하는 사용자입니다: {username}")

    user = User(
        username=username,
        password_hash=pbkdf2_sha256.hash(password),
        role=role,
        display_name=display_name or username,
        created_at=_now_iso(),
        password_updated_at=_now_iso(),
    )
    raw = _load_raw()
    raw["users"].append(asdict(user))
    _save_raw(raw)
    return user


def reset_password(username: str, new_password: str) -> None:
    validate_password_strength(new_password)
    raw = _load_raw()
    for entry in raw["users"]:
        if entry["username"] == username:
            entry["password_hash"] = pbkdf2_sha256.hash(new_password)
            entry["password_updated_at"] = _now_iso()
            _save_raw(raw)
            return
    raise UserStoreError(f"사용자를 찾을 수 없습니다: {username}")


def authenticate(username: str, password: str) -> User | None:
    user = get_user(username)
    if user is None:
        return None
    if pbkdf2_sha256.verify(password, user.password_hash):
        return user
    return None


def has_admin() -> bool:
    return any(u.role == ROLE_ADMIN for u in list_users())
```

#### 1.1.3 `scripts/manage_users.py` 신규

```python
"""사용자 관리 CLI.

사용법:
  python scripts/manage_users.py init                      # 첫 admin 부트스트랩
  python scripts/manage_users.py add <username> <role>     # role: employee | admin
  python scripts/manage_users.py reset <username>          # 비밀번호 재설정
  python scripts/manage_users.py list
"""

from __future__ import annotations

import argparse
import getpass
import sys

from src.auth import users as user_store


def _prompt_password(label: str = "비밀번호") -> str:
    while True:
        pw = getpass.getpass(f"{label}: ")
        confirm = getpass.getpass(f"{label} 확인: ")
        if pw != confirm:
            print("비밀번호가 일치하지 않습니다. 다시 입력하세요.")
            continue
        try:
            user_store.validate_password_strength(pw)
        except user_store.UserStoreError as exc:
            print(f"  ! {exc}")
            continue
        return pw


def cmd_init(args) -> int:
    if user_store.has_admin():
        print("이미 관리자 계정이 존재합니다. add 명령을 사용하세요.")
        return 1
    print("첫 시스템 관리자 계정을 생성합니다.")
    username = input("관리자 사용자명 (영문/숫자/_ 3~32자): ").strip()
    display = input(f"표시 이름 [{username}]: ").strip() or username
    pw = _prompt_password()
    user_store.add_user(username, pw, role=user_store.ROLE_ADMIN, display_name=display)
    print(f"관리자 '{username}'을(를) 생성했습니다.")
    return 0


def cmd_add(args) -> int:
    role = args.role
    username = args.username
    display = input(f"표시 이름 [{username}]: ").strip() or username
    pw = _prompt_password()
    user_store.add_user(username, pw, role=role, display_name=display)
    print(f"사용자 '{username}' ({role})을(를) 생성했습니다.")
    return 0


def cmd_reset(args) -> int:
    pw = _prompt_password("새 비밀번호")
    user_store.reset_password(args.username, pw)
    print(f"'{args.username}' 비밀번호를 재설정했습니다.")
    return 0


def cmd_list(args) -> int:
    rows = user_store.list_users()
    if not rows:
        print("(등록된 사용자 없음)")
        return 0
    for u in rows:
        print(f"- {u.username} | {u.role} | {u.display_name} | created={u.created_at}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="사용자 관리 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")

    p_add = sub.add_parser("add")
    p_add.add_argument("username")
    p_add.add_argument("role", choices=[user_store.ROLE_EMPLOYEE, user_store.ROLE_ADMIN])

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("username")

    sub.add_parser("list")

    args = parser.parse_args(argv)
    return {"init": cmd_init, "add": cmd_add, "reset": cmd_reset, "list": cmd_list}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

### 1.2 인증 게이트 교체

#### 1.2.1 `src/ui/streamlit_app.py` 의 `_check_auth` 재작성

```python
from src.auth import users as user_store
from src.auth.users import ROLE_ADMIN, ROLE_EMPLOYEE


def _check_auth(session_id: str) -> bool:
    """ID·비밀번호 인증. 통과 시 session_state에 user 정보를 채운다."""

    if st.session_state.get("authenticated"):
        return True

    if not user_store.has_admin():
        st.title("보험 고시 문서 RAG 챗봇")
        st.error(
            "관리자 계정이 설정되지 않았습니다.\n"
            "터미널에서 `python scripts/manage_users.py init`을 실행해 첫 관리자를 생성하세요."
        )
        return False

    st.title("보험 고시 문서 RAG 챗봇")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔐 임직원 전용 서비스")
        username = st.text_input("사용자명", placeholder="사용자명")
        password = st.text_input("비밀번호", type="password", placeholder="비밀번호")
        if st.button("로그인", use_container_width=True, type="primary"):
            user = user_store.authenticate(username.strip(), password)
            if user is None:
                st.error("사용자명 또는 비밀번호가 올바르지 않습니다.")
                log_event(EVENT_LOGIN_FAILURE, session_id,
                          {"username_attempt": username[:32], "reason": "invalid_credentials"})
                return False
            st.session_state.authenticated = True
            st.session_state.user_id = user.username
            st.session_state.user_role = user.role
            st.session_state.user_display = user.display_name
            log_event(EVENT_LOGIN_SUCCESS, session_id,
                      {"user_id": user.username, "role": user.role})
            st.rerun()
    return False
```

`config.APP_PASSWORD` 의존성 제거. `APP_PASSWORD` 환경변수는 deprecation 안내만 README에 남기고 코드에서는 참조하지 않는다.

#### 1.2.2 모든 `log_event` 호출에 user 정보 자동 부착

`src/utils/logger.py`를 다음과 같이 확장:

```python
# 기존 log_event를 그대로 두고, 상위 헬퍼 추가
def log_event_for_user(event: str, session_id: str,
                       user_id: str | None, role: str | None,
                       details: dict | None = None) -> None:
    """user_id·role을 details에 자동 부착해 기록한다."""
    enriched = dict(details or {})
    enriched.setdefault("user_id", user_id)
    enriched.setdefault("role", role)
    log_event(event, session_id, enriched)
```

`streamlit_app.py`에서 다음 헬퍼로 `log_event` 호출을 일괄 교체:

```python
def _log(event: str, details: dict | None = None) -> None:
    """현재 세션의 user_id·role을 details에 부착하여 로깅."""
    log_event_for_user(
        event,
        st.session_state.get("session_id", ""),
        st.session_state.get("user_id"),
        st.session_state.get("user_role"),
        details,
    )
```

기존 `log_event(EVENT_QUESTION, session_id, {...})` 호출 → `_log(EVENT_QUESTION, {...})` 형태로 일괄 치환.

새 이벤트 상수 `src/utils/logger.py`에 추가:
```python
EVENT_LOGOUT      = "LOGOUT"
EVENT_USER_CREATE = "USER_CREATE"
EVENT_USER_RESET  = "USER_RESET"
EVENT_ADMIN_VIEW  = "ADMIN_VIEW"
```

### 1.3 사이드바 사용자 영역

`with st.sidebar:` 상단에 사용자 정보 박스 추가:

```python
display = st.session_state.get("user_display", "")
role = st.session_state.get("user_role", "")
role_label = "관리자" if role == ROLE_ADMIN else "직원"
st.markdown(f"**{display}** · _{role_label}_")
if st.button("로그아웃", use_container_width=True):
    _log(EVENT_LOGOUT)
    for key in ("authenticated", "user_id", "user_role", "user_display", "messages"):
        st.session_state.pop(key, None)
    st.rerun()
st.divider()
```

### 1.4 관리자 페이지

#### 1.4.1 진입 방식

사이드바에 라디오 추가 (admin 전용):
```python
if role == ROLE_ADMIN:
    page = st.radio("페이지", ["챗봇", "관리자"], horizontal=True, key="page")
else:
    page = "챗봇"
```

`page == "관리자"`일 때 본문에서 `render_admin_page()` 호출, 챗봇 UI는 렌더하지 않는다.

#### 1.4.2 새 모듈 `src/ui/admin_page.py`

다음 4개 탭으로 구성:

| 탭 | 기능 |
|---|---|
| 로그 조회 | 날짜/사용자/이벤트 필터 + 표 |
| 통계 | 사용자별·일별·이벤트별 집계 |
| 사용자 관리 | 목록 / 추가 / 비밀번호 리셋 |
| 시스템 상태 | Ollama 연결, 인덱스 크기, 모델 목록 |

```python
"""관리자 전용 페이지."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from src import config
from src.auth import users as user_store
from src.auth.users import ROLE_ADMIN, ROLE_EMPLOYEE
from src.utils.logger import (
    EVENT_USER_CREATE, EVENT_USER_RESET, EVENT_ADMIN_VIEW,
)


LOG_DIR = Path(config.LOG_DIR)


def _read_logs(date_from: datetime, date_to: datetime) -> list[dict]:
    """logs/chat_*.jsonl 파일들을 읽어 기간 안의 이벤트만 반환."""
    events: list[dict] = []
    if not LOG_DIR.exists():
        return events
    for log_file in sorted(LOG_DIR.glob("chat_*.jsonl*")):
        try:
            with log_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("timestamp")
                    if not ts:
                        continue
                    try:
                        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if date_from <= when <= date_to:
                        events.append(rec)
        except OSError:
            continue
    return events


def _logs_to_csv(events: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["timestamp", "event", "session_id", "user_id", "role", "details"])
    for e in events:
        d = e.get("details", {}) or {}
        writer.writerow([
            e.get("timestamp", ""),
            e.get("event", ""),
            e.get("session_id", ""),
            d.get("user_id", ""),
            d.get("role", ""),
            json.dumps({k: v for k, v in d.items() if k not in ("user_id", "role")},
                       ensure_ascii=False),
        ])
    return out.getvalue()


def _tab_logs(_log) -> None:
    st.subheader("로그 조회")
    today = datetime.now(timezone.utc).date()
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        d_from = st.date_input("시작일", value=today - timedelta(days=7))
    with col_b:
        d_to = st.date_input("종료일", value=today)
    with col_c:
        usernames = sorted({u.username for u in user_store.list_users()})
        user_filter = st.multiselect("사용자", usernames, default=[])
    event_types = st.multiselect("이벤트 유형", [
        "APP_ACCESS", "LOGIN_SUCCESS", "LOGIN_FAILURE", "LOGOUT",
        "QUESTION", "ANSWER", "EXPORT",
        "USER_CREATE", "USER_RESET", "ADMIN_VIEW",
    ], default=[])

    dt_from = datetime.combine(d_from, datetime.min.time(), tzinfo=timezone.utc)
    dt_to = datetime.combine(d_to, datetime.max.time(), tzinfo=timezone.utc)
    events = _read_logs(dt_from, dt_to)
    if user_filter:
        events = [e for e in events if (e.get("details") or {}).get("user_id") in user_filter]
    if event_types:
        events = [e for e in events if e.get("event") in event_types]

    st.caption(f"총 {len(events)}건")
    rows = [
        {
            "시각": e.get("timestamp", ""),
            "이벤트": e.get("event", ""),
            "사용자": (e.get("details") or {}).get("user_id", ""),
            "역할": (e.get("details") or {}).get("role", ""),
            "세션": e.get("session_id", ""),
            "상세": json.dumps((e.get("details") or {}),
                              ensure_ascii=False)[:200],
        }
        for e in events[-500:]
    ]
    st.dataframe(rows, use_container_width=True, height=400)

    csv_text = _logs_to_csv(events)
    st.download_button("CSV 다운로드", data=csv_text,
                       file_name=f"logs_{d_from}_{d_to}.csv",
                       mime="text/csv")


def _tab_stats(_log) -> None:
    st.subheader("통계")
    today = datetime.now(timezone.utc).date()
    dt_from = datetime.combine(today - timedelta(days=30),
                               datetime.min.time(), tzinfo=timezone.utc)
    dt_to = datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc)
    events = _read_logs(dt_from, dt_to)

    questions = [e for e in events if e.get("event") == "QUESTION"]
    answers = [e for e in events if e.get("event") == "ANSWER"]

    col1, col2, col3 = st.columns(3)
    col1.metric("최근 30일 질문", f"{len(questions):,}")
    col2.metric("응답", f"{len(answers):,}")
    durations = [
        (e.get("details") or {}).get("timing", {}).get("total_ms", 0)
        for e in answers
    ]
    avg = sum(durations) / len(durations) / 1000 if durations else 0
    col3.metric("평균 응답(초)", f"{avg:.1f}")

    # 사용자별
    by_user: dict[str, int] = {}
    for e in questions:
        uid = (e.get("details") or {}).get("user_id") or "(unknown)"
        by_user[uid] = by_user.get(uid, 0) + 1
    st.markdown("**사용자별 질문 수**")
    st.bar_chart(by_user)

    # 모드별
    by_mode: dict[str, int] = {}
    for e in questions:
        mode = (e.get("details") or {}).get("mode") or "general"
        by_mode[mode] = by_mode.get(mode, 0) + 1
    st.markdown("**검색 모드 분포**")
    st.bar_chart(by_mode)

    # 모델별 (M16 적용 후)
    by_model: dict[str, int] = {}
    for e in answers:
        m = (e.get("details") or {}).get("model") or "?"
        by_model[m] = by_model.get(m, 0) + 1
    st.markdown("**모델별 응답 수**")
    st.bar_chart(by_model)


def _tab_users(_log) -> None:
    st.subheader("사용자 관리")
    users = user_store.list_users()
    st.dataframe(
        [{"사용자명": u.username, "역할": u.role, "표시 이름": u.display_name,
          "생성일": u.created_at, "비밀번호 갱신": u.password_updated_at}
         for u in users],
        use_container_width=True,
    )

    with st.expander("➕ 사용자 추가"):
        with st.form("add_user_form"):
            new_username = st.text_input("사용자명 (영숫자_, 3~32자)")
            new_display = st.text_input("표시 이름")
            new_role = st.selectbox("역할", [ROLE_EMPLOYEE, ROLE_ADMIN])
            new_pw = st.text_input("비밀번호 (8자 이상)", type="password")
            submit = st.form_submit_button("추가", type="primary")
        if submit:
            try:
                user_store.add_user(new_username.strip(), new_pw,
                                    role=new_role,
                                    display_name=new_display.strip() or None)
                _log(EVENT_USER_CREATE, {"target_username": new_username, "target_role": new_role})
                st.success(f"사용자 '{new_username}' 추가 완료")
                st.rerun()
            except user_store.UserStoreError as exc:
                st.error(str(exc))

    with st.expander("🔑 비밀번호 리셋"):
        with st.form("reset_pw_form"):
            target = st.selectbox("대상 사용자", [u.username for u in users])
            new_pw2 = st.text_input("새 비밀번호 (8자 이상)", type="password")
            submit2 = st.form_submit_button("리셋", type="primary")
        if submit2:
            try:
                user_store.reset_password(target, new_pw2)
                _log(EVENT_USER_RESET, {"target_username": target})
                st.success(f"'{target}' 비밀번호 리셋 완료")
            except user_store.UserStoreError as exc:
                st.error(str(exc))


def _tab_system(_log) -> None:
    st.subheader("시스템 상태")
    from src.llm.factory import build_llm  # M16 의존
    from src.llm.factory import is_ollama_allowed, list_available_models

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**인덱스**")
        st.write("Chroma 디렉토리:", str(config.CHROMA_DIR), "·",
                 "있음" if config.CHROMA_DIR.exists() else "없음")
        st.write("BM25 파일:", str(config.BM25_PATH), "·",
                 "있음" if config.BM25_PATH.exists() else "없음")
    with col2:
        st.markdown("**LLM**")
        st.write("Ollama 허용:", is_ollama_allowed())
        try:
            models = list_available_models()
            st.write("선택 가능 모델:", models)
        except Exception as exc:  # pragma: no cover
            st.warning(f"모델 목록 조회 실패: {exc}")


def render_admin_page(_log) -> None:
    """관리자 페이지 본문."""
    _log(EVENT_ADMIN_VIEW)
    st.title("관리자 페이지")
    tabs = st.tabs(["로그 조회", "통계", "사용자 관리", "시스템 상태"])
    with tabs[0]:
        _tab_logs(_log)
    with tabs[1]:
        _tab_stats(_log)
    with tabs[2]:
        _tab_users(_log)
    with tabs[3]:
        _tab_system(_log)
```

#### 1.4.3 권한 가드

`render_admin_page` 호출 직전, 그리고 모든 admin 액션 직전에 다음을 검사:

```python
if st.session_state.get("user_role") != ROLE_ADMIN:
    st.error("관리자 권한이 필요합니다.")
    st.stop()
```

### 1.5 의존성 추가

`requirements.txt`에 추가:
```
passlib>=1.7.4
```

### 1.6 M15 단위 테스트

| 파일 | 검사 |
|---|---|
| `tests/test_auth_users.py` (신규) | `add_user`/`get_user`/`authenticate`/`reset_password`/`validate_password_strength` 정상·예외 케이스, `users.json` 라운드트립 |
| `tests/test_admin_page.py` (신규) | `_read_logs`가 기간 필터·이벤트 유형 필터 정상 동작 (임시 디렉토리 fixture), `_logs_to_csv` 헤더·필드 |
| `tests/test_streamlit_app.py` (확장) | 로그인 게이트가 `users.json`에 admin이 없을 때 에러를 띄우는지 |

### 1.7 M15 자가 검증

```bash
pytest -q
python scripts/manage_users.py init      # 부트스트랩 (수동)
python scripts/manage_users.py add emp01 employee
streamlit run src/ui/streamlit_app.py
```

수동 체크:
- [ ] users.json이 없거나 admin이 없을 때 로그인 화면에 안내 표시
- [ ] init으로 admin 생성 → 해당 ID/PW로 로그인 성공
- [ ] 잘못된 PW 5회 → 로그에 LOGIN_FAILURE 5건 (user_id는 시도값)
- [ ] employee 로그인 시 사이드바에 "관리자" 페이지 라디오 미노출
- [ ] admin 로그인 시 "관리자" 페이지 진입 가능 → 4개 탭 표시
- [ ] 로그 조회 탭에 최근 7일 이벤트 표시, 사용자/이벤트 필터 동작, CSV 다운로드 정상
- [ ] 사용자 추가 → 즉시 목록 반영, 새 계정으로 로그인 가능
- [ ] 비밀번호 리셋 → 신 비밀번호로 로그인 가능
- [ ] 모든 QUESTION/ANSWER 로그에 `details.user_id`·`details.role`이 들어감
- [ ] 로그아웃 버튼 → 세션 초기화, 로그인 화면 복귀

---

## 섹션 2 — M16: LLM 추상화 + OpenAI 통합

### 2.1 LLM 추상화

#### 2.1.1 `src/llm/base.py` 신규

```python
"""LLM 클라이언트 공통 프로토콜."""

from __future__ import annotations

from typing import Iterator, Protocol


class LLMClient(Protocol):
    """OllamaClient·OpenAIClient가 모두 따르는 인터페이스."""

    model: str
    provider: str  # "ollama" | "openai"

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.2,
                 num_ctx: int | None = None) -> str: ...

    def generate_stream(self, prompt: str, system: str = "",
                        temperature: float = 0.2) -> Iterator[str]: ...

    def list_models(self) -> list[str]: ...
```

기존 `OllamaClient`에 `provider = "ollama"` 클래스 변수를 추가.

#### 2.1.2 `src/llm/openai_client.py` 신규

```python
"""OpenAI Chat Completions 클라이언트.

본 모듈은 외부 네트워크 호출을 수행한다. 단위 테스트에서는 mock을 사용해야 한다.
"""

from __future__ import annotations

import json as jsonlib
import os
from typing import Iterator

import requests

from src import config

OPENAI_BASE = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_TIMEOUT = 60


class OpenAIClient:
    provider = "openai"

    def __init__(self, model: str, api_key: str | None = None,
                 max_tokens: int | None = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.max_tokens = max_tokens or config.OPENAI_MAX_TOKENS
        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하거나 "
                "관리자에게 문의하세요."
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, prompt: str, system: str, temperature: float,
                 stream: bool) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.2,
                 num_ctx: int | None = None) -> str:
        # num_ctx는 OpenAI에는 의미 없음 — 시그니처 호환만 유지
        try:
            response = requests.post(
                f"{OPENAI_BASE}/chat/completions",
                headers=self._headers(),
                json=self._payload(prompt, system, temperature, stream=False),
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"OpenAI 호출 실패: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenAI 응답 오류(status={response.status_code}): {response.text[:300]}"
            )
        data = response.json()
        usage = data.get("usage", {})
        # 토큰 사용량을 호출자가 회수할 수 있도록 마지막 호출 정보 보관
        self.last_usage = usage
        return data["choices"][0]["message"]["content"].strip()

    def generate_stream(self, prompt: str, system: str = "",
                        temperature: float = 0.2) -> Iterator[str]:
        with requests.post(
            f"{OPENAI_BASE}/chat/completions",
            headers=self._headers(),
            json=self._payload(prompt, system, temperature, stream=True),
            stream=True,
            timeout=DEFAULT_TIMEOUT,
        ) as response:
            if response.status_code >= 400:
                raise RuntimeError(
                    f"OpenAI 스트림 오류(status={response.status_code})"
                )
            for raw in response.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                if payload.strip() == "[DONE]":
                    break
                try:
                    data = jsonlib.loads(payload)
                except jsonlib.JSONDecodeError:
                    continue
                delta = data.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content") or ""
                if token:
                    yield token

    def list_models(self) -> list[str]:
        # 정적 후보 반환 (실제 API call로 동적 조회는 비용 발생)
        return list(config.OPENAI_CANDIDATE_MODELS)
```

#### 2.1.3 `src/llm/factory.py` 신규

```python
"""모델 ID 패턴으로 적절한 LLMClient를 만든다."""

from __future__ import annotations

import os

from src import config
from src.llm.base import LLMClient
from src.llm.ollama_client import OllamaClient


def is_openai_model(model: str) -> bool:
    return model.startswith("gpt-") or model.startswith("openai:")


def is_ollama_allowed() -> bool:
    return os.getenv("ALLOW_OLLAMA", "true").lower() == "true"


def list_available_models() -> dict[str, list[str]]:
    """그룹별 모델 후보를 반환한다.

    Returns:
        {"local": [...], "cloud": [...]}
        - local: Ollama 후보 (ALLOW_OLLAMA=false면 빈 리스트)
        - cloud: OpenAI 후보 (OPENAI_API_KEY 미설정이면 빈 리스트)
    """
    local: list[str] = []
    if is_ollama_allowed():
        try:
            installed = set(OllamaClient(config.OLLAMA_HOST, config.OLLAMA_MODEL).list_models())
            local = [m for m in config.OLLAMA_CANDIDATE_MODELS if m in installed]
            if config.OLLAMA_MODEL in installed and config.OLLAMA_MODEL not in local:
                local.insert(0, config.OLLAMA_MODEL)
        except Exception:
            local = []
    cloud: list[str] = []
    if os.getenv("OPENAI_API_KEY"):
        cloud = list(config.OPENAI_CANDIDATE_MODELS)
    return {"local": local, "cloud": cloud}


def build_llm(model: str) -> LLMClient:
    """모델 ID에 맞는 LLMClient를 생성한다."""
    if is_openai_model(model):
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OpenAI 모델을 선택했지만 OPENAI_API_KEY가 설정되지 않았습니다."
            )
        from src.llm.openai_client import OpenAIClient
        normalized = model.removeprefix("openai:")
        return OpenAIClient(normalized)
    if not is_ollama_allowed():
        raise RuntimeError(
            "현재 환경에서는 로컬(Ollama) 모델 사용이 비활성화되어 있습니다. "
            "OpenAI 모델을 선택해 주세요."
        )
    return OllamaClient(config.OLLAMA_HOST, model)
```

### 2.2 설정 추가 (`src/config.py`)

```python
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_DEFAULT_MODEL: str = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")
OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "1500"))
OPENAI_CANDIDATE_MODELS: list[str] = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
]
```

`.env.example`에 다음 블록 추가 (실제 키는 사용자가 직접 입력):

```
# === OpenAI (선택) ===
# OPENAI_API_KEY=<OPENAI_API_KEY>
# OPENAI_DEFAULT_MODEL=gpt-4o-mini
# OPENAI_MAX_TOKENS=1500
# === 클라우드 게시 가드 ===
# ALLOW_OLLAMA=true        # 클라우드 환경에서 false로 두면 Ollama 모델 비활성
```

### 2.3 Streamlit UI 모델 선택 통합

`streamlit_app.py`의 기존 `_get_available_models`를 다음으로 교체:

```python
from src.llm.factory import build_llm, list_available_models, is_openai_model


@st.cache_data(ttl=30)
def _get_available_models_grouped() -> dict[str, list[str]]:
    return list_available_models()


def _select_model_widget() -> str:
    grouped = _get_available_models_grouped()
    options: list[str] = []
    labels: dict[str, str] = {}
    for m in grouped["local"]:
        options.append(m)
        labels[m] = f"Local · Ollama · {m}"
    for m in grouped["cloud"]:
        options.append(m)
        labels[m] = f"Cloud · OpenAI · {m}"
    if not options:
        st.error("사용 가능한 LLM 모델이 없습니다. .env의 OPENAI_API_KEY 설정 또는 Ollama 설치를 확인하세요.")
        st.stop()
    default_index = 0
    if config.OLLAMA_MODEL in options:
        default_index = options.index(config.OLLAMA_MODEL)
    elif config.OPENAI_DEFAULT_MODEL in options:
        default_index = options.index(config.OPENAI_DEFAULT_MODEL)
    selected = st.selectbox(
        "LLM 모델",
        options,
        index=default_index,
        format_func=lambda m: labels.get(m, m),
    )
    if is_openai_model(selected):
        st.info("⚠ OpenAI 모델은 외부 서버를 호출합니다. 입력된 질문과 검색된 청크가 OpenAI로 전송됩니다.")
    return selected
```

기존 `_load_llm`을 `factory.build_llm(model)`으로 대체:
```python
@st.cache_resource
def _load_llm(model: str):
    return build_llm(model)
```

LLM 호출 부분은 그대로 두되, `OllamaClient` 타입 단언을 제거하고 `LLMClient` 프로토콜로 처리.

### 2.4 토큰 사용량 로깅

`EVENT_ANSWER` 로그에 `provider`·`token_usage` 필드 추가:

```python
provider = getattr(pipeline.llm, "provider", "ollama")
usage = getattr(pipeline.llm, "last_usage", None)  # OpenAI만 채워짐
_log(EVENT_ANSWER, {
    "model": model,
    "provider": provider,
    "token_usage": usage,
    ...
})
```

관리자 통계 탭에 "OpenAI 누적 입력/출력 토큰" 표시 (선택, 알파에서는 합계만):
```python
total_in = sum((e.get("details") or {}).get("token_usage", {}).get("prompt_tokens", 0) or 0
               for e in answers)
total_out = sum((e.get("details") or {}).get("token_usage", {}).get("completion_tokens", 0) or 0
                for e in answers)
st.metric("OpenAI 누적 입력 토큰(30일)", f"{total_in:,}")
st.metric("OpenAI 누적 출력 토큰(30일)", f"{total_out:,}")
```

### 2.5 의존성

`requirements.txt`는 변경 없음 (`requests`로 직접 호출). 만일 OpenAI 공식 SDK를 선호한다면 `openai>=1.0`을 추가 가능하나, 의존성 단순성을 위해 본 명세는 `requests` 직접 호출.

### 2.6 M16 단위 테스트

| 파일 | 검사 |
|---|---|
| `tests/test_openai_client.py` (신규) | `_payload` 구성, mock된 `requests.post`로 generate·generate_stream 정상 동작, API 키 없을 때 RuntimeError |
| `tests/test_llm_factory.py` (신규) | `is_openai_model`/`is_ollama_allowed` 분기, `build_llm`이 모델별로 올바른 클래스 반환 |
| `tests/test_streamlit_app.py` (확장) | 모델 선택 셀렉트박스 옵션 그룹핑 헬퍼 단위 테스트 |

### 2.7 M16 자가 검증

```bash
pytest -q
streamlit run src/ui/streamlit_app.py
```

수동 체크 (사용자가 `.env`에 OPENAI_API_KEY를 입력한 상태):
- [ ] 모델 셀렉트박스에 "Local · Ollama · ..." / "Cloud · OpenAI · gpt-4o-mini" 등이 그룹별 표시
- [ ] OpenAI 모델 선택 시 노란 경고 박스 노출
- [ ] 일반 질의 모드 + gpt-4o-mini → 답변 생성, 출처 형식 보존
- [ ] 스트리밍 토큰이 UI에 점진적으로 표시
- [ ] OpenAI 호출 후 ANSWER 로그에 `provider="openai"`, `token_usage` 채워짐
- [ ] 관리자 통계 탭에 "OpenAI 누적 토큰" 메트릭 표시
- [ ] OPENAI_API_KEY를 비우고 재실행 → cloud 그룹이 사라지고 Ollama만 노출

---

## 섹션 3 — M17: 클라우드 배포 준비

> 본 마일스톤은 코드 변경(가드/플래그)과 가이드 문서 작성을 모두 포함한다.

### 3.1 PDF 출처별 `cloud_safe` 플래그

`src/config.py`의 `PdfSource` 데이터클래스에 `cloud_safe: bool = False` 추가. 각 항목 갱신:

```python
PdfSource(
    path=ROOT_DIR / "BZ202603053039374.pdf",
    doc_type="policy_act",
    doc_name="건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수",
    doc_short="심평원",
    cloud_safe=True,
),
PdfSource(
    path=ROOT_DIR / "2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf",
    doc_type="insurance_policy",
    doc_name="신한 이지로운 실손의료보험(무배당) 약관",
    doc_short="약관",
    cloud_safe=True,   # 공개 약관이지만 사용자 정책에 따라 변경 가능
),
PdfSource(
    path=ROOT_DIR / "보상가이드북.pdf",
    doc_type="guide_book",
    doc_name="보상가이드북",
    doc_short="가이드북",
    cloud_safe=False,  # 사내 자료 가능성 — 클라우드 빌드에서 제외
),
```

`scripts/ingest.py`에 `--cloud-only` 플래그 추가: 활성화 시 `cloud_safe=True`만 인제스트.

```python
parser.add_argument("--cloud-only", action="store_true",
                    help="cloud_safe=True인 PDF만 인덱싱한다.")
...
sources = [s for s in config.PDF_SOURCES if (not args.cloud_only) or s.cloud_safe]
```

### 3.2 클라우드 환경 가드

`src/config.py`에 추가:
```python
ALLOW_OLLAMA: bool = os.getenv("ALLOW_OLLAMA", "true").lower() == "true"
CLOUD_DEPLOY: bool = os.getenv("CLOUD_DEPLOY", "false").lower() == "true"
```

Streamlit 앱:
- `CLOUD_DEPLOY=true`이면 사이드바 상단에 "클라우드 배포 — 외부 LLM(OpenAI) 전용" 배너 표시
- `ALLOW_OLLAMA=false`이면 Ollama 모델은 후보에서 제외 (M16에서 이미 처리)

### 3.3 인덱스 자산 다운로드 부트스트랩

`scripts/bootstrap_assets.py` 신규:

```python
"""클라우드 첫 부팅 시 인덱스 자산을 외부 URL에서 다운로드한다.

환경변수 INDEX_RELEASE_URL이 설정되고 data/index/가 비어 있으면,
zip을 받아서 풀어준다.
"""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

import requests

from src import config


def main() -> int:
    url = os.getenv("INDEX_RELEASE_URL")
    if not url:
        print("INDEX_RELEASE_URL 미설정 — 스킵")
        return 0
    if config.CHROMA_DIR.exists() and any(config.CHROMA_DIR.iterdir()):
        print("인덱스가 이미 존재합니다 — 스킵")
        return 0
    print(f"인덱스 자산 다운로드: {url}")
    try:
        response = requests.get(url, timeout=300)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            zf.extractall(config.ROOT_DIR)
        print("다운로드 완료")
        return 0
    except Exception as exc:
        print(f"다운로드 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

`streamlit_app.py` 임포트 직후 한 번 호출 (CLOUD_DEPLOY일 때만):

```python
if config.CLOUD_DEPLOY:
    from scripts.bootstrap_assets import main as _bootstrap
    _bootstrap()
```

### 3.4 Streamlit Community Cloud 배포 가이드 (`docs/17_DEPLOY_GUIDE.md`)

새 문서로 다음 내용을 작성:

```
# 클라우드 배포 가이드 (Streamlit Community Cloud)

## 1. GitHub 저장소 준비
1. .gitignore 점검: .env, users.json, logs/, data/, *.pdf 모두 제외
2. PDF 라이선스 확인:
   - cloud_safe=True인 PDF만 공개 저장소에 둘 수 있음
   - 사내 자료(cloud_safe=False)는 절대 푸시 금지

## 2. 인덱스 자산 패키징
1. 로컬에서 cloud-only로 인덱스 빌드:
   `python scripts/ingest.py --cloud-only`
2. data/index/와 cloud_safe=True PDF들을 함께 zip:
   `zip -r assets.zip data/index/ <cloud_safe pdf 파일들>`
3. GitHub Release를 만들고 assets.zip 업로드 → URL 복사

## 3. Streamlit Community Cloud 설정
1. https://streamlit.io/cloud → Sign in with GitHub
2. New app → repo / branch / main file = `src/ui/streamlit_app.py`
3. Advanced settings → Python version 3.11, Secrets 입력:

```
OPENAI_API_KEY = "<OPENAI_API_KEY>"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_MAX_TOKENS = "1500"
ALLOW_OLLAMA = "false"
CLOUD_DEPLOY = "true"
INDEX_RELEASE_URL = "https://github.com/.../releases/download/.../assets.zip"
USERS_JSON = '{"version":1,"users":[{"username":"admin","password_hash":"$pbkdf2-sha256$...","role":"admin","display_name":"관리자","created_at":"...","password_updated_at":"..."}]}'
```

4. Secrets에 USERS_JSON이 있으면 부팅 시 users.json으로 풀어줘야 한다.
   `streamlit_app.py` 부팅 직후:
   ```python
   _users_json = os.getenv("USERS_JSON")
   if _users_json:
       p = Path(os.getenv("USERS_JSON_PATH", config.ROOT_DIR / "users.json"))
       if not p.exists():
           p.write_text(_users_json, encoding="utf-8")
   ```

## 4. 배포 후 점검
- [ ] 첫 부팅 로그에 인덱스 다운로드 성공
- [ ] 로그인 화면 표시
- [ ] OpenAI 모델 선택 후 일반 질의 정상 동작
- [ ] Ollama 모델은 후보에 없음
- [ ] 관리자 페이지 진입 가능

## 5. 대안: Hugging Face Spaces
... (Streamlit Cloud RAM 부족 시 전환 가이드 — 16GB RAM 활용)
```

(가이드 본문은 위 골격대로 Codex가 채워 작성한다. 단계별 스크린샷은 알파에서 생략.)

### 3.5 README.md 업데이트

기존 README의 "사전 요구사항"·"실행" 섹션을 다음과 같이 보강:

- 사용자 부트스트랩: `python scripts/manage_users.py init`
- OpenAI 사용 가이드: `.env`에 `OPENAI_API_KEY=<OPENAI_API_KEY>` 추가
- 클라우드 배포: `docs/17_DEPLOY_GUIDE.md` 참고
- `APP_PASSWORD` deprecated 안내

### 3.6 M17 자가 검증

```bash
# (1) 클라우드 빌드 시뮬레이션
python scripts/ingest.py --cloud-only --stage all

# (2) 배포 가드 동작 (로컬에서 가짜로 클라우드 모드 활성화)
ALLOW_OLLAMA=false CLOUD_DEPLOY=true streamlit run src/ui/streamlit_app.py
```

수동 체크:
- [ ] `--cloud-only`로 인덱싱 시 가이드북 청크가 포함되지 않음
- [ ] CLOUD_DEPLOY=true에서 사이드바 상단 배너 표시
- [ ] ALLOW_OLLAMA=false에서 모델 후보에 Ollama 없음
- [ ] OpenAI 모델로만 챗 동작
- [ ] `USERS_JSON` 환경변수가 있으면 부팅 시 `users.json`으로 풀림
- [ ] `docs/17_DEPLOY_GUIDE.md` 문서 작성

---

## 섹션 4 — 명세 외 / 구현 금지

- 사용자 삭제 (UI/CLI 모두), 사용자 자체 비밀번호 변경 화면(본 알파는 admin이 리셋)
- 비밀번호 정책 강화 (대소문자/특수문자 강제)
- 세션 만료, 동시 세션 제한, 강제 로그아웃
- SSO/OAuth/OIDC
- exaone3.5 등 7B+ 로컬 모델의 클라우드 호스팅
- OpenAI 외 다른 외부 LLM(Anthropic·Google·Mistral 등)
- 클라우드 로그 영속 저장 (S3/R2/GCS)
- 자체 GPU 인스턴스 운영
- Top-K · 온도 자동 설정 (M18로 별도 분리, 본 명세 범위 외)

## 섹션 5 — 변경 파일 요약

| 파일 | M15 | M16 | M17 |
|---|---|---|---|
| `requirements.txt` | passlib | — | — |
| `.env.example` | — | OpenAI 블록 추가 | ALLOW_OLLAMA / CLOUD_DEPLOY |
| `.gitignore` | users.json 추가 | — | — |
| `src/auth/__init__.py` | 신규(빈) | — | — |
| `src/auth/users.py` | 신규 | — | — |
| `scripts/manage_users.py` | 신규 | — | — |
| `src/utils/logger.py` | log_event_for_user, 새 이벤트 상수 | — | — |
| `src/ui/streamlit_app.py` | 인증 게이트 재작성, _log, 사이드바 사용자 영역, admin 라디오 | 모델 선택 그룹화, build_llm 사용 | CLOUD_DEPLOY 배너, USERS_JSON 부팅 펼침 |
| `src/ui/admin_page.py` | 신규 | OpenAI 토큰 통계 추가 | — |
| `src/llm/base.py` | — | 신규 | — |
| `src/llm/openai_client.py` | — | 신규 | — |
| `src/llm/factory.py` | — | 신규 | — |
| `src/llm/ollama_client.py` | — | provider 변수 추가 | — |
| `src/config.py` | — | OPENAI_*·OPENAI_CANDIDATE_MODELS | ALLOW_OLLAMA, CLOUD_DEPLOY, PdfSource.cloud_safe |
| `scripts/ingest.py` | — | — | --cloud-only 플래그 |
| `scripts/bootstrap_assets.py` | — | — | 신규 |
| `docs/17_DEPLOY_GUIDE.md` | — | — | 신규 |
| `README.md` | 인증 안내 | OpenAI 안내 | 배포 가이드 안내, APP_PASSWORD deprecated |
| `tests/test_*` | auth_users, admin_page, streamlit_app 확장 | openai_client, llm_factory | (선택) |

## 섹션 6 — 마이그레이션 노트

1. 기존 `APP_PASSWORD` 단일 비밀번호는 본 마일스톤부터 무시된다. 본인의 비밀번호를 알고 있는 임직원은 사용 불가 — 새 사용자명·비밀번호로 전환.
2. 첫 실행: `python scripts/manage_users.py init` 필수. 이전에는 `streamlit run` 만으로 동작했으나 이제는 admin 부트스트랩이 선행 조건.
3. 기존 로그(`logs/chat_*.jsonl`)에는 `user_id`/`role`이 없으므로 관리자 통계의 사용자별 집계에서 `(unknown)`으로 표시됨 — 정상.
4. M14 이전 버전의 챗 메시지 export(JSON) 형식은 호환 유지.

## 섹션 7 — Codex 완료 보고서 양식

각 PR마다 다음 형식으로 보고:

```
## M{N} 완료 보고
### 변경된 파일
- ...
### 자가 검증 결과
- pytest: NN passed
- 수동 체크리스트: [통과/실패 항목]
### 사용자에게 전달할 안내
- (필요시) `.env`에 추가해야 할 항목
- 부트스트랩 명령
### 이슈 및 특이사항
- (없으면 "없음")
```

---

*이 명세는 M14가 완료된 코드베이스(`src/ui/streamlit_app.py` 851라인 시점)를 기준으로 작성되었습니다.*
