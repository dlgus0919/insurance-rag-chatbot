import json
from pathlib import Path

from scripts import build_v1_v2_pair_mapping as mapping


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_emit_low_confidence_report(tmp_path: Path) -> None:
    doc = "상담사례집"
    mapping_dir = tmp_path / "mapping"
    low_conf_dir = tmp_path / "reports"

    mapping_rows = [
        {
            "canonical_chunk_id": "v2_1",
            "v1_chunk_id": "v1_1",
            "doc_short": doc,
            "page_start": 10,
            "content_type": "text",
            "match_type": "exact_order",
            "score": 0.97,
            "confidence": "high",
            "use_v1": True,
        },
        {
            "canonical_chunk_id": "v2_2",
            "v1_chunk_id": None,
            "doc_short": doc,
            "page_start": 11,
            "content_type": "text",
            "match_type": "fuzzy",
            "score": 0.80,
            "confidence": "low",
            "use_v1": False,
        },
    ]
    _write_jsonl(mapping_dir / f"v1_v2_pairs_{doc}.jsonl", mapping_rows)

    v1_lookup = {"v1_1": {"id": "v1_1", "text": "원본 텍스트"}}
    v2_lookup = {
        "v2_1": {"id": "v2_1", "text": "보정본 텍스트 1"},
        "v2_2": {"id": "v2_2", "text": "보정본 텍스트 2"},
    }

    mapping._emit_low_confidence_report(
        docs=[doc],
        out_dir=low_conf_dir,
        mapping_dir=mapping_dir,
        v1_lookup=v1_lookup,
        v2_lookup=v2_lookup,
    )

    report_path = low_conf_dir / f"low_confidence_{doc}.jsonl"
    assert report_path.exists()
    lines = [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["canonical_chunk_id"] == "v2_2"
    assert lines[0]["v1_chunk_id"] is None
    assert lines[0]["use_v1"] is False
    assert lines[0]["v2_text_preview"] == "보정본 텍스트 2"

    summary = json.loads((low_conf_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary[0]["doc_short"] == doc
    assert summary[0]["total_pairs"] == 2
    assert summary[0]["low_confidence_pairs"] == 1
