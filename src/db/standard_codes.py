"""비급여 표준 코드 SQLite 조회 헬퍼."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from src import config

DEFAULT_DB_PATH = config.STANDARD_CODES_DB_PATH


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    selected_path = Path(db_path or DEFAULT_DB_PATH)
    if not selected_path.exists():
        raise FileNotFoundError(f"비급여 표준 코드 DB가 없습니다: {selected_path}")
    connection = sqlite3.connect(selected_path)
    connection.row_factory = sqlite3.Row
    return connection


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def lookup_by_std_cd(std_cd: str, db_path: Path | None = None) -> dict | None:
    """표준코드로 단일 비급여 표준 모델 행을 조회한다."""

    normalized = std_cd.strip()
    if not normalized:
        return None
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM nonpay_standard WHERE std_cd = ?",
            (normalized,),
        ).fetchone()
    return _row_to_dict(row)


def search_by_name(keyword: str, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    """표준명 또는 표준코드에 keyword가 포함된 행을 조회한다."""

    normalized = keyword.strip()
    if not normalized or limit <= 0:
        return []
    capped_limit = min(limit, 500)
    pattern = f"%{normalized}%"
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM nonpay_standard
            WHERE std_cd_nm LIKE ? OR std_cd LIKE ?
            ORDER BY
                CASE
                    WHEN std_cd = ? THEN 0
                    WHEN std_cd_nm = ? THEN 1
                    ELSE 2
                END,
                std_cd
            LIMIT ?
            """,
            (pattern, pattern, normalized, normalized, capped_limit),
        ).fetchall()
    return [dict(row) for row in rows]


def list_categories(db_path: Path | None = None) -> list[tuple[str, str]]:
    """중분류 코드와 이름 목록을 반환한다."""

    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT mid_category_cd, mid_category_cd_nm
            FROM nonpay_standard
            WHERE mid_category_cd != ''
            GROUP BY mid_category_cd, mid_category_cd_nm
            ORDER BY mid_category_cd
            """
        ).fetchall()
    return [(row["mid_category_cd"], row["mid_category_cd_nm"]) for row in rows]
