import json
import time

import pytest

from src.parser.chunker import Chunk
from src.ui.chat_store import delete_chat, list_user_chats, load_chat, new_chat_id, rename_chat, save_chat


@pytest.fixture(autouse=True)
def isolated_chat_dir(tmp_path, monkeypatch):
    import src.ui.chat_store as chat_store

    monkeypatch.setattr(chat_store, "CHAT_HISTORY_DIR", tmp_path / "chat_history")


def _make_messages() -> list[dict]:
    chunk = Chunk(
        id="약관_ch_001",
        text="N39.3은 보상하지 않습니다.",
        metadata={"doc_short": "약관", "page_start": 38, "page_end": 38},
    )
    return [
        {"role": "user", "content": "N39.3 보상 여부는?"},
        {
            "role": "assistant",
            "content": "보상하지 않습니다.",
            "timing": {"retrieve_ms": 100.0, "llm_ms": 2000.0, "total_ms": 2100.0},
            "model": "gpt-5.2-chat-latest",
            "chunks": [chunk],
        },
    ]


def test_new_chat_id_returns_8_chars() -> None:
    chat_id = new_chat_id()

    assert len(chat_id) == 8


def test_save_and_load_chat_roundtrip() -> None:
    messages = _make_messages()
    save_chat("user1", "abc12345", messages)

    loaded = load_chat("user1", "abc12345")

    assert loaded is not None
    assert loaded["chat_id"] == "abc12345"
    assert loaded["title"] == "N39.3 보상 여부는?"
    assert len(loaded["messages"]) == 2
    assistant_msg = loaded["messages"][1]
    assert assistant_msg["model"] == "gpt-5.2-chat-latest"
    assert assistant_msg["chunks"][0].id == "약관_ch_001"


def test_save_chat_preserves_created_at_on_update() -> None:
    save_chat("user1", "abc12345", [{"role": "user", "content": "첫 질문"}])
    first = load_chat("user1", "abc12345")
    time.sleep(0.01)
    save_chat("user1", "abc12345", [{"role": "user", "content": "수정 질문"}])

    updated = load_chat("user1", "abc12345")

    assert first is not None
    assert updated is not None
    assert updated["created_at"] == first["created_at"]
    assert updated["updated_at"] >= first["updated_at"]


def test_list_user_chats_returns_sorted_without_messages() -> None:
    save_chat("user1", "oldchat1", [{"role": "user", "content": "오래된 질의"}])
    time.sleep(0.01)
    save_chat("user1", "newchat1", [{"role": "user", "content": "최신 질의"}])

    chat_list = list_user_chats("user1")

    assert [chat["chat_id"] for chat in chat_list] == ["newchat1", "oldchat1"]
    assert "messages" not in chat_list[0]


def test_delete_chat_removes_file() -> None:
    save_chat("user1", "abc12345", _make_messages())

    assert delete_chat("user1", "abc12345") is True
    assert load_chat("user1", "abc12345") is None
    assert delete_chat("user1", "abc12345") is False


def test_rename_chat_updates_title_and_truncates() -> None:
    save_chat("user1", "abc12345", _make_messages())
    long_title = "가" * 50

    assert rename_chat("user1", "abc12345", long_title) is True

    renamed = load_chat("user1", "abc12345")
    assert renamed is not None
    assert renamed["title"] == "가" * 40
    assert rename_chat("user1", "missing1", "새 제목") is False


def test_load_chat_returns_none_for_missing_or_broken_file(tmp_path, monkeypatch) -> None:
    import src.ui.chat_store as chat_store

    chat_root = tmp_path / "chat_history"
    monkeypatch.setattr(chat_store, "CHAT_HISTORY_DIR", chat_root)
    broken_dir = chat_root / "user1"
    broken_dir.mkdir(parents=True)
    (broken_dir / "broken.json").write_text("{broken", encoding="utf-8")

    assert load_chat("user1", "missing") is None
    assert load_chat("user1", "broken") is None
    assert list_user_chats("user1") == []


def test_auto_title_uses_first_user_message_with_newline_replaced(tmp_path, monkeypatch) -> None:
    import src.ui.chat_store as chat_store

    monkeypatch.setattr(chat_store, "CHAT_HISTORY_DIR", tmp_path / "chat_history")
    save_chat("user1", "abc12345", [{"role": "user", "content": "첫 줄\n둘째 줄"}])

    raw = json.loads((tmp_path / "chat_history" / "user1" / "abc12345.json").read_text(encoding="utf-8"))
    assert raw["title"] == "첫 줄 둘째 줄"
