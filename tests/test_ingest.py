from pathlib import Path

import scripts.ingest as ingest
from scripts.ingest import select_sources
from src.config import PdfSource
from src.parser.chunker import Chunk, load_chunks


def test_select_sources_cloud_only_excludes_unsafe_sources() -> None:
    sources = select_sources(cloud_only=True)

    assert sources
    assert all(source.cloud_safe for source in sources)
    assert "가이드북" not in {source.doc_short for source in sources}


def test_select_sources_default_keeps_all_sources() -> None:
    sources = select_sources(cloud_only=False)

    assert "심평원" in {source.doc_short for source in sources}
    assert "약관" in {source.doc_short for source in sources}
    assert "가이드북" in {source.doc_short for source in sources}
    assert "실무가이드" not in {source.doc_short for source in sources}
    assert "상담사례집" not in {source.doc_short for source in sources}


def test_select_sources_excludes_requires_ocr_by_default() -> None:
    sources = select_sources(skip_ocr=True)

    assert all(not source.requires_ocr for source in sources)


def test_select_sources_includes_ocr_when_skip_ocr_false() -> None:
    all_sources = select_sources(skip_ocr=False)
    default_sources = select_sources(skip_ocr=True)

    assert len(all_sources) >= len(default_sources)
    assert "실무가이드" in {source.doc_short for source in all_sources}
    assert "상담사례집" in {source.doc_short for source in all_sources}


def test_build_chunks_uses_extracted_ocr_manifest(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    extracted_dir = tmp_path / "extracted" / "스캔"
    extracted_dir.mkdir(parents=True)
    (extracted_dir / "manifest.json").write_text('{"pages": []}', encoding="utf-8")
    chunks_path = tmp_path / "chunks.jsonl"

    source = PdfSource(
        path=pdf_path,
        doc_type="ops_guide_scanned",
        doc_name="스캔",
        doc_short="스캔",
        requires_ocr=True,
    )

    def fake_chunk_from_extracted(doc_short, actual_extracted_dir, doc_source, id_offset=0):
        assert doc_short == "스캔"
        assert actual_extracted_dir == extracted_dir
        assert doc_source == source
        assert id_offset == 0
        return [
            Chunk(
                id="스캔_ch_000000",
                text="OCR 텍스트",
                metadata={"char_count": 6, "codes": [], "doc_short": "스캔", "content_type": "text"},
            )
        ]

    monkeypatch.setattr(ingest, "EXTRACTED_BASE", tmp_path / "extracted")
    monkeypatch.setattr(ingest, "chunk_from_extracted", fake_chunk_from_extracted)
    monkeypatch.setattr(ingest.config, "CHUNKS_PATH", chunks_path)

    ingest.build_chunks([source])

    loaded = load_chunks(chunks_path)
    assert loaded[0].id == "스캔_ch_000000"
