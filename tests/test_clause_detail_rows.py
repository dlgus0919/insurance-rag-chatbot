import json

from scripts.build_clause_detail_rows import build_clause_detail_rows
from src.parser.chunker import Chunk
from src.parser.digital_pdf_tables import write_digital_pdf_table_artifacts
from src.rag.clause_detail_rows import ClauseDetailRowRecord, ClauseDetailRowStore
from src.rag.pipeline import (
    _deterministic_guard_answer,
    _extract_clause_detail_manifest_rows,
)


def test_build_clause_detail_rows_manifest_from_table_json(tmp_path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    output_path = tmp_path / "clause_detail_rows.jsonl"
    table_json = {
        "headers": ["보장종목", "보상기준", "자기부담금"],
        "rows": [
            {
                "보장종목": "급여(상해·질병) 입원치료",
                "보상기준": "보장대상의료비의 80%",
                "자기부담금": "보장대상의료비의 20%",
            }
        ],
        "avg_confidence": 0.98,
    }
    chunks_path.write_text(
        json.dumps(
            {
                "id": "약관_ch_table",
                "text": "제3조(보장종목별 보상내용) <표1>",
                "metadata": {
                    "doc_short": "약관",
                    "page_start": 31,
                    "section": "제3조(보장종목별 보상내용)",
                    "content_type": "table",
                    "table_json": json.dumps(table_json, ensure_ascii=False),
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_clause_detail_rows(chunks_path, output_path)
    records = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    store = ClauseDetailRowStore(output_path)

    assert summary["chunks_seen"] == 1
    assert summary["table_chunks_seen"] == 1
    assert summary["rows_written"] == 1
    assert records[0]["doc_short"] == "약관"
    assert records[0]["article"] == "제3조"
    assert records[0]["table_label"] == "<표1>"
    assert records[0]["row_label"] == "급여(상해·질병) 입원치료"
    assert records[0]["numbers"] == ["80%", "20%"]
    assert store.is_available() is True
    assert store.records()[0].value_text == records[0]["value_text"]


def test_clause_detail_manifest_rows_feed_deterministic_answer() -> None:
    record = ClauseDetailRowRecord(
        row_id="cdr.test",
        doc_short="약관",
        article="제3조",
        table_label="<표1>",
        page=31,
        chunk_id="약관_ch_table",
        parent_heading="제3조(보장종목별 보상내용)",
        row_label="급여(상해·질병) 통원치료",
        value_text="보장종목: 급여(상해·질병) 통원치료 | 자기부담금: 1~2만원과 보장대상의료비의 20% 중 큰 금액",
        numbers=["1~2만원", "20%"],
        source_metadata={"source": "clause_detail_rows"},
    )

    rows = _extract_clause_detail_manifest_rows(
        "급여 통원치료의 자기부담금은 어떻게 산정하나?",
        (record,),
        ["deductible"],
        doc_filter=["약관"],
    )
    answer = _deterministic_guard_answer(
        "급여 통원치료의 자기부담금은 어떻게 산정하나?",
        [],
        clause_detail_rows=rows,
    )

    assert rows
    assert rows[0].source_kind == "clause_detail_rows"
    assert answer is not None
    assert "1~2만원" in answer
    assert "20%" in answer
    assert "source=clause_detail_rows row_id=cdr.test" in answer


def test_build_clause_detail_rows_includes_digital_pdf_table_artifacts(tmp_path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    chunks_path.write_text("", encoding="utf-8")
    output_path = tmp_path / "clause_detail_rows.jsonl"
    table_json = {
        "headers": ["구분", "보상금액"],
        "rows": [{"구분": "상급병실료 차액", "보상금액": "비급여 병실료의 50%, 1일 평균금액 10만원 한도"}],
    }
    chunk = Chunk(
        id="약관_tbl_000001",
        text="구분 | 보상금액\n상급병실료 차액 | 비급여 병실료의 50%, 1일 평균금액 10만원 한도",
        metadata={
            "doc_short": "약관",
            "page_start": 71,
            "section": "제3조(보장종목별 보상내용)",
            "content_type": "table",
            "source_method": "digital_pdf_table",
            "table_json": json.dumps(table_json, ensure_ascii=False),
        },
    )
    digital_root = tmp_path / "extracted_digital_pdf"
    write_digital_pdf_table_artifacts([chunk], digital_root, "약관")

    summary = build_clause_detail_rows(chunks_path, output_path, digital_table_root=digital_root)
    records = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]

    assert summary["digital_table_chunks_seen"] == 1
    assert summary["rows_written"] == 1
    assert records[0]["doc_short"] == "약관"
    assert records[0]["numbers"] == ["50%", "10만원"]
    assert records[0]["source_metadata"]["source"] == "digital_pdf_table"
