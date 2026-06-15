from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.graph.normalizer import normalize_name
from src.ontology.candidate_display import build_display_metadata, unique_strings
from src.ontology.candidate_reviewer import build_codex_dev_review, has_target_overlap
from src.ontology.hold_feedback import held_alias_blocklist, held_review_hints
from src.ontology.policy import CandidateExtractionPolicy, OntologyReviewPolicy, load_candidate_extraction_policy, load_review_policy
from src.ontology.registry import BASE_ONTOLOGY_MANIFEST
from src.ontology.review_store import OntologyCandidate, utc_now_iso


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OntologySourceConcept:
    concept_id: str
    canonical_name: str
    node_type: str
    aliases: tuple[str, ...]
    candidate_aliases: tuple[str, ...]
    evidence_tags: tuple[str, ...]
    planner: dict[str, Any]
    retrieval: dict[str, Any]

    @property
    def all_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.canonical_name, *self.aliases, *self.candidate_aliases)))


@dataclass(frozen=True)
class CandidateExtractionResult:
    candidates: list[OntologyCandidate]
    source_count: int
    warnings: list[str] = field(default_factory=list)


def load_manifest_concepts(path: str | Path = BASE_ONTOLOGY_MANIFEST) -> list[OntologySourceConcept]:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    concepts: list[OntologySourceConcept] = []
    for item in payload.get("concepts", []):
        if not isinstance(item, dict):
            continue
        concepts.append(
            OntologySourceConcept(
                concept_id=str(item.get("concept_id") or "").strip(),
                canonical_name=str(item.get("canonical_name") or "").strip(),
                node_type=str(item.get("node_type") or "").strip(),
                aliases=tuple(_string_list(item.get("aliases"))),
                candidate_aliases=tuple(_string_list(item.get("candidate_aliases"))),
                evidence_tags=tuple(_string_list(item.get("evidence_tags"))),
                planner=dict(item.get("planner") or {}),
                retrieval=dict(item.get("retrieval") or {}),
            )
        )
    return [concept for concept in concepts if concept.concept_id and concept.canonical_name]


def load_processed_chunks(paths: Iterable[str | Path], *, limit: int | None = None) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if not text:
                    continue
                row = json.loads(text)
                if not isinstance(row, dict):
                    continue
                chunk_text = str(row.get("text") or row.get("row_text") or "").strip()
                if not chunk_text:
                    continue
                metadata = dict(row.get("metadata") or {})
                chunk_id = str(row.get("id") or row.get("chunk_id") or metadata.get("chunk_id") or "").strip()
                chunks.append(SourceChunk(chunk_id=chunk_id or f"{path.name}:{len(chunks)}", text=chunk_text, metadata=metadata))
                if limit is not None and len(chunks) >= limit:
                    return chunks
    return chunks


def load_graph_evidence(path: str | Path, *, limit: int | None = None) -> list[SourceChunk]:
    db_path = Path(path)
    if not db_path.exists():
        return []
    chunks: list[SourceChunk] = []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in con.execute("pragma table_info(graph_evidence)").fetchall()}
        if not columns:
            return []
        select_columns = [
            "evidence_id",
            "chunk_id",
            "doc_short",
            "doc_name",
            "page_start",
            "page_end",
            "row_text",
            "metadata_json",
            "confidence",
        ]
        available = [column for column in select_columns if column in columns]
        sql = f"select {', '.join(available)} from graph_evidence"
        if limit is not None:
            sql += f" limit {int(limit)}"
        for row in con.execute(sql):
            row_dict = dict(row)
            text = str(row_dict.get("row_text") or "").strip()
            if not text:
                continue
            metadata = {
                "doc_short": row_dict.get("doc_short"),
                "doc_name": row_dict.get("doc_name"),
                "page_start": row_dict.get("page_start"),
                "page_end": row_dict.get("page_end"),
                "confidence": row_dict.get("confidence"),
            }
            chunks.append(
                SourceChunk(
                    chunk_id=str(row_dict.get("chunk_id") or row_dict.get("evidence_id") or f"graph:{len(chunks)}"),
                    text=text,
                    metadata=metadata,
                )
            )
    finally:
        con.close()
    return chunks


def extract_reinforcement_candidates(
    *,
    concepts: list[OntologySourceConcept],
    chunks: list[SourceChunk],
    extraction_run_id: str | None = None,
    candidate_limit: int | None = None,
    candidate_type: str | None = None,
    extraction_policy: CandidateExtractionPolicy | None = None,
    review_policy: OntologyReviewPolicy | None = None,
    previous_review_candidates: list[OntologyCandidate] | None = None,
) -> CandidateExtractionResult:
    policy = extraction_policy or load_candidate_extraction_policy()
    dev_review_policy = review_policy or load_review_policy()
    reinforcement_type = candidate_type or policy.default_reinforcement_type
    run_id = extraction_run_id or f"ontology-candidate-extract-{utc_now_iso()}"
    existing_terms = _normalized_existing_terms(concepts)
    prior_candidates = previous_review_candidates or []
    blocked_aliases_by_concept = held_alias_blocklist(prior_candidates)
    hold_hints_by_concept = held_review_hints(prior_candidates)
    grouped_terms: dict[str, list[str]] = {}
    grouped_evidence: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []

    for chunk in chunks:
        text = _clean_text(chunk.text)
        if not text:
            continue
        if _looks_like_index_or_code_table(text, policy):
            continue
        normalized_text = normalize_name(text)
        if not normalized_text:
            continue
        for concept in concepts:
            contexts = _matching_contexts(concept, text, normalized_text, policy=policy)
            if not contexts:
                continue
            terms = [
                term
                for context in contexts
                for term in extract_candidate_terms(context, policy=policy)
                if _is_new_term(term, existing_terms)
            ]
            if not terms:
                continue
            grouped_terms.setdefault(concept.concept_id, [])
            grouped_terms[concept.concept_id].extend(terms)
            grouped_evidence.setdefault(concept.concept_id, [])
            grouped_evidence[concept.concept_id].append(_source_evidence(chunk, terms[0]))

    concept_by_id = {concept.concept_id: concept for concept in concepts}
    candidates: list[OntologyCandidate] = []
    for concept_id, raw_terms in grouped_terms.items():
        concept = concept_by_id[concept_id]
        terms = [
            term
            for term in unique_strings(raw_terms, limit=8)
            if has_target_overlap(term, list(concept.all_terms))
            and normalize_name(term) not in blocked_aliases_by_concept.get(concept_id, set())
        ]
        evidence = _dedupe_evidence(grouped_evidence.get(concept_id, []), limit=3)
        if not terms or not evidence:
            continue
        review = build_codex_dev_review(
            candidate_type=reinforcement_type,
            source_evidence=evidence,
            similar_expressions=terms,
            target_terms=list(concept.all_terms),
            policy=dev_review_policy,
        )
        risk_flags = ["dev_auto_approval"] if review["decision"] == "approve" else ["requires_practitioner_review"]
        properties = {
            "candidate_type": reinforcement_type,
            "target_concept_id": concept.concept_id,
            "target_canonical_name": concept.canonical_name,
            "display": build_display_metadata(
                canonical_name=concept.canonical_name,
                node_type=concept.node_type,
                candidate_type=reinforcement_type,
                similar_expressions=terms,
                source_evidence=evidence,
            ),
            "codex_dev_review": review,
            "extraction": {
                "source": "processed_chunks_or_graph_evidence",
                "term_count": len(terms),
                "policy_id": policy.policy_id,
                "policy_version": policy.version,
            },
        }
        prior_hold_feedback = hold_hints_by_concept.get(concept.concept_id, [])
        if prior_hold_feedback:
            properties["extraction"]["prior_hold_feedback"] = prior_hold_feedback[:5]
        candidates.append(
            OntologyCandidate(
                candidate_id=_candidate_id(concept.concept_id, terms),
                concept_id=concept.concept_id,
                canonical_name=concept.canonical_name,
                node_type=concept.node_type,
                candidate_aliases=terms,
                evidence_tags=_candidate_evidence_tags(concept, terms),
                planner=_copy_planner(concept.planner),
                retrieval={
                    "expansion_rules": [
                        {
                            "match_any": [concept.canonical_name, *list(concept.aliases)[:3]],
                            "expansion_terms": terms,
                        }
                    ]
                },
                properties=properties,
                source_evidence=evidence,
                risk_flags=risk_flags,
                test_candidate=False,
                extraction_run_id=run_id,
            )
        )
        if candidate_limit is not None and len(candidates) >= candidate_limit:
            break

    if not candidates:
        warnings.append("no ontology reinforcement candidates were generated")
    return CandidateExtractionResult(candidates=candidates, source_count=len(chunks), warnings=warnings)


def extract_candidate_terms(text: str, policy: CandidateExtractionPolicy | None = None) -> list[str]:
    extraction_policy = policy or load_candidate_extraction_policy()
    cleaned = _clean_text(text)
    terms: list[str] = []
    terms.extend(_parenthetical_terms(cleaned))
    terms.extend(_delimited_terms(cleaned))
    terms.extend(_keyword_phrases(cleaned, extraction_policy))
    normalized_terms = [_normalize_candidate_term(term) for term in terms]
    return [term for term in unique_strings(normalized_terms, limit=24) if _candidate_term_allowed(term, extraction_policy)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return unique_strings([str(item) for item in value])


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalized_existing_terms(concepts: list[OntologySourceConcept]) -> set[str]:
    result: set[str] = set()
    for concept in concepts:
        for term in concept.all_terms:
            normalized = normalize_name(term)
            if normalized:
                result.add(normalized)
    return result


def _matching_contexts(
    concept: OntologySourceConcept,
    text: str,
    normalized_text: str,
    *,
    policy: CandidateExtractionPolicy,
    radius: int = 180,
) -> list[str]:
    contexts: list[str] = []
    for term in concept.all_terms:
        if len(term.strip()) < 2 or term in policy.stop_phrases:
            continue
        if term and term in text:
            index = text.find(term)
            contexts.append(text[max(index - radius, 0) : min(index + len(term) + radius, len(text))])
            continue
        normalized = normalize_name(term)
        if normalized and len(normalized) >= 2 and normalized in normalized_text:
            index = normalized_text.find(normalized)
            contexts.append(text[max(index - radius, 0) : min(index + len(term) + radius, len(text))])
    return unique_strings(contexts, limit=3)


def _is_new_term(term: str, existing_terms: set[str]) -> bool:
    normalized = normalize_name(term)
    return bool(normalized and normalized not in existing_terms)


def _candidate_term_allowed(term: str, policy: CandidateExtractionPolicy) -> bool:
    shape = policy.expression_shape
    text = _clean_text(term).strip(" -:;,.()[]{}")
    if len(text) < shape.min_length or len(text) > shape.max_length:
        return False
    if text in policy.stop_phrases:
        return False
    if any(generic in text for generic in policy.generic_table_terms):
        return False
    if any(fragment in text for fragment in policy.noise_fragments):
        return False
    if re.search(r"제\s*\d+\s*(장|절|편|부)", text):
        return False
    if not shape.allow_digits and any(char.isdigit() for char in text):
        return False
    if not shape.allow_ascii_letters and any("A" <= char <= "Z" or "a" <= char <= "z" for char in text):
        return False
    if len(text.split()) > shape.max_terms:
        return False
    if not any(keyword in text for keyword in policy.domain_keywords):
        return False
    if re.fullmatch(r"[\d\s.,%-]+", text):
        return False
    return True


def _normalize_candidate_term(term: str) -> str:
    text = _clean_text(term).strip(" -:;,.()[]{}")
    for marker in ("와 관련", "과 관련", "에 관한", "에서 확인", "검토에서"):
        if marker in text:
            text = text.split(marker, 1)[0]
    for marker in ("은 ", "는 ", "이 ", "가 ", "을 ", "를 "):
        if marker in text:
            right = text.rsplit(marker, 1)[1].strip()
            if len(right) >= 2:
                text = right
    return text.strip(" -:;,.()[]{}")


def _looks_like_index_or_code_table(text: str, policy: CandidateExtractionPolicy) -> bool:
    if "····" in text:
        return True
    if "분류번호" in text and "점 수" in text:
        return True
    if text.count("제") >= 8 and any(term in text for term in policy.table_noise_markers):
        return True
    return False


def _parenthetical_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in re.finditer(r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s·ㆍ/\-]{1,30})\(([^()]{2,40})\)", text):
        terms.append(match.group(1))
        terms.append(match.group(2))
    return terms


def _delimited_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in re.finditer(r"([가-힣A-Za-z0-9\s]{2,30}(?:/|·|ㆍ|,| 또는 | 및 )[가-힣A-Za-z0-9\s]{2,30})", text):
        for part in re.split(r"/|·|ㆍ|,| 또는 | 및 ", match.group(1)):
            terms.append(part)
    return terms


def _keyword_phrases(text: str, policy: CandidateExtractionPolicy) -> list[str]:
    terms: list[str] = []
    for keyword in policy.domain_keywords:
        for match in re.finditer(rf"([가-힣A-Za-z0-9\s]{{0,14}}{re.escape(keyword)}[가-힣A-Za-z0-9\s]{{0,14}})", text):
            phrase = _clean_text(match.group(1))
            if phrase:
                terms.append(phrase)
    return terms


def _source_evidence(chunk: SourceChunk, matched_term: str) -> dict[str, Any]:
    metadata = chunk.metadata
    page = metadata.get("page_start") or metadata.get("page") or metadata.get("page_end")
    return {
        "doc_short": metadata.get("doc_short") or metadata.get("doc_name") or "원천자료",
        "doc_name": metadata.get("doc_name") or metadata.get("pdf_filename") or "",
        "page": page,
        "chunk_id": chunk.chunk_id,
        "excerpt": _excerpt_around(chunk.text, matched_term),
        "confidence": metadata.get("confidence") or 0.7,
    }


def _excerpt_around(text: str, term: str, *, radius: int = 90) -> str:
    cleaned = _clean_text(text)
    index = cleaned.find(term)
    if index < 0:
        return cleaned[: radius * 2]
    start = max(index - radius, 0)
    end = min(index + len(term) + radius, len(cleaned))
    return cleaned[start:end]


def _dedupe_evidence(evidence_rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in evidence_rows:
        key = str(row.get("chunk_id") or row.get("excerpt") or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= limit:
            break
    return result


def _candidate_evidence_tags(concept: OntologySourceConcept, terms: list[str]) -> list[str]:
    tags = list(concept.evidence_tags)
    for term in terms[:3]:
        normalized = normalize_name(term)
        if normalized:
            tags.append(f"candidate:{normalized[:32]}")
    return unique_strings(tags, limit=8)


def _copy_planner(planner: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, value in planner.items():
        if isinstance(value, list):
            copied[key] = unique_strings([str(item) for item in value])
    return copied


def _candidate_id(concept_id: str, terms: list[str]) -> str:
    digest = hashlib.sha1("|".join([concept_id, *terms]).encode("utf-8")).hexdigest()[:12]
    safe_concept = re.sub(r"[^A-Za-z0-9_.-]+", "_", concept_id).strip("._-") or "concept"
    return f"dev.{safe_concept}.{digest}"
