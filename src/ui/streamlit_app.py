"""Streamlit 챗 UI."""

from __future__ import annotations

import csv
import io
import json
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
from src.llm.ollama_client import OllamaClient
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.rag.pipeline import RagPipeline, _hit_to_chunk
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.reranker import build_reranker
from src.retrieval.vector_store import VectorStore
from src.utils.logger import (
    EVENT_ANSWER,
    EVENT_APP_ACCESS,
    EVENT_EXPORT,
    EVENT_LOGIN_FAILURE,
    EVENT_LOGIN_SUCCESS,
    EVENT_QUESTION,
    log_event,
)

_DOC_SHORT_TO_FILENAME: dict[str, str] = {source.doc_short: source.path.name for source in config.PDF_SOURCES}


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


def _check_auth(session_id: str) -> bool:
    """인증 상태를 확인하고 로그인 화면을 렌더링한다."""

    if not config.APP_PASSWORD:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("보험 고시 문서 RAG 챗봇")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔐 임직원 전용 서비스")
        password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
        if st.button("로그인", use_container_width=True, type="primary"):
            if password == config.APP_PASSWORD:
                st.session_state.authenticated = True
                log_event(EVENT_LOGIN_SUCCESS, session_id)
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
                log_event(EVENT_LOGIN_FAILURE, session_id, {"reason": "wrong_password"})
    return False


def _turn_count(messages: list[dict]) -> int:
    """대화의 사용자 질문 수를 반환한다."""

    return sum(1 for message in messages if message.get("role") == "user")


def _export_txt(messages: list[dict], model: str) -> str:
    """대화 내용을 사람이 읽을 수 있는 텍스트로 변환한다."""

    lines = [
        "=" * 60,
        "보험 고시 문서 RAG 챗봇 - 대화 내보내기",
        f"모델: {model}",
        f"내보낸 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
    ]
    turn = 1
    for message in messages:
        if message["role"] == "user":
            lines.extend([f"[Q{turn}] {message['content']}", ""])
            continue
        lines.extend([f"[A{turn}] {message['content']}", ""])
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
                        model,
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


def _log_export(fmt: str, session_id: str, model: str, turn_count: int) -> None:
    """내보내기 이벤트를 감사 로그에 기록한다."""

    log_event(EVENT_EXPORT, session_id, {"format": fmt, "model": model, "turn_count": turn_count})


@st.cache_data(ttl=30)
def _get_available_models() -> list[str]:
    """Ollama에 설치된 권장 모델 목록을 반환한다."""

    installed = set(OllamaClient(config.OLLAMA_HOST, config.OLLAMA_MODEL).list_models())
    candidates = [model for model in config.OLLAMA_CANDIDATE_MODELS if model in installed]
    if config.OLLAMA_MODEL not in candidates:
        candidates.insert(0, config.OLLAMA_MODEL)
    return candidates if candidates else [config.OLLAMA_MODEL]


@st.cache_resource
def _load_heavy_components():
    """임베더·벡터스토어·BM25·Reranker를 한 번만 로드한다."""

    if not config.BM25_PATH.exists():
        raise RuntimeError("BM25 인덱스가 없습니다. `python scripts/ingest.py --stage index`를 먼저 실행하세요.")

    embedder = Embedder(config.EMBEDDING_MODEL)
    vector_store = VectorStore(config.CHROMA_DIR)
    bm25 = BM25Index.load(config.BM25_PATH)
    reranker = build_reranker(enabled=config.RERANKER_ENABLED)
    return embedder, vector_store, bm25, reranker


@st.cache_resource
def _load_llm(model: str) -> OllamaClient:
    """선택된 모델 전용 OllamaClient를 생성한다."""

    llm = OllamaClient(config.OLLAMA_HOST, model)
    installed_models = llm.list_models()
    if not installed_models or model not in installed_models:
        raise RuntimeError(
            f"Ollama 서버에 연결할 수 없거나 모델 '{model}'이 설치되지 않았습니다.\n"
            f"설치 명령: `ollama pull {model}`\n"
            "또는 Ollama 데스크톱 앱을 실행하세요."
        )
    return llm


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


def render_sources(chunks, timing: dict | None = None) -> None:
    """답변 출처 청크를 expander 안에 표시한다."""

    with st.expander("📄 출처 보기"):
        for index, chunk in enumerate(chunks, start=1):
            st.markdown(f"**{index}. {_source_title(chunk)}**")
            preview = chunk.text[:500] + ("..." if len(chunk.text) > 500 else "")
            st.text(preview)
            st.divider()


def render_timing(timing: dict | None) -> None:
    """응답 시간을 caption으로 표시한다."""

    if timing:
        st.caption(_format_timing(timing))


def _stream_answer(pipeline: RagPipeline, question: str, temperature: float) -> tuple[str, list, dict]:
    """검색 후 LLM 스트리밍 답변을 렌더링하고 결과를 반환한다."""

    total_started = time.perf_counter()
    with st.spinner("관련 문서 검색 중..."):
        retrieve_started = time.perf_counter()
        hits = pipeline.retrieve_hits(question)
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


def main() -> None:
    st.set_page_config(page_title="보험 고시 문서 RAG 챗봇")

    session_id = _ensure_session_id()
    if st.session_state.get("_access_logged") is not True:
        log_event(EVENT_APP_ACCESS, session_id)
        st.session_state._access_logged = True

    if not _check_auth(session_id):
        st.stop()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    st.title("보험 고시 문서 RAG 챗봇")

    with st.sidebar:
        available_models = _get_available_models()
        default_index = available_models.index(config.OLLAMA_MODEL) if config.OLLAMA_MODEL in available_models else 0
        model = st.selectbox(
            "LLM 모델",
            available_models,
            index=default_index,
            help="exaone3.5:7.8b-instruct 권장 (한국어 처리 최적화)",
        )
        top_k = st.slider("Top-K", min_value=4, max_value=12, value=8)
        temperature = st.slider("온도", min_value=0.0, max_value=0.7, value=0.2, step=0.1)
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
            args=("txt", session_id, model, turn_count),
        )
        st.download_button(
            "CSV",
            data=_export_csv(st.session_state.messages, model),
            file_name=f"{filename_prefix}.csv",
            mime="text/csv",
            disabled=not has_messages,
            use_container_width=True,
            on_click=_log_export,
            args=("csv", session_id, model, turn_count),
        )
        st.download_button(
            "JSON",
            data=_export_json(st.session_state.messages, model),
            file_name=f"{filename_prefix}.json",
            mime="application/json",
            disabled=not has_messages,
            use_container_width=True,
            on_click=_log_export,
            args=("json", session_id, model, turn_count),
        )

    try:
        pipeline = _get_pipeline(model, top_k)
    except RuntimeError as exc:
        st.error(str(exc))
        pipeline = None

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                if message.get("chunks"):
                    render_sources(message["chunks"])
                render_timing(message.get("timing"))

    question = st.chat_input("질문을 입력하세요")
    if question and pipeline is not None:
        log_event(
            EVENT_QUESTION,
            session_id,
            {
                "model": model,
                "top_k": top_k,
                "temperature": temperature,
                "question": question,
            },
        )
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            try:
                answer, chunks, timing = _stream_answer(pipeline, question, temperature)
            except RuntimeError as exc:
                st.error(str(exc))
                return
            render_sources(chunks)
            render_timing(timing)

        log_event(
            EVENT_ANSWER,
            session_id,
            {
                "model": model,
                "question_preview": question[:120],
                "answer_preview": answer[:200],
                "timing": {
                    "retrieve_ms": round(timing["retrieve_ms"], 1),
                    "llm_ms": round(timing["llm_ms"], 1),
                    "total_ms": round(timing["total_ms"], 1),
                },
                "chunk_count": len(chunks),
                "sources": [
                    {
                        "id": chunk.id,
                        "doc_short": chunk.metadata.get("doc_short"),
                        "page_start": chunk.metadata.get("page_start"),
                        "page_end": chunk.metadata.get("page_end"),
                    }
                    for chunk in chunks[:3]
                ],
            },
        )
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "chunks": chunks,
                "timing": timing,
            }
        )


if __name__ == "__main__":
    main()
