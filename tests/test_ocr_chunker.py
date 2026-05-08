import json
from pathlib import Path

from src.config import PdfSource
from src.parser.ocr_chunker import chunk_from_extracted


def test_chunk_from_extracted_creates_text_and_table_chunks(tmp_path: Path) -> None:
    extracted_dir = tmp_path / "실무가이드"
    (extracted_dir / "text").mkdir(parents=True)
    (extracted_dir / "tables").mkdir()

    (extracted_dir / "text" / "p060_b00.txt").write_text("보험금 지급 기준", encoding="utf-8")
    (extracted_dir / "tables" / "p066_t00_text.txt").write_text(
        "수술종수 | 수술명 | 수술해설\n1종 | 반월판연골 봉합술 | 봉합하는 수술",
        encoding="utf-8",
    )
    (extracted_dir / "tables" / "p066_t00.json").write_text(
        json.dumps({"headers": ["수술종수", "수술명", "수술해설"], "rows": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (extracted_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_no": 60,
                        "engine": "ppstructure",
                        "blocks": [
                            {"type": "text", "file": "text/p060_b00.txt", "bbox": [0, 0, 10, 10], "confidence": 0.9}
                        ],
                    },
                    {
                        "page_no": 66,
                        "engine": "ppstructure",
                        "blocks": [
                            {
                                "type": "table",
                                "file": "tables/p066_t00_text.txt",
                                "bbox": [0, 0, 10, 10],
                                "confidence": 0.95,
                            }
                        ],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source = PdfSource(
        path=Path("Claim 실무종합가이드.pdf"),
        doc_type="ops_guide_scanned",
        doc_name="Claim 실무종합가이드",
        doc_short="실무가이드",
        requires_ocr=True,
    )

    chunks = chunk_from_extracted("실무가이드", extracted_dir, source, id_offset=7)

    assert [chunk.id for chunk in chunks] == ["실무가이드_ch_000007", "실무가이드_ch_000008"]
    assert chunks[0].metadata["content_type"] == "text"
    assert chunks[0].metadata["page_start"] == 61
    assert chunks[1].metadata["content_type"] == "table"
    assert chunks[1].metadata["source_method"] == "ocr_ppstructure"
    assert chunks[1].metadata["is_code_table"] is True
    assert "수술종수" in chunks[1].metadata["table_json"]
