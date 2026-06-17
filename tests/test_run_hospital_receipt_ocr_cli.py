from __future__ import annotations

import pytest

from scripts.run_hospital_receipt_ocr import build_parser
from src.hospital_receipt_ocr.preprocess import collect_input_files


def test_cli_help_parser_accepts_required_options() -> None:
    parser = build_parser()
    args = parser.parse_args(["--input-dir", "input", "--output-dir", "out", "--strategy", "opencv_paddle", "--no-llm"])

    assert args.input_dir.name == "input"
    assert args.output_dir.name == "out"
    assert args.strategy == "opencv_paddle"
    assert args.no_llm is True


def test_cli_accepts_bc_strategies_without_llm() -> None:
    parser = build_parser()

    pp_args = parser.parse_args(["--input-dir", "input", "--output-dir", "out", "--strategy", "ppstructure", "--no-llm"])
    surya_args = parser.parse_args(
        [
            "--input-dir",
            "input",
            "--output-dir",
            "out",
            "--strategy",
            "surya",
            "--no-llm",
            "--allow-experimental-surya-inference",
        ]
    )

    assert pp_args.strategy == "ppstructure"
    assert surya_args.strategy == "surya"
    assert surya_args.allow_experimental_surya_inference is True


def test_cli_accepts_tatr_strategy_without_llm() -> None:
    parser = build_parser()
    args = parser.parse_args(["--input-dir", "input", "--output-dir", "out", "--strategy", "tatr_ocr", "--no-llm"])

    assert args.strategy == "tatr_ocr"


def test_collect_input_files_rejects_missing_dir(tmp_path) -> None:
    with pytest.raises(ValueError, match="입력 폴더"):
        collect_input_files(input_dir=tmp_path / "missing")
