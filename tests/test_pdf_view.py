from pathlib import Path

from src.ui import pdf_view


def test_render_pdf_page_png_returns_png_bytes(tmp_path: Path) -> None:
    import fitz

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "PDF preview test")
    doc.save(pdf_path)
    doc.close()

    png = pdf_view.render_pdf_page_png(str(pdf_path), 1)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_open_pdf_in_native_viewer_darwin(monkeypatch, tmp_path: Path) -> None:
    calls = []
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(pdf_view.sys, "platform", "darwin")
    monkeypatch.setattr(pdf_view.subprocess, "Popen", lambda args: calls.append(args))

    ok, msg = pdf_view.open_pdf_in_native_viewer(pdf_path)

    assert ok is True
    assert calls == [["open", str(pdf_path)]]
    assert "Preview" in msg


def test_open_pdf_in_native_viewer_handles_missing_file(tmp_path: Path) -> None:
    ok, msg = pdf_view.open_pdf_in_native_viewer(tmp_path / "missing.pdf")

    assert ok is False
    assert "파일을 찾을 수 없습니다" in msg
