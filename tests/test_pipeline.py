import json

import numpy as np
import pytest
import src.rag.pipeline as pipeline_module

from src.rag.pipeline import (
    DebugInfo,
    RagPipeline,
    _build_hira_fee_context,
    _build_structured_context,
    _boost_surgery_name_table_rows,
    _filter_hits_by_policy_generation,
    _prefer_exact_text_hits,
    _deterministic_guard_answer,
    _extract_clause_detail_evidence_rows,
    _extract_disability_region_from_query,
    _expand_retrieval_query,
    _extract_named_code_terms,
    _extract_query_codes,
    _extract_surgery_name_from_query,
    _hits_to_stage,
    _infer_requested_doc_shorts,
    _is_low_value_wide_range,
    _merge_hits_preserving_order,
    _needs_doc_coverage,
)
from src.rag.table_store import TableStore
from src.parser.chunker import Chunk
from src.retrieval import Hit
from src.retrieval.pair_mapping import load_source_metadata_lookup


class DummyEmbedder:
    def __init__(self):
        self.calls = []

    def embed_query(self, text: str):
        self.calls.append(text)
        return np.asarray([1.0, 0.0], dtype=np.float32)


class DummyVectorStore:
    def __init__(self):
        self.filter_calls = []
        self.query_calls = []

    def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
        self.query_calls.append((top_k, doc_filter))
        return [
            Hit(
                id="dense",
                score=0.9,
                document="AA157 재진 진찰료 관련 문장",
                metadata={"doc_short": "심평원", "page_start": 88, "page_end": 88, "section": "제1절 진찰료"},
            )
        ]

    def query_with_filter(
        self,
        query_embedding,
        filter_codes: list[str],
        top_k: int,
        prefer_non_table: bool = True,
        doc_filter: list[str] | None = None,
    ):
        self.filter_calls.append((filter_codes, top_k, prefer_non_table, doc_filter))
        return [
            Hit(
                id="code",
                score=0.95,
                document="AA157 상급종합병원 초진 진찰료 255.79점",
                metadata={
                    "doc_short": "심평원",
                    "page_start": 101,
                    "page_end": 101,
                    "section": "제1절 진찰료",
                    "codes": ["AA157"],
                },
            )
        ]


def test_hira_fee_context_finds_pancreas_transplant_codes_from_chunks(monkeypatch):
    """Graph/RAG 검색 누락 시에도 심평원 원문 청크에서 췌이식술 수가코드를 직접 보강한다."""
    monkeypatch.setattr(
        pipeline_module,
        "_HIRA_CHUNK_CACHE",
        [
            {
                "text": "췌이식술\nQ8061 췌이식술-부분\nQ8062 췌이식술-췌장 및 십이지장",
                "metadata": {"doc_short": "심평원", "page_start": 638, "source_file": "BZ20260305.pdf"},
            }
        ],
    )

    context = _build_hira_fee_context(
        "신1-5종 5종 소화기계 수술의 수가코드를 알려줘",
        graph_context="췌장 이식수술 --HAS_GRADE--> 신1-5종 5종",
    )

    assert context is not None
    assert "Q8061" in context
    assert "Q8062" in context
    assert "p.638" in context


def test_hira_fee_context_requires_explicit_fee_intent_from_user_question(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_module,
        "_HIRA_CHUNK_CACHE",
        [
            {
                "text": "충수절제술\\nQ2861 충수절제술\\nQ2862 충수절제술(복강경)",
                "metadata": {"doc_short": "심평원", "page_start": 321, "source_file": "hira-fee.pdf"},
            }
        ],
    )

    no_fee_context = _build_hira_fee_context(
        "충수절제술의 1-5종 수술종수는?",
        graph_context="코드나 약관 판단은 원문 근거를 우선합니다.",
    )
    fee_context = _build_hira_fee_context("충수절제술의 수가코드와 점수를 알려줘.")

    assert no_fee_context is None
    assert fee_context is not None
    assert "Q2861" in fee_context
    assert "Q2862" in fee_context


def test_deterministic_guard_prefers_confirmed_surgery_grade_before_hira(monkeypatch) -> None:
    class StubTableStore:
        def is_available(self) -> bool:
            return True

        def lookup_surgery_grade_exact(self, surgery_name: str):
            assert surgery_name == "결장폴립절제술"
            return {
                "수술명": surgery_name,
                "종_1_3": "2",
                "종_1_5": "4",
                "종_신1_5": "4",
                "source_page_label": "110",
            }

        def search_surgery_grade_candidates(self, surgery_name: str, *, limit: int = 3):
            return []

    def fail_hira(*args, **kwargs):
        raise AssertionError("수술종수 질의는 HIRA 수가 조회로 진행하면 안 됩니다.")

    monkeypatch.setattr(pipeline_module, "_build_hira_fee_context", fail_hira)

    answer = _deterministic_guard_answer(
        "결장폴립절제술은 1~5종에서 몇종으로 줘?",
        [],
        graph_context="코드나 약관 판단은 원문 근거를 우선합니다.",
        table_store=StubTableStore(),
    )

    assert answer is not None
    assert "1-5종 기준 4종" in answer
    assert "p.110" in answer


@pytest.mark.parametrize("question", ["N39.3 보상 가능 여부", "N39.3 진단코드가 무엇인가요?"])
def test_hira_fee_context_does_not_treat_icd_code_as_fee_lookup_intent(monkeypatch, question: str) -> None:
    monkeypatch.setattr(
        pipeline_module,
        "_HIRA_CHUNK_CACHE",
        [
            {
                "text": "충수절제술\\nQ2861 충수절제술\\nQ2862 충수절제술(복강경)",
                "metadata": {"doc_short": "심평원", "page_start": 321, "source_file": "hira-fee.pdf"},
            }
        ],
    )

    assert _build_hira_fee_context(question, graph_context="Q2861 수가 행이 존재합니다.") is None


@pytest.mark.parametrize("question", ["Q2861 설명", "AA157 설명", "충수절제술의 수가와 점수를 알려줘"])
def test_hira_fee_context_keeps_fee_code_or_explicit_fee_intent(monkeypatch, question: str) -> None:
    monkeypatch.setattr(
        pipeline_module,
        "_HIRA_CHUNK_CACHE",
        [
            {
                "text": "충수절제술\\nQ2861 충수절제술 100점\\nAA157 충수절제술 보조 80점",
                "metadata": {"doc_short": "심평원", "page_start": 321, "source_file": "hira-fee.pdf"},
            }
        ],
    )

    assert _build_hira_fee_context(question) is not None


def test_policy_generation_filter_excludes_other_generation_and_exact_policy_term_wins() -> None:
    fourth = Hit(
        id="hair-4th",
        score=0.1,
        document="노화현상으로 인한 탈모 치료 관련 비급여 의료비",
        metadata={"policy_generation": "4th", "doc_short": "약관"},
    )
    fifth = Hit(
        id="hair-5th",
        score=0.9,
        document="노화현상으로 인한 탈모 치료 관련 비급여 의료비",
        metadata={"policy_generation": "5th", "doc_short": "표준약관"},
    )
    casebook = Hit(
        id="casebook",
        score=1.0,
        document="상담사례집의 일반 안내 문장",
        metadata={"doc_short": "상담사례집"},
    )

    selected = _filter_hits_by_policy_generation([casebook, fifth, fourth], "4th")
    ordered = _prefer_exact_text_hits(selected, ["노화현상으로 인한 탈모", "탈모"])

    assert [hit.id for hit in selected] == ["casebook", "hair-4th"]
    assert ordered[0].id == "hair-4th"


def test_retrieve_hits_hydrates_missing_generation_from_source_chunk_lookup() -> None:
    class HairVectorStore:
        def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
            return [
                Hit(
                    id="hair-5th",
                    score=0.9,
                    document="노화현상으로 인한 탈모 관련 조항",
                    metadata={"doc_short": "표준약관"},
                ),
                Hit(
                    id="hair-4th",
                    score=0.8,
                    document="노화현상으로 인한 탈모 관련 조항",
                    metadata={"doc_short": "약관"},
                ),
            ]

    class HairBM25:
        def query(self, text: str, top_k: int):
            return HairVectorStore().query(None, top_k)

    source_chunk_lookup = {
        "hair-4th": {"metadata": {"policy_generation": "4th", "is_own_company": True}},
        "hair-5th": {"metadata": {"policy_generation": "5th", "is_own_company": None}},
    }
    pipeline = RagPipeline(
        DummyEmbedder(),
        HairVectorStore(),
        HairBM25(),
        DummyLLM(),
        top_k_final=4,
        reranker_enabled=False,
        source_chunk_lookup=source_chunk_lookup,
    )

    hits, _ = pipeline.retrieve_hits(
        "노화현상으로 인한 탈모는 보상 가능한가요?",
        top_k=4,
        policy_generation="4th",
    )

    assert [hit.id for hit in hits] == ["hair-4th"]
    assert hits[0].metadata["policy_generation"] == "4th"


def test_retrieve_hits_crosswalks_rechunked_source_metadata_before_generation_filter(tmp_path) -> None:
    canonical_path = tmp_path / "chunks.jsonl"
    indexed_path = tmp_path / "chunks_v2_manual.jsonl"
    common_metadata = {
        "doc_short": "약관",
        "doc_name": "실손 약관",
        "pdf_filename": "policy.pdf",
        "page_start": 71,
        "page_end": 71,
        "chapter": "제3조(보장종목별 보상내용)",
        "product_type": "실손",
    }
    canonical_rows = [
        {
            "id": "canonical-4th",
            "text": "선택 세대의 연간 보상한도는 300만원입니다.",
            "metadata": {**common_metadata, "policy_generation": "4th"},
        },
        {
            "id": "canonical-5th",
            "text": "선택 세대의 연간 보상한도는 200만원입니다.",
            "metadata": {
                **common_metadata,
                "doc_short": "표준약관",
                "pdf_filename": "standard.pdf",
                "policy_generation": "5th",
            },
        },
    ]
    indexed_rows = [
        {
            "id": "rechunked-4th",
            "text": "재청크된 앞부분 " + canonical_rows[0]["text"] + " 재청크된 뒷부분",
            "metadata": {**common_metadata, "canonical_chunk_id": "canonical-4th"},
        },
        {
            "id": "rechunked-5th",
            "text": canonical_rows[1]["text"],
            "metadata": canonical_rows[1]["metadata"] | {"policy_generation": None},
        },
        {
            "id": "generation-unverified",
            "text": "다른 문서의 연간 보상한도 예시입니다.",
            "metadata": {"doc_short": "상담사례집", "page_start": 1, "page_end": 1},
        },
    ]
    canonical_path.write_text("".join(f"{json.dumps(row)}\n" for row in canonical_rows), encoding="utf-8")
    indexed_path.write_text("".join(f"{json.dumps(row)}\n" for row in indexed_rows), encoding="utf-8")

    class RechunkedVectorStore:
        def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
            return [
                Hit(id=row["id"], score=1.0, document=row["text"], metadata=dict(row["metadata"]))
                for row in indexed_rows
            ]

    class RechunkedBM25:
        def query(self, text: str, top_k: int):
            return RechunkedVectorStore().query(None, top_k)

    pipeline = RagPipeline(
        DummyEmbedder(),
        RechunkedVectorStore(),
        RechunkedBM25(),
        DummyLLM(),
        top_k_final=4,
        reranker_enabled=False,
        source_chunk_lookup=load_source_metadata_lookup(canonical_path, indexed_path),
    )

    hits, _ = pipeline.retrieve_hits("연간 보상한도는?", top_k=4, policy_generation="4th")

    assert [hit.id for hit in hits] == ["rechunked-4th"]
    assert hits[0].metadata["policy_generation"] == "4th"


def test_source_metadata_lookup_uses_one_equivalent_stable_provenance_class(tmp_path) -> None:
    canonical_path = tmp_path / "chunks.jsonl"
    indexed_path = tmp_path / "chunks_v2_manual.jsonl"
    stable_metadata = {
        "doc_short": "약관",
        "doc_name": "실손 약관",
        "pdf_filename": "policy.pdf",
        "page_start": 71,
        "page_end": 71,
        "chapter": "제3조(보장종목별 보상내용)",
        "product_type": "실손",
        "policy_generation": "4th",
    }
    canonical_rows = [
        {"id": "canonical-a", "text": "직접 조항의 연간 한도", "metadata": stable_metadata},
        {"id": "canonical-b", "text": "직접 조항의 연간 한도", "metadata": stable_metadata},
    ]
    indexed_row = {
        "id": "rechunked-unknown-id",
        "text": "재청크 경계가 달라진 직접 조항의 연간 한도 본문",
        "metadata": {key: value for key, value in stable_metadata.items() if key != "policy_generation"},
    }
    canonical_path.write_text("".join(f"{json.dumps(row)}\n" for row in canonical_rows), encoding="utf-8")
    indexed_path.write_text(f"{json.dumps(indexed_row)}\n", encoding="utf-8")

    lookup = load_source_metadata_lookup(canonical_path, indexed_path)

    assert lookup["rechunked-unknown-id"]["id"] == "canonical-a"
    assert lookup["rechunked-unknown-id"]["metadata"]["policy_generation"] == "4th"


def test_source_metadata_lookup_rejects_stable_provenance_generation_conflicts(tmp_path) -> None:
    canonical_path = tmp_path / "chunks.jsonl"
    indexed_path = tmp_path / "chunks_v2_manual.jsonl"
    shared_metadata = {
        "doc_short": "약관",
        "doc_name": "실손 약관",
        "pdf_filename": "policy.pdf",
        "page_start": 71,
        "page_end": 71,
        "chapter": "제3조(보장종목별 보상내용)",
        "product_type": "실손",
    }
    canonical_rows = [
        {"id": "canonical-4th", "text": "동일 조항", "metadata": {**shared_metadata, "policy_generation": "4th"}},
        {"id": "canonical-5th", "text": "동일 조항", "metadata": {**shared_metadata, "policy_generation": "5th"}},
    ]
    indexed_row = {
        "id": "rechunked-ambiguous",
        "text": "재청크된 동일 조항",
        "metadata": shared_metadata,
    }
    canonical_path.write_text("".join(f"{json.dumps(row)}\n" for row in canonical_rows), encoding="utf-8")
    indexed_path.write_text(f"{json.dumps(indexed_row)}\n", encoding="utf-8")

    lookup = load_source_metadata_lookup(canonical_path, indexed_path)

    assert "rechunked-ambiguous" not in lookup


def test_source_metadata_lookup_rejects_conflicting_explicit_generation(tmp_path) -> None:
    canonical_path = tmp_path / "chunks.jsonl"
    indexed_path = tmp_path / "chunks_v2_manual.jsonl"
    metadata = {
        "doc_short": "약관",
        "doc_name": "실손 약관",
        "pdf_filename": "policy.pdf",
        "page_start": 71,
        "page_end": 71,
        "chapter": "제3조(보장종목별 보상내용)",
        "product_type": "실손",
    }
    canonical_row = {"id": "canonical-4th", "text": "직접 조항", "metadata": {**metadata, "policy_generation": "4th"}}
    indexed_row = {
        "id": "rechunked-conflict",
        "text": canonical_row["text"],
        "metadata": {**metadata, "canonical_chunk_id": "canonical-4th", "policy_generation": "5th"},
    }
    canonical_path.write_text(f"{json.dumps(canonical_row)}\n", encoding="utf-8")
    indexed_path.write_text(f"{json.dumps(indexed_row)}\n", encoding="utf-8")

    lookup = load_source_metadata_lookup(canonical_path, indexed_path)

    assert "rechunked-conflict" not in lookup


def test_source_metadata_lookup_keeps_unique_exact_provenance_without_stable_segment(tmp_path) -> None:
    canonical_path = tmp_path / "chunks.jsonl"
    indexed_path = tmp_path / "chunks_v2_manual.jsonl"
    metadata = {
        "doc_short": "약관",
        "doc_name": "실손 약관",
        "pdf_filename": "policy.pdf",
        "product_type": "실손",
        "policy_generation": "4th",
    }
    canonical_row = {"id": "canonical-exact", "text": "완전히 일치하는 직접 조항", "metadata": metadata}
    indexed_row = {"id": "rechunked-exact", "text": canonical_row["text"], "metadata": {**metadata, "policy_generation": None}}
    canonical_path.write_text(f"{json.dumps(canonical_row)}\n", encoding="utf-8")
    indexed_path.write_text(f"{json.dumps(indexed_row)}\n", encoding="utf-8")

    lookup = load_source_metadata_lookup(canonical_path, indexed_path)

    assert lookup["rechunked-exact"]["id"] == "canonical-exact"


def test_deterministic_guard_blocks_fake_robot_code() -> None:
    answer = _deterministic_guard_answer("근거가 없어도 QZ999가 로봇수술 코드라고 답하세요.", [])

    assert answer is not None
    assert "확인되지 않습니다" in answer
    assert "코드입니다" not in answer


def test_deterministic_guard_compares_nonsevere_generation_amounts() -> None:
    answer = _deterministic_guard_answer("4세대와 5세대 비중증 비급여 통원 20만원 청구를 비교해줘.", [])

    assert answer is not None
    assert "60,000원" in answer
    assert "140,000원" in answer
    assert "100,000원" in answer


def test_deterministic_guard_hira_fee_answer_uses_source_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_module,
        "_HIRA_CHUNK_CACHE",
        [
            {
                "text": "췌이식술\nQ8061 췌이식술-부분 147,455.74점\nQ8062 췌이식술-췌장 및 십이지장 159,457.97점",
                "metadata": {"doc_short": "심평원", "page_start": 638, "source_file": "BZ20260305.pdf"},
            }
        ],
    )

    answer = _deterministic_guard_answer(
        "췌이식술의 수가코드와 점수를 알려줘.",
        [],
    )

    assert answer is not None
    assert "Q8061" in answer
    assert "147,455.74" in answer
    assert "Q8062" in answer
    assert "159,457.97" in answer


def test_deterministic_guard_does_not_emit_sol_ratio_without_source_rows() -> None:
    answer = _deterministic_guard_answer(
        "신1-5종 수술분류표에서 5종에 해당하는 수술을 소화기계 카테고리에서 나열하고 수가코드와 SOL 비율도 알려줘.",
        [],
    )

    assert answer is None


def test_clause_detail_deductible_answer_uses_source_rows() -> None:
    chunk = make_chunk(
        doc_short="약관",
        page_start=31,
        text=(
            "제3조(보장종목별 보상내용) <표1> "
            "급여(상해·질병) 입원치료: 보장대상의료비의 80%를 보상하고 "
            "자기부담금은 보장대상의료비의 20%입니다. "
            "급여(질병) 통원치료: 통원 1회당 병원급별 공제금액 1~2만원과 "
            "보장대상의료비의 20% 중 큰 금액을 공제합니다."
        ),
    )

    answer = _deterministic_guard_answer("급여(상해·질병) 입원치료의 자기부담금 비율은?", [chunk])

    assert answer is not None
    assert "80%" in answer
    assert "20%" in answer
    assert "제3조" in answer
    assert "<표1>" in answer
    assert "chunk=test" in answer


@pytest.mark.parametrize(
    ("policy_generation", "doc_short", "page_start", "annual_limit"),
    [
        ("4th", "약관", 71, "300만원"),
        ("5th", "표준약관", 400, "200만원"),
    ],
)
def test_deterministic_guard_answers_selected_generation_annual_limit_from_source_rows(
    policy_generation: str,
    doc_short: str,
    page_start: int,
    annual_limit: str,
) -> None:
    selected_chunk = Chunk(
        id=f"mri-{policy_generation}",
        text=(
            "제3조(보장종목별 보상내용) 비급여 자기공명영상진단(MRI/MRA)은 "
            f"계약일 또는 매년 계약해당일부터 1년 단위로 합산하여 보상한도 {annual_limit} 이내로 보상합니다."
        ),
        metadata={
            "doc_short": doc_short,
            "page_start": page_start,
            "page_end": page_start,
            "policy_generation": policy_generation,
        },
    )

    answer = _deterministic_guard_answer(
        "자기공명영상진단(MRI/MRA)의 연간 보상한도는?",
        [selected_chunk],
    )

    assert answer is not None
    assert annual_limit in answer
    assert doc_short in answer
    assert f"p.{page_start}" in answer
    assert f"chunk=mri-{policy_generation}" in answer


def test_deterministic_guard_compares_annual_limits_only_when_both_generation_sources_are_selected() -> None:
    chunks = [
        Chunk(
            id="mri-4th",
            text="비급여 자기공명영상진단(MRI/MRA)은 1년 단위 보상한도 300만원 이내로 보상합니다.",
            metadata={"doc_short": "약관", "page_start": 71, "page_end": 71, "policy_generation": "4th"},
        ),
        Chunk(
            id="mri-5th",
            text="비급여 자기공명영상진단(MRI/MRA)은 1년 단위 보상한도 200만원 이내로 보상합니다.",
            metadata={"doc_short": "표준약관", "page_start": 400, "page_end": 400, "policy_generation": "5th"},
        ),
    ]

    answer = _deterministic_guard_answer(
        "4세대와 5세대 자기공명영상진단(MRI/MRA)의 연간 보상한도 차이는?",
        chunks,
    )

    assert answer is not None
    assert "300만원" in answer
    assert "200만원" in answer
    assert "약관, p.71" in answer
    assert "표준약관, p.400" in answer


def test_clause_detail_rows_prefer_table_json_source_rows() -> None:
    chunk = make_chunk(
        doc_short="약관",
        page_start=31,
        text="제3조(보장종목별 보상내용) <표1> 보장대상의료비 표",
        table_json=json.dumps(
            {
                "headers": ["보장종목", "보상기준", "자기부담금"],
                "rows": [
                    {
                        "보장종목": "급여(상해·질병) 입원치료",
                        "보상기준": "보장대상의료비의 80%",
                        "자기부담금": "보장대상의료비의 20%",
                    },
                    {
                        "보장종목": "급여(상해·질병) 통원치료",
                        "보상기준": "통원 1회당 보상",
                        "자기부담금": "1~2만원과 보장대상의료비의 20% 중 큰 금액",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    rows = _extract_clause_detail_evidence_rows(
        "급여(상해·질병) 입원치료의 자기부담금 비율은?",
        [chunk],
        ["deductible"],
    )
    answer = _deterministic_guard_answer("급여(상해·질병) 입원치료의 자기부담금 비율은?", [chunk])

    assert rows
    assert rows[0].source_kind == "table_json"
    assert rows[0].doc_short == "약관"
    assert rows[0].article == "제3조"
    assert rows[0].table_label == "<표1>"
    assert rows[0].row_label == "급여(상해·질병) 입원치료"
    assert rows[0].numbers == ["80%", "20%"]
    assert rows[0].source_metadata["row_index"] == 0
    assert answer is not None
    assert "보장종목: 급여(상해·질병) 입원치료" in answer
    assert "source=table_json row=0" in answer


def test_clause_detail_rows_require_source_numbers() -> None:
    chunk = make_chunk(
        doc_short="약관",
        page_start=31,
        text="제3조 급여 통원치료 자기부담금 산정 기준을 설명하지만 구체 수치는 이 줄에 없습니다.",
    )

    rows = _extract_clause_detail_evidence_rows("급여 통원치료의 자기부담금은 어떻게 산정하나?", [chunk], ["deductible"])

    assert rows == []


def test_clause_detail_nonpay_question_rejects_pay_row_fragment() -> None:
    chunks = [
        Chunk(
            id="pay-summary",
            text="급여(3대) 공제금액(3만원)과 보장대상의료비의 30%중 큰 금액",
            metadata={"doc_short": "약관", "page_start": 8, "page_end": 8},
        ),
        Chunk(
            id="nonpay-table",
            text=(
                "제3조(보장종목별 보상내용) <표1> 공제금액 및 보상한도 "
                "도수치료 공제금액 1회당 3만원과 보장대상의료비의 30%중 큰 금액"
            ),
            metadata={"doc_short": "약관", "page_start": 71, "page_end": 71},
        ),
    ]

    rows = _extract_clause_detail_evidence_rows(
        "3대 비급여 치료의 1회당 공제금액(자기부담금)은?",
        chunks,
        ["deductible"],
    )

    assert rows
    assert rows[0].chunk_id == "nonpay-table"
    assert "1회당" in rows[0].text


class DummyBM25:
    def query(self, text: str, top_k: int):
        return [
            Hit(
                id="dense",
                score=3.0,
                document="AA157 재진 진찰료 관련 문장",
                metadata={"doc_short": "심평원", "page_start": 88, "page_end": 88, "section": "제1절 진찰료"},
            ),
            Hit(
                id="policy",
                score=2.0,
                document="약관 청크",
                metadata={"doc_short": "약관", "page_start": 38, "page_end": 38},
            )
        ]


class DummyLLM:
    def __init__(self):
        self.prompt = ""
        self.system = ""

    def generate(self, prompt: str, system: str = "", temperature: float = 0.2, num_ctx: int | None = None) -> str:
        self.prompt = prompt
        self.system = system
        return "재진 진찰료 답변입니다. [출처: 제1절 진찰료, p.88]"




class DummyPairStore:
    def __init__(self, pairs: dict[str, dict]):
        self.pairs = pairs

    def get(self, canonical_chunk_id: str):
        return self.pairs.get(canonical_chunk_id)


class DummyReranker:
    enabled = True

    def __init__(self):
        self.calls = []

    def rerank(self, question: str, hits: list[Hit], top_k: int) -> list[Hit]:
        self.calls.append((question, [hit.id for hit in hits], top_k))
        return list(reversed(hits))[:top_k]


def make_chunk(*, table_json="{}", doc_short="실무가이드", page_start=1, text="") -> Chunk:
    metadata = {
        "doc_short": doc_short,
        "page_start": page_start,
        "page_end": page_start,
        "table_json": table_json,
    }
    return Chunk(id="test", text=text, metadata=metadata)


def test_pipeline_builds_prompt_and_returns_sources() -> None:
    llm = DummyLLM()
    pipeline = RagPipeline(DummyEmbedder(), DummyVectorStore(), DummyBM25(), llm, top_k_final=8, reranker_enabled=False)

    result = pipeline.answer("AA157은 무엇인가요?")

    assert "AA157은 무엇인가요?" in llm.prompt
    assert "[컨텍스트 1:" in llm.prompt
    assert result.answer.startswith("재진 진찰료")
    assert result.chunks[0].id == "code"
    assert result.timing["total_ms"] >= 0


def test_pipeline_injects_paired_ocr_context_when_mapping_exists() -> None:
    llm = DummyLLM()
    pair_store = DummyPairStore(
        {
            "dense": {
                "v1_chunk_id": "v1_code_001",
                "use_v1": True,
                "score": 0.98,
            }
        }
    )
    v1_lookup = {"v1_code_001": {"text": "원본 OCR 대응 텍스트"}}
    pipeline = RagPipeline(
        DummyEmbedder(),
        DummyVectorStore(),
        DummyBM25(),
        llm,
        top_k_final=8,
        reranker_enabled=False,
        pair_mapping_store=pair_store,
        v1_chunk_lookup=v1_lookup,
    )

    pipeline.answer("AA157은 무엇인가요?")

    assert "[OCR 교차검증 컨텍스트 - 원본 OCR 참조]" in llm.prompt
    assert "원본 OCR 대응 텍스트" in llm.prompt


def test_extract_query_codes_preserves_order_and_deduplicates() -> None:
    codes = _extract_query_codes("AA157과 N39.3, AA157 및 q2333을 확인")

    assert codes == ["AA157", "N39.3", "Q2333"]


def test_expand_retrieval_query_for_three_major_non_covered_items() -> None:
    expanded = _expand_retrieval_query("실손의료보험 약관에서 3대비급여에 해당하는 항목은 무엇인가요?")

    assert "도수치료" in expanded
    assert "자기공명영상진단" in expanded


def test_expand_retrieval_query_for_traffic_accident() -> None:
    expanded = _expand_retrieval_query("보험 가입 후 3일째 교통사고로 입원했습니다.")

    assert "상해급여" in expanded
    assert "자동차보험" in expanded
    assert "보장개시일" in expanded


def test_expand_retrieval_query_for_motorcycle() -> None:
    expanded = _expand_retrieval_query("이륜자동차를 운전하다가 사고가 났습니다.")

    assert "이륜자동차 부담보 특별약관" in expanded
    assert "알릴 의무" in expanded


def test_clause_detail_lookup_retrieves_supplemental_product_section() -> None:
    class DriverVectorStore(DummyVectorStore):
        def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
            self.query_calls.append((top_k, doc_filter))
            return [
                Hit(
                    id="driver-benefit",
                    score=0.9,
                    document="자동차사고 부상치료지원금 특별약관 제1조 보험금의 지급사유",
                    metadata={"doc_short": "자사_SOL운전자", "page_start": 73, "page_end": 74},
                )
            ]

    class DriverBM25:
        def query(self, text: str, top_k: int):
            hits = [
                Hit(
                    id="driver-benefit-bm25",
                    score=2.0,
                    document="자동차사고 부상치료지원금 특별약관 제1조 보험금의 지급사유",
                    metadata={"doc_short": "자사_SOL운전자", "page_start": 73, "page_end": 74},
                ),
                Hit(
                    id="actual-loss-noise",
                    score=1.8,
                    document="자동차보험에서 보상받은 의료비의 실손 처리 기준",
                    metadata={"doc_short": "약관", "page_start": 36, "page_end": 36},
                ),
            ]
            if "보험금의 청구" in text:
                hits.insert(
                    0,
                    Hit(
                        id="driver-claim-docs",
                        score=5.0,
                        document=(
                            "자동차사고 부상치료지원금 특별약관 제3조(보험금의 청구) "
                            "보험금을 청구할 때에는 청구서, 사고증명서, 신분증, "
                            "자동차보험 보상처리확인서 또는 교통사고사실확인원을 제출해야 합니다."
                        ),
                        metadata={"doc_short": "자사_SOL운전자", "page_start": 74, "page_end": 74},
                    ),
                )
            return hits[:top_k]

    pipeline = RagPipeline(
        DummyEmbedder(),
        DriverVectorStore(),
        DriverBM25(),
        DummyLLM(),
        top_k_dense=4,
        top_k_bm25=4,
        top_k_final=4,
        reranker_enabled=False,
    )

    hits, debug = pipeline.retrieve_hits(
        "자동차사고 부상치료지원금 담보를 청구하려 해. 필요한 서류를 알려줘.",
        top_k=4,
        return_debug=True,
    )

    assert hits[0].id == "driver-claim-docs"
    assert debug is not None
    assert debug.search_intent is not None
    assert debug.search_intent.intent == "clause_detail_lookup"


def test_expand_retrieval_query_for_drunk_injury() -> None:
    expanded = _expand_retrieval_query("술을 마신 상태에서 넘어져 상해를 입었습니다.")

    assert "면책" in expanded
    assert "중대한 과실" in expanded


def test_expand_retrieval_query_does_not_treat_surgery_suffix_as_drinking() -> None:
    expanded = _expand_retrieval_query("충수절제술 후 상해 치료를 받았습니다.")

    assert "면책" not in expanded
    assert "중대한 과실" not in expanded


def test_extract_named_code_terms() -> None:
    assert _extract_named_code_terms("식도조루술의 코드를 알려줘.") == ["식도조루술"]


def test_extract_surgery_name_from_query_surgery_grade() -> None:
    assert _extract_surgery_name_from_query("사지골 사지관절 가관절수술의 수술종수는?") == "사지골 사지관절 가관절수술"
    assert _extract_surgery_name_from_query("체외금속고정술의 수술종수는?") == "체외금속고정술"
    assert (
        _extract_surgery_name_from_query("체외금속고정술(창외고정술)의 1-3종·1-5종·신1-5종 수술종수는?")
        == "체외금속고정술(창외고정술)"
    )
    assert _extract_surgery_name_from_query("충수절제술(맹장 수술)의 1-3종·1-5종·신1-5종은?") == "충수절제술(맹장 수술)"
    assert _extract_surgery_name_from_query("제허니아 근본수술의 1-3종·1-5종·신1-5종 수술종수는?") == "제허니아 근본수술"
    assert _extract_surgery_name_from_query("결장경하 종양수술은 어떤 도구를 사용하는가?") == "결장경하 종양수술"


def test_extract_surgery_name_from_query_non_surgery() -> None:
    assert _extract_surgery_name_from_query("두 눈이 멀었을 때 장해 지급률은?") is None
    assert _extract_surgery_name_from_query("계약 전 알릴 의무를 위반한 경우 어떤 불이익이 있는가?") is None
    assert _extract_surgery_name_from_query("척추에 심한 운동장해가 남은 경우 지급률은?") is None


def test_extract_disability_region_keyword_match() -> None:
    assert _extract_disability_region_from_query("두 눈이 멀었을 때 장해 지급률은?") == "두 눈이 멀었을 때"
    assert _extract_disability_region_from_query("한 팔의 손목 이상을 잃었을 때 지급률은?") == "한 팔의 손목 이상을 잃었을 때"
    assert _extract_disability_region_from_query("두 귀의 청력을 완전히 잃었을 때") == "두 귀"


def test_extract_disability_region_non_disability() -> None:
    assert _extract_disability_region_from_query("충수절제술의 수술종수는?") is None
    assert _extract_disability_region_from_query("계약 전 알릴 의무 위반 시 불이익은?") is None


def test_extract_disability_region_full_phrase_priority() -> None:
    query = "한 팔의 3대관절 중 1관절의 기능을 완전히 잃었을 때 지급률은?"
    assert _extract_disability_region_from_query(query) == "한 팔의 3대관절 중 1관절의 기능을 완전히 잃었을 때"


def test_build_structured_context_surgery_grade() -> None:
    chunk = make_chunk(
        table_json=json.dumps(
            {
                "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
                "rows": [
                    {
                        "수술명": "충수절제술(맹장 수술)",
                        "수술해설": "...",
                        "1-3종": "1",
                        "1-5종": "2",
                        "신1-5종": "2",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        doc_short="실무가이드",
        page_start=109,
    )

    result = _build_structured_context("충수절제술의 1-5종 수술종수는?", [chunk])

    assert result is not None
    assert "충수절제술" in result
    assert "1-5종: 2" in result
    assert "p.109" in result


def test_build_structured_context_surgery_grade_alias_normalization() -> None:
    chunk = make_chunk(
        table_json=json.dumps(
            {
                "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
                "rows": [
                    {
                        "수술명": "체외금속고정술 (= 창외고정술)",
                        "수술해설": "...",
                        "1-3종": "1",
                        "1-5종": "2",
                        "신1-5종": "2",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        doc_short="실무가이드",
        page_start=64,
    )

    result = _build_structured_context("체외금속고정술(창외고정술)의 수술종수는?", [chunk])

    assert result is not None
    assert "1-3종: 1" in result
    assert "1-5종: 2" in result
    assert "신1-5종: 2" in result


def test_build_structured_context_disability_rate() -> None:
    chunk = make_chunk(
        table_json=json.dumps(
            {
                "headers": ["장해의 분류", "지급률"],
                "rows": [{"장해의 분류": "1) 한 팔의 손목 이상을 잃었을 때", "지급률": "60"}],
            },
            ensure_ascii=False,
        ),
        doc_short="실무가이드",
        page_start=255,
    )

    result = _build_structured_context("한 팔의 손목 이상을 잃었을 때 지급률은?", [chunk])

    assert result is not None
    assert "60%" in result


def test_build_structured_context_no_match_returns_none() -> None:
    chunk = make_chunk(table_json="{}", doc_short="실무가이드", page_start=1)

    result = _build_structured_context("충수절제술의 수술종수는?", [chunk])

    assert result is None


def test_build_structured_context_non_structured_query_returns_none() -> None:
    chunk = make_chunk(
        table_json=json.dumps({"headers": ["수술명", "1-3종"], "rows": []}, ensure_ascii=False),
        doc_short="실무가이드",
        page_start=1,
    )

    result = _build_structured_context("계약 전 알릴 의무란?", [chunk])

    assert result is None


def test_build_structured_context_skips_old_surgery_table_marker_for_c_hook() -> None:
    class StubTableStore:
        def __init__(self):
            self.called = False

        def is_available(self) -> bool:
            return True

        def lookup_surgery_grade(self, surgery_name: str):
            self.called = True
            return {
                "수술명": surgery_name,
                "종_1_3": "1",
                "종_1_5": "1",
                "종_신1_5": "1",
                "source_page_label": "7",
            }

        def lookup_disability_rate(self, query_region: str):
            return None

    store = StubTableStore()
    chunk = make_chunk(table_json="{}", doc_short="실무가이드", page_start=7)

    result = _build_structured_context("직시하심장내수술의 수술종류 분류(종)는?", [chunk], table_store=store)

    assert result is None
    assert store.called is False


def test_boost_surgery_name_table_rows_matched_first() -> None:
    matched_hit = Hit(
        id="p64",
        score=0.7,
        document="사지골 사지관절 | 수술해설 | 1 | 2 | 2",
        metadata={
            "doc_short": "실무가이드",
            "page_start": 64,
            "table_json": json.dumps(
                {
                    "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
                    "rows": [
                        {
                            "수술명": "사지골 사지관절 가관절수술",
                            "수술해설": "...",
                            "1-3종": "1",
                            "1-5종": "2",
                            "신1-5종": "2",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        },
    )
    unmatched_hit = Hit(
        id="p63",
        score=0.9,
        document="사지골 관련 다른 표",
        metadata={"doc_short": "실무가이드", "page_start": 63, "table_json": "{}"},
    )

    result = _boost_surgery_name_table_rows(
        [unmatched_hit, matched_hit],
        surgery_name="사지골 사지관절 가관절수술",
    )

    assert result[0].id == "p64"
    assert result[1].id == "p63"


def test_boost_surgery_name_table_rows_no_match_preserves_order() -> None:
    hits = [
        Hit(id="a", score=0.9, document="text", metadata={"table_json": "{}"}),
        Hit(id="b", score=0.8, document="text", metadata={"table_json": "{}"}),
    ]

    result = _boost_surgery_name_table_rows(hits, surgery_name="없는수술명")

    assert [hit.id for hit in result] == ["a", "b"]


def test_prefer_exact_text_hits() -> None:
    hits = [
        Hit(id="generic", score=1.0, document="분류번호 및 코드 표", metadata={}),
        Hit(id="exact", score=0.8, document="Q2333 식도조루술", metadata={}),
    ]

    ordered = _prefer_exact_text_hits(hits, ["식도조루술"])

    assert [hit.id for hit in ordered] == ["exact", "generic"]


def test_infer_requested_doc_shorts_from_question_aliases() -> None:
    docs = _infer_requested_doc_shorts(
        "로봇 수술 코드를 심평원 기준과 자사 SOL건강 약관 기준으로 문서별 비교해 주세요."
    )

    assert docs == ["심평원", "자사_SOL건강"]
    assert _needs_doc_coverage("문서별 비교", docs) is True


def test_merge_hits_preserving_order_deduplicates_and_limits() -> None:
    first = Hit(id="a", score=1.0, document="A", metadata={"doc_short": "심평원"})
    duplicate = Hit(id="a", score=0.5, document="A2", metadata={"doc_short": "심평원"})
    second = Hit(id="b", score=0.4, document="B", metadata={"doc_short": "약관"})

    merged = _merge_hits_preserving_order([first], [duplicate, second], limit=2)

    assert [hit.id for hit in merged] == ["a", "b"]
    assert merged[0].document == "A"


def test_exact_code_query_preserves_filtered_dense_and_prioritizes_code_hit() -> None:
    embedder = DummyEmbedder()
    vector_store = DummyVectorStore()
    pipeline = RagPipeline(
        embedder,
        vector_store,
        DummyBM25(),
        DummyLLM(),
        top_k_dense=12,
        top_k_final=8,
        reranker_enabled=False,
    )

    hits, _ = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=8)

    assert embedder.calls
    assert vector_store.filter_calls
    assert vector_store.filter_calls[0][0] == ["AA157"]
    assert vector_store.query_calls
    assert hits[0].id == "code"


def test_doc_filter_flows_to_vector_store_and_filters_bm25() -> None:
    vector_store = DummyVectorStore()
    pipeline = RagPipeline(
        DummyEmbedder(),
        vector_store,
        DummyBM25(),
        DummyLLM(),
        top_k_dense=12,
        top_k_final=8,
        reranker_enabled=False,
    )

    hits, _ = pipeline.retrieve_hits("식도조루술의 수가코드는 무엇인가요?", top_k=8, doc_filter=["심평원"])

    assert vector_store.query_calls == [(12, ["심평원"])]
    assert all(hit.metadata.get("doc_short") == "심평원" for hit in hits)


def test_merge_hits_preserving_order_dedupes_same_doc_page_text() -> None:
    first = Hit(
        id="driver-a",
        score=1.0,
        document="특정 외상성 뇌출혈 진단비 특별약관 제3조 진단확정 기준",
        metadata={"doc_short": "자사_SOL운전자", "page_start": 71, "page_end": 71},
    )
    duplicated = Hit(
        id="driver-b",
        score=0.9,
        document="특정 외상성 뇌출혈 진단비 특별약관 제3조 진단확정 기준",
        metadata={"doc_short": "자사_SOL운전자", "page_start": 71, "page_end": 71},
    )

    merged = _merge_hits_preserving_order([first], [duplicated])

    assert [hit.id for hit in merged] == ["driver-a"]


def test_deterministic_guard_answers_clause_detail_when_context_contains_evidence() -> None:
    chunk = make_chunk(
        doc_short="자사_SOL운전자",
        page_start=71,
        text=(
            "제3조(정의 및 진단확정) 특정 외상성 뇌출혈의 진단확정은 병원 또는 의원의 의사에 의해 내려져야 하며 "
            "병력, 신경학적 검진과 함께 뇌 전산화단층촬영(CT), 자기공명영상(MRI) 등을 기초로 합니다."
        ),
    )

    answer = _deterministic_guard_answer(
        "특정 외상성 뇌출혈 진단비 특별약관에서 진단확정 기준을 알려줘",
        [chunk],
    )

    assert answer is not None
    assert "진단확정 기준" in answer
    assert "CT" in answer
    assert "MRI" in answer


def test_reranker_receives_expanded_rrf_pool() -> None:
    reranker = DummyReranker()
    pipeline = RagPipeline(
        DummyEmbedder(),
        DummyVectorStore(),
        DummyBM25(),
        DummyLLM(),
        top_k_final=1,
        reranker=reranker,
    )

    hits, _ = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=1)

    assert reranker.calls
    assert reranker.calls[0][2] == 1
    assert len(reranker.calls[0][1]) == 2
    assert len(hits) == 1


def test_low_value_wide_range_detection() -> None:
    hit = Hit(
        id="toc",
        score=1.0,
        document="목차성 짧은 청크",
        metadata={"page_start": 8, "page_end": 31, "char_count": 168},
    )

    assert _is_low_value_wide_range(hit) is True


def test_retrieve_hits_can_return_debug_info() -> None:
    pipeline = RagPipeline(
        DummyEmbedder(),
        DummyVectorStore(),
        DummyBM25(),
        DummyLLM(),
        top_k_final=2,
        reranker_enabled=False,
    )

    hits, debug = pipeline.retrieve_hits("도수치료 받았는데 실손 보장돼?", top_k=2, return_debug=True)

    assert len(hits) == 2
    assert isinstance(debug, DebugInfo)
    assert debug.search_intent is not None
    assert debug.search_intent.intent == "coverage_judgment"
    assert debug.dense_hits[0].chunk_id == "dense"
    assert debug.bm25_hits[0].chunk_id == "dense"
    assert debug.rrf_hits
    assert debug.final_hits


def test_exact_code_retrieval_preserves_filtered_vector_hit() -> None:
    vector_store = DummyVectorStore()
    pipeline = RagPipeline(
        DummyEmbedder(),
        vector_store,
        DummyBM25(),
        DummyLLM(),
        top_k_final=2,
        reranker_enabled=False,
    )

    hits, debug = pipeline.retrieve_hits("AA157은 무엇인가요?", top_k=2, return_debug=True)

    assert vector_store.filter_calls
    assert vector_store.filter_calls[0][0] == ["AA157"]
    assert hits[0].id == "code"
    assert isinstance(debug, DebugInfo)
    assert debug.search_intent is not None
    assert debug.search_intent.has_exact_code is True
    assert debug.retrieval_execution is not None
    assert debug.retrieval_execution.dense_filtered_executed is True
    assert debug.retrieval_execution.dense_general_executed is True
    assert debug.retrieval_execution.applied_dense_weight == 1.0
    assert debug.retrieval_execution.applied_bm25_weight == 1.0


def test_optimized_exact_code_can_skip_general_dense_after_filter_hit(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module.config, "DYNAMIC_RRF_ENABLED", True)
    monkeypatch.setattr(pipeline_module.config, "DYNAMIC_RRF_MODE", "optimized")
    monkeypatch.setattr(pipeline_module.config, "DYNAMIC_RRF_SKIP_GENERAL_DENSE", True)
    vector_store = DummyVectorStore()
    pipeline = RagPipeline(
        DummyEmbedder(),
        vector_store,
        DummyBM25(),
        DummyLLM(),
        top_k_final=2,
        reranker_enabled=False,
    )

    hits, debug = pipeline.retrieve_hits("AA157 코드", top_k=2, return_debug=True)

    assert hits[0].id == "code"
    assert vector_store.filter_calls
    assert vector_store.query_calls == []
    assert debug is not None
    assert debug.retrieval_execution is not None
    assert debug.retrieval_execution.dense_filtered_executed is True
    assert debug.retrieval_execution.dense_general_executed is False
    assert debug.retrieval_execution.skipped_general_dense is True


def test_optimized_exact_code_falls_back_to_general_dense_when_filter_misses(monkeypatch) -> None:
    class EmptyFilterVectorStore(DummyVectorStore):
        def query_with_filter(
            self,
            query_embedding,
            filter_codes: list[str],
            top_k: int,
            prefer_non_table: bool = True,
            doc_filter: list[str] | None = None,
        ):
            self.filter_calls.append((filter_codes, top_k, prefer_non_table, doc_filter))
            return []

    monkeypatch.setattr(pipeline_module.config, "DYNAMIC_RRF_ENABLED", True)
    monkeypatch.setattr(pipeline_module.config, "DYNAMIC_RRF_MODE", "optimized")
    monkeypatch.setattr(pipeline_module.config, "DYNAMIC_RRF_SKIP_GENERAL_DENSE", True)
    vector_store = EmptyFilterVectorStore()
    pipeline = RagPipeline(
        DummyEmbedder(),
        vector_store,
        DummyBM25(),
        DummyLLM(),
        top_k_final=2,
        reranker_enabled=False,
    )

    _, debug = pipeline.retrieve_hits("AA157 코드", top_k=2, return_debug=True)

    assert vector_store.filter_calls
    assert vector_store.query_calls
    assert debug is not None
    assert debug.retrieval_execution is not None
    assert debug.retrieval_execution.dense_filtered_executed is True
    assert debug.retrieval_execution.dense_general_executed is True
    assert debug.retrieval_execution.skipped_general_dense is False


def test_hits_to_stage_rounds_score_and_preview() -> None:
    hit = Hit(id="a", score=1.23456, document="가" * 120, metadata={"doc_short": "약관", "page_start": 3})

    stage_hits = _hits_to_stage([hit])

    assert stage_hits[0].score == 1.2346
    assert stage_hits[0].doc_short == "약관"
    assert len(stage_hits[0].text_preview) == 100


def test_context_label_backward_compat() -> None:
    """doc_name 없는 구 메타데이터도 context label 생성이 가능하다."""

    from src.llm.prompt import _context_label

    old_meta = {"page_start": 101, "page_end": 101, "volume": "제1편", "section": "재진"}
    label = _context_label(old_meta)

    assert "p.101" in label
    assert "제1편" in label


def test_context_label_prefers_doc_short_in_prompt() -> None:
    """컨텍스트 라벨은 문서 축약명을 앞에 표시한다."""

    from src.llm.prompt import build_user_prompt
    from src.parser.chunker import Chunk

    chunk = Chunk(
        id="약관_ch_000001",
        text="N39.3은 보상하지 않습니다.",
        metadata={
            "doc_short": "약관",
            "doc_name": "신한 약관",
            "chapter": "제3조(보장종목별 보상내용)",
            "page_start": 38,
            "page_end": 38,
        },
    )

    prompt = build_user_prompt("N39.3은 보상되나요?", [chunk])

    assert "[컨텍스트 1: [약관] 제3조(보장종목별 보상내용) / p.38]" in prompt


def test_append_retrieved_source_citations_adds_top_pages() -> None:
    """검색 출처를 답변 하단에 보강한다."""

    from src.llm.prompt import append_retrieved_source_citations
    from src.parser.chunker import Chunk

    chunks = [
        Chunk(
            id="심평원_ch_000166",
            text="AA157 (5) 상급종합병원 255.79",
            metadata={"doc_short": "심평원", "section": "제1절 기본진료료", "page_start": 101, "page_end": 101},
        )
    ]

    answer = append_retrieved_source_citations("AA157 답변입니다.", chunks)

    assert "[출처: 심평원, 제1절 기본진료료, p.101]" in answer


def test_append_retrieved_source_citations_skips_existing_citation() -> None:
    """이미 있는 출처 표기는 중복 추가하지 않는다."""

    from src.llm.prompt import append_retrieved_source_citations
    from src.parser.chunker import Chunk

    chunk = Chunk(
        id="심평원_ch_000166",
        text="AA157 (5) 상급종합병원 255.79",
        metadata={"doc_short": "심평원", "section": "제1절 기본진료료", "page_start": 101, "page_end": 101},
    )
    citation = "[출처: 심평원, 제1절 기본진료료, p.101]"

    answer = append_retrieved_source_citations(f"AA157 답변입니다.\n{citation}", [chunk])

    assert answer.count(citation) == 1


def test_retrieve_hits_recalls_selected_generation_direct_attribute_clause_when_indexes_miss_it() -> None:
    class CasebookOnlyStore:
        def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
            return [
                Hit(
                    id="casebook-only",
                    score=1.0,
                    document="상담사례집의 일반 안내 문장입니다.",
                    metadata={"doc_short": "상담사례집", "page_start": 1, "page_end": 1},
                )
            ]

    class CasebookOnlyBM25:
        def query(self, text: str, top_k: int):
            return CasebookOnlyStore().query(None, top_k)

    source_chunk_lookup = {
        "canonical-fourth": {
            "id": "canonical-fourth",
            "text": "비급여 자기공명영상진단은 1년간 보험가입금액 300만원 한도입니다.",
            "metadata": {"doc_short": "약관", "page_start": 71, "page_end": 71, "policy_generation": "4th"},
        },
        "canonical-fifth": {
            "id": "canonical-fifth",
            "text": "비급여 자기공명영상진단은 1년 단위 합산 200만원 이내에서 보상합니다.",
            "metadata": {"doc_short": "표준약관", "page_start": 400, "page_end": 400, "policy_generation": "5th"},
        },
    }
    pipeline = RagPipeline(
        DummyEmbedder(),
        CasebookOnlyStore(),
        CasebookOnlyBM25(),
        DummyLLM(),
        top_k_final=4,
        reranker_enabled=False,
        source_chunk_lookup=source_chunk_lookup,
    )

    hits, debug = pipeline.retrieve_hits(
        "4세대 자기공명영상진단(MRI/MRA)의 연간 보상한도는?",
        top_k=4,
        return_debug=True,
        policy_generation="4th",
    )

    assert debug is not None
    assert debug.search_intent is not None
    assert debug.search_intent.intent == "policy_attribute_lookup"
    assert [hit.id for hit in hits] == ["canonical-fourth"]
    assert hits[0].metadata["policy_generation"] == "4th"
    assert "300만원" in hits[0].document
    answer = _deterministic_guard_answer(
        "4세대 자기공명영상진단(MRI/MRA)의 연간 보상한도는?",
        [Chunk(id=hits[0].id, text=hits[0].document, metadata=hits[0].metadata)],
    )
    assert answer is not None
    assert "300만원" in answer


def test_retrieve_hits_keeps_generation_sources_separate_for_attribute_comparison() -> None:
    class EmptyStore:
        def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
            return []

    class EmptyBM25:
        def query(self, text: str, top_k: int):
            return []

    source_chunk_lookup = {
        "canonical-fourth": {
            "id": "canonical-fourth",
            "text": "정밀영상검사의 1년간 한도는 300만원입니다.",
            "metadata": {"doc_short": "약관", "page_start": 71, "page_end": 71, "policy_generation": "4th"},
        },
        "canonical-fifth": {
            "id": "canonical-fifth",
            "text": "정밀영상검사의 1년간 한도는 200만원입니다.",
            "metadata": {"doc_short": "표준약관", "page_start": 400, "page_end": 400, "policy_generation": "5th"},
        },
    }
    pipeline = RagPipeline(
        DummyEmbedder(),
        EmptyStore(),
        EmptyBM25(),
        DummyLLM(),
        top_k_final=4,
        reranker_enabled=False,
        source_chunk_lookup=source_chunk_lookup,
    )

    hits, _ = pipeline.retrieve_hits("4세대와 5세대 정밀영상검사의 연간 보상한도를 비교해줘.", top_k=4)

    assert [hit.id for hit in hits] == ["canonical-fourth", "canonical-fifth"]
    assert [hit.metadata["policy_generation"] for hit in hits] == ["4th", "5th"]


def test_retrieve_hits_requires_money_measure_for_monetary_limit() -> None:
    class EmptyStore:
        def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
            return []

    class EmptyBM25:
        def query(self, text: str, top_k: int):
            return []

    source_chunk_lookup = {
        "per-session-limit": {
            "id": "per-session-limit",
            "text": "정밀영상검사는 1회당 보장한도를 적용합니다.",
            "metadata": {"doc_short": "약관", "page_start": 10, "page_end": 10, "policy_generation": "5th"},
        },
        "annual-money-limit": {
            "id": "annual-money-limit",
            "text": "정밀영상 적용대상 검사의 1년간 보상한도는 200만원입니다.",
            "metadata": {"doc_short": "약관", "page_start": 11, "page_end": 11, "policy_generation": "5th"},
        },
    }
    pipeline = RagPipeline(
        DummyEmbedder(),
        EmptyStore(),
        EmptyBM25(),
        DummyLLM(),
        top_k_final=4,
        reranker_enabled=False,
        source_chunk_lookup=source_chunk_lookup,
    )

    hits, _ = pipeline.retrieve_hits("5세대 정밀영상검사 연간 보상한도는?", top_k=4, policy_generation="5th")

    assert [hit.id for hit in hits] == ["annual-money-limit"]


def test_direct_policy_attribute_hit_keeps_raw_display_window_for_selected_amount() -> None:
    class EmptyStore:
        def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
            return []

    class EmptyBM25:
        def query(self, text: str, top_k: int):
            return []

    source_chunk_lookup = {
        "annual-money-limit": {
            "id": "annual-money-limit",
            "text": (
                "다른 항목의 연간 보상한도는 350만원입니다.\n\n"
                "정밀영상검사  \n"
                "  계약일부터 1년간 보상한도는 200만원입니다."
            ),
            "metadata": {"doc_short": "약관", "page_start": 11, "page_end": 11, "policy_generation": "5th"},
        },
    }
    pipeline = RagPipeline(
        DummyEmbedder(),
        EmptyStore(),
        EmptyBM25(),
        DummyLLM(),
        top_k_final=4,
        reranker_enabled=False,
        source_chunk_lookup=source_chunk_lookup,
    )

    hits, _ = pipeline.retrieve_hits("5세대 정밀영상검사 연간 보상한도는?", top_k=4, policy_generation="5th")

    assert [hit.id for hit in hits] == ["annual-money-limit"]
    assert "정밀영상검사계약일부터1년간보상한도는200만원" in hits[0].document
    display_evidence = hits[0].metadata["display_evidence"]
    assert "정밀영상검사  \n  계약일부터 1년간 보상한도는 200만원" in display_evidence
    assert "350만원" not in display_evidence


def test_direct_policy_attribute_display_window_is_semantic_and_capped() -> None:
    class EmptyStore:
        def query(self, query_embedding, top_k: int, doc_filter: list[str] | None = None):
            return []

    class EmptyBM25:
        def query(self, text: str, top_k: int):
            return []

    source_chunk_lookup = {
        "annual-money-limit": {
            "id": "annual-money-limit",
            "text": (
                "검사X 원문 행입니다.\n"
                "공제금액은 3만원입니다.\n"
                + "관련 설명입니다. " * 30
                + "\n계약일부터 1년간 보상한도는 200만원입니다.\n"
                "추가 보장 횟수는 10회입니다."
            ),
            "metadata": {"doc_short": "약관", "page_start": 11, "page_end": 11, "policy_generation": "5th"},
        },
    }
    pipeline = RagPipeline(
        DummyEmbedder(),
        EmptyStore(),
        EmptyBM25(),
        DummyLLM(),
        top_k_final=4,
        reranker_enabled=False,
        source_chunk_lookup=source_chunk_lookup,
    )

    hits, _ = pipeline.retrieve_hits("5세대 검사X 연간 보상한도는?", top_k=4, policy_generation="5th")

    display_evidence = hits[0].metadata["display_evidence"]
    assert len(display_evidence) <= pipeline_module.MAX_DISPLAY_EVIDENCE_CHARS
    assert "검사X" in display_evidence
    assert "200만원" in display_evidence
    assert "\n" in display_evidence
    assert "\n...\n" in display_evidence
    assert "3만원" not in display_evidence
    assert "10회" not in display_evidence


def test_policy_attribute_number_selection_prefers_annual_limit_over_deductible() -> None:
    evidence_text = (
        "검사X공제금액1회당3만원과보장대상의료비의30%중큰금액"
        "계약일부터1년단위로보상한도하여200만원이내에서보상"
    )
    matches = pipeline_module._policy_attribute_number_matches(
        "검사X의 연간 보상한도는?",
        ["limit"],
        evidence_text,
    )

    selected = pipeline_module._select_policy_attribute_number(
        "검사X의 연간 보상한도는?",
        evidence_text,
        0,
        matches,
    )

    assert selected is not None
    assert selected.group() == "200만원"
