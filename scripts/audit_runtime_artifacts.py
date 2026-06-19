from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactClassification:
    path: str
    size_bytes: int
    category: str
    reason: str


def classify_artifact(path: str, size_bytes: int) -> ArtifactClassification:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name

    if normalized.startswith(".git/objects/pack/"):
        return ArtifactClassification(path, size_bytes, "separate_project", "git_history_pack")
    if name.startswith("._"):
        return ArtifactClassification(path, size_bytes, "cleanup_candidate", "macos_appledouble")
    if "/__pycache__/" in normalized or normalized.endswith(".pyc"):
        return ArtifactClassification(path, size_bytes, "cleanup_candidate", "python_cache")
    if normalized.startswith("data/index/") or normalized.endswith(".db") or normalized.endswith(".sqlite"):
        return ArtifactClassification(path, size_bytes, "preserve", "operational_index_or_database")
    if normalized.startswith("data/ontology/"):
        return ArtifactClassification(path, size_bytes, "preserve", "ontology_manifest_or_review_log")
    if normalized.startswith("data/hospital_receipts/") and "/runs/" in normalized:
        return ArtifactClassification(path, size_bytes, "review", "runtime_experiment_output")
    if normalized.startswith("reports/") or normalized.startswith("docs/"):
        return ArtifactClassification(path, size_bytes, "review", "project_report_or_document")
    return ArtifactClassification(path, size_bytes, "review", "unclassified_project_artifact")


def iter_artifacts(root: Path) -> list[ArtifactClassification]:
    results: list[ArtifactClassification] = []
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            results.append(classify_artifact(relative, path.stat().st_size))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only runtime artifact inventory")
    parser.add_argument("--root", default=".", help="Project root to inspect")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-file artifacts from the JSON payload",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    results = iter_artifacts(root)
    payload = {
        "root": str(root),
        "summary": {
            category: sum(item.size_bytes for item in results if item.category == category)
            for category in sorted({item.category for item in results})
        },
    }
    if not args.summary_only:
        payload["artifacts"] = [asdict(item) for item in results]

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
