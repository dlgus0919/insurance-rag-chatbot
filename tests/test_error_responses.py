from types import SimpleNamespace

import pytest

from src.api.exceptions import (
    AppException,
    DuplicateEntryException,
    InvalidCredentialsException,
    InvalidFormatException,
    PermissionException,
    RateLimitException,
    SessionNotFoundException,
    UserNotFoundException,
    error_response,
)


def test_app_exception_standard_shape() -> None:
    exc = AppException("INVALID_INPUT", "입력값이 올바르지 않습니다.", "field=x", 400)
    payload = exc.to_dict("req_test")

    assert payload["error"]["code"] == "INVALID_INPUT"
    assert payload["error"]["message"] == "입력값이 올바르지 않습니다."
    assert payload["error"]["detail"] == "field=x"
    assert payload["error"]["request_id"] == "req_test"
    assert payload["error"]["timestamp"].endswith("Z")


def test_error_response_helper_includes_required_fields() -> None:
    payload = error_response("INTERNAL_ERROR", "서버 내부 오류가 발생했습니다.", None, "req_1")

    assert set(payload["error"]) == {"code", "message", "detail", "timestamp", "request_id"}


@pytest.mark.parametrize(
    ("exc", "status_code", "code"),
    [
        (InvalidCredentialsException(), 401, "INVALID_CREDENTIALS"),
        (PermissionException(), 403, "PERMISSION_DENIED"),
        (SessionNotFoundException(), 404, "SESSION_NOT_FOUND"),
        (DuplicateEntryException(), 409, "DUPLICATE_ENTRY"),
        (RateLimitException(), 429, "RATE_LIMIT_EXCEEDED"),
    ],
)
def test_exception_status_codes(exc, status_code, code) -> None:
    assert exc.status_code == status_code
    assert exc.code == code


def test_user_not_found_error_message() -> None:
    exc = UserNotFoundException("user_id=missing")
    assert exc.to_dict("req_2")["error"]["message"] == "해당 사용자를 찾을 수 없습니다."


def test_invalid_format_error_code() -> None:
    exc = InvalidFormatException("fmt=xml")
    assert exc.to_dict("req_3")["error"]["code"] == "INVALID_FORMAT"


def test_request_id_can_be_unknown() -> None:
    assert AppException("X", "Y").to_dict()["error"]["request_id"] == "unknown"
