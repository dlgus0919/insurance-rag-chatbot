import csv
import io
import json
from datetime import datetime, timezone

from src.ui.admin_page import _compute_stats, _filter_events, _logs_to_csv, _read_logs


def _write_event(path, event: str, user_id: str, role: str = "employee", **details) -> None:
    record = {
        "timestamp": datetime(2026, 5, 6, 1, 0, tzinfo=timezone.utc).isoformat(),
        "event": event,
        "session_id": "sess",
        "details": {"user_id": user_id, "role": role, **details},
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_read_logs_filters_by_date_and_skips_bad_lines(tmp_path) -> None:
    log_file = tmp_path / "chat_2026-05-06.jsonl"
    _write_event(log_file, "QUESTION", "admin", mode="general")
    log_file.write_text(log_file.read_text(encoding="utf-8") + "{bad json\n", encoding="utf-8")

    events = _read_logs(
        datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 6, 23, 59, tzinfo=timezone.utc),
        log_dir=tmp_path,
    )

    assert len(events) == 1
    assert events[0]["event"] == "QUESTION"


def test_filter_events_by_user_and_event_type() -> None:
    events = [
        {"event": "QUESTION", "details": {"user_id": "admin"}},
        {"event": "ANSWER", "details": {"user_id": "employee01"}},
    ]

    assert _filter_events(events, user_filter=["admin"], event_types=["QUESTION"]) == [events[0]]


def test_logs_to_csv_contains_expected_columns() -> None:
    events = [
        {
            "timestamp": "2026-05-06T00:00:00+00:00",
            "event": "QUESTION",
            "session_id": "sess",
            "details": {"user_id": "admin", "role": "admin", "question": "AA157"},
        }
    ]

    rows = list(csv.reader(io.StringIO(_logs_to_csv(events))))

    assert rows[0] == ["timestamp", "event", "session_id", "user_id", "role", "details"]
    assert rows[1][:5] == ["2026-05-06T00:00:00+00:00", "QUESTION", "sess", "admin", "admin"]
    assert "AA157" in rows[1][5]


def test_compute_stats_groups_questions_and_answers() -> None:
    events = [
        {"event": "QUESTION", "details": {"user_id": "admin", "mode": "general"}},
        {"event": "QUESTION", "details": {"user_id": "admin", "mode": "quick_code"}},
        {"event": "ANSWER", "details": {"model": "gemma3:4b", "timing": {"total_ms": 2000}}},
    ]

    stats = _compute_stats(events)

    assert stats["question_count"] == 2
    assert stats["answer_count"] == 1
    assert stats["avg_total_sec"] == 2
    assert stats["by_user"] == {"admin": 2}
    assert stats["by_mode"] == {"general": 1, "quick_code": 1}
    assert stats["by_model"] == {"gemma3:4b": 1}
