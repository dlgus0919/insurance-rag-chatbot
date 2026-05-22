from __future__ import annotations

import json
from pathlib import Path

from scripts.run_clova_local import _block_quality, _header_score, _update_summary, parse_pages


def test_block_quality_empty_text() -> None:
    quality = _block_quality({"text": ""})
    assert quality == {"chars": 0, "korean_ratio": 0.0, "noise_ratio": 0.0, "grade": "FAIL"}


def test_block_quality_korean_pass() -> None:
    quality = _block_quality({"text": "수술종수 수술명 수술해설"})
    assert quality["chars"] > 0
    assert quality["korean_ratio"] > 0.5
    assert quality["grade"] == "PASS"


def test_header_score_keyword_matching() -> None:
    table_json = {"headers": ["수술종수", "수술명", "기타"], "rows": []}
    score = _header_score(table_json)
    assert score == round(2 / 3, 3)


def test_parse_pages_range_and_list() -> None:
    assert parse_pages("60-62") == [60, 61, 62]
    assert parse_pages("66") == [66]
    assert parse_pages("60,62,66") == [60, 62, 66]


def test_update_summary_replaces_clova_section(tmp_path: Path) -> None:
    doc_short = "실무가이드"
    doc_dir = tmp_path / doc_short
    doc_dir.mkdir(parents=True)
    summary_path = doc_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_at": "2026-05-08T00:00:00",
                "doc_short": doc_short,
                "pages": [60, 61],
                "engines": {
                    "hybrid": {"status": "SUCCESS"},
                    "clova": {"status": "SKIPPED", "skipped_pages": [60, 61]},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    clova_results = [
        {
            "page_no": 60,
            "elapsed_sec": 7.2,
            "status": "SUCCESS",
            "blocks": [
                {"block_type": "text", "quality": {"korean_ratio": 0.8, "noise_ratio": 0.01, "grade": "PASS"}},
                {
                    "block_type": "table",
                    "table_json": {"headers": ["수술종수", "수술명"], "rows": []},
                    "quality": {"korean_ratio": 0.7, "noise_ratio": 0.02, "grade": "PASS"},
                },
            ],
            "metrics": {"header_score_avg": 0.5},
        },
        {
            "page_no": 61,
            "elapsed_sec": 60.0,
            "status": "SKIPPED",
            "blocks": [],
            "metrics": {"header_score_avg": 0.0},
        },
    ]

    _update_summary(tmp_path, doc_short, clova_results)

    updated = json.loads(summary_path.read_text(encoding="utf-8"))
    clova = updated["engines"]["clova"]
    assert clova["status"] == "PARTIAL"
    assert clova["skipped_pages"] == [61]
    assert clova["table_blocks"] == 1
    assert clova["grade"]["PASS"] == 2
    assert "clova_rerun_at" in updated
