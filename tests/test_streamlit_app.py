from src.parser.chunker import Chunk
from src.ui.streamlit_app import _source_title


def test_source_title_includes_hierarchy_and_page() -> None:
    chunk = Chunk(
        id="ch_000001",
        text="본문",
        metadata={
            "volume": "제1편",
            "part": "제1부",
            "chapter": "제1장",
            "section": "제1절",
            "page_start": 3,
            "page_end": 4,
        },
    )

    title = _source_title(chunk)

    assert "ch_000001" in title
    assert "제1편 / 제1부 / 제1장 / 제1절" in title
    assert "p.3-4" in title
