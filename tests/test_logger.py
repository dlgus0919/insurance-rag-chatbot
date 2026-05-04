import json
import logging

from src.utils import logger as audit_logger


def test_log_event_writes_jsonl_record(tmp_path, monkeypatch) -> None:
    logger = logging.getLogger("rag_chat_audit")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    monkeypatch.setattr(audit_logger, "LOG_DIR", tmp_path)

    audit_logger.log_event("TEST_EVENT", "session-1", {"질문": "AA157"})

    for handler in logger.handlers:
        handler.flush()

    log_files = list(tmp_path.glob("chat_*.jsonl"))
    assert len(log_files) == 1

    record = json.loads(log_files[0].read_text(encoding="utf-8").strip())
    assert record["event"] == "TEST_EVENT"
    assert record["session_id"] == "session-1"
    assert record["details"] == {"질문": "AA157"}
    assert "timestamp" in record

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
