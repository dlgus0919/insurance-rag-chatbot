"""Parquet-backed deterministic lookup for insurance table rows."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd


SURGERY_GRADES_PATH = Path("data/index/surgery_grades.parquet")
DISABILITY_RATES_PATH = Path("data/index/disability_rates.parquet")
_MIDDLE_DOT_PATTERN = re.compile(r"[\s\u00B7\u2022\u2027\u22C5\u30FB\uFF65]")
_GRADE_COLUMNS = ("종_1_3", "종_1_5", "종_신1_5")
_PARENTHETICAL_ALIAS_PATTERN = re.compile(r"([^\s()\[\],]{2,})\(([^()\[\],]{2,})\)")
_MIN_CANDIDATE_MATCH_SPAN_RATIO = 0.6
_CANDIDATE_SCORE_FRACTION = 0.8


def _normalize_lookup_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return _MIDDLE_DOT_PATTERN.sub("", text).lower()


def _clean_record(record: dict) -> dict:
    cleaned: dict = {}
    for key, value in record.items():
        cleaned[key] = None if pd.isna(value) else value
    return cleaned


def _surgery_name_variants(record: dict[str, Any]) -> set[str]:
    """원문 표에 명시된 수술명과 괄호 안 병기만 정확 일치 후보로 사용한다."""

    variants: set[str] = set()
    for field in ("수술명", "수술명_원문"):
        value = str(record.get(field, "") or "")
        if not value:
            continue
        variants.add(_normalize_lookup_text(value))
        variants.add(_normalize_lookup_text(re.split(r"[([]", value, maxsplit=1)[0]))
        for part in re.split(r"[()\[\]=,\n]+", value):
            normalized = _normalize_lookup_text(part)
            if normalized:
                variants.add(normalized)
    return {variant for variant in variants if variant}


def _has_surgery_grade(record: dict[str, Any]) -> bool:
    return any(str(record.get(column, "N")) != "N" for column in _GRADE_COLUMNS)


def _source_parenthetical_aliases(records: pd.DataFrame) -> set[tuple[str, str]]:
    """Return candidate-only lexical variants explicitly written in source text."""

    aliases: set[tuple[str, str]] = set()
    for field in ("수술명", "수술명_원문", "수술해설"):
        if field not in records.columns:
            continue
        for value in records[field].dropna():
            for raw_term, raw_alias in _PARENTHETICAL_ALIAS_PATTERN.findall(str(value)):
                term = _normalize_lookup_text(raw_term)
                alias = _normalize_lookup_text(raw_alias)
                if term and alias and term != alias:
                    aliases.add((term, alias))
                    aliases.add((alias, term))
    return aliases


def _query_variants_from_source_aliases(query: str, aliases: set[tuple[str, str]]) -> set[str]:
    variants = {query}
    for term, alias in aliases:
        if term in query:
            variants.add(query.replace(term, alias))
    return variants


def _best_candidate_match(query_variants: set[str], name: str) -> tuple[float, float]:
    best_score = 0.0
    best_span_ratio = 0.0
    for query in query_variants:
        if not query:
            continue
        matcher = SequenceMatcher(a=query, b=name)
        score = matcher.ratio()
        span_size = matcher.find_longest_match(0, len(query), 0, len(name)).size
        span_ratio = span_size / len(query)
        if (score, span_ratio) > (best_score, best_span_ratio):
            best_score = score
            best_span_ratio = span_ratio
    return best_score, best_span_ratio


def _has_source_variant_match(query_variants: set[str], record: dict[str, Any]) -> bool:
    source_text = _normalize_lookup_text(
        " ".join(str(record.get(field, "") or "") for field in ("수술명", "수술명_원문", "수술해설"))
    )
    return any(variant and variant in source_text for variant in query_variants)


def _is_subsequence(shorter: str, longer: str) -> bool:
    index = 0
    for character in longer:
        if index < len(shorter) and shorter[index] == character:
            index += 1
    return index == len(shorter)


def _is_same_source_variant(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_source = str(left.get("source_file") or "")
    if not left_source or left_source != str(right.get("source_file") or ""):
        return False
    if tuple(str(left.get(column) or "") for column in _GRADE_COLUMNS) != tuple(
        str(right.get(column) or "") for column in _GRADE_COLUMNS
    ):
        return False
    left_name = _normalize_lookup_text(left.get("수술명"))
    right_name = _normalize_lookup_text(right.get("수술명"))
    return bool(left_name and right_name) and (
        _is_subsequence(left_name, right_name) or _is_subsequence(right_name, left_name)
    )


def _source_variant_representatives(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse source-table spelling variants without turning them into aliases."""

    groups: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        group = next(
            (group for group in groups if any(_is_same_source_variant(candidate, item) for item in group)),
            None,
        )
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)

    representatives: list[dict[str, Any]] = []
    for group in groups:
        representative = min(
            group,
            key=lambda item: (
                len(_normalize_lookup_text(item.get("수술명"))),
                _normalize_lookup_text(item.get("수술명")),
            ),
        ).copy()
        representative["match_score"] = round(max(float(item["match_score"]) for item in group), 4)
        representative["source_variant_match"] = any(bool(item.get("source_variant_match")) for item in group)
        representatives.append(representative)
    return representatives


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

    def lookup_surgery_grade_exact(self, surgery_name: str) -> dict | None:
        """원문 표에 명시된 단일 수술명 또는 병기 별칭만 확정 조회한다."""

        df = self._load_surgery()
        query = _normalize_lookup_text(surgery_name)
        if df is None or df.empty or not query or "수술명" not in df:
            return None

        matches = [
            _clean_record(row.to_dict())
            for _, row in df.iterrows()
            if _has_surgery_grade(row) and query in _surgery_name_variants(row.to_dict())
        ]
        if not matches:
            return None

        canonical_names = {_normalize_lookup_text(row.get("수술명")) for row in matches}
        return matches[0] if len(canonical_names) == 1 else None

    def search_surgery_grade_candidates(self, surgery_name: str, *, limit: int = 3) -> list[dict]:
        """근거 표의 유사 수술명을 후보로만 반환한다. 첫 부분 일치를 확정하지 않는다."""

        df = self._load_surgery()
        query = _normalize_lookup_text(surgery_name)
        if df is None or df.empty or not query or "수술명" not in df or limit < 1:
            return []

        query_variants = _query_variants_from_source_aliases(query, _source_parenthetical_aliases(df))
        candidates: list[dict] = []
        for _, row in df.iterrows():
            record = _clean_record(row.to_dict())
            if not _has_surgery_grade(record):
                continue
            name = _normalize_lookup_text(record.get("수술명"))
            if not name or name == query:
                continue
            score, span_ratio = _best_candidate_match(query_variants, name)
            if score < 0.45 or span_ratio < _MIN_CANDIDATE_MATCH_SPAN_RATIO:
                continue
            record["match_score"] = round(score, 4)
            record["source_variant_match"] = _has_source_variant_match(query_variants, record)
            candidates.append(record)

        candidates = _source_variant_representatives(candidates)
        if candidates:
            best_match_score = max(float(record["match_score"]) for record in candidates)
            candidates = [
                record
                for record in candidates
                if record.get("source_variant_match")
                or float(record["match_score"]) >= best_match_score * _CANDIDATE_SCORE_FRACTION
            ]
        candidates.sort(
            key=lambda record: (
                -int(bool(record.get("source_variant_match"))),
                -float(record["match_score"]),
                str(record.get("수술명", "")),
            )
        )
        return candidates[:limit]

    def lookup_surgery_grade(self, surgery_name: str) -> dict | None:
        """호환용 정확 수술종수 조회. 유사 이름은 자동 확정하지 않는다."""

        return self.lookup_surgery_grade_exact(surgery_name)

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
