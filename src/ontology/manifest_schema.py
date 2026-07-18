"""Fail-closed schema validation for ontology runtime artifacts.

This module deliberately depends only on JSON Schema primitives so both merge
and runtime readers can share the same validation boundary without an import
cycle through the registry or review store.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ONTOLOGY_MANIFEST_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "ontology"
    / "ontology_manifest.schema.json"
)

_NON_EMPTY_STRING = {"type": "string", "minLength": 1}

ACTIVE_PROVENANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "schema_version",
        "generated_at",
        "base_lock",
        "trusted_base_content_hash",
        "active_content_hash",
        "quarantined_concept_ids",
        "integrity_issues",
        "applied_operations",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "generated_at": _NON_EMPTY_STRING,
        "base_lock": {
            "type": "object",
            "required": [
                "schema_version",
                "manifest_content_hash",
                "concept_hashes",
                "source_commit",
                "review_record_id",
            ],
            "additionalProperties": False,
            "properties": {
                "schema_version": {"const": 1},
                "manifest_content_hash": _NON_EMPTY_STRING,
                "concept_hashes": {
                    "type": "object",
                    "minProperties": 1,
                    "propertyNames": _NON_EMPTY_STRING,
                    "additionalProperties": _NON_EMPTY_STRING,
                },
                "source_commit": _NON_EMPTY_STRING,
                "review_record_id": _NON_EMPTY_STRING,
            },
        },
        "trusted_base_content_hash": _NON_EMPTY_STRING,
        "active_content_hash": _NON_EMPTY_STRING,
        "quarantined_concept_ids": {
            "type": "array",
            "items": _NON_EMPTY_STRING,
            "uniqueItems": True,
        },
        "integrity_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "concept_id", "path", "message"],
                "additionalProperties": False,
                "properties": {
                    "code": _NON_EMPTY_STRING,
                    "concept_id": {"type": "string"},
                    "path": _NON_EMPTY_STRING,
                    "message": _NON_EMPTY_STRING,
                },
            },
        },
        "applied_operations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "candidate_id",
                    "candidate_payload_hash",
                    "approval_patch_hash",
                    "operation",
                    "path",
                    "value_hash",
                ],
                "additionalProperties": False,
                "properties": {
                    "candidate_id": _NON_EMPTY_STRING,
                    "candidate_payload_hash": _NON_EMPTY_STRING,
                    "approval_patch_hash": _NON_EMPTY_STRING,
                    "operation": {"enum": ["add", "replace", "remove"]},
                    "path": _NON_EMPTY_STRING,
                    "value_hash": _NON_EMPTY_STRING,
                },
            },
        },
    },
}


def _raise_first_schema_error(
    validator: Draft202012Validator,
    payload: Any,
    *,
    artifact: str,
) -> None:
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    first = errors[0]
    path = "/".join(str(part) for part in first.absolute_path) or artifact
    raise ValueError(f"{artifact} schema validation failed at {path}: {first.message}")


@lru_cache(maxsize=1)
def ontology_manifest_validator() -> Draft202012Validator:
    with ONTOLOGY_MANIFEST_SCHEMA_PATH.open(encoding="utf-8") as file:
        schema = json.load(file)
    if not isinstance(schema, dict):
        raise ValueError("ontology manifest schema must be an object")
    return Draft202012Validator(schema)


@lru_cache(maxsize=1)
def active_provenance_validator() -> Draft202012Validator:
    return Draft202012Validator(ACTIVE_PROVENANCE_SCHEMA)


def validate_ontology_manifest_schema(payload: Any) -> None:
    _raise_first_schema_error(
        ontology_manifest_validator(),
        payload,
        artifact="ontology manifest",
    )


def validate_active_provenance_schema(payload: Any) -> None:
    _raise_first_schema_error(
        active_provenance_validator(),
        payload,
        artifact="active provenance",
    )
