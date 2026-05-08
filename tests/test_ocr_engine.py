from src.parser.ocr_engine import (
    LayoutBlock,
    _region_to_block,
    _table_html_to_json,
    _table_html_to_text,
    should_use_easyocr_fallback,
)


def test_table_html_to_text_and_json() -> None:
    html = """
    <table>
      <tr><td>수술종수</td><td>수술명</td><td>수술해설</td></tr>
      <tr><td>1종</td><td>반월판연골 봉합술</td><td>봉합하는 수술</td></tr>
    </table>
    """

    text = _table_html_to_text(html)
    data = _table_html_to_json(html)

    assert "수술종수 | 수술명 | 수술해설" in text
    assert data["headers"] == ["수술종수", "수술명", "수술해설"]
    assert data["rows"][0]["수술명"] == "반월판연골 봉합술"


def test_table_html_to_json_preserves_blank_duplicate_columns() -> None:
    html = "<table><tr><td>구분</td><td></td><td></td></tr><tr><td>A</td><td>B</td><td>C</td></tr></table>"

    data = _table_html_to_json(html)

    assert data["headers"] == ["구분", "col_2", "col_3"]
    assert data["rows"][0] == {"구분": "A", "col_2": "B", "col_3": "C"}


def test_region_to_block_parses_ppstructure_table() -> None:
    block = _region_to_block(
        {
            "type": "table",
            "bbox": [1, 2, 30, 40],
            "res": {"html": "<table><tr><td>A</td><td>B</td></tr></table>", "score": 0.91, "cell_bbox": [[1, 2, 3, 4]]},
        }
    )

    assert block.block_type == "table"
    assert block.bbox == [1, 2, 30, 40]
    assert block.text == "A | B"
    assert block.confidence == 0.91
    assert block.raw["cell_bbox"] == [[1, 2, 3, 4]]


def test_region_to_block_parses_text_result_list() -> None:
    block = _region_to_block(
        {
            "type": "text",
            "bbox": [0, 0, 100, 20],
            "res": [
                ([[0, 0], [10, 0], [10, 10], [0, 10]], ("보험금", 0.95)),
                ([[0, 10], [10, 10], [10, 20], [0, 20]], ("지급", 0.90)),
            ],
        }
    )

    assert block.block_type == "text"
    assert block.text == "보험금 지급"
    assert round(block.confidence, 2) == 0.93


def test_should_use_easyocr_fallback() -> None:
    assert should_use_easyocr_fallback([], threshold=0.5) is True
    assert should_use_easyocr_fallback([LayoutBlock("text", [0, 0, 1, 1], "x", confidence=0.2)], 0.5) is True
    assert should_use_easyocr_fallback([LayoutBlock("table", [0, 0, 1, 1], "x", confidence=0.9)], 0.5) is False
