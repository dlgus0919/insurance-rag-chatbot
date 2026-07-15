#!/usr/bin/env python3
"""Render the practitioner troubleshooting manual as a Korean PDF."""

from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md"
DEFAULT_OUTPUT = ROOT / "output/pdf/practitioner_operations_troubleshooting_manual.pdf"
FONT_CANDIDATES = (
    ROOT / "assets/fonts/NotoSansKR-Regular.ttf",
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
)
KOREAN_CID_FONT = "HYSMyeongJo-Medium"


def resolve_korean_font(font_path: str | Path | None = None) -> Path:
    """Return an installed Korean-capable font without embedding a machine path in output."""
    candidates: Iterable[Path] = (Path(font_path),) if font_path else FONT_CANDIDATES
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Korean PDF font was not found")


def _register_font(font_path: Path) -> str:
    if font_path.suffix.lower() == ".ttc":
        if KOREAN_CID_FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_CID_FONT))
        return KOREAN_CID_FONT

    font_name = "PractitionerKorean"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    return font_name


def _styles(font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ManualTitle",
            parent=base["Title"],
            fontName=font_name,
            fontSize=18,
            leading=25,
            textColor=colors.HexColor("#172554"),
            spaceAfter=10 * mm,
        ),
        "h2": ParagraphStyle(
            "ManualHeading2",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=13,
            leading=19,
            textColor=colors.HexColor("#1E3A8A"),
            spaceBefore=7 * mm,
            spaceAfter=3 * mm,
        ),
        "h3": ParagraphStyle(
            "ManualHeading3",
            parent=base["Heading3"],
            fontName=font_name,
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#0F172A"),
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "ManualBody",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=8.8,
            leading=14,
            spaceAfter=2.2 * mm,
        ),
        "table": ParagraphStyle(
            "ManualTable",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=7.4,
            leading=10.2,
        ),
        "footer": ParagraphStyle(
            "ManualFooter",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=7.2,
            leading=9,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#475569"),
        ),
    }


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    escaped = html.escape(text.strip()).replace("`", "")
    return Paragraph(escaped, style)


def _table(lines: list[str], style: ParagraphStyle) -> Table:
    rows: list[list[Paragraph]] = []
    for line in lines:
        stripped = line.strip()
        content = stripped.strip("|")
        if content and set(content) <= {"-", ":", "|", " "}:
            continue
        cells = [cell.strip() for cell in content.split("|")]
        rows.append([_paragraph(cell, style) for cell in cells])

    columns = max(len(row) for row in rows)
    for row in rows:
        row.extend([_paragraph("", style)] * (columns - len(row)))

    available_width = A4[0] - 38 * mm - 28 * mm
    if columns == 2:
        col_widths = [42 * mm, available_width - 42 * mm]
    elif columns == 5:
        col_widths = [24 * mm, 48 * mm, 24 * mm, 34 * mm, available_width - 130 * mm]
    else:
        col_widths = [available_width / columns] * columns

    table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _markdown_story(source: Path, styles: dict[str, ParagraphStyle]) -> list[object]:
    story: list[object] = []
    paragraph_lines: list[str] = []
    table_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines)
            story.append(_paragraph(text, styles["body"]))
            paragraph_lines.clear()

    def flush_table() -> None:
        if table_lines:
            story.append(_table(table_lines, styles["table"]))
            story.append(Spacer(1, 2.5 * mm))
            table_lines.clear()

    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("|"):
            flush_paragraph()
            table_lines.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_paragraph()
            continue
        if line.startswith("# "):
            flush_paragraph()
            story.append(_paragraph(line[2:], styles["title"]))
        elif line.startswith("## "):
            flush_paragraph()
            story.append(_paragraph(line[3:], styles["h2"]))
        elif line.startswith("### "):
            flush_paragraph()
            story.append(_paragraph(line[4:], styles["h3"]))
        elif line.startswith("- "):
            flush_paragraph()
            story.append(_paragraph(f"- {line[2:]}", styles["body"]))
        elif len(line) >= 3 and line[0].isdigit() and line[1:3] == ". ":
            flush_paragraph()
            story.append(_paragraph(line, styles["body"]))
        else:
            paragraph_lines.append(line)

    flush_table()
    flush_paragraph()
    return story


def _draw_footer(canvas, doc) -> None:  # type: ignore[no-untyped-def]
    canvas.saveState()
    canvas.setFont(getattr(doc, "manual_font_name", "PractitionerKorean"), 7.2)
    canvas.setFillColor(colors.HexColor("#475569"))
    canvas.drawCentredString(A4[0] / 2, 14 * mm, f"실무자 전체 운영 오류 대응 매뉴얼 · 페이지 {doc.page}")
    canvas.restoreState()


def build_pdf(source: str | Path, output: str | Path, font_path: str | Path | None = None) -> None:
    """Build the canonical manual into a paginated PDF."""
    source_path = Path(source)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_name = _register_font(resolve_korean_font(font_path))
    styles = _styles(font_name)
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=38 * mm,
        rightMargin=28 * mm,
        topMargin=24 * mm,
        bottomMargin=24 * mm,
        title="실무자 전체 운영 오류 대응 매뉴얼",
        author="Insurance RAG Chatbot",
    )
    document.manual_font_name = font_name
    document.build(_markdown_story(source_path, styles), onFirstPage=_draw_footer, onLaterPages=_draw_footer)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the practitioner troubleshooting manual PDF.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    build_pdf(args.source, args.output, args.font)
    print("PDF generated: practitioner_operations_troubleshooting_manual.pdf")


if __name__ == "__main__":
    main()
