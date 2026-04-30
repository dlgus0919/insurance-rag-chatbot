"""Streamlit 챗 UI."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.ollama_client import OllamaClient
from src.rag.pipeline import RagPipeline
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore


def _source_title(chunk) -> str:
    metadata = chunk.metadata
    start = metadata.get("page_start")
    end = metadata.get("page_end")
    page = f"p.{start}" if start == end or end is None else f"p.{start}-{end}"
    hierarchy = " / ".join(
        str(value)
        for value in [
            metadata.get("volume"),
            metadata.get("part"),
            metadata.get("chapter"),
            metadata.get("section"),
        ]
        if value
    )
    return f"{chunk.id} | {hierarchy} | {page}"


@st.cache_resource
def load_pipeline(model: str, top_k: int) -> RagPipeline:
    """Streamlit 리소스 캐시에 파이프라인을 로드한다."""

    if not config.BM25_PATH.exists():
        raise RuntimeError("BM25 인덱스가 없습니다. `python scripts/ingest.py --stage index`를 먼저 실행하세요.")

    llm = OllamaClient(config.OLLAMA_HOST, model)
    if not llm.health():
        raise RuntimeError("Ollama 서버에 연결할 수 없습니다. Ollama 데스크톱 앱 또는 `ollama serve`를 실행하세요.")

    embedder = Embedder(config.EMBEDDING_MODEL)
    vector_store = VectorStore(config.CHROMA_DIR)
    bm25 = BM25Index.load(config.BM25_PATH)
    return RagPipeline(
        embedder=embedder,
        vector_store=vector_store,
        bm25=bm25,
        llm=llm,
        top_k_dense=config.TOP_K_DENSE,
        top_k_bm25=config.TOP_K_BM25,
        top_k_final=top_k,
        rrf_k=config.RRF_K,
    )


def render_sources(chunks) -> None:
    """답변 출처 청크를 expander 안에 표시한다."""

    with st.expander("출처 보기"):
        for index, chunk in enumerate(chunks, start=1):
            st.markdown(f"**{index}. {_source_title(chunk)}**")
            st.text(chunk.text)


def main() -> None:
    st.set_page_config(page_title="보험 고시 문서 RAG 챗봇 (Alpha)")
    st.title("보험 고시 문서 RAG 챗봇 (Alpha)")

    with st.sidebar:
        model = st.selectbox("모델", [config.OLLAMA_MODEL], index=0)
        top_k = st.slider("Top-K", min_value=4, max_value=12, value=8)
        temperature = st.slider("온도", min_value=0.0, max_value=0.7, value=0.2, step=0.1)
        if st.button("대화 초기화"):
            st.session_state.messages = []
            st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    try:
        pipeline = load_pipeline(model, top_k)
    except RuntimeError as exc:
        st.error(str(exc))
        pipeline = None

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("chunks"):
                render_sources(message["chunks"])

    question = st.chat_input("질문을 입력하세요")
    if question and pipeline is not None:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("답변 생성 중"):
                try:
                    result = pipeline.answer(question, temperature=temperature)
                except RuntimeError as exc:
                    st.error(str(exc))
                    return
            st.markdown(result.answer)
            render_sources(result.chunks)

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result.answer,
                "chunks": result.chunks,
                "timing": result.timing,
            }
        )


if __name__ == "__main__":
    main()
