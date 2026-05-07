from pathlib import Path
import sqlite3

from openpyxl import Workbook

from scripts.build_relational_db import EXPECTED_COLUMNS, build_database
from src.db.standard_codes import list_categories, lookup_by_std_cd, search_by_name


def _write_sample_workbook(path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Result 1"
    worksheet.append([f"한글_{index}" for index, _ in enumerate(EXPECTED_COLUMNS)])
    worksheet.append(EXPECTED_COLUMNS)
    worksheet.append(
        [
            "050000011",
            "D3베이스주100,000IU(콜레칼시페롤)_(2.5mg/1mL)",
            "HDR000311",
            "비타민A 및 D제",
            "NB",
            "비급여",
            "NB2",
            "비급여_특약2",
            "RE08",
            "주사료 약품비",
            "DE12",
            "영양제/호르몬/불임/의약외품",
            "PM0102",
            "추가확인 후 보상",
            "CR30",
            "추가확인",
            "비타민 D 결핍의 예방과 치료",
            "",
            "sample.xlsx",
            "2023-01-01",
            "9999-12-31",
            "2023-12-01",
            "INSERT",
        ]
    )
    worksheet.append(
        [
            "050000011",
            "중복 표준코드",
            "HDR000311",
            "비타민A 및 D제",
            "NB",
            "비급여",
            "NB2",
            "비급여_특약2",
            "RE08",
            "주사료 약품비",
            "DE12",
            "영양제/호르몬/불임/의약외품",
            "PM0102",
            "추가확인 후 보상",
            "CR30",
            "추가확인",
            "",
            "",
            "sample.xlsx",
            "2023-01-01",
            "9999-12-31",
            "2023-12-01",
            "INSERT",
        ]
    )
    worksheet.append(
        [
            "A1000001",
            "테스트 치료재료",
            "HDR000400",
            "치료재료",
            "NB",
            "비급여",
            "NB1",
            "비급여_특약1",
            "RE99",
            "재료대",
            "DE99",
            "기타",
            "PM9999",
            "기타",
            "CR99",
            "확인필요",
            "",
            "",
            "sample.xlsx",
            "2024-01-01",
            "9999-12-31",
            "2024-01-01",
            "INSERT",
        ]
    )
    workbook.save(path)


def test_build_database_and_lookup_helpers(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "nonpay.xlsx"
    db_path = tmp_path / "standard_codes.sqlite"
    _write_sample_workbook(xlsx_path)

    stats = build_database(xlsx_path, db_path, batch_size=2)

    assert stats.source_rows == 3
    assert stats.inserted_rows == 2
    assert stats.duplicate_std_cd_rows == 1

    row = lookup_by_std_cd("050000011", db_path=db_path)
    assert row is not None
    assert row["std_cd_nm"].startswith("D3베이스주")
    assert row["mid_category_cd_nm"] == "비타민A 및 D제"

    assert lookup_by_std_cd("없음", db_path=db_path) is None
    assert search_by_name("치료재료", db_path=db_path)[0]["std_cd"] == "A1000001"
    assert ("HDR000311", "비타민A 및 D제") in list_categories(db_path=db_path)


def test_build_database_creates_required_indexes(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "nonpay.xlsx"
    db_path = tmp_path / "standard_codes.sqlite"
    _write_sample_workbook(xlsx_path)
    build_database(xlsx_path, db_path)

    with sqlite3.connect(db_path) as connection:
        indexes = {row[1]: row[2] for row in connection.execute("PRAGMA index_list(nonpay_standard)").fetchall()}

    assert indexes["idx_nonpay_standard_std_cd"] == 1
    assert "idx_nonpay_standard_mid_category_cd" in indexes
    assert "idx_nonpay_standard_medical_class_cd" in indexes
    assert "idx_nonpay_standard_apply_start_date" in indexes
