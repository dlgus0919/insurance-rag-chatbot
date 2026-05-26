import pytest

from src.api.exceptions import DuplicateEntryException, UserNotFoundException, ValidationException
from src.api.routes import admin
from src.api.schemas.admin import AdminUserCreateRequest, AdminUserPatchRequest, PasswordResetRequest
from src.auth import users
from src.auth.users import User


def _admin() -> User:
    return User("admin", "hash", users.ROLE_ADMIN, "관리자", "2026-05-20T00:00:00Z", "2026-05-20T00:00:00Z")


@pytest.mark.anyio
async def test_admin_user_create_and_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))

    created = await admin.create_admin_user(
        AdminUserCreateRequest(
            user_id="user001",
            username="김보상",
            email="kim@example.com",
            password="password123",
            role="user",
        ),
        _admin(),
    )
    listed = await admin.list_admin_users(1, 10, None, None, None, _admin())

    assert created.id == "user001"
    assert listed.total == 1
    assert listed.items[0].email == "kim@example.com"


@pytest.mark.anyio
async def test_admin_user_duplicate_conflict(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("user001", "password123", users.ROLE_EMPLOYEE)

    with pytest.raises(DuplicateEntryException):
        await admin.create_admin_user(
            AdminUserCreateRequest(user_id="user001", username="중복", password="password123", role="user"),
            _admin(),
        )


@pytest.mark.anyio
async def test_admin_user_patch_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("user001", "password123", users.ROLE_EMPLOYEE)

    updated = await admin.update_admin_user("user001", AdminUserPatchRequest(status="inactive"), _admin())

    assert updated.status == "inactive"


@pytest.mark.anyio
async def test_admin_user_patch_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))

    with pytest.raises(UserNotFoundException):
        await admin.update_admin_user("missing", AdminUserPatchRequest(status="inactive"), _admin())


@pytest.mark.anyio
async def test_admin_user_reset_password(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("user001", "password123", users.ROLE_EMPLOYEE)

    response = await admin.reset_admin_user_password("user001", PasswordResetRequest(new_password="newpass123"), _admin())

    assert response.user_id == "user001"
    assert users.authenticate("user001", "newpass123") is not None


@pytest.mark.anyio
async def test_admin_user_search_filter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("user001", "password123", users.ROLE_EMPLOYEE, "김보상", email="kim@example.com")
    users.add_user("admin01", "password123", users.ROLE_ADMIN, "관리자")

    response = await admin.list_admin_users(1, 10, "user", "active", "kim", _admin())

    assert response.total == 1
    assert response.items[0].id == "user001"


@pytest.mark.anyio
async def test_admin_user_create_viewer_role(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))

    created = await admin.create_admin_user(
        AdminUserCreateRequest(
            user_id="viewer01",
            username="열람자",
            password="password123",
            role="viewer",
        ),
        _admin(),
    )

    assert created.role == "viewer"
    assert users.get_user("viewer01").role == users.ROLE_VIEWER


@pytest.mark.anyio
async def test_admin_user_delete_and_protect_admin(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("admin", "password123", users.ROLE_ADMIN, "관리자")
    users.add_user("user001", "password123", users.ROLE_EMPLOYEE)

    response = await admin.delete_admin_user("user001", _admin())

    assert response.status_code == 204
    assert users.get_user("user001") is None

    with pytest.raises(ValidationException):
        await admin.delete_admin_user("admin", _admin())


@pytest.mark.anyio
async def test_admin_user_cannot_deactivate_or_downgrade_admin(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("admin", "password123", users.ROLE_ADMIN, "관리자")

    with pytest.raises(ValidationException):
        await admin.update_admin_user("admin", AdminUserPatchRequest(status="inactive"), _admin())

    with pytest.raises(ValidationException):
        await admin.update_admin_user("admin", AdminUserPatchRequest(role="user"), _admin())
