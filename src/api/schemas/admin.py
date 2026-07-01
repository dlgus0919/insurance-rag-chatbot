"""Admin API schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RoleName = Literal["admin", "user"]
UserStatus = Literal["active", "inactive", "locked"]


class AdminUserResponse(BaseModel):
    id: str
    username: str
    email: str | None = None
    role: RoleName
    status: UserStatus
    last_login: str | None = None
    created_at: str
    updated_at: str | None = None


class AdminUserListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AdminUserResponse]


class AdminUserCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=3, max_length=32)
    username: str = Field(..., min_length=1, max_length=64)
    email: str | None = None
    password: str = Field(..., min_length=8)
    role: RoleName = "user"


class AdminUserCreateResponse(AdminUserResponse):
    message: str


class AdminUserPatchRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    email: str | None = None
    role: RoleName | None = None
    status: UserStatus | None = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8)


class PasswordResetResponse(BaseModel):
    message: str
    user_id: str
