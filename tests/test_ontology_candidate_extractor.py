from __future__ import annotations

import json
from pathlib import Path

from src.ontology.candidate_extractor import (
    extract_reinforcement_candidates,
    load_manifest_concepts,
    load_processed_chunks,
)


def write_manifest(path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "version": "test",
        "concepts": [
            {
                "concept_id": "cond.traffic_injury",
                "canonical_name": "교통사고 상해",
                "node_type": "ClaimCondition",
                "aliases": ["교통사고"],
                "planner": {"conditions": ["교통사고 상해"]},
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_chunks(path: Path) -> None:
    row = {
        "id": "chunk-1",
        "text": "교통사고 상해는 교통상해(교통 사고) 표현과 함께 보장 검토에서 확인한다.",
        "metadata": {
            "doc_short": "약관",
            "doc_name": "테스트 약관",
            "page_start": 12,
            "confidence": 0.9,
        },
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def test_extract_reinforcement_candidates_from_processed_chunks(tmp_path: Path) -> None:
    manifest = tmp_path / "concepts.json"
    chunks = tmp_path / "chunks.jsonl"
    write_manifest(manifest)
    write_chunks(chunks)

    concepts = load_manifest_concepts(manifest)
    source_chunks = load_processed_chunks([chunks])
    result = extract_reinforcement_candidates(concepts=concepts, chunks=source_chunks, candidate_limit=5)

    assert result.source_count == 1
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.concept_id == "cond.traffic_injury"
    assert candidate.properties["candidate_type"] == "alias_or_expansion"
    assert candidate.properties["target_concept_id"] == "cond.traffic_injury"
    assert "display" in candidate.properties
    assert candidate.properties["codex_dev_review"]["decision"] == "approve"
    assert candidate.properties["codex_dev_review"]["policy_id"] == "ontology-review-default"
    assert candidate.properties["extraction"]["policy_id"] == "candidate-extraction-default"
    assert candidate.properties["extraction"]["policy_version"] == "2026-06-10"
    assert candidate.risk_flags == ["dev_auto_approval"]
    assert any("교통 사고" in item or "교통상해" in item for item in candidate.candidate_aliases)
