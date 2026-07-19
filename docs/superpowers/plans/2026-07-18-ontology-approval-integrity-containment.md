# Ontology 승인 무결성·운영 격리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` for each code task and `superpowers:verification-before-completion` before reporting completion. Do not execute the active apply or GraphDB publication steps without a separate operational approval.

**Goal:** 승인된 후보의 명시적 필드만 active ontology와 GraphDB에 투영하고, 승인 provenance를 증명할 수 없는 개념은 이름이나 질환별 예외 없이 개념 단위로 운영 해석에서 격리한다.

**Architecture:** 검증된 base manifest를 개념별 content hash lock으로 고정하고, 후보 검토 시 semantic JSON path 단위 `ApprovalPatch`를 불변 로그에 남긴다. 병합기는 현재 base 전체를 복사하지 않고 lock과 일치하는 trusted base projection 위에 승인 연산만 적용하며, active manifest와 provenance sidecar의 해시를 함께 검증한다. runtime registry와 GraphDB builder는 동일 integrity report를 사용하여 fail-closed로 동작한다.

**Tech Stack:** Python 3.11, dataclasses, JSON/JSONL append-only audit log, SHA-256 canonical JSON, FastAPI runtime registry, SQLite GraphDB builder, pytest.

**Approved design:** `docs/superpowers/specs/2026-07-18-approval-safe-conversational-evidence-resolution-design.md`

## Global Constraints

- `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`를 최우선 적용한다.
- production 코드에는 `탈모`, 특정 concept id, 특정 질문 문장 또는 질환별 denylist를 추가하지 않는다.
- 현재 사건의 개념명은 forensic fixture와 correction report에서만 사용할 수 있다.
- `data/ontology/concepts.json`의 현재 내용을 신뢰 기준으로 자동 채택하지 않는다.
- 기존 `review_log.jsonl`, `applied_reviews.jsonl`, 운영 active manifest, GraphDB를 삭제·축약·재작성하지 않는다.
- legacy 승인 로그에 field-level patch가 없으면 승인 범위를 추정하지 않고 `legacy_unverifiable`로 처리한다.
- 코드 구현과 dry-run 산출물 생성까지만 허용한다. active manifest 교체, GraphDB 재구축·교체, 서비스 재기동은 별도 운영 승인 뒤에 수행한다.
- 보호된 DGX main checkout에서 직접 개발하지 않는다. 최신 `origin/master` 기반 격리 작업공간을 사용한다.
- Developer는 이 계획 수행 중 stage, commit, push, protected main 반영을 하지 않는다. 아래 commit checkpoint는 이후 사용자가 별도로 승인했을 때만 실행한다.

## Fixed Contracts

### Semantic approval path

배열 인덱스가 아니라 concept id를 주소로 쓰는 semantic JSON pointer를 사용한다.

```text
/concepts/{escaped_concept_id}/canonical_name
/concepts/{escaped_concept_id}/aliases/{value_hash}
/concepts/{escaped_concept_id}/candidate_aliases/{value_hash}
/concepts/{escaped_concept_id}/evidence_tags/{value_hash}
/concepts/{escaped_concept_id}/planner/conditions/{value_hash}
/concepts/{escaped_concept_id}/retrieval/expansion_rules/{value_hash}
/concepts/{escaped_concept_id}/properties/{escaped_key}
```

`~`는 `~0`, `/`는 `~1`로 escape한다. list item 경로의 마지막 segment는 canonical item hash이므로 입력 순서가 달라도 같은 항목을 가리킨다.

### Candidate property separation

- `OntologyCandidate.properties`: 추출·검토·표시·lifecycle 제어 metadata 전용
- `OntologyCandidate.runtime_properties`: active concept의 `properties`로 승격 가능한 지식 payload 전용
- 기존 candidate의 `properties`는 자동으로 `runtime_properties`로 이동하지 않는다.
- 새 runtime property도 명시적 approval path 없이는 병합하지 않는다.

### Integrity states

```python
IntegrityState = Literal["valid", "quarantined", "stale", "legacy_unverifiable"]
```

- `valid`: trusted base와 같거나 승인 patch가 모든 delta를 설명함
- `quarantined`: 승인되지 않은 delta가 있어 해당 concept를 runtime에서 제외함
- `stale`: 승인 시 base/candidate/evidence hash와 현재 값이 다름
- `legacy_unverifiable`: 기존 승인 로그에 field-level patch가 없어 delta를 증명할 수 없음

---

## Task 1: 변경 전 증거와 trusted baseline 후보를 재현한다

**Files:**

- Inspect: `data/ontology/concepts.json`
- Inspect: `data/ontology/review/candidates.jsonl`
- Inspect: `data/ontology/review/review_log.jsonl`
- Inspect when present: `data/ontology/concepts.active.json`
- Inspect when present: `data/index/graph/insurance_graph.sqlite`
- Inspect: `docs/review_artifacts/2026-07-18-hair-loss-full-payload-correction-candidate.json`
- Create during implementation report: `docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md`

- [ ] 현재 작업공간, 기준 commit, dirty state를 기록한다.

Run:

```bash
git rev-parse HEAD
git status --short
git log -5 --oneline
```

Expected: 최신 `origin/master` 기반 격리 작업공간이며 작업 시작 전 의도하지 않은 변경이 없다. dirty file이 있으면 보존하고 보고한 뒤 겹치는 파일을 수정하지 않는다.

- [ ] 승인되지 않은 base 변경이 들어오기 전 manifest를 임시 파일로 복원한다.

Run:

```bash
git show 23278c3^:data/ontology/concepts.json > /tmp/ontology-trusted-base-before-23278c3.json
python -m json.tool /tmp/ontology-trusted-base-before-23278c3.json >/dev/null
```

Expected: JSON 검증이 통과한다. 이 commit hash는 현재 사건의 forensic 재현 명령에만 사용하고 production Python 상수로 넣지 않는다.

- [ ] 현재 base와 trusted baseline 후보의 concept-level 차이를 기록한다.

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

old = json.loads(Path('/tmp/ontology-trusted-base-before-23278c3.json').read_text(encoding='utf-8'))
new = json.loads(Path('data/ontology/concepts.json').read_text(encoding='utf-8'))
old_ids = {row['concept_id'] for row in old['concepts']}
new_ids = {row['concept_id'] for row in new['concepts']}
print({'added': sorted(new_ids - old_ids), 'removed': sorted(old_ids - new_ids)})
PY
```

Expected: 현재 사건에서 직접 추가된 concept들이 `added`에 표시된다. 이 출력은 증거이며 자동 승인 목록이 아니다.

- [ ] DGX 운영 산출물은 읽기 전용 명령으로만 snapshot한다.

Run on DGX only when the files exist:

```bash
sha256sum data/ontology/concepts.json data/ontology/concepts.active.json data/index/graph/insurance_graph.sqlite
python scripts/check_graph_index.py --db data/index/graph/insurance_graph.sqlite
```

Expected: hash와 검사 결과가 보고서에 기록된다. 파일을 저장소로 복사하거나 변경하지 않는다.

## Task 2: canonical hash와 base lock 계약을 테스트 우선으로 추가한다

**Files:**

- Create: `src/ontology/approval_integrity.py`
- Create: `tests/test_ontology_approval_integrity.py`
- Create after review evidence is fixed: `data/ontology/policies/base_manifest.lock.json`

- [ ] 다음 회귀 테스트를 먼저 작성한다.

```python
def test_manifest_content_hash_ignores_only_generated_active_version() -> None:
    first = {
        "schema_version": "1.0",
        "version": "base+approved-2026-07-18T01:00:00Z",
        "description": "active",
        "concepts": [{"concept_id": "cond.alpha", "canonical_name": "조건 A"}],
    }
    second = {**first, "version": "base+approved-2026-07-18T02:00:00Z"}
    assert manifest_content_hash(first) == manifest_content_hash(second)
    second["concepts"][0]["canonical_name"] = "조건 B"
    assert manifest_content_hash(first) != manifest_content_hash(second)


def test_trusted_base_projection_quarantines_only_hash_mismatched_concepts() -> None:
    base = _base_manifest("cond.alpha", "cond.injected")
    lock = BaseManifestLock.from_manifest(_base_manifest("cond.alpha"), source_commit="trusted")
    projection, report = build_trusted_base_projection(base, lock)
    assert [row["concept_id"] for row in projection["concepts"]] == ["cond.alpha"]
    assert report.quarantined_concept_ids == ("cond.injected",)
```

- [ ] 테스트가 구현 부재로 실패하는지 확인한다.

Run:

```bash
pytest tests/test_ontology_approval_integrity.py -v
```

Expected: `src.ontology.approval_integrity` import 또는 새 symbol 부재로 실패한다.

- [ ] 다음 공개 계약을 구현한다.

```python
@dataclass(frozen=True)
class BaseManifestLock:
    schema_version: int
    manifest_content_hash: str
    concept_hashes: dict[str, str]
    source_commit: str
    review_record_id: str


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    concept_id: str
    path: str
    message: str


@dataclass(frozen=True)
class ManifestIntegrityReport:
    state: IntegrityState
    manifest_content_hash: str
    trusted_base_content_hash: str
    issues: tuple[IntegrityIssue, ...]
    quarantined_concept_ids: tuple[str, ...]


def canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def manifest_content_hash(payload: dict[str, Any]) -> str:
    content = {
        "schema_version": payload.get("schema_version"),
        "description": payload.get("description"),
        "concepts": payload.get("concepts", []),
    }
    return canonical_json_hash(content)


def build_trusted_base_projection(
    base_payload: dict[str, Any],
    lock: BaseManifestLock,
) -> tuple[dict[str, Any], ManifestIntegrityReport]:
    """Keep only concepts whose canonical content hash matches the reviewed lock."""
```

`canonical_json_hash()`는 일반 값에는 어떤 key도 제외하지 않는다. 생성 시각 제외는 `manifest_content_hash()`의 top-level `version` 한 곳에서만 수행한다.

- [ ] trusted baseline lock을 deterministic하게 생성하는 helper를 구현한다.

```python
def build_base_manifest_lock(
    payload: dict[str, Any],
    *,
    source_commit: str,
    review_record_id: str,
) -> BaseManifestLock:
    concept_hashes = {
        str(row["concept_id"]): canonical_json_hash(row)
        for row in payload["concepts"]
    }
    return BaseManifestLock(
        schema_version=1,
        manifest_content_hash=manifest_content_hash(payload),
        concept_hashes=concept_hashes,
        source_commit=source_commit,
        review_record_id=review_record_id,
    )
```

- [ ] 테스트를 다시 실행한다.

Run:

```bash
pytest tests/test_ontology_approval_integrity.py -v
```

Expected: hash 안정성, concept-level quarantine, lock round-trip 테스트가 모두 통과한다.

## Task 3: 후보 payload와 runtime payload를 분리한다

**Files:**

- Modify: `src/ontology/review_store.py`
- Modify: `tests/test_ontology_review_store.py`
- Modify: `tests/test_ontology_candidate_extractor.py`

- [ ] `properties` 제어 metadata가 runtime concept에 복사되지 않는 테스트를 추가한다.

```python
def test_runtime_concept_does_not_promote_candidate_control_properties() -> None:
    candidate = OntologyCandidate(
        candidate_id="cand-control",
        concept_id="cond.alpha",
        canonical_name="조건 A",
        properties={"candidate_type": "evidence_tag", "review_feedback": {"note": "internal"}},
        runtime_properties={"decision_polarity": "review"},
    )
    concept = candidate.runtime_concept()
    assert concept["properties"] == {"decision_polarity": "review"}
    assert "candidate_type" not in concept["properties"]
```

- [ ] candidate approval hash가 lifecycle 상태 변경에 흔들리지 않는 테스트를 추가한다.

```python
def test_candidate_approval_hash_excludes_lifecycle_state() -> None:
    candidate = _candidate(status="pending")
    before = candidate.approval_payload_hash()
    candidate.status = "approved"
    candidate.properties["applied_at"] = "2026-07-18T00:00:00Z"
    assert candidate.approval_payload_hash() == before
```

- [ ] `OntologyCandidate`에 다음 필드와 메서드를 추가한다.

```python
runtime_properties: dict[str, Any] = field(default_factory=dict)

def approval_payload(self) -> dict[str, Any]:
    return {
        "candidate_id": self.candidate_id,
        "concept_id": self.concept_id,
        "canonical_name": self.canonical_name,
        "node_type": self.node_type,
        "aliases": self.aliases,
        "candidate_aliases": self.candidate_aliases,
        "evidence_tags": self.evidence_tags,
        "planner": self.planner,
        "retrieval": self.retrieval,
        "runtime_properties": self.runtime_properties,
        "source_evidence": self.source_evidence,
    }

def approval_payload_hash(self) -> str:
    return canonical_json_hash(self.approval_payload())
```

- [ ] `from_dict()`와 `to_dict()`는 `runtime_properties`를 round-trip하고, 기존 row에 필드가 없으면 빈 dict로 읽는다.

- [ ] `runtime_concept()`는 candidate control metadata를 복사하지 않고 명시된 runtime field만 반환하도록 제한한다.

- [ ] focused tests를 실행한다.

Run:

```bash
pytest tests/test_ontology_review_store.py tests/test_ontology_candidate_extractor.py -v
```

Expected: 기존 후보 생성·표시 테스트와 새 payload 분리 테스트가 모두 통과한다.

## Task 4: 검토 시점에 field-level ApprovalPatch를 불변 기록한다

**Files:**

- Modify: `src/ontology/approval_integrity.py`
- Modify: `src/ontology/review_store.py`
- Modify: `scripts/ontology_review.py`
- Modify: `scripts/ontology_review_local_ui.py`
- Modify: `src/api/schemas/knowledge.py`
- Modify: `src/api/routes/knowledge.py`
- Modify: `frontend/js/pages/admin.js`
- Modify: `tests/test_ontology_approval_integrity.py`
- Modify: `tests/test_ontology_review_store.py`
- Modify: `tests/test_api_admin_knowledge.py`
- Modify: `tests/test_admin_knowledge_frontend.mjs`

- [ ] 다음 dataclass와 projector 테스트를 먼저 추가한다.

```python
@dataclass(frozen=True)
class ApprovalOperation:
    operation: Literal["add", "replace", "remove"]
    path: str
    value_hash: str


@dataclass(frozen=True)
class ApprovedEvidence:
    chunk_id: str
    content_hash: str


@dataclass(frozen=True)
class ApprovalPatch:
    schema_version: int
    candidate_id: str
    candidate_payload_hash: str
    base_manifest_hash: str
    allowed_operations: tuple[ApprovalOperation, ...]
    approved_evidence: tuple[ApprovedEvidence, ...]
    reviewer: str
    reviewed_at: str
```

Required assertions:

```python
def test_evidence_tag_candidate_exposes_only_evidence_tag_operation() -> None:
    candidate = _reinforcement_candidate(
        candidate_type="evidence_tag",
        candidate_aliases=["승인 밖 표현"],
        evidence_tags=["source:alpha"],
        retrieval={"expansion_rules": [{"match_any": ["A"], "expansion_terms": ["B"]}]},
    )
    operations = project_candidate_operations(candidate, _base_manifest("cond.alpha"))
    assert [operation.path for operation in operations] == [
        f"/concepts/cond.alpha/evidence_tags/{canonical_json_hash('source:alpha')}"
    ]
```

- [ ] candidate type별 허용 field group을 코드 지식이 아닌 처리 policy로 정의한다.

Create or modify: `data/ontology/policies/review_policy.json`

```json
{
  "approval_path_policy": {
    "evidence_tag": ["evidence_tags"],
    "alias_or_expansion": ["candidate_aliases"],
    "search_query_expansion": ["retrieval.expansion_rules"],
    "new_concept": ["canonical_name", "node_type", "aliases", "candidate_aliases", "evidence_tags", "planner", "retrieval", "runtime_properties"]
  }
}
```

기존 policy key는 유지하고 위 key를 병합한다. 이 목록은 field group 처리 권한이며 보험 정답이나 특정 concept를 담지 않는다.

- [ ] `OntologyReviewStore.decide()`의 approve 경로를 다음 계약으로 확장한다.

```python
def decide(
    self,
    candidate_id: str,
    decision: str,
    *,
    reviewer: str = "unknown",
    reviewer_type: str = "practitioner",
    reason: str = "",
    hold_reason_codes: list[str] | None = None,
    approved_paths: list[str] | None = None,
    base_manifest_path: str | Path = BASE_ONTOLOGY_MANIFEST,
) -> OntologyCandidate:
```

`decision == "approve"`이면 `approved_paths`가 비어 있거나 projector가 노출하지 않은 path가 포함되면 status를 바꾸기 전에 `ValueError`를 발생시킨다.

- [ ] approve review log에 다음 필드를 추가한다.

```json
{
  "candidate_payload_hash": "sha256",
  "base_manifest_hash": "sha256",
  "approval_patch": {
    "schema_version": 1,
    "allowed_operations": [],
    "approved_evidence": []
  }
}
```

- [ ] `OntologyReviewStore.latest_approval_patch(candidate_id)`를 추가하여 가장 최근의 유효 approve log를 읽는다. candidate hash가 현재 값과 다르면 `stale` 오류를 반환하고 과거 log를 고치지 않는다.

- [ ] CLI의 승인 명령은 path를 반복 입력받도록 변경한다.

```bash
python scripts/ontology_review.py --show candidate-id
python scripts/ontology_review.py \
  --decide candidate-id \
  --decision approve \
  --reviewer practitioner-id \
  --approve-path '/concepts/cond.alpha/evidence_tags/hash-value'
```

`show` 출력은 가능한 operation path, value preview, source evidence를 함께 표시한다. `--approve-all`은 추가하지 않는다.

- [ ] 관리자 API와 로컬 검토 UI도 같은 explicit path 계약을 사용한다.

`CandidateDecisionRequest`를 다음처럼 확장한다.

```python
approved_paths: list[str] = Field(default_factory=list)
```

`decision="approve"`이면 UI는 projector가 반환한 operation을 checkbox로 표시하고 선택된 path만 전송한다. hold/reject는 빈 목록을 허용한다. API route와 local UI는 store 내부 검증을 우회하지 않는다.

관리자 후보 목록에는 raw value 대신 `approval_operations`의 path, field label, bounded value preview, value hash를 표시한다. `runtime_properties`의 전체 내부 payload를 일반 목록 화면에 펼치지 않는다.

- [ ] 개발용 자동 승인은 review policy가 허용한 low-risk path만 선택하고, 지급·면책·한도·계산·runtime decision property는 계속 제외한다.

- [ ] focused tests를 실행한다.

Run:

```bash
pytest \
  tests/test_ontology_approval_integrity.py \
  tests/test_ontology_review_store.py \
  tests/test_extract_ontology_candidates_cli.py \
  tests/test_api_admin_knowledge.py -v
node --test tests/test_admin_knowledge_frontend.mjs
```

Expected: CLI·API·로컬 UI의 explicit path 승인, 잘못된 path 거부, stale candidate 거부, legacy log 판정, auto-approval 제한이 모두 통과한다.

## Task 5: 병합기를 trusted projection + approved operations 방식으로 교체한다

**Files:**

- Modify: `src/ontology/manifest_merge.py`
- Modify: `tests/test_ontology_manifest_merge.py`
- Modify: `src/ontology/approval_integrity.py`
- Modify: `data/ontology/ontology_manifest.schema.json`

- [ ] 기존 누출을 재현하는 실패 테스트를 먼저 추가한다.

```python
def test_evidence_only_patch_cannot_promote_alias_question_retrieval_or_decision_profile(tmp_path: Path) -> None:
    base_path = _write_base_with_untrusted_delta(tmp_path)
    lock_path = _write_lock_for_trusted_projection(tmp_path)
    candidate = _approved_evidence_candidate()
    patch = _approval_patch(candidate, approved_field="evidence_tags")
    result = merge_approved_candidates(
        [candidate],
        approval_patches={candidate.candidate_id: patch},
        base_manifest_path=base_path,
        base_lock_path=lock_path,
        output_path=tmp_path / "concepts.active.json",
        provenance_path=tmp_path / "concepts.active.provenance.json",
    )
    concept = _concept(result.output_path, "cond.alpha")
    assert concept["evidence_tags"] == ["source:alpha"]
    assert "aliases" not in concept
    assert "clarification_questions" not in concept.get("planner", {})
    assert "retrieval" not in concept
    assert "source_grounded_decision" not in concept.get("properties", {})
```

- [ ] 다음 merge signature를 구현한다.

```python
def merge_approved_candidates(
    candidates: Iterable[OntologyCandidate],
    *,
    approval_patches: Mapping[str, ApprovalPatch],
    base_manifest_path: str | Path = BASE_ONTOLOGY_MANIFEST,
    base_lock_path: str | Path = BASE_ONTOLOGY_LOCK,
    output_path: str | Path = ACTIVE_ONTOLOGY_MANIFEST,
    provenance_path: str | Path = ACTIVE_ONTOLOGY_PROVENANCE,
) -> ManifestMergeResult:
```

- [ ] 병합 순서를 고정한다.

```text
1. base JSON과 base lock 로드
2. concept hash가 lock과 일치하는 trusted base projection 생성
3. approved/applied candidate마다 최신 ApprovalPatch 조회
4. candidate/base/evidence hash 검증
5. operation을 path 정렬 순서로 적용
6. alias 품질·manifest schema·승인 범위 외 delta 검증
7. active content hash 계산
8. provenance sidecar 작성
9. 두 임시 파일 fsync
10. provenance를 먼저 replace하고 active manifest를 replace
```

provenance가 먼저 교체된 짧은 구간에는 old active hash가 맞지 않으므로 runtime audit가 fail-closed한다. 새 active가 교체된 뒤에만 두 hash가 일치한다.

- [ ] `ManifestMergeResult`에 다음 필드를 추가한다.

```python
provenance_path: Path
active_content_hash: str
trusted_base_content_hash: str
applied_operation_count: int
quarantined_concept_ids: tuple[str, ...]
```

- [ ] legacy approved/applied candidate에 patch가 없으면 병합 전체를 중단하고 candidate id를 포함한 `LegacyApprovalUnverifiableError`를 반환한다. legacy payload를 전체 승인으로 간주하지 않는다.

- [ ] 같은 inputs를 두 번 병합해 active content hash와 provenance operations가 동일한지 검증한다. 생성 시각만 달라도 content hash는 같아야 한다.

- [ ] manifest schema를 registry가 실제 허용하는 generic planner/retrieval field와 일치시킨다. `clarification_questions`, `required_evidence`, `lexical_priority_terms`는 string list로만 허용하고 임의의 보험 정답 field를 schema에 추가하지 않는다.

- [ ] focused tests를 실행한다.

Run:

```bash
pytest tests/test_ontology_manifest_merge.py tests/test_ontology_approval_integrity.py -v
```

Expected: evidence-only isolation, stale rejection, legacy rejection, idempotence, existing alias conflict 검사가 모두 통과한다.

## Task 6: dry-run을 실제 expected diff와 integrity audit로 바꾼다

**Files:**

- Modify: `scripts/ontology_review.py`
- Modify: `src/ingest/knowledge_apply.py`
- Create: `scripts/audit_ontology_approval_integrity.py`
- Create: `tests/test_ontology_review_cli.py`
- Modify: `tests/test_knowledge_apply.py`

- [ ] `--dry-run`이 단순 count가 아니라 임시 디렉터리에서 실제 merge와 audit를 수행하는 실패 테스트를 추가한다.

Required output shape:

```json
{
  "status": "dry_run",
  "trusted_base_content_hash": "sha256",
  "expected_active_content_hash": "sha256",
  "applied_operations": [],
  "quarantined_concept_ids": [],
  "legacy_unverifiable_candidate_ids": [],
  "concept_diffs": [],
  "graph_rebuild_required": true
}
```

- [ ] `scripts/audit_ontology_approval_integrity.py` CLI를 구현한다.

```bash
python scripts/audit_ontology_approval_integrity.py \
  --base data/ontology/concepts.json \
  --base-lock data/ontology/policies/base_manifest.lock.json \
  --active data/ontology/concepts.active.json \
  --provenance data/ontology/concepts.active.provenance.json \
  --format json
```

Exit codes:

- `0`: 모든 active delta가 valid
- `2`: quarantined 또는 legacy_unverifiable 존재
- `3`: stale/global hash mismatch
- `4`: 입력 손상 또는 schema 오류

- [ ] `scripts/ontology_review.py --build-base-lock` action을 추가한다. 이 action은 입력 manifest에서 deterministic lock JSON을 만들 뿐 active manifest, review log, GraphDB를 변경하지 않는다. `--base`, `--source-commit`, `--review-record-id`, `--output`을 필수로 받는다.

- [ ] `knowledge_apply.preflight()`는 이 dry-run 결과가 `valid`가 아니면 source promotion, active merge, Graph rebuild를 시작하지 않는다.

- [ ] `apply_reviews()`는 dry-run과 실제 apply가 같은 merge 함수를 사용하게 한다. dry-run 전용 우회 병합 로직을 만들지 않는다.

- [ ] applied review row에 다음을 append한다.

```json
{
  "candidate_id": "candidate-id",
  "candidate_payload_hash": "sha256",
  "approval_patch_hash": "sha256",
  "active_content_hash": "sha256",
  "applied_operation_paths": [],
  "applied_at": "ISO-8601"
}
```

- [ ] focused tests를 실행한다.

Run:

```bash
pytest tests/test_ontology_review_cli.py tests/test_knowledge_apply.py -v
```

Expected: real dry-run diff, nonzero integrity exit, knowledge apply fail-closed, append-only applied log가 통과한다.

## Task 7: runtime registry가 concept-level integrity를 강제하게 한다

**Files:**

- Modify: `src/ontology/registry.py`
- Modify: `src/ontology/__init__.py`
- Modify: `tests/test_ontology_registry.py`
- Modify: `src/api/routes/admin.py`
- Modify: `tests/test_api_admin.py`

- [ ] valid concept만 planner/retrieval/decision/graph seed에 노출되는 테스트를 먼저 추가한다.

```python
def test_registry_excludes_only_unproven_concepts(tmp_path: Path) -> None:
    registry = OntologyRegistry(
        manifest_path=_active_with_valid_and_unproven_concepts(tmp_path),
        base_manifest_path=_trusted_base(tmp_path),
        base_lock_path=_trusted_lock(tmp_path),
        provenance_path=_provenance_for_only_valid_concept(tmp_path),
    )
    assert [concept.concept_id for concept in registry.concepts] == ["cond.valid"]
    assert registry.integrity_report.quarantined_concept_ids == ("cond.unproven",)
    assert registry.find_matches("격리 표현") == []
```

- [ ] `OntologyRegistry` 생성자에 선택 가능한 integrity inputs를 추가한다.

```python
def __init__(
    self,
    manifest_path: str | Path = DEFAULT_ONTOLOGY_MANIFEST,
    *,
    base_manifest_path: str | Path = BASE_ONTOLOGY_MANIFEST,
    base_lock_path: str | Path = BASE_ONTOLOGY_LOCK,
    provenance_path: str | Path | None = None,
    enforce_integrity: bool = True,
) -> None:
```

- [ ] base manifest를 직접 로드할 때도 concept hash lock을 적용한다. active manifest를 로드할 때는 base lock과 provenance를 모두 적용한다.

- [ ] corrupted state JSON, missing provenance, stale hash는 warning만 남기고 원래 concept를 노출하지 않는다. integrity 경고에는 concept id와 code를 남기되 일반 사용자 답변에는 내부 path를 노출하지 않는다.

- [ ] 관리자 진단 payload에 aggregate만 추가한다.

```json
{
  "ontology_integrity": {
    "state": "quarantined",
    "manifest_content_hash": "sha256",
    "quarantined_concept_count": 1,
    "issue_counts": {"UNAPPROVED_ACTIVE_DELTA": 1}
  }
}
```

민감하지 않은 관리자 상세 endpoint에서만 concept id와 path를 조회한다.

- [ ] focused tests를 실행한다.

Run:

```bash
pytest tests/test_ontology_registry.py tests/test_api_admin.py -v
```

Expected: valid concept 보존, unproven concept 격리, legacy manifest 호환, 관리자 aggregate가 통과한다.

## Task 8: GraphDB가 검증된 registry만 seed하고 manifest hash를 기록하게 한다

**Files:**

- Modify: `src/graph/extractors.py`
- Modify: `src/graph/build.py`
- Modify: `scripts/build_graph_index.py`
- Modify: `tests/test_graph_build_active_sources.py`
- Modify: `scripts/check_ontology_sync.py`
- Modify: `scripts/check_graph_index.py`
- Modify: `scripts/check_graph_vector_sync.py`

- [ ] quarantined concept가 Graph node/alias로 생성되지 않는 테스트를 먼저 추가한다.

```python
def test_graph_seed_omits_quarantined_registry_concepts(tmp_path: Path, monkeypatch) -> None:
    registry = _registry_with_one_valid_and_one_quarantined(tmp_path)
    monkeypatch.setattr("src.graph.extractors.get_default_ontology_registry", lambda: registry)
    graph_path = _build_minimal_graph(tmp_path)
    assert _node_ids(graph_path) == {"cond_valid"}
    assert "격리 표현" not in _aliases(graph_path)
```

- [ ] graph manifest와 DB manifest table에 다음 값을 기록한다.

```json
{
  "ontology_manifest_content_hash": "sha256",
  "ontology_provenance_content_hash": "sha256",
  "ontology_integrity_state": "valid",
  "ontology_quarantined_concept_count": 0
}
```

- [ ] `build_graph_index.py --strict`는 integrity state가 `valid`가 아니면 output temp DB를 publish하지 않는다.

- [ ] sync checks는 active/provenance/Graph hashes가 모두 일치해야 통과하도록 확장한다.

Run:

```bash
pytest tests/test_graph_build_active_sources.py -v
python scripts/check_ontology_sync.py
python scripts/check_graph_index.py --db data/index/graph/insurance_graph.sqlite
python scripts/check_graph_vector_sync.py
```

Expected: 격리 fixture 테스트는 통과한다. 로컬 운영 artifact가 없으면 check script는 명확한 `missing artifact` 결과를 반환하고 성공으로 위장하지 않는다.

## Task 9: 현재 incident의 correction dry-run만 생성한다

**Files:**

- Create: `data/ontology/policies/base_manifest.lock.json`
- Preserve: `docs/review_artifacts/2026-07-18-hair-loss-full-payload-correction-candidate.json`
- Create: `docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md`
- Generate outside git: `reports/ontology/2026-07-18-approval-integrity-dry-run.json`

- [ ] Task 1에서 복원한 pre-incident manifest로 lock payload를 생성한다.

Run:

```bash
python scripts/ontology_review.py \
  --build-base-lock \
  --base /tmp/ontology-trusted-base-before-23278c3.json \
  --source-commit "$(git rev-parse 23278c3^)" \
  --review-record-id docs/superpowers/specs/2026-07-18-approval-safe-conversational-evidence-resolution-design.md \
  --output /tmp/base_manifest.lock.proposed.json
python -m json.tool /tmp/base_manifest.lock.proposed.json >/dev/null
```

Expected: deterministic lock가 생성되며 현재 base에서 새로 들어온 concept들은 lock에 없다.

- [ ] proposed lock을 tracked policy path에 복사하기 전 hash와 concept count를 보고서에 기록하고, 코드 리뷰 범위에 lock diff를 포함한다.

- [ ] 현재 active snapshot이 있으면 base, proposed lock, active, provenance를 audit한다.

Run:

```bash
python scripts/audit_ontology_approval_integrity.py \
  --base data/ontology/concepts.json \
  --base-lock /tmp/base_manifest.lock.proposed.json \
  --active data/ontology/concepts.active.json \
  --provenance data/ontology/concepts.active.provenance.json \
  --format json
```

Expected: approval provenance가 없는 incident concept만 concept-level quarantine로 표시되고, 기존 trusted concept는 유지된다. 특정 개념 ID를 코드에 넣은 결과가 아니어야 한다.

- [ ] active snapshot이 없으면 실제 merge 함수 기반 dry-run으로 expected active를 생성한다.

Run only when `data/ontology/concepts.active.json` does not exist:

```bash
python scripts/ontology_review.py \
  --apply \
  --base data/ontology/concepts.json \
  --base-lock /tmp/base_manifest.lock.proposed.json \
  --dry-run
```

Expected: 파일을 쓰지 않고 trusted projection, approved operations, quarantine, expected active hash를 반환한다.

- [ ] full-payload correction candidate는 승인·apply하지 않는다. 보고서에는 현재 상태를 `unapproved forensic artifact`로 기록한다.

- [ ] 다음 active/Graph expected diff를 보고서에 포함한다.

```text
- trusted base retained concept count
- quarantined concept ids and generic reason codes
- approved operation count
- expected active content hash
- expected Graph ontology node/alias removals
- legacy unverifiable candidate ids
```

- [ ] 여기서 중단한다.

Stop condition: 사용자에게 code diff, lock diff, active expected diff, Graph expected diff, focused/full test 결과를 제시한다. `concepts.active.json` 교체, GraphDB rebuild, 서비스 재기동은 하지 않는다.

## Task 10: 전체 회귀와 자체 점검을 수행한다

**Files:**

- Verify: all files changed in Tasks 2-9
- Update: `docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md`

- [ ] focused ontology tests를 실행한다.

```bash
pytest \
  tests/test_ontology_approval_integrity.py \
  tests/test_ontology_review_store.py \
  tests/test_ontology_manifest_merge.py \
  tests/test_ontology_registry.py \
  tests/test_ontology_review_cli.py \
  tests/test_graph_build_active_sources.py -v
```

Expected: all pass.

- [ ] 관련 ingest/admin 회귀를 실행한다.

```bash
pytest tests/test_knowledge_apply.py tests/test_api_admin.py tests/test_extract_ontology_candidates_cli.py -v
```

Expected: all pass.

- [ ] 전체 Python 회귀를 실행한다.

```bash
pytest -q
```

Expected: all pass. 기존 기준선 실패가 있으면 같은 commit의 변경 전 격리 작업공간에서 재현하여 이번 변경과 독립임을 증명하고 보고서에 남긴다. skip/xfail로 숨기지 않는다.

- [ ] 금지된 지엽 분기와 임시 산출물을 검사한다.

```bash
rg -n "if .*탈모|cov\.hair_loss|cond\.disease_related_hair_loss" src scripts
git status --short
find . -name '*.tmp' -o -name '*.bak'
```

Expected: production `src/`, `scripts/`에 incident-specific 분기가 0건이며 임시 파일이 저장소에 없다. 테스트 fixture와 forensic docs의 문자열은 허용한다.

- [ ] 보고서에 다음을 기록한다.

```text
- 변경 파일과 역할
- baseline lock source commit/hash
- candidate/patch/provenance 계약
- quarantine 결과와 이유 code
- 실행 명령 및 pass/fail 수
- active apply 미수행 확인
- GraphDB rebuild 미수행 확인
- commit/push/deploy 미수행 확인
- 남은 운영 승인 항목
```

### Conditional commit checkpoint

사용자가 구현 검토 뒤 별도로 commit을 승인한 경우에만 의도한 파일을 명시적으로 stage한다.

```bash
git add \
  src/ontology/approval_integrity.py \
  src/ontology/review_store.py \
  src/ontology/manifest_merge.py \
  src/ontology/registry.py \
  src/ontology/__init__.py \
  src/ingest/knowledge_apply.py \
  src/graph/extractors.py \
  src/graph/build.py \
  src/api/routes/admin.py \
  scripts/ontology_review.py \
  scripts/audit_ontology_approval_integrity.py \
  scripts/build_graph_index.py \
  scripts/check_ontology_sync.py \
  scripts/check_graph_index.py \
  scripts/check_graph_vector_sync.py \
  scripts/ontology_review_local_ui.py \
  data/ontology/policies/review_policy.json \
  data/ontology/policies/base_manifest.lock.json \
  data/ontology/ontology_manifest.schema.json \
  src/api/schemas/knowledge.py \
  src/api/routes/knowledge.py \
  frontend/js/pages/admin.js \
  tests/test_ontology_approval_integrity.py \
  tests/test_ontology_review_store.py \
  tests/test_ontology_manifest_merge.py \
  tests/test_ontology_registry.py \
  tests/test_ontology_review_cli.py \
  tests/test_graph_build_active_sources.py \
  tests/test_knowledge_apply.py \
  tests/test_api_admin.py \
  tests/test_api_admin_knowledge.py \
  tests/test_admin_knowledge_frontend.mjs \
  tests/test_extract_ontology_candidates_cli.py \
  docs/275_APPROVAL_INTEGRITY_CONTAINMENT_REPORT.md
git diff --cached --check
git commit -m "fix(ontology): enforce field-level approval integrity"
```

Do not push at this checkpoint without a separate explicit request.

## Operational Apply Gate — Not Authorized by This Plan

다음 단계는 구현 완료가 아니라 별도 운영 승인 대상이다.

1. correction dry-run의 quarantined concept 목록 검토
2. base lock diff와 source commit 검토
3. corrected active manifest expected diff 검토
4. 임시 GraphDB의 ontology node/alias diff 검토
5. 운영 적용 승인
6. versioned temp active/provenance publish
7. 임시 GraphDB strict build 및 검사
8. GraphDB 원자 교체
9. 서비스 재기동
10. fail-closed smoke와 rollback 판정

운영 승인이 없으면 Task 10에서 종료한다.

## Completion Marker

Developer는 코드 구현·테스트·dry-run·보고서가 끝나고 active/Graph/runtime 변경을 수행하지 않았을 때 최종 응답 마지막 줄에 다음 marker를 정확히 남긴다.

```text
DEVELOPER_RELEASE_A_IMPLEMENTATION_READY_FOR_REVIEW
```
