from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.api.isolated_e2e import IsolatedE2EPreflightError


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_isolated_frontend_e2e.py"
    spec = importlib.util.spec_from_file_location("isolated_frontend_e2e_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_isolated_environment_binds_every_write_destination_to_root(tmp_path: Path) -> None:
    runner = _load_runner()
    root = tmp_path / "browser-e2e"

    environment = runner.build_isolated_environment(
        root=root,
        port=18181,
        base_environment={
            "E2E_TEST_USERNAME": "fixture_user",
            "E2E_TEST_PASSWORD": "fixture_password",
        },
    )

    assert environment["INSURANCE_RAG_ISOLATED_E2E"] == "1"
    assert environment["INSURANCE_RAG_E2E_ALLOW_WRITES"] == "1"
    assert environment["BASE_URL"] == "http://127.0.0.1:18181"
    assert environment["API_DATABASE_URL"].endswith("/browser-e2e/insurance_chat.db")
    assert environment["USERS_JSON_PATH"].endswith("/browser-e2e/users.json")
    assert environment["LOG_DIR"].endswith("/browser-e2e/logs")


def test_runner_cli_help_imports_project_modules_outside_project_root(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_isolated_frontend_e2e.py"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--mode" in result.stdout


def test_build_isolated_environment_rejects_protected_port(tmp_path: Path) -> None:
    runner = _load_runner()

    with pytest.raises(IsolatedE2EPreflightError, match="18080"):
        runner.build_isolated_environment(
            root=tmp_path / "browser-e2e",
            port=18080,
            base_environment={
                "E2E_TEST_USERNAME": "fixture_user",
                "E2E_TEST_PASSWORD": "fixture_password",
            },
        )

def test_prepare_test_account_uses_environment_bound_users_path(tmp_path: Path, monkeypatch) -> None:
    runner = _load_runner()
    root = tmp_path / "browser-e2e"
    environment = runner.build_isolated_environment(
        root=root,
        port=18181,
        base_environment={
            "E2E_TEST_USERNAME": "fixture_user",
            "E2E_TEST_PASSWORD": "fixture_password",
        },
    )
    wrong_users_path = root / "wrong-users.json"
    monkeypatch.setenv("USERS_JSON_PATH", str(wrong_users_path))

    runner.prepare_isolated_test_account(environment)

    assert Path(environment["USERS_JSON_PATH"]).exists()
    assert not wrong_users_path.exists()



def test_playwright_invocation_uses_explicit_config_and_matching_test_module(tmp_path: Path) -> None:
    runner = _load_runner()
    root = tmp_path / "browser-e2e"
    playwright_bin = tmp_path / "node_modules" / ".bin" / "playwright"
    playwright_module = tmp_path / "node_modules" / "@playwright" / "test" / "index.js"
    playwright_bin.parent.mkdir(parents=True)
    playwright_module.parent.mkdir(parents=True)
    playwright_bin.touch()
    playwright_module.touch()
    environment = runner.build_isolated_environment(
        root=root,
        port=18181,
        base_environment={
            "E2E_TEST_USERNAME": "fixture_user",
            "E2E_TEST_PASSWORD": "fixture_password",
            "E2E_PLAYWRIGHT_BIN": str(playwright_bin),
        },
    )

    command, process_environment = runner._playwright_invocation(environment, "playwright.isolated.config.js")

    assert command[3] == str(runner.PROJECT_ROOT / "playwright.isolated.config.js")

def test_playwright_invocation_finds_test_module_from_symlinked_cli(tmp_path: Path) -> None:
    runner = _load_runner()
    root = tmp_path / "browser-e2e"
    node_modules = tmp_path / "node_modules"
    playwright_bin = node_modules / ".bin" / "playwright"
    cli_target = node_modules / "@playwright" / "test" / "cli.js"
    test_module = node_modules / "@playwright" / "test" / "index.js"
    playwright_bin.parent.mkdir(parents=True)
    cli_target.parent.mkdir(parents=True)
    cli_target.touch()
    test_module.touch()
    playwright_bin.symlink_to(cli_target)
    environment = runner.build_isolated_environment(
        root=root,
        port=18181,
        base_environment={
            "E2E_TEST_USERNAME": "fixture_user",
            "E2E_TEST_PASSWORD": "fixture_password",
            "E2E_PLAYWRIGHT_BIN": str(playwright_bin),
        },
    )

    _, process_environment = runner._playwright_invocation(environment, "playwright.isolated.config.js")

    assert process_environment["E2E_PLAYWRIGHT_TEST_MODULE"] == str(test_module)
