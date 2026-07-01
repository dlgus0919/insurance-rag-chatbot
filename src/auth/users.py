"""사용자 저장소와 비밀번호 검증."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src import config

try:
    from passlib.hash import pbkdf2_sha256
except ImportError:  # pragma: no cover - 테스트 환경에 passlib가 없을 수 있다.

    class _Pbkdf2Sha256Fallback:
        """passlib 미설치 환경을 위한 최소 PBKDF2-SHA256 호환 래퍼."""

        rounds = 29000

        @classmethod
        def hash(cls, password: str) -> str:
            salt = secrets.token_bytes(16)
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, cls.rounds)
            salt_text = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
            digest_text = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
            return f"$pbkdf2-sha256${cls.rounds}${salt_text}${digest_text}"

        @classmethod
        def verify(cls, password: str, password_hash: str) -> bool:
            try:
                _, scheme, rounds_text, salt_text, digest_text = password_hash.split("$", 4)
                if scheme != "pbkdf2-sha256":
                    return False
                rounds = int(rounds_text)
                salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
                expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
            except Exception:
                return False
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
            return hmac.compare_digest(digest, expected)

    pbkdf2_sha256 = _Pbkdf2Sha256Fallback


USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
PASSWORD_MIN_LEN = 8
ROLE_EMPLOYEE = "employee"
ROLE_ADMIN = "admin"
VALID_ROLES = {ROLE_EMPLOYEE, ROLE_ADMIN}
VALID_STATUSES = {"active", "inactive", "locked"}


@dataclass
class User:
    """사용자 계정."""

    username: str
    password_hash: str
    role: str
    display_name: str
    created_at: str
    password_updated_at: str
    email: str | None = None
    status: str = "active"
    updated_at: str | None = None
    last_login: str | None = None

    def public_dict(self) -> dict:
        """비밀번호 해시를 제외한 공개 표현을 반환한다."""

        return {key: value for key, value in asdict(self).items() if key != "password_hash"}


class UserStoreError(Exception):
    """사용자 저장소 오류."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _users_path() -> Path:
    return Path(os.getenv("USERS_JSON_PATH", str(config.ROOT_DIR / "users.json")))


def _load_raw() -> dict:
    path = _users_path()
    if not path.exists():
        return {"version": 1, "users": []}
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except json.JSONDecodeError as exc:
        raise UserStoreError(f"사용자 파일 형식이 올바르지 않습니다: {path}") from exc
    raw.setdefault("version", 1)
    raw.setdefault("users", [])
    return raw


def _save_raw(data: dict) -> None:
    path = _users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except (PermissionError, OSError):
        pass


def list_users() -> list[User]:
    """등록된 모든 사용자를 반환한다."""

    raw = _load_raw()
    return [User(**_normalize_entry(entry)) for entry in raw.get("users", [])]


def get_user(username: str) -> User | None:
    """사용자명으로 사용자 한 명을 조회한다."""

    return next((user for user in list_users() if user.username == username), None)


def validate_password_strength(password: str) -> None:
    """비밀번호 길이 정책을 검증한다."""

    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LEN:
        raise UserStoreError(f"비밀번호는 최소 {PASSWORD_MIN_LEN}자 이상이어야 합니다.")


def _validate_display_name(display_name: str) -> None:
    if not display_name or len(display_name) > 64:
        raise UserStoreError("표시 이름은 1~64자여야 합니다.")


def add_user(
    username: str,
    password: str,
    role: str,
    display_name: str | None = None,
    email: str | None = None,
    status: str = "active",
) -> User:
    """새 사용자를 추가한다."""

    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise UserStoreError("사용자명은 영문/숫자/_ 조합 3~32자여야 합니다.")
    role = _normalize_role(role)
    if role not in VALID_ROLES:
        raise UserStoreError(f"role은 {sorted(VALID_ROLES)} 중 하나여야 합니다.")
    if status not in VALID_STATUSES:
        raise UserStoreError(f"status는 {sorted(VALID_STATUSES)} 중 하나여야 합니다.")
    validate_password_strength(password)
    selected_display_name = (display_name or username).strip()
    _validate_display_name(selected_display_name)
    if get_user(username) is not None:
        raise UserStoreError(f"이미 존재하는 사용자입니다: {username}")

    now = _now_iso()
    user = User(
        username=username,
        password_hash=pbkdf2_sha256.hash(password),
        role=role,
        display_name=selected_display_name,
        created_at=now,
        password_updated_at=now,
        email=(email or None),
        status=status,
        updated_at=now,
        last_login=None,
    )
    raw = _load_raw()
    raw.setdefault("users", []).append(asdict(user))
    _save_raw(raw)
    return user


def reset_password(username: str, new_password: str) -> None:
    """사용자 비밀번호를 재설정한다."""

    validate_password_strength(new_password)
    raw = _load_raw()
    for entry in raw.get("users", []):
        if entry.get("username") == username:
            entry["password_hash"] = pbkdf2_sha256.hash(new_password)
            entry["password_updated_at"] = _now_iso()
            entry["updated_at"] = entry["password_updated_at"]
            _save_raw(raw)
            return
    raise UserStoreError(f"사용자를 찾을 수 없습니다: {username}")


def update_user(
    username: str,
    *,
    display_name: str | None = None,
    email: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> User:
    """사용자 프로필, 역할, 상태를 갱신한다."""

    raw = _load_raw()
    for entry in raw.get("users", []):
        if entry.get("username") != username:
            continue
        if display_name is not None:
            selected_display_name = display_name.strip()
            _validate_display_name(selected_display_name)
            entry["display_name"] = selected_display_name
        if email is not None:
            entry["email"] = email.strip() or None
        if role is not None:
            normalized_role = _normalize_role(role)
            if normalized_role not in VALID_ROLES:
                raise UserStoreError(f"role은 {sorted(VALID_ROLES)} 중 하나여야 합니다.")
            entry["role"] = normalized_role
        if status is not None:
            if status not in VALID_STATUSES:
                raise UserStoreError(f"status는 {sorted(VALID_STATUSES)} 중 하나여야 합니다.")
            entry["status"] = status
        entry["updated_at"] = _now_iso()
        _save_raw(raw)
        return User(**_normalize_entry(entry))
    raise UserStoreError(f"사용자를 찾을 수 없습니다: {username}")


def delete_user(username: str) -> None:
    """사용자를 영구 삭제한다."""

    target = get_user(username)
    if target is None:
        raise UserStoreError(f"사용자를 찾을 수 없습니다: {username}")
    if target.role == ROLE_ADMIN:
        admin_count = sum(1 for user in list_users() if user.role == ROLE_ADMIN)
        if admin_count <= 1:
            raise UserStoreError("마지막 관리자 계정은 삭제할 수 없습니다.")

    raw = _load_raw()
    users = raw.get("users", [])
    new_users = [entry for entry in users if entry.get("username") != username]
    if len(new_users) == len(users):
        raise UserStoreError(f"사용자를 찾을 수 없습니다: {username}")
    raw["users"] = new_users
    _save_raw(raw)


def mark_login(username: str) -> None:
    """마지막 로그인 시각을 기록한다."""

    raw = _load_raw()
    now = _now_iso()
    for entry in raw.get("users", []):
        if entry.get("username") == username:
            entry["last_login"] = now
            entry["updated_at"] = now
            _save_raw(raw)
            return


def authenticate(username: str, password: str) -> User | None:
    """사용자명과 비밀번호를 검증한다."""

    user = get_user((username or "").strip())
    if user is None:
        return None
    if user.status != "active":
        return None
    if user.role not in VALID_ROLES:
        return None
    if pbkdf2_sha256.verify(password, user.password_hash):
        return user
    return None


def has_admin() -> bool:
    """관리자 계정이 하나 이상 존재하는지 반환한다."""

    return any(user.role == ROLE_ADMIN for user in list_users())


def _normalize_role(role: str) -> str:
    return ROLE_EMPLOYEE if role == "user" else role


def external_role(role: str) -> str:
    """API 응답용 역할 이름으로 변환한다."""

    return "user" if role == ROLE_EMPLOYEE else role


def _normalize_entry(entry: dict) -> dict:
    normalized = dict(entry)
    now = normalized.get("created_at") or _now_iso()
    normalized.setdefault("role", ROLE_EMPLOYEE)
    normalized["role"] = _normalize_role(normalized["role"])
    normalized.setdefault("display_name", normalized.get("username", ""))
    normalized.setdefault("created_at", now)
    normalized.setdefault("password_updated_at", now)
    normalized.setdefault("email", None)
    normalized.setdefault("status", "active")
    normalized.setdefault("updated_at", normalized.get("password_updated_at"))
    normalized.setdefault("last_login", None)
    return normalized
