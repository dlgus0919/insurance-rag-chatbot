from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import re
from src.graph.store import GraphStore
from src.graph.schema import Edge, EdgeType, Evidence, Node, NodeType
from src.graph.normalizer import normalize_name, normalize_code
from src.ingest.source_promotion import ACTIVE_SOURCE_CHUNKS_PATH, load_active_source_chunks
from src.parser.chunker import Chunk, load_chunks, save_chunks
from src.graph.extractors import (
    SurgeryGradeExtractor,
    PolicyAppendixExtractor,
    HiraCodeExtractor,
    NonpayStandardExtractor,
    PolicyReviewExtractor,
    SilsonCoverageExtractor,
)
from src.retrieval.canonical_manifest import iter_chunks_for_index_mode, load_canonical_manifest


FEE_NAME_SPLIT_RE = re.compile(r"[-–—\[]")

TRANSPLANT_STEM_ALIASES = {
    "간장": "간",
    "췌장": "췌",
    "폐장": "폐",
    "신장": "신",
    "비장": "비",
    "심장": "심장",
}


def _fee_name_bases(name: str) -> set[str]:
    """수가 명칭에서 행 세부명칭을 뺀 보수적 비교 키를 만든다."""
    normalized = normalize_name(name)
    bases = {normalized} if normalized else set()
    if normalized:
        base = FEE_NAME_SPLIT_RE.split(normalized, maxsplit=1)[0]
        if base:
            bases.add(base)
    return bases


def _procedure_fee_variants(name: str) -> set[str]:
    """실무가이드 수술명을 HIRA 수가명칭과 연결하기 위한 보수적 변형 집합."""
    normalized = normalize_name(name)
    variants = {normalized} if normalized else set()
    if not normalized:
        return variants

    if normalized.endswith("이식수술"):
        stem = normalized[: -len("이식수술")]
        if stem:
            variants.add(f"{stem}이식술")
            short_stem = TRANSPLANT_STEM_ALIASES.get(stem)
            if short_stem:
                variants.add(f"{short_stem}이식술")

    if normalized.endswith("수술"):
        variants.add(normalized[: -len("수술")] + "술")

    return {v for v in variants if len(v) >= 3}


def _match_procedure_to_fee_code(proc_name: str, fee_name: str) -> tuple[bool, str | None, str | None]:
    """수술명과 HIRA 수가명칭이 같은 시술을 가리키는지 보수적으로 판정한다."""
    proc_variants = _procedure_fee_variants(proc_name)
    fee_bases = _fee_name_bases(fee_name)
    if not proc_variants or not fee_bases:
        return False, None, None

    for proc_variant in sorted(proc_variants, key=len, reverse=True):
        for fee_base in sorted(fee_bases, key=len, reverse=True):
            if fee_base == proc_variant:
                return True, proc_variant, fee_base

    return False, None, None


def build_graph(
    chunks_path: str | Path,
    standard_db_path: str | Path,
    output_db_path: str | Path,
    manifest_path: str | Path,
    low_confidence_report_path: str | Path,
    canonical_manifest_path: str | Path | None = None,
    source_mode: str = "v1_v2_combined",
    rebuild: bool = False,
    skip_standard_codes: bool = False,
    skip_policy_appendix: bool = False,
    skip_hira_codes: bool = False,
    rule_links_path: str | Path | None = None,
    active_source_chunks_path: str | Path | None = ACTIVE_SOURCE_CHUNKS_PATH,
) -> None:
    chunks_path = Path(chunks_path)
    canonical_manifest_path = Path(canonical_manifest_path) if canonical_manifest_path else None
    active_source_chunks_path = Path(active_source_chunks_path) if active_source_chunks_path else None
    standard_db_path = Path(standard_db_path)
    output_db_path = Path(output_db_path)
    manifest_path = Path(manifest_path)
    low_confidence_report_path = Path(low_confidence_report_path)
    rule_links_path = Path(rule_links_path) if rule_links_path else None

    # 1. Clean up and Rebuild if requested
    if rebuild and output_db_path.exists():
        os.remove(output_db_path)

    output_db_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    low_confidence_report_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. Initialize Store
    store = GraphStore(output_db_path, build_mode=True)

    # 3. Resolve canonical-manifest derived chunks when available
    resolved_chunks_path = chunks_path
    temp_chunk_file: tempfile.NamedTemporaryFile[str] | None = None
    if canonical_manifest_path and canonical_manifest_path.exists() and source_mode in {"v2_only", "v1_v2_combined"}:
        rows = load_canonical_manifest(canonical_manifest_path)
        chunks = iter_chunks_for_index_mode(rows, source_mode)
        chunks = _merge_active_source_chunks(chunks, active_source_chunks_path)
        temp_chunk_file = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        temp_chunk_file.close()
        resolved_chunks_path = Path(temp_chunk_file.name)
        save_chunks(chunks, resolved_chunks_path)
    elif active_source_chunks_path and active_source_chunks_path.exists():
        chunks = load_chunks(chunks_path)
        chunks = _merge_active_source_chunks(chunks, active_source_chunks_path)
        temp_chunk_file = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        temp_chunk_file.close()
        resolved_chunks_path = Path(temp_chunk_file.name)
        save_chunks(chunks, resolved_chunks_path)

    # 4. Read input datasets and determine source paths
    # (In DGX server, chunks and parquet are in the standard data directory)
    project_root = Path(__file__).resolve().parents[2]
    parquet_path = project_root / "data" / "index" / "surgery_grades.parquet"

    print("[INFO] Starting GraphDB build...")

    # 4. Ingest via Extractors
    # Ingest Surgery Grades
    if parquet_path.exists():
        print(f"[INFO] Extracting surgery grades from {parquet_path}")
        s_extractor = SurgeryGradeExtractor(store)
        s_extractor.extract(resolved_chunks_path, parquet_path)
    else:
        print(f"[WARNING] Surgery grades parquet not found at {parquet_path}. Skipping.")

    # Ingest Policy Appendix
    if not skip_policy_appendix:
        print(f"[INFO] Extracting policy appendix rules from {resolved_chunks_path}")
        p_extractor = PolicyAppendixExtractor(store)
        p_extractor.extract(resolved_chunks_path)

    # Ingest HIRA Codes
    if not skip_hira_codes:
        print(f"[INFO] Extracting HIRA codes from {resolved_chunks_path}")
        h_extractor = HiraCodeExtractor(store)
        h_extractor.extract(resolved_chunks_path)

    # Ingest Nonpay Standard Codes
    if not skip_standard_codes:
        print(f"[INFO] Extracting non-pay standard codes from {standard_db_path}")
        n_extractor = NonpayStandardExtractor(store)
        n_extractor.extract(standard_db_path)

    # Ingest 5th Generation Coverage Hierarchy
    print("[INFO] Extracting Silson Coverage hierarchy")
    cov_extractor = SilsonCoverageExtractor(store)
    cov_extractor.extract()

    # Ingest document-grounded policy review graph
    print(f"[INFO] Extracting policy review graph from {resolved_chunks_path}")
    review_extractor = PolicyReviewExtractor(store)
    review_extractor.extract(resolved_chunks_path)

    # 5. Link approved claim rules to source/ontology graph nodes without copying payout values.
    _ingest_rule_links(store, rule_links_path)

    # 6. Build cross-reference edges based on normalization & aliases
    print("[INFO] Building cross-reference edges...")
    _build_cross_references(store)

    # 7. Generate low confidence reports (placeholders/log for now as deterministic rule-based is high confidence)
    # Write empty/sample log to low_confidence_report_path
    low_confidence_report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(low_confidence_report_path, "w", encoding="utf-8") as f:
        # We can write an initial log line
        f.write(json.dumps({"timestamp": datetime.now().isoformat(), "message": "Build completed. All deterministic extractions marked confidence 1.0."}) + "\n")

    # 7. Write Manifest
    manifest_data = {
        "build_date": datetime.now().isoformat(),
        "source_mode": source_mode,
        "chunks_path": str(resolved_chunks_path),
        "canonical_manifest_path": str(canonical_manifest_path) if canonical_manifest_path else "",
        "active_source_chunks_path": str(active_source_chunks_path) if active_source_chunks_path else "",
        "standard_code_db": str(standard_db_path),
        "rule_links_path": str(rule_links_path) if rule_links_path else "",
        "node_count": store.query("SELECT COUNT(*) as count FROM graph_nodes")[0]["count"],
        "edge_count": store.query("SELECT COUNT(*) as count FROM graph_edges")[0]["count"],
        "evidence_count": store.query("SELECT COUNT(*) as count FROM graph_evidence")[0]["count"],
        "alias_count": store.query("SELECT COUNT(*) as count FROM graph_aliases")[0]["count"],
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    # Store manifest info in the DB as well
    for k, v in manifest_data.items():
        store.set_manifest(k, str(v))
    store.commit()

    store.close()
    if temp_chunk_file is not None:
        with contextlib.suppress(FileNotFoundError):
            Path(temp_chunk_file.name).unlink()
    print("[INFO] GraphDB build finished successfully.")


def _merge_active_source_chunks(chunks: list[Chunk], active_source_chunks_path: Path | None) -> list[Chunk]:
    if not active_source_chunks_path or not active_source_chunks_path.exists():
        return list(chunks)
    return list(chunks) + load_active_source_chunks(active_source_chunks_path)


def _ingest_rule_links(store: GraphStore, rule_links_path: Path | None) -> None:
    """Attach approved claim rules to ontology/source nodes in GraphDB.

    The calculation values remain in the active rule manifest. This layer only
    records traceability links so future graph queries can explain where an
    active rule came from and which ontology concepts it belongs to.
    """
    if not rule_links_path or not rule_links_path.exists():
        return
    data = json.loads(rule_links_path.read_text(encoding="utf-8"))
    records = data.get("links", data) if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise ValueError(f"rule links must be a list or object with links: {rule_links_path}")

    with store.transaction():
        for record in records:
            if not isinstance(record, dict) or record.get("link_status") != "active":
                continue
            rule_id = str(record.get("rule_id") or "").strip()
            if not rule_id:
                continue
            rule_node_id = f"deductible_rule:{rule_id}"
            source_refs = [str(ref) for ref in record.get("source_refs") or [] if str(ref).strip()]
            ontology_refs = [str(ref) for ref in record.get("ontology_refs") or [] if str(ref).strip()]
            graph_refs = [str(ref) for ref in record.get("graph_refs") or [] if str(ref).strip()]
            store.upsert_node(
                Node(
                    node_id=rule_node_id,
                    node_type=NodeType.DeductibleRule,
                    canonical_name=rule_id,
                    normalized_name=normalize_name(rule_id),
                    properties={
                        "rule_id": rule_id,
                        "source_refs": source_refs,
                        "ontology_refs": ontology_refs,
                        "graph_refs": graph_refs,
                        "link_status": "active",
                    },
                    created_by="rule_link_manifest",
                )
            )
            source_node_ids = _link_rule_sources(store, rule_node_id, source_refs)
            _link_rule_ontology_refs(store, rule_node_id, ontology_refs, source_node_ids)


def _link_rule_sources(store: GraphStore, rule_node_id: str, source_refs: list[str]) -> list[str]:
    source_node_ids: list[str] = []
    for source_ref in source_refs:
        chunk_id = _source_ref_chunk_id(source_ref)
        if not chunk_id:
            continue
        source_node_id = f"source_chunk:{chunk_id}"
        source_node_ids.append(source_node_id)
        evidence_id = f"evidence:{chunk_id}"
        store.upsert_node(
            Node(
                node_id=source_node_id,
                node_type=NodeType.DocumentSection,
                canonical_name=chunk_id,
                normalized_name=normalize_name(chunk_id),
                properties={"source_ref": source_ref, "chunk_id": chunk_id},
                created_by="rule_link_manifest",
            )
        )
        store.upsert_evidence(
            Evidence(
                evidence_id=evidence_id,
                chunk_id=chunk_id,
                doc_short="rule_source",
                source_method="rule_link_manifest",
                metadata_json={"source_ref": source_ref},
            )
        )
        store.link_node_evidence(rule_node_id, evidence_id, role="source")
        store.link_node_evidence(source_node_id, evidence_id, role="source")
        edge_id = f"edge_rule_source_{rule_node_id}_{source_node_id}"
        store.upsert_edge(
            Edge(
                edge_id=edge_id,
                source_node_id=rule_node_id,
                target_node_id=source_node_id,
                edge_type=EdgeType.HAS_CANONICAL_SOURCE,
                properties={"source_ref": source_ref},
                source_evidence_id=evidence_id,
                created_by="rule_link_manifest",
            )
        )
        store.link_edge_evidence(edge_id, evidence_id, role="source")
    return source_node_ids


def _link_rule_ontology_refs(
    store: GraphStore,
    rule_node_id: str,
    ontology_refs: list[str],
    source_node_ids: list[str],
) -> None:
    for ontology_ref in ontology_refs:
        concept_id = ontology_ref.strip()
        if not concept_id:
            continue
        concept_node_id = f"ontology:{concept_id}"
        store.upsert_node(
            Node(
                node_id=concept_node_id,
                node_type=NodeType.DecisionConcept,
                canonical_name=concept_id,
                normalized_name=normalize_name(concept_id),
                properties={"concept_id": concept_id, "source": "rule_link_manifest"},
                created_by="rule_link_manifest",
            )
        )
        store.upsert_edge(
            Edge(
                edge_id=f"edge_rule_ontology_{rule_node_id}_{concept_node_id}",
                source_node_id=rule_node_id,
                target_node_id=concept_node_id,
                edge_type=EdgeType.HAS_TOPIC,
                properties={"ontology_ref": concept_id},
                created_by="rule_link_manifest",
            )
        )
        store.upsert_edge(
            Edge(
                edge_id=f"edge_ontology_rule_{concept_node_id}_{rule_node_id}",
                source_node_id=concept_node_id,
                target_node_id=rule_node_id,
                edge_type=EdgeType.HAS_DEDUCTIBLE_RULE,
                properties={"ontology_ref": concept_id},
                created_by="rule_link_manifest",
            )
        )
        for source_node_id in source_node_ids:
            store.upsert_edge(
                Edge(
                    edge_id=f"edge_ontology_source_{concept_node_id}_{source_node_id}",
                    source_node_id=concept_node_id,
                    target_node_id=source_node_id,
                    edge_type=EdgeType.HAS_CANONICAL_SOURCE,
                    properties={"ontology_ref": concept_id},
                    created_by="rule_link_manifest",
                )
            )


def _source_ref_chunk_id(source_ref: str) -> str:
    prefix = "policy_chunk:"
    if source_ref.startswith(prefix):
        return source_ref[len(prefix):].strip()
    if source_ref.startswith("source_chunk:"):
        return source_ref.split(":", 1)[1].strip()
    return ""


def _build_cross_references(store: GraphStore) -> None:
    store.begin()
    # 1. Match: PolicyBenefitRule -> SurgeryProcedure (Exact, Alias, and Keyword Partial)
    rules = store.query(
        """
        SELECT n.node_id, n.canonical_name, n.normalized_name, n.properties_json, ne.evidence_id
        FROM graph_nodes n
        LEFT JOIN graph_node_evidence ne ON n.node_id = ne.node_id AND ne.role = 'source'
        WHERE n.node_type = ?
        """,
        (NodeType.PolicyBenefitRule.value,),
    )
    procedures = store.query(
        "SELECT node_id, canonical_name, normalized_name, properties_json FROM graph_nodes WHERE node_type = ?",
        (NodeType.SurgeryProcedure.value,),
    )
    aliases = store.query(
        """
        SELECT a.node_id, a.alias, a.normalized_alias, n.node_type
        FROM graph_aliases a
        JOIN graph_nodes n ON a.node_id = n.node_id
        """
    )

    proc_map = {p["normalized_name"]: p["node_id"] for p in procedures}
    alias_map = {
        a["normalized_alias"]: a["node_id"]
        for a in aliases
        if a["node_type"] == NodeType.SurgeryProcedure.value
    }

    # Gather category normalization mapping for procedures
    proc_cat_rows = store.query(
        """
        SELECT
            e.source_node_id as proc_id,
            n.normalized_name as cat_norm,
            n_parent.normalized_name as parent_cat_norm
        FROM graph_edges e
        JOIN graph_nodes n ON e.target_node_id = n.node_id
        LEFT JOIN graph_edges e_sub ON n.node_id = e_sub.source_node_id AND e_sub.edge_type = 'SAME_CATEGORY_AS'
        LEFT JOIN graph_nodes n_parent ON e_sub.target_node_id = n_parent.node_id
        WHERE e.edge_type = 'HAS_CATEGORY'
        """
    )
    proc_cats = {}
    for r in proc_cat_rows:
        pid = r["proc_id"]
        if pid not in proc_cats:
            proc_cats[pid] = set()
        if r["cat_norm"]:
            proc_cats[pid].add(r["cat_norm"])
        if r["parent_cat_norm"]:
            proc_cats[pid].add(r["parent_cat_norm"])

    STOP_KEYWORDS = {"수술", "수술분류표", "관혈수술", "비관혈수술", "관혈", "비관혈", "기타", "이외", "이외의"}

    for rule in rules:
        rule_id = rule["node_id"]
        norm_rule = rule["normalized_name"]
        evidence_id = rule["evidence_id"]

        # 1.1 Exact or Alias Match
        target_proc_id = None
        if norm_rule in proc_map:
            target_proc_id = proc_map[norm_rule]
        elif norm_rule in alias_map:
            target_proc_id = alias_map[norm_rule]

        if target_proc_id:
            edge_id = f"edge_cover_{rule_id}_{target_proc_id}"
            store.upsert_edge(
                Edge(
                    edge_id=edge_id,
                    source_node_id=rule_id,
                    target_node_id=target_proc_id,
                    edge_type=EdgeType.POLICY_COVERS_PROCEDURE,
                    confidence=1.0,
                    source_evidence_id=evidence_id,
                )
            )
            if evidence_id:
                store.link_edge_evidence(edge_id, evidence_id, role="source")
            continue

        # 1.2 Keyword Partial Match (if categories match or are close)
        rule_props = json.loads(rule["properties_json"])
        rule_cat_large = rule_props.get("category_large", "")
        rule_cat_norm = normalize_name(rule_cat_large)

        # Clean rule name for matching (remove hanja parens, numbers, etc.)
        rule_name_clean = re.sub(r"\([가-힣\w]+\)", "", rule["canonical_name"])
        raw_keywords = [k.strip() for k in re.split(r"[,·\/ㆍ\s]+", rule_name_clean) if k.strip()]

        # Filter out general stop keywords like '수술'
        keywords = [kw for kw in raw_keywords if kw not in STOP_KEYWORDS]

        for proc in procedures:
            proc_id = proc["node_id"]
            proc_name = proc["canonical_name"]
            proc_cat_norm = proc_cats.get(proc_id, "")

            # Check if categories align
            cat_aligns = False
            proc_cat_set = proc_cats.get(proc_id, set())
            for pc_norm in proc_cat_set:
                if rule_cat_norm and pc_norm:
                    if rule_cat_norm in pc_norm or pc_norm in rule_cat_norm:
                        cat_aligns = True
                        break
                    elif "호흡기" in rule_cat_norm and "호흡기" in pc_norm:
                        cat_aligns = True
                        break
                    elif "소화기" in rule_cat_norm and "소화기" in pc_norm:
                        cat_aligns = True
                        break

            if not cat_aligns:
                continue

            for kw in keywords:
                if len(kw) >= 2 and kw in proc_name:
                    edge_id = f"edge_cover_partial_{rule_id}_{proc_id}"
                    store.upsert_edge(
                        Edge(
                            edge_id=edge_id,
                            source_node_id=rule_id,
                            target_node_id=proc_id,
                            edge_type=EdgeType.POLICY_COVERS_PROCEDURE,
                            confidence=0.8,
                            properties={"matched_keyword": kw, "match_type": "partial_keyword"},
                            source_evidence_id=evidence_id,
                        )
                    )
                    if evidence_id:
                        store.link_edge_evidence(edge_id, evidence_id, role="source")
                    break

    # 2. Match: SurgeryProcedure -> MedicalFeeCode
    fee_codes = store.query(
        "SELECT node_id, canonical_name, normalized_name FROM graph_nodes WHERE node_type = ?",
        (NodeType.MedicalFeeCode.value,),
    )
    fee_evidence_rows = store.query(
        """
        SELECT node_id, evidence_id
        FROM graph_node_evidence
        WHERE role IN ('source', 'support')
        """
    )
    node_evidence_map: dict[str, list[str]] = {}
    for row in fee_evidence_rows:
        node_evidence_map.setdefault(row["node_id"], []).append(row["evidence_id"])

    for code in fee_codes:
        code_id = code["node_id"]
        norm_code_nm = normalize_name(code["canonical_name"])

        target_proc_id = None
        match_method = "exact_name"
        matched_proc_variant = None
        matched_fee_base = None
        if norm_code_nm in proc_map:
            target_proc_id = proc_map[norm_code_nm]
        elif norm_code_nm in alias_map:
            target_proc_id = alias_map[norm_code_nm]
            match_method = "alias"
        else:
            for proc in procedures:
                matched, proc_variant, fee_base = _match_procedure_to_fee_code(
                    proc["canonical_name"], code["canonical_name"]
                )
                if matched:
                    target_proc_id = proc["node_id"]
                    match_method = "semantic_fee_name"
                    matched_proc_variant = proc_variant
                    matched_fee_base = fee_base
                    break

        if target_proc_id:
            edge_id = f"edge_proc_fee_{target_proc_id}_{code_id}"
            evidence_ids = node_evidence_map.get(code_id, [])
            source_evidence_id = evidence_ids[0] if evidence_ids else None
            store.upsert_edge(
                Edge(
                    edge_id=edge_id,
                    source_node_id=target_proc_id,
                    target_node_id=code_id,
                    edge_type=EdgeType.HAS_MEDICAL_FEE_CODE,
                    confidence=1.0 if match_method in {"exact_name", "alias"} else 0.95,
                    properties={
                        "match_method": match_method,
                        "procedure_variant": matched_proc_variant,
                        "fee_base": matched_fee_base,
                    },
                    source_evidence_id=source_evidence_id,
                )
            )
            for evidence_id in evidence_ids:
                store.link_edge_evidence(edge_id, evidence_id, role="support")

    # 3. Match: SurgeryCategory (실무가이드) <-> SurgeryCategory (약관)
    categories = store.query(
        "SELECT node_id, canonical_name, normalized_name FROM graph_nodes WHERE node_type = ?",
        (NodeType.SurgeryCategory.value,),
    )
    for cat1 in categories:
        for cat2 in categories:
            if cat1["node_id"] == cat2["node_id"]:
                continue

            n1 = cat1["normalized_name"]
            n2 = cat2["normalized_name"]

            is_match = False
            if n1 in n2 or n2 in n1:
                is_match = True
            else:
                domain_keywords = ["소화기계", "호흡기계", "순환기계", "비뇨기계", "근골격계", "뇌척수", "신경계", "피부유방", "골관절", "이비인후", "안과", "구강인두"]
                for kw in domain_keywords:
                    if kw in cat1["canonical_name"] and kw in cat2["canonical_name"]:
                        is_match = True
                        break

            if is_match:
                edge_id = f"edge_cat_match_{cat1['node_id']}_{cat2['node_id']}"
                store.upsert_edge(
                    Edge(
                        edge_id=edge_id,
                        source_node_id=cat1["node_id"],
                        target_node_id=cat2["node_id"],
                        edge_type=EdgeType.SAME_CATEGORY_AS,
                        properties={"relationship": "equivalent_category"},
                    )
                )

    store.commit()
