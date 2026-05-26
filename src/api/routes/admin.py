"""Admin routes backed by SQLite audit and message data."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_db
from src.api.deps import require_admin, require_permission
from src.api.exceptions import DuplicateEntryException, UserNotFoundException, ValidationException
from src.api.models import AuditLog
from src.api.rate_limit import limiter
from src.api.schemas.admin import (
    AdminUserCreateRequest,
    AdminUserCreateResponse,
    AdminUserListResponse,
    AdminUserPatchRequest,
    AdminUserResponse,
    PasswordResetRequest,
    PasswordResetResponse,
)
from src.auth import users as user_store
from src.auth.users import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/logs")
@limiter.limit("60/minute")
async def logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_permission("admin.logs")),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """Return paginated audit logs newest first."""

    total = await db.scalar(select(func.count(AuditLog.id)))
    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "items": [
            {
                "id": item.id,
                "user_id": item.user_id,
                "event_type": item.event_type,
                "ip_address": item.ip_address,
                "detail": item.detail or {},
                "created_at": item.created_at.isoformat(),
            }
            for item in result.scalars()
        ],
    }


@router.get("/stats")
async def stats(
    _: User = Depends(require_permission("admin.stats")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate dashboard stats from messages and audit logs."""

    total_queries = await db.scalar(select(func.count(AuditLog.id)).where(AuditLog.event_type == "CHAT_QUERY"))

    mode_rows = await db.execute(
        select(func.json_extract(AuditLog.detail, "$.mode"), func.count(AuditLog.id))
        .where(AuditLog.event_type == "CHAT_QUERY")
        .group_by(func.json_extract(AuditLog.detail, "$.mode"))
    )
    mode_distribution = {str(mode or "unknown"): int(count) for mode, count in mode_rows.all()}
    for mode in ("general", "quickcode", "formal"):
        mode_distribution.setdefault(mode, 0)

    daily_rows = await db.execute(
        select(func.date(AuditLog.created_at), func.count(AuditLog.id))
        .where(AuditLog.event_type == "CHAT_QUERY")
        .group_by(func.date(AuditLog.created_at))
        .order_by(func.date(AuditLog.created_at).asc())
    )
    return {
        "total_queries": int(total_queries or 0),
        "mode_distribution": mode_distribution,
        "daily_usage": [{"date": str(date), "count": int(count)} for date, count in daily_rows.all()],
    }


@router.get("/users", response_model=AdminUserListResponse)
@limiter.limit("100/minute")
async def list_admin_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    role: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    _: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> AdminUserListResponse:
    """Return paginated users from users.json."""

    items = [_admin_user_response(user) for user in user_store.list_users()]
    if role:
        items = [item for item in items if item.role == role]
    if status_filter:
        items = [item for item in items if item.status == status_filter]
    if search:
        needle = search.casefold()
        items = [
            item
            for item in items
            if needle in item.id.casefold()
            or needle in item.username.casefold()
            or needle in (item.email or "").casefold()
        ]

    total = len(items)
    start = (page - 1) * page_size
    return AdminUserListResponse(total=total, page=page, page_size=page_size, items=items[start : start + page_size])


@router.post("/users", response_model=AdminUserCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("100/minute")
async def create_admin_user(
    payload: AdminUserCreateRequest,
    _: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> AdminUserCreateResponse:
    """Create a users.json-backed account."""

    try:
        created = user_store.add_user(
            payload.user_id,
            payload.password,
            payload.role,
            payload.username,
            email=payload.email,
        )
    except user_store.UserStoreError as exc:
        if "이미 존재" in str(exc):
            raise DuplicateEntryException(detail=str(exc)) from exc
        raise ValidationException(detail=str(exc)) from exc

    response = _admin_user_response(created)
    payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()
    return AdminUserCreateResponse(**payload, message="사용자가 정상 생성되었습니다.")


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
@limiter.limit("100/minute")
async def update_admin_user(
    user_id: str,
    payload: AdminUserPatchRequest,
    current: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> AdminUserResponse:
    """Update account profile, role, or status."""

    if user_id == "admin":
        if payload.status is not None and payload.status != "active":
            raise ValidationException(detail="admin 계정은 비활성화할 수 없습니다.")
        if payload.role is not None and payload.role != "admin":
            raise ValidationException(detail="admin 계정의 역할은 변경할 수 없습니다.")

    try:
        updated = user_store.update_user(
            user_id,
            display_name=payload.username,
            email=payload.email,
            role=payload.role,
            status=payload.status,
        )
    except user_store.UserStoreError as exc:
        if "찾을 수 없습니다" in str(exc):
            raise UserNotFoundException(detail=str(exc)) from exc
        raise ValidationException(detail=str(exc)) from exc
    return _admin_user_response(updated)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("100/minute")
async def delete_admin_user(
    user_id: str,
    current: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> Response:
    """Permanently delete a users.json-backed account."""

    if user_id == "admin":
        raise ValidationException(detail="admin 계정은 삭제할 수 없습니다.")
    if user_id == current.username:
        raise ValidationException(detail="자기 자신의 계정은 삭제할 수 없습니다.")

    try:
        user_store.delete_user(user_id)
    except user_store.UserStoreError as exc:
        if "찾을 수 없습니다" in str(exc):
            raise UserNotFoundException(detail=str(exc)) from exc
        raise ValidationException(detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetResponse)
@limiter.limit("100/minute")
async def reset_admin_user_password(
    user_id: str,
    payload: PasswordResetRequest,
    _: User = Depends(require_permission("admin.users.manage")),
    request: Request = None,
) -> PasswordResetResponse:
    """Reset a user's password."""

    try:
        user_store.reset_password(user_id, payload.new_password)
    except user_store.UserStoreError as exc:
        if "찾을 수 없습니다" in str(exc):
            raise UserNotFoundException(detail=str(exc)) from exc
        raise ValidationException(detail=str(exc)) from exc
    return PasswordResetResponse(message="비밀번호가 정상 재설정되었습니다.", user_id=user_id)


def _admin_user_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.username,
        username=user.display_name,
        email=user.email,
        role=user_store.external_role(user.role),
        status=user.status,
        last_login=user.last_login,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )
