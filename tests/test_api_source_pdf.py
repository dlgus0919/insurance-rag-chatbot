from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config
from src.api.deps import current_user
from src.api.main import create_app
from src.auth.users import User


def _user(role: str = "employee") -> User:
    return User(
        username=f"{role}01",
        password_hash="hash",
        role=role,
        display_name=role,
        created_at="2026-07-20T00:00:00+00:00",
        password_updated_at="2026-07-20T00:00:00+00:00",
    )


def _source(path: Path, *, doc_short: str) -> config.PdfSource:
    return config.PdfSource(
        path=path,
        doc_type="policy",
        doc_name=doc_short,
        doc_short=doc_short,
    )


def _client(monkeypatch: pytest.MonkeyPatch, sources: list[config.PdfSource], role: str | None = "employee") -> TestClient:
    monkeypatch.setattr(config, "PDF_SOURCES", sources)
    app = create_app()
    if role is not None:
        app.dependency_overrides[current_user] = lambda: _user(role)
    return TestClient(app)


def test_registered_pdf_is_served_inline_by_doc_short_or_basename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "등록 약관.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\\nregistered source")
    client = _client(monkeypatch, [_source(pdf_path, doc_short="약관")])

    normalized = client.get("/api/chat/sources/pdf", params={"doc_short": unicodedata.normalize("NFD", "약관")})
    basename = client.get("/api/chat/sources/pdf", params={"filename": pdf_path.name})

    for response in (normalized, basename):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")
        assert "inline" in response.headers["content-disposition"]
        assert response.content == pdf_path.read_bytes()


def test_source_pdf_requires_authenticated_chat_permission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "allowed.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\\nauthorized source")
    sources = [_source(pdf_path, doc_short="약관")]

    unauthenticated = _client(monkeypatch, sources, role=None)
    forbidden = _client(monkeypatch, sources, role="viewer")

    assert unauthenticated.get("/api/chat/sources/pdf", params={"doc_short": "약관"}).status_code == 401
    assert forbidden.get("/api/chat/sources/pdf", params={"doc_short": "약관"}).status_code == 403


def test_source_pdf_fails_closed_for_unknown_traversal_missing_and_non_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed_pdf = tmp_path / "allowed.pdf"
    allowed_pdf.write_bytes(b"%PDF-1.7\\nallowed source")
    text_path = tmp_path / "not-a-pdf.txt"
    text_path.write_text("not a PDF", encoding="utf-8")
    sources = [
        _source(allowed_pdf, doc_short="약관"),
        _source(tmp_path / "missing.pdf", doc_short="누락"),
        _source(text_path, doc_short="비PDF"),
    ]
    client = _client(monkeypatch, sources)

    for params in (
        {"doc_short": "미등록"},
        {"filename": "../allowed.pdf"},
        {"doc_short": "누락"},
        {"doc_short": "비PDF"},
        {},
    ):
        response = client.get("/api/chat/sources/pdf", params=params)
        assert response.status_code == 404
        assert b"%PDF" not in response.content
