import json

import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from src.api.exceptions import PermissionException
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
    auth_cookie_headers = [header for header in cookie_headers if "access_token=" in header or "refresh_token=" in header]
    assert all("Max-Age" not in header for header in auth_cookie_headers)

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
async def test_current_user_rejects_removed_viewer_role(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("USERS_JSON_PATH", str(tmp_path / "users.json"))
    monkeypatch.setenv("API_JWT_SECRET", "test-secret")
    users.add_user("viewer01", "password123", users.ROLE_EMPLOYEE, "열람자")
    path = tmp_path / "users.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["users"][0]["role"] = "viewer"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    pair = auth.security.issue_token_pair("viewer01", "viewer")

    with pytest.raises(PermissionException):
        await auth.current_user(pair.access_token)


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


@pytest.mark.anyio
async def test_models_include_local_optional_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routes.system.list_available_models",
        lambda: {"sglang": [], "vllm": ["gemma-4-31b-it-nvfp4"], "ollama": [], "openai": []},
    )

    models = await system.models()

    local = models.providers["local"][0]
    assert local.id == "vllm:gemma-4-31b-it-nvfp4"
    assert local.status == "vision_candidate"
    assert local.optional is False
    assert local.use_case


@pytest.mark.anyio
async def test_models_excludes_unsupported_trtllm_from_local_choices(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routes.system.list_available_models",
        lambda: {"sglang": [], "vllm": [], "trtllm": ["openai/gpt-oss-120b"], "ollama": [], "openai": []},
    )

    models = await system.models()

    assert models.providers["local"] == []


@pytest.mark.anyio
async def test_models_can_include_unsupported_trtllm_diagnostics(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routes.system.list_available_models",
        lambda: {"sglang": [], "vllm": [], "trtllm": [], "ollama": [], "openai": []},
    )

    models = await system.models(include_diagnostics=True)

    diagnostics = models.providers["diagnostics"]
    target = next(model for model in diagnostics if model.id == "trtllm:openai/gpt-oss-120b")
    assert target.status == "unsupported_on_dgx_spark"
    assert "DGX Spark" in (target.use_case or "")


@pytest.mark.anyio
async def test_models_default_prefers_answer_primary_sglang(monkeypatch) -> None:
    monkeypatch.setattr(system.config, "SGLANG_DEFAULT_MODEL", "qwen3-next-80b-a3b-instruct-fp8")
    monkeypatch.setattr(system.config, "VLLM_DEFAULT_MODEL", "gemma-4-31b-it-nvfp4")
    monkeypatch.setattr(system.config, "OLLAMA_MODEL", "exaone3.5:7.8b")
    monkeypatch.setattr(
        "src.api.routes.system.list_available_models",
        lambda: {
            "sglang": ["qwen3-next-80b-a3b-instruct-fp8"],
            "vllm": ["gemma-4-31b-it-nvfp4"],
            "ollama": ["exaone3.5:7.8b"],
            "openai": [],
        },
    )

    models = await system.models()

    assert models.defaults["local"] == "sglang:qwen3-next-80b-a3b-instruct-fp8"


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
