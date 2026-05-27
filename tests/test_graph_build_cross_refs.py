from __future__ import annotations

import tempfile
from pathlib import Path

from src.graph.build import _build_cross_references
from src.graph.schema import Alias, EdgeType, Evidence, Node, NodeType
from src.graph.store import GraphStore


def _temp_db_path() -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    return tmp.name


def test_cross_references_link_transplant_fee_codes_with_evidence() -> None:
    path = _temp_db_path()
    try:
        store = GraphStore(path)
        for node in [
            Node("proc_간장이식수술", NodeType.SurgeryProcedure, "간장 이식수술", "간장이식수술"),
            Node("proc_췌장이식수술", NodeType.SurgeryProcedure, "췌장 이식수술", "췌장이식수술"),
            Node("hira_Q8040", NodeType.MedicalFeeCode, "간이식술-뇌사자(전간)", "간이식술-뇌사자전간"),
            Node("hira_Q8061", NodeType.MedicalFeeCode, "췌이식술-부분", "췌이식술-부분"),
            Node("hira_Q8062", NodeType.MedicalFeeCode, "췌이식술-췌장 및 십이지장", "췌이식술-췌장및십이지장"),
            Node("hira_SZ712", NodeType.MedicalFeeCode, "청성뇌간이식술", "청성뇌간이식술"),
            Node("std_Q8061UM1", NodeType.NonpayStandardCode, "췌이식술-부분", "Q8061UM1"),
        ]:
            store.upsert_node(node)

        store.add_alias(
            Alias(
                alias_id="alias_std_q8061",
                node_id="std_Q8061UM1",
                alias="췌이식술-부분",
                normalized_alias="췌이식술-부분",
                source="standard_code",
            )
        )

        for evidence in [
            Evidence("ev_Q8040", chunk_id="심평원_ch_liver", doc_short="심평원", page_start=638),
            Evidence("ev_Q8061", chunk_id="심평원_ch_001121", doc_short="심평원", page_start=638),
            Evidence("ev_Q8062", chunk_id="심평원_ch_001121", doc_short="심평원", page_start=638),
            Evidence("ev_SZ712", chunk_id="심평원_ch_brain", doc_short="심평원", page_start=999),
        ]:
            store.upsert_evidence(evidence)

        store.link_node_evidence("hira_Q8040", "ev_Q8040", "source")
        store.link_node_evidence("hira_Q8061", "ev_Q8061", "source")
        store.link_node_evidence("hira_Q8062", "ev_Q8062", "source")
        store.link_node_evidence("hira_SZ712", "ev_SZ712", "source")
        store.commit()

        _build_cross_references(store)

        rows = store.query(
            """
            SELECT source_node_id, target_node_id, properties_json, source_evidence_id
            FROM graph_edges
            WHERE edge_type = ?
            ORDER BY target_node_id
            """,
            (EdgeType.HAS_MEDICAL_FEE_CODE.value,),
        )

        pairs = {(row["source_node_id"], row["target_node_id"]) for row in rows}
        assert ("proc_간장이식수술", "hira_Q8040") in pairs
        assert ("proc_췌장이식수술", "hira_Q8061") in pairs
        assert ("proc_췌장이식수술", "hira_Q8062") in pairs
        assert ("proc_간장이식수술", "hira_SZ712") not in pairs
        assert ("std_Q8061UM1", "hira_Q8061") not in pairs

        pancreas_edges = [row for row in rows if row["source_node_id"] == "proc_췌장이식수술"]
        assert {row["source_evidence_id"] for row in pancreas_edges} == {"ev_Q8061", "ev_Q8062"}
        assert all('"match_method": "semantic_fee_name"' in row["properties_json"] for row in pancreas_edges)

        edge_evidence = store.query(
            """
            SELECT edge_id, evidence_id
            FROM graph_edge_evidence
            WHERE edge_id LIKE 'edge_proc_fee_proc_췌장이식수술_%'
            """
        )
        assert {row["evidence_id"] for row in edge_evidence} == {"ev_Q8061", "ev_Q8062"}
        store.close()
    finally:
        Path(path).unlink(missing_ok=True)
