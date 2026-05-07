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
    assert "실무가이드" not in {source.doc_short for source in sources}
    assert "상담사례집" not in {source.doc_short for source in sources}


def test_select_sources_excludes_requires_ocr_by_default() -> None:
    sources = select_sources(skip_ocr=True)

    assert all(not source.requires_ocr for source in sources)


def test_select_sources_includes_ocr_when_skip_ocr_false() -> None:
    all_sources = select_sources(skip_ocr=False)
    default_sources = select_sources(skip_ocr=True)

    assert len(all_sources) >= len(default_sources)
    assert "실무가이드" in {source.doc_short for source in all_sources}
    assert "상담사례집" in {source.doc_short for source in all_sources}
