from __future__ import annotations

from pathlib import Path

import pytest

from src.api import main
from src.api.isolated_e2e import (
    IsolatedE2EPreflightError,
    is_isolated_e2e_run,
    validate_isolated_e2e_environment,
    validate_read_only_e2e_target,
)


def _isolated_environment(root: Path) -> dict[str, str]:
    return {
        "INSURANCE_RAG_ISOLATED_SMOKE": "1",
        "INSURANCE_RAG_ISOLATED_SMOKE_ROOT": str(root),
        "API_DATABASE_URL": f"sqlite+aiosqlite:///{root / 'insurance_chat.db'}",
        "USERS_JSON_PATH": str(root / "users.json"),
        "LOG_DIR": str(root / "logs"),
        "INSURANCE_RAG_ISOLATED_E2E": "1",
        "INSURANCE_RAG_E2E_ALLOW_WRITES": "1",
        "E2E_PORT": "18181",
        "E2E_TEST_USERNAME": "injected-test-user",
        "E2E_TEST_PASSWORD": "injected-test-password",
    }


def test_isolated_e2e_preflight_requires_explicit_write_opt_in(tmp_path: Path) -> None:
    environment = _isolated_environment(tmp_path / "isolated-e2e")
    environment.pop("INSURANCE_RAG_E2E_ALLOW_WRITES")

    with pytest.raises(IsolatedE2EPreflightError, match="INSURANCE_RAG_E2E_ALLOW_WRITES"):
        validate_isolated_e2e_environment(environment, project_root=tmp_path)


def test_isolated_e2e_preflight_rejects_protected_live_port_for_writes(tmp_path: Path) -> None:
    environment = _isolated_environment(tmp_path / "isolated-e2e")
    environment["E2E_PORT"] = "18080"

    with pytest.raises(IsolatedE2EPreflightError, match="18080"):
        validate_isolated_e2e_environment(environment, project_root=tmp_path)


def test_isolated_e2e_preflight_requires_runtime_injected_credentials(tmp_path: Path) -> None:
    environment = _isolated_environment(tmp_path / "isolated-e2e")
    environment.pop("E2E_TEST_PASSWORD")

    with pytest.raises(IsolatedE2EPreflightError, match="E2E_TEST_PASSWORD"):
        validate_isolated_e2e_environment(environment, project_root=tmp_path)


def test_isolated_e2e_preflight_accepts_only_isolated_write_target(tmp_path: Path) -> None:
    root = tmp_path / "isolated-e2e"

    validated = validate_isolated_e2e_environment(
        _isolated_environment(root),
        project_root=tmp_path,
    )

    assert validated.port == 18181
    assert validated.base_url == "http://127.0.0.1:18181"
    assert validated.smoke.root == root


def test_read_only_live_target_allows_18080_without_credentials() -> None:
    target = validate_read_only_e2e_target("http://127.0.0.1:18080")

    assert target.base_url == "http://127.0.0.1:18080"


@pytest.mark.parametrize(
    ("base_url", "message"),
    (
        ("http://127.0.0.1:18181", "18080"),
        ("http://localhost:18181", "18080"),
        ("https://example.test:18181", "loopback"),
    ),
)
def test_read_only_live_target_rejects_non_protected_ports(base_url: str, message: str) -> None:
    with pytest.raises(IsolatedE2EPreflightError, match=message):
        validate_read_only_e2e_target(base_url)


def test_isolated_e2e_mode_requires_explicit_flag() -> None:
    assert not is_isolated_e2e_run({})
    assert not is_isolated_e2e_run({"INSURANCE_RAG_ISOLATED_E2E": "true"})
    assert is_isolated_e2e_run({"INSURANCE_RAG_ISOLATED_E2E": "1"})
@pytest.mark.anyio
async def test_isolated_e2e_lifespan_validates_destinations_before_db_initialization(monkeypatch) -> None:
    events: list[str] = []

    async def fake_init_db() -> None:
        events.append("init_db")

    def fake_validate(*_args, **_kwargs) -> None:
        events.append("validate")

    monkeypatch.setenv("INSURANCE_RAG_ISOLATED_E2E", "1")
    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(main, "validate_isolated_e2e_environment", fake_validate)

    async with main.lifespan(None):
        pass

    assert events == ["validate", "init_db"]
