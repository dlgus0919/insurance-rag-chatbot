from __future__ import annotations

import json
from pathlib import Path

from src.graph.extractors import PolicyReviewExtractor
from src.graph.retriever import GraphRetriever
from src.graph.store import GraphStore


def test_graph_retriever_builds_complication_review_path(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": "제2조 미용 목적 수술 후 합병증 치료는 보상하지 않는다. 진단서와 세부내역서를 확인해야 한다.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 80,
                "page_end": 80,
                "section": "제2조(보상하지 않는 손해)",
                "codes": [],
            },
        }
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    result = retriever.retrieve("미용 목적 쌍꺼풀 수술 후 염증이 생겼습니다. 합병증 치료비를 실손으로 받을 수 있나요?")

    assert result.review_paths
    path = result.review_paths[0]
    assert path.path_type == "complication_review"
    assert path.status in {"confirmed", "review_required"}
    assert any(step.object == "합병증" for step in path.steps if step.source == "session")
    assert "미용 목적" in path.exclusion_reasons
    assert "진단서" in path.required_documents or "진단서" in path.required_evidence
    assert not any("당뇨" in (step.object or "") and "망막병증" in (step.object or "") for step in path.steps)


def test_graph_retriever_does_not_confirm_wrong_topic_exclusion(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": "제1조 실손 합병증 치료는 보상하지 않는다.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 10,
                "page_end": 10,
                "section": "제1조(보상하지 않는 손해)",
                "codes": [],
            },
        },
        {
            "id": "약관_ch_0002",
            "text": "제2조 합병증 특약은 진단서와 세부내역서를 제출한 경우 추가 심사 필요.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "특약 약관",
                "pdf_filename": "special.pdf",
                "page_start": 11,
                "page_end": 11,
                "section": "제2조(합병증 특약)",
                "codes": [],
            },
        },
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    result = retriever.retrieve("당뇨 진단 후 합병증 특약 보상이 되나요?")

    path = next(path for path in result.review_paths if path.path_type == "complication_review")
    assert path.status == "review_required"
    assert any(step.object == "면책" and step.status == "candidate" for step in path.steps)
    assert not any(step.object == "면책" and step.status == "confirmed" for step in path.steps)


def test_graph_retriever_builds_coordination_and_generation_rule_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": "제3조 자동차보험으로 이미 보상받은 치료비는 지급내역을 확인하고 중복 보상 조정이 필요하다.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 88,
                "page_end": 88,
                "section": "제3조(중복 보상 조정)",
                "codes": [],
            },
        },
        {
            "id": "약관_ch_0002",
            "text": "제4조 5세대 실손 통원 도수치료는 연간 50회 한도와 공제금액을 적용한다.",
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 89,
                "page_end": 89,
                "section": "제4조(5세대 한도와 공제)",
                "codes": [],
            },
        },
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    coord = retriever.retrieve("자동차보험으로 이미 보상받은 치료비를 실손에서도 청구할 수 있나요?")
    assert any(path.path_type == "coordination_review" for path in coord.review_paths)
    assert any("자동차보험 처리 후 실손 청구" in path.coordination_rules for path in coord.review_paths)

    generation = retriever.retrieve("5세대 실손 통원 도수치료 한도와 공제는 어떻게 보나요?")
    assert any(path.path_type == "generation_rule_review" for path in generation.review_paths)
    assert any("5세대 실손 적용 규칙" in path.generation_rules for path in generation.review_paths)
    assert any("도수치료 횟수 한도" in path.benefit_limits for path in generation.review_paths)


def test_graph_retriever_keeps_diagnosis_review_rules_scoped_to_current_context(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": (
                "제5조 N39.3 요실금은 보상하지 않는다. "
                "자동차보험으로 이미 보상받은 치료비는 실손에서 조정한다. "
                "5세대 실손 통원은 공제와 한도를 적용한다."
            ),
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 90,
                "page_end": 90,
                "section": "제5조(보상하지 않는 사항)",
                "codes": ["N39.3"],
            },
        },
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    result = retriever.retrieve("N39.3 진단코드로 보상 가능 여부 알려주세요")

    diagnosis_path = next(path for path in result.review_paths if path.path_type == "diagnosis_review")
    assert diagnosis_path.exclusion_reasons
    assert diagnosis_path.exclusion_reasons == ["약관상 보상제외 치료"]
    assert diagnosis_path.coordination_rules == []
    assert diagnosis_path.generation_rules == []
    assert diagnosis_path.deductible_rules == []
    assert diagnosis_path.benefit_limits == []

    result_with_broad_topic = retriever.retrieve("N39.3 진단코드로 실손 보상 가능 여부 알려주세요")
    broad_topic_path = next(path for path in result_with_broad_topic.review_paths if path.path_type == "diagnosis_review")
    assert broad_topic_path.exclusion_reasons == ["약관상 보상제외 치료"]
    assert broad_topic_path.coordination_rules == []
    assert broad_topic_path.generation_rules == []
    assert broad_topic_path.deductible_rules == []
    assert broad_topic_path.benefit_limits == []


def test_graph_retriever_keeps_diagnosis_coordination_exclusion_only_when_query_has_context(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": (
                "제5조 N39.3 요실금은 보상하지 않는다. "
                "자동차보험으로 이미 보상받은 치료비는 실손에서 조정한다."
            ),
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 90,
                "page_end": 90,
                "section": "제5조(보상하지 않는 사항)",
                "codes": ["N39.3"],
            },
        },
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    result = retriever.retrieve("자동차보험으로 처리된 N39.3 진단코드 치료비도 보상 가능 여부 알려주세요")

    diagnosis_path = next(path for path in result.review_paths if path.path_type == "diagnosis_review")
    assert "약관상 보상제외 치료" in diagnosis_path.exclusion_reasons
    assert "자동차보험 처리 대상" in diagnosis_path.exclusion_reasons


def test_graph_retriever_keeps_general_diagnosis_exclusions_without_coordination_context(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": (
                "제5조 N39.3 요실금은 보상하지 않는다. "
                "고의 또는 중대한 과실로 생긴 손해와 전쟁, 폭동, 소요, 사변으로 생긴 손해는 보상하지 않는다. "
                "자동차보험으로 이미 보상받은 치료비는 실손에서 조정한다."
            ),
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 91,
                "page_end": 91,
                "section": "제5조(보상하지 않는 사항)",
                "codes": ["N39.3"],
            },
        },
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    result = retriever.retrieve("N39.3 진단코드로 보상 가능 여부 알려주세요")

    diagnosis_path = next(path for path in result.review_paths if path.path_type == "diagnosis_review")
    assert "약관상 보상제외 치료" in diagnosis_path.exclusion_reasons
    assert "고의 또는 중대한 과실" in diagnosis_path.exclusion_reasons
    assert "전쟁/폭동 등 일반 면책" in diagnosis_path.exclusion_reasons
    assert "자동차보험 처리 대상" not in diagnosis_path.exclusion_reasons


def test_graph_retriever_reintroduces_coordination_exclusion_when_query_has_context(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = GraphStore(db_path)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [
        {
            "id": "약관_ch_0001",
            "text": (
                "제5조 N39.3 요실금은 보상하지 않는다. "
                "고의 또는 중대한 과실로 생긴 손해는 보상하지 않는다. "
                "자동차보험으로 이미 보상받은 치료비는 실손에서 조정한다."
            ),
            "metadata": {
                "doc_short": "약관",
                "doc_name": "실손 약관",
                "pdf_filename": "medical.pdf",
                "page_start": 92,
                "page_end": 92,
                "section": "제5조(보상하지 않는 사항)",
                "codes": ["N39.3"],
            },
        },
    ]
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
    PolicyReviewExtractor(store).extract(chunks_path)
    store.close()

    retriever = GraphRetriever(db_path)
    result = retriever.retrieve("자동차보험으로 처리된 N39.3 진단코드 치료비도 보상 가능 여부 알려주세요")

    diagnosis_path = next(path for path in result.review_paths if path.path_type == "diagnosis_review")
    assert "약관상 보상제외 치료" in diagnosis_path.exclusion_reasons
    assert "고의 또는 중대한 과실" in diagnosis_path.exclusion_reasons
    assert "자동차보험 처리 대상" in diagnosis_path.exclusion_reasons
