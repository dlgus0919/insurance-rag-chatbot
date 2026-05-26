from datetime import timedelta

import pytest

from src.api import security


def test_create_and_decode_access_token(monkeypatch) -> None:
    monkeypatch.setenv("API_JWT_SECRET", "test-secret")

    token = security.create_token("admin", "admin", "access", timedelta(minutes=5))
    payload = security.decode_token(token, expected_type="access")

    assert payload["sub"] == "admin"
    assert payload["role"] == "admin"
    assert payload["typ"] == "access"


def test_decode_rejects_bad_signature(monkeypatch) -> None:
    monkeypatch.setenv("API_JWT_SECRET", "test-secret")

    token = security.create_token("admin", "admin", "access", timedelta(minutes=5))
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.bad{signature}"

    with pytest.raises(security.TokenError):
        security.decode_token(tampered, expected_type="access")


def test_decode_rejects_wrong_type(monkeypatch) -> None:
    monkeypatch.setenv("API_JWT_SECRET", "test-secret")

    token = security.create_token("admin", "admin", "refresh", timedelta(minutes=5))

    with pytest.raises(security.TokenError):
        security.decode_token(token, expected_type="access")
