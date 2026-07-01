import json

import pytest

from src.auth import users


def test_add_authenticate_and_list_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))

    user = users.add_user("admin", "password123", users.ROLE_ADMIN, "관리자")

    assert user.username == "admin"
    assert user.role == users.ROLE_ADMIN
    assert user.password_hash.startswith("$pbkdf2-sha256$")
    assert users.has_admin() is True
    assert users.authenticate("admin", "password123").display_name == "관리자"
    assert users.authenticate("admin", "wrong") is None
    assert users.list_users()[0].public_dict()["username"] == "admin"

    raw = json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["users"][0]["username"] == "admin"


def test_add_user_validates_inputs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))

    with pytest.raises(users.UserStoreError):
        users.add_user("ab", "password123", users.ROLE_EMPLOYEE)
    with pytest.raises(users.UserStoreError):
        users.add_user("employee01", "short", users.ROLE_EMPLOYEE)
    with pytest.raises(users.UserStoreError):
        users.add_user("employee01", "password123", "manager")

    users.add_user("employee01", "password123", users.ROLE_EMPLOYEE)
    with pytest.raises(users.UserStoreError):
        users.add_user("employee01", "password123", users.ROLE_EMPLOYEE)


def test_reset_password(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("employee01", "password123", users.ROLE_EMPLOYEE)

    users.reset_password("employee01", "newpass123")

    assert users.authenticate("employee01", "password123") is None
    assert users.authenticate("employee01", "newpass123") is not None
    with pytest.raises(users.UserStoreError):
        users.reset_password("missing", "newpass123")


def test_authenticate_rejects_removed_viewer_role(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("viewer01", "password123", users.ROLE_EMPLOYEE, "열람자")
    path = tmp_path / "users.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["users"][0]["role"] = "viewer"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    assert users.get_user("viewer01").role == "viewer"
    assert users.authenticate("viewer01", "password123") is None


def test_list_users_returns_empty_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "missing.json"))

    assert users.list_users() == []
    assert users.has_admin() is False
