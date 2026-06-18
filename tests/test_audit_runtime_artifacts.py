from __future__ import annotations

from scripts.audit_runtime_artifacts import classify_artifact


def test_operational_index_is_preserved():
    result = classify_artifact("data/index/v2_only/chroma.sqlite3", 10_000)

    assert result.category == "preserve"
    assert result.reason == "operational_index_or_database"


def test_hospital_receipt_runtime_output_is_review_candidate():
    result = classify_artifact("data/hospital_receipts/manual_20260609/runs/opencv_paddle/run_summary.json", 10_000)

    assert result.category == "review"
    assert result.reason == "runtime_experiment_output"


def test_mac_appledouble_file_is_cleanup_candidate():
    result = classify_artifact("data/index/._chunks.jsonl", 4096)

    assert result.category == "cleanup_candidate"
    assert result.reason == "macos_appledouble"


def test_git_pack_requires_separate_project():
    result = classify_artifact(".git/objects/pack/pack-abc.pack", 27 * 1024 * 1024 * 1024)

    assert result.category == "separate_project"
    assert result.reason == "git_history_pack"
