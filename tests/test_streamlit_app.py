import csv
import io
import json

from src.parser.chunker import Chunk
from src.rag.insurance_form import InsuranceFormInput
from src.ui.streamlit_app import (
    _build_answer_log_details,
    _build_question_log_details,
    _admin_bootstrap_message,
    _export_csv,
    _export_json,
    _export_txt,
    _format_timing,
    _insurance_form_log_input,
    _source_title,
    _turn_count,
)


def test_source_title_includes_pdf_filename_hierarchy_and_page() -> None:
    chunk = Chunk(
        id="ch_000001",
        text="본문",
        metadata={
            "doc_short": "심평원",
            "pdf_filename": "BZ202603053039374.pdf",
            "volume": "제1편",
            "part": "제1부",
            "chapter": "제1장",
            "section": "제1절",
            "page_start": 3,
            "page_end": 4,
        },
    )

    title = _source_title(chunk)

    assert "[심평원] | BZ202603053039374.pdf | p.3~4" in title
    assert "제1편 > 제1부 > 제1장 > 제1절" in title


def test_admin_bootstrap_message_mentions_cli() -> None:
    message = _admin_bootstrap_message()

    assert "관리자 계정이 설정되지 않았습니다" in message
    assert "python scripts/manage_users.py init" in message


def test_source_title_uses_config_filename_fallback() -> None:
    chunk = Chunk(
        id="심평원_ch_000001",
        text="본문",
        metadata={"doc_short": "심평원", "page_start": 101, "page_end": 101},
    )

    title = _source_title(chunk)

    assert "[심평원] | BZ202603053039374.pdf | p.101" in title


def test_format_timing() -> None:
    timing = {"retrieve_ms": 12.3, "llm_ms": 456.7, "total_ms": 1234.5}

    assert _format_timing(timing) == "검색 12ms · 생성 457ms · 합계 1.2초"


def test_export_helpers_include_messages_timing_and_sources() -> None:
    chunk = Chunk(
        id="약관_ch_000001",
        text="본문",
        metadata={
            "doc_short": "약관",
            "pdf_filename": "2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf",
            "chapter": "제4조(보상하지 않는 사항)",
            "page_start": 12,
            "page_end": 12,
        },
    )
    messages = [
        {"role": "user", "content": "N39.3 보상 여부는?"},
        {
            "role": "assistant",
            "content": "요실금은 보상하지 않습니다.",
            "chunks": [chunk],
            "timing": {"retrieve_ms": 100.4, "llm_ms": 1200.6, "total_ms": 1500.0},
        },
    ]

    txt = _export_txt(messages, "gemma3:4b")
    csv_text = _export_csv(messages, "gemma3:4b")
    json_data = json.loads(_export_json(messages, "gemma3:4b"))

    assert _turn_count(messages) == 1
    assert "[Q1] N39.3 보상 여부는?" in txt
    assert "[A1] 요실금은 보상하지 않습니다." in txt
    assert "[약관]" in txt

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0] == ["순번", "역할", "내용", "모델", "검색(ms)", "생성(ms)", "합계(초)", "주요출처"]
    assert rows[1][:3] == ["1", "Q", "N39.3 보상 여부는?"]
    assert rows[2][1:4] == ["A", "요실금은 보상하지 않습니다.", "gemma3:4b"]
    assert "[약관]" in rows[2][7]

    assert json_data["model"] == "gemma3:4b"
    assert json_data["turn_count"] == 1
    assert json_data["messages"][1]["sources"][0]["doc_short"] == "약관"


def test_question_log_details_include_mode_and_selected_docs() -> None:
    details = _build_question_log_details(
        mode="general",
        model="gemma3:4b",
        top_k=8,
        temperature=0.2,
        selected_docs=["심평원"],
        question="AA157은?",
    )

    assert details["mode"] == "general"
    assert details["selected_docs"] == ["심평원"]
    assert details["question"] == "AA157은?"


def test_answer_log_details_include_sources_and_extra_options() -> None:
    chunk = Chunk(
        id="심평원_ch_000001",
        text="본문",
        metadata={"doc_short": "심평원", "page_start": 101, "page_end": 101},
    )

    details = _build_answer_log_details(
        mode="quick_code",
        model="gemma3:4b",
        selected_docs=["심평원", "약관"],
        answer="[코드] Q2333",
        timing={"retrieve_ms": 1.2, "llm_ms": 3.4, "total_ms": 4.6},
        chunks=[chunk],
        question="식도조루술",
        extra={"options": {"summary": True, "coverage": False}},
    )

    assert details["mode"] == "quick_code"
    assert details["question_preview"] == "식도조루술"
    assert details["sources"][0]["doc_short"] == "심평원"
    assert details["options"] == {"summary": True, "coverage": False}
    assert details["provider"] == "ollama"


def test_answer_log_details_include_openai_model_metadata_and_usage() -> None:
    details = _build_answer_log_details(
        mode="general",
        model="gpt-5-mini",
        selected_docs=["약관"],
        answer="답변",
        timing={"retrieve_ms": 1, "llm_ms": 2, "total_ms": 3},
        chunks=[],
        provider="openai",
        token_usage={"prompt_tokens": 10, "completion_tokens": 5},
    )

    assert details["provider"] == "openai"
    assert details["model_family"] == "GPT-5"
    assert details["model_size"] == "mini"
    assert details["token_usage"] == {"prompt_tokens": 10, "completion_tokens": 5}


def test_insurance_form_log_input_truncates_situation_note() -> None:
    form = InsuranceFormInput(
        mode="coverage_judgment",
        primary="N39.3",
        coverage_topics=["질병급여"],
        situation_note="가" * 250,
    )

    payload = _insurance_form_log_input(form)

    assert payload["primary"] == "N39.3"
    assert payload["coverage_topics"] == ["질병급여"]
    assert len(payload["situation_note_preview"]) == 200
