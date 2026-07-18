from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from src.db import standard_codes


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    path = PROJECT_ROOT / "scripts" / "run_isolated_frontend_e2e.py"
    spec = importlib.util.spec_from_file_location("isolated_frontend_e2e_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_standard_codes_path_supports_runtime_override(tmp_path: Path) -> None:
    reference_path = tmp_path / "standard_codes.sqlite"
    reference_path.touch()
    environment = dict(os.environ)
    environment["STANDARD_CODES_DB_PATH"] = str(reference_path)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.config import STANDARD_CODES_DB_PATH; print(STANDARD_CODES_DB_PATH)",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(reference_path)


def test_isolated_e2e_opens_standard_code_reference_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference_path = tmp_path / "standard_codes.sqlite"
    with sqlite3.connect(reference_path) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.commit()

    monkeypatch.setenv("INSURANCE_RAG_ISOLATED_E2E", "1")
    with standard_codes._connect(reference_path) as connection:
        row = connection.execute("SELECT name FROM sqlite_master WHERE name = 'sample'").fetchone()
        assert row is not None
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO sample (value) VALUES ('blocked')")


def test_isolated_runner_requires_explicit_read_only_standard_code_reference(tmp_path: Path) -> None:
    runner = _load_runner()

    with pytest.raises(runner.IsolatedE2ERunnerError, match="E2E_STANDARD_CODES_DB_PATH"):
        runner.bind_read_only_standard_codes_reference({})

    reference_path = tmp_path / "standard_codes.sqlite"
    sqlite3.connect(reference_path).close()
    environment = runner.bind_read_only_standard_codes_reference(
        {"E2E_STANDARD_CODES_DB_PATH": str(reference_path)}
    )

    assert environment["STANDARD_CODES_DB_PATH"] == str(reference_path)
    assert environment["E2E_STANDARD_CODES_DB_PATH"] == str(reference_path)
