# 214. Ontology Policy Externalization Plan

작성일: 2026-06-10

## 1. 목적

승인 기반 온톨로지 구축 workflow의 다음 단계는 후보 추출 성능을 곧바로 높이는 것이 아니라, 후보 생성과 자동 승인 판단을 좌우하는 정책을 코드 밖의 검증 가능한 데이터 계층으로 분리하는 것이다.

현재 Phase 5 MVP는 운영 온톨로지를 직접 하드코딩하지 않는다. 후보는 `data/ontology/review/candidates.jsonl`에 저장되고, 승인된 후보만 `data/ontology/concepts.active.json`에 병합될 수 있다. 이 구조는 올바르지만, 후보 추출과 개발용 자동 승인 판단에 쓰이는 키워드, stop phrase, noise fragment, 위험어, 후보 타입 정책은 아직 Python 상수로 남아 있다.

이 계획의 목적은 다음 원칙을 구현 가능한 작업 단위로 구체화하는 것이다.

```text
보험 지식 체계와 업무 판단 로직은 코드 상수로 확정하지 않는다.
코드는 정책 파일을 읽고 검증하고 실행한다.
운영 지식은 원천 근거, 승인 이력, active manifest, GraphDB rebuild 결과로 관리한다.
```

## 2. 배경

현재 구현된 승인 기반 ontology 구성 요소:

- `src/ontology/candidate_extractor.py`
  - 원천 chunk와 GraphDB evidence에서 기존 concept 보강 후보를 생성한다.
  - `DOMAIN_KEYWORDS`, `STOP_PHRASES`, `GENERIC_TABLE_TERMS`, `CANDIDATE_NOISE_FRAGMENTS`가 코드 상수로 존재한다.
- `src/ontology/candidate_reviewer.py`
  - 개발용 자동 승인 가능 여부를 판단한다.
  - `LOW_RISK_CANDIDATE_TYPES`, `PROHIBITED_AUTO_APPROVAL_TYPES`, `PROHIBITED_RISK_TERMS`, `UNSAFE_AUTO_APPROVAL_FRAGMENTS`가 코드 상수로 존재한다.
- `src/ontology/review_store.py`
  - 후보 상태와 승인 이력을 JSONL로 관리한다.
  - `pending`, `approved`, `held`, `rejected`, `applied` 상태를 사용한다.
- `src/ontology/manifest_merge.py`
  - 승인된 후보만 active manifest에 병합한다.
  - 기존 concept 보강 후보는 새 concept이 아니라 target concept의 alias, candidate_aliases, evidence_tags, retrieval expansion으로 병합한다.
- `scripts/extract_ontology_candidates.py`
  - 비지속 batch 방식으로 후보를 추출한다.
- `scripts/ontology_review.py`
  - 실무자 승인, 개발용 자동 승인, summary, list-json, apply 흐름을 제공한다.

현재 방식의 장점:

- 운영 manifest를 직접 수정하지 않는다.
- 지급, 면책, 감액, 보험금 계산 rule 자동 승인을 막고 있다.
- source evidence 없는 후보는 자동 승인하지 않는다.
- 실무자 표시용 metadata와 내부 metadata를 분리했다.

현재 방식의 한계:

- 후보 생성과 자동 승인 보류 사유가 Python 코드의 문자열 목록에 의존한다.
- 정책 변경을 하려면 코드 수정, 테스트, 배포가 필요하다.
- 정책 버전과 후보 생성 결과를 명확히 연결하기 어렵다.
- 후보가 0건 승인되거나 전부 hold될 때, 정책이 과도하게 보수적인지 추출 품질이 낮은지 분리 진단하기 어렵다.

## 3. 설계 방향

실무 GraphRAG 시스템에서 확장 가능한 ontology는 아래 계층을 분리해야 한다.

```text
원천 근거 계층
  -> 후보 추출 계층
  -> 정책/ontology schema 계층
  -> 검증/진단 계층
  -> 실무자 승인 계층
  -> active manifest / GraphDB runtime 계층
```

이번 작업은 이 중 `정책/ontology schema 계층`과 `검증/진단 계층`의 최소 기반을 만든다.

핵심 방향:

- Python 코드는 정책을 보관하지 않고 정책 파일을 로드한다.
- 정책 파일은 저장소에서 versioning되고 review 대상이 된다.
- 정책 파일은 schema validation을 통과해야 후보 추출과 자동 승인 판단에 사용된다.
- 후보에는 어떤 정책 버전으로 생성/판정되었는지 기록한다.
- 정책 파일 변경만으로 후보 추출/자동 승인 기준을 조정할 수 있어야 한다.

## 4. 범위

이번 작업 범위:

- ontology 후보 추출 정책 파일 추가
- ontology review/auto-approval 정책 파일 추가
- 정책 로더와 validation 모듈 추가
- 기존 extractor/reviewer의 코드 상수를 정책 로더 기반으로 변경
- 후보 metadata에 정책 버전과 policy id 기록
- 정책 파일 검증 CLI 추가 또는 기존 후보 추출 CLI에 검증 옵션 추가
- 관련 단위 테스트 추가
- 구현 보고서 작성

이번 작업에서 제외:

- 운영 manifest 병합 `--apply`
- GraphDB rebuild
- 신규 concept 자동 생성
- 지급/면책/감액/보험금 계산 rule 자동 승인
- 실무자 승인 대체
- LLM prompt tuning 고도화
- 표준코드 DB와 평가 실패 로그 기반 후보 생성 확대

## 5. 신규 정책 파일 구조

신규 디렉터리:

```text
data/ontology/policies/
```

신규 파일:

```text
data/ontology/policies/candidate_extraction_policy.json
data/ontology/policies/review_policy.json
```

### 5.1 후보 추출 정책

`candidate_extraction_policy.json`은 후보 생성 전처리와 필터링 기준을 담는다.

예상 구조:

```json
{
  "schema_version": "1.0",
  "policy_id": "candidate-extraction-default",
  "version": "2026-06-10",
  "domain_keywords": [
    "상해",
    "질병",
    "진단",
    "수술",
    "입원",
    "통원",
    "치료"
  ],
  "stop_phrases": [
    "보험",
    "약관",
    "보장"
  ],
  "generic_table_terms": [
    "급여 상대가치점수",
    "비급여 목록",
    "분류번호"
  ],
  "noise_fragments": [
    "상대가치",
    "요양급여",
    "의료급여"
  ],
  "expression_shape": {
    "min_length": 3,
    "max_length": 18,
    "allow_digits": false,
    "allow_ascii_letters": false
  },
  "candidate_types": {
    "default_reinforcement_type": "alias_or_expansion"
  }
}
```

### 5.2 검토/자동 승인 정책

`review_policy.json`은 개발용 자동 승인과 보류 판단 기준을 담는다.

예상 구조:

```json
{
  "schema_version": "1.0",
  "policy_id": "ontology-review-default",
  "version": "2026-06-10",
  "low_risk_candidate_types": [
    "alias_or_expansion",
    "evidence_tag",
    "search_query_expansion"
  ],
  "prohibited_auto_approval_types": [
    "exclusion_rule",
    "payment_logic",
    "deductible_rule",
    "benefit_limit",
    "coordination_rule",
    "coverage_decision_edge"
  ],
  "prohibited_risk_terms": [
    "면책",
    "부지급",
    "감액",
    "공제",
    "한도",
    "보험금",
    "지급",
    "보상"
  ],
  "unsafe_auto_approval_fragments": [
    "상대가치",
    "분류번호",
    "요양급여",
    "의료급여"
  ],
  "auto_approval": {
    "require_pending_status": true,
    "require_source_evidence": true,
    "require_target_overlap": true,
    "allowed_risk_levels": ["low", "dev_only"],
    "development_only": true
  }
}
```

## 6. 코드 변경 계획

### 6.1 정책 모델 추가

신규 파일:

```text
src/ontology/policy.py
```

역할:

- 정책 파일 기본 경로 정의
- JSON load
- schema validation
- default policy load
- 테스트에서 임시 policy path 주입 가능

예상 public API:

```python
load_candidate_extraction_policy(path: str | Path | None = None) -> CandidateExtractionPolicy
load_review_policy(path: str | Path | None = None) -> OntologyReviewPolicy
validate_candidate_extraction_policy(payload: dict[str, Any]) -> list[str]
validate_review_policy(payload: dict[str, Any]) -> list[str]
```

정책 모델은 dataclass 또는 Pydantic 중 기존 의존성에 맞는 방식을 따른다. 이 저장소에서 Pydantic 의존성이 이미 안정적으로 사용 중이면 Pydantic을 우선 검토하고, 그렇지 않으면 dataclass + 명시 validation을 사용한다.

### 6.2 후보 추출기 변경

수정 파일:

```text
src/ontology/candidate_extractor.py
```

변경:

- `DOMAIN_KEYWORDS` 등 하드코딩 목록을 정책 파일에서 로드한다.
- `extract_candidate_terms()`가 policy 인자를 받을 수 있게 한다.
- `extract_reinforcement_candidates()`가 policy 인자를 받을 수 있게 한다.
- 후보 `properties.extraction.policy_id`, `properties.extraction.policy_version`을 기록한다.

호환성:

- 호출자가 policy를 넘기지 않으면 default policy를 로드한다.
- 기존 CLI와 테스트가 기본 동작으로 계속 통과해야 한다.

### 6.3 후보 검토기 변경

수정 파일:

```text
src/ontology/candidate_reviewer.py
```

변경:

- low-risk type, prohibited type, risk term, unsafe fragment를 review policy에서 읽는다.
- `build_codex_dev_review()`가 policy 인자를 받을 수 있게 한다.
- 반환 metadata에 `policy_id`, `policy_version`을 포함한다.
- reason 문자열은 기존 한국어 메시지를 유지하되, 내부적으로는 reason code를 함께 기록한다.

예상 metadata:

```json
{
  "decision": "hold",
  "development_only": true,
  "domain_fit": true,
  "evidence_fit": true,
  "risk_level": "medium",
  "reason": "지급/면책/감액/한도 관련 표현 포함",
  "reason_codes": ["risk_term_guardrail"],
  "policy_id": "ontology-review-default",
  "policy_version": "2026-06-10"
}
```

### 6.4 CLI 변경

수정 파일:

```text
scripts/extract_ontology_candidates.py
scripts/ontology_review.py
```

후보 추출 CLI 옵션:

```text
--candidate-policy data/ontology/policies/candidate_extraction_policy.json
--review-policy data/ontology/policies/review_policy.json
--validate-policies
```

review CLI 옵션:

```text
--review-policy data/ontology/policies/review_policy.json
--validate-policy
```

정책 validation만 수행하는 명령은 저장소 상태를 변경하지 않는다.

## 7. 테스트 계획

신규 테스트:

```text
tests/test_ontology_policy.py
```

검증 항목:

- 기본 후보 추출 정책 파일이 로드된다.
- 기본 review 정책 파일이 로드된다.
- 필수 필드가 없으면 validation error가 발생한다.
- 빈 `domain_keywords`는 reject한다.
- 음수 또는 역전된 expression length 정책은 reject한다.
- review policy에서 low-risk type과 prohibited type이 충돌하면 reject한다.
- 위험어 목록이 비어 있으면 reject한다.

기존 테스트 수정:

```text
tests/test_ontology_candidate_extractor.py
tests/test_ontology_candidate_reviewer.py
tests/test_ontology_review_store.py
```

검증 항목:

- 기존 low-risk 후보는 default policy 기준으로 approve된다.
- 지급/면책/감액/보험금 관련 표현은 default policy 기준으로 hold된다.
- 테스트용 custom policy를 넣으면 후보 추출 결과가 policy 변경을 반영한다.
- 후보 metadata에 policy id/version이 기록된다.

권장 실행:

```bash
.venv/bin/python -m pytest \
  tests/test_ontology_policy.py \
  tests/test_ontology_candidate_extractor.py \
  tests/test_ontology_candidate_reviewer.py \
  tests/test_ontology_review_store.py \
  tests/test_ontology_manifest_merge.py \
  tests/test_ontology_registry.py \
  -q
```

CLI 검증:

```bash
.venv/bin/python scripts/extract_ontology_candidates.py \
  --dry-run \
  --limit 20 \
  --template-only \
  --validate-policies

.venv/bin/python scripts/ontology_review.py \
  --summary \
  --validate-policy
```

## 8. 안전장치

- `data/ontology/concepts.json` 직접 수정 금지
- `data/ontology/concepts.active.json` 직접 수정 금지
- `scripts/ontology_review.py --apply` 실행 금지
- GraphDB rebuild 실행 금지
- 운영 후보 전체 자동 승인 금지
- 개발용 자동 승인은 기존 `test_candidate=true` 및 dev-only guardrail을 보존
- 지급/면책/감액/보험금 계산 rule은 자동 승인 대상에서 계속 제외
- 정책 파일은 raw data가 아니므로 커밋 가능하지만, 후보 산출물 JSONL은 작업 목적에 따라 별도 확인 후 커밋 여부를 결정한다.

## 9. 성공 기준

구현 성공 조건:

- 후보 추출/검토 정책이 코드 상수가 아니라 정책 파일에서 로드된다.
- 기본 정책 파일로 기존 테스트 의미가 유지된다.
- 잘못된 정책 파일은 명확한 validation error로 차단된다.
- 후보 생성 metadata에 정책 id/version이 기록된다.
- 개발용 자동 승인 guardrail이 완화되지 않는다.
- 운영 manifest와 active manifest는 변경되지 않는다.
- GraphDB rebuild는 실행되지 않는다.

품질 성공 조건:

- 정책을 바꾸기 위해 Python 코드를 수정할 필요가 없다.
- 후보가 전부 hold되는 경우에도 reason code와 policy version으로 원인을 분리 진단할 수 있다.
- 실무자 승인 workflow와 기존 desktop launcher 흐름을 깨지 않는다.

## 10. 구현 순서

1. 사전 확인
   - `git status --short --branch`
   - 관련 파일 확인:
     - `src/ontology/candidate_extractor.py`
     - `src/ontology/candidate_reviewer.py`
     - `src/ontology/review_store.py`
     - `scripts/extract_ontology_candidates.py`
     - `scripts/ontology_review.py`

2. 정책 파일 추가
   - `data/ontology/policies/candidate_extraction_policy.json`
   - `data/ontology/policies/review_policy.json`

3. 정책 loader/validator 추가
   - `src/ontology/policy.py`
   - `tests/test_ontology_policy.py`

4. extractor 정책 주입
   - 하드코딩 목록 제거 또는 compatibility alias로 축소
   - default policy load
   - 후보 metadata에 policy 기록

5. reviewer 정책 주입
   - 하드코딩 목록 제거 또는 compatibility alias로 축소
   - reason code 추가
   - review metadata에 policy 기록

6. CLI 옵션 연결
   - `--candidate-policy`
   - `--review-policy`
   - `--validate-policies`
   - `--validate-policy`

7. 테스트와 dry-run 검증
   - 관련 pytest 실행
   - 후보 추출 dry-run 실행
   - review summary 실행

8. 구현 보고서 작성
   - `docs/215_ONTOLOGY_POLICY_EXTERNALIZATION_IMPL_REPORT.md`

## 11. 운영 반영과의 관계

이번 작업은 운영 ontology 개편본을 적용하는 작업이 아니다.

다음 항목은 후속 작업에서만 수행한다.

```bash
.venv/bin/python scripts/ontology_review.py --apply
.venv/bin/python scripts/ontology_review.py --apply --rebuild-graph
```

이번 작업은 위 명령을 더 안전하게 실행하기 위한 정책 기반을 만드는 준비 단계다.

## 12. 점검 결과

계획 점검:

- [x] 하드코딩된 보험 지식과 업무 판단을 줄이는 방향인가
- [x] 기존 승인 기반 workflow를 유지하는가
- [x] 개발용 자동 승인 guardrail을 완화하지 않는가
- [x] 운영 manifest와 active manifest를 직접 수정하지 않는가
- [x] GraphDB rebuild를 후속 작업으로 분리하는가
- [x] 정책 변경과 후보 생성 결과를 추적할 수 있는가
- [x] 테스트와 dry-run 검증 경로가 있는가

판정:

이 계획은 후보 추출 품질 개선보다 먼저 정책 외부화와 검증 가능성을 확보한다. 따라서 “하드코딩을 통한 지식 체계 및 로직 구축 금지”라는 근본 목적에 부합한다.

## 13. 목표 설정 프롬프트

아래 프롬프트를 다음 구현 작업의 목표 설정용으로 사용한다.

```text
DGX 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot`와 로컬 저장소 `/Users/june_kim/Projects/insurance-rag-chatbot`의 현재 상태를 확인한 뒤, `docs/214_ONTOLOGY_POLICY_EXTERNALIZATION_PLAN.md`에 따라 승인 기반 온톨로지 후보 생성/검토 정책 외부화 작업을 구현하세요.

목표:
- 후보 추출과 개발용 자동 승인 판단을 좌우하는 키워드, stop phrase, noise fragment, 위험어, 후보 타입 정책을 Python 코드 상수에서 `data/ontology/policies/*.json` 정책 파일로 이동합니다.
- `src/ontology/policy.py`를 추가해 정책 파일 로드, 기본 경로, schema validation, 테스트용 path 주입을 지원합니다.
- `src/ontology/candidate_extractor.py`와 `src/ontology/candidate_reviewer.py`가 정책 객체를 받아 동작하도록 수정합니다.
- 후보 metadata와 `codex_dev_review` metadata에 `policy_id`, `policy_version`, 가능한 경우 `reason_codes`를 기록합니다.
- `scripts/extract_ontology_candidates.py`와 `scripts/ontology_review.py`에 정책 경로 및 validation 옵션을 연결합니다.
- 기존 개발용 자동 승인 guardrail은 완화하지 않습니다. 특히 지급/면책/감액/보험금 계산 rule 자동 승인 금지, source evidence 필수, dev-only 제한, `test_candidate=true` 기반 자동 승인 제한을 보존합니다.
- `data/ontology/concepts.json`, `data/ontology/concepts.active.json`는 직접 수정하지 않습니다.
- `scripts/ontology_review.py --apply`와 GraphDB rebuild는 실행하지 않습니다.

구현 후 검증:
- `git status --short --branch`로 작업 전후 상태를 확인합니다.
- 관련 pytest를 실행합니다.
  `.venv/bin/python -m pytest tests/test_ontology_policy.py tests/test_ontology_candidate_extractor.py tests/test_ontology_candidate_reviewer.py tests/test_ontology_review_store.py tests/test_ontology_manifest_merge.py tests/test_ontology_registry.py -q`
- 후보 추출 dry-run과 review policy validation을 실행합니다.
  `.venv/bin/python scripts/extract_ontology_candidates.py --dry-run --limit 20 --template-only --validate-policies`
  `.venv/bin/python scripts/ontology_review.py --summary --validate-policy`
- 구현 보고서를 `docs/215_ONTOLOGY_POLICY_EXTERNALIZATION_IMPL_REPORT.md`에 작성합니다.

완료 보고:
- 변경한 파일
- 정책 파일 구조
- 하드코딩 제거 범위
- 보존한 guardrail
- 실행한 검증 명령과 결과
- 실행하지 않은 운영 반영 작업과 남은 위험을 한국어로 간결히 보고하세요.
```
