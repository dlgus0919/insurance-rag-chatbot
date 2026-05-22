from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import pandas as pd
import pytest

from src.graph.store import GraphStore
from src.graph.extractors import (
    SurgeryGradeExtractor,
    PolicyAppendixExtractor,
    HiraCodeExtractor,
    NonpayStandardExtractor,
)
from src.graph.schema import NodeType, EdgeType


@pytest.fixture
def temp_db(tmp_path: Path) -> GraphStore:
    db_file = tmp_path / "test_graph.sqlite"
    return GraphStore(db_file)


def test_surgery_grade_extractor(temp_db: GraphStore, tmp_path: Path) -> None:
    # 1. Create a dummy chunks.jsonl
    chunks_file = tmp_path / "chunks.jsonl"
    dummy_chunks = [
        {
            "id": "ch_001",
            "text": "호흡기계, 흉부\n17. 편도, 아데노이드 절제수술\n기타 내용들",
            "metadata": {
                "doc_short": "실무가이드",
                "page_start": 79,
                "is_code_table": False,
            },
        }
    ]
    with open(chunks_file, "w", encoding="utf-8") as f:
        for chunk in dummy_chunks:
            f.write(json.dumps(chunk) + "\n")

    # 2. Create a dummy parquet file
    parquet_file = tmp_path / "surgery_grades.parquet"
    df_data = {
        "수술명": ["기관지 식도루 폐쇄술"],
        "수술명_원문": ["기관지 식도루 폐쇄술(원문)"],
        "수술해설": ["식도 부위를 절제하고 구멍을 봉합하는 수술"],
        "종_1_3": ["2"],
        "종_1_5": ["4"],
        "종_신1_5": ["4"],
        "source_page_label": [79],
        "source_file": ["p079_t00.json"],
    }
    pd.DataFrame(df_data).to_parquet(parquet_file, index=False)

    extractor = SurgeryGradeExtractor(temp_db)
    extractor.extract(chunks_file, parquet_file)

    # Verify procedure node
    nodes = temp_db.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.SurgeryProcedure.value,))
    assert len(nodes) == 1
    proc = nodes[0]
    assert proc["canonical_name"] == "기관지 식도루 폐쇄술"
    assert proc["normalized_name"] == "기관지식도루폐쇄술"

    props = json.loads(proc["properties_json"])
    assert props["grade_1_3"] == "2"
    assert props["grade_1_5"] == "4"
    assert props["grade_new_1_5"] == "4"

    # Verify category node & link
    cat_nodes = temp_db.query(
        "SELECT * FROM graph_nodes WHERE node_type = ? AND canonical_name = ?",
        (NodeType.SurgeryCategory.value, "17. 편도, 아데노이드 절제수술")
    )
    assert len(cat_nodes) == 1

    # Verify edge
    edges = temp_db.query("SELECT * FROM graph_edges WHERE edge_type = ?", (EdgeType.HAS_GRADE.value,))
    # We should have 3 grade edges (1-3종 2, 1-5종 4, 신1-5종 4)
    assert len(edges) == 3


def test_policy_appendix_extractor(temp_db: GraphStore, tmp_path: Path) -> None:
    # Create a dummy chunks.jsonl for appendix
    chunks_file = tmp_path / "chunks.jsonl"
    dummy_chunks = [
        {
            "id": "자사_SOL건강_v2_manual_ch_011755",
            "text": "호흡기계·흉부의 수술\n18. 기관(氣管), 기관지(氣管支), 폐(肺), 흉막(胸膜) 관혈수술 4",
            "metadata": {
                "doc_short": "자사_SOL건강",
                "section": "[별표7] 1-5종 수술분류표",
                "page_start": 384,
            },
        }
    ]
    with open(chunks_file, "w", encoding="utf-8") as f:
        for chunk in dummy_chunks:
            f.write(json.dumps(chunk) + "\n")

    extractor = PolicyAppendixExtractor(temp_db)
    extractor.extract(chunks_file)

    # Verify product and appendix nodes
    prod = temp_db.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.PolicyProduct.value,))
    assert len(prod) == 1

    app = temp_db.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.PolicyAppendix.value,))
    assert len(app) == 1

    # Verify benefit rule node
    rules = temp_db.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.PolicyBenefitRule.value,))
    assert len(rules) == 1
    rule = rules[0]
    assert rule["node_id"] == "rule_sol_health_별표7_18"
    assert rule["canonical_name"] == "기관(氣管), 기관지(氣管支), 폐(肺), 흉막(胸膜) 관혈수술"

    props = json.loads(rule["properties_json"])
    assert props["grade_value"] == "4"
    assert props["payment_ratio"] == "100%"
    assert props["category_large"] == "호흡기계·흉부의 수술"

    # Verify edges
    app_edge = temp_db.query("SELECT * FROM graph_edges WHERE edge_type = ?", (EdgeType.DEFINED_IN_APPENDIX.value,))
    assert len(app_edge) == 1
    assert app_edge[0]["source_node_id"] == "rule_sol_health_별표7_18"
    assert app_edge[0]["target_node_id"] == "app_sol_health_별표7"

    pays_edge = temp_db.query("SELECT * FROM graph_edges WHERE edge_type = ?", (EdgeType.PAYS_BY_RATIO.value,))
    assert len(pays_edge) == 1


def test_policy_appendix_extractor_regression_18_19(temp_db: GraphStore, tmp_path: Path) -> None:
    # Create a dummy chunks.jsonl for appendix containing the problematic text where grade '4' is on a lonely line.
    chunks_file = tmp_path / "chunks.jsonl"
    dummy_chunks = [
        {
            "id": "자사_SOL건강_v2_manual_ch_011755",
            "text": "호흡기계·흉부의 수술\n18. 기관(氣管), 기관지(氣管支), 폐(肺), 흉막(胸膜) 관혈수술\n4\n(개흉술(開胸術)을 수반하는 것에 한합니다)\n19. 개흉술(開胸術)을 수반하지 않는 폐장(肺臟) 수술 3",
            "metadata": {
                "doc_short": "자사_SOL건강",
                "section": "[별표7] 1-5종 수술분류표",
                "page_start": 384,
            },
        }
    ]
    with open(chunks_file, "w", encoding="utf-8") as f:
        for chunk in dummy_chunks:
            f.write(json.dumps(chunk) + "\n")

    extractor = PolicyAppendixExtractor(temp_db)
    extractor.extract(chunks_file)

    # Verify both rules 18 and 19 exist and are separated
    rules = temp_db.query("SELECT * FROM graph_nodes WHERE node_type = ? ORDER BY node_id", (NodeType.PolicyBenefitRule.value,))
    assert len(rules) == 2

    rule_18 = rules[0]
    assert rule_18["node_id"] == "rule_sol_health_별표7_18"
    assert "기관" in rule_18["canonical_name"]
    # Check that rule 19 text did not merge into rule 18
    assert "19." not in rule_18["canonical_name"]
    assert "개흉술(開胸術)을 수반하지 않는" not in rule_18["canonical_name"]

    props_18 = json.loads(rule_18["properties_json"])
    assert props_18["grade_value"] == "4"
    assert props_18["payment_ratio"] == "100%"

    rule_19 = rules[1]
    assert rule_19["node_id"] == "rule_sol_health_별표7_19"
    assert "개흉술" in rule_19["canonical_name"]

    props_19 = json.loads(rule_19["properties_json"])
    assert props_19["grade_value"] == "3"
    assert props_19["payment_ratio"] == "50%"


def test_hira_code_extractor(temp_db: GraphStore, tmp_path: Path) -> None:
    chunks_file = tmp_path / "chunks.jsonl"
    dummy_chunks = [
        {
            "id": "심평원_ch_001425",
            "text": "조-961 QZ966 로봇 보조 수술 Robot-assisted Surgery\n주: 1. 어쩌구",
            "metadata": {
                "doc_short": "심평원",
                "page_start": 812,
                "codes": ["QZ966"],
            },
        }
    ]
    with open(chunks_file, "w", encoding="utf-8") as f:
        for chunk in dummy_chunks:
            f.write(json.dumps(chunk) + "\n")

    extractor = HiraCodeExtractor(temp_db)
    extractor.extract(chunks_file)

    codes = temp_db.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.MedicalFeeCode.value,))
    assert len(codes) == 1
    code = codes[0]
    assert code["node_id"] == "hira_QZ966"
    assert code["canonical_name"] == "로봇 보조 수술"
    assert code["normalized_name"] == "QZ966"

    props = json.loads(code["properties_json"])
    assert props["classification_no"] == "조-961"
    assert props["code_system"] == "HIRA"


def test_nonpay_standard_extractor(temp_db: GraphStore, tmp_path: Path) -> None:
    standard_db_path = tmp_path / "standard_codes.sqlite"
    conn = sqlite3.connect(str(standard_db_path))
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE nonpay_standard (
            std_cd TEXT,
            std_cd_nm TEXT,
            mid_category_cd_nm TEXT,
            hira_care_type_cd_nm TEXT,
            ins_care_type_cd_nm TEXT,
            medical_class_cd_nm TEXT,
            item_class_level1cd_nm TEXT,
            item_class_level2cd_nm TEXT,
            pay_opn_cd_nm TEXT,
            notes TEXT,
            remarks TEXT,
            apply_start_date TEXT,
            apply_end_date TEXT
        );
        """
    )
    cursor.execute(
        """
        INSERT INTO nonpay_standard (
            std_cd, std_cd_nm, mid_category_cd_nm, hira_care_type_cd_nm,
            ins_care_type_cd_nm, medical_class_cd_nm, item_class_level1cd_nm,
            item_class_level2cd_nm, pay_opn_cd_nm, notes, remarks,
            apply_start_date, apply_end_date
        ) VALUES (
            'E7000', '도수치료', '도수치료중분류', '진료유형1',
            '의료분류1', '의료클래스1', '레벨1',
            '레벨2', '보상의견임', '비고임', 'remarks임',
            '2026-01-01', '2026-12-31'
        );
        """
    )
    conn.commit()
    conn.close()

    extractor = NonpayStandardExtractor(temp_db)
    extractor.extract(standard_db_path)

    nodes = temp_db.query("SELECT * FROM graph_nodes WHERE node_type = ?", (NodeType.NonpayStandardCode.value,))
    assert len(nodes) == 1
    node = nodes[0]
    assert node["node_id"] == "std_E7000"
    assert node["canonical_name"] == "도수치료"
    assert node["normalized_name"] == "E7000"

    props = json.loads(node["properties_json"])
    assert props["mid_category"] == "도수치료중분류"
    assert props["pay_opinion"] == "보상의견임"

    # Verify alias exists
    aliases = temp_db.query("SELECT * FROM graph_aliases WHERE node_id = ?", ("std_E7000",))
    assert len(aliases) == 1
    assert aliases[0]["alias"] == "도수치료"
    assert aliases[0]["normalized_alias"] == "도수치료"
