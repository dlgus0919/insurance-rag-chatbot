from pathlib import Path

from PIL import Image

from src.parser.pdf_extractor import extract_page_image, get_page_count


def test_extract_page_image_uses_embedded_image(tmp_path: Path) -> None:
    import fitz

    image_path = tmp_path / "page.jpg"
    Image.new("L", (120, 80), color=220).save(image_path, "JPEG")

    pdf_path = tmp_path / "scan.pdf"
    doc = fitz.open()
    page = doc.new_page(width=120, height=80)
    page.insert_image(page.rect, filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    image = extract_page_image(pdf_path, 0)

    assert get_page_count(pdf_path) == 1
    assert image.size == (120, 80)
    assert image.mode in {"L", "RGB"}
