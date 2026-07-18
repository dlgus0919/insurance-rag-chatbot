#!/usr/bin/env python3
"""Read-only integrity audit for an active ontology manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ontology.approval_integrity import BaseManifestLock, audit_active_manifest
from src.ontology.manifest_merge import validate_manifest_schema


EXIT_CODE_BY_STATE = {
    "valid": 0,
    "quarantined": 2,
    "legacy_unverifiable": 2,
    "stale": 3,
}


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("JSON object is required")
    return payload


def _audit_payload(audit: Any, *, exit_code: int) -> dict[str, Any]:
    issues = list(audit.report.issues)
    return {
        "state": audit.report.state,
        "exit_code": exit_code,
        "manifest_content_hash": audit.active_content_hash,
        "trusted_base_content_hash": audit.report.trusted_base_content_hash,
        "provenance_content_hash": audit.provenance_content_hash,
        "quarantined_concept_ids": list(audit.report.quarantined_concept_ids),
        "issue_counts": dict(sorted(Counter(issue.code for issue in issues).items())),
        "issues": [
            {
                "code": issue.code,
                "concept_id": issue.concept_id,
                "path": issue.path,
                "message": issue.message,
            }
            for issue in issues
        ],
        "approved_operation_count": len(audit.approved_operations),
        "concept_diff_count": len(audit.concept_diffs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ontology approval integrity without writing runtime data.")
    parser.add_argument("--base", required=True, help="Reviewed base manifest JSON path.")
    parser.add_argument("--base-lock", required=True, help="Reviewed base manifest lock JSON path.")
    parser.add_argument("--active", required=True, help="Active manifest JSON path.")
    parser.add_argument("--provenance", required=True, help="Active provenance JSON path.")
    parser.add_argument("--format", choices=["json"], default="json", help="Output format.")
    args = parser.parse_args()

    try:
        base = _load_json_object(Path(args.base))
        active = _load_json_object(Path(args.active))
        provenance = _load_json_object(Path(args.provenance))
        validate_manifest_schema(base)
        validate_manifest_schema(active)
        audit = audit_active_manifest(
            base,
            BaseManifestLock.load(args.base_lock),
            active,
            provenance,
        )
        exit_code = EXIT_CODE_BY_STATE[audit.report.state]
        print(json.dumps(_audit_payload(audit, exit_code=exit_code), ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code
    except (OSError, ValueError, json.JSONDecodeError):
        print(
            json.dumps(
                {
                    "state": "invalid_input",
                    "exit_code": 4,
                    "error": "input validation failed",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
