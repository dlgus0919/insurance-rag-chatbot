from scripts.ingest import select_sources


def test_select_sources_cloud_only_excludes_unsafe_sources() -> None:
    sources = select_sources(cloud_only=True)

    assert sources
    assert all(source.cloud_safe for source in sources)
    assert "가이드북" not in {source.doc_short for source in sources}


def test_select_sources_default_keeps_all_sources() -> None:
    sources = select_sources(cloud_only=False)

    assert "심평원" in {source.doc_short for source in sources}
    assert "약관" in {source.doc_short for source in sources}
    assert "가이드북" in {source.doc_short for source in sources}
