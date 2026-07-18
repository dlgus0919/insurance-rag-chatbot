from __future__ import annotations

import os
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_commonjs_playwright_module(tmp_path: Path) -> Path:
    module_path = tmp_path / "playwright-test.cjs"
    module_path.write_text(
        "module.exports = { defineConfig: (config) => config, devices: { 'Desktop Chrome': {} } };\n",
        encoding="utf-8",
    )
    return module_path


def _run_config(config_name: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(PROJECT_ROOT / config_name)],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_isolated_config_accepts_commonjs_playwright_module(tmp_path: Path) -> None:
    module_path = _write_commonjs_playwright_module(tmp_path)
    environment = {
        "PATH": os.environ["PATH"],
        "E2E_PLAYWRIGHT_TEST_MODULE": str(module_path),
        "E2E_ISOLATED_TARGET": "1",
        "INSURANCE_RAG_E2E_ALLOW_WRITES": "1",
        "E2E_TEST_USERNAME": "fixture_user",
        "E2E_TEST_PASSWORD": "fixture_password",
        "BASE_URL": "http://127.0.0.1:18181",
        "E2E_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
    }

    result = _run_config("playwright.isolated.config.js", environment)

    assert result.returncode == 0, result.stderr


def test_live_read_only_config_accepts_commonjs_playwright_module(tmp_path: Path) -> None:
    module_path = _write_commonjs_playwright_module(tmp_path)
    environment = {
        "PATH": os.environ["PATH"],
        "E2E_PLAYWRIGHT_TEST_MODULE": str(module_path),
        "E2E_READ_ONLY_TARGET": "1",
        "BASE_URL": "http://127.0.0.1:18080",
        "E2E_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
    }

    result = _run_config("playwright.live-readonly.config.js", environment)

    assert result.returncode == 0, result.stderr
