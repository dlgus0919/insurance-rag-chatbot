"""Fail-closed configuration validation for isolated browser E2E runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from src.api.isolated_smoke import (
    ISOLATED_SMOKE_ROOT,
    IsolatedSmokeEnvironment,
    IsolatedSmokePreflightError,
    validate_isolated_smoke_environment,
)


ISOLATED_E2E_FLAG = "INSURANCE_RAG_ISOLATED_E2E"
ISOLATED_E2E_WRITE_FLAG = "INSURANCE_RAG_E2E_ALLOW_WRITES"
E2E_PORT_KEY = "E2E_PORT"
E2E_BASE_URL_KEY = "BASE_URL"
E2E_TEST_USERNAME_KEY = "E2E_TEST_USERNAME"
E2E_TEST_PASSWORD_KEY = "E2E_TEST_PASSWORD"
PROTECTED_LIVE_PORT = 18080


class IsolatedE2EPreflightError(RuntimeError):
    """Raised before a browser E2E run could target a non-isolated service."""


@dataclass(frozen=True)
class IsolatedE2ETarget:
    """Validated HTTP target for a browser E2E invocation."""

    base_url: str


@dataclass(frozen=True)
class IsolatedE2EEnvironment:
    """Validated isolated write target without retaining test credentials."""

    smoke: IsolatedSmokeEnvironment
    port: int
    base_url: str


def _require_environment(environment: Mapping[str, str], key: str) -> str:
    value = str(environment.get(key) or "").strip()
    if not value:
        raise IsolatedE2EPreflightError(f"missing required isolated E2E environment: {key}")
    return value


def _parse_port(value: str, key: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise IsolatedE2EPreflightError(f"{key} must be a numeric TCP port") from exc
    if not 1024 <= port <= 65535:
        raise IsolatedE2EPreflightError(f"{key} must be between 1024 and 65535")
    return port


def _parse_loopback_target(base_url: str) -> IsolatedE2ETarget:
    try:
        parsed = urlparse(base_url)
        port = parsed.port
    except ValueError as exc:
        raise IsolatedE2EPreflightError("BASE_URL must contain a valid TCP port") from exc

    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise IsolatedE2EPreflightError(
            "BASE_URL must be an HTTP loopback address so an SSH tunnel cannot expose writes"
        )
    if port is None:
        raise IsolatedE2EPreflightError("BASE_URL must contain an explicit TCP port")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise IsolatedE2EPreflightError("BASE_URL must not include a path, query, or fragment")
    return IsolatedE2ETarget(base_url=f"http://{parsed.netloc}")


def validate_isolated_e2e_environment(
    environment: Mapping[str, str] | None = None,
    *,
    project_root: Path | None = None,
) -> IsolatedE2EEnvironment:
    """Require all write destinations and credentials to be explicitly injected."""

    env = environment if environment is not None else os.environ
    try:
        smoke = validate_isolated_smoke_environment(env, project_root=project_root)
    except IsolatedSmokePreflightError as exc:
        raise IsolatedE2EPreflightError(str(exc)) from exc

    if _require_environment(env, ISOLATED_E2E_FLAG) != "1":
        raise IsolatedE2EPreflightError(f"{ISOLATED_E2E_FLAG} must be exactly 1")
    if _require_environment(env, ISOLATED_E2E_WRITE_FLAG) != "1":
        raise IsolatedE2EPreflightError(f"{ISOLATED_E2E_WRITE_FLAG} must be exactly 1")

    _require_environment(env, E2E_TEST_USERNAME_KEY)
    _require_environment(env, E2E_TEST_PASSWORD_KEY)

    port = _parse_port(_require_environment(env, E2E_PORT_KEY), E2E_PORT_KEY)
    if port == PROTECTED_LIVE_PORT:
        raise IsolatedE2EPreflightError(
            f"{E2E_PORT_KEY} must not target protected live port {PROTECTED_LIVE_PORT}"
        )

    target = _parse_loopback_target(
        str(env.get(E2E_BASE_URL_KEY) or f"http://127.0.0.1:{port}")
    )
    target_port = urlparse(target.base_url).port
    if target_port != port:
        raise IsolatedE2EPreflightError("BASE_URL port must match E2E_PORT for an isolated write run")

    return IsolatedE2EEnvironment(smoke=smoke, port=port, base_url=target.base_url)


def validate_read_only_e2e_target(base_url: str) -> IsolatedE2ETarget:
    """Allow the protected app only for the explicitly read-only smoke route."""

    target = _parse_loopback_target(base_url)
    if urlparse(target.base_url).port != PROTECTED_LIVE_PORT:
        raise IsolatedE2EPreflightError(
            f"read-only live smoke is restricted to protected port {PROTECTED_LIVE_PORT}"
        )
    return target


def is_isolated_e2e_run(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether an explicitly marked test process should avoid RAG startup."""

    env = environment if environment is not None else os.environ
    return str(env.get(ISOLATED_E2E_FLAG) or "").strip() == "1"
