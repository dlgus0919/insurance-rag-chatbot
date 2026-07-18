#!/usr/bin/env python3
"""Run only fail-closed browser E2E checks against an isolated API instance."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from typing import Mapping
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.isolated_e2e import (
    E2E_BASE_URL_KEY,
    E2E_PORT_KEY,
    E2E_TEST_PASSWORD_KEY,
    E2E_TEST_USERNAME_KEY,
    ISOLATED_E2E_FLAG,
    ISOLATED_E2E_WRITE_FLAG,
    IsolatedE2EPreflightError,
    validate_isolated_e2e_environment,
    validate_read_only_e2e_target,
)
from src.api.isolated_smoke import ISOLATED_SMOKE_FLAG, ISOLATED_SMOKE_ROOT

LOOPBACK_HOST = "127.0.0.1"
HEALTH_TIMEOUT_SECONDS = 45
E2E_STANDARD_CODES_DB_KEY = "E2E_STANDARD_CODES_DB_PATH"


class IsolatedE2ERunnerError(RuntimeError):
    """Raised when a browser E2E command is unsafe or incomplete."""


def _absolute_path(path_text: str | Path, field_name: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        raise IsolatedE2ERunnerError(f"{field_name} must be an absolute path")
    return path.resolve(strict=False)


def _require_runtime_credential(environment: Mapping[str, str], key: str) -> str:
    value = str(environment.get(key) or "").strip()
    if not value:
        raise IsolatedE2ERunnerError(f"{key} must be injected through the runtime environment")
    return value


def bind_read_only_standard_codes_reference(environment: Mapping[str, str]) -> dict[str, str]:
    """Require an explicit read-only standard-code reference for isolated claims."""

    source_text = str(environment.get(E2E_STANDARD_CODES_DB_KEY) or "").strip()
    if not source_text:
        raise IsolatedE2ERunnerError(
            f"{E2E_STANDARD_CODES_DB_KEY} must point to an existing read-only reference database"
        )
    source_path = _absolute_path(source_text, E2E_STANDARD_CODES_DB_KEY)
    if not source_path.is_file():
        raise IsolatedE2ERunnerError(
            f"{E2E_STANDARD_CODES_DB_KEY} must point to an existing read-only reference database"
        )
    bound = dict(environment)
    bound["STANDARD_CODES_DB_PATH"] = str(source_path)
    bound[E2E_STANDARD_CODES_DB_KEY] = str(source_path)
    return bound


def build_isolated_environment(
    *,
    root: Path,
    port: int,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a root-bound write environment and validate it before startup."""

    root = _absolute_path(root, "root")
    environment = dict(os.environ if base_environment is None else base_environment)
    _require_runtime_credential(environment, E2E_TEST_USERNAME_KEY)
    _require_runtime_credential(environment, E2E_TEST_PASSWORD_KEY)

    environment.update(
        {
            ISOLATED_SMOKE_FLAG: "1",
            ISOLATED_SMOKE_ROOT: str(root),
            "API_DATABASE_URL": f"sqlite+aiosqlite:///{root / 'insurance_chat.db'}",
            "USERS_JSON_PATH": str(root / "users.json"),
            "LOG_DIR": str(root / "logs"),
            ISOLATED_E2E_FLAG: "1",
            ISOLATED_E2E_WRITE_FLAG: "1",
            E2E_PORT_KEY: str(port),
            E2E_BASE_URL_KEY: f"http://{LOOPBACK_HOST}:{port}",
            "E2E_ISOLATED_TARGET": "1",
            "E2E_ARTIFACTS_DIR": str(root / "playwright-artifacts"),
            "API_COOKIE_SECURE": "false",
            "API_RATE_LIMIT_DISABLED": "true",
        }
    )
    environment.setdefault("API_JWT_SECRET", secrets.token_urlsafe(32))
    validate_isolated_e2e_environment(environment, project_root=PROJECT_ROOT)
    return environment


def build_read_only_environment(
    *,
    base_url: str,
    artifacts_dir: Path,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an environment for a no-login, no-write smoke against protected live."""

    environment = dict(os.environ if base_environment is None else base_environment)
    if str(environment.get(ISOLATED_E2E_WRITE_FLAG) or "").strip():
        raise IsolatedE2ERunnerError("read-only smoke must not inherit E2E write opt-in")
    validate_read_only_e2e_target(base_url)
    environment.update(
        {
            E2E_BASE_URL_KEY: base_url,
            "E2E_ARTIFACTS_DIR": str(_absolute_path(artifacts_dir, "artifacts_dir")),
            "E2E_READ_ONLY_TARGET": "1",
        }
    )
    return environment


@contextmanager
def _temporary_environment(overrides: Mapping[str, str]):
    """Temporarily bind modules that read process env to an isolated target."""

    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update({key: str(value) for key, value in overrides.items()})
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def prepare_isolated_test_account(environment: Mapping[str, str]) -> None:
    """Create or reset one employee account in the explicitly isolated users file."""

    validate_isolated_e2e_environment(environment, project_root=PROJECT_ROOT)
    username = _require_runtime_credential(environment, E2E_TEST_USERNAME_KEY)
    password = _require_runtime_credential(environment, E2E_TEST_PASSWORD_KEY)

    with _temporary_environment({"USERS_JSON_PATH": environment["USERS_JSON_PATH"]}):
        from src.auth import users as user_store
        from src.auth.users import ROLE_EMPLOYEE

        existing = user_store.get_user(username)
        if existing is not None:
            if existing.role != ROLE_EMPLOYEE:
                raise IsolatedE2ERunnerError("isolated E2E account must have the employee role")
            user_store.reset_password(username, password)
            return
        user_store.add_user(username, password, ROLE_EMPLOYEE, display_name="격리 E2E 테스트")


def _wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    health_url = f"{base_url}/api/health"
    while time.monotonic() < deadline:
        try:
            with urlopen(health_url, timeout=2) as response:  # nosec B310 - loopback only
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            time.sleep(0.5)
    raise IsolatedE2ERunnerError("isolated API did not become healthy before the timeout")


def _start_isolated_server(
    *,
    environment: Mapping[str, str],
    root: Path,
    port: int,
) -> tuple[subprocess.Popen[bytes], object]:
    log_path = root / "server.log"
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.api.main:app",
            "--host",
            LOOPBACK_HOST,
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        env=dict(environment),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return process, log_handle


def _stop_server(process: subprocess.Popen[bytes], log_handle: object) -> None:
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    finally:
        log_handle.close()


def _infer_playwright_test_module(executable: Path) -> Path:
    for ancestor in executable.parents:
        candidate = ancestor / "@playwright" / "test" / "index.js"
        if candidate.is_file():
            return candidate
    raise IsolatedE2ERunnerError(
        "E2E_PLAYWRIGHT_TEST_MODULE must point to @playwright/test/index.js"
    )



def _playwright_invocation(
    environment: Mapping[str, str],
    config_name: str,
) -> tuple[list[str], dict[str, str]]:
    playwright_bin = str(environment.get("E2E_PLAYWRIGHT_BIN") or "").strip()
    if not playwright_bin:
        raise IsolatedE2ERunnerError("E2E_PLAYWRIGHT_BIN must point to an existing Playwright executable")
    executable = _absolute_path(playwright_bin, "E2E_PLAYWRIGHT_BIN")
    if not executable.is_file():
        raise IsolatedE2ERunnerError("E2E_PLAYWRIGHT_BIN must point to an existing Playwright executable")
    config_path = (PROJECT_ROOT / config_name).resolve()
    if not config_path.is_file():
        raise IsolatedE2ERunnerError(f"Playwright config does not exist: {config_name}")
    configured_test_module = environment.get("E2E_PLAYWRIGHT_TEST_MODULE")
    test_module = (
        _absolute_path(configured_test_module, "E2E_PLAYWRIGHT_TEST_MODULE")
        if configured_test_module
        else _infer_playwright_test_module(executable)
    )
    if not test_module.is_file():
        raise IsolatedE2ERunnerError("E2E_PLAYWRIGHT_TEST_MODULE must point to @playwright/test/index.js")
    process_environment = dict(environment)
    process_environment.setdefault("E2E_PLAYWRIGHT_TEST_MODULE", str(test_module))
    command = [str(executable), "test", "--config", str(config_path), "--project", "chromium", "--reporter", "line"]
    return command, process_environment


def _run_playwright(environment: Mapping[str, str], config_name: str) -> int:
    artifacts_dir = _absolute_path(environment["E2E_ARTIFACTS_DIR"], "E2E_ARTIFACTS_DIR")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    command, process_environment = _playwright_invocation(environment, config_name)
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=process_environment,
        check=False,
    )
    return result.returncode


def run_isolated_write(*, root: Path, port: int, run: bool, serve: bool) -> int:
    environment = bind_read_only_standard_codes_reference(
        build_isolated_environment(root=root, port=port)
    )
    root = _absolute_path(root, "root")
    root.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    prepare_isolated_test_account(environment)

    process, log_handle = _start_isolated_server(environment=environment, root=root, port=port)
    try:
        _wait_for_health(environment[E2E_BASE_URL_KEY])
        if run:
            return _run_playwright(environment, "playwright.isolated.config.js")
        if serve:
            print("격리 E2E 서버가 루프백 포트에서 실행 중입니다. 종료하려면 Ctrl+C를 누르세요.")
            while True:
                signal.pause()
        raise IsolatedE2ERunnerError("isolated write mode requires --run or --serve")
    finally:
        _stop_server(process, log_handle)


def run_read_only(*, base_url: str, artifacts_dir: Path) -> int:
    environment = build_read_only_environment(base_url=base_url, artifacts_dir=artifacts_dir)
    return _run_playwright(environment, "playwright.live-readonly.config.js")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("isolated-write", "read-only"), required=True)
    parser.add_argument("--root", help="absolute isolated write root")
    parser.add_argument("--port", type=int, help="isolated loopback port")
    parser.add_argument("--base-url", help="read-only target URL")
    parser.add_argument("--artifacts-dir", help="absolute Playwright artifact directory")
    parser.add_argument("--run", action="store_true", help="run the dedicated Playwright scenario")
    parser.add_argument("--serve", action="store_true", help="keep the isolated server running for an SSH tunnel")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        if args.mode == "isolated-write":
            if not args.root or args.port is None:
                raise IsolatedE2ERunnerError("isolated-write mode requires --root and --port")
            if args.run == args.serve:
                raise IsolatedE2ERunnerError("isolated-write mode requires exactly one of --run or --serve")
            return run_isolated_write(root=Path(args.root), port=args.port, run=args.run, serve=args.serve)

        if not args.base_url or not args.artifacts_dir or not args.run or args.serve:
            raise IsolatedE2ERunnerError(
                "read-only mode requires --base-url, --artifacts-dir, and --run only"
            )
        return run_read_only(base_url=args.base_url, artifacts_dir=Path(args.artifacts_dir))
    except (IsolatedE2EPreflightError, IsolatedE2ERunnerError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
