"""Authentication API routes."""

from __future__ import annotations

import os
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import security
from src.api.db import get_db
from src.api.deps import current_user, log_audit_event, optional_current_user
from src.api.exceptions import AuthException, InvalidCredentialsException, TokenInvalidException
from src.api.rate_limit import limiter
from src.api.schemas.auth import AuthResponse, LoginRequest, RefreshResponse, UserPublic
from src.api.settings import get_api_settings
from src.auth import users as user_store
from src.auth.users import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_secure() -> bool:
    default = str(get_api_settings().cookie_secure).lower()
    return os.getenv("API_COOKIE_SECURE", default).lower() == "true"


def _set_auth_cookies(response: Response, pair: security.TokenPair) -> None:
    response.set_cookie(
        security.ACCESS_TOKEN_COOKIE,
        pair.access_token,
        max_age=pair.access_expires_in,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        security.REFRESH_TOKEN_COOKIE,
        pair.refresh_token,
        max_age=pair.refresh_expires_in,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    for name in (security.ACCESS_TOKEN_COOKIE, security.REFRESH_TOKEN_COOKIE):
        response.delete_cookie(name, path="/", httponly=True, secure=_cookie_secure(), samesite="strict")


def _public_user(user: User) -> UserPublic:
    payload = user.public_dict()
    payload["role"] = user_store.external_role(user.role)
    return UserPublic(**payload)


def _client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


def _request_id(request: Request | None) -> str | None:
    return getattr(getattr(request, "state", None), "request_id", None)


@router.post("/login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_request: LoginRequest,
    response: Response = None,
    db: AsyncSession | None = Depends(get_db),
) -> AuthResponse:
    """Authenticate a user and issue HttpOnly JWT cookies."""

    if isinstance(request, LoginRequest):  # Backward-compatible direct unit-test call.
        legacy_request = request
        legacy_response = login_request if isinstance(login_request, Response) else Response()
        request = None
        login_request = legacy_request
        response = legacy_response
    if response is None:
        response = Response()

    user = user_store.authenticate(login_request.username, login_request.password)
    if user is None:
        if db is not None:
            await log_audit_event(
                db,
                "LOGIN_FAILED",
                user_id=login_request.username,
                ip_address=_client_ip(request),
                detail={"username": login_request.username, "request_id": _request_id(request)},
            )
        raise InvalidCredentialsException(detail=f"username={login_request.username}")
    pair = security.issue_token_pair(user.username, user.role)
    _set_auth_cookies(response, pair)
    user_store.mark_login(user.username)
    if db is not None:
        await log_audit_event(
            db,
            "LOGIN_SUCCESS",
            user_id=user.username,
            ip_address=_client_ip(request),
            detail={"role": user.role, "request_id": _request_id(request)},
        )
    return AuthResponse(user=_public_user(user), access_expires_in=pair.access_expires_in)


@router.post("/logout")
async def logout(
    response: Response,
    request: Request,
    user: User | None = Depends(optional_current_user),
    db: AsyncSession | None = Depends(get_db),
) -> dict[str, str]:
    """Clear authentication cookies."""

    _clear_auth_cookies(response)
    if db is not None and user is not None:
        await log_audit_event(
            db,
            "LOGOUT",
            user_id=user.username,
            ip_address=_client_ip(request),
            detail={"role": user.role, "request_id": _request_id(request)},
        )
    return {"status": "ok"}


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(current_user)) -> UserPublic:
    """Return the current authenticated user."""

    return _public_user(user)


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit("10/minute")
async def refresh(
    request: Request,
    response: Response = None,
    refresh_token: str | None = Cookie(default=None),
) -> RefreshResponse:
    """Issue a new access token from a valid refresh token."""

    if isinstance(request, Response):  # Backward-compatible direct unit-test call.
        legacy_response = request
        legacy_refresh_token = response if isinstance(response, str) else refresh_token
        request = None
        response = legacy_response
        refresh_token = legacy_refresh_token

    if not refresh_token:
        raise AuthException(message="Refresh token이 없습니다.", code="SESSION_EXPIRED")
    try:
        payload = security.decode_token(refresh_token, expected_type="refresh")
    except security.TokenError as exc:
        raise TokenInvalidException(detail=str(exc)) from exc

    username = str(payload.get("sub") or "")
    user = user_store.get_user(username)
    if user is None:
        raise AuthException(message="사용자를 찾을 수 없습니다.", code="AUTH_FAILED")

    access = security.create_token(
        user.username,
        user.role,
        "access",
        timedelta(seconds=security.ACCESS_TOKEN_SECONDS),
    )
    response.set_cookie(
        security.ACCESS_TOKEN_COOKIE,
        access,
        max_age=security.ACCESS_TOKEN_SECONDS,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return RefreshResponse(access_expires_in=security.ACCESS_TOKEN_SECONDS)
