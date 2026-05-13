from pathlib import Path

import pandas as pd
import pytest

from src.rag.table_store import TableStore


@pytest.fixture
def sample_surgery_df(tmp_path: Path) -> Path:
    df = pd.DataFrame(
        [
            {
                "수술명": "충수절제술(맹장 수술)",
                "수술명_원문": "충수절제술",
                "수술해설": "맹장과 충수를 절제하는 수술",
                "종_1_3": "1",
                "종_1_5": "2",
                "종_신1_5": "2",
                "source_page_label": 109,
                "source_file": "p108_t00.json",
                "table_type": "surgery_grade",
                "table_group_id": "수술종수표",
                "group_page_range": "33-175",
                "is_page_continued": True,
            },
        ]
    )
    path = tmp_path / "surgery_grades.parquet"
    df.to_parquet(path)
    return path


@pytest.fixture
def sample_disability_df(tmp_path: Path) -> Path:
    df = pd.DataFrame(
        [
            {
                "신체부위": "팔의 장해",
                "장해분류": "한 팔의 손목 이상을 잃었을 때",
                "장해분류_원문": "한 팔의 손목 이상을 잃었을 때",
                "지급률": "60",
                "지급률_원문": "60%",
                "지급률_범위_최소": None,
                "지급률_범위_최대": None,
                "source_page_label": 255,
                "source_file": "p254_t00.json",
                "table_type": "disability_rate",
                "table_group_id": "팔의 장해",
                "is_page_continued": False,
            },
        ]
    )
    path = tmp_path / "disability_rates.parquet"
    df.to_parquet(path)
    return path


def test_lookup_surgery_grade_exact(sample_surgery_df: Path, sample_disability_df: Path) -> None:
    store = TableStore(surgery_path=sample_surgery_df, disability_path=sample_disability_df)

    result = store.lookup_surgery_grade("충수절제술")

    assert result is not None
    assert result["종_1_5"] == "2"
    assert result["source_page_label"] == 109


def test_lookup_surgery_grade_no_match(sample_surgery_df: Path, sample_disability_df: Path) -> None:
    store = TableStore(surgery_path=sample_surgery_df, disability_path=sample_disability_df)

    result = store.lookup_surgery_grade("우주유영수술")

    assert result is None


def test_lookup_disability_rate_exact(sample_surgery_df: Path, sample_disability_df: Path) -> None:
    store = TableStore(surgery_path=sample_surgery_df, disability_path=sample_disability_df)

    result = store.lookup_disability_rate("손목 이상을 잃었을 때")

    assert result is not None
    assert result["지급률"] == "60"
    assert result["신체부위"] == "팔의 장해"


def test_table_store_unavailable_when_no_parquet(tmp_path: Path) -> None:
    store = TableStore(
        surgery_path=tmp_path / "nonexistent.parquet",
        disability_path=tmp_path / "nonexistent2.parquet",
    )

    assert not store.is_available()


def test_lookup_returns_none_when_unavailable(tmp_path: Path) -> None:
    store = TableStore(
        surgery_path=tmp_path / "nonexistent.parquet",
        disability_path=tmp_path / "nonexistent2.parquet",
    )

    assert store.lookup_surgery_grade("충수절제술") is None
    assert store.lookup_disability_rate("두 눈") is None
