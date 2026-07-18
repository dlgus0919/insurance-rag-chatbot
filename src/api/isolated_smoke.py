"""Fail-closed environment validation for isolated API smoke runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ISOLATED_SMOKE_FLAG = "INSURANCE_RAG_ISOLATED_SMOKE"
ISOLATED_SMOKE_ROOT = "INSURANCE_RAG_ISOLATED_SMOKE_ROOT"
REQUIRED_ENVIRONMENT_KEYS = (
    ISOLATED_SMOKE_FLAG,
    ISOLATED_SMOKE_ROOT,
    "API_DATABASE_URL",
    "USERS_JSON_PATH",
    "LOG_DIR",
)
_SQLITE_PREFIXES = ("sqlite+aiosqlite:///", "sqlite:///")


class IsolatedSmokePreflightError(RuntimeError):
    """Raised before a smoke run could write to a non-isolated location."""


@dataclass(frozen=True)
class IsolatedSmokeEnvironment:
    """Validated destinations for an explicitly isolated smoke invocation."""

    root: Path
    database_path: Path
    users_path: Path
    log_dir: Path


def _require_environment(
    environment: Mapping[str, str],
    key: str,
) -> str:
    value = str(environment.get(key) or "").strip()
    if not value:
        raise IsolatedSmokePreflightError(f"missing required isolated smoke environment: {key}")
    return value


def _resolve_absolute(path_text: str, field_name: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        raise IsolatedSmokePreflightError(f"{field_name} must be an absolute path")
    return path.resolve(strict=False)


def _sqlite_database_path(database_url: str) -> Path:
    for prefix in _SQLITE_PREFIXES:
        if database_url.startswith(prefix):
            path_text = database_url[len(prefix) :]
            if path_text == ":memory:":
                break
            return _resolve_absolute(path_text, "API_DATABASE_URL")
    raise IsolatedSmokePreflightError(
        "API_DATABASE_URL must be an absolute sqlite file URL for an isolated smoke run"
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _assert_within_isolated_root(path: Path, root: Path, field_name: str) -> None:
    if not _is_within(path, root):
        raise IsolatedSmokePreflightError(
            f"{field_name} must be contained by INSURANCE_RAG_ISOLATED_SMOKE_ROOT"
        )


def validate_isolated_smoke_environment(
    environment: Mapping[str, str] | None = None,
    *,
    project_root: Path | None = None,
) -> IsolatedSmokeEnvironment:
    """Require explicit, non-default API destinations before an isolated smoke run."""

    env = environment if environment is not None else os.environ
    if _require_environment(env, ISOLATED_SMOKE_FLAG) != "1":
        raise IsolatedSmokePreflightError(f"{ISOLATED_SMOKE_FLAG} must be exactly 1")

    root = _resolve_absolute(
        _require_environment(env, ISOLATED_SMOKE_ROOT),
        ISOLATED_SMOKE_ROOT,
    )
    database_path = _sqlite_database_path(_require_environment(env, "API_DATABASE_URL"))
    users_path = _resolve_absolute(_require_environment(env, "USERS_JSON_PATH"), "USERS_JSON_PATH")
    log_dir = _resolve_absolute(_require_environment(env, "LOG_DIR"), "LOG_DIR")

    if root == (project_root or Path.cwd()).resolve(strict=False):
        raise IsolatedSmokePreflightError(
            "INSURANCE_RAG_ISOLATED_SMOKE_ROOT must not be the project root"
        )

    for path, field_name in (
        (database_path, "API_DATABASE_URL"),
        (users_path, "USERS_JSON_PATH"),
        (log_dir, "LOG_DIR"),
    ):
        _assert_within_isolated_root(path, root, field_name)

    return IsolatedSmokeEnvironment(
        root=root,
        database_path=database_path,
        users_path=users_path,
        log_dir=log_dir,
    )


def main() -> int:
    validate_isolated_smoke_environment()
    print("isolated smoke environment accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
