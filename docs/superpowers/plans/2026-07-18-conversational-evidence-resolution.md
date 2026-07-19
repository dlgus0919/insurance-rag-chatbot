# 일반 질의 대화 연속성·근거 적용성 판정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` for each task and `superpowers:verification-before-completion` before reporting completion. Start this release only after Release A has a reviewed `valid` safe baseline.

**Goal:** 일반 보험 질의의 후속 발화를 이전 확인 요청과 연결하고, 사용자 진술·문서 권한·질문 관련성·현재 사례 적용성을 분리하여 해결된 질문 반복과 확정 근거 오표시 및 중복 출력을 제거한다.

**Architecture:** 기존 `messages`를 대화 원본으로 유지하고 assistant message의 `assistant_meta`에 versioned clarification state를 append한다. 서버는 라우팅 전에 최근 metadata에서 `ResolvedConversationContext`를 복원하고 router, Graph planner/retriever, generic `EvidenceAssessment`가 같은 context를 사용하게 한다. 응답 본문과 구조화 panel은 하나의 display contract에서 파생하며, user/assistant/meta 저장 commit 뒤에만 확정 `final`과 `done` SSE를 보낸다.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async SQLite, existing GraphQueryPlanner/GraphRetriever, ontology registry, Python dataclasses, static SPA JavaScript, SSE, pytest/anyio, Node test runner, Playwright.

**Approved design:** `docs/superpowers/specs/2026-07-18-approval-safe-conversational-evidence-resolution-design.md`

**Release dependency:** `docs/superpowers/plans/2026-07-18-ontology-approval-integrity-containment.md`

## Global Constraints

- `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`를 최우선 적용한다.
- Release A의 active manifest/provenance/Graph hash가 모두 `valid`인 safe baseline에서만 Release B를 배포한다.
- production 코드에 `탈모`, 특정 질환, 특정 테스트 문장, 특정 concept id 기반 분기를 추가하지 않는다.
- 이번 대화 문구는 테스트 fixture에서만 사용할 수 있고 production source가 fixture를 import하면 안 된다.
- 사용자 발화는 session-scoped assertion이며 ontology fact, GraphDB fact, 의료 지식 또는 보험 보장 판단으로 승격하지 않는다.
- 승인 provenance가 있는 `ApprovedDecisionProfile`만 deterministic decision에 사용한다.
- 승인 프로필이 없으면 관련 문서나 사용자 진술이 있어도 확정 판단으로 만들지 않는다.
- 새 chat table을 만들거나 기존 메시지를 migration·재작성하지 않는다.
- 보험금 계산 snapshot metadata와 key 충돌을 만들지 않는다.
- 추가 LLM 호출을 필수화하지 않는다. 불명확한 해석은 한 질문으로 재확인한다.
- stage, commit, push, DGX main 반영, 서비스 재기동은 별도 승인 전까지 하지 않는다.

## Fixed Data Contracts

### Assistant metadata namespace

기존 source list의 `__kind=assistant_meta` row 안에 다음 namespace를 추가한다.

```json
{
  "__kind": "assistant_meta",
  "graph_result": {},
  "warnings": [],
  "claim_snapshot": null,
  "turn": {
    "schema_version": 1,
    "turn_id": "uuid",
    "user_message_id": 101,
    "assistant_message_id": 102
  },
  "conversation_state": {
    "schema_version": 1,
    "clarification_request": {
      "schema_version": 1,
      "request_id": "uuid",
      "topic_anchor": "canonical-topic-anchor",
      "origin_turn_id": "uuid",
      "status": "pending",
      "slots": [],
      "ontology_manifest_hash": "sha256",
      "query_scope": {
        "route": "general",
        "intent": "claim_condition_review",
        "policy_generation": "5th",
        "doc_filter": [],
        "index_mode": "v2_only"
      }
    },
    "user_assertions": []
  }
}
```

사용자 원문은 metadata에 복제하지 않고 `source_message_id`로 원래 message row를 참조한다.

### Clarification values

```python
ClarificationValue = Literal["yes", "no", "unknown", "asserted_alternative"]
AssertionResolution = Literal[
    "explicit_ui_selection",
    "explicit_text_value",
    "confirmed_by_user",
    "asserted_alternative",
]
```

`asserted_alternative`는 “사용자가 pending 질문에 대한 다른 사실을 명시했다”는 대화 상태만 뜻한다. 해당 조건의 반대가 의학적으로 참이거나 보장된다는 의미로 해석하지 않는다.

### Evidence axes

```python
EvidenceAuthority = Literal["own_policy", "standard_policy", "other_document"]
EvidenceRelevance = Literal["direct_clause", "related_clause", "unrelated"]
EvidenceApplicability = Literal["applies", "does_not_apply", "unknown"]
EvidenceDecisionStatus = Literal[
    "supported",
    "supported_exclusion",
    "unresolved",
    "no_direct_evidence",
]
```

네 축을 하나의 문자열 status로 합치지 않는다.

---

## Task 1: Release A safe baseline과 기존 채팅 계약을 확인한다

**Files:**

- Inspect: `src/api/models.py`
- Inspect: `src/api/schemas/chat.py`
- Inspect: `src/api/routes/chat.py`
- Inspect: `src/api/routes/sessions.py`
- Inspect: `src/api/rag_service.py`
- Inspect: `src/graph/query_planner.py`
- Inspect: `src/graph/retriever.py`
- Inspect: `frontend/js/pages/chat.js`
- Create during implementation report: `docs/276_CONVERSATIONAL_EVIDENCE_RESOLUTION_REPORT.md`

- [ ] Release A integrity를 먼저 확인한다.

Run:

```bash
python scripts/audit_ontology_approval_integrity.py \
  --base data/ontology/concepts.json \
  --base-lock data/ontology/policies/base_manifest.lock.json \
  --active data/ontology/concepts.active.json \
  --provenance data/ontology/concepts.active.provenance.json \
  --format json
```

Expected: exit `0`, state `valid`, quarantined concept count `0`. 이 조건을 충족하지 않으면 Release B 구현을 시작하지 않고 `BLOCKED_BY_RELEASE_A_INTEGRITY`로 보고한다.

- [ ] 기존 DB schema와 metadata 호환성을 기록한다.

Run:

```bash
rg -n "class ChatMessage|assistant_meta|claim_snapshot|canonical_decision|clarification" \
  src/api src/rag src/graph frontend/js/pages/chat.js tests
```

Expected: `messages.sources` JSON 안에 assistant metadata가 저장되며 별도 conversation state table은 없다.

- [ ] 현재 실패 순서를 회귀 증거로 기록한다.

```text
current question only → resolve_query_route
current question only → GraphRetriever.retrieve
current question only → build_policy_clause_decision
final SSE → database commit
answer text + canonical summary/authority → duplicate frontend rendering
```

## Task 2: versioned conversation state를 pure module로 추가한다

**Files:**

- Create: `src/rag/conversation_context.py`
- Create: `tests/test_conversation_context.py`

- [ ] 다음 dataclass 계약과 round-trip 테스트를 먼저 작성한다.

```python
@dataclass(frozen=True)
class ClarificationSlot:
    slot_id: str
    evidence_condition_id: str
    question: str
    allowed_values: tuple[Literal["yes", "no", "unknown"], ...]
    evidence_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class ConversationQueryScope:
    route: Literal["general", "quickcode", "formal"]
    intent: str
    policy_generation: Literal["4th", "5th"] | None
    doc_filter: tuple[str, ...]
    index_mode: Literal["v2_only", "v1_v2_combined"]


@dataclass(frozen=True)
class ClarificationRequest:
    schema_version: int
    request_id: str
    topic_anchor: str
    origin_turn_id: str
    status: Literal["pending", "resolved", "superseded", "stale"]
    slots: tuple[ClarificationSlot, ...]
    ontology_manifest_hash: str
    query_scope: ConversationQueryScope


@dataclass(frozen=True)
class UserAssertion:
    assertion_id: str
    request_id: str
    slot_id: str
    value: ClarificationValue
    resolution: AssertionResolution
    source_message_id: int
    supersedes: str | None


@dataclass(frozen=True)
class ConversationState:
    schema_version: int
    clarification_request: ClarificationRequest | None
    user_assertions: tuple[UserAssertion, ...]
```

Required tests:

```python
def test_state_round_trip_keeps_message_reference_without_copying_user_text() -> None:
    state = _resolved_state(source_message_id=41)
    payload = serialize_conversation_state(state)
    assert payload["user_assertions"][0]["source_message_id"] == 41
    assert "user_text" not in json.dumps(payload, ensure_ascii=False)
    assert parse_conversation_state(payload) == state


def test_missing_legacy_metadata_is_schema_v0_without_inferred_state() -> None:
    state, warnings = restore_conversation_state(
        _legacy_history(),
        current_manifest_hash="manifest-a",
    )
    assert state.schema_version == 0
    assert state.clarification_request is None
    assert state.user_assertions == ()
    assert warnings == ()
```

- [ ] malformed state는 해당 row만 무시하고 warning을 반환하는 테스트를 추가한다.

```python
state, warnings = restore_conversation_state(_history_with_broken_state())
assert state.clarification_request is None
assert [warning.code for warning in warnings] == ["CONVERSATION_STATE_INVALID"]
```

- [ ] 다음 pure functions를 구현한다.

```python
def parse_conversation_state(payload: Mapping[str, Any]) -> ConversationState:
    """Parse schema v1 strictly; reject unknown status/value combinations."""


def serialize_conversation_state(state: ConversationState) -> dict[str, Any]:
    """Emit a bounded schema v1 payload without duplicating user message text."""


def restore_conversation_state(
    history: Sequence[ChatMessage],
    *,
    current_manifest_hash: str,
    max_messages: int = 40,
) -> tuple[ConversationState, tuple[ConversationStateWarning, ...]]:
    """Read the newest valid assistant_meta state and mark hash mismatch stale."""
```

- [ ] 상태 payload bound를 적용한다.

```text
- newest clarification request: at most 1
- slots per request: at most 8, but UI exposes highest-priority 1
- user assertions retained: at most 20
- evidence chunk ids per slot: at most 8
- message scan: newest 40 rows
```

- [ ] focused tests를 실행한다.

Run:

```bash
pytest tests/test_conversation_context.py -v
```

Expected: round-trip, legacy, malformed JSON, stale manifest, bound tests all pass.

## Task 3: 후속 발화를 주제 독립적으로 해석한다

**Files:**

- Modify: `src/rag/conversation_context.py`
- Modify: `tests/test_conversation_context.py`
- Reuse: `src/rag/search_intent.py`

- [ ] continuation 결과 계약을 추가한다.

```python
ContinuationKind = Literal[
    "new_question",
    "clarification_response",
    "topic_switch",
    "ambiguous_continuation",
]


@dataclass(frozen=True)
class AssertionDraft:
    request_id: str
    slot_id: str
    value: ClarificationValue
    resolution: AssertionResolution
    supersedes: str | None


@dataclass(frozen=True)
class ResolvedConversationContext:
    kind: ContinuationKind
    current_question: str
    route_query: str
    retrieval_query: str
    topic_anchor: str
    query_scope: ConversationQueryScope
    graph_clarification: dict[str, dict[str, str]]
    state_before: ConversationState
    state_after_draft: ConversationState
    assertion_draft: AssertionDraft | None
    pending_request: ClarificationRequest | None
```

- [ ] 다음 처리 순서를 회귀 테스트로 고정한다.

```text
1. no pending request → new_question
2. valid request_id + slot_id + allowed value from UI → clarification_response
3. free text exact yes/no/unknown lexeme → clarification_response
4. short declarative alternative assertion → clarification_response with asserted_alternative
5. clear independent question with different intent/topic anchor → topic_switch
6. confidence tie → ambiguous_continuation and no assertion draft
```

- [ ] 범용 explicit text lexeme만 처리 policy로 둔다.

```python
EXPLICIT_VALUE_LEXEMES = {
    "yes": frozenset({"예", "네", "맞습니다", "해당합니다"}),
    "no": frozenset({"아니오", "아닙니다", "해당하지 않습니다"}),
    "unknown": frozenset({"모름", "모릅니다", "확인되지 않음"}),
}
```

보험 개념이나 질환 표현을 이 map에 넣지 않는다.

- [ ] 자연스러운 대체 진술을 반대 조건으로 추론하지 않는 테스트를 추가한다.

```python
def test_declarative_followup_is_preserved_as_alternative_without_inverting_condition() -> None:
    context = resolve_conversation_context(
        question="의사 진단을 받은 질병성입니다.",
        history=_pending_fixture_history(),
        explicit_clarification={},
        current_manifest_hash="manifest-a",
    )
    assert context.kind == "clarification_response"
    assert context.assertion_draft is not None
    assert context.assertion_draft.value == "asserted_alternative"
    assert context.graph_clarification == {}
    assert context.pending_request is None
    assert context.state_after_draft.clarification_request.status == "resolved"
```

이 문구는 회귀 fixture일 뿐 production resolver에서 참조하지 않는다.

- [ ] 명확한 topic switch와 ambiguous continuation 테스트를 합성 주제로 추가한다.

```python
def test_independent_claim_document_question_supersedes_pending_request() -> None:
    context = resolve_conversation_context(
        question="통원 청구서류는 무엇인가요?",
        history=_pending_fixture_history(topic_anchor="치료 목적 확인"),
        explicit_clarification={},
        current_manifest_hash="manifest-a",
    )
    assert context.kind == "topic_switch"
    assert context.state_after_draft.clarification_request.status == "superseded"
```

- [ ] `route_query`와 `retrieval_query`를 current short sentence만으로 만들지 않는다.

```text
route_query = topic_anchor + current assertion category + unresolved source condition labels
retrieval_query = original topic anchor + current user message + confirmed UI filters + unresolved evidence conditions
```

사용자 원문은 request 처리 중에만 query 조립에 사용하고 persisted metadata에는 복제하지 않는다.

- [ ] pending request의 `query_scope`를 후속 turn에 보존한다. 현재 UI가 다른 policy generation 또는 document scope를 명시적으로 선택하면 이전 request를 `superseded`로 닫고 새 scope로 다시 판정한다. 서로 다른 세대·문서 범위를 한 assessment에 조용히 섞지 않는다.

- [ ] focused tests를 실행한다.

Run:

```bash
pytest tests/test_conversation_context.py -v
```

Expected: explicit, free-text, alternative, unknown, supersedes, topic switch, ambiguous cases all pass.

## Task 4: 승인형 generic EvidenceAssessment 엔진을 추가한다

**Files:**

- Create: `src/rag/evidence_assessment.py`
- Create: `tests/test_evidence_assessment.py`
- Modify: `src/ontology/registry.py`
- Modify: `tests/test_ontology_registry.py`

- [ ] 승인 decision profile 계약을 정의한다.

```python
@dataclass(frozen=True)
class ApprovedEvidenceCondition:
    condition_id: str
    question: str
    required_values: tuple[Literal["yes", "no"], ...]
    evidence_chunk_ids: tuple[str, ...]
    required_evidence: tuple[str, ...]
    priority: int


@dataclass(frozen=True)
class ApprovedDecisionProfile:
    profile_id: str
    concept_id: str
    approval_patch_id: str
    effect: Literal["coverage", "exclusion", "review"]
    clause_terms: tuple[str, ...]
    source_chunk_ids: tuple[str, ...]
    conditions: tuple[ApprovedEvidenceCondition, ...]
    supported_text: str
    unresolved_text: str
```

프로필은 candidate의 `runtime_properties.approved_decision_profiles`가 승인 patch로 active concept의 `properties.approved_decision_profiles`에 투영된 경우에만 읽는다. candidate control `properties`, legacy unverified concept, quarantined concept은 읽지 않는다.

- [ ] registry accessor를 추가한다.

```python
def approved_decision_profiles(self) -> tuple[ApprovedDecisionProfile, ...]:
    """Return only profiles covered by valid approval provenance paths."""
```

- [ ] EvidenceAssessment 결과 계약을 정의한다.

```python
@dataclass(frozen=True)
class EvidenceAssessment:
    authority: EvidenceAuthority
    relevance: EvidenceRelevance
    applicability: EvidenceApplicability
    decision: EvidenceDecisionStatus
    primary_text: str
    conditions: tuple[EvidenceConditionResult, ...]
    source_evidence: tuple[dict[str, Any], ...]
    pending_slots: tuple[ClarificationSlot, ...]
```

- [ ] 다음 generic decision table을 테스트로 고정한다.

| Profile/Evidence | Condition state | Relevance | Applicability | Decision |
| --- | --- | --- | --- | --- |
| approved profile + exact source chunk | all required values match | direct_clause | applies | effect에 따라 supported 또는 supported_exclusion |
| approved profile + exact source chunk | one confirmed value conflicts | direct_clause | does_not_apply | unresolved |
| approved profile + exact source chunk | pending/unknown/asserted_alternative | direct_clause | unknown | unresolved |
| approved profile + related chunk only | any | related_clause | unknown | unresolved |
| no approved profile | any | unrelated | unknown | no_direct_evidence |

- [ ] 질문 생성은 unknown condition 중 priority가 가장 높은 하나만 반환한다.

```python
pending = sorted(unresolved_conditions, key=lambda item: (item.priority, item.condition_id))[:1]
```

- [ ] source authority는 selected evidence metadata에서 계산한다.

```python
def source_authority(metadata: Mapping[str, Any]) -> EvidenceAuthority:
    if metadata.get("is_own_company") is True:
        return "own_policy"
    if metadata.get("product_type") == "표준약관" or metadata.get("doc_short") == "표준약관":
        return "standard_policy"
    return "other_document"
```

- [ ] 사용자 assertion만으로 `supported`나 `supported_exclusion`이 되지 않는 테스트를 추가한다.

- [ ] 특정 질환을 사용하지 않은 두 개 이상의 합성 profile fixture로 모든 decision table row를 검증한다.

- [ ] focused tests를 실행한다.

Run:

```bash
pytest tests/test_evidence_assessment.py tests/test_ontology_registry.py -v
```

Expected: authority, relevance, applicability, decision의 독립 축과 단일 pending slot이 모두 통과한다.

## Task 5: topic-specific deterministic decision을 generic engine으로 교체한다

**Files:**

- Modify: `src/rag/source_grounded_answers.py`
- Modify: `src/api/rag_service.py`
- Modify: `src/rag/pipeline.py`
- Modify: `tests/test_source_grounded_answers.py`
- Modify: `tests/test_api_rag_service_payload.py`
- Modify: `tests/test_pipeline.py`

- [ ] 현재 `_hair_loss_profile()`과 `build_policy_clause_decision()`이 topic string/profile field에 의존하는 회귀 테스트를 generic fixture로 대체한다.

- [ ] `PolicyClauseDecision` 대신 다음 adapter contract를 사용한다.

```python
@dataclass(frozen=True)
class GroundedDisplayResult:
    answer: str
    payload: dict[str, Any]
    chunks: list[Chunk]


def build_grounded_display_result(
    context: ResolvedConversationContext,
    chunks: list[Chunk],
    profiles: Sequence[ApprovedDecisionProfile],
) -> GroundedDisplayResult | None:
    assessment = evaluate_evidence(context, chunks, profiles)
    if assessment.decision == "no_direct_evidence":
        return None
    return GroundedDisplayResult(
        answer=assessment.primary_text,
        payload=assessment_to_payload(assessment),
        chunks=select_assessment_chunks(chunks, assessment),
    )
```

- [ ] `src/rag/source_grounded_answers.py`에서 다음 production symbols와 topic-specific branch를 제거한다.

```text
_hair_loss_profile
_matches_any_term used only by that profile
build_policy_clause_decision
profile-specific summary/alternative cause selection
```

HIRA code guard, generation deductible comparison, other source-backed generic helpers는 유지한다.

- [ ] `RagPipeline.answer()`의 direct 사용 경로는 history가 없으므로 `new_question`용 context를 명시적으로 생성해 같은 generic engine을 호출한다. 별도의 topic-specific compatibility branch를 남기지 않는다.

```python
context = ResolvedConversationContext.for_new_question(
    question=question,
    policy_generation=policy_generation,
    doc_filter=tuple(doc_filter or ()),
    index_mode="v2_only",
)
```

- [ ] active ontology에 새 질환 profile이나 alias를 추가하지 않는다. generic profile 테스트는 fixture manifest와 fixture provenance를 사용한다.

- [ ] `apply_policy_clause_decision()`을 `apply_evidence_assessment()`로 교체하고 legacy `canonical_decision`은 과거 message rendering에만 남긴다.

```python
def apply_evidence_assessment(
    graph_payload: dict[str, Any] | None,
    result: GroundedDisplayResult | None,
) -> dict[str, Any] | None:
    payload = deepcopy(graph_payload) if isinstance(graph_payload, dict) else {}
    if result is None:
        return payload or None
    payload["schema_version"] = 2
    payload["display"] = {"primary_text": result.answer}
    payload["decision"] = result.payload["decision"]
    payload["clarification"] = result.payload["clarification"]
    return payload
```

- [ ] focused tests를 실행한다.

Run:

```bash
pytest \
  tests/test_source_grounded_answers.py \
  tests/test_evidence_assessment.py \
  tests/test_api_rag_service_payload.py \
  tests/test_pipeline.py -v
```

Expected: topic-specific production branch 부재, generic direct/related/no-evidence 판단, legacy helper 회귀가 통과한다.

## Task 6: 하나의 ResolvedConversationContext를 router·Graph·retrieval에 연결한다

**Files:**

- Modify: `src/api/routes/chat.py`
- Modify: `src/api/rag_service.py`
- Modify: `src/rag/query_router.py`
- Modify: `src/graph/retriever.py`
- Modify: `tests/test_query_router.py`
- Modify: `tests/test_graph_query_planner.py`
- Modify: `tests/test_api_rag_service_payload.py`
- Modify: `tests/test_api_chat_stream.py`

- [ ] `GraphRetriever`가 clarification을 planner에 전달하는 실패 테스트를 추가한다.

```python
def test_graph_retriever_passes_confirmed_clarification_to_planner(tmp_path: Path) -> None:
    retriever = GraphRetriever(tmp_path / "missing.sqlite")
    result = retriever.retrieve(
        "후속 답변",
        clarification={
            "selections": [
                {
                    "group": "policy_generation",
                    "value": "5세대",
                    "raw": "",
                }
            ]
        },
    )
    assert result.plan.policy_generation == "5th"
```

- [ ] signatures를 다음처럼 확장한다.

```python
def resolve_query_route(
    question: str,
    filters: dict | None = None,
    *,
    conversation_context: ResolvedConversationContext | None = None,
) -> QueryRoute:


def GraphRetriever.retrieve(
    self,
    question: str,
    clarification: dict | None = None,
) -> GraphRetrievalResult:


async def prepare_retrieved_context(
    pipeline: RagPipeline,
    question: str,
    top_k: int,
    history: list[ChatMessage],
    filters: dict | None = None,
    *,
    conversation_context: ResolvedConversationContext,
    auto_params: AutoRagParams | None = None,
    policy_generation: str | None = None,
):
```

- [ ] `chat_stream()` 처리 순서를 바꾼다.

```text
ensure session
load history
restore conversation state
resolve current continuation
emit session identity
claim follow-up detection only when context is new_question/topic_switch
resolve route with context.route_query
GraphRetriever.retrieve(context.retrieval_query, context.graph_clarification)
document retrieval with context.retrieval_query
EvidenceAssessment with same context
persist turn and state
emit final/done
```

- [ ] explicit `ChatRequest.clarification`은 pending request id/slot id/value가 server state와 모두 일치할 때만 사용한다. 불일치하면 `CLARIFICATION_SELECTION_STALE` warning과 재확인 한 질문을 반환한다.

- [ ] claim thread follow-up 경로는 기존 snapshot resolver를 유지한다. 일반 clarification response가 claim recalculation intent detector로 잘못 들어가지 않도록 context kind로 경계를 둔다.

- [ ] route/retrieval/Graph가 모두 같은 topic anchor를 사용했는지 debug payload에 hash만 기록한다.

```json
{
  "conversation_context": {
    "kind": "clarification_response",
    "topic_anchor_hash": "sha256",
    "pending_slot_count": 0
  }
}
```

- [ ] focused tests를 실행한다.

Run:

```bash
pytest \
  tests/test_query_router.py \
  tests/test_graph_query_planner.py \
  tests/test_api_rag_service_payload.py \
  tests/test_api_chat_stream.py -v
```

Expected: 후속 발화가 original route/topic을 유지하고, topic switch와 claim follow-up 경계가 통과한다.

## Task 7: turn idempotency와 저장 후 final 계약을 구현한다

**Files:**

- Modify: `src/api/schemas/chat.py`
- Modify: `src/api/routes/chat.py`
- Modify: `tests/test_api_chat_stream.py`
- Modify: `tests/test_api_sessions_db.py`

- [ ] `ChatRequest`에 client-stable turn id를 추가한다.

```python
turn_id: str | None = Field(default=None, min_length=8, max_length=64)
```

서버는 누락 시 UUID를 발급하고 첫 `session` SSE에서 반환한다.

- [ ] persistence 결과 계약을 추가한다.

```python
@dataclass(frozen=True)
class PersistedTurn:
    session_id: str
    turn_id: str
    user_message_id: int
    assistant_message_id: int
    assistant_meta: dict[str, Any]
    replayed: bool = False
```

- [ ] `_persist_turn()`이 user id를 받은 뒤 assertion reference를 완성하도록 구현한다.

```python
async def _persist_turn(
    db: AsyncSession,
    session_id: str,
    turn_id: str,
    query: str,
    answer: str,
    sources: list[dict],
    *,
    graph_payload: dict | None = None,
    warnings: list[dict] | None = None,
    conversation_context: ResolvedConversationContext | None = None,
) -> PersistedTurn:
    existing = await _find_persisted_turn(db, session_id, turn_id, recent_limit=60)
    if existing is not None:
        return existing
    user_message = ChatMessage(session_id=session_id, role="user", content=query, sources=None)
    db.add(user_message)
    await db.flush()
    state = finalize_state_with_source_message_id(conversation_context, user_message.id)
    assistant_meta = build_assistant_meta(turn_id, user_message.id, graph_payload, warnings, state)
    assistant_message = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=answer,
        sources=[*sources, assistant_meta],
    )
    db.add(assistant_message)
    await db.flush()
    assistant_meta = {
        **assistant_meta,
        "turn": {
            **assistant_meta["turn"],
            "assistant_message_id": assistant_message.id,
        },
    }
    assistant_message.sources = [*sources, assistant_meta]
    await db.commit()
    return PersistedTurn(
        session_id=session_id,
        turn_id=turn_id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        assistant_meta=assistant_meta,
    )
```

assistant flush 뒤 nested dict를 in-place 수정하지 않고 `assistant_message.sources` 전체에 새 list를 재할당하여 SQLAlchemy JSON 변경 추적을 보장한다.

- [ ] SSE 순서를 회귀 테스트로 고정한다.

```text
status/session/sources/graph/warning/token(provisional)
database commit
final
done(persisted=true)
```

Required failure assertion:

```python
stream = await _chat_stream_with_persist_failure()
assert "event: error" in stream
assert "event: final" not in stream
assert "event: done" not in stream
```

- [ ] claim follow-up branch도 final-before-persist 순서를 같은 방식으로 수정한다.

- [ ] retry가 같은 turn id와 session id로 들어오면 새 message를 추가하지 않고 저장된 answer/meta를 replay한다.

```python
assert await _message_count(session_id) == 2
assert second_result.replayed is True
```

- [ ] focused tests를 실행한다.

Run:

```bash
pytest tests/test_api_chat_stream.py tests/test_api_sessions_db.py -v
```

Expected: success ordering, persist failure, idempotent retry, claim follow-up ordering 모두 통과한다.

## Task 8: 단일 출력 계약과 legacy renderer를 구현한다

**Files:**

- Modify: `frontend/js/pages/chat.js`
- Modify: `tests/test_frontend_assistant_display.mjs`
- Modify: `src/api/routes/sessions.py`
- Modify: `tests/test_api_chat_stream.py`
- Modify: `tests/test_api_sessions_db.py`

- [ ] schema v2 UI payload에서 primary text를 한 번만 렌더링하는 실패 테스트를 추가한다.

```javascript
test('renders schema v2 primary text once and omits duplicate decision summary', () => {
  const payload = {
    schema_version: 2,
    display: { primary_text: '근거 적용 여부를 추가 확인해야 합니다.' },
    decision: {
      status_label: '추가 확인 필요',
      summary: '근거 적용 여부를 추가 확인해야 합니다.',
      authority_note: '표준약관 직접 조항입니다.',
      conditions: [{ label: '조건 A', status: 'unknown' }],
    },
    clarification: { pending_slots: [{ slot_id: 'slot-a', question: '조건 A인가요?' }] },
  };
  const html = renderAssistantResultHtml(payload);
  assert.equal((html.match(/근거 적용 여부를 추가 확인해야 합니다\./g) || []).length, 1);
  assert.equal((html.match(/추가 확인 필요/g) || []).length, 1);
});
```

- [ ] renderer 우선순위를 고정한다.

```text
schema v2 → display.primary_text + decision details + one pending clarification + sources
legacy canonical_decision → existing compatibility renderer with duplicate normalization
no structured payload → model answer + sources
```

- [ ] schema v2 decision panel에는 status, applicability, condition statuses, source evidence만 표시한다. `summary`와 `authority_note`가 primary text에 이미 반영되었으면 반복하지 않는다.

- [ ] clarification panel은 `clarification.pending_slots[0]`만 표시하고, resolved slot과 required evidence 중복을 제거한다.

- [ ] explicit selection용 generic 버튼을 렌더링한다.

```html
<button data-clarification-value="yes">예</button>
<button data-clarification-value="no">아니오</button>
<button data-clarification-value="unknown">모름</button>
```

버튼 payload는 server-issued `request_id`, `slot_id`, allowed value만 전송한다. 자연어 입력은 빈 `clarification`으로 전송하여 서버가 history와 대조한다.

- [ ] export는 primary text, decision details, sources를 각각 한 번만 조합한다. internal `conversation_state`, turn id, user assertion id는 export하지 않는다.

- [ ] Node와 Python focused tests를 실행한다.

Run:

```bash
node --test tests/test_frontend_assistant_display.mjs
pytest tests/test_api_chat_stream.py tests/test_api_sessions_db.py -v
```

Expected: v2 single rendering, legacy compatibility, export internal metadata filtering 모두 통과한다.

## Task 9: frontend retry가 session/turn identity를 보존하게 한다

**Files:**

- Modify: `frontend/js/pages/chat.js`
- Modify: `tests/e2e/chat.spec.js`
- Modify: `tests/test_frontend_assistant_display.mjs`

- [ ] optimistic user row에 turn id를 저장하고 재시도에서 재사용한다.

```javascript
function getOrCreateTurnId(row) {
  const existing = row?.dataset?.turnId;
  if (existing) return existing;
  const turnId = crypto.randomUUID();
  if (row) row.dataset.turnId = turnId;
  return turnId;
}
```

- [ ] `session` SSE를 받으면 `done` 전이라도 retry target session id만 보존하되, persisted history로 표시하지 않는다.

- [ ] token row를 `provisional` class로 표시하고 `final` 뒤에만 확정 class로 전환한다. error가 오면 bot provisional row를 제거하고 user row에 retry action을 표시한다.

- [ ] 다음 E2E를 추가한다.

```text
1. 첫 요청에서 session event와 provisional token 수신
2. persist error 수신, final/done 없음
3. retry button 클릭
4. 같은 session_id와 turn_id 전송 확인
5. replayed done 수신
6. user/assistant bubble이 각각 한 개만 존재
```

- [ ] pending clarification button과 free-text follow-up의 payload 차이를 검증한다.

```text
button: clarification={request_id, slot_id, value}
free text: clarification={}
both: same session_id, new turn_id
```

- [ ] focused browser tests를 실행한다.

Run:

```bash
npx playwright test tests/e2e/chat.spec.js --project=chromium
```

Expected: persistence retry, explicit clarification, free-text continuation, legacy history rendering all pass.

## Task 10: 주제 독립 2-turn 회귀 세트를 추가한다

**Files:**

- Create: `tests/fixtures/conversation_evidence_profiles.json`
- Create: `tests/test_conversational_evidence_regressions.py`
- Modify: `tests/e2e/chat.spec.js`

- [ ] fixture는 source evidence와 approval provenance를 모두 가진 합성 profile만 포함한다.

```json
{
  "profiles": [
    {
      "profile_id": "fixture.treatment-purpose",
      "concept_id": "fixture.topic-a",
      "approval_patch_id": "fixture-approved-a",
      "effect": "review",
      "clause_terms": ["치료 목적"],
      "source_chunk_ids": ["fixture-chunk-a"],
      "conditions": [
        {
          "condition_id": "fixture.condition-a",
          "question": "치료 목적인가요?",
          "required_values": ["yes"],
          "evidence_chunk_ids": ["fixture-chunk-a"],
          "required_evidence": ["의사소견"],
          "priority": 10
        }
      ],
      "supported_text": "직접 조항의 조건이 확인되었습니다.",
      "unresolved_text": "직접 조항의 적용 조건을 확인해야 합니다."
    }
  ]
}
```

Fixture values are test expectations. Production code must not read `tests/fixtures`.

- [ ] 다음 matrix를 자동 검증한다.

| Scenario | Expected continuation | Expected applicability | Repeated question |
| --- | --- | --- | --- |
| explicit yes | clarification_response | applies | 0 |
| explicit no | clarification_response | does_not_apply | 0 |
| unknown | clarification_response | unknown | 0 |
| declarative alternative | clarification_response | unknown | 0 |
| changed assertion | clarification_response + supersedes | recomputed | 0 |
| independent question | topic_switch | new assessment | 0 |
| manifest hash changed | stale | unknown | 1 source-backed revalidation question |
| legacy message | new_question | normal legacy path | 0 |

- [ ] 이번 사용자 테스트 문장을 fixture input 중 하나로 넣되 expected result는 “대화 assertion을 보존하고 이전 질문을 반복하지 않으며, 승인 근거가 없으면 확정하지 않는다”로 제한한다.

- [ ] 질환이 아닌 합성 주제 3개 이상을 같은 matrix로 검증한다.

- [ ] focused regression을 실행한다.

Run:

```bash
pytest tests/test_conversational_evidence_regressions.py -v
npx playwright test tests/e2e/chat.spec.js --project=chromium
```

Expected: 실제 문구 1개와 주제 독립 합성 사례가 동일 generic code path로 통과한다.

## Task 11: 기존 기능 전체 회귀와 DGX 부하 경계를 검증한다

**Files:**

- Verify: all Release B changes
- Update: `docs/276_CONVERSATIONAL_EVIDENCE_RESOLUTION_REPORT.md`

- [ ] focused Python suite를 실행한다.

```bash
pytest \
  tests/test_conversation_context.py \
  tests/test_evidence_assessment.py \
  tests/test_conversational_evidence_regressions.py \
  tests/test_api_chat_stream.py \
  tests/test_api_rag_service_payload.py \
  tests/test_query_router.py \
  tests/test_graph_query_planner.py \
  tests/test_source_grounded_answers.py \
  tests/test_api_sessions_db.py -v
```

Expected: all pass.

- [ ] frontend unit/E2E를 실행한다.

```bash
node --test tests/test_frontend_assistant_display.mjs
npx playwright test tests/e2e/chat.spec.js --project=chromium
npm run test:e2e
```

Expected: focused Chromium과 전체 configured browser suite가 모두 통과한다.

- [ ] 기존 핵심 기능 회귀를 실행한다.

```bash
pytest \
  tests/test_procedure_grade_resolution.py \
  tests/test_claim_calculation_pipeline.py \
  tests/test_claim_thread_context.py \
  tests/test_api_admin.py \
  tests/test_graph_build_active_sources.py -v
```

Expected: 수술명·수술종수, HIRA 의도 gate, MX122 4세대 계산, 계산+일반 질의 연결, 채팅 열람, 관리자 GraphDB가 통과한다.

- [ ] 전체 Python suite를 실행한다.

```bash
pytest -q
```

Expected: all pass. 실패를 skip/xfail/삭제로 숨기지 않는다.

- [ ] 격리 DGX에서 추가 LLM 호출과 latency를 비교한다.

```text
baseline requests: 20
new requests: same 20
metrics: LLM invocation count, p50/p95 latency, peak GPU memory, Graph query count, assistant_meta bytes
acceptance: LLM invocation count unchanged; peak GPU memory regression <= 2%; metadata <= 16 KiB/turn
```

측정 도구는 기존 운영 로그와 `nvidia-smi`/DGX 상태 도구를 사용하고 민감한 질문 원문은 보고서에 남기지 않는다.

- [ ] production hardcoding과 임시 산출물을 점검한다.

```bash
rg -n "if .*탈모|질병성 탈모|cov\.hair_loss|fixture\.topic" src frontend scripts
git status --short
find . -name '*.tmp' -o -name '*.bak'
```

Expected: production source에 incident/fixture-specific branch가 0건이고 임시 산출물이 없다.

- [ ] 보고서에 다음을 기록한다.

```text
- ResolvedConversationContext 계약
- assertion과 ontology fact 분리 방식
- EvidenceAssessment four-axis 결과
- final-after-persist 및 retry idempotency 증거
- v2/legacy renderer 결과
- focused/full/Node/Playwright 결과
- LLM call, latency, GPU, metadata size 비교
- Release A integrity hash 재확인
- commit/push/deploy 미수행 확인
```

### Conditional commit checkpoint

사용자가 구현 검토 뒤 별도로 commit을 승인한 경우에만 의도한 파일을 명시적으로 stage한다.

```bash
git add \
  src/rag/conversation_context.py \
  src/rag/evidence_assessment.py \
  src/rag/source_grounded_answers.py \
  src/rag/pipeline.py \
  src/rag/query_router.py \
  src/api/schemas/chat.py \
  src/api/routes/chat.py \
  src/api/routes/sessions.py \
  src/api/rag_service.py \
  src/graph/retriever.py \
  src/ontology/registry.py \
  frontend/js/pages/chat.js \
  tests/test_conversation_context.py \
  tests/test_evidence_assessment.py \
  tests/test_conversational_evidence_regressions.py \
  tests/test_api_chat_stream.py \
  tests/test_api_rag_service_payload.py \
  tests/test_query_router.py \
  tests/test_graph_query_planner.py \
  tests/test_source_grounded_answers.py \
  tests/test_api_sessions_db.py \
  tests/test_frontend_assistant_display.mjs \
  tests/e2e/chat.spec.js \
  tests/fixtures/conversation_evidence_profiles.json \
  docs/276_CONVERSATIONAL_EVIDENCE_RESOLUTION_REPORT.md
git diff --cached --check
git commit -m "fix(chat): resolve grounded multi-turn evidence state"
```

Do not push at this checkpoint without a separate explicit request.

## Release Gate — Not Authorized by This Plan

배포 전 다음을 모두 확인한다.

1. Release A active/provenance/Graph hash `valid`
2. independent code review 완료
3. focused, full Python, Node, Playwright 통과
4. LLM invocation count 증가 없음
5. user assertion이 ontology/Graph에 저장되지 않음
6. final-before-persist event 0건
7. duplicate rendering 0건
8. 수술종수, HIRA, MX122, 채팅 이력, 관리자 Graph 회귀 0건
9. DGX main 반영 별도 승인
10. 서비스 재기동과 사용자 수준 smoke 별도 승인

하나라도 충족하지 않으면 부분 배포하지 않고 Release A corrected safe baseline을 유지한다.

## Completion Marker

Developer는 Release B 코드·테스트·보고서가 완료되고 commit/push/deploy를 수행하지 않았을 때 최종 응답 마지막 줄에 다음 marker를 정확히 남긴다.

```text
DEVELOPER_RELEASE_B_IMPLEMENTATION_READY_FOR_REVIEW
```
