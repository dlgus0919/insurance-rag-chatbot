from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.graph.schema import Alias, Edge, Evidence, Node, EdgeType, NodeType
from src.graph.store import GraphStore


@pytest.fixture
def temp_db() -> str:
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        path = tmp.name
    yield path
    try:
        Path(path).unlink()
    except OSError:
        pass


def test_graph_store_crud(temp_db: str) -> None:
    store = GraphStore(temp_db)

    # 1. Node Upsert
    node1 = Node(
        node_id="proc_bronchial_fistula",
        node_type=NodeType.SurgeryProcedure,
        canonical_name="기관지 식도루 폐쇄술",
        normalized_name="기관지식도루폐쇄술",
        properties={"grade": "4종"}
    )
    store.upsert_node(node1)

    node2 = Node(
        node_id="grade_new_1_5_4",
        node_type=NodeType.SurgeryGrade,
        canonical_name="신1-5종 4종",
        normalized_name="신15종4종",
        properties={"payment_ratio": "50%"}
    )
    store.upsert_node(node2)

    nodes = store.query("SELECT * FROM graph_nodes;")
    assert len(nodes) == 2
    assert nodes[0]["node_id"] == "proc_bronchial_fistula"

    # Node update idempotency
    node1.properties = {"grade": "4종", "updated": True}
    store.upsert_node(node1)
    nodes = store.query("SELECT * FROM graph_nodes WHERE node_id = ?;", ("proc_bronchial_fistula",))
    assert len(nodes) == 1
    import json
    assert json.loads(nodes[0]["properties_json"])["updated"] is True

    # 2. Evidence Upsert
    evidence = Evidence(
        evidence_id="ev_001",
        chunk_id="chk_001",
        doc_short="실무가이드",
        page_start=80,
        row_text="기관지 식도루 폐쇄술 | 4종"
    )
    store.upsert_evidence(evidence)

    evs = store.query("SELECT * FROM graph_evidence;")
    assert len(evs) == 1
    assert evs[0]["evidence_id"] == "ev_001"

    # 3. Edge Upsert
    edge = Edge(
        edge_id="edge_001",
        source_node_id="proc_bronchial_fistula",
        target_node_id="grade_new_1_5_4",
        edge_type=EdgeType.HAS_GRADE,
        source_evidence_id="ev_001"
    )
    store.upsert_edge(edge)

    edges = store.query("SELECT * FROM graph_edges;")
    assert len(edges) == 1
    assert edges[0]["edge_id"] == "edge_001"

    # 4. Alias Add
    alias = Alias(
        alias_id="alias_001",
        node_id="proc_bronchial_fistula",
        alias="식도루폐쇄술",
        normalized_alias="식도루폐쇄술",
        source="manual"
    )
    store.add_alias(alias)

    aliases = store.query("SELECT * FROM graph_aliases;")
    assert len(aliases) == 1
    assert aliases[0]["alias_id"] == "alias_001"

    # 5. Link Node & Edge Evidence
    store.link_node_evidence("proc_bronchial_fistula", "ev_001", "source")
    store.link_edge_evidence("edge_001", "ev_001", "support")

    node_evs = store.query("SELECT * FROM graph_node_evidence;")
    assert len(node_evs) == 1
    assert node_evs[0]["role"] == "source"

    edge_evs = store.query("SELECT * FROM graph_edge_evidence;")
    assert len(edge_evs) == 1
    assert edge_evs[0]["role"] == "support"

    # 6. Cascade Delete test (Foreign Keys)
    store.execute("DELETE FROM graph_nodes WHERE node_id = ?;", ("proc_bronchial_fistula",))

    # node_id를 참조하는 edge와 alias가 자동으로 지워지는지 확인
    assert len(store.query("SELECT * FROM graph_edges;")) == 0
    assert len(store.query("SELECT * FROM graph_aliases;")) == 0
    assert len(store.query("SELECT * FROM graph_node_evidence;")) == 0

    store.close()


def test_graph_store_readonly_and_transaction(temp_db: str) -> None:
    # 1. Prepare data with standard store
    store = GraphStore(temp_db)
    node1 = Node(
        node_id="proc_test",
        node_type=NodeType.SurgeryProcedure,
        canonical_name="테스트 수술",
        normalized_name="테스트수술"
    )
    store.upsert_node(node1)
    store.commit()
    store.close()

    # 2. Test readonly missing file
    with pytest.raises(FileNotFoundError):
        GraphStore("non_existent_file_path_12345.sqlite", readonly=True)

    # 3. Test readonly operations
    ro_store = GraphStore(temp_db, readonly=True)

    # Read should succeed
    nodes = ro_store.query("SELECT * FROM graph_nodes;")
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == "proc_test"

    # Writes should raise PermissionError
    with pytest.raises(PermissionError):
        ro_store.upsert_node(node1)

    with pytest.raises(PermissionError):
        ro_store.execute("DELETE FROM graph_nodes;")

    with pytest.raises(PermissionError):
        ro_store.commit()

    with pytest.raises(PermissionError):
        with ro_store.transaction():
            pass

    ro_store.close()

    # 4. Test transactions (Success case)
    rw_store = GraphStore(temp_db)
    with rw_store.transaction():
        node2 = Node(
            node_id="proc_test_2",
            node_type=NodeType.SurgeryProcedure,
            canonical_name="테스트 수술2",
            normalized_name="테스트수술2"
        )
        rw_store.upsert_node(node2)

    nodes = rw_store.query("SELECT * FROM graph_nodes;")
    assert len(nodes) == 2

    # 5. Test transactions (Rollback case)
    try:
        with rw_store.transaction():
            node3 = Node(
                node_id="proc_test_3",
                node_type=NodeType.SurgeryProcedure,
                canonical_name="테스트 수술3",
                normalized_name="테스트수술3"
            )
            rw_store.upsert_node(node3)
            # Raise arbitrary exception to force rollback
            raise ValueError("Forced error")
    except ValueError:
        pass

    # Node 3 should not exist
    nodes = rw_store.query("SELECT * FROM graph_nodes WHERE node_id = 'proc_test_3';")
    assert len(nodes) == 0

    rw_store.close()
