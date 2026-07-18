from __future__ import annotations

from pathlib import Path

import pytest

from src.api.isolated_smoke import (
    IsolatedSmokePreflightError,
    validate_isolated_smoke_environment,
)


def _isolated_environment(root: Path) -> dict[str, str]:
    return {
        "INSURANCE_RAG_ISOLATED_SMOKE": "1",
        "INSURANCE_RAG_ISOLATED_SMOKE_ROOT": str(root),
        "API_DATABASE_URL": f"sqlite+aiosqlite:///{root / 'insurance_chat.db'}",
        "USERS_JSON_PATH": str(root / "users.json"),
        "LOG_DIR": str(root / "logs"),
    }


def test_isolated_smoke_preflight_requires_explicit_overrides(tmp_path: Path) -> None:
    with pytest.raises(IsolatedSmokePreflightError, match="API_DATABASE_URL"):
        validate_isolated_smoke_environment(
            {
                "INSURANCE_RAG_ISOLATED_SMOKE": "1",
                "INSURANCE_RAG_ISOLATED_SMOKE_ROOT": str(tmp_path / "isolated"),
            },
            project_root=tmp_path,
        )


def test_isolated_smoke_preflight_rejects_protected_project_root_destinations(tmp_path: Path) -> None:
    environment = _isolated_environment(tmp_path)
    environment["INSURANCE_RAG_ISOLATED_SMOKE_ROOT"] = str(tmp_path)

    with pytest.raises(IsolatedSmokePreflightError, match="must not be the project root"):
        validate_isolated_smoke_environment(environment, project_root=tmp_path)


def test_isolated_smoke_preflight_accepts_only_contained_test_destinations(tmp_path: Path) -> None:
    root = tmp_path / "isolated-smoke"
    environment = _isolated_environment(root)

    validated = validate_isolated_smoke_environment(environment, project_root=tmp_path)

    assert validated.root == root
    assert validated.database_path == root / "insurance_chat.db"
    assert validated.users_path == root / "users.json"
    assert validated.log_dir == root / "logs"
    assert not root.exists()
