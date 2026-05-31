"""GraphDB evidence와 Chroma VectorStore의 근거 청크 정합성 진단 유틸."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
import random
import re
import sqlite3
from typing import Any, Iterable

from src.retrieval.vector_store import _decode_metadata


@dataclass(frozen=True)
class EvidenceRow:
    evidence_id: str
    chunk_id: str
    doc_short: str
    page_start: int | None
    page_end: int | None
    source_method: str | None = None


@dataclass
class SyncCheckResult:
    evidence_id: str
    chunk_id: str
    doc_short: str
    page_start: int | None
    page_end: int | None
    status: str
    matched_id: str | None = None
    matched_by: str | None = None


def graph_chunk_fallback_ids(chunk_id: str) -> list[str]:
    """VectorStore.get_by_ids와 같은 Graph chunk id fallback 후보를 만든다."""

    fallbacks: list[str] = []
    normalized_id = re.sub(r"_(?:v2_manual|v1_original|v1_v2_combined)(?=_ch_)", "", chunk_id)
    if normalized_id != chunk_id:
        fallbacks.append(normalized_id)
    if chunk_id.startswith("v1_"):
        suffix = chunk_id[3:]
        fallbacks.append(f"v2_{suffix}")
        fallbacks.append(suffix)
    elif chunk_id.startswith("v2_"):
        suffix = chunk_id[3:]
        fallbacks.append(f"v1_{suffix}")
        fallbacks.append(suffix)
    else:
        fallbacks.append(f"v1_{chunk_id}")
        fallbacks.append(f"v2_{chunk_id}")
    for marker in ("_v2_manual_", "_v1_original_", "_v1_v2_combined_"):
        if marker in chunk_id:
            fallbacks.append(chunk_id.replace(marker, "_"))

    unique: list[str] = []
    seen: set[str] = set()
    for fallback in fallbacks:
        if fallback != chunk_id and fallback not in seen:
            seen.add(fallback)
            unique.append(fallback)
    return unique


def load_evidence_rows(
    graph_path: Path,
    *,
    limit: int | None,
    seed: int,
    doc_short: str | None = None,
    source_method: str | None = None,
) -> list[EvidenceRow]:
    """GraphDB에서 chunk_id가 있는 evidence row를 읽는다."""

    conditions = ["chunk_id IS NOT NULL", "chunk_id != ''"]
    params: list[Any] = []
    if doc_short:
        conditions.append("doc_short = ?")
        params.append(doc_short)
    if source_method:
        conditions.append("source_method = ?")
        params.append(source_method)

    query = (
        "SELECT evidence_id, chunk_id, doc_short, page_start, page_end, source_method "
        "FROM graph_evidence WHERE "
        + " AND ".join(conditions)
        + " ORDER BY evidence_id"
    )
    with sqlite3.connect(graph_path) as conn:
        rows = [
            EvidenceRow(
                evidence_id=str(row[0]),
                chunk_id=str(row[1]),
                doc_short=str(row[2]),
                page_start=row[3],
                page_end=row[4],
                source_method=row[5],
            )
            for row in conn.execute(query, params)
        ]

    if limit is not None and limit > 0 and len(rows) > limit:
        rng = random.Random(seed)
        rows = rng.sample(rows, limit)
        rows.sort(key=lambda item: item.evidence_id)
    return rows


def check_evidence_sync(rows: list[EvidenceRow], collection: Any) -> list[SyncCheckResult]:
    """Evidence row 목록을 direct/fallback/doc_page/missing으로 분류한다."""

    candidate_ids: list[str] = []
    fallback_map: dict[str, list[str]] = {}
    for row in rows:
        fallbacks = graph_chunk_fallback_ids(row.chunk_id)
        fallback_map[row.chunk_id] = fallbacks
        candidate_ids.append(row.chunk_id)
        candidate_ids.extend(fallbacks)

    unique_candidates = list(dict.fromkeys(candidate_ids))
    found_ids = _collection_get_ids(collection, unique_candidates)

    doc_page_cache: dict[str, list[tuple[str, int, int]]] = {}
    results: list[SyncCheckResult] = []
    for row in rows:
        if row.chunk_id in found_ids:
            results.append(
                SyncCheckResult(
                    evidence_id=row.evidence_id,
                    chunk_id=row.chunk_id,
                    doc_short=row.doc_short,
                    page_start=row.page_start,
                    page_end=row.page_end,
                    status="direct_hit",
                    matched_id=row.chunk_id,
                    matched_by="chunk_id",
                )
            )
            continue

        fallback_hit = next((candidate for candidate in fallback_map[row.chunk_id] if candidate in found_ids), None)
        if fallback_hit is not None:
            results.append(
                SyncCheckResult(
                    evidence_id=row.evidence_id,
                    chunk_id=row.chunk_id,
                    doc_short=row.doc_short,
                    page_start=row.page_start,
                    page_end=row.page_end,
                    status="fallback_hit",
                    matched_id=fallback_hit,
                    matched_by="chunk_id_fallback",
                )
            )
            continue

        if row.doc_short not in doc_page_cache:
            doc_page_cache[row.doc_short] = _load_doc_page_cache(collection, row.doc_short)
        page_hit = _find_doc_page_match(doc_page_cache[row.doc_short], row.page_start, row.page_end)
        if page_hit is not None:
            results.append(
                SyncCheckResult(
                    evidence_id=row.evidence_id,
                    chunk_id=row.chunk_id,
                    doc_short=row.doc_short,
                    page_start=row.page_start,
                    page_end=row.page_end,
                    status="doc_page_hit",
                    matched_id=page_hit,
                    matched_by="doc_page_overlap",
                )
            )
            continue

        results.append(
            SyncCheckResult(
                evidence_id=row.evidence_id,
                chunk_id=row.chunk_id,
                doc_short=row.doc_short,
                page_start=row.page_start,
                page_end=row.page_end,
                status="missing",
            )
        )
    return results


def summarize_results(results: Iterable[SyncCheckResult]) -> dict[str, Any]:
    rows = list(results)
    total = len(rows)
    status_counts = Counter(row.status for row in rows)
    by_doc: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_doc[row.doc_short][row.status] += 1

    return {
        "total": total,
        "status_counts": dict(status_counts),
        "hit_rate": _ratio(total - status_counts.get("missing", 0), total),
        "direct_hit_rate": _ratio(status_counts.get("direct_hit", 0), total),
        "fallback_recovery_rate": _ratio(
            status_counts.get("fallback_hit", 0) + status_counts.get("doc_page_hit", 0),
            total,
        ),
        "by_doc_short": {
            doc: {"total": sum(counter.values()), **dict(counter)}
            for doc, counter in sorted(by_doc.items(), key=lambda item: item[0])
        },
    }


def build_report(
    *,
    graph_path: Path,
    chroma_dir: Path,
    index_mode: str,
    rows: list[EvidenceRow],
    results: list[SyncCheckResult],
    example_limit: int,
) -> dict[str, Any]:
    return {
        "graph_path": str(graph_path),
        "chroma_dir": str(chroma_dir),
        "index_mode": index_mode,
        "sampled_evidence_rows": len(rows),
        "summary": summarize_results(results),
        "examples": {
            "fallback_hit": _examples(results, "fallback_hit", example_limit),
            "doc_page_hit": _examples(results, "doc_page_hit", example_limit),
            "missing": _examples(results, "missing", example_limit),
        },
    }


def _collection_get_ids(collection: Any, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    result = collection.get(ids=ids, include=["metadatas"])
    return set(result.get("ids", []) or [])


def _load_doc_page_cache(collection: Any, doc_short: str) -> list[tuple[str, int, int]]:
    try:
        result = collection.get(where={"doc_short": doc_short}, include=["metadatas"])
    except Exception:
        return []

    ids = result.get("ids", []) or []
    metadatas = result.get("metadatas", []) or []
    entries: list[tuple[str, int, int]] = []
    for index, hit_id in enumerate(ids):
        metadata = _decode_metadata(metadatas[index] if index < len(metadatas) else {})
        page_start = metadata.get("page_start")
        page_end = metadata.get("page_end", page_start)
        if page_start is None or page_end is None:
            continue
        try:
            entries.append((str(hit_id), int(page_start), int(page_end)))
        except (TypeError, ValueError):
            continue
    return entries


def _find_doc_page_match(
    cache: list[tuple[str, int, int]],
    page_start: int | None,
    page_end: int | None,
) -> str | None:
    if page_start is None:
        return None
    final_page_end = page_end if page_end is not None else page_start
    for hit_id, hit_start, hit_end in cache:
        if hit_start <= int(final_page_end) and hit_end >= int(page_start):
            return hit_id
    return None


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _examples(results: list[SyncCheckResult], status: str, limit: int) -> list[dict[str, Any]]:
    return [asdict(row) for row in results if row.status == status][:limit]
