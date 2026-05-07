from scripts.check_raw_assets import is_blocked_path


def test_raw_asset_guard_blocks_raw_documents_and_sensitive_outputs() -> None:
    assert is_blocked_path("약관.pdf")
    assert is_blocked_path("data/raw/source.xlsx")
    assert is_blocked_path("data/extracted/doc/page.json")
    assert is_blocked_path("backup/alpha/source.pdf")
    assert is_blocked_path("assets.zip")


def test_raw_asset_guard_allows_gitkeep_placeholders() -> None:
    assert not is_blocked_path("data/extracted/.gitkeep")
    assert not is_blocked_path("data/index/graph/.gitkeep")
