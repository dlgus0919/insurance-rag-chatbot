"""FastAPI dependency helpers."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import security
from src.api.exceptions import AdminOnlyException, AuthException, PermissionException, TokenInvalidException
from src.api.models import AuditLog
from src.auth.users import ROLE_ADMIN, User, get_user


async def current_user(request: Request = None, access_token: str | None = Cookie(default=None)) -> User:
    """Resolve the authenticated user from the HttpOnly access token cookie."""

    if isinstance(request, str):  # Backward-compatible direct unit-test call.
        access_token = request
        request = None

    if not access_token:
        raise AuthException(message="로그인이 필요합니다.", code="SESSION_EXPIRED")
    try:
        payload = security.decode_token(access_token, expected_type="access")
    except security.TokenError as exc:
        raise TokenInvalidException(detail=str(exc)) from exc

    username = str(payload.get("sub") or "")
    user = get_user(username)
    if user is None:
        raise AuthException(message="사용자를 찾을 수 없습니다.", code="AUTH_FAILED")
    if getattr(user, "status", "active") != "active":
        raise PermissionException(message="비활성화된 사용자입니다.", detail=f"status={user.status}")
    if request is not None:
        request.state.user = user
    return user


async def optional_current_user(request: Request = None, access_token: str | None = Cookie(default=None)) -> User | None:
    """Resolve a user when possible, but never block cleanup-oriented routes."""

    try:
        return await current_user(request, access_token)
    except (AuthException, PermissionException, TokenInvalidException):
        return None


async def require_admin(user: User = Depends(current_user)) -> User:
    """Require an administrator role."""

    if user.role != ROLE_ADMIN:
        raise AdminOnlyException()
    return user


def require_permission(permission: str) -> Callable[[User], User]:
    """Build a dependency that checks a named role permission."""

    async def _dependency(user: User = Depends(current_user)) -> User:
        if not security.ROLE_PERMISSIONS.get(user.role, {}).get(permission, False):
            raise PermissionException(detail=f"permission={permission}")
        return user

    return _dependency


async def get_request_id(request: Request) -> str:
    """Return the current request id assigned by middleware."""

    return getattr(request.state, "request_id", "unknown")


async def log_audit_event(
    db: AsyncSession,
    event_type: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    detail: dict | None = None,
    commit: bool = True,
) -> AuditLog:
    """Insert a security audit event."""

    entry = AuditLog(user_id=user_id, event_type=event_type, ip_address=ip_address, detail=detail or {})
    db.add(entry)
    if commit:
        await db.commit()
        await db.refresh(entry)
    return entry
