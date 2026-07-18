from __future__ import annotations

import json

from scripts.extract_claim_rule_candidates import extract_fourth_manual_therapy_candidates
from src.claim_calculation.rule_candidate_evidence import load_rule_candidate_evidence_spec


def test_manual_therapy_candidate_extractor_uses_versioned_evidence_spec(tmp_path) -> None:
    spec_path = tmp_path / "evidence_specs.json"
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "review_specs": [
                    {
                        "scope": "custom-manual-therapy",
                        "generation": "4th",
                        "generation_label": "4세대",
                        "category": "3대비급여_도수",
                        "treatment_label": "도수치료군",
                        "rule_id_template": "deductible.{generation}.three_major_manual.{visit_type}",
                        "candidate_id_template": "rulecand.add.{rule_id}",
                        "description_template": "{generation_label} {treatment_label}: 1회당 {minimum_won}원과 보장대상의료비 {copay_percent}% 중 큰 금액, 연 {annual_limit_won}원·{annual_visit_limit}회",
                        "extraction_reason": "원문 근거에서 분리 추출",
                        "primary_chunk_id": "custom-primary",
                        "supporting_chunk_ids": [
                            "custom-support-1",
                            "custom-support-2"
                        ],
                        "primary_required_terms": [
                            "치료A",
                            "치료B",
                            "치료C"
                        ],
                        "visit_types": [
                            "hospitalization",
                            "outpatient"
                        ],
                        "review_requirements": [
                            {
                                "required_all": [
                                    "최초",
                                    "10회"
                                ],
                                "required_any": [
                                    "호전",
                                    "증상"
                                ],
                                "message": "최초 10회 이후 증상 호전 증빙 확인 필요"
                            },
                            {
                                "required_all": [
                                    "1회"
                                ],
                                "required_any": [
                                    "동일",
                                    "당일"
                                ],
                                "message": "동일 방문 복수 치료 횟수 확인 필요"
                            }
                        ]
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    evidence_spec = load_rule_candidate_evidence_spec("custom-manual-therapy", spec_path)
    chunks = [
        {
            "text": "치료A 치료B 치료C는 보장대상의료비의 30%와 3만원 중 큰 금액을 공제합니다.",
            "doc_short": "테스트약관",
            "chunk_id": "custom-primary",
            "page": 1,
            "article": "제1조",
        },
        {
            "text": "최초 10회부터 증상 호전 증빙이 필요하며 연간 350만원, 50회를 한도로 합니다.",
            "doc_short": "테스트약관",
            "chunk_id": "custom-support-1",
            "page": 2,
            "article": "제2조",
        },
        {
            "text": "동일한 날 여러 번 시행한 치료는 1회로 봅니다.",
            "doc_short": "테스트약관",
            "chunk_id": "custom-support-2",
            "page": 3,
            "article": "제3조",
        },
    ]

    candidates = extract_fourth_manual_therapy_candidates(chunks, evidence_spec=evidence_spec)

    assert {candidate["proposed_rule"]["rule_id"] for candidate in candidates} == {
        "deductible.4th.three_major_manual.hospitalization",
        "deductible.4th.three_major_manual.outpatient",
    }
    assert all(candidate["status"] == "pending" for candidate in candidates)
    assert all(candidate["proposed_rule"]["source_chunk_id"] == "custom-primary" for candidate in candidates)
    assert all(candidate["proposed_rule"]["annual_limit"] == "3500000" for candidate in candidates)
