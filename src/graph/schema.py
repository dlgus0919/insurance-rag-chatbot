from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    Document = "Document"
    DocumentSection = "DocumentSection"
    Table = "Table"
    TableRow = "TableRow"
    SurgeryProcedure = "SurgeryProcedure"
    SurgeryGrade = "SurgeryGrade"
    SurgeryCategory = "SurgeryCategory"
    MedicalFeeCode = "MedicalFeeCode"
    PolicyProduct = "PolicyProduct"
    PolicyAppendix = "PolicyAppendix"
    PolicyBenefitRule = "PolicyBenefitRule"
    CoverageItem = "CoverageItem"
    NonpayStandardCode = "NonpayStandardCode"


class EdgeType(str, Enum):
    APPEARS_IN = "APPEARS_IN"
    HAS_SOURCE_ROW = "HAS_SOURCE_ROW"
    HAS_GRADE = "HAS_GRADE"
    HAS_CATEGORY = "HAS_CATEGORY"
    HAS_MEDICAL_FEE_CODE = "HAS_MEDICAL_FEE_CODE"
    DEFINED_IN_APPENDIX = "DEFINED_IN_APPENDIX"
    POLICY_COVERS_PROCEDURE = "POLICY_COVERS_PROCEDURE"
    PAYS_BY_RATIO = "PAYS_BY_RATIO"
    SAME_GRADE_AS = "SAME_GRADE_AS"
    SAME_CATEGORY_AS = "SAME_CATEGORY_AS"
    CROSS_REFERENCES = "CROSS_REFERENCES"
    HAS_CANONICAL_SOURCE = "HAS_CANONICAL_SOURCE"


@dataclass
class Node:
    node_id: str
    node_type: NodeType
    canonical_name: str
    normalized_name: str
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    created_by: str = "extractor"
    updated_at: str = ""

    def to_db_row(self) -> tuple:
        return (
            self.node_id,
            self.node_type.value,
            self.canonical_name,
            self.normalized_name,
            json.dumps(self.properties, ensure_ascii=False),
            self.confidence,
            self.created_by,
            self.updated_at,
        )


@dataclass
class Alias:
    alias_id: str
    node_id: str
    alias: str
    normalized_alias: str
    source: str
    confidence: float = 1.0

    def to_db_row(self) -> tuple:
        return (
            self.alias_id,
            self.node_id,
            self.alias,
            self.normalized_alias,
            self.source,
            self.confidence,
        )


@dataclass
class Edge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: EdgeType
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source_evidence_id: str | None = None
    created_by: str = "extractor"
    updated_at: str = ""

    def to_db_row(self) -> tuple:
        return (
            self.edge_id,
            self.source_node_id,
            self.target_node_id,
            self.edge_type.value,
            json.dumps(self.properties, ensure_ascii=False),
            self.confidence,
            self.source_evidence_id,
            self.created_by,
            self.updated_at,
        )


@dataclass
class Evidence:
    evidence_id: str
    chunk_id: str | None = None
    doc_short: str = ""
    doc_name: str | None = None
    pdf_filename: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    source_version: str | None = None
    source_method: str | None = None
    table_id: str | None = None
    row_index: int | None = None
    row_text: str | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_db_row(self) -> tuple:
        return (
            self.evidence_id,
            self.chunk_id,
            self.doc_short,
            self.doc_name,
            self.pdf_filename,
            self.page_start,
            self.page_end,
            self.source_version,
            self.source_method,
            self.table_id,
            self.row_index,
            self.row_text,
            json.dumps(self.metadata_json, ensure_ascii=False),
            self.confidence,
        )
