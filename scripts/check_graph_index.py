#!/usr/bin/env python3
import argparse
import sys
import json
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.graph.store import GraphStore
from src.ontology.registry import get_default_ontology_registry

def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and inspect SQLite Property Graph index.")
    parser.add_argument(
        "--graph",
        type=str,
        default="data/index/graph/insurance_graph.sqlite",
        help="Path to the graph SQLite database."
    )
    args = parser.parse_args()

    graph_path = Path(args.graph)
    if not graph_path.exists():
        print(f"[ERROR] Graph database not found at {graph_path}", file=sys.stderr)
        sys.exit(1)

    print(f"=== Graph DB Inspection: {graph_path.name} ===")
    store = GraphStore(graph_path, readonly=True)

    # 1. Manifest
    print("\n--- Manifest Info ---")
    manifest_rows = store.query("SELECT key, value FROM graph_build_manifest")
    manifest = {row["key"]: row["value"] for row in manifest_rows}
    for k, v in manifest.items():
        print(f"  {k}: {v}")

    registry = get_default_ontology_registry()
    integrity_errors = registry.graph_manifest_integrity_errors(manifest)
    if integrity_errors:
        print("\n[FAIL] Graph ontology integrity manifest mismatch")
        for error in integrity_errors:
            print(f"  - {error}")
        store.close()
        sys.exit(1)

    # 2. Total Counts
    print("\n--- Summary Statistics ---")
    total_nodes = store.query("SELECT COUNT(*) as count FROM graph_nodes")[0]["count"]
    total_edges = store.query("SELECT COUNT(*) as count FROM graph_edges")[0]["count"]
    total_evidence = store.query("SELECT COUNT(*) as count FROM graph_evidence")[0]["count"]
    total_aliases = store.query("SELECT COUNT(*) as count FROM graph_aliases")[0]["count"]
    print(f"  Nodes: {total_nodes}")
    print(f"  Edges: {total_edges}")
    print(f"  Evidence: {total_evidence}")
    print(f"  Aliases: {total_aliases}")

    # 3. Node Type Counts
    print("\n--- Node Types ---")
    node_types = store.query("SELECT node_type, COUNT(*) as count FROM graph_nodes GROUP BY node_type")
    for r in node_types:
        print(f"  {r['node_type']}: {r['count']}")

    # 4. Edge Type Counts
    print("\n--- Edge Types ---")
    edge_types = store.query("SELECT edge_type, COUNT(*) as count FROM graph_edges GROUP BY edge_type")
    for r in edge_types:
        print(f"  {r['edge_type']}: {r['count']}")

    # 5. Low Confidence Counts
    print("\n--- Low Confidence Entities (confidence < 0.8) ---")
    low_nodes = store.query("SELECT COUNT(*) as count FROM graph_nodes WHERE confidence < 0.8")[0]["count"]
    low_edges = store.query("SELECT COUNT(*) as count FROM graph_edges WHERE confidence < 0.8")[0]["count"]
    print(f"  Low Confidence Nodes: {low_nodes}")
    print(f"  Low Confidence Edges: {low_edges}")

    # 6. Hard Query Coverage Check
    print("\n--- Hard Query Fixture Coverage ---")
    
    # Query 1 Check:
    # "기관지 식도루 폐쇄술" 수술 노드 존재 여부
    proc_bronchial = store.query(
        "SELECT * FROM graph_nodes WHERE node_type = 'SurgeryProcedure' AND normalized_name = '기관지식도루폐쇄술'"
    )
    q1_node_ok = len(proc_bronchial) > 0
    print(f"  Q1 Target Node (기관지 식도루 폐쇄술): {'PASS' if q1_node_ok else 'FAIL'}")
    
    # 신1-5종 등급 연결 여부
    q1_grade_ok = False
    if q1_node_ok:
        node_id = proc_bronchial[0]["node_id"]
        grades = store.query(
            """
            SELECT e.*, n.canonical_name 
            FROM graph_edges e 
            JOIN graph_nodes n ON e.target_node_id = n.node_id 
            WHERE e.source_node_id = ? AND e.edge_type = 'HAS_GRADE'
            """, 
            (node_id,)
        )
        for g in grades:
            if "신1-5종" in g["canonical_name"]:
                print(f"    - Has Grade: {g['canonical_name']}")
                q1_grade_ok = True
    
    # Peer procedures check
    q1_peers_ok = False
    if q1_grade_ok:
        # Find same grade peers
        # Check if there are other procedures connected to the same grade
        peers = store.query(
            """
            SELECT COUNT(DISTINCT source_node_id) as count 
            FROM graph_edges 
            WHERE target_node_id = (
                SELECT target_node_id FROM graph_edges 
                WHERE source_node_id = ? AND edge_type = 'HAS_GRADE' 
                AND target_node_id LIKE 'grade_new_1_5_%' LIMIT 1
            ) AND source_node_id != ?
            """,
            (node_id, node_id)
        )
        peer_count = peers[0]["count"]
        print(f"    - Same Grade Peer Procedures: {peer_count} found")
        q1_peers_ok = peer_count >= 3

    # SOL Appendix 7 mapping check
    q1_policy_ok = False
    if q1_node_ok:
        # Check if PolicyBenefitRule -> POLICY_COVERS_PROCEDURE -> SurgeryProcedure exists
        rule_edges = store.query(
            "SELECT * FROM graph_edges WHERE target_node_id = ? AND edge_type = 'POLICY_COVERS_PROCEDURE'",
            (node_id,)
        )
        if len(rule_edges) > 0:
            print(f"    - PolicyBenefitRule covers this procedure: Yes ({len(rule_edges)} edges)")
            q1_policy_ok = True
        else:
            print("    - PolicyBenefitRule covers this procedure: No")
            
    print(f"  Q1 Overall Coverage: {'PASS' if (q1_node_ok and q1_grade_ok and q1_peers_ok and q1_policy_ok) else 'FAIL'}")

    # Query 2 Check:
    # "소화기계" 카테고리에 속한 5종 수술
    digestive_nodes = store.query(
        "SELECT * FROM graph_nodes WHERE node_type = 'SurgeryCategory' AND normalized_name LIKE '%소화기계%'"
    )
    q2_cat_ok = len(digestive_nodes) > 0
    print(f"  Q2 Target Category (소화기계): {'PASS' if q2_cat_ok else 'FAIL'}")
    
    # Check if there are grade 5 procedures in digestive category
    q2_proc_ok = False
    if q2_cat_ok:
        # Query procedures in digestive categories that have 5종 (grade_new_1_5_5)
        digestive_grade5_procs = store.query(
            """
            SELECT DISTINCT p.canonical_name
            FROM graph_nodes p
            JOIN graph_edges e_cat ON p.node_id = e_cat.source_node_id AND e_cat.edge_type = 'HAS_CATEGORY'
            JOIN graph_edges e_grd ON p.node_id = e_grd.source_node_id AND e_grd.edge_type = 'HAS_GRADE'
            WHERE e_cat.target_node_id IN (
                SELECT node_id FROM graph_nodes WHERE node_type = 'SurgeryCategory' AND normalized_name LIKE '%소화기계%'
            ) AND e_grd.target_node_id = 'grade_new_1_5_5'
            """
        )
        print(f"    - Digestive Grade 5 Procedures: {len(digestive_grade5_procs)} found")
        q2_proc_ok = len(digestive_grade5_procs) > 0
        for p in digestive_grade5_procs[:3]:
            print(f"      * {p['canonical_name']}")
        if len(digestive_grade5_procs) > 3:
            print("      * ...")

    # Check if MedicalFeeCode is linked
    hira_link_count = store.query(
        "SELECT COUNT(*) as count FROM graph_edges WHERE edge_type = 'HAS_MEDICAL_FEE_CODE'"
    )[0]["count"]
    print(f"    - Medical Fee Code links count: {hira_link_count}")
    q2_fee_ok = hira_link_count > 0

    pancreas_fee_rows = store.query(
        """
        SELECT n.canonical_name, e.source_evidence_id
        FROM graph_edges e
        JOIN graph_nodes n ON e.target_node_id = n.node_id
        WHERE e.source_node_id = 'proc_췌장이식수술'
          AND e.edge_type = 'HAS_MEDICAL_FEE_CODE'
        ORDER BY n.canonical_name
        """
    )
    pancreas_fee_codes = [row["canonical_name"] for row in pancreas_fee_rows]
    q2_pancreas_fee_ok = {"췌이식술-부분", "췌이식술-췌장 및 십이지장"}.issubset(set(pancreas_fee_codes))
    q2_pancreas_evidence_ok = all(row["source_evidence_id"] for row in pancreas_fee_rows)
    print(f"    - Pancreas Transplant Fee Codes: {', '.join(pancreas_fee_codes) if pancreas_fee_codes else 'missing'}")
    print(f"    - Pancreas Fee Code Evidence: {'PASS' if q2_pancreas_evidence_ok else 'FAIL'}")
    
    # Check if Policy Appendix payment ratio mapping exists
    policy_ratio_count = store.query(
        "SELECT COUNT(*) as count FROM graph_edges WHERE edge_type = 'PAYS_BY_RATIO'"
    )[0]["count"]
    print(f"    - Policy Appendix payment ratio links count: {policy_ratio_count}")

    q2_overall = q2_cat_ok and q2_proc_ok and q2_fee_ok and q2_pancreas_fee_ok and q2_pancreas_evidence_ok and policy_ratio_count > 0
    print(f"  Q2 Overall Coverage: {'PASS' if q2_overall else 'FAIL'}")

    # 7. Detailed Rule, Grade, Payment Ratio & Evidence Verification
    print("\n--- Detailed Rule, Grade, Payment Ratio & Evidence Verification ---")
    import re
    cover_edges = store.query(
        """
        SELECT e.edge_id, e.source_node_id, e.target_node_id, e.source_evidence_id,
               n_rule.canonical_name as rule_name, n_rule.properties_json as rule_props,
               n_proc.canonical_name as proc_name
        FROM graph_edges e
        JOIN graph_nodes n_rule ON e.source_node_id = n_rule.node_id
        JOIN graph_nodes n_proc ON e.target_node_id = n_proc.node_id
        WHERE e.edge_type = 'POLICY_COVERS_PROCEDURE'
        """
    )
    
    total_cover_edges = len(cover_edges)
    print(f"  Total POLICY_COVERS_PROCEDURE edges: {total_cover_edges}")
    
    if total_cover_edges == 0:
        print("  [FAIL] No POLICY_COVERS_PROCEDURE edges found.")
        sys.exit(1)
        
    invalid_rules = 0
    invalid_evidence = 0
    invalid_edge_evidence = 0
    
    for idx, edge in enumerate(cover_edges):
        # 1) Rule Properties Validation
        try:
            props = json.loads(edge["rule_props"])
        except Exception:
            props = {}
            
        rule_no = props.get("appendix_number")
        grade = props.get("grade_value")
        ratio = props.get("payment_ratio")
        
        # Validate rule number (should be format like '18' or '17-1')
        if not rule_no or not re.match(r"^\d+(?:-\d+)?$", str(rule_no)):
            if invalid_rules < 5:
                print(f"    - Invalid rule number '{rule_no}' for node {edge['source_node_id']}")
            invalid_rules += 1
            
        # Validate grade (should be 1-5 or N)
        if not grade or str(grade) not in {"1", "2", "3", "4", "5", "N"}:
            if invalid_rules < 5:
                print(f"    - Invalid grade '{grade}' for node {edge['source_node_id']}")
            invalid_rules += 1
            
        # Validate payment ratio (should be 0%, 10%, 30%, 50%, 100%)
        if not ratio or str(ratio) not in {"0%", "10%", "30%", "50%", "100%"}:
            if invalid_rules < 5:
                print(f"    - Invalid payment ratio '{ratio}' for node {edge['source_node_id']}")
            invalid_rules += 1
            
        # 2) source_evidence_id Validation
        sev_id = edge["source_evidence_id"]
        if not sev_id:
            if invalid_evidence < 5:
                print(f"    - Missing source_evidence_id on edge {edge['edge_id']}")
            invalid_evidence += 1
        else:
            # Check if evidence exists in graph_evidence
            ev_exists = store.query("SELECT COUNT(*) as count FROM graph_evidence WHERE evidence_id = ?", (sev_id,))[0]["count"]
            if ev_exists == 0:
                if invalid_evidence < 5:
                    print(f"    - Evidence ID '{sev_id}' on edge {edge['edge_id']} does not exist in graph_evidence")
                invalid_evidence += 1
                
        # 3) graph_edge_evidence Validation
        edge_id = edge["edge_id"]
        if sev_id:
            ee_exists = store.query(
                "SELECT COUNT(*) as count FROM graph_edge_evidence WHERE edge_id = ? AND evidence_id = ?",
                (edge_id, sev_id)
            )[0]["count"]
            if ee_exists == 0:
                if invalid_edge_evidence < 5:
                    print(f"    - Mapping in graph_edge_evidence missing for edge {edge_id} and evidence {sev_id}")
                invalid_edge_evidence += 1

    print(f"  Validation Summary:")
    print(f"    - Invalid Rule Props (rule_no/grade/ratio): {invalid_rules}")
    print(f"    - Missing/Invalid source_evidence_id: {invalid_evidence}")
    print(f"    - Missing graph_edge_evidence mapping: {invalid_edge_evidence}")
    
    q3_ok = (invalid_rules == 0) and (invalid_evidence == 0) and (invalid_edge_evidence == 0)
    print(f"  Detailed Integrity Check: {'PASS' if q3_ok else 'FAIL'}")
    
    if not q3_ok:
        sys.exit(1)

    store.close()

if __name__ == "__main__":
    main()
