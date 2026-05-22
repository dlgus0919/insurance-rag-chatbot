"""계정별 채팅 내역 저장소."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.parser.chunker import Chunk

CHAT_HISTORY_DIR = config.ROOT_DIR / "data" / "chat_history"
MAX_CHATS_PER_USER = 50


def _chat_dir(user_id: str) -> Path:
    path = CHAT_HISTORY_DIR / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_chat_id() -> str:
    """8자리 UUID를 생성한다."""

    return str(uuid.uuid4())[:8]


def _auto_title(messages: list[dict]) -> str:
    """첫 사용자 메시지 앞 30자를 채팅 제목으로 사용한다."""

    for message in messages:
        if message.get("role") == "user":
            return message["content"][:30].replace("\n", " ")
    return "새 채팅"


def _chunk_to_dict(chunk: Chunk) -> dict:
    return {"id": chunk.id, "text": chunk.text, "metadata": chunk.metadata}


def _dict_to_chunk(data: dict) -> Chunk:
    return Chunk(id=data["id"], text=data["text"], metadata=data.get("metadata", {}))


def _graph_result_to_dict(res: any) -> dict | None:
    if res is None:
        return None
    if isinstance(res, dict):
        return res

    try:
        confirmed_count = sum(1 for f in res.facts if f.status == "confirmed")
        candidate_count = sum(1 for f in res.facts if f.status == "candidate")
        missing_count = sum(1 for f in res.facts if f.status == "missing")

        summary_facts = []
        for f in res.facts[:10]:
            summary_facts.append({
                "subject": f.subject,
                "relation": f.relation,
                "object": f.object,
                "status": f.status
            })

        return {
            "is_summary": True,
            "intents": res.plan.intents if hasattr(res, "plan") and res.plan else [],
            "confirmed_count": confirmed_count,
            "candidate_count": candidate_count,
            "missing_count": missing_count,
            "facts": summary_facts,
            "warnings": res.warnings if hasattr(res, "warnings") else [],
        }
    except Exception:
        return {
            "is_summary": True,
            "intents": [],
            "confirmed_count": 0,
            "candidate_count": 0,
            "missing_count": 0,
            "facts": [],
            "warnings": ["Graph result serialization failed."]
        }


def _dict_to_graph_result(data: dict | None) -> any:
    if data is None:
        return None

    try:
        from src.graph.query_planner import GraphQueryPlan
        from src.graph.retriever import GraphRetrievalResult, GraphFact, GraphEvidence
    except ImportError:
        return data

    try:
        if data.get("is_summary"):
            plan = GraphQueryPlan(intents=data.get("intents", []))
            facts = []
            for f in data.get("facts", []):
                facts.append(GraphFact(
                    subject=f.get("subject", ""),
                    relation=f.get("relation", ""),
                    object=f.get("object"),
                    confidence=1.0,
                    status=f.get("status", "missing"),
                    evidence=[]
                ))
            return GraphRetrievalResult(
                plan=plan,
                facts=facts,
                source_chunk_ids=[],
                warnings=data.get("warnings", []),
                debug={}
            )
        else:
            plan_data = data.get("plan", {})
            plan = GraphQueryPlan(
                intents=plan_data.get("intents", []),
                procedure_name=plan_data.get("procedure_name"),
                grade_system=plan_data.get("grade_system"),
                grade_value=plan_data.get("grade_value"),
                category=plan_data.get("category"),
                policy_product=plan_data.get("policy_product"),
                appendix=plan_data.get("appendix"),
                hira_code=plan_data.get("hira_code"),
                requested_peer_count=plan_data.get("requested_peer_count", 3),
            )

            facts = []
            for f in data.get("facts", []):
                evidences = []
                for ev in f.get("evidence", []):
                    evidences.append(GraphEvidence(
                        evidence_id=ev.get("evidence_id"),
                        chunk_id=ev.get("chunk_id"),
                        doc_short=ev.get("doc_short", ""),
                        doc_name=ev.get("doc_name"),
                        pdf_filename=ev.get("pdf_filename"),
                        page_start=ev.get("page_start"),
                        page_end=ev.get("page_end"),
                        source_version=ev.get("source_version"),
                        row_text=ev.get("row_text"),
                        confidence=ev.get("confidence", 1.0),
                    ))
                facts.append(GraphFact(
                    subject=f.get("subject"),
                    relation=f.get("relation"),
                    object=f.get("object"),
                    confidence=f.get("confidence", 1.0),
                    status=f.get("status", "missing"),
                    evidence=evidences,
                    properties=f.get("properties", {}),
                ))

            return GraphRetrievalResult(
                plan=plan,
                facts=facts,
                source_chunk_ids=data.get("source_chunk_ids", []),
                warnings=data.get("warnings", []),
                debug=data.get("debug", {}),
            )
    except Exception:
        return data



def _serialize_messages(messages: list[dict]) -> list[dict]:
    """st.session_state 형식을 JSON 저장 형식으로 변환한다."""

    serialized = []
    for message in messages:
        entry: dict = {"role": message["role"], "content": message["content"]}
        if message["role"] == "assistant":
            for key in ("timing", "model"):
                if key in message:
                    entry[key] = message[key]
            if "chunks" in message:
                entry["chunks"] = [_chunk_to_dict(chunk) for chunk in message["chunks"]]
            if "graph_result" in message:
                entry["graph_result"] = _graph_result_to_dict(message["graph_result"])
        serialized.append(entry)
    return serialized


def _deserialize_messages(messages: list[dict]) -> list[dict]:
    """JSON 저장 형식을 st.session_state 형식으로 복원한다."""

    deserialized = []
    for message in messages:
        entry: dict = {"role": message["role"], "content": message["content"]}
        if message["role"] == "assistant":
            for key in ("timing", "model"):
                if key in message:
                    entry[key] = message[key]
            if "chunks" in message:
                entry["chunks"] = [_dict_to_chunk(chunk) for chunk in message["chunks"]]
            if "graph_result" in message:
                entry["graph_result"] = _dict_to_graph_result(message["graph_result"])
        deserialized.append(entry)
    return deserialized


def save_chat(user_id: str, chat_id: str, messages: list[dict], title: str | None = None) -> None:
    """채팅을 디스크에 저장한다. 이미 존재하면 created_at을 보존하고 내용을 갱신한다."""

    path = _chat_dir(user_id) / f"{chat_id}.json"
    now = datetime.now(timezone.utc).isoformat()

    created_at = now
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            created_at = existing.get("created_at", now)
        except (OSError, json.JSONDecodeError):
            pass

    data = {
        "chat_id": chat_id,
        "user_id": user_id,
        "title": title or _auto_title(messages),
        "created_at": created_at,
        "updated_at": now,
        "message_count": len(messages),
        "messages": _serialize_messages(messages),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_chat(user_id: str, chat_id: str) -> dict | None:
    """저장된 채팅을 로드한다. 파일이 없거나 손상된 경우 None을 반환한다."""

    path = _chat_dir(user_id) / f"{chat_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["messages"] = _deserialize_messages(data.get("messages", []))
        return data
    except (OSError, KeyError, json.JSONDecodeError):
        return None


def list_user_chats(user_id: str) -> list[dict]:
    """사용자의 채팅 목록을 최신순으로 반환한다. messages 필드는 제외한다."""

    chats: list[dict] = []
    for path in _chat_dir(user_id).glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            chats.append(
                {
                    "chat_id": raw["chat_id"],
                    "title": raw.get("title", "제목 없음"),
                    "updated_at": raw.get("updated_at", ""),
                    "message_count": raw.get("message_count", 0),
                }
            )
        except (OSError, KeyError, json.JSONDecodeError):
            continue
    chats.sort(key=lambda chat: chat["updated_at"], reverse=True)
    return chats[:MAX_CHATS_PER_USER]


def delete_chat(user_id: str, chat_id: str) -> bool:
    """채팅 파일을 삭제한다. 성공 여부를 반환한다."""

    path = _chat_dir(user_id) / f"{chat_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def rename_chat(user_id: str, chat_id: str, new_title: str) -> bool:
    """채팅 제목을 변경한다."""

    path = _chat_dir(user_id) / f"{chat_id}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["title"] = new_title[:40]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except (OSError, json.JSONDecodeError):
        return False
