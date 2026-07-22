# 215. Ontology Policy Externalization Implementation Report

작성일: 2026-06-10

## Summary

`docs/214_ONTOLOGY_POLICY_EXTERNALIZATION_PLAN.md`에 따라 승인 기반 온톨로지 후보 생성/검토 정책을 Python 코드 상수에서 JSON 정책 파일로 분리했다.

이번 작업은 운영 온톨로지 개편본 적용 작업이 아니다. `data/ontology/concepts.json`과 `data/ontology/concepts.active.json`는 직접 수정하지 않았고, `scripts/ontology_review.py --apply`와 GraphDB rebuild도 실행하지 않았다.

## Pre-check

로컬 저장소:

```text
branch: master...origin/master
pre-existing local change: docs/214_ONTOLOGY_POLICY_EXTERNALIZATION_PLAN.md
```

DGX 메인 저장소:

```text
path: /srv/shared/projects/insurance-rag-chatbot
branch: master...origin/master
HEAD: 4728716
docs/214_ONTOLOGY_POLICY_EXTERNALIZATION_PLAN.md: missing
```

DGX에는 이번 로컬 구현을 복사, 커밋, push하지 않았다. 원격 반영은 별도 사용자 승인 후 수행한다.

## Implemented

### 1. 정책 파일 추가

추가:

- `data/ontology/policies/candidate_extraction_policy.json`
- `data/ontology/policies/review_policy.json`

`candidate_extraction_policy.json`에는 후보 추출 기준을 둔다.

- `domain_keywords`
- `stop_phrases`
- `generic_table_terms`
- `noise_fragments`
- `table_noise_markers`
- `expression_shape`
- `candidate_types.default_reinforcement_type`

`review_policy.json`에는 개발용 자동 승인과 보류 판단 기준을 둔다.

- `low_risk_candidate_types`
- `prohibited_auto_approval_types`
- `prohibited_risk_terms`
- `unsafe_auto_approval_fragments`
- `expression_shape`
- `auto_approval`

`auto_approval.require_test_candidate=true`를 명시해 개발용 자동 승인도 `test_candidate=true` 후보로 제한한다.

### 2. 정책 loader/validator 추가

추가:

- `src/ontology/policy.py`

제공 API:

- `load_candidate_extraction_policy`
- `load_review_policy`
- `validate_candidate_extraction_policy`
- `validate_review_policy`
- `validate_policy_files`

검증 항목:

- 필수 metadata 존재
- 빈 domain keyword 차단
- 빈 risk term 차단
- expression length 역전 차단
- low-risk type과 prohibited type 충돌 차단
- auto-approval risk level/risk flag 누락 차단

### 3. 후보 추출기 정책 주입

수정:

- `src/ontology/candidate_extractor.py`

변경:

- `DOMAIN_KEYWORDS`, `STOP_PHRASES`, `GENERIC_TABLE_TERMS`, `CANDIDATE_NOISE_FRAGMENTS`를 코드 상수에서 제거했다.
- 후보 추출, table/noise 필터, 표현 길이 필터가 `CandidateExtractionPolicy`를 사용한다.
- `extract_reinforcement_candidates()`와 `extract_candidate_terms()`가 정책 객체를 받을 수 있다.
- 후보 metadata에 `properties.extraction.policy_id`, `properties.extraction.policy_version`을 기록한다.

### 4. 후보 검토기 정책 주입

수정:

- `src/ontology/candidate_reviewer.py`

변경:

- `LOW_RISK_CANDIDATE_TYPES`, `PROHIBITED_AUTO_APPROVAL_TYPES`, `PROHIBITED_RISK_TERMS`, `UNSAFE_AUTO_APPROVAL_FRAGMENTS`를 코드 상수에서 제거했다.
- 개발용 자동 승인 판단이 `OntologyReviewPolicy`를 사용한다.
- `codex_dev_review` metadata에 `policy_id`, `policy_version`, `reason_codes`를 기록한다.

대표 reason code:

- `low_risk_evidence_backed`
- `source_evidence_missing`
- `candidate_type_not_low_risk`
- `prohibited_candidate_type`
- `risk_term_guardrail`
- `expression_safety_guardrail`
- `target_overlap_missing`
- `ontology_conflict`

### 5. review store 자동 승인 gate 정책화

수정:

- `src/ontology/review_store.py`

변경:

- `is_codex_development_auto_approvable()`가 `OntologyReviewPolicy.auto_approval`을 사용한다.
- 개발용 자동 승인 조건에 `test_candidate=true` 제한을 명시적으로 반영했다.
- source evidence, dev risk flag, allowed risk level 조건도 정책 파일을 따른다.

주의:

- 후보 생성 dry-run에서 `codex_dev_review.decision=approve`가 붙어도 `test_candidate=false`이면 실제 `--auto-approve-dev` 대상이 아니다.
- 이는 운영 후보 전체 자동 승인을 막기 위한 보수적 guardrail이다.

### 6. CLI 옵션 연결

수정:

- `scripts/extract_ontology_candidates.py`
- `scripts/ontology_review.py`

후보 추출 CLI:

```text
--candidate-policy
--review-policy
--validate-policies
```

review CLI:

```text
--review-policy
--validate-policy
```

정책 validation은 저장소 상태를 변경하지 않는다.

### 7. .gitignore 예외 추가

수정:

- `.gitignore`

`data/*` ignore 규칙 때문에 정책 JSON이 추적되지 않는 문제가 있었다. 정책 파일은 생성 산출물이 아니라 코드가 읽는 운영 정책이므로 다음 범위를 예외 처리했다.

```text
!data/ontology/
data/ontology/*
!data/ontology/policies/
!data/ontology/policies/*.json
```

## Tests

실행:

```bash
python -m py_compile src/ontology/policy.py src/ontology/candidate_extractor.py src/ontology/candidate_reviewer.py src/ontology/review_store.py scripts/extract_ontology_candidates.py scripts/ontology_review.py
```

결과:

```text
PASS
```

실행:

```bash
python -m pytest tests/test_ontology_policy.py tests/test_ontology_candidate_extractor.py tests/test_ontology_candidate_reviewer.py tests/test_ontology_review_store.py -q
```

결과:

```text
18 passed
```

실행:

```bash
python -m pytest tests/test_ontology_policy.py tests/test_ontology_candidate_extractor.py tests/test_ontology_candidate_reviewer.py tests/test_ontology_review_store.py tests/test_ontology_manifest_merge.py tests/test_ontology_registry.py -q
```

결과:

```text
28 passed
```

실행:

```bash
python scripts/extract_ontology_candidates.py --dry-run --limit 20 --template-only --validate-policies
```

결과:

```text
source_count: 2000
generated_count: 5
saved_count: 0
policy_validation: candidate-extraction-default / ontology-review-default
```

실행:

```bash
python scripts/ontology_review.py --summary --validate-policy
```

결과:

```text
review_policy valid: true
summary: total 0
```

추가 확인:

```text
is_codex_development_auto_approvable(test_candidate=false) -> False
is_codex_development_auto_approvable(test_candidate=true) -> True
```

## Guardrails Preserved

- `data/ontology/concepts.json` 직접 수정 없음
- `data/ontology/concepts.active.json` 직접 수정 없음
- `scripts/ontology_review.py --apply` 미실행
- GraphDB rebuild 미실행
- 운영 후보 전체 자동 승인 없음
- 지급/면책/감액/보험금 계산 rule 자동 승인 없음
- source evidence 필수 유지
- 개발용 자동 승인 `test_candidate=true` 제한 유지
- LLM prompt tuning 또는 신규 concept 자동 생성 범위 확장 없음

## Remaining Work

다음 작업에서 검토할 수 있는 항목:

- 정책 파일 변경 diff를 실무자가 읽기 쉬운 형태로 보여주는 진단 명령
- 후보별 hold 원인 집계에서 `reason_codes`를 직접 활용
- 정책 version과 후보 extraction run id를 묶은 batch report 생성
- DGX 메인 저장소 반영, 커밋, push
- 별도 승인 후 active manifest 병합과 GraphDB rebuild
