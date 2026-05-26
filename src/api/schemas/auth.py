"""Authentication request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserPublic(BaseModel):
    username: str
    role: str
    display_name: str
    created_at: str
    password_updated_at: str
    email: str | None = None
    status: str = "active"
    updated_at: str | None = None
    last_login: str | None = None


class AuthResponse(BaseModel):
    user: UserPublic
    access_expires_in: int


class RefreshResponse(BaseModel):
    access_expires_in: int
