from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PUBLIC_DOCS = (
    "000_PROJECT_DEVELOPMENT_GUARDRAILS.md",
    "INSURANCE_PROJECT_RETROSPECTIVE.md",
)


def test_public_docs_match_the_approved_allowlist() -> None:
    actual = sorted(str(path.relative_to(DOCS)) for path in DOCS.rglob("*") if path.is_file())
    assert actual == sorted(PUBLIC_DOCS)


def test_public_docs_have_expected_titles() -> None:
    guardrails = (DOCS / PUBLIC_DOCS[0]).read_text(encoding="utf-8")
    retrospective = (DOCS / PUBLIC_DOCS[1]).read_text(encoding="utf-8")

    assert guardrails.startswith("# 000. Project Development Guardrails")
    assert retrospective.startswith("# 보험 문서 기반 보상지원 AI 프로젝트 회고 및 실무 인수 문서")
