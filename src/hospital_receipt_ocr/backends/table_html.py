"""Shared helpers for converting OCR table HTML into runtime OCR tables."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from ..models import OcrCell, OcrTable


class _TableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._cell_colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._cell_colspan = _parse_colspan(attrs)

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            text = " ".join("".join(self._current_cell).split())
            self._current_row.append(text)
            for _ in range(max(self._cell_colspan - 1, 0)):
                self._current_row.append("")
            self._current_cell = None
            self._cell_colspan = 1
        elif tag == "tr" and self._current_row is not None:
            if any(cell.strip() for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def html_table_to_ocr_table(
    *,
    page_id: str,
    table_id: str,
    bbox: list[int],
    html: str,
    source_method: str,
    raw: dict[str, Any] | None = None,
) -> OcrTable | None:
    """Convert simple table HTML into an ``OcrTable``.

    PP-Structure and similar table recognizers often return structural HTML
    without reliable per-cell coordinates. We keep the source bbox and assign
    deterministic synthetic cell boxes so downstream normalization can work
    while still preserving raw backend output for review.
    """

    rows = parse_table_html(html)
    if not rows:
        return None

    cols = max(len(row) for row in rows)
    if cols <= 0:
        return None

    x1, y1, x2, y2 = _normalize_bbox(bbox)
    width = max(x2 - x1, cols)
    height = max(y2 - y1, len(rows))
    cells: list[OcrCell] = []
    for row_index, row in enumerate(rows):
        for col_index in range(cols):
            text = row[col_index] if col_index < len(row) else ""
            cell_bbox = [
                int(round(x1 + width * col_index / cols)),
                int(round(y1 + height * row_index / len(rows))),
                int(round(x1 + width * (col_index + 1) / cols)),
                int(round(y1 + height * (row_index + 1) / len(rows))),
            ]
            cell_id = f"{page_id}_r{row_index:03d}_c{col_index:03d}"
            cells.append(
                OcrCell(
                    cell_id=cell_id,
                    page_id=page_id,
                    row=row_index,
                    col=col_index,
                    bbox=cell_bbox,
                    text=text,
                    source_method=source_method,
                    raw=raw or {},
                )
            )

    return OcrTable(table_id=table_id, page_id=page_id, bbox=[x1, y1, x2, y2], rows=len(rows), cols=cols, cells=cells)


def parse_table_html(html: str) -> list[list[str]]:
    parser = _TableHtmlParser()
    parser.feed(html or "")
    parser.close()
    return parser.rows


def _parse_colspan(attrs: list[tuple[str, str | None]]) -> int:
    for key, value in attrs:
        if key.lower() == "colspan" and value:
            try:
                return max(int(value), 1)
            except ValueError:
                return 1
    return 1


def _normalize_bbox(bbox: list[int]) -> list[int]:
    if len(bbox) >= 4:
        x1, y1, x2, y2 = [int(value) for value in bbox[:4]]
        if x2 > x1 and y2 > y1:
            return [x1, y1, x2, y2]
    return [0, 0, 1, 1]
