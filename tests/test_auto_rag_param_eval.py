from scripts import eval_auto_rag_params as auto_eval


def test_auto_rag_eval_defaults_to_corrected_ocr_index_mode() -> None:
    args = auto_eval.parse_args(["--models", "sglang:gpt-oss-20b"])

    assert args.index_mode == "v2_only"


def test_auto_rag_eval_all_stage_expands_to_baseline_rule_threshold_and_grid() -> None:
    args = auto_eval.parse_args([
        "--models",
        "sglang:gpt-oss-20b",
        "--stage",
        "all",
        "--temperature-grid",
        "0,0.2",
    ])

    runs = auto_eval._make_runs(args)

    assert [run.strategy for run in runs] == [
        "baseline_fixed",
        "rule_auto",
        "threshold_auto",
        "temperature_grid_0",
        "temperature_grid_0.2",
    ]


def test_auto_rag_eval_quality_penalizes_overly_casual_tone() -> None:
    quality = auto_eval._quality_metrics("안녕하세요. 저는 AI입니다.", "coverage_judgment")

    assert quality["tone_ok"] is False
    assert quality["score"] < 1.0
