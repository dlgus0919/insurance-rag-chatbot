import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from src.api.main import create_app
from src.api.routes import auth, system
from src.auth import users


@pytest.mark.anyio
async def test_auth_cookie_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    monkeypatch.setenv("API_JWT_SECRET", "test-secret")
    users.add_user("admin", "password123", users.ROLE_ADMIN, "관리자")
    response = Response()

    login = await auth.login(auth.LoginRequest(username="admin", password="password123"), response, None, db=None)
    cookie_headers = response.headers.getlist("set-cookie")

    assert login.user.username == "admin"
    assert any("access_token=" in header for header in cookie_headers)
    assert any("refresh_token=" in header for header in cookie_headers)

    pair = auth.security.issue_token_pair("admin", users.ROLE_ADMIN)
    me = await auth.me(await auth.current_user(pair.access_token))
    assert me.role == users.ROLE_ADMIN

    refresh_response = Response()
    refreshed = await auth.refresh(refresh_response, pair.refresh_token)
    assert refreshed.access_expires_in > 0

    logout_response = Response()
    logged_out = await auth.logout(logout_response, None, user=None, db=None)
    assert logged_out == {"status": "ok"}


@pytest.mark.anyio
async def test_auth_rejects_invalid_login(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    users.add_user("employee01", "password123", users.ROLE_EMPLOYEE, "직원")

    with pytest.raises(auth.HTTPException) as exc_info:
        await auth.login(auth.LoginRequest(username="employee01", password="wrong"), Response(), None, db=None)
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_health_and_models(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routes.system.list_available_models",
        lambda: {"local": ["gemma3:4b"], "cloud": ["gpt-5-mini"]},
    )

    health = await system.health()
    models = await system.models()

    assert health.status == "ok"
    assert models.providers["local"][0].id == "gemma3:4b"
    assert models.providers["openai"][0].id == "gpt-5-mini"


def test_create_app_registers_week1_routes() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/api/health" in paths
    assert "/api/auth/login" in paths
    assert "/api/auth/me" in paths
    assert "/api/system/models" in paths
    assert "/api/chat/stream" in paths
    assert "/api/sessions" in paths
    assert "/api/admin/stats" in paths


def test_logout_route_clears_cookies_without_access_token(monkeypatch) -> None:
    monkeypatch.setenv("API_COOKIE_SECURE", "false")
    client = TestClient(create_app())

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    set_cookie = response.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
    assert "Max-Age=0" in set_cookie
