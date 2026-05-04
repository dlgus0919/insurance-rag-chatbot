from src.parser.chunker import Chunk
from src.ui.streamlit_app import _format_timing, _source_title


def test_source_title_includes_pdf_filename_hierarchy_and_page() -> None:
    chunk = Chunk(
        id="ch_000001",
        text="본문",
        metadata={
            "doc_short": "심평원",
            "pdf_filename": "BZ202603053039374.pdf",
            "volume": "제1편",
            "part": "제1부",
            "chapter": "제1장",
            "section": "제1절",
            "page_start": 3,
            "page_end": 4,
        },
    )

    title = _source_title(chunk)

    assert "[심평원] | BZ202603053039374.pdf | p.3~4" in title
    assert "제1편 > 제1부 > 제1장 > 제1절" in title


def test_source_title_uses_config_filename_fallback() -> None:
    chunk = Chunk(
        id="심평원_ch_000001",
        text="본문",
        metadata={"doc_short": "심평원", "page_start": 101, "page_end": 101},
    )

    title = _source_title(chunk)

    assert "[심평원] | BZ202603053039374.pdf | p.101" in title


def test_format_timing() -> None:
    timing = {"retrieve_ms": 12.3, "llm_ms": 456.7, "total_ms": 1234.5}

    assert _format_timing(timing) == "검색 12ms · 생성 457ms · 합계 1.2초"
