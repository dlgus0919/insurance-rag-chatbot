#!/usr/bin/env python3
"""Run the hospital receipt OCR process."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hospital_receipt_ocr.runner import run_hospital_receipt_ocr


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run hospital receipt OCR.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-file", type=Path)
    source.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--strategy", choices=["opencv_paddle", "ppstructure", "surya", "tatr_ocr"], default="opencv_paddle")
    parser.add_argument(
        "--doc-type-mode",
        choices=["auto", "detail_statement", "medical_detail_statement", "receipt", "medical_bill_receipt", "diagnosis", "diagnosis_certificate", "surgery_certificate", "unknown"],
        default="auto",
    )
    parser.add_argument("--redact-sensitive", action="store_true", default=False)
    parser.add_argument("--no-llm", action="store_true", default=False)
    parser.add_argument("--export-claim-items", action="store_true", default=False)
    parser.add_argument("--fail-on-unverified", action="store_true", default=False)
    parser.add_argument(
        "--allow-experimental-surya-inference",
        action="store_true",
        default=False,
        help="Allow the experimental Surya backend to run local inference. Default is degraded/no-inference.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = run_hospital_receipt_ocr(
        input_file=args.input_file,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        strategy=args.strategy,
        doc_type_mode=args.doc_type_mode,
        redact_sensitive=args.redact_sensitive,
        no_llm=args.no_llm,
        export_claim_items=args.export_claim_items,
        fail_on_unverified=args.fail_on_unverified,
        allow_experimental_surya_inference=args.allow_experimental_surya_inference,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
