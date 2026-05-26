"""Application exceptions and unified error response helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException


class AppException(HTTPException):
    """Base exception class for all application errors."""

    def __init__(
        self,
        code: str,
        message: str,
        detail: str | None = None,
        status_code: int = 400,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(status_code=status_code, detail=message)
        self.detail = detail

    def to_dict(self, request_id: str = "unknown") -> dict:
        """Convert this exception to the public API error shape."""

        return error_response(self.code, self.message, self.detail, request_id)


def error_response(
    code: str,
    message: str,
    detail: str | None = None,
    request_id: str = "unknown",
) -> dict:
    """Build the standard API error response body."""

    return {
        "error": {
            "code": code,
            "message": message,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "request_id": request_id,
        }
    }


class AuthException(AppException):
    """Authentication-related exceptions."""

    def __init__(
        self,
        code: str = "AUTH_FAILED",
        message: str = "인증 오류가 발생했습니다.",
        detail: str | None = None,
        status_code: int = 401,
    ) -> None:
        super().__init__(code, message, detail, status_code)


class TokenExpiredException(AuthException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("TOKEN_EXPIRED", "토큰이 만료되었습니다.", detail, 401)


class TokenInvalidException(AuthException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("TOKEN_INVALID", "토큰 형식이 올바르지 않습니다.", detail, 401)


class SessionExpiredException(AuthException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("SESSION_EXPIRED", "세션이 만료되었습니다.", detail, 401)


class InvalidCredentialsException(AuthException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("INVALID_CREDENTIALS", "사용자명 또는 비밀번호가 올바르지 않습니다.", detail, 401)


class PermissionException(AppException):
    """Permission-related exceptions."""

    def __init__(
        self,
        code: str = "PERMISSION_DENIED",
        message: str = "이 작업을 수행할 권한이 없습니다.",
        detail: str | None = None,
        status_code: int = 403,
    ) -> None:
        super().__init__(code, message, detail, status_code)


class AdminOnlyException(PermissionException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("ADMIN_ONLY", "관리자만 접근할 수 있습니다.", detail, 403)


class RetrievalException(AppException):
    """RAG/Search-related exceptions."""

    def __init__(
        self,
        code: str = "RETRIEVAL_FAILED",
        message: str = "검색 중 오류가 발생했습니다.",
        detail: str | None = None,
        status_code: int = 500,
    ) -> None:
        super().__init__(code, message, detail, status_code)


class IndexCorruptedException(RetrievalException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("INDEX_CORRUPTED", "검색 인덱스 상태가 올바르지 않습니다.", detail, 500)


class NoResultsException(RetrievalException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("NO_RESULTS", "검색 결과가 없습니다.", detail, 404)


class DatabaseException(AppException):
    """Database-related exceptions."""

    def __init__(
        self,
        code: str = "DB_ERROR",
        message: str = "데이터베이스 오류가 발생했습니다.",
        detail: str | None = None,
        status_code: int = 500,
    ) -> None:
        super().__init__(code, message, detail, status_code)


class SessionNotFoundException(DatabaseException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("SESSION_NOT_FOUND", "해당 세션을 찾을 수 없습니다.", detail, 404)


class UserNotFoundException(DatabaseException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("USER_NOT_FOUND", "해당 사용자를 찾을 수 없습니다.", detail, 404)


class DuplicateEntryException(DatabaseException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("DUPLICATE_ENTRY", "이미 존재하는 항목입니다.", detail, 409)


class ValidationException(AppException):
    """Input validation exceptions."""

    def __init__(
        self,
        code: str = "INVALID_INPUT",
        message: str = "입력값이 올바르지 않습니다.",
        detail: str | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(code, message, detail, status_code)


class MissingFieldException(ValidationException):
    def __init__(self, field_name: str, detail: str | None = None) -> None:
        super().__init__("MISSING_FIELD", f"필수 필드가 누락되었습니다: {field_name}", detail, 400)


class InvalidFormatException(ValidationException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("INVALID_FORMAT", "입력 형식이 올바르지 않습니다.", detail, 400)


class RateLimitException(AppException):
    """Rate limiting exception."""

    def __init__(self, detail: str | None = None) -> None:
        super().__init__("RATE_LIMIT_EXCEEDED", "요청이 너무 많습니다. 잠시 후 다시 시도하세요.", detail, 429)


class TooManyRequestsException(AppException):
    def __init__(self, detail: str | None = None) -> None:
        super().__init__("TOO_MANY_REQUESTS", "동시 요청이 너무 많습니다.", detail, 429)


class InternalException(AppException):
    """Internal server errors."""

    def __init__(
        self,
        code: str = "INTERNAL_ERROR",
        message: str = "서버 내부 오류가 발생했습니다.",
        detail: str | None = None,
        status_code: int = 500,
    ) -> None:
        super().__init__(code, message, detail, status_code)
