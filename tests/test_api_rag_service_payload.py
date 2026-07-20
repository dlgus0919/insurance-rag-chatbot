import pytest

from src.api import rag_service
from src.api.rag_service import (
    apply_policy_clause_decision,
    build_formal_retrieval_query,
    chunks_to_sources,
    extract_doc_filter,
    finalize_answer_for_question,
    formal_doc_filter,
    graph_payload_has_renderable_evidence,
    graph_result_to_payload,
    normalize_assistant_answer_for_display,
    strip_embedded_review_template,
)
from src.graph.query_planner import GraphQueryPlan
from src.graph.retriever import GraphPathStep, GraphRetrievalResult, GraphReviewPath
from src.parser.chunker import Chunk
from src.rag.source_grounded_answers import PolicyClauseDecision


def test_graph_result_to_payload_adds_review_display_labels() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(intents=["complication_policy_lookup"]),
        review_paths=[
            GraphReviewPath(
                path_id="complication::test",
                path_type="complication_review",
                status="review_required",
                summary="합병증 관련 조항 검토",
                exclusion_reasons=["미용 목적"],
                required_documents=["진단서"],
                steps=[
                    GraphPathStep(
                        source="session",
                        subject="질문/입력",
                        relation="ASSERTS",
                        object="합병증",
                        status="asserted",
                    )
                ],
            )
        ],
    )

    payload = graph_result_to_payload(result)

    assert payload is not None
    path = payload["graph_review_paths"][0]
    assert path["path_type_label"] == "합병증/후유증 검토"
    assert path["status_label"] == "검토 필요"
    assert path["exclusion_reasons"] == ["미용 목적"]
    assert path["required_documents"] == ["진단서"]
    assert payload["exclusion_reasons"] == ["미용 목적"]
    assert payload["required_documents"] == ["진단서"]



def test_graph_result_to_payload_includes_clarification_and_normalized_terms() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(
            intents=['session_claim_path_review'],
            coverage_topics=['도수치료'],
            conditions=['증빙 부족'],
            normalized_terms={'영수증만': '증빙 부족'},
            term_correction_candidates=[{'raw': '엠알아이', 'normalized': 'MRI', 'confidence': 0.72}],
            ambiguous_terms=['실손 세대'],
            clarification_questions=['어느 실손 세대 기준인지 확인해 주세요.'],
        ),
    )

    payload = graph_result_to_payload(result)

    assert payload is not None
    assert payload['plan']['normalized_terms'] == {'영수증만': '증빙 부족'}
    assert payload['plan']['term_correction_candidates'][0]['raw'] == '엠알아이'
    assert payload['plan']['ambiguous_terms'] == ['실손 세대']
    assert payload['plan']['clarification_questions'] == ['어느 실손 세대 기준인지 확인해 주세요.']


def test_graph_result_to_payload_prunes_followups_after_confirmed_diagnosis_exclusion() -> None:
    result = GraphRetrievalResult(
        plan=GraphQueryPlan(
            intents=["diagnosis_policy_lookup", "session_claim_path_review"],
            diagnosis_codes=["N39.3"],
            coverage_topics=["실손"],
            ambiguous_terms=["실손 세대", "방문 구분", "증빙 서류"],
            clarification_questions=[
                "어느 실손 세대(예: 4세대/5세대) 기준인지 확인해 주세요.",
                "입원/통원/처방조제 중 어떤 방문 구분인지 확인해 주세요.",
                "진료비 영수증, 진료비 세부내역서, 진단서 등 어떤 증빙이 있는지 확인해 주세요.",
            ],
        ),
        review_paths=[
            GraphReviewPath(
                path_id="diagnosis::N39.3",
                path_type="diagnosis_review",
                status="confirmed",
                summary="문서에 직접 언급된 진단코드와 연결된 약관 근거를 찾았습니다.",
                exclusion_reasons=["약관상 보상제외 치료"],
            )
        ],
    )

    payload = graph_result_to_payload(result)

    assert payload is not None
    assert payload["plan"]["ambiguous_terms"] == []
    assert payload["plan"]["clarification_questions"] == []


def test_graph_payload_has_renderable_evidence_checks_panels_and_clarifications() -> None:
    assert graph_payload_has_renderable_evidence(None) is False
    assert graph_payload_has_renderable_evidence({"graph_review_paths": [], "facts": [], "plan": {}}) is False
    assert graph_payload_has_renderable_evidence({"graph_review_paths": [{"path_type": "diagnosis_review"}]}) is True
    assert graph_payload_has_renderable_evidence({"facts": [{"subject": "N39.3"}]}) is True
    assert graph_payload_has_renderable_evidence(
        {"plan": {"clarification_questions": ["어느 실손 세대 기준인지 확인해 주세요."]}}
    ) is True


def test_direct_policy_clause_decision_overrides_missing_generic_claim_condition_review() -> None:
    graph_payload = {
        "graph_review_paths": [
            {
                "path_type": "claim_condition_review",
                "status": "missing",
                "summary": "GraphDB 근거가 없습니다.",
            }
        ],
        "facts": [],
        "plan": {"clarification_questions": ["방문 구분을 확인해 주세요."]},
    }
    decision = PolicyClauseDecision(
        answer="탈모만으로는 보상 여부를 확정할 수 없습니다.",
        payload={
            "status": "clarification_required",
            "status_label": "추가 확인 필요",
            "summary": "노화성 탈모 조항을 일반 탈모 전체에 자동 적용할 수 없습니다.",
            "clarification_questions": ["노화현상인지 질병성 탈모인지 확인해 주세요."],
            "required_evidence": ["진단명 또는 진단코드"],
        },
        chunks=[],
    )

    updated = apply_policy_clause_decision(graph_payload, decision)

    assert updated["canonical_decision"]["status_label"] == "추가 확인 필요"
    assert updated["graph_review_paths"] == []
    assert "노화현상인지 질병성 탈모인지 확인해 주세요." in updated["plan"]["clarification_questions"]


def test_extract_doc_filter_deduplicates_and_normalizes() -> None:
    filters = {"doc_filter": ["약관", "표준약관", "약관", ""]}
    assert extract_doc_filter(filters) == ["약관", "표준약관"]


def test_chunks_to_sources_deduplicates_same_doc_page_snippet() -> None:
    first = Chunk(
        id="driver-1",
        text="특정 외상성 뇌출혈 진단비 특별약관 제3조 진단확정 기준",
        metadata={
            "pdf_filename": "운전자.pdf",
            "doc_short": "자사_SOL운전자",
            "page_start": 71,
            "page_end": 71,
        },
    )
    duplicate = Chunk(
        id="driver-2",
        text="특정 외상성 뇌출혈 진단비 특별약관 제3조 진단확정 기준",
        metadata={
            "pdf_filename": "운전자.pdf",
            "doc_short": "자사_SOL운전자",
            "page_start": 71,
            "page_end": 71,
        },
    )

    sources = chunks_to_sources([first, duplicate])

    assert len(sources) == 1
    assert sources[0]["chunk_id"] == "driver-1"


def test_formal_doc_filter_merges_scope_and_category() -> None:
    filters = {
        "doc_filter": ["상담사례집"],
        "product_category": ["실손", "암보험"],
    }
    assert formal_doc_filter(filters) == ["상담사례집", "약관", "표준약관", "자사_SOL건강"]


def test_formal_doc_filter_without_explicit_scope_keeps_legacy_policy_scope() -> None:
    assert formal_doc_filter({"search_type": "약관 조문 검색"}) == ["약관"]


def test_formal_doc_filter_auto_routed_without_scope_is_unfiltered() -> None:
    assert formal_doc_filter({"search_type": "약관 조문 검색", "_auto_routed": True}) is None


def test_build_formal_retrieval_query_shapes_clause_search() -> None:
    query = build_formal_retrieval_query("N39.3", {"search_type": "약관 조문 검색"})

    assert query.startswith("N39.3")
    assert "약관 조문" in query
    assert "보상하지 않는 사항" in query


def test_build_formal_retrieval_query_shapes_keyword_search() -> None:
    query = build_formal_retrieval_query("백내장", {"search_type": "키워드/시술명 검색"})

    assert query.startswith("백내장")
    assert "시술명" in query
    assert "수술명" in query


def test_strip_embedded_review_template_removes_tail_sections_when_answer_has_leading_prose() -> None:
    raw_answer = (
        "N39.3은 보상 제외로 판단됩니다.\n\n"
        "■ 섹션 1️⃣ 【확정 근거】\n해당 없음\n"
        "■ 섹션 2️⃣ 【검토 필요 사항】\n해당 없음\n"
        "■ 섹션 3️⃣ 【추가 확인 사항】\n해당 없음\n"
        "■ 섹션 4️⃣ 【권장 조치】\n질병/상해 구분 확인\n"
    )

    assert strip_embedded_review_template(raw_answer) == "N39.3은 보상 제외로 판단됩니다."


def test_strip_embedded_review_template_collapses_template_when_body_is_only_review_sections() -> None:
    raw_answer = (
        "■ 섹션 1️⃣ 【확정 근거】\n해당 없음\n"
        "■ 섹션 2️⃣ 【검토 필요 사항】\n해당 없음\n"
    )

    assert strip_embedded_review_template(raw_answer) == "제공된 구조화 검토 경로 기준으로 추가 확인이 필요합니다."


def test_strip_embedded_review_template_extracts_answer_block_when_template_starts_first() -> None:
    raw_answer = (
        "■ 섹션 1️⃣ 【확정 근거】\n제공된 문서에서 보상 제외 근거 확인\n"
        "■ 섹션 2️⃣ 【검토 필요 사항】\n추가 확인 필요\n"
        "[답변]\nN39.3 진단코드는 보상 제외입니다."
    )

    assert strip_embedded_review_template(raw_answer) == "N39.3 진단코드는 보상 제외입니다."


def test_strip_embedded_review_template_builds_summary_from_review_only_body() -> None:
    raw_answer = (
        "■ 섹션 1️⃣  【확정 근거】\n"
        "해당 없음\n\n"
        "■ 섹션 2️⃣  【검토 필요 사항】\n"
        "- 합병증 관련 면책 후보 조항이 존재할 수 있으나, 입력 조건과 직접 일치하는지 추가 확인이 필요합니다.\n"
        "  ⚠️ 이유: Graph review path가 자동 확정이 아닌 검토 대상으로 반환되었습니다.\n"
        "  ➜ 확인 필요: 원문 근거, 입력 조건, 상품/특약 적용 여부를 확인하십시오.\n\n"
        "■ 섹션 3️⃣  【추가 확인 사항】\n"
        "☐ 합병증 특약 내용 확인\n"
        "   현황: required / 중요도: high\n"
        "☐ 해당 특약 가입 여부 확인\n"
        "   현황: required / 중요도: high\n"
    )

    cleaned = strip_embedded_review_template(raw_answer)

    assert "■ 섹션" not in cleaned
    assert "Graph review path" not in cleaned
    assert "합병증 관련 면책 후보 조항이 존재할 수 있으나" in cleaned
    assert "합병증 특약 내용 확인" in cleaned


def test_finalize_answer_for_question_keeps_embedded_review_template_when_graph_payload_is_empty() -> None:
    raw_answer = (
        "N39.3은 보상 제외로 판단됩니다.\n\n"
        "■ 섹션 1️⃣ 【확정 근거】\n해당 없음\n"
        "■ 섹션 2️⃣ 【검토 필요 사항】\n질병/상해 구분 확인\n"
    )
    chunks = [
        Chunk(
            id="chunk-1",
            text="약관 근거",
            metadata={"pdf_filename": "약관.pdf", "doc_short": "약관", "page_start": 12, "page_end": 12},
        )
    ]

    finalized = finalize_answer_for_question(
        "N39.3 진단코드로 보상 가능 여부 알려주세요",
        raw_answer,
        chunks,
        {"graph_review_paths": [], "facts": [], "plan": {}},
    )

    assert "■ 섹션 1️⃣" in finalized
    assert "【확정 근거】" in finalized
    assert "[출처:" not in finalized


def test_finalize_answer_for_question_strips_embedded_review_template_when_graph_payload_is_renderable() -> None:
    raw_answer = (
        "N39.3은 보상 제외로 판단됩니다.\n\n"
        "■ 섹션 1️⃣ 【확정 근거】\n해당 없음\n"
        "■ 섹션 2️⃣ 【검토 필요 사항】\n해당 없음\n"
    )
    chunks = [
        Chunk(
            id="chunk-1",
            text="약관 근거",
            metadata={"pdf_filename": "약관.pdf", "doc_short": "약관", "page_start": 12, "page_end": 12},
        )
    ]

    finalized = finalize_answer_for_question(
        "N39.3 진단코드로 보상 가능 여부 알려주세요",
        raw_answer,
        chunks,
        {"graph_review_paths": [{"path_type": "diagnosis_review", "status": "confirmed"}]},
    )

    assert "■ 섹션 1️⃣" not in finalized
    assert "【확정 근거】" not in finalized
    assert "N39.3은 보상 제외로 판단됩니다." in finalized
    assert "[출처:" not in finalized


def test_finalize_answer_for_question_strips_internal_review_path_markers_when_graph_payload_is_renderable() -> None:
    raw_answer = (
        "선택한 약관 기준으로 연간 보상한도를 확인했습니다.\n"
        "【claim_condition_review】 직접 연결된 판단 조건 경로를 찾지 못했습니다.\n"
        "【generation_rule_review】 세대별 기준을 검토합니다.\n"
        "---"
    )
    chunks = [
        Chunk(
            id="chunk-1",
            text="약관 근거",
            metadata={"pdf_filename": "약관.pdf", "doc_short": "약관", "page_start": 71, "page_end": 71},
        )
    ]

    finalized = finalize_answer_for_question(
        "자기공명영상진단의 연간 보상한도는?",
        raw_answer,
        chunks,
        {"graph_review_paths": [{"path_type": "claim_condition_review", "status": "missing"}]},
    )

    assert "선택한 약관 기준으로 연간 보상한도를 확인했습니다." in finalized
    assert "【claim_condition_review】" not in finalized
    assert "【generation_rule_review】" not in finalized
    assert "---" not in finalized


def test_finalize_answer_for_question_strips_missing_graph_review_summary_from_answer_body() -> None:
    internal_summary = "직접 연결된 판단 조건 경로를 찾지 못했습니다."
    raw_answer = (
        "선택한 약관 기준의 수치를 확인했습니다.\n"
        f"{internal_summary}\n"
        "실제 지급 판단에는 추가 사실관계 확인이 필요합니다."
    )
    chunks = [
        Chunk(
            id="chunk-1",
            text="약관 근거",
            metadata={"pdf_filename": "약관.pdf", "doc_short": "약관", "page_start": 71, "page_end": 71},
        )
    ]

    finalized = finalize_answer_for_question(
        "선택 약관의 보상한도는?",
        raw_answer,
        chunks,
        {
            "graph_review_paths": [
                {"path_type": "claim_condition_review", "status": "missing", "summary": internal_summary},
            ]
        },
    )

    assert "선택한 약관 기준의 수치를 확인했습니다." in finalized
    assert "실제 지급 판단에는 추가 사실관계 확인이 필요합니다." in finalized
    assert internal_summary not in finalized


def test_strip_embedded_review_template_preserves_normal_bracket_tokens_and_surrounding_text() -> None:
    raw_answer = (
        "약어는 【mri】로 표기됩니다.\n"
        "부연은 【note】로 남깁니다.\n"
        "정상 선행 【claim_condition_review】 정상 후행\n"
        "【generation_rule_review】 내부 검토 경로입니다.\n"
        "---"
    )

    cleaned = strip_embedded_review_template(raw_answer)

    assert "약어는 【mri】로 표기됩니다." in cleaned
    assert "부연은 【note】로 남깁니다." in cleaned
    assert "정상 선행 정상 후행" in cleaned
    assert "【claim_condition_review】" not in cleaned
    assert "【generation_rule_review】" not in cleaned
    assert "내부 검토 경로입니다." not in cleaned
    assert "---" not in cleaned


def test_normalize_assistant_answer_for_display_keeps_template_without_renderable_graph_payload() -> None:
    text = (
        "■ 섹션 1️⃣ 【확정 근거】\n"
        "해당 없음\n\n"
        "■ 섹션 2️⃣ 【검토 필요 사항】\n"
        "- 질병/상해 구분 확인\n\n"
        "[출처: 약관, p.12]"
    )

    normalized = normalize_assistant_answer_for_display(text, {"graph_review_paths": [], "facts": [], "plan": {}})

    assert "■ 섹션 1️⃣" in normalized
    assert "질병/상해 구분 확인" in normalized
    assert "[출처:" not in normalized


def test_normalize_assistant_answer_for_display_removes_trailing_source_lines() -> None:
    text = (
        "N39.3 진단코드는 보상 제외입니다.\n\n"
        "[출처: 약관, 제3조(보장종목별 보상내용), p.38]\n"
        "[출처: 표준약관, 제4조(보상하지 않는 사항), p.268-279]"
    )

    normalized = normalize_assistant_answer_for_display(text)

    assert normalized == "N39.3 진단코드는 보상 제외입니다."


def test_normalize_assistant_answer_for_display_removes_source_line_before_followup_note() -> None:
    text = (
        "백내장 다초점 렌즈 수술에 대한 보상 여부는 현재 제공된 문서들에서 확인되지 않습니다.\n\n"
        "[출처: 약관, 제12관 재가입에 관한 사항 등 / 제4조(보상하지 않는 사항), p.78-84]\n\n"
        "(참고: 추가 확인이 필요합니다.)"
    )

    normalized = normalize_assistant_answer_for_display(text)

    assert "[출처:" not in normalized
    assert "(참고: 추가 확인이 필요합니다.)" not in normalized
    assert normalized == "백내장 다초점 렌즈 수술에 대한 보상 여부는 현재 제공된 문서들에서 확인되지 않습니다."


def test_normalize_assistant_answer_for_display_preserves_mid_body_source_lines() -> None:
    text = (
        "요실금 관련 조항은 다음과 같습니다.\n"
        "[출처: 약관, 제3조(보장종목별 보상내용), p.38]\n"
        "위 조항은 본문 설명에 직접 필요한 인용입니다.\n\n"
        "[출처: 표준약관, 제4조(보상하지 않는 사항), p.268-279]"
    )

    normalized = normalize_assistant_answer_for_display(text)

    assert "[출처: 약관, 제3조(보장종목별 보상내용), p.38]" in normalized
    assert "[출처: 표준약관" not in normalized
    assert normalized.endswith("위 조항은 본문 설명에 직접 필요한 인용입니다.")


def test_get_rag_pipeline_reuses_shared_embedder_and_reranker_across_index_modes(monkeypatch) -> None:
    rag_service._load_shared_retrieval_components.cache_clear()
    rag_service._load_index_retrieval_components.cache_clear()
    rag_service.get_rag_pipeline.cache_clear()

    calls = {"embedder": 0, "reranker": 0, "vector_store": 0, "bm25": 0, "llm": 0}

    class FakeEmbedder:
        def __init__(self, *_args, **_kwargs):
            calls["embedder"] += 1

    class FakeVectorStore:
        def __init__(self, *_args, **_kwargs):
            calls["vector_store"] += 1

    class FakeBM25:
        @staticmethod
        def load(_path):
            calls["bm25"] += 1
            return object()

    def fake_build_reranker(enabled=True):
        calls["reranker"] += 1
        return object() if enabled else None

    def fake_build_llm(_model):
        calls["llm"] += 1
        return object()

    class FakePath:
        def exists(self):
            return True

    monkeypatch.setattr(rag_service, "Embedder", FakeEmbedder)
    monkeypatch.setattr(rag_service, "VectorStore", FakeVectorStore)
    monkeypatch.setattr(rag_service, "BM25Index", FakeBM25)
    monkeypatch.setattr(rag_service, "build_reranker", fake_build_reranker)
    monkeypatch.setattr(rag_service, "build_llm", fake_build_llm)
    monkeypatch.setattr(rag_service, "_resolve_index_paths", lambda index_mode: (FakePath(), f"/tmp/{index_mode}"))

    rag_service.get_rag_pipeline("sglang:gpt-oss-20b", 10, "default")
    rag_service.get_rag_pipeline("sglang:gpt-oss-20b", 10, "v2_only")

    assert calls["embedder"] == 1
    assert calls["reranker"] == 1
    assert calls["vector_store"] == 2
    assert calls["bm25"] == 2
    assert calls["llm"] == 2

    rag_service._load_shared_retrieval_components.cache_clear()
    rag_service._load_index_retrieval_components.cache_clear()
    rag_service.get_rag_pipeline.cache_clear()


@pytest.mark.anyio
async def test_prepare_quickcode_context_reflects_ui_options(monkeypatch) -> None:
    chunk = Chunk(
        id="chunk-1",
        text="백내장 수술 심평원/약관 근거",
        metadata={"pdf_filename": "약관.pdf", "doc_short": "약관", "page_start": 14, "page_end": 14},
    )

    captured = {}

    def fake_retrieve_quick_code_chunks(pipeline, procedure_name, include_coverage, selected_docs=None):
        captured["procedure_name"] = procedure_name
        captured["include_coverage"] = include_coverage
        captured["selected_docs"] = selected_docs
        return [chunk], ["심평원", "약관"]

    def fake_build_quick_code_prompt(procedure_name, chunks, include_summary, include_coverage):
        captured["include_summary"] = include_summary
        captured["prompt_include_coverage"] = include_coverage
        return "SYSTEM", f"PROMPT::{procedure_name}::{len(chunks)}"

    monkeypatch.setattr(rag_service, "retrieve_quick_code_chunks", fake_retrieve_quick_code_chunks)
    monkeypatch.setattr(rag_service, "build_quick_code_prompt", fake_build_quick_code_prompt)

    chunks, sources, prompt, system_prompt, applied_doc_filter = await rag_service.prepare_quickcode_context(
        pipeline=object(),
        query="백내장 수술",
        filters={
            "include_summary": False,
            "include_coverage": True,
            "doc_filter": ["약관"],
        },
    )

    assert chunks == [chunk]
    assert sources[0]["doc_short"] == "약관"
    assert system_prompt == "SYSTEM"
    assert prompt.startswith("[적용 문서 필터] 심평원, 약관")
    assert applied_doc_filter == ["심평원", "약관"]
    assert captured == {
        "procedure_name": "백내장 수술",
        "include_coverage": True,
        "selected_docs": ["약관"],
        "include_summary": False,
        "prompt_include_coverage": True,
    }


@pytest.mark.anyio
async def test_prepare_formal_context_uses_shaped_retrieval_query() -> None:
    captured = {}

    class FakePipeline:
        def retrieve_hits(self, question, top_k=None, doc_filter=None):
            captured["question"] = question
            captured["top_k"] = top_k
            captured["doc_filter"] = doc_filter
            return [], None

        def build_prompt(self, question, chunks):
            captured["prompt_question"] = question
            return "PROMPT"

    chunks, sources, prompt, doc_filter = await rag_service.prepare_formal_context(
        pipeline=FakePipeline(),
        question="N39.3",
        top_k=5,
        history=[],
        filters={"search_type": "약관 조문 검색", "product_category": ["실손"]},
        memo="입원 7일",
    )

    assert chunks == []
    assert sources == []
    assert prompt == "PROMPT"
    assert doc_filter == ["약관", "표준약관"]
    assert captured["top_k"] == 5
    assert "약관 조문" in captured["question"]
    assert "보상하지 않는 사항" in captured["question"]
    assert "[검색 유형]\n약관 조문 검색" in captured["prompt_question"]
    assert "[상황 메모]\n입원 7일" in captured["prompt_question"]


@pytest.mark.anyio
async def test_prepare_formal_context_uses_dynamic_document_selection_without_scope() -> None:
    captured = {}

    class FakePipeline:
        def retrieve_hits(self, question, top_k=None, doc_filter=None):
            captured["question"] = question
            captured["doc_filter"] = doc_filter
            return [], None

        def build_prompt(self, question, chunks):
            return "PROMPT"

    chunks, sources, prompt, doc_filter = await rag_service.prepare_formal_context(
        pipeline=FakePipeline(),
        question="자동차사고 부상치료지원금 담보를 청구하려고 합니다. 필요한 서류를 알려주세요.",
        top_k=5,
        history=[],
        filters={"search_type": "약관 조문 검색", "_auto_routed": True},
    )

    assert chunks == []
    assert sources == []
    assert prompt == "PROMPT"
    assert doc_filter is None
    assert captured["doc_filter"] is None
    assert "자동차사고 부상치료지원금" in captured["question"]
