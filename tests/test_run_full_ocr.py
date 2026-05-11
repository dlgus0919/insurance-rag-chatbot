from __future__ import annotations

import json
from pathlib import Path

from src.parser.ocr_engine import LayoutBlock

from scripts.run_full_ocr import (
    CLOVA_NATIVE_ENGINE,
    TRUE_HYBRID_ENGINE,
    _engine_from_native_flag,
    _is_page_done,
    _process_page,
    _save_blocks,
    _update_manifest,
    build_arg_parser,
    parse_pages,
)


def test_parse_pages_supports_ranges_and_validates_total() -> None:
    assert parse_pages("60-62,64", total_pages=100) == [60, 61, 62, 64]
    assert parse_pages(None, total_pages=3) == [0, 1, 2]


def test_engine_from_native_flag_selects_workflow() -> None:
    assert _engine_from_native_flag(True) == CLOVA_NATIVE_ENGINE
    assert _engine_from_native_flag(False) == TRUE_HYBRID_ENGINE


def test_is_page_done_requires_matching_engine() -> None:
    manifest = {
        "pages": [
            {"page_no": 64, "engine": "clova_native"},
            {"page_no": 65, "engine": "true_hybrid"},
        ]
    }
    assert _is_page_done(manifest, 64, "clova_native") is True
    assert _is_page_done(manifest, 65, "true_hybrid") is True
    assert _is_page_done(manifest, 65, "clova_native") is False
    assert _is_page_done(manifest, 66, "clova_native") is False


def test_save_blocks_writes_text_blocks(tmp_path: Path) -> None:
    blocks = [
        LayoutBlock("text", [1, 2, 3, 4], "본문 텍스트", confidence=0.91),
        LayoutBlock("figure", [0, 0, 10, 10], "", confidence=1.0),
    ]

    entries = _save_blocks(blocks, tmp_path, 64)

    assert entries == [
        {
            "type": "text",
            "file": "text/p064_b00.txt",
            "bbox": [1, 2, 3, 4],
            "confidence": 0.91,
            "chars": 6,
            "source_method": "ocr_ppstructure",
        }
    ]
    assert (tmp_path / "text" / "p064_b00.txt").read_text(encoding="utf-8") == "본문 텍스트"


def test_save_blocks_writes_table_text_and_json(tmp_path: Path) -> None:
    table_json = {"headers": ["수술명", "1-3종"], "rows": [{"수술명": "봉합술", "1-3종": "1"}]}
    blocks = [
        LayoutBlock(
            "table",
            [10, 20, 30, 40],
            "ignored",
            table_json=table_json,
            confidence=None,
            raw={"vision_cleaned": True, "numeric_refined": True},
        )
    ]

    entries = _save_blocks(blocks, tmp_path, 68)

    assert entries[0]["type"] == "table"
    assert entries[0]["file"] == "tables/p068_t00.txt"
    assert entries[0]["vision_cleaned"] is True
    assert entries[0]["numeric_refined"] is True
    assert (tmp_path / "tables" / "p068_t00.txt").read_text(encoding="utf-8") == "수술명 | 1-3종\n봉합술 | 1"
    saved_json = json.loads((tmp_path / "tables" / "p068_t00.json").read_text(encoding="utf-8"))
    assert saved_json == table_json


def test_update_manifest_replaces_page_and_sorts(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "doc_short": "실무가이드",
        "total_pages": 330,
        "pages": [
            {"page_no": 65, "engine": "ppstructure", "blocks": []},
            {"page_no": 64, "engine": "ppstructure", "blocks": []},
        ],
    }

    _update_manifest(
        manifest_path,
        manifest,
        64,
        65,
        [{"type": "text", "file": "text/p064_b00.txt", "bbox": [0, 0, 1, 1], "confidence": 1.0, "chars": 4}],
    )

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [page["page_no"] for page in updated["pages"]] == [64, 65]
    assert updated["pages"][0]["engine"] == "clova_native"
    assert updated["pages"][0]["page_label"] == 65


def test_update_manifest_can_record_true_hybrid_engine(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest = {"doc_short": "실무가이드", "total_pages": 330, "pages": []}

    _update_manifest(
        manifest_path,
        manifest,
        64,
        65,
        [],
        engine="true_hybrid",
    )

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated["pages"][0]["engine"] == "true_hybrid"


def test_process_page_clova_native_skips_ppstructure(monkeypatch, tmp_path: Path) -> None:
    image = object()
    calls = {"ppstructure": 0, "layout_regions": "not-called"}

    monkeypatch.setattr("scripts.run_full_ocr.extract_page_image", lambda _pdf, _page: image)

    def fake_run_ppstructure(_image):
        calls["ppstructure"] += 1
        return []

    def fake_clova_ocr_page(_image, *, page_name, layout_regions, timeout_sec):
        calls["layout_regions"] = layout_regions
        return [LayoutBlock("text", [0, 0, 10, 10], "CLOVA 본문", source_method="ocr_clova")]

    monkeypatch.setattr("scripts.run_full_ocr.run_ppstructure", fake_run_ppstructure)
    monkeypatch.setattr("scripts.run_full_ocr.clova_ocr_page", fake_clova_ocr_page)

    entries, vision_available = _process_page(
        tmp_path / "dummy.pdf",
        64,
        tmp_path / "out",
        timeout_sec=90,
        clova_native=True,
    )

    assert calls["ppstructure"] == 0
    assert calls["layout_regions"] is None
    assert vision_available is True
    assert entries[0]["source_method"] == "ocr_clova"


def test_arg_parser_defaults_to_clova_native_and_keeps_true_hybrid_flag() -> None:
    parser = build_arg_parser()

    default_args = parser.parse_args(["--doc", "all"])
    true_hybrid_args = parser.parse_args(["--doc", "all", "--true-hybrid"])

    assert default_args.clova_native is True
    assert true_hybrid_args.clova_native is False
