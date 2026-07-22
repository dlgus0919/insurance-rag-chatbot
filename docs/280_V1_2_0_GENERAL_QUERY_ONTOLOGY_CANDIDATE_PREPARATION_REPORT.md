# 280. v1.2.0 일반 질의 온톨로지 후보·근거 준비 보고서

## 목적과 범위

이 문서는 v1.2.0 온톨로지 재구축 전에 실무자가 직접 판단할 수 있도록 만든 **준비 전용** 후보·근거 패키지입니다. 이 작업에서는 후보의 승인·보류·거절, active manifest 적용, GraphDB 재구축, 인덱스 재생성, 서비스 또는 LLM 조작을 수행하지 않았습니다.

- 후보 수: 7개 신규 일반 질의 개념
- 후보 상태: 모두 `pending`, `test_candidate=false`
- 기존 보류 후보: 3개를 원문 payload와 근거를 바꾸지 않은 채 별도 부록으로 보존
- 기준선: raw 55개 중 provenance가 부족한 6개를 제외한 trusted 49개

## 동결 입력과 경계

아래 파일의 SHA-256을 생성 전후에 고정해 계산 규칙 및 처리 정책이 바뀐 상태에서 후보를 만들지 않도록 했습니다.

| 입력 | SHA-256 |
|---|---|
| `data/rules/claim_deductible_rules.active.json` | `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818` |
| `data/rules/rule_links.active.json` | `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9` |
| `src/claim_calculation/processing_policy.py` | `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f` |

- trusted base content hash: `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2`
- source manifest content hash: `9700d288477ce2e9aa6e21d374849f56be00096b6a89bc8e7e1bc2c0463ff12c`
- 제외 유지 concept ID: `cond.age_related_hair_loss`, `cond.disease_related_hair_loss`, `cond.pay_nonpay_status`, `cond.treatment_side_effect_hair_loss`, `cond.work_daily_life_impairment`, `cov.hair_loss`
- 특히 `cond.pay_nonpay_status`의 alias·판단 payload는 이번 후보에 재도입하지 않았습니다.

## 실무자 검토 후보

후보는 지급액, 공제율, 한도, 지급 결론, 개별 질문 문구를 포함하지 않습니다. 각각은 재사용 가능한 명사구 alias, 질문 분류, 근거 확인을 위한 planner 필드만 제안합니다.

| 후보 | 제안 개념 | 주요 근거 | 평가 사례 ID | 검토 시 유의점 |
|---|---|---|---|---|
| `practitioner.v1_2_0.evidence.claim_document_requirements`<br>`EvidenceRequirement` | 보험금 청구 구비서류<br>alias: 보험금 청구 서류, 청구 구비서류, 추가 청구서류 | `약관_ch_002317` (pp.8-31, own_company_policy)<br>`약관_ch_002318` (pp.8-31, own_company_policy) | `new_20260702_014`, `new_20260702_019`, `expanded_20260615_082` | requires_practitioner_review, claim_event_context_required, no_runtime_decision |
| `practitioner.v1_2_0.cond.claim_payment_timeline`<br>`ClaimCondition` | 보험금 지급 절차 및 지연 사유<br>alias: 보험금 지급기일, 보험금 지급 지연 사유, 지급예정일 | `약관_ch_002353` (pp.40-41, own_company_policy) | `new_20260702_014`, `new_20260702_015`, `new_20260702_019`, `new_20260702_023`, `new_20260702_047` | requires_practitioner_review, policy_generation_sensitive, no_runtime_decision |
| `practitioner.v1_2_0.cond.policy_source_authority`<br>`ClaimCondition` | 약관 출처 및 실손 세대 확인<br>alias: 자사 상품 약관, 표준약관, 실손 세대 | `약관_ch_002286` (pp.1-2, own_company_policy)<br>`표준약관_ch_004925` (p.1, standard_policy) | `new_20260702_035`, `new_20260702_047` | requires_practitioner_review, authority_resolution_required, no_runtime_decision |
| `practitioner.v1_2_0.cond.korean_medicine_treatment_context`<br>`ClaimCondition` | 한방 치료 적용 맥락<br>alias: 한방 치료, 한의원 진료, 한방 의료기관 | `약관_ch_002421` (pp.62-66, own_company_policy)<br>`약관_ch_002451` (pp.78-84, own_company_policy) | `new_20260702_021` | requires_practitioner_review, exact_policy_clause_required, no_runtime_decision |
| `practitioner.v1_2_0.cond.dental_treatment_classification`<br>`ClaimCondition` | 치과 치료 질환 분류<br>alias: 치과 치료, 치과 질환, 치아 질환 | `약관_ch_002451` (pp.78-84, own_company_policy) | `new_20260702_022` | requires_practitioner_review, diagnosis_classification_required, no_runtime_decision |
| `practitioner.v1_2_0.cond.foreign_medical_institution`<br>`ClaimCondition` | 해외 의료기관 진료<br>alias: 해외 의료기관, 해외 진료, 외국 의료기관 | `표준약관_ch_005463` (p.313, standard_policy) | `new_20260702_025` | requires_practitioner_review, standard_reference_only, no_runtime_decision |
| `practitioner.v1_2_0.cond.nonclaim_history_discount`<br>`ClaimCondition` | 무사고·무청구 할인 조건<br>alias: 무사고 할인, 무청구 할인, 비급여 보험료 차등제 | `약관_ch_002313` (pp.8-31, own_company_policy) | `new_20260702_026`, `new_20260702_027` | requires_practitioner_review, product_specific_terms, not_a_claim_outcome, no_runtime_decision |

각 후보의 전체 planner/retrieval 필드, 원문 발췌, source hash, 문서 권위, field-level approval path는 JSON 패키지에서만 확인합니다. 실무자 승인 시에도 해당 경로만 선택적으로 적용할 수 있도록 기록했습니다.

## 이번에 후보로 만들지 않은 주제

| 주제 | not proposed 사유 |
|---|---|
| 수술 제외 목적 | trusted 49 baseline의 cond.cosmetic_purpose, cond.treatment_purpose, cond.preventive_purpose가 이미 목적 분류를 담당합니다. 중복 후보를 만들지 않고 후속 검색 평가로 확인합니다. 기존 담당: `cond.cosmetic_purpose`, `cond.treatment_purpose`, `cond.preventive_purpose` |
| 다수 실손보험 및 비례 처리 | trusted 49 baseline의 cond.other_insurance_payment가 이미 타 보험·다른 보험 문맥을 담당합니다. 이번 배치에서는 별칭을 넓혀 지급 판단 범위를 넓히지 않습니다. 기존 담당: `cond.other_insurance_payment` |
| 약관 모호성 및 근거 부족 | trusted 49 baseline의 cond.insufficient_evidence가 증빙 부족 경로를 담당합니다. 후보를 중복 생성하지 않고 약관 출처 및 실손 세대 확인 후보로 문서 권위 판별을 보강합니다. 기존 담당: `cond.insufficient_evidence` |
| 급여/비급여 상태 | cond.pay_nonpay_status는 provenance-deficient excluded set에 속합니다. 별칭·판단 payload를 재도입하지 않으며, 별도의 무사고·무청구 할인 맥락만 독립 후보로 제한합니다. 기존 담당: `cond.pay_nonpay_status` |

## 기존 보류 후보 부록

다음 3건은 기존 검토 상태를 바꾸지 않았습니다. 정확한 현재 payload와 source evidence는 후보 JSON의 `legacy_held_disposition_appendix`에 그대로 보존했습니다.

| 후보 ID | 현재 상태 |
|---|---|
| `dev.cov.indemnity_medical.2f8f7057fb90` | `held` |
| `dev.cond.motorcycle_riding.fc842c72db6f` | `held` |
| `dev.cov.superior_room_difference.d1fad7d62df5` | `held` |

## 생성·검증 기록

1. `template_only` 방식으로 원문 청크를 참조해 후보 패키지를 생성했습니다. LLM 서버를 시작·정지·교체하지 않았습니다.
2. 기존 `OntologyCandidate` 검토 모델, source hash, frozen hash, 49/6 기준선, 7개 후보 수, 3개 held 부록, field-level approval path, alias 명사구 규칙을 검증했습니다: 오류 0건.
3. `scripts/extract_ontology_candidates.py --dry-run --limit 100 --template-only`을 격리 작업공간에서 실행했습니다: generated_count 6, saved_count 0, `dry_run=true`, LLM mode `none`.
4. 후보 JSON은 `python -m json.tool`로 문법 검사를 통과했고, candidate extraction/review 정책 파일도 정상 로드했습니다.

## 산출물과 다음 결정

- 후보·근거 패키지: `docs/review_artifacts/2026-07-19-v1.2.0-general-query-ontology-candidate-batch.json`
- 이 보고서: `docs/280_V1_2_0_GENERAL_QUERY_ONTOLOGY_CANDIDATE_PREPARATION_REPORT.md`
- 다음 단계는 실무자가 후보별 field-level approval path와 근거를 검토해 명시적으로 승인·보류·거절하는 것입니다. 이번 패키지 자체는 runtime 또는 active ontology에 영향을 주지 않습니다.

## 운영 경계 확인

보호 메인 저장소, active ontology, active rule/links, GraphDB, BM25/Chroma 인덱스, 사용자·대화·운영 로그, 서비스와 LLM 서버는 변경하지 않았습니다. Git stage, commit, push도 수행하지 않았습니다. 원본 Excel 파일은 저장소로 복사하지 않았고 case ID와 집계 정보만 패키지에 기록했습니다.
