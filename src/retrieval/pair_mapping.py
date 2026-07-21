"""v2 canonical -> v1 pair 매핑 로더."""

from __future__ import annotations

import json
from pathlib import Path

from src import config


class PairMappingStore:
    """문서별 v1-v2 매핑 JSONL을 로드해 조회한다."""

    def __init__(self, mapping_dir: Path | None = None):
        self.mapping_dir = mapping_dir or (config.ROOT_DIR / "data" / "mapping")
        self._pairs: dict[str, dict] = {}

    def load_doc(self, doc_short: str) -> int:
        """문서별 매핑 파일을 로드하고 로드 건수를 반환한다."""

        path = self.mapping_dir / f"v1_v2_pairs_{doc_short}.jsonl"
        if not path.exists():
            return 0
        count = 0
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = str(row.get("canonical_chunk_id") or "")
                if not key:
                    continue
                self._pairs[key] = row
                count += 1
        return count

    def get(self, canonical_chunk_id: str) -> dict | None:
        """canonical(v2) chunk id로 pair 정보를 조회한다."""

        return self._pairs.get(canonical_chunk_id)


def load_chunk_lookup(chunks_path: Path, docs: list[str] | None = None) -> dict[str, dict]:
    """청크 JSONL에서 id -> row 조회 딕셔너리를 로드한다."""

    allowed = set(docs or [])
    use_filter = bool(allowed)
    lookup: dict[str, dict] = {}
    with chunks_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            meta = row.get("metadata", {})
            if use_filter and meta.get("doc_short") not in allowed:
                continue
            lookup[row["id"]] = row
    return lookup
