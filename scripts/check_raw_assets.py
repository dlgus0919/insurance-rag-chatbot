#!/usr/bin/env python3
"""커밋 예정 목록에 원본 자료가 포함되었는지 검사한다."""

from __future__ import annotations

import subprocess
import sys

BLOCKED_SUFFIXES = (".pdf", ".xlsx", ".xls")
BLOCKED_DIRS = (
    "data/raw/",
    "data/extracted/",
    "backup/",
    "data/chat_history/",
)
BLOCKED_EXACT = {
    ".env",
    "assets.zip",
    "users.json",
    "users.json.tmp",
}


def normalize_git_path(path: str) -> str:
    """git 출력 경로를 슬래시 기준 상대 경로로 정규화한다."""

    return path.replace("\\", "/").lstrip("./")


def is_blocked_path(path: str) -> bool:
    """원본 자료 또는 배포 금지 산출물 경로인지 확인한다."""

    normalized = normalize_git_path(path)
    lowered = normalized.lower()
    if normalized.endswith("/.gitkeep"):
        return False
    if normalized in BLOCKED_EXACT:
        return True
    if lowered.endswith(BLOCKED_SUFFIXES):
        return True
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in BLOCKED_DIRS)


def staged_paths() -> list[str]:
    """삭제가 아닌 staged 파일 경로 목록을 반환한다."""

    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    blocked = [path for path in staged_paths() if is_blocked_path(path)]
    if not blocked:
        print("OK: staged 원본 자료 없음")
        return 0

    print("ERROR: GitHub에 올리면 안 되는 원본/민감 자료가 staged 상태입니다.", file=sys.stderr)
    for path in blocked:
        print(f"- {path}", file=sys.stderr)
    print("해당 파일은 stage에서 제거하고, 필요하면 GitHub Release나 사내 저장소로 분리하세요.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
