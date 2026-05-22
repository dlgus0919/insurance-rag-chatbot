"""Streamlit 챗 UI."""

from __future__ import annotations

import csv
import io
import json
import logging as _logging
import os
import subprocess
import re as _re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

_logging.getLogger("transformers.utils.versions").setLevel(_logging.ERROR)
_logging.getLogger("sentence_transformers").setLevel(_logging.WARNING)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.auth import users as user_store
from src.auth.users import ROLE_ADMIN
from src.llm.factory import build_llm, format_model_label, get_openai_model_info, is_openai_model, list_available_models, list_startup_large_models, provider_prefixed_model, split_model_selection
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations
from src.rag.evidence import append_evidence_validation_warning
from src.rag.insurance_form import (
    COVERAGE_TOPICS,
    INSURANCE_FORM_TOP_K,
    InsuranceFormInput,
    build_form_query,
    generate_insurance_form_answer,
    retrieve_insurance_form_chunks,
)
from src.rag.pipeline import DebugInfo, RagPipeline, _hit_to_chunk
from src.rag.quick_code import QUICK_CODE_TOP_K, generate_quick_code_answer, retrieve_quick_code_chunks
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.index_mode import resolve_index_paths
from src.retrieval.pair_mapping import PairMappingStore, load_chunk_lookup
from src.retrieval.reranker import build_reranker
from src.retrieval.vector_store import VectorStore
from src.ui.admin_page import render_admin_page
from src.ui.brand import inject_css, render_logo
from src.ui.chat_store import delete_chat, list_user_chats, load_chat, new_chat_id, save_chat
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
SEARCH_MODES = ["일반 질의", "퀵 코드 검색", "약관 정형 검색", "보험금 계산"]
INSURANCE_SUB_MODES = {
    "보상가능 여부 판정": "coverage_judgment",
    "약관 조문 검색": "clause_lookup",
    "키워드/시술명 검색": "keyword_search",
}
OCR_INDEX_MODES = {
    "기본 운영 인덱스": "default",
    "보정본 OCR만": "v2_only",
    "원본+보정본 OCR 통합": "v1_v2_combined",
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


def _filter_cited_chunks(answer: str, chunks: list) -> list:
    """답변의 [출처: <doc_short>, ...] 블록에 언급된 문서 청크만 반환한다."""

    cited_docs = {match.strip() for match in _re.findall(r"\[출처:\s*([^,\]\n]+)", answer)}
    if not cited_docs:
        return chunks
    filtered = [chunk for chunk in chunks if chunk.metadata.get("doc_short") in cited_docs]
    return filtered if filtered else chunks


def _sanitize_answer_markdown(text: str) -> str:
    """LLM 답변의 단일 물결표 양측에 공백을 추가해 취소선 렌더링을 방지한다."""

    return _re.sub(r"(?<![~\s])~(?![~\s])", " ~ ", text)


def _ensure_session_id() -> str:
    """세션 고유 ID를 생성하거나 기존 값을 반환한다."""

    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    return st.session_state.session_id



def _served_models(base_url: str, api_key: str | None = None) -> list[str]:
    """Return model IDs served by an OpenAI-compatible local endpoint."""

    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = requests.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=2)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []
    return [item.get("id") for item in payload.get("data", []) if item.get("id")]


def _switch_large_model(provider: str, model: str) -> None:
    """Switch the single large local model slot to the requested provider/model."""

    allowed = set(list_startup_large_models())
    if (provider, model) not in allowed:
        raise RuntimeError(f"허용되지 않은 대형 로컬 모델입니다: {provider}:{model}")
    if provider == "sglang":
        if not config.SGLANG_ENABLE_APP_SWITCH:
            raise RuntimeError("앱 기반 SGLang 모델 전환이 비활성화되어 있습니다.")
        script = config.SGLANG_SWITCH_SCRIPT
        timeout = config.SGLANG_SWITCH_TIMEOUT
        label = "SGLang"
    elif provider == "vllm":
        if not config.VLLM_ENABLE_APP_SWITCH:
            raise RuntimeError("앱 기반 vLLM 모델 전환이 비활성화되어 있습니다.")
        script = config.VLLM_SWITCH_SCRIPT
        timeout = config.VLLM_SWITCH_TIMEOUT
        label = "vLLM"
    else:
        raise RuntimeError(f"대형 로컬 모델 provider가 아닙니다: {provider}")
    if not script.exists():
        raise RuntimeError(f"{label} 전환 스크립트가 없습니다: {script}")

    try:
        completed = subprocess.run(
            [str(script), model],
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label} 모델 로딩 시간이 초과되었습니다: {model}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
        raise RuntimeError(f"{label} 모델 전환 실패: {model}\n{detail}")


def _ensure_selected_large_model_ready() -> None:
    """Load the login-selected large local model before the chat UI is used."""

    if config.CLOUD_DEPLOY:
        return
    models = list_startup_large_models()
    if not models:
        return
    selected = st.session_state.get("selected_large_model")
    if not selected:
        selected = provider_prefixed_model("vllm", config.VLLM_DEFAULT_MODEL) if ("vllm", config.VLLM_DEFAULT_MODEL) in models else provider_prefixed_model(*models[0])
    provider, model = split_model_selection(selected)
    if (provider, model) not in models:
        provider, model = models[0]
        selected = provider_prefixed_model(provider, model)
        st.session_state.selected_large_model = selected

    base_url = config.vllm_base_url_for_model(model) if provider == "vllm" else config.sglang_base_url_for_model(model)
    api_key = config.VLLM_API_KEY if provider == "vllm" else config.SGLANG_API_KEY
    served = _served_models(base_url, api_key=api_key)
    if model in served:
        st.session_state.loaded_large_model = selected
        return

    with st.spinner(f"대형 로컬 모델을 로딩 중입니다: {format_model_label(model, provider)}"):
        _switch_large_model(provider, model)
    try:
        _get_available_models_grouped.clear()
    except AttributeError:
        pass
    try:
        _load_llm.clear()
    except AttributeError:
        pass
    st.session_state.loaded_large_model = selected

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


def _start_new_chat() -> None:
    """새 채팅을 시작한다."""

    st.session_state.current_chat_id = None
    st.session_state.messages = []
    st.session_state["last_debug"] = None


def _switch_chat(user_id: str, chat_id: str) -> None:
    """저장된 채팅을 불러와 현재 세션에 적용한다."""

    chat = load_chat(user_id, chat_id)
    if chat:
        st.session_state.current_chat_id = chat_id
        st.session_state.messages = chat["messages"]
        st.session_state["last_debug"] = None


def _auto_save(user_id: str) -> None:
    """어시스턴트 메시지 추가 후 채팅을 자동 저장하고 목록을 갱신한다."""

    if not user_id or not st.session_state.messages:
        return
    if st.session_state.get("current_chat_id") is None:
        st.session_state.current_chat_id = new_chat_id()
    save_chat(user_id, st.session_state.current_chat_id, st.session_state.messages)
    st.session_state.chat_list = list_user_chats(user_id)


def _check_auth(session_id: str) -> bool:
    """ID·비밀번호 인증 상태를 확인하고 로그인 화면을 렌더링한다."""

    if st.session_state.get("authenticated"):
        return True

    if not user_store.has_admin():
        render_logo(width=220)
        st.markdown(
            '<h1 class="app-header" style="text-align:center;">보험 문서 RAG 챗봇</h1>',
            unsafe_allow_html=True,
        )
        st.error(_admin_bootstrap_message())
        return False

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        render_logo(width=220)
        st.markdown(
            '<p class="login-subtitle">임직원 전용 보험 문서 RAG 서비스</p>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.subheader("🔐 로그인")
        large_models = [provider_prefixed_model(provider, model) for provider, model in list_startup_large_models()]
        selected_large_model = None
        if large_models:
            default_large = st.session_state.get("selected_large_model") or provider_prefixed_model("vllm", config.VLLM_DEFAULT_MODEL)
            default_index = large_models.index(default_large) if default_large in large_models else 0
            selected_large_model = st.selectbox(
                "대형 로컬 모델",
                large_models,
                index=default_index,
                format_func=lambda value: format_model_label(split_model_selection(value)[1], split_model_selection(value)[0]),
                help="로그인 후 선택한 대형 로컬 모델 1개만 로딩합니다. Gemma4는 vLLM 경로를 사용합니다.",
            )
        username = st.text_input("사용자명", placeholder="사용자명")
        password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
        if st.button("로그인", use_container_width=True, type="primary"):
            if selected_large_model:
                st.session_state.selected_large_model = selected_large_model
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
    index_mode: str = "default",
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
        "index_mode": index_mode,
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
    index_mode: str = "default",
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
        "index_mode": index_mode,
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
    """Provider and model selection widgets; returns a provider-prefixed model ID."""

    grouped = _get_available_models_grouped()
    provider_labels = {
        "vllm": "vLLM",
        "sglang": "SGLang",
        "ollama": "Ollama",
        "openai": "OpenAI Cloud",
    }
    providers = [provider for provider in ("vllm", "sglang", "ollama", "openai") if grouped.get(provider)]
    if not providers:
        st.error("사용 가능한 LLM provider가 없습니다. SGLang/Ollama 실행 또는 OpenAI 설정을 확인하세요.")
        st.stop()

    default_provider = "vllm" if "vllm" in providers else "sglang" if "sglang" in providers else providers[0]
    provider = st.selectbox(
        "LLM Provider",
        providers,
        index=providers.index(default_provider),
        format_func=lambda value: provider_labels.get(value, value),
    )
    models = grouped[provider]
    if not models:
        st.error("선택한 provider에 사용 가능한 모델이 없습니다.")
        st.stop()

    default_model = {
        "vllm": config.VLLM_DEFAULT_MODEL,
        "sglang": config.SGLANG_DEFAULT_MODEL,
        "ollama": config.OLLAMA_MODEL,
        "openai": config.OPENAI_DEFAULT_MODEL,
    }.get(provider, models[0])
    default_index = models.index(default_model) if default_model in models else 0
    selected_model = st.selectbox(
        "LLM 모델",
        models,
        index=default_index,
        format_func=lambda model: format_model_label(model, provider),
    )
    selected = provider_prefixed_model(provider, selected_model)
    if provider == "openai" or is_openai_model(selected):
        st.info("⚠ OpenAI 모델은 외부 서버를 호출합니다. 입력된 질문과 검색된 청크가 OpenAI로 전송됩니다.")
    return selected


@st.cache_resource
def _load_heavy_components(index_mode: str):
    """임베더·벡터스토어·BM25·Reranker와 OCR pair mapping을 로드한다."""

    bm25_path, chroma_dir = resolve_index_paths(index_mode)
    if not bm25_path.exists():
        raise RuntimeError(
            f"BM25 인덱스가 없습니다: {bm25_path}\n"
            "필요 시 해당 OCR 인덱스 모드를 먼저 생성하세요."
        )

    embedder = Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
    vector_store = VectorStore(chroma_dir)
    bm25 = BM25Index.load(bm25_path)
    reranker = build_reranker(enabled=config.RERANKER_ENABLED)

    pair_store = PairMappingStore(config.ROOT_DIR / "data" / "mapping")
    for doc in ("실무가이드", "상담사례집"):
        pair_store.load_doc(doc)

    v1_lookup = {}
    v1_chunks_path = config.ROOT_DIR / "data" / "processed" / "chunks_v1_rechunked_target16.jsonl"
    if v1_chunks_path.exists():
        v1_lookup = load_chunk_lookup(v1_chunks_path, docs=["실무가이드", "상담사례집"])

    return embedder, vector_store, bm25, reranker, pair_store, v1_lookup


@st.cache_resource
def _load_llm(model: str):
    """선택된 provider/model 전용 LLM 클라이언트를 생성한다."""

    provider, model_id = split_model_selection(model)
    return build_llm(model_id, provider=provider)


def _get_pipeline(model: str, top_k: int, index_mode: str = "default") -> RagPipeline:
    """캐시된 컴포넌트로 RagPipeline 객체를 조합한다."""

    embedder, vector_store, bm25, reranker, pair_store, v1_lookup = _load_heavy_components(index_mode)
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
        pair_mapping_store=pair_store,
        v1_chunk_lookup=v1_lookup,
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
) -> tuple[str, list, dict, DebugInfo | None]:
    """검색 후 LLM 스트리밍 답변을 렌더링하고 결과를 반환한다."""

    total_started = time.perf_counter()
    with st.spinner("관련 문서 검색 중..."):
        retrieve_started = time.perf_counter()
        hits, debug = pipeline.retrieve_hits(question, doc_filter=doc_filter, return_debug=True)
        chunks = [_hit_to_chunk(hit) for hit in hits]
        retrieve_ms = (time.perf_counter() - retrieve_started) * 1000

    prompt = pipeline.build_prompt(question, chunks)
    llm_started = time.perf_counter()
    placeholder = st.empty()
    tokens: list[str] = []
    for token in pipeline.llm.generate_stream(prompt, system=SYSTEM_PROMPT, temperature=temperature):
        tokens.append(token)
        placeholder.markdown("".join(tokens) + "▌")

    raw_answer = "".join(tokens).strip()
    answer = append_retrieved_source_citations(_sanitize_answer_markdown(raw_answer), chunks)
    answer = append_evidence_validation_warning(answer, question, chunks)
    placeholder.markdown(answer)
    llm_ms = (time.perf_counter() - llm_started) * 1000
    total_ms = (time.perf_counter() - total_started) * 1000
    return answer, chunks, {"retrieve_ms": retrieve_ms, "llm_ms": llm_ms, "total_ms": total_ms}, debug


def _handle_quick_code(
    procedure_name: str,
    include_summary: bool,
    include_coverage: bool,
    pipeline: RagPipeline,
    model: str,
    temperature: float,
    session_id: str,
    selected_docs: list[str] | None,
) -> None:
    """퀵 코드 검색 폼 제출을 처리한다."""

    question = f"퀵 코드 검색: {procedure_name}"
    options = {"summary": include_summary, "coverage": include_coverage}
    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state["last_debug"] = None
    log_selected_docs = list(selected_docs or [])
    _log(
        EVENT_QUESTION,
        _build_question_log_details(
            mode="quick_code",
            model=model,
            top_k=6,
            temperature=0.0,
            selected_docs=log_selected_docs,
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
                if selected_docs is None:
                    hits, _ = pipeline.retrieve_hits(procedure_name, top_k=QUICK_CODE_TOP_K, doc_filter=None)
                    chunks = [_hit_to_chunk(hit) for hit in hits]
                    applied_doc_filter = []
                else:
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
            answer = _sanitize_answer_markdown(answer)
            answer = append_retrieved_source_citations(answer, chunks)
            llm_ms = (time.perf_counter() - llm_started) * 1000
        except RuntimeError as exc:
            st.error(str(exc))
            return

        total_ms = (time.perf_counter() - total_started) * 1000
        timing = {"retrieve_ms": retrieve_ms, "llm_ms": llm_ms, "total_ms": total_ms}
        cited_chunks = _filter_cited_chunks(answer, chunks)
        st.markdown(answer)
        render_sources(cited_chunks, key_prefix=f"quick_{len(st.session_state.messages)}")
        render_timing(timing)

    _log(
        EVENT_ANSWER,
        _build_answer_log_details(
            mode="quick_code",
            model=model,
            selected_docs=applied_doc_filter,
            answer=answer,
            timing=timing,
            chunks=cited_chunks,
            question=procedure_name,
            **_llm_answer_log_extra(pipeline),
            extra={"options": options},
        ),
    )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "chunks": cited_chunks,
            "timing": timing,
            "model": model,
        }
    )
    _auto_save(st.session_state.get("user_id", ""))


def _handle_insurance_form(
    form: InsuranceFormInput,
    pipeline: RagPipeline,
    model: str,
    session_id: str,
    selected_docs: list[str] | None,
) -> None:
    """약관 정형 검색 폼 제출을 처리한다."""

    sub_mode_label = {value: key for key, value in INSURANCE_SUB_MODES.items()}[form.mode]
    question = f"약관 정형 검색({sub_mode_label}): {form.primary}"
    applied_doc_filter = [] if selected_docs is None else list(dict.fromkeys(["약관"] + selected_docs))
    log_extra = {
        "sub_mode": form.mode,
        "form_input": _insurance_form_log_input(form),
    }

    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state["last_debug"] = None
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
                if selected_docs is None:
                    hits, _ = pipeline.retrieve_hits(
                        build_form_query(form),
                        top_k=INSURANCE_FORM_TOP_K,
                        doc_filter=None,
                    )
                    chunks = [_hit_to_chunk(hit) for hit in hits]
                    applied_doc_filter = []
                else:
                    chunks, applied_doc_filter = retrieve_insurance_form_chunks(
                        pipeline,
                        form,
                        extra_doc_filter=selected_docs,
                    )
                retrieve_ms = (time.perf_counter() - retrieve_started) * 1000

            llm_started = time.perf_counter()
            answer = generate_insurance_form_answer(pipeline, form, chunks, temperature=0.1)
            answer = _sanitize_answer_markdown(answer)
            llm_ms = (time.perf_counter() - llm_started) * 1000
        except RuntimeError as exc:
            st.error(str(exc))
            return

        total_ms = (time.perf_counter() - total_started) * 1000
        timing = {"retrieve_ms": retrieve_ms, "llm_ms": llm_ms, "total_ms": total_ms}
        cited_chunks = _filter_cited_chunks(answer, chunks)
        st.markdown(answer)
        render_sources(cited_chunks, key_prefix=f"insurance_{len(st.session_state.messages)}")
        render_timing(timing)

    _log(
        EVENT_ANSWER,
        _build_answer_log_details(
            mode="insurance_form",
            model=model,
            selected_docs=applied_doc_filter,
            answer=answer,
            timing=timing,
            chunks=cited_chunks,
            question=form.primary,
            **_llm_answer_log_extra(pipeline),
            extra=log_extra,
        ),
    )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "chunks": cited_chunks,
            "timing": timing,
            "model": model,
        }
    )
    _auto_save(st.session_state.get("user_id", ""))


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


def render_claim_calculation_panel(model: str, get_pipeline_or_show_error, session_id: str) -> None:
    st.subheader("📋 보험금 지급예상액 계산 (MVP)")

    # Session state initialization for results
    if "claim_calc_result" not in st.session_state:
        st.session_state["claim_calc_result"] = None
    if "claim_calc_error" not in st.session_state:
        st.session_state["claim_calc_error"] = None
    if "claim_calc_rag_failed" not in st.session_state:
        st.session_state["claim_calc_rag_failed"] = False
    if "claim_input_code" not in st.session_state:
        st.session_state["claim_input_code"] = ""

    # Layout: Two columns for inputs
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 1. 청구 항목 입력")
        input_name = st.text_input("청구 항목명", value="도수치료", placeholder="예: 도수치료, 체외충격파치료")
        input_code = st.text_input("표준코드 (선택)", key="claim_input_code", placeholder="예: SC0001 (공란인 경우 명칭 매칭)")
        claimed_amount = st.text_input("청구금액", value="150,000", placeholder="예: 150000, 150,000원")
        quantity = st.text_input("수량/횟수", value="1", placeholder="예: 1, 1회")
        user_category_hint = st.selectbox(
            "급여/비급여 구분",
            ["선택 안 함", "비급여", "3대비급여", "급여"],
            index=0
        )

    with col2:
        st.markdown("#### 2. 보상 상황 입력")
        visit_type = st.selectbox("방문 형태", ["통원", "입원", "선택 안 함"], index=0)
        accident_type = st.selectbox("사고 유형", ["질병", "상해", "교통사고", "선택 안 함"], index=0)
        coverage_topic = st.text_input("보장종목", value="실손", placeholder="예: 실손, 3대비급여")
        diagnosis_code = st.text_input("진단코드", value="", placeholder="예: M54.5")
        diagnosis_name = st.text_input("진단명", value="", placeholder="예: 요통")
        situation_note = st.text_area("상황 메모", value="", placeholder="예: 도수치료 1회차 통원 치료 시행함")

    st.markdown("#### 3. 계산 기준 문서 및 모드 선택")

    col3, col4 = st.columns(2)
    with col3:
        basis_mode = st.radio("근거 문서 선택 방식", ["자동 선택 (추천)", "수동 선택"], horizontal=True)
        selected_docs = None
        if basis_mode == "수동 선택":
            selected_docs = st.multiselect(
                "적용 대상 문서",
                ["약관", "자사_SOL건강", "자사_SOL운전자", "실무가이드", "상담사례집", "심평원"],
                default=["약관", "실무가이드"]
            )

    with col4:
        planner_type = st.radio("플래너 유형", ["Fake Planner", "LLM Planner"], horizontal=True)
        rag_enabled = False
        if planner_type == "Fake Planner":
            rag_enabled = st.checkbox("RAG 근거 검색 사용", value=False)

    submitted = st.button("지급예상액 계산 실행", type="primary", use_container_width=True)

    visit_type_map = {
        "통원": "outpatient",
        "입원": "hospitalization",
        "선택 안 함": ""
    }
    accident_type_map = {
        "질병": "disease",
        "상해": "injury",
        "교통사고": "accident",
        "선택 안 함": ""
    }

    def run_calc(use_rag_active: bool):
        try:
            from decimal import Decimal
            from src.claim_calculation.models import ClaimItemInput, ClaimCaseContext
            from src.claim_calculation.pipeline import run_claim_calculation
        except ImportError as exc:
            st.session_state["claim_calc_error"] = f"모듈 임포트 실패: {exc}"
            return

        # Prepare items
        items = [
            ClaimItemInput(
                line_id="item_1",
                input_name=input_name.strip(),
                input_code=input_code.strip(),
                claimed_amount=claimed_amount.strip(),
                quantity=quantity.strip(),
                user_category_hint=user_category_hint if user_category_hint != "선택 안 함" else ""
            )
        ]

        # Prepare context
        context = ClaimCaseContext(
            visit_type=visit_type_map[visit_type],
            coverage_topic=coverage_topic.strip(),
            diagnosis_code=diagnosis_code.strip(),
            diagnosis_name=diagnosis_name.strip(),
            accident_type=accident_type_map[accident_type],
            situation_note=situation_note.strip()
        )

        active_rag_pipeline = None
        if use_rag_active:
            active_rag_pipeline = get_pipeline_or_show_error()
            if active_rag_pipeline is None:
                st.session_state["claim_calc_error"] = "RAG 파이프라인을 활성화할 수 없습니다."
                return

        try:
            with st.spinner("보험금 계산 처리 중..."):
                res = run_claim_calculation(
                    rag_pipeline=active_rag_pipeline,
                    items=items,
                    context=context,
                    basis_mode="manual" if basis_mode == "수동 선택" else "auto",
                    selected_basis_docs=selected_docs if basis_mode == "수동 선택" else None,
                    use_fake_planner=(planner_type == "Fake Planner"),
                    model_id=split_model_selection(model)[1],
                    provider=split_model_selection(model)[0],
                )
            st.session_state["claim_calc_result"] = res
            st.session_state["claim_calc_error"] = None
        except Exception as e:
            st.session_state["claim_calc_result"] = None
            st.session_state["claim_calc_error"] = str(e)

    if submitted:
        st.session_state["claim_calc_result"] = None
        st.session_state["claim_calc_error"] = None
        st.session_state["claim_calc_rag_failed"] = False

        if not input_name.strip():
            st.warning("청구 항목명을 입력해주세요.")
            return

        use_rag = (planner_type == "LLM Planner") or (planner_type == "Fake Planner" and rag_enabled)

        if use_rag:
            # Check pipeline status
            pipeline_obj = get_pipeline_or_show_error()
            if pipeline_obj is None:
                st.session_state["claim_calc_rag_failed"] = True
                return

        run_calc(use_rag_active=use_rag)

    # Fallback rendering if RAG load failed
    if st.session_state.get("claim_calc_rag_failed"):
        st.error("임베딩 모델 및 RAG 파이프라인 로드 실패로 인해 RAG 검색을 사용할 수 없습니다.")
        if st.button("비급여 DB 단독 계산으로 계속", key="fallback_calc_btn", use_container_width=True):
            st.session_state["claim_calc_rag_failed"] = False
            run_calc(use_rag_active=False)
            st.rerun()

    # Render results
    result = st.session_state.get("claim_calc_result")
    error = st.session_state.get("claim_calc_error")

    if error:
        st.error(f"계산 수행 에러: {error}")

    if result:
        from decimal import Decimal
        st.markdown("### 📊 계산 결과")

        # 만약 다중 후보가 존재할 경우 선택 가이드 제공
        if hasattr(result, "candidates") and result.candidates:
            st.warning("⚠️ 입력하신 청구 항목명에 대해 매칭되는 표준코드가 2개 이상 존재하여 계산이 보류되었습니다. 아래에서 적절한 코드를 선택하시면 계산이 자동 재개됩니다:")
            # 후보 리스트 버튼 렌더링
            cols = st.columns(min(len(result.candidates), 3))
            for idx, cand in enumerate(result.candidates):
                col_idx = idx % len(cols)
                btn_label = f"📌 {cand['code']}\n({cand['name']})"
                if cols[col_idx].button(btn_label, key=f"cand_btn_{cand['code']}_{idx}", use_container_width=True):
                    st.session_state["claim_input_code"] = cand["code"]
                    st.session_state["claim_calc_result"] = None
                    st.session_state["claim_calc_error"] = None
                    st.rerun()
            st.markdown("---")

        # Grid/Metrics display
        col_c, col_d, col_e = st.columns(3)
        try:
            c_val = int(Decimal(result.claimed_amount))
            claimed_disp = f"{c_val:,}원"
        except:
            claimed_disp = f"{result.claimed_amount}원"

        try:
            d_val = int(Decimal(result.deductible))
            deductible_disp = f"{d_val:,}원"
        except:
            deductible_disp = f"{result.deductible}원"

        try:
            p_val = int(Decimal(result.payable_amount))
            payable_disp = f"{p_val:,}원"
        except:
            payable_disp = f"{result.payable_amount}원"

        col_c.metric("총 청구금액", claimed_disp)
        col_d.metric("공제금액", deductible_disp)
        col_e.metric("지급예상액", payable_disp)

        if result.requires_review:
            st.warning("⚠️ 추가 심사 및 정밀 검토가 필요합니다.")
            for reason in result.review_reasons:
                st.write(f"- {reason}")
        else:
            st.success("✅ 지급예상액 계산이 통과되었습니다. (추가 심사 필요 없음)")

        # Applied basis
        if result.applied_basis:
            st.markdown("#### 📄 적용 근거")
            for idx, basis in enumerate(result.applied_basis):
                with st.expander(f"{idx+1}. {basis['source']}"):
                    st.write(basis["content"])

        # Executed formula code
        if result.executed_code:
            st.markdown("#### ⚙️ 실행 산식")
            st.code(result.executed_code, language="python")


def main() -> None:
    st.set_page_config(page_title="보험 고시 문서 RAG 챗봇")
    inject_css()
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

    try:
        _ensure_selected_large_model_ready()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    user_id = st.session_state.get("user_id", "")
    if "chat_list" not in st.session_state:
        st.session_state.chat_list = list_user_chats(user_id)
    if "current_chat_id" not in st.session_state:
        st.session_state.current_chat_id = None
    if "messages" not in st.session_state:
        st.session_state.messages = []

    render_logo(width=360)
    st.markdown('<h1 class="app-header">보험 문서 RAG 챗봇</h1>', unsafe_allow_html=True)
    index_mode = "default"

    with st.sidebar:
        if config.CLOUD_DEPLOY:
            st.info("클라우드 배포 - 외부 LLM(OpenAI) 전용")
        display = st.session_state.get("user_display", "")
        role = st.session_state.get("user_role", "")
        role_label = "관리자" if role == ROLE_ADMIN else "직원"
        st.markdown(f"**{display}** · _{role_label}_")
        if st.session_state.get("selected_large_model"):
            provider, model = split_model_selection(st.session_state.selected_large_model)
            st.caption(f"대형 모델: {format_model_label(model, provider)}")
        if st.button("로그아웃", use_container_width=True):
            _log(EVENT_LOGOUT)
            for key in (
                "authenticated",
                "user_id",
                "user_role",
                "user_display",
                "messages",
                "last_debug",
                "current_chat_id",
                "chat_list",
                "loaded_large_model",
            ):
                st.session_state.pop(key, None)
        # vLLM strict 모드 토글 추가
        strict_mode = st.toggle(
            "vLLM Strict 모드",
            value=config.VLLM_STRICT_AVAILABLE_MODELS,
            help="활성화하면 vLLM API 엔드포인트에서 실제로 서비스 중인 모델만 노출합니다.",
        )
        if strict_mode != config.VLLM_STRICT_AVAILABLE_MODELS:
            config.VLLM_STRICT_AVAILABLE_MODELS = strict_mode
            try:
                _get_available_models_grouped.clear()
            except AttributeError:
                pass
            st.rerun()

        page = st.radio("페이지", ["챗봇", "관리자"], horizontal=True, key="page") if role == ROLE_ADMIN else "챗봇"
        st.divider()

        if page == "챗봇":
            model = _select_model_widget()
            index_label = st.selectbox("OCR 인덱스 모드", list(OCR_INDEX_MODES.keys()), index=0)
            index_mode = OCR_INDEX_MODES[index_label]
            top_k = st.slider("Top-K", min_value=4, max_value=12, value=8)
            temperature = st.slider("온도", min_value=0.0, max_value=0.7, value=0.2, step=0.1)

            st.divider()
            st.subheader("💬 채팅 목록")
            if st.button("+ 새 채팅", use_container_width=True, type="primary"):
                _start_new_chat()
                st.rerun()

            chat_list = st.session_state.get("chat_list", [])
            if not chat_list:
                st.caption("저장된 채팅이 없습니다.")
            else:
                for meta in chat_list:
                    chat_id = meta["chat_id"]
                    is_active = chat_id == st.session_state.get("current_chat_id")
                    date_str = meta.get("updated_at", "")[:10]
                    label = meta.get("title", "제목 없음")

                    col_btn, col_del = st.columns([5, 1])
                    with col_btn:
                        btn_type = "primary" if is_active else "secondary"
                        if st.button(
                            label,
                            key=f"chat_sel_{chat_id}",
                            use_container_width=True,
                            type=btn_type,
                            help=f"{date_str} · {meta.get('message_count', 0)}개 메시지",
                        ):
                            if not is_active:
                                _switch_chat(user_id, chat_id)
                                st.rerun()
                    with col_del:
                        if st.button("🗑", key=f"chat_del_{chat_id}", help="삭제"):
                            delete_chat(user_id, chat_id)
                            if is_active:
                                _start_new_chat()
                            st.session_state.chat_list = list_user_chats(user_id)
                            st.rerun()

            st.divider()
            st.markdown("#### 검색 범위")
            st.caption("현재 전체 문서를 검색합니다.")

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

    pipeline = None
    pipeline_error = None

    def get_pipeline_or_show_error() -> RagPipeline | None:
        nonlocal pipeline, pipeline_error
        if pipeline is not None:
            return pipeline
        if pipeline_error is not None:
            st.error(pipeline_error)
            return None
        try:
            pipeline = _get_pipeline(model, top_k, index_mode=index_mode)
            return pipeline
        except RuntimeError as exc:
            pipeline_error = str(exc)
            st.error(pipeline_error)
            return None

    for message_index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                if message.get("chunks"):
                    render_sources(message["chunks"], key_prefix=f"history_{message_index}")
                render_timing(message.get("timing"))

    search_mode = st.radio("검색 모드", SEARCH_MODES, horizontal=True, key="search_mode")

    if search_mode == "보험금 계산":
        render_claim_calculation_panel(model, get_pipeline_or_show_error, session_id)
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
            active_pipeline = get_pipeline_or_show_error()
            if active_pipeline is None:
                return
            _handle_insurance_form(form, active_pipeline, model, session_id, None)
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
            active_pipeline = get_pipeline_or_show_error()
            if active_pipeline is None:
                return
            _handle_quick_code(
                procedure_name.strip(),
                opt_summary,
                opt_coverage,
                active_pipeline,
                model,
                temperature,
                session_id,
                None,
            )
        return

    question = st.chat_input("질문을 입력하세요")
    if question:
        active_pipeline = get_pipeline_or_show_error()
        if active_pipeline is not None:
            _log(
                EVENT_QUESTION,
                _build_question_log_details(
                    mode="general",
                    model=model,
                    top_k=top_k,
                    temperature=temperature,
                    selected_docs=[],
                    question=question,
                    index_mode=index_mode,
                ),
            )
            st.session_state.messages.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                try:
                    answer, chunks, timing, debug = _stream_answer(
                        active_pipeline,
                        question,
                        temperature,
                        doc_filter=None,
                    )
                except RuntimeError as exc:
                    st.error(str(exc))
                    return
                st.session_state["last_debug"] = debug
                cited_chunks = _filter_cited_chunks(answer, chunks)
                render_sources(cited_chunks, key_prefix=f"current_{len(st.session_state.messages)}")
                render_timing(timing)

            _log(
                EVENT_ANSWER,
                _build_answer_log_details(
                    mode="general",
                    model=model,
                    selected_docs=[],
                    answer=answer,
                    timing=timing,
                    chunks=cited_chunks,
                    question=question,
                    index_mode=index_mode,
                    **_llm_answer_log_extra(active_pipeline),
                ),
            )
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "chunks": cited_chunks,
                    "timing": timing,
                    "model": model,
                }
            )
            _auto_save(user_id)

    # 관리자 진단 도구
    role = st.session_state.get("user_role", "")
    if role == ROLE_ADMIN and st.session_state.get("last_debug") is not None:
        debug_info = st.session_state["last_debug"]
        st.divider()
        with st.expander("🛠️ RAG 관리자 진단 도구", expanded=True):
            st.subheader("RAG 단계별 중간 검색 결과")

            # metrics 연산
            last_answer = ""
            if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
                last_answer = st.session_state.messages[-1]["content"]

            final_hits = debug_info.final_hits if debug_info.final_hits else []
            fused_docs = list({hit.doc_short for hit in final_hits if hit.doc_short})
            referenced_docs = [doc for doc in fused_docs if doc in last_answer]
            coverage = len(referenced_docs) / len(fused_docs) if fused_docs else 1.0

            has_table = False
            last_chunks = st.session_state.messages[-1].get("chunks", []) if st.session_state.messages else []
            for chunk in last_chunks:
                raw_table = chunk.metadata.get("table_json")
                if raw_table not in (None, "", "{}"):
                    has_table = True
                    break

            table_cited = False
            if has_table:
                page_mentioned = any(str(chunk.metadata.get("page_start")) in last_answer for chunk in last_chunks if chunk.metadata.get("page_start") is not None)
                if "[구조화" in last_answer or page_mentioned:
                    table_cited = True

            col1, col2 = st.columns(2)
            col1.metric("출처 커버리지 (Source Coverage)", f"{coverage * 100:.1f}%")
            if has_table:
                col2.metric("테이블 메타데이터 인용 여부", "인용됨" if table_cited else "미인용 (경고)")
            else:
                col2.metric("테이블 메타데이터 인용 여부", "N/A (표 없음)")

            # 단계별 Hit 표시 (Tabs 사용)
            tab_dense, tab_bm25, tab_rrf, tab_final = st.tabs([
                "1. Dense Retrieval",
                "2. BM25 Retrieval",
                "3. RRF Fusion",
                "4. Final Reranked"
            ])

            def render_debug_hits(hits):
                if not hits:
                    st.caption("결과가 없습니다.")
                    return
                for idx, hit in enumerate(hits, start=1):
                    st.markdown(f"**{idx}. [{hit.doc_short}]** (Score: {hit.score}) | 페이지: {hit.page_start or 'N/A'}")
                    st.caption(hit.text_preview)

            with tab_dense:
                render_debug_hits(debug_info.dense_hits)
            with tab_bm25:
                render_debug_hits(debug_info.bm25_hits)
            with tab_rrf:
                render_debug_hits(debug_info.rrf_hits)
            with tab_final:
                render_debug_hits(debug_info.final_hits)


if __name__ == "__main__":
    main()
