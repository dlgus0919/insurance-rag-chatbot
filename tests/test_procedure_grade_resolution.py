from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.rag.procedure_grade import resolve_procedure_grade
from src.rag.table_store import TableStore


def _store(tmp_path: Path) -> TableStore:
    surgery_path = tmp_path / "surgery_grades.parquet"
    disability_path = tmp_path / "disability_rates.parquet"
    pd.DataFrame(
        [
            {
                "수술명": "결장폴립절제술",
                "수술명_원문": "결장폴립절제술",
                "수술해설": "개복하여 결장에 양성종양이 국한되어 있는 경우 이를 절제해 내는 수술",
                "종_1_3": "2",
                "종_1_5": "4",
                "종_신1_5": "4",
                "source_page_label": "110",
            },
            {
                "수술명": "결장경하 폴립절제술",
                "수술명_원문": "결장경하 폴립절제술",
                "수술해설": "결장내 폴립(용종)을 결장경을 이용해 절제해내는 수술",
                "종_1_3": "1",
                "종_1_5": "2",
                "종_신1_5": "1",
                "source_page_label": "167",
            },
        ]
    ).to_parquet(surgery_path)
    pd.DataFrame({"장해분류": [], "지급률": []}).to_parquet(disability_path)
    return TableStore(surgery_path=surgery_path, disability_path=disability_path)


def _ambiguous_procedure_store(tmp_path: Path) -> TableStore:
    surgery_path = tmp_path / "surgery_grades.parquet"
    disability_path = tmp_path / "disability_rates.parquet"
    pd.DataFrame(
        [
            {
                "수술명": "결장폴립절제술",
                "수술명_원문": "결장폴립절제술",
                "수술해설": "개복하여 결장에 양성종양이 국한되어 있는 경우 이를 절제해 내는 수술",
                "종_1_3": "2",
                "종_1_5": "4",
                "종_신1_5": "4",
                "source_page_label": "110",
                "source_file": "p109_t01.json",
            },
            {
                "수술명": "결장경하 폴립절제술",
                "수술명_원문": "결장경하 폴립절제술",
                "수술해설": "결장내 폴립(용종)을 결장경을 이용해 절제해내는 수술",
                "종_1_3": "1",
                "종_1_5": "2",
                "종_신1_5": "1",
                "source_page_label": "167",
                "source_file": "p166_t00.json",
            },
            {
                "수술명": "결장경하 대장폴립 절제술",
                "수술명_원문": "결장경하 대장폴립 절제술",
                "수술해설": "결장경을 이용하여 대장내 폴립(용종)을 절제해내는 수술",
                "종_1_3": "1",
                "종_1_5": "2",
                "종_신1_5": "1",
                "source_page_label": "167",
                "source_file": "p166_t00.json",
            },
            {
                "수술명": "직장폴립절제술",
                "수술명_원문": "직장폴립절제술",
                "수술해설": "직장내 폴립(용종)을 절제해내는 수술",
                "종_1_3": "1",
                "종_1_5": "2",
                "종_신1_5": "1",
                "source_page_label": "167",
                "source_file": "p166_t00.json",
            },
            {
                "수술명": "대장절제술",
                "수술명_원문": "대장절제술",
                "수술해설": "대장에 병변이 있는 경우 대장을 절제해내는 수술",
                "종_1_3": "3",
                "종_1_5": "5",
                "종_신1_5": "5",
                "source_page_label": "120",
                "source_file": "p119_t00.json",
            },
            {
                "수술명": "관혈적 위폴립 절제술",
                "수술명_원문": "관혈적 위폴립 절제술",
                "수술해설": "관혈로 위의 양성종양을 절제하는 수술",
                "종_1_3": "2",
                "종_1_5": "3",
                "종_신1_5": "3",
                "source_page_label": "101",
                "source_file": "p100_t01.json",
            },
        ]
    ).to_parquet(surgery_path)
    pd.DataFrame({"장해분류": [], "지급률": []}).to_parquet(disability_path)
    return TableStore(surgery_path=surgery_path, disability_path=disability_path)


def test_exact_open_colon_polypectomy_is_fourth_grade(tmp_path: Path) -> None:
    result = resolve_procedure_grade("결장폴립절제술은 1~5종에서 몇종으로 줘?", table_store=_store(tmp_path))

    assert result.status == "confirmed"
    assert result.selected is not None
    assert result.selected.canonical_name == "결장폴립절제술"
    assert result.selected.grades["1-5종"] == "4종"
    assert result.selected.source_page == "110"


def test_exact_endoscopic_colon_polypectomy_is_second_grade(tmp_path: Path) -> None:
    result = resolve_procedure_grade("결장경하 폴립절제술 종수를 알려줘", table_store=_store(tmp_path))

    assert result.status == "confirmed"
    assert result.selected is not None
    assert result.selected.canonical_name == "결장경하 폴립절제술"
    assert result.selected.grades["1-5종"] == "2종"
    assert result.selected.source_page == "167"


def test_unapproved_colon_polyp_synonym_requires_procedure_confirmation(tmp_path: Path) -> None:
    result = resolve_procedure_grade("대장용종절제술은 1~5종에서 몇종으로 줘?", table_store=_store(tmp_path))

    assert result.status == "candidate_pending"
    assert {item.canonical_name for item in result.candidates} == {"결장폴립절제술", "결장경하 폴립절제술"}
    assert "결장경" in result.clarification_question or "내시경" in result.clarification_question


def test_source_backed_parenthetical_variant_ranks_procedure_candidates(tmp_path: Path) -> None:
    result = resolve_procedure_grade(
        "대장용종절제술은 1~5종에서 몇종으로 줘?",
        table_store=_ambiguous_procedure_store(tmp_path),
    )

    assert result.status == "candidate_pending"
    assert {item.canonical_name for item in result.candidates} == {"결장폴립절제술", "결장경하 폴립절제술"}
    assert "결장경" in result.clarification_question or "내시경" in result.clarification_question


def test_q7701_requires_grounded_procedure_bridge(tmp_path: Path) -> None:
    result = resolve_procedure_grade("Q7701의 수술종수는?", table_store=_store(tmp_path))

    assert result.status == "candidate_pending"
    assert result.selected is None
    assert "연결 근거" in result.clarification_question
