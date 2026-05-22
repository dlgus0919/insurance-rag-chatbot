from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
import pandas as pd

from src.graph.schema import Node, Edge, Evidence, Alias, NodeType, EdgeType
from src.graph.normalizer import normalize_name, normalize_code


class SurgeryGradeExtractor:
    """Reads surgery_grades.parquet and extracts SurgeryProcedure, SurgeryGrade, SurgeryCategory nodes and edges."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, chunks_path: str | Path, parquet_path: str | Path) -> None:
        self.store.begin()
        chunks_path = Path(chunks_path)
        parquet_path = Path(parquet_path)

        # 1. Build page to category mapping from chunks
        page_to_category: dict[int, tuple[str, str]] = {}
        large_pattern = re.compile(
            r"("
            r"피부,\s*유방의?\s*(?:수술)?|"
            r"호흡기계\s*,\s*흉부의?\s*(?:수술)?|호흡기계\s*(?:및\s*흉부)?\s*(?:의?\s*수술)?|"
            r"순환기계\s*(?:,\s*비장)?\s*(?:의?\s*수술)?|"
            r"소화기계\s*(?:의?\s*수술)?|"
            r"비뇨기계\s*(?:,\s*생식기계)?\s*(?:의?\s*수술)?|"
            r"눈의?\s*(?:수술)?|"
            r"귀\s*,\s*코의?\s*(?:수술)?|"
            r"뇌\s*,\s*척수의?\s*(?:수술)?|"
            r"골\s*,\s*관절의?\s*(?:수술)?|사지관절의?\s*(?:수술)?|"
            r"근골격계\s*(?:의?\s*수술)?|"
            r"구강\s*,\s*인두\s*,\s*인후의?\s*(?:수술)?|"
            r"상기\s*이외의\s*수술"
            r")"
        )
        medium_pattern = re.compile(r"^(\d+(?:-\d+)?)\.\s*(.*)")

        current_large = "일반 수술"
        current_medium = "일반"

        # Scan chunks sequentially by page to establish current categories
        chunks: list[dict] = []
        if chunks_path.exists():
            with open(chunks_path, encoding="utf-8") as f:
                for line in f:
                    c = json.loads(line)
                    if c["metadata"]["doc_short"] == "실무가이드":
                        chunks.append(c)

        # Sort chunks by page_start
        chunks.sort(key=lambda x: x["metadata"]["page_start"] or 0)

        for chunk in chunks:
            page = chunk["metadata"]["page_start"]
            if not page:
                continue
            text = chunk["text"]
            is_code_table = chunk["metadata"].get("is_code_table", False)

            if not is_code_table:
                for line in text.split("\n"):
                    line_clean = line.strip()
                    if not line_clean:
                        continue
                    # Match large category
                    large_match = large_pattern.search(line_clean)
                    if large_match:
                        current_large = large_match.group(1).strip()
                    # Match medium category
                    medium_match = medium_pattern.match(line_clean)
                    if medium_match:
                        current_medium = f"{medium_match.group(1)}. {medium_match.group(2).strip()}"

            page_to_category[page] = (current_large, current_medium)

        # 2. Read parquet and load nodes/edges
        df = pd.read_parquet(parquet_path)
        for _, row in df.iterrows():
            proc_name = str(row["수술명"]).strip()
            proc_name_raw = str(row["수술명_원문"]).strip()
            desc = str(row["수술해설"]).strip()
            g_13 = str(row["종_1_3"]).strip()
            g_15 = str(row["종_1_5"]).strip()
            g_s15 = str(row["종_신1_5"]).strip()
            page = int(row["source_page_label"])
            source_file = str(row["source_file"])

            # Normalized name
            norm_proc_name = normalize_name(proc_name)
            node_id = f"proc_{norm_proc_name}"

            # Create SurgeryProcedure Node
            proc_node = Node(
                node_id=node_id,
                node_type=NodeType.SurgeryProcedure,
                canonical_name=proc_name,
                normalized_name=norm_proc_name,
                properties={
                    "procedure_name": proc_name,
                    "procedure_name_raw": proc_name_raw,
                    "description": desc,
                    "grade_1_3": g_13,
                    "grade_1_5": g_15,
                    "grade_new_1_5": g_s15,
                    "source_doc_priority": "실무가이드",
                    "source_page_label": page,
                    "source_file": source_file,
                },
                confidence=1.0,
            )
            self.store.upsert_node(proc_node)

            # Link with Evidence
            ev_id = f"ev_proc_{norm_proc_name}_{page}"
            evidence = Evidence(
                evidence_id=ev_id,
                doc_short="실무가이드",
                doc_name="Claim 실무종합가이드",
                pdf_filename="Claim 실무종합가이드.pdf",
                page_start=page,
                page_end=page,
                source_version="v2_manual" if "v2" in source_file else "v1",
                source_method="table_index",
                row_text=f"{proc_name} | {desc} | {g_13} | {g_15} | {g_s15}",
                confidence=1.0,
            )
            self.store.upsert_evidence(evidence)
            self.store.link_node_evidence(node_id, ev_id, role="source")

            # Create alias if raw name is different
            if proc_name != proc_name_raw and proc_name_raw:
                norm_raw = normalize_name(proc_name_raw)
                alias_id = f"alias_proc_{norm_proc_name}_raw"
                alias_obj = Alias(
                    alias_id=alias_id,
                    node_id=node_id,
                    alias=proc_name_raw,
                    normalized_alias=norm_raw,
                    source="실무가이드_raw",
                    confidence=1.0,
                )
                self.store.add_alias(alias_obj)

            # Connect Category with preceding page fallback
            cat_large, cat_medium = "일반 수술", "일반"
            sorted_pages = sorted(page_to_category.keys())
            for p in sorted_pages:
                if p <= page:
                    cat_large, cat_medium = page_to_category[p]
                else:
                    break

            large_cat_id = f"cat_{normalize_name(cat_large)}"
            medium_cat_id = f"cat_{normalize_name(cat_medium)}"

            # Upsert Category Nodes
            self.store.upsert_node(
                Node(
                    node_id=large_cat_id,
                    node_type=NodeType.SurgeryCategory,
                    canonical_name=cat_large,
                    normalized_name=normalize_name(cat_large),
                )
            )
            self.store.upsert_node(
                Node(
                    node_id=medium_cat_id,
                    node_type=NodeType.SurgeryCategory,
                    canonical_name=cat_medium,
                    normalized_name=normalize_name(cat_medium),
                )
            )

            # Link categories
            edge_cat_relation_id = f"edge_cat_sub_{normalize_name(cat_medium)}_{normalize_name(cat_large)}"
            self.store.upsert_edge(
                Edge(
                    edge_id=edge_cat_relation_id,
                    source_node_id=medium_cat_id,
                    target_node_id=large_cat_id,
                    edge_type=EdgeType.SAME_CATEGORY_AS,
                    properties={"relationship": "subclass_of"},
                )
            )

            # Link procedure to medium category
            edge_proc_cat_id = f"edge_proc_cat_{norm_proc_name}_{normalize_name(cat_medium)}"
            self.store.upsert_edge(
                Edge(
                    edge_id=edge_proc_cat_id,
                    source_node_id=node_id,
                    target_node_id=medium_cat_id,
                    edge_type=EdgeType.HAS_CATEGORY,
                )
            )

            # Link procedure to large category directly as well
            edge_proc_large_cat_id = f"edge_proc_cat_{norm_proc_name}_{normalize_name(cat_large)}"
            self.store.upsert_edge(
                Edge(
                    edge_id=edge_proc_large_cat_id,
                    source_node_id=node_id,
                    target_node_id=large_cat_id,
                    edge_type=EdgeType.HAS_CATEGORY,
                )
            )

            # Connect Grades
            grades_to_link = [
                ("1-3종", g_13, "grade_1_3"),
                ("1-5종", g_15, "grade_1_5"),
                ("신1-5종", g_s15, "grade_new_1_5"),
            ]
            for grade_system, grade_val, prefix in grades_to_link:
                if not grade_val or grade_val in ("N", "", "nan", "None"):
                    continue
                grade_node_id = f"{prefix}_{grade_val}"
                grade_canonical = f"{grade_system} {grade_val}종"

                # Upsert Grade Node
                self.store.upsert_node(
                    Node(
                        node_id=grade_node_id,
                        node_type=NodeType.SurgeryGrade,
                        canonical_name=grade_canonical,
                        normalized_name=normalize_name(grade_canonical),
                        properties={"grade_system": grade_system, "grade_value": grade_val},
                    )
                )

                # Link procedure to grade
                edge_grade_id = f"edge_grade_{norm_proc_name}_{prefix}_{grade_val}"
                self.store.upsert_edge(
                    Edge(
                        edge_id=edge_grade_id,
                        source_node_id=node_id,
                        target_node_id=grade_node_id,
                        edge_type=EdgeType.HAS_GRADE,
                        source_evidence_id=ev_id,
                    )
                )
        self.store.commit()


class PolicyAppendixExtractor:
    """Extracts PolicyProduct, PolicyAppendix, PolicyBenefitRule nodes and edges from 자사_SOL건강 Appendix 7 chunks."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, chunks_path: str | Path) -> None:
        self.store.begin()
        chunks_path = Path(chunks_path)
        if not chunks_path.exists():
            return

        # 1. Ensure PolicyProduct and PolicyAppendix Nodes exist
        product_id = "prod_sol_health"
        product_node = Node(
            node_id=product_id,
            node_type=NodeType.PolicyProduct,
            canonical_name="신한 SOL 처음건강보험(무배당)(자동갱신형)",
            normalized_name=normalize_name("신한 SOL 처음건강보험"),
        )
        self.store.upsert_node(product_node)

        appendix_id = "app_sol_health_별표7"
        appendix_node = Node(
            node_id=appendix_id,
            node_type=NodeType.PolicyAppendix,
            canonical_name="[별표7] 1-5종 수술분류표",
            normalized_name=normalize_name("별표7 1-5종 수술분류표"),
        )
        self.store.upsert_node(appendix_node)

        # Link appendix to product
        self.store.upsert_edge(
            Edge(
                edge_id="edge_app_appears_in_prod",
                source_node_id=appendix_id,
                target_node_id=product_id,
                edge_type=EdgeType.APPEARS_IN,
            )
        )

        # 2. Parse Appendix Chunks
        large_cats = [
            "피부, 유방의 수술", "호흡기계·흉부의 수술", "호흡기계, 흉부의 수술", "호흡기계ㆍ흉부의 수술", "호흡기계·흉부",
            "순환기계, 비장의 수술", "순환기계, 비장(변식)의 수술", "소화기계의 수술", "비뇨기계·생식기계의 수술",
            "눈의 수술", "귀, 코의 수술", "뇌, 척수의 수술", "골, 관절의 수술", "사지, 골, 관절, 근육의 수술",
            "사지관절의 수술", "근골격계의 수술", "구강, 인두, 인후의 수술"
        ]

        large_pattern_str = "|".join(re.escape(cat) for cat in large_cats)
        rule_pattern = re.compile(
            r"(\d+(?:-\d+)?)\.\s*(.+?)\s+([1-5N])(?=\s+\d+(?:-\d+)?\.\s*|\s*(?:" + large_pattern_str + r")|\s*$)"
        )
        cat_pattern = re.compile(
            r"(" + large_pattern_str + r"|[가-힣\w\s,·ㆍ]+계의?\s*수술|[가-힣\w\s,·ㆍ]+기[가-힣\w\s,·ㆍ]*의\s*수술|상기\s*이외의\s*수술)"
        )

        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                meta = c["metadata"]
                # Only process Appendix 7 of 자사_SOL건강
                if meta["doc_short"] == "자사_SOL건강" and "별표7" in str(meta["section"]):
                    raw_text = c["text"]

                    # Preprocess to move lonely grades to the end of their respective item chunks
                    # e.g., "\n4\n" inside item 18 should be moved to the end of item 18's section.
                    parts = re.split(r"(?:^|\n)(?=\d+(?:-\d+)?\.)", raw_text)
                    processed_parts = []

                    # The first part is usually header text before the first item number (e.g. "호흡기계·흉부의 수술")
                    if parts:
                        processed_parts.append(parts[0])

                    grade_lonely_pattern = re.compile(r"(?:\n|^)\s*([1-5N])\s*(?:\n|$)")

                    for part in parts[1:]:
                        grade_match = grade_lonely_pattern.search(part)
                        if grade_match:
                            grade_val = grade_match.group(1)
                            # Remove the lonely grade from its original position
                            part_clean = grade_lonely_pattern.sub("\n", part)
                            # Append it to the end of this part (item)
                            part_fixed = f"{part_clean.rstrip()} {grade_val}"
                            processed_parts.append(part_fixed)
                        else:
                            processed_parts.append(part)

                    # Reconstruct text with newlines before replacing them with spaces
                    text = "\n".join(processed_parts)
                    text = text.replace("\n", " ")
                    text = re.sub(r"\s+", " ", text)
                    chunk_id = c["id"]
                    page = meta["page_start"]

                    # Find all category positions in clean text
                    cat_positions: list[tuple[int, str]] = []
                    for m in cat_pattern.finditer(text):
                        cat_positions.append((m.start(), m.group(1).strip()))
                    cat_positions.sort()

                    # Find all rule matches
                    for m in rule_pattern.finditer(text):
                        pos = m.start()
                        num = m.group(1)
                        name = m.group(2).strip()
                        grade = m.group(3)

                        # Determine category for this rule
                        current_large = "일반"
                        for c_pos, cat in cat_positions:
                            if c_pos < pos:
                                current_large = cat
                            else:
                                break

                        # Create PolicyBenefitRule Node
                        norm_rule_name = normalize_name(name)
                        rule_node_id = f"rule_sol_health_별표7_{num}"

                        # Grade payment mapping
                        grade_ratio_map = {
                            "1": ("10%", 0.1),
                            "2": ("30%", 0.3),
                            "3": ("50%", 0.5),
                            "4": ("100%", 1.0),
                            "5": ("100%", 1.0),
                            "N": ("0%", 0.0),
                        }
                        ratio_str, ratio_val = grade_ratio_map.get(grade, ("0%", 0.0))

                        rule_node = Node(
                            node_id=rule_node_id,
                            node_type=NodeType.PolicyBenefitRule,
                            canonical_name=name,
                            normalized_name=norm_rule_name,
                            properties={
                                "product_name": "신한 SOL 처음건강보험(무배당)(자동갱신형)",
                                "appendix_name": "별표7",
                                "benefit_name": name,
                                "payment_ratio": ratio_str,
                                "payment_ratio_numeric": ratio_val,
                                "grade_value": grade,
                                "appendix_number": num,
                                "category_large": current_large,
                            },
                        )
                        self.store.upsert_node(rule_node)

                        # Create Evidence
                        ev_id = f"ev_rule_sol_health_별표7_{num}_{page}"
                        evidence = Evidence(
                            evidence_id=ev_id,
                            chunk_id=chunk_id,
                            doc_short="자사_SOL건강",
                            doc_name="신한 SOL 처음건강보험 약관",
                            pdf_filename="2.약관_신한 SOL 처음건강보험(무배당)(자동갱신형)_20260101.pdf",
                            page_start=page,
                            page_end=page,
                            source_version="v2_manual",
                            source_method="regex_appendix_extractor",
                            row_text=f"[{current_large}] {num}. {name} {grade}",
                        )
                        self.store.upsert_evidence(evidence)
                        self.store.link_node_evidence(rule_node_id, ev_id, role="source")

                        # Link rule to appendix
                        self.store.upsert_edge(
                            Edge(
                                edge_id=f"edge_rule_def_{num}",
                                source_node_id=rule_node_id,
                                target_node_id=appendix_id,
                                edge_type=EdgeType.DEFINED_IN_APPENDIX,
                                source_evidence_id=ev_id,
                            )
                        )

                        # Link rule to grade node if exists
                        if grade != "N":
                            grade_node_id = f"grade_1_5_{grade}"
                            grade_canonical = f"1-5종 {grade}종"
                            self.store.upsert_node(
                                Node(
                                    node_id=grade_node_id,
                                    node_type=NodeType.SurgeryGrade,
                                    canonical_name=grade_canonical,
                                    normalized_name=normalize_name(grade_canonical),
                                    properties={"grade_system": "1-5종", "grade_value": grade},
                                )
                            )
                            self.store.upsert_edge(
                                Edge(
                                    edge_id=f"edge_rule_pays_{num}_{grade}",
                                    source_node_id=rule_node_id,
                                    target_node_id=grade_node_id,
                                    edge_type=EdgeType.PAYS_BY_RATIO,
                                    source_evidence_id=ev_id,
                                )
                            )
        self.store.commit()


class HiraCodeExtractor:
    """Extracts MedicalFeeCode nodes and edges from 심평원 chunks."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, chunks_path: str | Path) -> None:
        self.store.begin()
        chunks_path = Path(chunks_path)
        if not chunks_path.exists():
            return

        # Ensure Document node exists
        doc_id = "doc_심평원"
        self.store.upsert_node(
            Node(
                node_id=doc_id,
                node_type=NodeType.Document,
                canonical_name="건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수",
                normalized_name=normalize_name("건강보험 행위 급여비급여 목록표 및 상대가치점수"),
            )
        )

        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                meta = c["metadata"]
                if meta["doc_short"] == "심평원" and meta.get("codes"):
                    text = c["text"]
                    chunk_id = c["id"]
                    page = meta["page_start"]

                    for code in meta["codes"]:
                        for l in text.split("\n"):
                            if code in l:
                                parts = l.split(code)
                                if len(parts) >= 2:
                                    left = parts[0].strip()
                                    right = parts[1].strip()

                                    # Parse classification number (e.g., 조-961)
                                    class_match = re.search(r"([가-힣\w]+-\d+(?:-\d+)?)", left)
                                    class_no = class_match.group(1) if class_match else ""

                                    # Clean name
                                    name_match = re.match(r"^([가-힣\s\(\),·\-+]+)", right)
                                    name = name_match.group(1).strip() if name_match else right

                                    # Remove English names
                                    eng_start = re.search(r"\b[A-Za-z][A-Za-z\s\-,\(\)/]{3,}\b", name)
                                    if eng_start and eng_start.start() > 0:
                                        name = name[:eng_start.start()].strip()

                                    # Remove trailing numbers
                                    name = re.sub(r"\s*\d+.*$", "", name).strip()

                                    # Upsert MedicalFeeCode Node
                                    code_node_id = f"hira_{normalize_code(code)}"
                                    self.store.upsert_node(
                                        Node(
                                            node_id=code_node_id,
                                            node_type=NodeType.MedicalFeeCode,
                                            canonical_name=name,
                                            normalized_name=normalize_code(code),
                                            properties={
                                                "code": code,
                                                "code_system": "HIRA",
                                                "name": name,
                                                "doc_specific": True,
                                                "classification_no": class_no,
                                            },
                                        )
                                    )

                                    # Create Evidence
                                    ev_id = f"ev_hira_{normalize_code(code)}_{page}"
                                    evidence = Evidence(
                                        evidence_id=ev_id,
                                        chunk_id=chunk_id,
                                        doc_short="심평원",
                                        doc_name="건강보험 행위 급여·비급여 목록표",
                                        pdf_filename="BZ202603053039374.pdf",
                                        page_start=page,
                                        page_end=page,
                                        source_version="v1",
                                        source_method="regex_hira_extractor",
                                        row_text=l.strip(),
                                    )
                                    self.store.upsert_evidence(evidence)
                                    self.store.link_node_evidence(code_node_id, ev_id, role="source")

                                    # Link code to document
                                    self.store.upsert_edge(
                                        Edge(
                                            edge_id=f"edge_hira_app_{normalize_code(code)}",
                                            source_node_id=code_node_id,
                                            target_node_id=doc_id,
                                            edge_type=EdgeType.APPEARS_IN,
                                            source_evidence_id=ev_id,
                                        )
                                    )
        self.store.commit()


class NonpayStandardExtractor:
    """Extracts NonpayStandardCode nodes from standard_codes.sqlite."""

    def __init__(self, store: Any):
        self.store = store

    def extract(self, standard_db_path: str | Path, batch_size: int = 10000) -> None:
        self.store.begin()
        standard_db_path = Path(standard_db_path)
        if not standard_db_path.exists():
            return

        conn = sqlite3.connect(str(standard_db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                std_cd, std_cd_nm, mid_category_cd_nm, hira_care_type_cd_nm,
                ins_care_type_cd_nm, medical_class_cd_nm, item_class_level1cd_nm,
                item_class_level2cd_nm, pay_opn_cd_nm, notes, remarks,
                apply_start_date, apply_end_date
            FROM nonpay_standard;
            """
        )

        nodes_batch = []
        aliases_batch = []
        count = 0

        for row in cursor:
            code = str(row["std_cd"]).strip()
            name = str(row["std_cd_nm"]).strip()

            node_id = f"std_{normalize_code(code)}"
            nodes_batch.append(
                Node(
                    node_id=node_id,
                    node_type=NodeType.NonpayStandardCode,
                    canonical_name=name,
                    normalized_name=normalize_code(code),
                    properties={
                        "std_cd": code,
                        "std_cd_nm": name,
                        "mid_category": str(row["mid_category_cd_nm"] or "").strip(),
                        "hira_care_type": str(row["hira_care_type_cd_nm"] or "").strip(),
                        "ins_care_type": str(row["ins_care_type_cd_nm"] or "").strip(),
                        "medical_class": str(row["medical_class_cd_nm"] or "").strip(),
                        "item_class_level1": str(row["item_class_level1cd_nm"] or "").strip(),
                        "item_class_level2": str(row["item_class_level2cd_nm"] or "").strip(),
                        "pay_opinion": str(row["pay_opn_cd_nm"] or "").strip(),
                        "notes": str(row["notes"] or "").strip(),
                        "remarks": str(row["remarks"] or "").strip(),
                        "apply_start_date": str(row["apply_start_date"] or "").strip(),
                        "apply_end_date": str(row["apply_end_date"] or "").strip(),
                    },
                )
            )

            # Create alias
            alias_id = f"alias_std_{normalize_code(code)}_nm"
            aliases_batch.append(
                Alias(
                    alias_id=alias_id,
                    node_id=node_id,
                    alias=name,
                    normalized_alias=normalize_name(name),
                    source="standard_codes",
                )
            )

            count += 1
            if count % batch_size == 0:
                self.store.upsert_nodes_bulk(nodes_batch)
                self.store.add_aliases_bulk(aliases_batch)
                self.store.commit()
                nodes_batch.clear()
                aliases_batch.clear()
                print(f"[INFO] Ingested {count} non-pay standard codes...")
                self.store.begin()

        # Process remaining
        if nodes_batch:
            self.store.upsert_nodes_bulk(nodes_batch)
            self.store.add_aliases_bulk(aliases_batch)
            self.store.commit()
            print(f"[INFO] Ingested {count} non-pay standard codes (Final batch).")
        else:
            self.store.commit()

        conn.close()
