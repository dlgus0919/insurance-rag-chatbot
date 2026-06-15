from pathlib import Path

from src.config import PdfSource
from src.parser.digital_pdf_tables import (
    extract_digital_pdf_table_chunks,
    load_digital_pdf_table_chunks,
    table_matrix_to_json,
    write_digital_pdf_table_artifacts,
)


def test_table_matrix_to_json_preserves_rows_without_header() -> None:
    table_json = table_matrix_to_json(
        [
            ["입원", "보장대상의료비의 80%"],
            ["통원", "1만원과 20% 중 큰 금액"],
        ]
    )

    assert table_json is not None
    assert table_json["headers"] == ["열1", "열2"]
    assert table_json["rows"][0]["열1"] == "입원"
    assert table_json["rows"][1]["열2"] == "1만원과 20% 중 큰 금액"


def test_extract_digital_pdf_table_chunks_from_text_layer(tmp_path: Path) -> None:
    import fitz

    pdf_path = tmp_path / "policy.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420, height=220)
    x0, y0 = 40, 60
    col_widths = [120, 220]
    row_height = 36
    for row in range(4):
        y = y0 + row * row_height
        page.draw_line((x0, y), (x0 + sum(col_widths), y))
    for x in (x0, x0 + col_widths[0], x0 + sum(col_widths)):
        page.draw_line((x, y0), (x, y0 + 3 * row_height))
    page.insert_text((55, 82), "구분", fontsize=10)
    page.insert_text((175, 82), "보상금액", fontsize=10)
    page.insert_text((55, 118), "입원", fontsize=10)
    page.insert_text((175, 118), "비급여 의료비의 70%", fontsize=10)
    page.insert_text((55, 154), "통원", fontsize=10)
    page.insert_text((175, 154), "3만원과 30% 중 큰 금액", fontsize=10)
    doc.save(pdf_path)
    doc.close()

    source = PdfSource(
        path=pdf_path,
        doc_type="insurance_policy",
        doc_name="테스트 약관",
        doc_short="테스트약관",
    )

    chunks, summary = extract_digital_pdf_table_chunks(source)

    assert summary.pages_seen == 1
    assert summary.table_chunks >= 1
    assert chunks[0].metadata["content_type"] == "table"
    assert chunks[0].metadata["source_method"] == "digital_pdf_table"
    assert "70%" in chunks[0].text


def test_write_and_load_digital_pdf_table_artifacts(tmp_path: Path) -> None:
    chunk_payload = table_matrix_to_json([["구분", "보상금액"], ["입원", "보장대상의료비의 80%"]])
    assert chunk_payload is not None
    source = PdfSource(
        path=tmp_path / "policy.pdf",
        doc_type="insurance_policy",
        doc_name="테스트 약관",
        doc_short="테스트약관",
    )
    from src.parser.chunker import Chunk
    import json

    chunk = Chunk(
        id="테스트약관_tbl_000000",
        text="구분 | 보상금액\n입원 | 보장대상의료비의 80%",
        metadata={
            "doc_short": source.doc_short,
            "doc_name": source.doc_name,
            "doc_type": source.doc_type,
            "pdf_filename": source.path.name,
            "page_start": 1,
            "content_type": "table",
            "source_method": "digital_pdf_table",
            "table_json": json.dumps(chunk_payload, ensure_ascii=False),
        },
    )

    manifest_path = write_digital_pdf_table_artifacts([chunk], tmp_path / "extracted", "테스트약관")
    loaded = load_digital_pdf_table_chunks(tmp_path / "extracted")

    assert manifest_path.exists()
    assert loaded[0].id == chunk.id
    assert loaded[0].metadata["source_method"] == "digital_pdf_table"
