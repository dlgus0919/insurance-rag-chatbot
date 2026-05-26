import pytest

from src.api.deps import require_admin, require_permission
from src.api.exceptions import AdminOnlyException, PermissionException
from src.auth.users import ROLE_ADMIN, ROLE_EMPLOYEE, ROLE_VIEWER, User


def _user(role: str) -> User:
    return User(
        "admin" if role == ROLE_ADMIN else role + "01",
        "hash",
        role,
        role,
        "2026-05-20T00:00:00Z",
        "2026-05-20T00:00:00Z",
    )


@pytest.mark.anyio
async def test_admin_can_pass_admin_dependency() -> None:
    assert await require_admin(_user(ROLE_ADMIN))


@pytest.mark.anyio
async def test_employee_cannot_pass_admin_dependency() -> None:
    with pytest.raises(AdminOnlyException):
        await require_admin(_user(ROLE_EMPLOYEE))


@pytest.mark.anyio
async def test_admin_has_user_manage_permission() -> None:
    dependency = require_permission("admin.users.manage")

    assert await dependency(_user(ROLE_ADMIN))


@pytest.mark.anyio
async def test_employee_lacks_user_manage_permission() -> None:
    dependency = require_permission("admin.users.manage")

    with pytest.raises(PermissionException):
        await dependency(_user(ROLE_EMPLOYEE))


@pytest.mark.anyio
async def test_employee_has_session_export_permission() -> None:
    dependency = require_permission("sessions.export")

    assert await dependency(_user(ROLE_EMPLOYEE))


@pytest.mark.anyio
async def test_viewer_can_read_and_export_but_not_chat_or_delete() -> None:
    read_dependency = require_permission("sessions.read")
    export_dependency = require_permission("sessions.export")
    chat_dependency = require_permission("chat.stream")
    delete_dependency = require_permission("sessions.delete")

    assert await read_dependency(_user(ROLE_VIEWER))
    assert await export_dependency(_user(ROLE_VIEWER))

    with pytest.raises(PermissionException):
        await chat_dependency(_user(ROLE_VIEWER))

    with pytest.raises(PermissionException):
        await delete_dependency(_user(ROLE_VIEWER))
