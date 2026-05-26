#!/usr/bin/env python3
"""사용자 관리 CLI."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.auth import users as user_store


def _prompt_password(label: str = "비밀번호") -> str:
    """비밀번호를 확인 입력까지 받아 검증한다."""

    while True:
        password = getpass.getpass(f"{label}: ")
        confirm = getpass.getpass(f"{label} 확인: ")
        if password != confirm:
            print("비밀번호가 일치하지 않습니다. 다시 입력하세요.")
            continue
        try:
            user_store.validate_password_strength(password)
        except user_store.UserStoreError as exc:
            print(f"  ! {exc}")
            continue
        return password


def cmd_init(args) -> int:
    """첫 관리자 계정을 만든다."""

    if user_store.has_admin():
        print("이미 관리자 계정이 존재합니다. add 명령을 사용하세요.")
        return 1
    print("첫 시스템 관리자 계정을 생성합니다.")
    username = input("관리자 사용자명 (영문/숫자/_ 3~32자): ").strip()
    display = input(f"표시 이름 [{username}]: ").strip() or username
    password = _prompt_password()
    user_store.add_user(username, password, role=user_store.ROLE_ADMIN, display_name=display)
    print(f"관리자 '{username}'을(를) 생성했습니다.")
    return 0


def cmd_add(args) -> int:
    """사용자를 추가한다."""

    display = input(f"표시 이름 [{args.username}]: ").strip() or args.username
    password = _prompt_password()
    user_store.add_user(args.username, password, role=args.role, display_name=display)
    print(f"사용자 '{args.username}' ({args.role})을(를) 생성했습니다.")
    return 0


def cmd_reset(args) -> int:
    """사용자 비밀번호를 재설정한다."""

    password = _prompt_password("새 비밀번호")
    user_store.reset_password(args.username, password)
    print(f"'{args.username}' 비밀번호를 재설정했습니다.")
    return 0


def cmd_list(args) -> int:
    """사용자 목록을 출력한다."""

    rows = user_store.list_users()
    if not rows:
        print("(등록된 사용자 없음)")
        return 0
    for user in rows:
        print(f"- {user.username} | {user.role} | {user.display_name} | created={user.created_at}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="사용자 관리 CLI")
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    subparsers.add_parser("init")

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("username")
    add_parser.add_argument("role", choices=[user_store.ROLE_EMPLOYEE, user_store.ROLE_ADMIN, user_store.ROLE_VIEWER])

    reset_parser = subparsers.add_parser("reset")
    reset_parser.add_argument("username")

    subparsers.add_parser("list")

    args = parser.parse_args(argv)
    return {
        "init": cmd_init,
        "add": cmd_add,
        "reset": cmd_reset,
        "list": cmd_list,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
