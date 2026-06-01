from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.claim_calculation.models import ClaimCaseContext, ClaimItemInput
from src.claim_calculation.pipeline import run_claim_calculation
from src.graph.extractors import PolicyReviewExtractor
from src.graph.retriever import GraphRetriever
from src.graph.store import GraphStore


class _DummyPipeline:
    def __init__(self, db_path: Path) -> None:
        self.graph_enabled = True
        self.graph_retriever = GraphRetriever(db_path)

    def retrieve_hits(self, *_args, **_kwargs):
        return [], None


def test_claim_pipeline_marks_complication_review_and_blocks_confirmed_exclusion(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunk = {
        "id": "약관_ch_0001",
        "text": "제2조 미용 목적 수술 후 합병증 치료는 보상하지 않는다. 진단서와 세부내역서를 확인해야 한다.",
        "metadata": {
            "doc_short": "약관",
            "doc_name": "실손 약관",
            "pdf_filename": "medical.pdf",
            "page_start": 38,
            "page_end": 38,
            "section": "제2조(보상하지 않는 손해)",
            "codes": [],
        },
    }
    chunks_path.write_text(json.dumps(chunk, ensure_ascii=False) + "\n", encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    items = [ClaimItemInput(line_id="line1", input_name="합병증 치료비", claimed_amount="100000")]
    context = ClaimCaseContext(
        policy_generation="5th",
        visit_type="outpatient",
        coverage_topic="실손",
        complication_asserted=True,
        situation_note="미용 목적 쌍꺼풀 수술 후 염증",
    )

    mock_match = {
        "std_cd": "SC0001",
        "std_cd_nm": "합병증 치료비",
        "mid_category_cd_nm": "비급여",
        "pay_opn_cd_nm": "보상",
    }

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(_DummyPipeline(db_path), items, context, use_fake_planner=True)

    assert result.requires_review
    assert result.payable_amount == "0"
    assert result.deductible == "100000"
    assert result.calculation_status == "not_covered"
    assert {"진단서", "세부내역서"}.issubset(set(result.missing_evidence))
    assert "진단서 요청" in result.review_actions
    assert "세부내역서 요청" in result.review_actions
    assert "미용 목적" in result.exclusion_reasons
    assert "진단서" in result.required_documents
    assert any("면책" in reason or "합병증" in reason for reason in result.review_reasons)


def test_claim_pipeline_exposes_one_disease_review_path_without_auto_confirming(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunk = {
        "id": "표준약관_ch_one_disease_0001",
        "text": (
            "제3조 하나의 질병이란 발생 원인이 동일한 질병을 말하며, "
            "의학상 중요한 관련이 있는 질병은 하나의 질병으로 간주합니다. "
            "질병의 치료 중에 발생된 합병증 또는 새로 발견된 질병의 치료가 병행된 경우도 검토합니다."
        ),
        "metadata": {
            "doc_short": "표준약관",
            "doc_name": "실손 표준약관",
            "pdf_filename": "standard.pdf",
            "page_start": 350,
            "page_end": 350,
            "section": "제3조(보장종목별 보상내용)",
            "codes": [],
        },
    }
    chunks_path.write_text(json.dumps(chunk, ensure_ascii=False) + "\n", encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    items = [ClaimItemInput(line_id="line1", input_name="합병증 치료비", claimed_amount="100000")]
    context = ClaimCaseContext(
        policy_generation="5th",
        visit_type="outpatient",
        coverage_topic="실손",
        complication_asserted=True,
        same_disease_claimed=True,
        situation_note="당뇨 진단 후 합병증 치료를 하나의 질병으로 볼 수 있는지 검토",
    )

    mock_match = {
        "std_cd": "SC0002",
        "std_cd_nm": "합병증 치료비",
        "mid_category_cd_nm": "비급여",
        "pay_opn_cd_nm": "보상",
    }

    with patch("src.db.standard_codes.search_by_name", return_value=[mock_match]):
        result = run_claim_calculation(_DummyPipeline(db_path), items, context, use_fake_planner=True)

    assert result.requires_review
    assert result.calculation_status == "estimated_review_required"
    assert any(path["path_type"] == "one_disease_review" for path in result.graph_review_paths)
    assert any(assertion["kind"] == "claim_unit" for assertion in result.session_assertions)
    assert "진단서" in result.required_documents
    assert any("하나의 질병" in reason or "검토 경로" in reason for reason in result.review_reasons)
