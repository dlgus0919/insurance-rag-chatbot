from __future__ import annotations

from typing import Any

from src.api.routes import chat, sessions


_FORBIDDEN_KEYS = {
    "__kind",
    "chunk_id",
    "source_chunk_ids",
    "evidence_chunk_ids",
    "session_assertions",
    "provenance",
    "operation_path",
    "filesystem_path",
    "conversation_state",
    "graph_result",
    "claim_snapshot",
    "turn",
}


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _nested_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _nested_keys(item)}
    return set()


def test_public_payloads_allow_only_display_fields_at_all_boundaries() -> None:
    sources = [
        {
            "filename": "/srv/private/policy.pdf",
            "doc_short": "실손약관",
            "page": 12,
            "page_end": 13,
            "snippet": "사용자에게 표시할 근거 문장",
            "chunk_id": "chunk-private",
            "source_chunk_ids": ["chunk-private"],
            "nested": {"provenance": {"filesystem_path": "/srv/private"}},
        },
        {
            "__kind": "claim_snapshot",
            "conversation_state": {"session_assertions": ["private"]},
        },
    ]
    graph_payload = {
        "plan": {
            "clarification_questions": ["확인 질문"],
            "source_chunk_ids": ["chunk-private"],
            "provenance": {"operation_path": "private"},
        },
        "facts": [
            {
                "subject": "보장",
                "relation": "HAS_CONDITION",
                "object": "조건",
                "evidence": [
                    {
                        "doc_short": "실손약관",
                        "page_start": 12,
                        "chunk_id": "chunk-private",
                    }
                ],
            }
        ],
        "clarification": {
            "pending_slots": [
                {
                    "slot_id": "condition-a",
                    "question": "확인 질문",
                    "allowed_values": ["yes", "no"],
                    "evidence_chunk_ids": ["chunk-private"],
                }
            ],
            "session_assertions": ["private"],
        },
        "source_chunk_ids": ["chunk-private"],
        "provenance": {"filesystem_path": "/srv/private"},
    }
    assistant_sources = sources + [
        {
            "__kind": "assistant_meta",
            "graph_result": graph_payload,
            "warnings": [
                {
                    "code": "REVIEW",
                    "message": "표시용 경고",
                    "provenance": {"operation_path": "private"},
                }
            ],
        }
    ]

    expected_sources = [
        {
            "filename": "policy.pdf",
            "doc_short": "실손약관",
            "page": 12,
            "page_end": 13,
            "snippet": "사용자에게 표시할 근거 문장",
        }
    ]
    assert chat._public_sources(sources) == expected_sources
    assert sessions._public_sources(sources) == expected_sources

    public_graph = chat._public_graph_payload(graph_payload)
    assert public_graph is not None
    assert not (_nested_keys(public_graph) & _FORBIDDEN_KEYS)

    export_meta = sessions._public_export_meta(assistant_sources)
    assert not (_nested_keys(export_meta) & _FORBIDDEN_KEYS)
    assert export_meta["warnings"] == [{"code": "REVIEW", "message": "표시용 경고"}]
