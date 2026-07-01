"""Small JWT and cookie helpers for the FastAPI layer."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from src.api.settings import get_api_settings

ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"
_SETTINGS = get_api_settings()
ACCESS_TOKEN_SECONDS = _SETTINGS.access_token_seconds
REFRESH_TOKEN_SECONDS = _SETTINGS.refresh_token_seconds

ROLE_PERMISSIONS = {
    "admin": {
        "chat.stream": True,
        "sessions.read": True,
        "sessions.delete": True,
        "sessions.export": True,
        "admin.read": True,
        "admin.logs": True,
        "admin.stats": True,
        "admin.users.manage": True,
        "admin.audit": True,
        "admin.knowledge.read": True,
        "admin.knowledge.manage": True,
    },
    "employee": {
        "chat.stream": True,
        "sessions.read": True,
        "sessions.delete": True,
        "sessions.export": True,
        "admin.read": False,
        "admin.logs": False,
        "admin.stats": False,
        "admin.users.manage": False,
        "admin.audit": False,
        "admin.knowledge.read": False,
        "admin.knowledge.manage": False,
    },
    "user": {
        "chat.stream": True,
        "sessions.read": True,
        "sessions.delete": True,
        "sessions.export": True,
        "admin.read": False,
        "admin.logs": False,
        "admin.stats": False,
        "admin.users.manage": False,
        "admin.audit": False,
        "admin.knowledge.read": False,
        "admin.knowledge.manage": False,
    },
}


@dataclass(frozen=True)
class TokenPair:
    """Issued access and refresh token pair."""

    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int


class TokenError(Exception):
    """Raised when a token is malformed, expired, or has a bad signature."""


def _secret() -> bytes:
    value = os.getenv("API_JWT_SECRET") or os.getenv("SECRET_KEY") or _SETTINGS.jwt_secret
    return value.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _json_dumps(data: dict[str, Any]) -> bytes:
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")


def create_token(
    subject: str,
    role: str,
    token_type: str,
    expires_delta: timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    """Create a compact HS256 JWT string."""

    now = int(time.time())
    payload = {
        "sub": subject,
        "role": role,
        "typ": token_type,
        "iat": now,
        "exp": now + int(expires_delta.total_seconds()),
    }
    if extra:
        payload.update(extra)

    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64encode(_json_dumps(header))}.{_b64encode(_json_dumps(payload))}"
    signature = hmac.new(_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """Verify and decode an HS256 JWT payload."""

    try:
        header_text, payload_text, signature_text = token.split(".", 2)
        header = json.loads(_b64decode(header_text))
        payload = json.loads(_b64decode(payload_text))
    except Exception as exc:
        raise TokenError("토큰 형식이 올바르지 않습니다.") from exc

    if header.get("alg") != "HS256":
        raise TokenError("지원하지 않는 토큰 서명 알고리즘입니다.")

    signing_input = f"{header_text}.{payload_text}".encode("ascii")
    expected = hmac.new(_secret(), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64decode(signature_text)
    except Exception as exc:
        raise TokenError("토큰 서명이 올바르지 않습니다.") from exc
    if not hmac.compare_digest(expected, actual):
        raise TokenError("토큰 서명이 올바르지 않습니다.")

    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("토큰이 만료되었습니다.")
    if expected_type is not None and payload.get("typ") != expected_type:
        raise TokenError("토큰 유형이 올바르지 않습니다.")
    return payload


def issue_token_pair(username: str, role: str) -> TokenPair:
    """Issue access and refresh tokens for a user."""

    access = create_token(
        username,
        role,
        "access",
        timedelta(seconds=ACCESS_TOKEN_SECONDS),
    )
    refresh = create_token(
        username,
        role,
        "refresh",
        timedelta(seconds=REFRESH_TOKEN_SECONDS),
    )
    return TokenPair(access, refresh, ACCESS_TOKEN_SECONDS, REFRESH_TOKEN_SECONDS)
