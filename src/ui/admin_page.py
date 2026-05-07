"""관리자 전용 페이지."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import streamlit as st

from src import config
from src.auth import users as user_store
from src.auth.users import ROLE_ADMIN, ROLE_EMPLOYEE
from src.llm.factory import is_ollama_allowed, list_available_models
from src.rag.pipeline import DebugInfo
from src.utils.logger import EVENT_ADMIN_VIEW, EVENT_USER_CREATE, EVENT_USER_RESET

LOG_DIR = Path(config.LOG_DIR)
EVENT_TYPES = [
    "APP_ACCESS",
    "LOGIN_SUCCESS",
    "LOGIN_FAILURE",
    "LOGOUT",
    "QUESTION",
    "ANSWER",
    "EXPORT",
    "USER_CREATE",
    "USER_RESET",
    "ADMIN_VIEW",
]


def _parse_log_time(value: str) -> datetime | None:
    """로그 timestamp 문자열을 timezone-aware datetime으로 변환한다."""

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _read_logs(date_from: datetime, date_to: datetime, log_dir: Path | None = None) -> list[dict]:
    """logs/chat_*.jsonl 파일에서 기간 안의 이벤트를 읽는다."""

    selected_log_dir = log_dir or LOG_DIR
    events: list[dict] = []
    if not selected_log_dir.exists():
        return events
    for log_file in sorted(selected_log_dir.glob("chat_*.jsonl*")):
        try:
            with log_file.open("r", encoding="utf-8") as file:
                for line in file:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    timestamp = _parse_log_time(record.get("timestamp", ""))
                    if timestamp is None:
                        continue
                    if date_from <= timestamp <= date_to:
                        events.append(record)
        except OSError:
            continue
    return events


def _filter_events(events: list[dict], user_filter: list[str] | None = None, event_types: list[str] | None = None) -> list[dict]:
    """사용자와 이벤트 유형으로 이벤트 목록을 필터링한다."""

    filtered = list(events)
    if user_filter:
        allowed_users = set(user_filter)
        filtered = [event for event in filtered if (event.get("details") or {}).get("user_id") in allowed_users]
    if event_types:
        allowed_events = set(event_types)
        filtered = [event for event in filtered if event.get("event") in allowed_events]
    return filtered


def _logs_to_csv(events: list[dict]) -> str:
    """로그 이벤트를 CSV 문자열로 변환한다."""

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "event", "session_id", "user_id", "role", "details"])
    for event in events:
        details = event.get("details", {}) or {}
        detail_body = {key: value for key, value in details.items() if key not in {"user_id", "role"}}
        writer.writerow(
            [
                event.get("timestamp", ""),
                event.get("event", ""),
                event.get("session_id", ""),
                details.get("user_id", ""),
                details.get("role", ""),
                json.dumps(detail_body, ensure_ascii=False),
            ]
        )
    return output.getvalue()


def _compute_stats(events: list[dict]) -> dict:
    """관리자 통계 탭에서 사용할 집계 값을 만든다."""

    questions = [event for event in events if event.get("event") == "QUESTION"]
    answers = [event for event in events if event.get("event") == "ANSWER"]
    total_ms = [
        (event.get("details") or {}).get("timing", {}).get("total_ms", 0) or 0
        for event in answers
    ]
    by_user = Counter((event.get("details") or {}).get("user_id") or "(unknown)" for event in questions)
    by_mode = Counter((event.get("details") or {}).get("mode") or "general" for event in questions)
    by_model = Counter((event.get("details") or {}).get("model") or "?" for event in answers)
    prompt_tokens = sum((event.get("details") or {}).get("token_usage", {}).get("prompt_tokens", 0) or 0 for event in answers)
    completion_tokens = sum(
        (event.get("details") or {}).get("token_usage", {}).get("completion_tokens", 0) or 0 for event in answers
    )
    return {
        "question_count": len(questions),
        "answer_count": len(answers),
        "avg_total_sec": (sum(total_ms) / len(total_ms) / 1000) if total_ms else 0,
        "by_user": dict(by_user),
        "by_mode": dict(by_mode),
        "by_model": dict(by_model),
        "openai_prompt_tokens": prompt_tokens,
        "openai_completion_tokens": completion_tokens,
    }


def _to_utc_range(start: date, end: date) -> tuple[datetime, datetime]:
    """date_input 값을 UTC datetime 범위로 변환한다."""

    return (
        datetime.combine(start, time.min, tzinfo=timezone.utc),
        datetime.combine(end, time.max, tzinfo=timezone.utc),
    )


def _tab_logs(_log) -> None:
    st.subheader("로그 조회")
    today = datetime.now(timezone.utc).date()
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        date_from = st.date_input("시작일", value=today - timedelta(days=7))
    with col_b:
        date_to = st.date_input("종료일", value=today)
    with col_c:
        usernames = sorted({user.username for user in user_store.list_users()})
        user_filter = st.multiselect("사용자", usernames, default=[])

    event_types = st.multiselect("이벤트 유형", EVENT_TYPES, default=[])
    dt_from, dt_to = _to_utc_range(date_from, date_to)
    events = _filter_events(_read_logs(dt_from, dt_to), user_filter, event_types)

    st.caption(f"총 {len(events)}건")
    rows = [
        {
            "시각": event.get("timestamp", ""),
            "이벤트": event.get("event", ""),
            "사용자": (event.get("details") or {}).get("user_id", ""),
            "역할": (event.get("details") or {}).get("role", ""),
            "세션": event.get("session_id", ""),
            "상세": json.dumps(event.get("details") or {}, ensure_ascii=False)[:200],
        }
        for event in events[-500:]
    ]
    st.dataframe(rows, use_container_width=True, height=400)
    st.download_button(
        "CSV 다운로드",
        data=_logs_to_csv(events),
        file_name=f"logs_{date_from}_{date_to}.csv",
        mime="text/csv",
    )


def _tab_stats(_log) -> None:
    st.subheader("통계")
    today = datetime.now(timezone.utc).date()
    date_from, date_to = _to_utc_range(today - timedelta(days=30), today)
    stats = _compute_stats(_read_logs(date_from, date_to))

    col1, col2, col3 = st.columns(3)
    col1.metric("최근 30일 질문", f"{stats['question_count']:,}")
    col2.metric("응답", f"{stats['answer_count']:,}")
    col3.metric("평균 응답(초)", f"{stats['avg_total_sec']:.1f}")
    col4, col5 = st.columns(2)
    col4.metric("OpenAI 누적 입력 토큰(30일)", f"{stats['openai_prompt_tokens']:,}")
    col5.metric("OpenAI 누적 출력 토큰(30일)", f"{stats['openai_completion_tokens']:,}")

    st.markdown("**사용자별 질문 수**")
    st.bar_chart(stats["by_user"])
    st.markdown("**검색 모드 분포**")
    st.bar_chart(stats["by_mode"])
    st.markdown("**모델별 응답 수**")
    st.bar_chart(stats["by_model"])


def _tab_users(_log) -> None:
    st.subheader("사용자 관리")
    users = user_store.list_users()
    st.dataframe(
        [
            {
                "사용자명": user.username,
                "역할": user.role,
                "표시 이름": user.display_name,
                "생성일": user.created_at,
                "비밀번호 갱신": user.password_updated_at,
            }
            for user in users
        ],
        use_container_width=True,
    )

    with st.expander("➕ 사용자 추가"):
        with st.form("add_user_form"):
            new_username = st.text_input("사용자명 (영숫자_, 3~32자)")
            new_display = st.text_input("표시 이름")
            new_role = st.selectbox("역할", [ROLE_EMPLOYEE, ROLE_ADMIN])
            new_password = st.text_input("비밀번호 (8자 이상)", type="password")
            submitted = st.form_submit_button("추가", type="primary")
        if submitted:
            try:
                user_store.add_user(
                    new_username.strip(),
                    new_password,
                    role=new_role,
                    display_name=new_display.strip() or None,
                )
                _log(EVENT_USER_CREATE, {"target_username": new_username.strip(), "target_role": new_role})
                st.success(f"사용자 '{new_username.strip()}' 추가 완료")
                st.rerun()
            except user_store.UserStoreError as exc:
                st.error(str(exc))

    with st.expander("🔑 비밀번호 리셋"):
        with st.form("reset_pw_form"):
            target = st.selectbox("대상 사용자", [user.username for user in users])
            new_password = st.text_input("새 비밀번호 (8자 이상)", type="password")
            submitted = st.form_submit_button("리셋", type="primary")
        if submitted:
            try:
                user_store.reset_password(target, new_password)
                _log(EVENT_USER_RESET, {"target_username": target})
                st.success(f"'{target}' 비밀번호 리셋 완료")
            except user_store.UserStoreError as exc:
                st.error(str(exc))


def _tab_system(_log) -> None:
    st.subheader("시스템 상태")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**인덱스**")
        st.write("Chroma 디렉토리:", str(config.CHROMA_DIR), "·", "있음" if config.CHROMA_DIR.exists() else "없음")
        st.write("BM25 파일:", str(config.BM25_PATH), "·", "있음" if config.BM25_PATH.exists() else "없음")
    with col2:
        st.markdown("**LLM**")
        st.write("Ollama 허용:", is_ollama_allowed())
        st.write("기본 로컬 모델:", config.OLLAMA_MODEL)
        st.write("기본 OpenAI 모델:", config.OPENAI_DEFAULT_MODEL)
        st.write("선택 가능 모델:", list_available_models())
        st.markdown("**임베딩**")
        st.write("임베딩 모델:", config.EMBEDDING_MODEL)
        st.write("HuggingFace 다운로드 허용:", config.HF_MODEL_DOWNLOAD)
        st.write("클라우드 배포:", config.CLOUD_DEPLOY)


def _tab_search_diagnostics(_log) -> None:
    """최근 질의의 RAG 단계별 검색 결과를 표시한다."""

    st.markdown("### RAG 검색 진단")
    st.caption("최근 질의의 단계별 검색 결과를 표시합니다.")

    debug = st.session_state.get("last_debug")
    if debug is None:
        st.info("챗봇 페이지에서 일반 질의를 먼저 실행하면 단계별 결과가 여기에 표시됩니다.")
        st.caption("(퀵 코드·약관 정형 모드는 진단 데이터를 수집하지 않습니다.)")
        return

    debug = DebugInfo(
        dense_hits=debug.dense_hits,
        bm25_hits=debug.bm25_hits,
        rrf_hits=debug.rrf_hits,
        final_hits=debug.final_hits,
    )
    for stage_name, stage_hits in [
        ("① Dense (BGE-M3)", debug.dense_hits),
        ("② BM25 (키워드)", debug.bm25_hits),
        ("③ RRF 융합", debug.rrf_hits),
        ("④ Rerank 후 최종", debug.final_hits),
    ]:
        with st.expander(f"{stage_name} — {len(stage_hits)}건", expanded=stage_name.startswith("④")):
            if not stage_hits:
                st.write("(결과 없음)")
                continue
            import pandas as pd

            st.dataframe(
                [
                    {
                        "chunk_id": hit.chunk_id,
                        "문서": hit.doc_short,
                        "점수": hit.score,
                        "페이지": f"p.{hit.page_start}" if hit.page_start else "-",
                        "본문 미리보기": hit.text_preview,
                    }
                    for hit in stage_hits
                ],
                use_container_width=True,
            )


def render_admin_page(_log) -> None:
    """관리자 페이지 본문을 렌더링한다."""

    if st.session_state.get("user_role") != ROLE_ADMIN:
        st.error("관리자 권한이 필요합니다.")
        st.stop()

    _log(EVENT_ADMIN_VIEW)
    st.title("관리자 페이지")
    tabs = st.tabs(["로그 조회", "통계", "사용자 관리", "시스템 상태", "🔍 검색 진단"])
    with tabs[0]:
        _tab_logs(_log)
    with tabs[1]:
        _tab_stats(_log)
    with tabs[2]:
        _tab_users(_log)
    with tabs[3]:
        _tab_system(_log)
    with tabs[4]:
        _tab_search_diagnostics(_log)
