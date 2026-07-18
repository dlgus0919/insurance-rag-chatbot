"""Ontology registry helpers shared by retrieval, graph planning, and graph build."""

from src.ontology.registry import (
    ACTIVE_ONTOLOGY_MANIFEST,
    ACTIVE_ONTOLOGY_PROVENANCE,
    BASE_ONTOLOGY_MANIFEST,
    BASE_ONTOLOGY_LOCK,
    ConceptMatch,
    OntologyConcept,
    OntologyRegistry,
    get_default_ontology_registry,
    resolve_default_ontology_manifest,
)

__all__ = [
    "ACTIVE_ONTOLOGY_MANIFEST",
    "ACTIVE_ONTOLOGY_PROVENANCE",
    "BASE_ONTOLOGY_MANIFEST",
    "BASE_ONTOLOGY_LOCK",
    "ConceptMatch",
    "OntologyConcept",
    "OntologyRegistry",
    "get_default_ontology_registry",
    "resolve_default_ontology_manifest",
]
