# Intake Source Index Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 관리자 문서 intake 후보를 active ontology/rule에 반영할 때, 해당 문서 원문 chunk도 active 검색 소스와 BM25/Chroma/GraphDB 재빌드 입력에 포함한다.

**Architecture:** 신규 업로드 문서 원문은 기존 `data/processed/chunks_canonical_manifest.jsonl`을 직접 수정하지 않고 `data/intake/active_sources/chunks.jsonl` overlay로 승격한다. 인덱스와 GraphDB 빌드는 canonical manifest chunk에 active source overlay를 명시적으로 병합한다. `apply-approved`는 dry-run preflight, source promotion, ontology/rule apply, search index rebuild, GraphDB rebuild 순서로 실패 지점을 분리한다.

**Tech Stack:** FastAPI admin routes, JSONL intake/review stores, BM25/Chroma build scripts, SQLite GraphDB build script, pytest, Node test runner.

---

## Scope

P2는 P0/P1에서 생성 및 승인 가능한 후보가 실제 운영 검색 근거와 연결되도록 하는 작업이다.

포함한다:

- 디지털 PDF intake job의 `staging/chunks.jsonl`을 승인 반영 시 active source overlay로 승격한다.
- active source overlay를 `v2_only`, `v1_v2_combined` 인덱스 빌드와 GraphDB 빌드 입력에 포함한다.
- `apply-approved` 결과에 source promotion과 index rebuild 상태를 포함한다.
- source 승격이 불가능한 승인 후보는 active ontology/rule mutation 전에 preflight 실패로 멈춘다.

제외한다:

- 스캔 PDF OCR 자동화.
- Excel staging 및 Excel 후보 생성.
- 기존 canonical manifest의 원본 보정 OCR row 재작성.
- LLM 서버 기동 또는 모델 교체.
- 운영 데이터 파일을 Git에 커밋하는 작업.

## 000번 규칙 적용

- 신규 문서의 보험 지식은 후보 상태에서 시작하고 실무자 승인 후 active 자산으로만 반영한다.
- 원문 chunk는 지식 판단이 아니라 source evidence이므로 별도 overlay에 provenance와 함께 저장한다.
- 계산 rule 값은 후보 승인 경로를 통해서만 active rule table에 들어간다.
- 스캔 PDF는 텍스트 레이어 없음 경고로 차단하고 OCR 추론으로 보정하지 않는다.
- 일반 질의 기본 DB는 보정본 OCR 포함 경로인 `v2_only`를 유지하고, 신규 active source도 해당 경로에 병합한다.

## Files

- Create: `src/ingest/source_promotion.py`
  - active source overlay 경로, 승격 결과 모델, idempotent promotion, 승인 후보에서 intake source ref 수집 기능.
- Create: `tests/test_source_promotion.py`
  - overlay 승격, 중복 승격 방지, 승인 후보 source ref 수집 테스트.
- Modify: `scripts/build_index_from_canonical_manifest.py`
  - active source overlay를 canonical-derived chunks 뒤에 병합하는 함수와 CLI 옵션 추가.
- Create: `tests/test_build_index_from_canonical_manifest_active_sources.py`
  - 인덱스 빌드 입력에 active source chunk가 포함되는지 monkeypatch로 검증.
- Modify: `src/graph/build.py`
  - GraphDB build 입력에 active source overlay를 병합한다.
- Modify: `scripts/build_graph_index.py`
  - `--active-source-chunks` CLI 옵션을 추가해 `build_graph()`에 전달한다.
- Create: `tests/test_graph_build_active_sources.py`
  - GraphDB build helper가 canonical chunk와 active source chunk를 중복 없이 병합하는지 검증.
- Modify: `src/ingest/knowledge_apply.py`
  - source promotion preflight, source promotion, search index rebuild, GraphDB rebuild 순서로 apply pipeline 확장.
- Modify: `tests/test_knowledge_apply.py`
  - apply 순서, source preflight 실패, source promotion 이후 rebuild 호출 테스트.
- Modify: `frontend/js/pages/admin.js`
  - apply confirmation/result copy에 “문서 원문 검색 인덱스 반영”을 표시한다.
- Modify: `tests/test_admin_knowledge_frontend.mjs`
  - admin 화면 copy가 source/index 반영을 안내하는지 검증.
- Create: `docs/260_INTAKE_SOURCE_INDEX_PROMOTION_REPORT.md`
  - 구현 후 변경 파일, 검증 결과, 남은 위험을 기록한다.

## Task 1: Active Source Promotion Module

**Files:**
- Create: `src/ingest/source_promotion.py`
- Create: `tests/test_source_promotion.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_source_promotion.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from src.ingest.source_promotion import (
    collect_approved_intake_source_refs,
    load_active_source_chunks,
    load_active_source_manifest,
    promote_staging_chunks,
)
from src.parser.chunker import Chunk, save_chunks


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_promote_staging_chunks_appends_provenance_and_manifest(tmp_path: Path) -> None:
    staging_path = tmp_path / "jobs" / "intake_001" / "staging" / "chunks.jsonl"
    save_chunks(
        [
            Chunk(
                id="intake_001_doc_p001",
                text="4세대 급여 통원 80% 보상",
                metadata={
                    "doc_short": "intake_001_doc",
                    "doc_name": "새 약관",
                    "pdf_filename": "new_policy.pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "intake_job_id": "intake_001",
                },
            )
        ],
        staging_path,
    )
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    manifest_path = tmp_path / "active" / "manifest.jsonl"

    result = promote_staging_chunks(
        job_id="intake_001",
        staging_chunks_path=staging_path,
        source_filename="new_policy.pdf",
        active_chunks_path=active_chunks_path,
        manifest_path=manifest_path,
    )

    assert result.status == "promoted"
    assert result.chunk_count == 1
    chunks = load_active_source_chunks(active_chunks_path)
    assert [chunk.id for chunk in chunks] == ["intake_001_doc_p001"]
    assert chunks[0].metadata["source_status"] == "active_intake_source"
    assert chunks[0].metadata["source_method"] == "admin_digital_pdf_text_layer"
    assert chunks[0].metadata["source_filename"] == "new_policy.pdf"
    assert chunks[0].metadata["canonical_chunk_id"] == "intake_001_doc_p001"
    manifest = load_active_source_manifest(manifest_path)
    assert manifest[0]["job_id"] == "intake_001"
    assert manifest[0]["chunk_count"] == 1
    assert manifest[0]["source_filename"] == "new_policy.pdf"


def test_promote_staging_chunks_is_idempotent_by_job_id(tmp_path: Path) -> None:
    staging_path = tmp_path / "jobs" / "intake_001" / "staging" / "chunks.jsonl"
    save_chunks(
        [Chunk(id="intake_001_doc_p001", text="본문", metadata={"intake_job_id": "intake_001"})],
        staging_path,
    )
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    manifest_path = tmp_path / "active" / "manifest.jsonl"

    first = promote_staging_chunks(
        job_id="intake_001",
        staging_chunks_path=staging_path,
        source_filename="new_policy.pdf",
        active_chunks_path=active_chunks_path,
        manifest_path=manifest_path,
    )
    second = promote_staging_chunks(
        job_id="intake_001",
        staging_chunks_path=staging_path,
        source_filename="new_policy.pdf",
        active_chunks_path=active_chunks_path,
        manifest_path=manifest_path,
    )

    assert first.status == "promoted"
    assert second.status == "already_promoted"
    assert len(load_active_source_chunks(active_chunks_path)) == 1
    assert len(load_active_source_manifest(manifest_path)) == 1


def test_collect_approved_intake_source_refs_from_ontology_and_rule_candidates(tmp_path: Path) -> None:
    ontology_path = tmp_path / "ontology" / "candidates.jsonl"
    rule_path = tmp_path / "rules" / "candidates.jsonl"
    staging_path = tmp_path / "jobs" / "intake_001" / "staging" / "chunks.jsonl"
    _write_jsonl(
        ontology_path,
        [
            {
                "candidate_id": "dev.cov.demo.1",
                "concept_id": "cov.demo",
                "canonical_name": "테스트 보장",
                "status": "approved",
                "properties": {
                    "intake_job_id": "intake_001",
                    "source_filename": "new_policy.pdf",
                    "staging_chunks_path": str(staging_path),
                },
            },
            {
                "candidate_id": "dev.cov.demo.2",
                "concept_id": "cov.demo",
                "canonical_name": "미승인 보장",
                "status": "pending",
                "properties": {
                    "intake_job_id": "intake_002",
                    "staging_chunks_path": str(tmp_path / "jobs" / "intake_002" / "staging" / "chunks.jsonl"),
                },
            },
        ],
    )
    _write_jsonl(
        rule_path,
        [
            {
                "candidate_id": "rulecand.demo.1",
                "status": "approved",
                "intake_job_id": "intake_001",
                "source_filename": "new_policy.pdf",
                "staging_chunks_path": str(staging_path),
                "proposed_rule": {"rule_id": "rule.demo"},
            }
        ],
    )

    refs = collect_approved_intake_source_refs(
        ontology_candidates_path=ontology_path,
        rule_candidates_path=rule_path,
    )

    assert len(refs) == 1
    assert refs[0].job_id == "intake_001"
    assert refs[0].source_filename == "new_policy.pdf"
    assert refs[0].staging_chunks_path == staging_path
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_source_promotion.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.ingest.source_promotion'`.

- [ ] **Step 3: Create the promotion module**

Create `src/ingest/source_promotion.py`:

```python
"""Promote reviewed intake staging chunks into active retrieval source overlays."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import config
from src.claim_calculation.rule_candidates import load_jsonl
from src.ontology.review_store import OntologyReviewStore
from src.parser.chunker import Chunk, load_chunks, save_chunks

ACTIVE_SOURCE_ROOT = config.ROOT_DIR / "data" / "intake" / "active_sources"
ACTIVE_SOURCE_CHUNKS_PATH = ACTIVE_SOURCE_ROOT / "chunks.jsonl"
ACTIVE_SOURCE_MANIFEST_PATH = ACTIVE_SOURCE_ROOT / "manifest.jsonl"


@dataclass(frozen=True)
class IntakeSourceRef:
    job_id: str
    staging_chunks_path: Path
    source_filename: str


@dataclass(frozen=True)
class SourcePromotionResult:
    status: str
    job_id: str
    chunk_count: int
    chunks_path: str
    manifest_path: str
    source_filename: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_active_source_chunks(path: Path = ACTIVE_SOURCE_CHUNKS_PATH) -> list[Chunk]:
    if not path.exists():
        return []
    return load_chunks(path)


def load_active_source_manifest(path: Path = ACTIVE_SOURCE_MANIFEST_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def collect_approved_intake_source_refs(
    *,
    ontology_candidates_path: Path,
    rule_candidates_path: Path,
) -> list[IntakeSourceRef]:
    refs: dict[str, IntakeSourceRef] = {}
    ontology_store = OntologyReviewStore(candidates_path=ontology_candidates_path)
    for candidate in ontology_store.load_candidates():
        if candidate.status != "approved":
            continue
        ref = _ref_from_mapping(candidate.properties)
        if ref is not None:
            refs[ref.job_id] = ref

    for candidate in load_jsonl(rule_candidates_path):
        if candidate.get("status") != "approved":
            continue
        ref = _ref_from_mapping(candidate)
        if ref is not None:
            refs[ref.job_id] = ref
    return sorted(refs.values(), key=lambda item: item.job_id)


def promote_staging_chunks(
    *,
    job_id: str,
    staging_chunks_path: Path,
    source_filename: str,
    active_chunks_path: Path = ACTIVE_SOURCE_CHUNKS_PATH,
    manifest_path: Path = ACTIVE_SOURCE_MANIFEST_PATH,
) -> SourcePromotionResult:
    manifest = load_active_source_manifest(manifest_path)
    if any(row.get("job_id") == job_id for row in manifest):
        return SourcePromotionResult(
            status="already_promoted",
            job_id=job_id,
            chunk_count=0,
            chunks_path=str(active_chunks_path),
            manifest_path=str(manifest_path),
            source_filename=source_filename,
        )
    if not staging_chunks_path.exists():
        raise FileNotFoundError(f"staging chunks not found for {job_id}: {staging_chunks_path}")

    staged_chunks = load_chunks(staging_chunks_path)
    if not staged_chunks:
        raise ValueError(f"staging chunks are empty for {job_id}: {staging_chunks_path}")

    existing_chunks = load_active_source_chunks(active_chunks_path)
    existing_ids = {chunk.id for chunk in existing_chunks}
    promoted_chunks = [_promoted_chunk(chunk, job_id=job_id, source_filename=source_filename) for chunk in staged_chunks]
    duplicated = [chunk.id for chunk in promoted_chunks if chunk.id in existing_ids]
    if duplicated:
        raise ValueError(f"active source chunk id already exists for {job_id}: {duplicated[0]}")

    save_chunks([*existing_chunks, *promoted_chunks], active_chunks_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "job_id": job_id,
        "source_filename": source_filename,
        "staging_chunks_path": str(staging_chunks_path),
        "active_chunks_path": str(active_chunks_path),
        "chunk_count": len(promoted_chunks),
        "chunk_ids": [chunk.id for chunk in promoted_chunks],
        "promoted_at": utc_now_iso(),
    }
    with manifest_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return SourcePromotionResult(
        status="promoted",
        job_id=job_id,
        chunk_count=len(promoted_chunks),
        chunks_path=str(active_chunks_path),
        manifest_path=str(manifest_path),
        source_filename=source_filename,
    )


def _ref_from_mapping(payload: dict[str, Any]) -> IntakeSourceRef | None:
    job_id = str(payload.get("intake_job_id") or "").strip()
    staging_chunks = str(payload.get("staging_chunks_path") or "").strip()
    if not job_id or not staging_chunks:
        return None
    return IntakeSourceRef(
        job_id=job_id,
        staging_chunks_path=Path(staging_chunks),
        source_filename=str(payload.get("source_filename") or "").strip() or "uploaded_document",
    )


def _promoted_chunk(chunk: Chunk, *, job_id: str, source_filename: str) -> Chunk:
    metadata = dict(chunk.metadata)
    metadata["intake_job_id"] = job_id
    metadata["source_filename"] = source_filename
    metadata["source_status"] = "active_intake_source"
    metadata["source_method"] = "admin_digital_pdf_text_layer"
    metadata["canonical_chunk_id"] = metadata.get("canonical_chunk_id") or chunk.id
    metadata["source_chunk_id"] = metadata.get("source_chunk_id") or chunk.id
    return Chunk(id=chunk.id, text=chunk.text, metadata=metadata)
```

- [ ] **Step 4: Run source promotion tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_source_promotion.py -q
```

Expected: PASS, `3 passed`.

## Task 2: Search Index Build Includes Active Source Overlay

**Files:**
- Modify: `scripts/build_index_from_canonical_manifest.py`
- Create: `tests/test_build_index_from_canonical_manifest_active_sources.py`

- [ ] **Step 1: Write the failing index build test**

Create `tests/test_build_index_from_canonical_manifest_active_sources.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import scripts.build_index_from_canonical_manifest as builder
from src.parser.chunker import Chunk, load_chunks, save_chunks


def test_build_index_from_manifest_includes_active_source_overlay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "chunks_canonical_manifest.jsonl"
    manifest_path.write_text(
        json.dumps(
            {
                "canonical_chunk_id": "base_ch_001",
                "doc_short": "기존문서",
                "doc_name": "기존 문서",
                "pdf_filename": "base.pdf",
                "page_start": 1,
                "page_end": 1,
                "metadata": {"doc_short": "기존문서"},
                "source_variants": {
                    "v2_only": {
                        "available": True,
                        "variant_chunk_id": "base_ch_001",
                        "text": "기존 약관 본문",
                        "metadata": {"doc_short": "기존문서"},
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    save_chunks(
        [
            Chunk(
                id="intake_001_doc_p001",
                text="신규 약관 본문",
                metadata={
                    "doc_short": "intake_001_doc",
                    "page_start": 1,
                    "page_end": 1,
                    "source_status": "active_intake_source",
                },
            )
        ],
        active_chunks_path,
    )
    chunks_output = tmp_path / "processed" / "chunks_v2_manual.jsonl"
    index_root = tmp_path / "index_v2_manual"
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(builder, "build_index", lambda *, chunks_path, index_root: calls.append((chunks_path, index_root)))

    result = builder.build_index_from_manifest(
        canonical_manifest=manifest_path,
        index_mode="v2_only",
        chunks_output=chunks_output,
        index_root=index_root,
        active_source_chunks=active_chunks_path,
    )

    chunks = load_chunks(chunks_output)
    assert [chunk.id for chunk in chunks] == ["base_ch_001", "intake_001_doc_p001"]
    assert result["chunks"] == 2
    assert calls == [(chunks_output, index_root)]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_build_index_from_canonical_manifest_active_sources.py -q
```

Expected: FAIL because `build_index_from_manifest` is not defined.

- [ ] **Step 3: Refactor the index script with an explicit build function**

Modify `scripts/build_index_from_canonical_manifest.py` so the file contains this function above `main()`:

```python
from src.ingest.source_promotion import ACTIVE_SOURCE_CHUNKS_PATH, load_active_source_chunks


def build_index_from_manifest(
    *,
    canonical_manifest: Path,
    index_mode: str,
    chunks_output: Path,
    index_root: Path,
    active_source_chunks: Path | None = ACTIVE_SOURCE_CHUNKS_PATH,
) -> dict[str, object]:
    rows = load_canonical_manifest(canonical_manifest)
    chunks = iter_chunks_for_index_mode(rows, index_mode)
    chunks = _merge_active_source_chunks(chunks, active_source_chunks)
    save_chunks(chunks, chunks_output)
    build_index(chunks_path=chunks_output, index_root=index_root)
    return {
        "index_mode": index_mode,
        "chunks": len(chunks),
        "chunks_output": str(chunks_output),
        "index_root": str(index_root),
        "active_source_chunks": str(active_source_chunks) if active_source_chunks else "",
    }


def _merge_active_source_chunks(chunks: list, active_source_chunks: Path | None) -> list:
    if active_source_chunks is None or not active_source_chunks.exists():
        return chunks
    existing_ids = {chunk.id for chunk in chunks}
    merged = list(chunks)
    for chunk in load_active_source_chunks(active_source_chunks):
        if chunk.id not in existing_ids:
            merged.append(chunk)
            existing_ids.add(chunk.id)
    return merged
```

Then replace the body in `main()` after path resolution with:

```python
    result = build_index_from_manifest(
        canonical_manifest=canonical_manifest,
        index_mode=args.index_mode,
        chunks_output=chunks_output,
        index_root=index_root,
        active_source_chunks=args.active_source_chunks,
    )

    print(f"[canonical-index] mode: {result['index_mode']}")
    print(f"[canonical-index] chunks: {int(result['chunks']):,}")
    print(f"[canonical-index] chunks_output: {result['chunks_output']}")
    print(f"[canonical-index] index_root: {result['index_root']}")
    print(f"[canonical-index] active_source_chunks: {result['active_source_chunks']}")
```

Add this CLI argument after `--index-root`:

```python
    parser.add_argument(
        "--active-source-chunks",
        type=Path,
        default=ROOT / "data" / "intake" / "active_sources" / "chunks.jsonl",
        help="Optional active intake source overlay chunks.",
    )
```

Normalize the new argument before the function call:

```python
    active_source_chunks = args.active_source_chunks
    if active_source_chunks is not None and not active_source_chunks.is_absolute():
        active_source_chunks = ROOT / active_source_chunks
    args.active_source_chunks = active_source_chunks
```

- [ ] **Step 4: Run index build tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_build_index_from_canonical_manifest_active_sources.py -q
.venv/bin/python -m py_compile scripts/build_index_from_canonical_manifest.py
```

Expected: pytest PASS, `py_compile` exits 0.

## Task 3: GraphDB Build Includes Active Source Overlay

**Files:**
- Modify: `src/graph/build.py`
- Modify: `scripts/build_graph_index.py`
- Create: `tests/test_graph_build_active_sources.py`

- [ ] **Step 1: Write the failing graph merge test**

Create `tests/test_graph_build_active_sources.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.graph.build import _merge_active_source_chunks
from src.parser.chunker import Chunk, save_chunks


def test_merge_active_source_chunks_appends_without_duplicate(tmp_path: Path) -> None:
    active_chunks_path = tmp_path / "active" / "chunks.jsonl"
    save_chunks(
        [
            Chunk(id="base_ch_001", text="중복 본문", metadata={"doc_short": "기존문서"}),
            Chunk(id="intake_001_doc_p001", text="신규 본문", metadata={"doc_short": "intake_001_doc"}),
        ],
        active_chunks_path,
    )

    merged = _merge_active_source_chunks(
        [Chunk(id="base_ch_001", text="기존 본문", metadata={"doc_short": "기존문서"})],
        active_chunks_path,
    )

    assert [chunk.id for chunk in merged] == ["base_ch_001", "intake_001_doc_p001"]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_graph_build_active_sources.py -q
```

Expected: FAIL because `_merge_active_source_chunks` is not exported from `src.graph.build`.

- [ ] **Step 3: Add active source merge helper to GraphDB build**

Modify imports in `src/graph/build.py`:

```python
from src.parser.chunker import load_chunks, save_chunks
from src.ingest.source_promotion import ACTIVE_SOURCE_CHUNKS_PATH, load_active_source_chunks
```

Add this helper near the top-level helper functions:

```python
def _merge_active_source_chunks(chunks: list, active_source_chunks_path: str | Path | None) -> list:
    if not active_source_chunks_path:
        return chunks
    path = Path(active_source_chunks_path)
    if not path.exists():
        return chunks
    existing_ids = {chunk.id for chunk in chunks}
    merged = list(chunks)
    for chunk in load_active_source_chunks(path):
        if chunk.id not in existing_ids:
            merged.append(chunk)
            existing_ids.add(chunk.id)
    return merged
```

Extend the `build_graph()` signature:

```python
    active_source_chunks_path: str | Path | None = ACTIVE_SOURCE_CHUNKS_PATH,
) -> None:
```

Inside `build_graph()`, after `canonical_manifest_path` normalization, normalize the active source path:

```python
    active_source_chunks_path = Path(active_source_chunks_path) if active_source_chunks_path else None
```

Replace the canonical chunk resolution block with:

```python
    if canonical_manifest_path and canonical_manifest_path.exists() and source_mode in {"v2_only", "v1_v2_combined"}:
        rows = load_canonical_manifest(canonical_manifest_path)
        chunks = iter_chunks_for_index_mode(rows, source_mode)
        chunks = _merge_active_source_chunks(chunks, active_source_chunks_path)
        temp_chunk_file = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        temp_chunk_file.close()
        resolved_chunks_path = Path(temp_chunk_file.name)
        save_chunks(chunks, resolved_chunks_path)
    elif active_source_chunks_path and active_source_chunks_path.exists() and chunks_path.exists():
        chunks = _merge_active_source_chunks(load_chunks(chunks_path), active_source_chunks_path)
        temp_chunk_file = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        temp_chunk_file.close()
        resolved_chunks_path = Path(temp_chunk_file.name)
        save_chunks(chunks, resolved_chunks_path)
```

- [ ] **Step 4: Add CLI argument to graph build script**

Modify `scripts/build_graph_index.py` by adding this parser argument after `--canonical-manifest`:

```python
    parser.add_argument(
        "--active-source-chunks",
        type=str,
        default="data/intake/active_sources/chunks.jsonl",
        help="Optional active intake source overlay chunks.",
    )
```

Pass it to `build_graph()`:

```python
        active_source_chunks_path=args.active_source_chunks,
```

- [ ] **Step 5: Run graph tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_graph_build_active_sources.py -q
.venv/bin/python -m py_compile scripts/build_graph_index.py
```

Expected: pytest PASS, `py_compile` exits 0.

## Task 4: Wire Source Promotion Into Apply-Approved

**Files:**
- Modify: `src/ingest/knowledge_apply.py`
- Modify: `tests/test_knowledge_apply.py`

- [ ] **Step 1: Add failing apply pipeline tests**

Append these tests to `tests/test_knowledge_apply.py`:

```python
def test_apply_approved_knowledge_promotes_sources_before_mutation(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.collect_approved_intake_source_refs",
        lambda **_kwargs: ["source-ref"],
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.promote_approved_sources",
        lambda refs: calls.append(f"sources:{len(refs)}") or [{"status": "promoted", "job_id": "intake_001"}],
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda *, dry_run=False: calls.append(f"ontology:{dry_run}") or {"merged_candidate_count": 1},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_rule_candidates",
        lambda *, dry_run=False: calls.append(f"rules:{dry_run}") or {"applied_candidate_ids": ["rulecand.demo"]},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_search_indexes",
        lambda: calls.append("search-index") or None,
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert result.status == "completed"
    assert result.sources == [{"status": "promoted", "job_id": "intake_001"}]
    assert result.index_rebuilt is True
    assert calls == [
        "ontology:True",
        "rules:True",
        "sources:1",
        "ontology:False",
        "rules:False",
        "search-index",
        "graph",
    ]


def test_apply_approved_knowledge_stops_when_source_promotion_fails(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "src.ingest.knowledge_apply.collect_approved_intake_source_refs",
        lambda **_kwargs: ["source-ref"],
    )

    def fail_sources(refs):
        calls.append(f"sources:{len(refs)}")
        raise FileNotFoundError("staging chunks not found")

    monkeypatch.setattr("src.ingest.knowledge_apply.promote_approved_sources", fail_sources)
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_ontology_reviews",
        lambda *, dry_run=False: calls.append(f"ontology:{dry_run}") or {"merged_candidate_count": 1},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.apply_rule_candidates",
        lambda *, dry_run=False: calls.append(f"rules:{dry_run}") or {"applied_candidate_ids": ["rulecand.demo"]},
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_search_indexes",
        lambda: calls.append("search-index") or None,
    )
    monkeypatch.setattr(
        "src.ingest.knowledge_apply.rebuild_graph",
        lambda: calls.append("graph") or None,
    )

    result = apply_approved_knowledge()

    assert result.status == "failed_preflight"
    assert "staging chunks not found" in result.sources[0]["error"]
    assert calls == ["ontology:True", "rules:True", "sources:1"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_knowledge_apply.py -q
```

Expected: FAIL because `sources`, `index_rebuilt`, `collect_approved_intake_source_refs`, `promote_approved_sources`, and `rebuild_search_indexes` are not wired.

- [ ] **Step 3: Extend the apply result dataclass**

Modify `KnowledgeApplyResult` in `src/ingest/knowledge_apply.py`:

```python
@dataclass(frozen=True)
class KnowledgeApplyResult:
    status: str
    ontology: dict[str, Any]
    rules: dict[str, Any]
    graph_rebuilt: bool
    sources: list[dict[str, Any]]
    index_rebuilt: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Update existing return sites in tests and implementation to pass `sources=[]` and `index_rebuilt=False` where no source/index work has occurred.

- [ ] **Step 4: Add source promotion and index rebuild helpers**

Add imports to `src/ingest/knowledge_apply.py`:

```python
from src.ingest.source_promotion import (
    ACTIVE_SOURCE_CHUNKS_PATH,
    collect_approved_intake_source_refs,
    promote_staging_chunks,
)
```

Add these functions above `apply_approved_knowledge()`:

```python
def promote_approved_sources(refs) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for ref in refs:
        result = promote_staging_chunks(
            job_id=ref.job_id,
            staging_chunks_path=ref.staging_chunks_path,
            source_filename=ref.source_filename,
        )
        results.append(result.as_dict())
    return results


def rebuild_search_indexes() -> None:
    for mode in ("v2_only", "v1_v2_combined"):
        subprocess.run(
            [
                sys.executable,
                "scripts/build_index_from_canonical_manifest.py",
                "--index-mode",
                mode,
                "--active-source-chunks",
                str(ACTIVE_SOURCE_CHUNKS_PATH),
            ],
            cwd=config.ROOT_DIR,
            check=True,
        )
```

- [ ] **Step 5: Pass active source overlay to GraphDB rebuild**

Modify `rebuild_graph()` command list by adding:

```python
            "--active-source-chunks",
            str(ACTIVE_SOURCE_CHUNKS_PATH),
```

The final command list must include:

```python
        [
            sys.executable,
            "scripts/build_graph_index.py",
            "--rebuild",
            "--output",
            str(GRAPH_DB_PATH),
            "--manifest",
            str(GRAPH_MANIFEST_PATH),
            "--active-source-chunks",
            str(ACTIVE_SOURCE_CHUNKS_PATH),
        ],
```

- [ ] **Step 6: Update apply-approved ordering**

Replace `apply_approved_knowledge()` with:

```python
def apply_approved_knowledge() -> KnowledgeApplyResult:
    ontology_preflight: dict[str, Any] = {}
    source_results: list[dict[str, Any]] = []
    try:
        ontology_preflight = apply_ontology_reviews(dry_run=True)
        apply_rule_candidates(dry_run=True)
        refs = collect_approved_intake_source_refs(
            ontology_candidates_path=OntologyReviewStore().candidates_path,
            rule_candidates_path=DEFAULT_RULE_CANDIDATES_PATH,
        )
        source_results = promote_approved_sources(refs)
    except Exception as exc:
        return KnowledgeApplyResult(
            status="failed_preflight",
            ontology=ontology_preflight,
            rules={"error": str(exc), "error_type": type(exc).__name__},
            graph_rebuilt=False,
            sources=[{"error": str(exc), "error_type": type(exc).__name__}],
            index_rebuilt=False,
        )

    ontology = apply_ontology_reviews(dry_run=False)
    rules = apply_rule_candidates(dry_run=False)
    rebuild_search_indexes()
    rebuild_graph()
    return KnowledgeApplyResult(
        status="completed",
        ontology=ontology,
        rules=rules,
        graph_rebuilt=True,
        sources=source_results,
        index_rebuilt=True,
    )
```

- [ ] **Step 7: Run apply tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_knowledge_apply.py -q
```

Expected: PASS.

## Task 5: Admin UI Copy for Source/Index Apply

**Files:**
- Modify: `frontend/js/pages/admin.js`
- Modify: `tests/test_admin_knowledge_frontend.mjs`

- [ ] **Step 1: Write failing frontend copy test**

Append this test to `tests/test_admin_knowledge_frontend.mjs`:

```js
test('apply approved knowledge copy mentions source index rebuild', async () => {
  const moduleText = await readFile(new URL('../frontend/js/pages/admin.js', import.meta.url), 'utf8');

  assert.match(moduleText, /문서 원문 검색 인덱스/);
  assert.match(moduleText, /BM25\\/Chroma/);
});
```

- [ ] **Step 2: Run frontend test and verify failure**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: FAIL until the apply confirmation copy is updated.

- [ ] **Step 3: Update confirmation and success copy**

In `frontend/js/pages/admin.js`, replace the confirmation text in `applyApprovedKnowledgeFromAdmin()` with:

```js
    '승인된 온톨로지와 계산 룰 후보를 active 자산에 반영하고, 승인 후보의 문서 원문 검색 인덱스(BM25/Chroma)와 GraphDB를 재빌드합니다. 계속하시겠습니까?',
```

Replace the success toast with:

```js
        toast('승인된 지식 항목과 문서 원문 검색 인덱스를 active DB에 반영했습니다.', 'success');
```

- [ ] **Step 4: Run frontend tests**

Run:

```bash
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: PASS.

## Task 6: Implementation Report

**Files:**
- Create: `docs/260_INTAKE_SOURCE_INDEX_PROMOTION_REPORT.md`

- [ ] **Step 1: Create the report after implementation**

Create `docs/260_INTAKE_SOURCE_INDEX_PROMOTION_REPORT.md` with this structure:

```markdown
# 260 Intake Source Index Promotion Report

## Summary
- 디지털 PDF intake staging chunk를 실무자 승인 반영 시 active source overlay로 승격하도록 구현했다.
- active source overlay는 `data/intake/active_sources/chunks.jsonl`과 `manifest.jsonl`에 저장된다.
- BM25/Chroma 인덱스와 GraphDB rebuild는 canonical manifest chunk에 active source overlay를 병합한다.

## Changed Files
- `src/ingest/source_promotion.py`
- `scripts/build_index_from_canonical_manifest.py`
- `src/graph/build.py`
- `scripts/build_graph_index.py`
- `src/ingest/knowledge_apply.py`
- `frontend/js/pages/admin.js`
- 관련 테스트 파일

## Validation
- `.venv/bin/python -m pytest tests/test_source_promotion.py tests/test_build_index_from_canonical_manifest_active_sources.py tests/test_graph_build_active_sources.py tests/test_knowledge_apply.py -q`
- `node --test tests/test_admin_knowledge_frontend.mjs`
- `.venv/bin/python -m py_compile scripts/build_index_from_canonical_manifest.py scripts/build_graph_index.py`

## Guardrail Review
- 보험 지식 값은 코드에 추가하지 않았다.
- 신규 문서 원문은 active source evidence로만 승격되고, ontology/rule 지식은 승인 경로를 유지한다.
- 스캔 PDF OCR 자동화와 Excel staging은 이번 범위에 포함하지 않았다.

## Remaining Risks
- 실제 DGX 인덱스 재빌드는 embedding 계산이 포함되어 시간이 걸린다.
- 신규 문서가 매우 크면 `apply-approved` 응답 시간이 길어질 수 있다.
- Excel staging은 별도 작업 전까지 후보 생성과 source promotion 대상이 아니다.
```

- [ ] **Step 2: Run a placeholder scan on the report and plan**

Run:

```bash
python -c "from pathlib import Path; needles=['\\ubbf8\\uc815','\\uc791\\uc131 \\uc608\\uc815','\\ucd94\\ud6c4 \\uc791\\uc131','\\uc138\\ubd80 \\ub0b4\\uc6a9 \\ubcf4\\uac15','\\ub098\\uc911\\uc5d0']; paths=[Path('docs/260_INTAKE_SOURCE_INDEX_PROMOTION_REPORT.md'),Path('docs/superpowers/plans/2026-07-02-intake-source-index-promotion.md')]; hits=[(str(p),n) for p in paths if p.exists() for n in needles if n in p.read_text(encoding='utf-8')]; print(hits); raise SystemExit(1 if hits else 0)"
```

Expected: no matches.

## Local Verification

Run after all implementation tasks:

```bash
.venv/bin/python -m pytest tests/test_source_promotion.py tests/test_build_index_from_canonical_manifest_active_sources.py tests/test_graph_build_active_sources.py tests/test_knowledge_apply.py tests/test_intake_runner.py tests/test_api_admin_knowledge.py tests/test_file_intake_planner.py -q
node --test tests/test_admin_knowledge_frontend.mjs
.venv/bin/python -m py_compile scripts/build_index_from_canonical_manifest.py scripts/build_graph_index.py
```

Expected:

- Python tests pass.
- Node tests pass.
- Shell syntax checks exit 0.
- No LLM server is started.
- No scanned PDF OCR automation is introduced.

## DGX Verification

Patch the same changes to `/srv/shared/projects/insurance-rag-chatbot`, then run:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python -m pytest tests/test_source_promotion.py tests/test_build_index_from_canonical_manifest_active_sources.py tests/test_graph_build_active_sources.py tests/test_knowledge_apply.py tests/test_intake_runner.py tests/test_api_admin_knowledge.py tests/test_file_intake_planner.py -q && node --test tests/test_admin_knowledge_frontend.mjs && .venv/bin/python -m py_compile scripts/build_index_from_canonical_manifest.py scripts/build_graph_index.py'
```

Expected:

- Python tests pass.
- Node tests pass.
- Syntax checks pass.
- No LLM process is started or stopped.

## Manual Smoke on DGX

Use only a small digital PDF sample already approved for local runtime testing:

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python scripts/build_index_from_canonical_manifest.py --index-mode v2_only --active-source-chunks data/intake/active_sources/chunks.jsonl'
```

Expected:

- Command exits 0.
- Output prints `active_source_chunks`.
- Generated chunk count is greater than or equal to the base canonical `v2_only` count.

Do not run a full production rebuild during this smoke if another team member is using DGX resources.

## Self-Review Checklist

- [ ] `data/processed/chunks_canonical_manifest.jsonl` is not modified by intake source promotion.
- [ ] `data/intake/active_sources/chunks.jsonl` contains only source chunks with `intake_job_id`, `source_filename`, `canonical_chunk_id`, and `source_status`.
- [ ] Approved ontology/rule candidates still go through existing review and apply paths.
- [ ] `apply-approved` stops before mutation if source promotion fails.
- [ ] `v2_only` and `v1_v2_combined` search indexes include active source overlay.
- [ ] GraphDB rebuild receives the same active source overlay.
- [ ] Frontend copy no longer claims only GraphDB is rebuilt.
- [ ] No LLM server, OCR automation, or Excel candidate generation was added.

## Commit Guidance

Commit only after the user has authorized implementation commits:

```bash
git add src/ingest/source_promotion.py scripts/build_index_from_canonical_manifest.py src/graph/build.py scripts/build_graph_index.py src/ingest/knowledge_apply.py frontend/js/pages/admin.js tests/test_source_promotion.py tests/test_build_index_from_canonical_manifest_active_sources.py tests/test_graph_build_active_sources.py tests/test_knowledge_apply.py tests/test_admin_knowledge_frontend.mjs docs/260_INTAKE_SOURCE_INDEX_PROMOTION_REPORT.md
git commit -m "feat(knowledge): promote approved intake sources into indexes"
```

Push only when the user explicitly authorizes push.
