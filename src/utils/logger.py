"""사내 챗봇 감사 로그 모듈.

logs/chat_YYYY-MM-DD.jsonl 형식으로 저장한다. 각 줄은 독립적인 JSON 객체다.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))

EVENT_APP_ACCESS = "APP_ACCESS"
EVENT_LOGIN_SUCCESS = "LOGIN_SUCCESS"
EVENT_LOGIN_FAILURE = "LOGIN_FAILURE"
EVENT_QUESTION = "QUESTION"
EVENT_ANSWER = "ANSWER"
EVENT_EXPORT = "EXPORT"
EVENT_LOGOUT = "LOGOUT"
EVENT_USER_CREATE = "USER_CREATE"
EVENT_USER_RESET = "USER_RESET"
EVENT_ADMIN_VIEW = "ADMIN_VIEW"


def _get_logger() -> logging.Logger:
    """날짜별 로테이션 JSONL 파일 로거를 반환한다."""

    logger = logging.getLogger("rag_chat_audit")
    if logger.handlers:
        return logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"chat_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
    handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=90,
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


def log_event_for_user(
    event: str,
    session_id: str,
    user_id: str | None,
    role: str | None,
    details: dict | None = None,
) -> None:
    """사용자 정보를 details에 자동 부착해 이벤트를 기록한다."""

    enriched = dict(details or {})
    enriched.setdefault("user_id", user_id)
    enriched.setdefault("role", role)
    log_event(event, session_id, enriched)
