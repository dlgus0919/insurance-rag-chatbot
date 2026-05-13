"""Parquet-backed deterministic lookup for insurance table rows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


SURGERY_GRADES_PATH = Path("data/index/surgery_grades.parquet")
DISABILITY_RATES_PATH = Path("data/index/disability_rates.parquet")


def _normalize_lookup_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", "", text).lower()


def _clean_record(record: dict) -> dict:
    cleaned: dict = {}
    for key, value in record.items():
        cleaned[key] = None if pd.isna(value) else value
    return cleaned


class TableStore:
    """Parquet 기반 수술종수·장해분류 직접 조회 인터페이스."""

    def __init__(
        self,
        surgery_path: Path = SURGERY_GRADES_PATH,
        disability_path: Path = DISABILITY_RATES_PATH,
    ):
        self._surgery_df: pd.DataFrame | None = None
        self._disability_df: pd.DataFrame | None = None
        self._surgery_path = Path(surgery_path)
        self._disability_path = Path(disability_path)

    def is_available(self) -> bool:
        return self._surgery_path.exists() and self._disability_path.exists()

    def _load_surgery(self) -> pd.DataFrame | None:
        if not self._surgery_path.exists():
            return None
        if self._surgery_df is None:
            try:
                self._surgery_df = pd.read_parquet(self._surgery_path)
            except Exception:
                return None
        return self._surgery_df

    def _load_disability(self) -> pd.DataFrame | None:
        if not self._disability_path.exists():
            return None
        if self._disability_df is None:
            try:
                self._disability_df = pd.read_parquet(self._disability_path)
            except Exception:
                return None
        return self._disability_df

    def lookup_surgery_grade(self, surgery_name: str) -> dict | None:
        """수술명으로 수술종수 행을 부분 일치 조회한다."""

        df = self._load_surgery()
        query = _normalize_lookup_text(surgery_name)
        if df is None or df.empty or not query or "수술명" not in df:
            return None

        names = df["수술명"].map(_normalize_lookup_text)
        mask = names.str.contains(query, na=False, regex=False) | names.map(lambda name: bool(name and name in query))

        if not mask.any():
            for token in [_normalize_lookup_text(token) for token in str(surgery_name).split()]:
                if len(token) < 2:
                    continue
                mask = names.str.contains(token, na=False, regex=False)
                if mask.any():
                    break

        hits = df[mask]
        if hits.empty:
            return None
        return _clean_record(hits.iloc[0].to_dict())

    def lookup_disability_rate(self, query_region: str) -> dict | None:
        """장해 부위/유형 문자열로 장해분류 행을 부분 일치 조회한다."""

        df = self._load_disability()
        query = _normalize_lookup_text(query_region)
        if df is None or df.empty or not query or "장해분류" not in df or "지급률" not in df:
            return None

        valid = df[df["지급률"].notna() & (df["지급률"].astype(str) != "")]
        categories = valid["장해분류"].map(_normalize_lookup_text)
        mask = categories.str.contains(query, na=False, regex=False) | categories.map(
            lambda category: bool(category and category in query)
        )

        if not mask.any():
            for token in [_normalize_lookup_text(token) for token in str(query_region).split()]:
                if len(token) < 2:
                    continue
                mask = categories.str.contains(token, na=False, regex=False)
                if mask.any():
                    break

        hits = valid[mask]
        if hits.empty:
            return None
        return _clean_record(hits.iloc[0].to_dict())
