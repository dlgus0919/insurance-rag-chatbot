import io
import zipfile

import requests

from scripts import bootstrap_assets


class DummyResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


def _zip_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zf:
        zf.writestr("data/index/chroma/marker.txt", "ok")
    return output.getvalue()


def test_bootstrap_assets_skips_without_url(monkeypatch) -> None:
    monkeypatch.delenv("INDEX_RELEASE_URL", raising=False)

    assert bootstrap_assets.main() == 0


def test_bootstrap_assets_skips_when_index_exists(tmp_path, monkeypatch) -> None:
    chroma_dir = tmp_path / "data" / "index" / "chroma"
    chroma_dir.mkdir(parents=True)
    (chroma_dir / "chroma.sqlite3").write_text("ok", encoding="utf-8")
    (tmp_path / "data" / "index" / ".assets_complete").write_text("complete", encoding="utf-8")
    monkeypatch.setenv("INDEX_RELEASE_URL", "https://example.com/assets.zip")
    monkeypatch.setattr(bootstrap_assets.config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(bootstrap_assets.config, "CHROMA_DIR", chroma_dir)

    assert bootstrap_assets.main() == 0


def test_bootstrap_assets_downloads_and_extracts_zip(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return DummyResponse(_zip_bytes())

    monkeypatch.setenv("INDEX_RELEASE_URL", "https://example.com/assets.zip")
    monkeypatch.setattr(bootstrap_assets.config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(bootstrap_assets.config, "CHROMA_DIR", tmp_path / "data" / "index" / "chroma")
    monkeypatch.setattr(requests, "get", fake_get)

    assert bootstrap_assets.main() == 0
    assert calls == [("https://example.com/assets.zip", 300)]
    assert (tmp_path / "data" / "index" / "chroma" / "marker.txt").read_text(encoding="utf-8") == "ok"
    assert (tmp_path / "data" / "index" / ".assets_complete").read_text(encoding="utf-8") == "complete\n"


def test_bootstrap_assets_replaces_partial_index_before_extract(tmp_path, monkeypatch) -> None:
    calls = []
    chroma_dir = tmp_path / "data" / "index" / "chroma"
    chroma_dir.mkdir(parents=True)
    (chroma_dir / "stale.txt").write_text("old", encoding="utf-8")

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return DummyResponse(_zip_bytes())

    monkeypatch.setenv("INDEX_RELEASE_URL", "https://example.com/assets.zip")
    monkeypatch.setattr(bootstrap_assets.config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(bootstrap_assets.config, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(requests, "get", fake_get)

    assert bootstrap_assets.main() == 0
    assert calls == [("https://example.com/assets.zip", 300)]
    assert not (chroma_dir / "stale.txt").exists()
    assert (chroma_dir / "marker.txt").read_text(encoding="utf-8") == "ok"
