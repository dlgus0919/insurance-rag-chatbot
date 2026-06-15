import json

from src.ontology.llm_enrichment import (
    build_enrichment_input,
    build_enrichment_prompt,
    enrich_candidate_with_llm,
    is_unsafe_approval,
    parse_enrichment_response,
    summarize_enrichment_rows,
    template_enrichment,
    validate_enrichment_output,
)
from src.ontology.review_store import HELD, OntologyCandidate
from scripts.eval_ontology_llm_enrichment import evaluate_expected_enrichment


def _candidate(**kwargs) -> OntologyCandidate:
    base = {
        "candidate_id": "dev.cov.manual_therapy.demo",
        "concept_id": "cov.manual_therapy",
        "canonical_name": "도수치료",
        "node_type": "CoverageConcept",
        "aliases": ["도수치료"],
        "candidate_aliases": ["즉 비급여 도수치료"],
        "source_evidence": [{"doc_short": "약관", "page": "38", "excerpt": "즉 비급여 도수치료 관련 조항"}],
        "status": "pending",
        "properties": {"display": {"summary": "도수치료 관련 표현 후보입니다."}},
    }
    base.update(kwargs)
    return OntologyCandidate(**base)


def test_build_enrichment_input_reports_alias_conflicts():
    candidate = _candidate(candidate_aliases=["비급여 주사제"])
    other = _candidate(
        candidate_id="dev.cov.nonpay_injection.demo",
        concept_id="cov.nonpay_injection",
        canonical_name="비급여 주사료",
        candidate_aliases=["비급여 주사제"],
    )

    payload = build_enrichment_input(candidate, all_candidates=[candidate, other])

    assert payload["target"]["concept_id"] == "cov.manual_therapy"
    assert payload["known_conflicts"][0]["other_concept_id"] == "cov.nonpay_injection"


def test_parse_enrichment_response_falls_back_to_hold_for_invalid_json():
    result = parse_enrichment_response("not json")

    assert result.json_valid is False
    assert result.schema_valid is False
    assert result.payload["overall_decision"] == "hold"
    assert result.payload["risk_level"] == "high"
    assert result.payload["alias_assessments"][0]["reason_codes"] == ["schema_uncertain"]


def test_validate_enrichment_output_maps_common_reason_code_aliases():
    payload = {
        "overall_decision": "reject",
        "domain_fit": True,
        "evidence_fit": False,
        "risk_level": "high",
        "confidence": 0.8,
        "alias_assessments": [
            {
                "expression": "보험금 지급여부",
                "decision": "reject",
                "reason_codes": ["risk_term_guardrail"],
                "reason": "지급 판단 표현입니다.",
                "suggested_rewrite": "",
            }
        ],
        "refined_aliases": [],
        "practitioner_summary": "보류",
        "example_questions": [],
        "review_notes": "",
    }

    normalized, errors = validate_enrichment_output(payload)

    assert errors == []
    assert normalized["alias_assessments"][0]["reason_codes"] == ["policy_risk"]


def test_template_enrichment_flags_sentence_fragment_alias():
    candidate = _candidate(candidate_aliases=["즉 비급여 도수치료"])

    payload = template_enrichment(candidate, all_candidates=[candidate])

    assert payload["overall_decision"] == "hold"
    assert payload["alias_assessments"][0]["decision"] == "reject"
    assert "sentence_fragment" in payload["alias_assessments"][0]["reason_codes"]


def test_llm_enrichment_uses_json_schema_prompt_and_client():
    class FakeClient:
        def __init__(self):
            self.prompt = ""
            self.system = ""

        def generate(self, prompt, system="", temperature=0.0, num_ctx=None, reasoning_mode="off"):
            self.prompt = prompt
            self.system = system
            return json.dumps(
                {
                    "schema_version": 1,
                    "overall_decision": "approve",
                    "domain_fit": True,
                    "evidence_fit": True,
                    "risk_level": "low",
                    "confidence": 0.9,
                    "alias_assessments": [
                        {
                            "expression": "도수치료",
                            "decision": "approve",
                            "reason_codes": ["safe_alias"],
                            "reason": "동일 개념입니다.",
                            "suggested_rewrite": "",
                        }
                    ],
                    "refined_aliases": ["도수치료"],
                    "practitioner_summary": "도수치료 alias입니다.",
                    "example_questions": ["도수치료는 보상되나요?"],
                    "review_notes": "",
                },
                ensure_ascii=False,
            )

    client = FakeClient()
    candidate = _candidate(candidate_aliases=["도수치료"])

    result = enrich_candidate_with_llm(candidate, client, all_candidates=[candidate])

    assert result.payload["overall_decision"] == "approve"
    assert result.schema_valid is True
    assert "출력 schema" in client.prompt
    assert "보험 도메인 온톨로지 후보 검토" in client.system


def test_unsafe_approval_detects_conflicting_or_high_risk_output():
    candidate = _candidate(candidate_aliases=["즉 비급여 도수치료"])
    payload = {
        "overall_decision": "approve",
        "domain_fit": True,
        "evidence_fit": True,
        "risk_level": "low",
        "alias_assessments": [{"reason_codes": ["safe_alias"]}],
    }

    assert is_unsafe_approval(candidate, payload) is True


def test_summary_counts_status_regressions():
    rows = [
        {
            "model": "sglang:qwen3-30b-a3b-instruct-2507-fp8",
            "candidate_status": HELD,
            "overall_decision": "approve",
            "json_valid": True,
            "schema_valid": True,
            "unsafe_approval": True,
            "has_expected_enrichment": True,
            "expected_checks_ok": False,
        }
    ]

    summary = summarize_enrichment_rows(rows)

    item = summary["sglang:qwen3-30b-a3b-instruct-2507-fp8"]
    assert item["unsafe_approval_count"] == 1
    assert item["held_as_approve"] == 1
    assert item["json_validity"] == 1.0
    assert item["expected_total"] == 1
    assert item["expected_pass"] == 0


def test_build_enrichment_prompt_contains_candidate_payload():
    prompt = build_enrichment_prompt(build_enrichment_input(_candidate(), all_candidates=[]))

    assert "dev.cov.manual_therapy.demo" in prompt
    assert "candidate_aliases" in prompt
    assert "reason_codes는 반드시" in prompt
    assert "ownership_conflict" in prompt


def test_evaluate_expected_enrichment_checks_expected_and_forbidden_decisions():
    candidate = _candidate(
        properties={
            "expected_enrichment": {
                "expected_decisions": ["reject", "hold"],
                "forbidden_decisions": ["approve"],
                "required_reason_codes": ["policy_risk"],
            }
        }
    )
    payload = {
        "overall_decision": "reject",
        "alias_assessments": [{"reason_codes": ["policy_risk"]}],
    }

    result = evaluate_expected_enrichment(candidate, payload)

    assert result["has_expected_enrichment"] is True
    assert result["expected_checks_ok"] is True
    assert result["emitted_reason_codes"] == ["policy_risk"]
