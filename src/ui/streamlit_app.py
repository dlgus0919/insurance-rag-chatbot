"""Streamlit 챗 UI."""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.auth import users as user_store
from src.auth.users import ROLE_ADMIN
from src.llm.factory import build_llm, format_model_label, get_openai_model_info, is_openai_model, list_available_models
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.rag.insurance_form import (
    COVERAGE_TOPICS,
    InsuranceFormInput,
    generate_insurance_form_answer,
    retrieve_insurance_form_chunks,
)
from src.rag.pipeline import RagPipeline, _hit_to_chunk
from src.rag.quick_code import generate_quick_code_answer, retrieve_quick_code_chunks
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.reranker import build_reranker
from src.retrieval.vector_store import VectorStore
from src.ui.admin_page import render_admin_page
from src.ui.pdf_view import open_pdf_in_native_viewer, render_pdf_page_png
from src.utils.logger import (
    EVENT_ANSWER,
    EVENT_APP_ACCESS,
    EVENT_EXPORT,
    EVENT_LOGIN_FAILURE,
    EVENT_LOGIN_SUCCESS,
    EVENT_LOGOUT,
    EVENT_QUESTION,
    log_event_for_user,
)

_DOC_SHORT_TO_FILENAME: dict[str, str] = {source.doc_short: source.path.name for source in config.PDF_SOURCES}
SEARCH_MODES = ["일반 질의", "퀵 코드 검색", "약관 정형 검색"]
INSURANCE_SUB_MODES = {
    "보상가능 여부 판정": "coverage_judgment",
    "약관 조문 검색": "clause_lookup",
    "키워드/시술명 검색": "keyword_search",
}


def _source_title(chunk) -> str:
    metadata = chunk.metadata
    doc_short = metadata.get("doc_short", "")
    filename = metadata.get("pdf_filename") or _DOC_SHORT_TO_FILENAME.get(doc_short, "")
    start = metadata.get("page_start")
    end = metadata.get("page_end")
    page = f"p.{start}" if start == end or end is None else f"p.{start}~{end}"
    hierarchy = " > ".join(
        str(value)
        for value in [
            metadata.get("volume"),
            metadata.get("part"),
            metadata.get("chapter"),
            metadata.get("section"),
        ]
        if value
    )
    parts = [f"[{doc_short}]" if doc_short else "", filename, page]
    header = " | ".join(part for part in parts if part)
    return f"{header}\n{hierarchy}" if hierarchy else header


def _format_timing(timing: dict) -> str:
    """응답 시간 딕셔너리를 UI 표시 문자열로 변환한다."""

    return (
        f"검색 {timing['retrieve_ms']:.0f}ms · 생성 {timing['llm_ms']:.0f}ms · "
        f"합계 {timing['total_ms'] / 1000:.1f}초"
    )


def _ensure_session_id() -> str:
    """세션 고유 ID를 생성하거나 기존 값을 반환한다."""

    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    return st.session_state.session_id


def _admin_bootstrap_message() -> str:
    """관리자 계정 부트스트랩 안내 문구를 반환한다."""

    return (
        "관리자 계정이 설정되지 않았습니다.\n\n"
        "터미널에서 `python scripts/manage_users.py init`을 실행해 첫 관리자를 생성하세요."
    )


def _bootstrap_users_json_from_env() -> bool:
    """USERS_JSON 환경변수가 있으면 users.json 파일로 풀어 쓴다."""

    raw = os.getenv("USERS_JSON")
    if not raw:
        return False
    path = Path(os.getenv("USERS_JSON_PATH", str(config.ROOT_DIR / "users.json")))
    if path.exists():
        return False
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("USERS_JSON 환경변수가 올바른 JSON이 아닙니다.") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    try:
        path.chmod(0o600)
    except (PermissionError, OSError):
        pass
    return True


def _bootstrap_cloud_assets() -> int:
    """클라우드 배포 모드에서 인덱스 자산 다운로드 부트스트랩을 실행한다."""

    if not config.CLOUD_DEPLOY:
        return 0
    from scripts.bootstrap_assets import main as bootstrap_main

    return bootstrap_main()


def _check_auth(session_id: str) -> bool:
    """ID·비밀번호 인증 상태를 확인하고 로그인 화면을 렌더링한다."""

    if st.session_state.get("authenticated"):
        return True

    if not user_store.has_admin():
        st.title("보험 고시 문서 RAG 챗봇")
        st.error(_admin_bootstrap_message())
        return False

    st.title("보험 고시 문서 RAG 챗봇")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔐 임직원 전용 서비스")
        username = st.text_input("사용자명", placeholder="사용자명")
        password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
        if st.button("로그인", use_container_width=True, type="primary"):
            user = user_store.authenticate(username.strip(), password)
            if user is None:
                st.error("사용자명 또는 비밀번호가 올바르지 않습니다.")
                log_event_for_user(
                    EVENT_LOGIN_FAILURE,
                    session_id,
                    username.strip()[:32] or None,
                    None,
                    {"username_attempt": username.strip()[:32], "reason": "invalid_credentials"},
                )
                return False
            st.session_state.authenticated = True
            st.session_state.user_id = user.username
            st.session_state.user_role = user.role
            st.session_state.user_display = user.display_name
            log_event_for_user(EVENT_LOGIN_SUCCESS, session_id, user.username, user.role)
            st.rerun()
    return False


def _log(event: str, details: dict | None = None) -> None:
    """현재 세션의 사용자 정보를 포함해 감사 로그를 기록한다."""

    log_event_for_user(
        event,
        st.session_state.get("session_id", ""),
        st.session_state.get("user_id"),
        st.session_state.get("user_role"),
        details,
    )


def _turn_count(messages: list[dict]) -> int:
    """대화의 사용자 질문 수를 반환한다."""

    return sum(1 for message in messages if message.get("role") == "user")


def _export_txt(messages: list[dict], model: str) -> str:
    """대화 내용을 사람이 읽을 수 있는 텍스트로 변환한다."""

    used_models = list(
        dict.fromkeys(
            m.get("model", model) for m in messages if m["role"] == "assistant"
        )
    )
    model_str = ", ".join(used_models) if used_models else model
    lines = [
        "=" * 60,
        "보험 고시 문서 RAG 챗봇 - 대화 내보내기",
        f"사용 모델: {model_str}",
        f"내보낸 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
    ]
    turn = 1
    for message in messages:
        if message["role"] == "user":
            lines.extend([f"[Q{turn}] {message['content']}", ""])
            continue
        msg_model = message.get("model", model)
        lines.extend([f"[A{turn}] [{msg_model}] {message['content']}", ""])
        if message.get("timing"):
            lines.append(f"  {_format_timing(message['timing'])}")
        if message.get("chunks"):
            lines.append("  참조 출처:")
            for chunk in message["chunks"][:3]:
                lines.append(f"    - {_source_title(chunk)}")
        lines.append("-" * 40)
        turn += 1
    return "\n".join(lines)


def _export_csv(messages: list[dict], model: str) -> str:
    """대화 내용을 CSV 문자열로 변환한다."""

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["순번", "역할", "내용", "모델", "검색(ms)", "생성(ms)", "합계(초)", "주요출처"])
    turn = 1
    index = 0
    while index < len(messages):
        message = messages[index]
        if message["role"] == "user":
            writer.writerow([turn, "Q", message["content"], "", "", "", "", ""])
            if index + 1 < len(messages) and messages[index + 1]["role"] == "assistant":
                answer_message = messages[index + 1]
                timing = answer_message.get("timing", {})
                chunks = answer_message.get("chunks", [])
                source = _source_title(chunks[0]) if chunks else ""
                writer.writerow(
                    [
                        turn,
                        "A",
                        answer_message["content"],
                        answer_message.get("model", model),
                        f"{timing.get('retrieve_ms', 0):.0f}",
                        f"{timing.get('llm_ms', 0):.0f}",
                        f"{timing.get('total_ms', 0) / 1000:.1f}",
                        source,
                    ]
                )
                turn += 1
                index += 2
                continue
        index += 1
    return output.getvalue()


def _export_json(messages: list[dict], model: str) -> str:
    """대화 내용을 JSON 문자열로 변환한다."""

    export_data = {
        "exported_at": datetime.now().isoformat(),
        "model": model,
        "turn_count": _turn_count(messages),
        "messages": [],
    }
    for message in messages:
        entry: dict = {"role": message["role"], "content": message["content"]}
        if message["role"] == "assistant":
            entry["model"] = message.get("model", model)
            if message.get("timing"):
                entry["timing"] = message["timing"]
            if message.get("chunks"):
                entry["sources"] = [
                    {
                        "id": chunk.id,
                        "doc_short": chunk.metadata.get("doc_short"),
                        "pdf_filename": chunk.metadata.get("pdf_filename"),
                        "page_start": chunk.metadata.get("page_start"),
                        "page_end": chunk.metadata.get("page_end"),
                    }
                    for chunk in message["chunks"]
                ]
        export_data["messages"].append(entry)
    return json.dumps(export_data, ensure_ascii=False, indent=2)


def _log_export(fmt: str, model: str, turn_count: int) -> None:
    """내보내기 이벤트를 감사 로그에 기록한다."""

    _log(EVENT_EXPORT, {"format": fmt, "model": model, "turn_count": turn_count})


def _source_log_payload(chunks: list, limit: int = 3) -> list[dict]:
    """감사 로그에 저장할 출처 요약을 만든다."""

    return [
        {
            "id": chunk.id,
            "doc_short": chunk.metadata.get("doc_short"),
            "page_start": chunk.metadata.get("page_start"),
            "page_end": chunk.metadata.get("page_end"),
        }
        for chunk in chunks[:limit]
    ]


def _timing_log_payload(timing: dict) -> dict:
    """응답 시간 값을 로그용으로 반올림한다."""

    return {
        "retrieve_ms": round(timing["retrieve_ms"], 1),
        "llm_ms": round(timing["llm_ms"], 1),
        "total_ms": round(timing["total_ms"], 1),
    }


def _build_question_log_details(
    mode: str,
    model: str,
    top_k: int,
    temperature: float,
    selected_docs: list[str],
    question: str,
    extra: dict | None = None,
) -> dict:
    """질문 이벤트 로그 상세 정보를 만든다."""

    details = {
        "mode": mode,
        "model": model,
        "top_k": top_k,
        "temperature": temperature,
        "selected_docs": selected_docs,
        "question": question,
    }
    if extra:
        details.update(extra)
    return details


def _build_answer_log_details(
    mode: str,
    model: str,
    selected_docs: list[str],
    answer: str,
    timing: dict,
    chunks: list,
    question: str | None = None,
    provider: str = "ollama",
    token_usage: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """답변 이벤트 로그 상세 정보를 만든다."""

    details = {
        "mode": mode,
        "model": model,
        "provider": provider,
        "selected_docs": selected_docs,
        "answer_preview": answer[:200],
        "timing": _timing_log_payload(timing),
        "chunk_count": len(chunks),
        "sources": _source_log_payload(chunks),
    }
    if question is not None:
        details["question_preview"] = question[:120]
    if is_openai_model(model):
        model_info = get_openai_model_info(model)
        details["model_family"] = model_info["family"]
        details["model_size"] = model_info["size"]
    if token_usage is not None:
        details["token_usage"] = token_usage
    if extra:
        details.update(extra)
    return details


def _llm_answer_log_extra(pipeline: RagPipeline) -> dict:
    """현재 LLM의 provider와 토큰 사용량을 로그 필드로 반환한다."""

    return {
        "provider": getattr(pipeline.llm, "provider", "ollama"),
        "token_usage": getattr(pipeline.llm, "last_usage", None),
    }


def _insurance_form_log_input(form: InsuranceFormInput) -> dict:
    """약관 정형 검색 입력값을 감사 로그용으로 축약한다."""

    payload = {
        "primary": form.primary,
        "coverage_topics": form.coverage_topics or [],
        "article_number": form.article_number,
        "include_appendix": form.include_appendix,
    }
    if form.situation_note:
        payload["situation_note_preview"] = form.situation_note[:200]
    return payload


@st.cache_data(ttl=30)
def _get_available_models_grouped() -> dict[str, list[str]]:
    """Local/Cloud 모델 후보를 그룹별로 반환한다."""

    return list_available_models()


def _select_model_widget() -> str:
    """모델 선택 위젯을 렌더링하고 선택 모델 ID를 반환한다."""

    grouped = _get_available_models_grouped()
    options: list[str] = []
    labels: dict[str, str] = {}
    for model in grouped["local"]:
        options.append(model)
        labels[model] = format_model_label(model, "ollama")
    for model in grouped["cloud"]:
        options.append(model)
        labels[model] = format_model_label(model, "openai")

    if not options:
        st.error("사용 가능한 LLM 모델이 없습니다. .env의 OPENAI_API_KEY 설정 또는 Ollama 설치를 확인하세요.")
        st.stop()

    default_index = 0
    if config.OLLAMA_MODEL in options:
        default_index = options.index(config.OLLAMA_MODEL)
    elif config.OPENAI_DEFAULT_MODEL in options:
        default_index = options.index(config.OPENAI_DEFAULT_MODEL)

    selected = st.selectbox(
        "LLM 모델",
        options,
        index=default_index,
        format_func=lambda model: labels.get(model, model),
    )
    if is_openai_model(selected):
        st.info("⚠ OpenAI 모델은 외부 서버를 호출합니다. 입력된 질문과 검색된 청크가 OpenAI로 전송됩니다.")
    return selected


@st.cache_resource
def _load_heavy_components():
    """임베더·벡터스토어·BM25·Reranker를 한 번만 로드한다."""

    if not config.BM25_PATH.exists():
        raise RuntimeError("BM25 인덱스가 없습니다. `python scripts/ingest.py --stage index`를 먼저 실행하세요.")

    embedder = Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
    vector_store = VectorStore(config.CHROMA_DIR)
    bm25 = BM25Index.load(config.BM25_PATH)
    reranker = build_reranker(enabled=config.RERANKER_ENABLED)
    return embedder, vector_store, bm25, reranker


@st.cache_resource
def _load_llm(model: str):
    """선택된 모델 전용 LLM 클라이언트를 생성한다."""

    return build_llm(model)


def _get_pipeline(model: str, top_k: int) -> RagPipeline:
    """캐시된 컴포넌트로 RagPipeline 객체를 조합한다."""

    embedder, vector_store, bm25, reranker = _load_heavy_components()
    llm = _load_llm(model)
    return RagPipeline(
        embedder=embedder,
        vector_store=vector_store,
        bm25=bm25,
        llm=llm,
        top_k_dense=config.TOP_K_DENSE,
        top_k_bm25=config.TOP_K_BM25,
        top_k_final=top_k,
        rrf_k=config.RRF_K,
        reranker=reranker,
    )


def render_sources(chunks, timing: dict | None = None, key_prefix: str = "sources") -> None:
    """답변 출처 청크를 expander 안에 표시한다."""

    with st.expander("📄 출처 보기"):
        for index, chunk in enumerate(chunks, start=1):
            st.markdown(f"**{index}. {_source_title(chunk)}**")
            preview = chunk.text[:500] + ("..." if len(chunk.text) > 500 else "")
            st.text(preview)

            pdf_filename = chunk.metadata.get("pdf_filename")
            page_start = chunk.metadata.get("page_start")
            if pdf_filename and page_start is not None:
                pdf_path = config.ROOT_DIR / pdf_filename
                safe_key = f"{key_prefix}_{index}_{chunk.id}"
                preview_key = f"_pdf_prev_{safe_key}"

                col_prev, col_open = st.columns(2)
                with col_prev:
                    if st.button("📄 페이지 미리보기", key=f"prev_btn_{safe_key}", use_container_width=True):
                        st.session_state[preview_key] = not st.session_state.get(preview_key, False)
                with col_open:
                    if st.button("📂 PDF 열기", key=f"open_btn_{safe_key}", use_container_width=True):
                        ok, msg = open_pdf_in_native_viewer(pdf_path)
                        (st.success if ok else st.warning)(msg)

                if st.session_state.get(preview_key):
                    try:
                        img = render_pdf_page_png(str(pdf_path), int(page_start))
                        st.image(img, caption=f"{pdf_filename} p.{page_start}", use_container_width=True)
                    except Exception as exc:
                        st.error(f"페이지를 불러올 수 없습니다: {exc}")
            st.divider()


def render_timing(timing: dict | None) -> None:
    """응답 시간을 caption으로 표시한다."""

    if timing:
        st.caption(_format_timing(timing))


def _stream_answer(
    pipeline: RagPipeline,
    question: str,
    temperature: float,
    doc_filter: list[str] | None = None,
) -> tuple[str, list, dict]:
    """검색 후 LLM 스트리밍 답변을 렌더링하고 결과를 반환한다."""

    total_started = time.perf_counter()
    with st.spinner("관련 문서 검색 중..."):
        retrieve_started = time.perf_counter()
        hits = pipeline.retrieve_hits(question, doc_filter=doc_filter)
        chunks = [_hit_to_chunk(hit) for hit in hits]
        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000

    prompt = build_user_prompt(question, chunks)
    llm_started = time.perf_counter()
    placeholder = st.empty()
    tokens: list[str] = []
    for token in pipeline.llm.generate_stream(prompt, system=SYSTEM_PROMPT, temperature=temperature):
        tokens.append(token)
        placeholder.markdown("".join(tokens) + "▌")

    answer = append_retrieved_source_citations("".join(tokens).strip(), chunks)
    placeholder.markdown(answer)
    llm_ms = (time.perf_counter() - llm_started) * 1000
    total_ms = (time.perf_counter() - total_started) * 1000
    return answer, chunks, {"retrieve_ms": retrieve_ms, "llm_ms": llm_ms, "total_ms": total_ms}


def _handle_quick_code(
    procedure_name: str,
    include_summary: bool,
    include_coverage: bool,
    pipeline: RagPipeline,
    model: str,
    temperature: float,
    session_id: str,
    selected_docs: list[str],
) -> None:
    """퀵 코드 검색 폼 제출을 처리한다."""

    question = f"퀵 코드 검색: {procedure_name}"
    options = {"summary": include_summary, "coverage": include_coverage}
    st.session_state.messages.append({"role": "user", "content": question})
    _log(
        EVENT_QUESTION,
        _build_question_log_details(
            mode="quick_code",
            model=model,
            top_k=6,
            temperature=0.0,
            selected_docs=selected_docs,
            question=procedure_name,
            extra={"options": options},
        ),
    )

    with st.chat_message("user"):
        st.markdown(question)

    total_started = time.perf_counter()
    with st.chat_message("assistant"):
        try:
            with st.spinner("코드 후보 검색 중..."):
                retrieve_started = time.perf_counter()
                chunks, applied_doc_filter = retrieve_quick_code_chunks(
                    pipeline,
                    procedure_name,
                    include_coverage,
                    selected_docs,
                )
                retrieve_ms = (time.perf_counter() - retrieve_started) * 1000

            llm_started = time.perf_counter()
            answer = generate_quick_code_answer(
                pipeline,
                procedure_name,
                chunks,
                include_summary,
                include_coverage,
                temperature=0.0,
            )
            answer = append_retrieved_source_citations(answer, chunks)
            llm_ms = (time.perf_counter() - llm_started) * 1000
        except RuntimeError as exc:
            st.error(str(exc))
            return

        total_ms = (time.perf_counter() - total_started) * 1000
        timing = {"retrieve_ms": retrieve_ms, "llm_ms": llm_ms, "total_ms": total_ms}
        st.markdown(answer)
        render_sources(chunks, key_prefix=f"quick_{len(st.session_state.messages)}")
        render_timing(timing)

    _log(
        EVENT_ANSWER,
        _build_answer_log_details(
            mode="quick_code",
            model=model,
            selected_docs=applied_doc_filter,
            answer=answer,
            timing=timing,
            chunks=chunks,
            question=procedure_name,
            **_llm_answer_log_extra(pipeline),
            extra={"options": options},
        ),
    )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "chunks": chunks,
            "timing": timing,
            "model": model,
        }
    )


def _handle_insurance_form(
    form: InsuranceFormInput,
    pipeline: RagPipeline,
    model: str,
    session_id: str,
    selected_docs: list[str],
) -> None:
    """약관 정형 검색 폼 제출을 처리한다."""

    sub_mode_label = {value: key for key, value in INSURANCE_SUB_MODES.items()}[form.mode]
    question = f"약관 정형 검색({sub_mode_label}): {form.primary}"
    applied_doc_filter = list(dict.fromkeys(["약관"] + selected_docs))
    log_extra = {
        "sub_mode": form.mode,
        "form_input": _insurance_form_log_input(form),
    }

    st.session_state.messages.append({"role": "user", "content": question})
    _log(
        EVENT_QUESTION,
        _build_question_log_details(
            mode="insurance_form",
            model=model,
            top_k=8,
            temperature=0.1,
            selected_docs=applied_doc_filter,
            question=form.primary,
            extra=log_extra,
        ),
    )

    with st.chat_message("user"):
        st.markdown(question)

    total_started = time.perf_counter()
    with st.chat_message("assistant"):
        try:
            with st.spinner("약관 조항 검색 중..."):
                retrieve_started = time.perf_counter()
                chunks, applied_doc_filter = retrieve_insurance_form_chunks(
                    pipeline,
                    form,
                    extra_doc_filter=selected_docs,
                )
                retrieve_ms = (time.perf_counter() - retrieve_started) * 1000

            llm_started = time.perf_counter()
            answer = generate_insurance_form_answer(pipeline, form, chunks, temperature=0.1)
            llm_ms = (time.perf_counter() - llm_started) * 1000
        except RuntimeError as exc:
            st.error(str(exc))
            return

        total_ms = (time.perf_counter() - total_started) * 1000
        timing = {"retrieve_ms": retrieve_ms, "llm_ms": llm_ms, "total_ms": total_ms}
        st.markdown(answer)
        render_sources(chunks, key_prefix=f"insurance_{len(st.session_state.messages)}")
        render_timing(timing)

    _log(
        EVENT_ANSWER,
        _build_answer_log_details(
            mode="insurance_form",
            model=model,
            selected_docs=applied_doc_filter,
            answer=answer,
            timing=timing,
            chunks=chunks,
            question=form.primary,
            **_llm_answer_log_extra(pipeline),
            extra=log_extra,
        ),
    )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "chunks": chunks,
            "timing": timing,
            "model": model,
        }
    )


def render_insurance_form_panel() -> tuple[InsuranceFormInput | None, bool]:
    """약관 정형 검색 입력 패널을 렌더링하고 제출 값을 반환한다."""

    sub_mode = st.radio("시나리오", list(INSURANCE_SUB_MODES.keys()), horizontal=True, key="insurance_sub_mode")
    sub_key = INSURANCE_SUB_MODES[sub_mode]

    with st.form("insurance_form", clear_on_submit=False):
        coverage_topics: list[str] | None = None
        situation_note: str | None = None
        article_number: str | None = None
        include_appendix = False

        if sub_key == "coverage_judgment":
            primary = st.text_input("진단코드 또는 시술명", placeholder="예: N39.3")
            coverage_topics = st.multiselect("보장종목", COVERAGE_TOPICS, default=COVERAGE_TOPICS)
            situation_note = st.text_area("상황 메모(옵션)", "")
        elif sub_key == "clause_lookup":
            primary = st.text_input("키워드", placeholder="예: 보상하지 않는 사항")
            col_a, col_b = st.columns(2)
            with col_a:
                article_number = st.text_input("조문번호(옵션, 숫자만)", "")
            with col_b:
                include_appendix = st.checkbox("별표 포함", value=False)
        else:
            primary = st.text_input("키워드", placeholder="예: 도수치료")

        submitted = st.form_submit_button("검색", type="primary", use_container_width=True)

    if not submitted:
        return None, False

    form = InsuranceFormInput(
        mode=sub_key,
        primary=primary.strip(),
        coverage_topics=coverage_topics,
        situation_note=(situation_note or "").strip() or None,
        article_number=(article_number or "").strip() or None,
        include_appendix=include_appendix,
    )
    return form, True


def main() -> None:
    st.set_page_config(page_title="보험 고시 문서 RAG 챗봇")
    try:
        _bootstrap_users_json_from_env()
        if _bootstrap_cloud_assets() != 0:
            st.warning("클라우드 인덱스 자산 다운로드에 실패했습니다. 관리자에게 문의하세요.")
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    session_id = _ensure_session_id()
    if st.session_state.get("_access_logged") is not True:
        _log(EVENT_APP_ACCESS)
        st.session_state._access_logged = True

    if not _check_auth(session_id):
        st.stop()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    st.title("보험 고시 문서 RAG 챗봇")

    with st.sidebar:
        if config.CLOUD_DEPLOY:
            st.info("클라우드 배포 - 외부 LLM(OpenAI) 전용")
        display = st.session_state.get("user_display", "")
        role = st.session_state.get("user_role", "")
        role_label = "관리자" if role == ROLE_ADMIN else "직원"
        st.markdown(f"**{display}** · _{role_label}_")
        if st.button("로그아웃", use_container_width=True):
            _log(EVENT_LOGOUT)
            for key in ("authenticated", "user_id", "user_role", "user_display", "messages"):
                st.session_state.pop(key, None)
            st.rerun()
        page = st.radio("페이지", ["챗봇", "관리자"], horizontal=True, key="page") if role == ROLE_ADMIN else "챗봇"
        st.divider()

        if page == "챗봇":
            model = _select_model_widget()
            top_k = st.slider("Top-K", min_value=4, max_value=12, value=8)
            temperature = st.slider("온도", min_value=0.0, max_value=0.7, value=0.2, step=0.1)

            st.divider()
            st.markdown("**검색 대상 문서**")
            selected_docs = []
            for doc_short in config.DOC_SHORT_ORDER:
                if st.checkbox(doc_short, value=True, key=f"doc_filter_{doc_short}"):
                    selected_docs.append(doc_short)
            if not selected_docs:
                st.warning("최소 1개 문서를 선택해주세요.")

            if st.button("대화 초기화"):
                st.session_state.messages = []
                st.rerun()

            st.divider()
            st.subheader("대화 내보내기")
            has_messages = bool(st.session_state.messages)
            turn_count = _turn_count(st.session_state.messages)
            exported_at = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename_prefix = f"insurance_rag_chat_{exported_at}"
            st.download_button(
                "TXT",
                data=_export_txt(st.session_state.messages, model),
                file_name=f"{filename_prefix}.txt",
                mime="text/plain",
                disabled=not has_messages,
                use_container_width=True,
                on_click=_log_export,
                args=("txt", model, turn_count),
            )
            st.download_button(
                "CSV",
                data=_export_csv(st.session_state.messages, model),
                file_name=f"{filename_prefix}.csv",
                mime="text/csv",
                disabled=not has_messages,
                use_container_width=True,
                on_click=_log_export,
                args=("csv", model, turn_count),
            )
            st.download_button(
                "JSON",
                data=_export_json(st.session_state.messages, model),
                file_name=f"{filename_prefix}.json",
                mime="application/json",
                disabled=not has_messages,
                use_container_width=True,
                on_click=_log_export,
                args=("json", model, turn_count),
            )

    if page == "관리자":
        render_admin_page(_log)
        return

    try:
        pipeline = _get_pipeline(model, top_k)
    except RuntimeError as exc:
        st.error(str(exc))
        pipeline = None

    for message_index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                if message.get("chunks"):
                    render_sources(message["chunks"], key_prefix=f"history_{message_index}")
                render_timing(message.get("timing"))

    search_mode = st.radio("검색 모드", SEARCH_MODES, horizontal=True, key="search_mode")
    if not selected_docs:
        st.info("검색 대상 문서를 1개 이상 선택하면 질문할 수 있습니다.")
        return

    if search_mode == "약관 정형 검색":
        form, submitted = render_insurance_form_panel()
        if submitted:
            if form is None or not form.primary:
                st.warning("검색어를 입력해주세요.")
                return
            if form.mode == "coverage_judgment" and not form.coverage_topics:
                st.warning("보장종목을 1개 이상 선택해주세요.")
                return
            if pipeline is None:
                st.error("검색 파이프라인을 사용할 수 없습니다.")
                return
            _handle_insurance_form(form, pipeline, model, session_id, selected_docs)
        return

    if search_mode == "퀵 코드 검색":
        with st.form("quick_code_form", clear_on_submit=False):
            procedure_name = st.text_input("시술/수술명", placeholder="예: 식도조루술")
            col_a, col_b = st.columns(2)
            with col_a:
                opt_summary = st.checkbox("분류·점수·산정지침 요약", value=True)
            with col_b:
                opt_coverage = st.checkbox("실손 약관 기준 보상가능 여부", value=False)
            submitted = st.form_submit_button("코드 검색", type="primary", use_container_width=True)

        if submitted:
            if not procedure_name.strip():
                st.warning("시술/수술명을 입력해주세요.")
                return
            if pipeline is None:
                st.error("검색 파이프라인을 사용할 수 없습니다.")
                return
            _handle_quick_code(
                procedure_name.strip(),
                opt_summary,
                opt_coverage,
                pipeline,
                model,
                temperature,
                session_id,
                selected_docs,
            )
        return

    question = st.chat_input("질문을 입력하세요")
    if question and pipeline is not None:
        _log(
            EVENT_QUESTION,
            _build_question_log_details(
                mode="general",
                model=model,
                top_k=top_k,
                temperature=temperature,
                selected_docs=selected_docs,
                question=question,
            ),
        )
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            try:
                answer, chunks, timing = _stream_answer(pipeline, question, temperature, doc_filter=selected_docs)
            except RuntimeError as exc:
                st.error(str(exc))
                return
            render_sources(chunks, key_prefix=f"current_{len(st.session_state.messages)}")
            render_timing(timing)

        _log(
            EVENT_ANSWER,
            _build_answer_log_details(
                mode="general",
                model=model,
                selected_docs=selected_docs,
                answer=answer,
                timing=timing,
                chunks=chunks,
                question=question,
                **_llm_answer_log_extra(pipeline),
            ),
        )
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "chunks": chunks,
                "timing": timing,
                "model": model,
            }
        )


if __name__ == "__main__":
    main()
