# Release B Conversational Evidence Resolution 독립 리뷰

- 검토 시각: 2026-07-19 04:40:50 KST
- 판정 대상: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 후보 HEAD/base: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- Developer marker: `DEVELOPER_RELEASE_B_IMPLEMENTATION_READY_FOR_REVIEW`
- 보호 메인: `/srv/shared/projects/insurance-rag-chatbot` at `fa8d734d643d18d6983447978de2210819717bc6`
- 원격 master: 보호 checkout의 GitHub `origin/master`가 `b1c0b658a621552bb9b98a035d8883d6fba1dca2`로 확인됨
- 경계: read-only review. 구현·데이터·stage·commit·push·integration·deploy·restart·candidate apply·practitioner approval·active/provenance 교체·GraphDB rebuild·reindex를 수행하지 않음.

## Findings

### P1. 공개 SSE/history 경계가 내부 provenance와 상태를 제거하지 못함

`src/api/routes/chat.py:365-389`의 `_public_graph_payload`는 `clarification.pending_slots`만 재구성하고 나머지 Graph payload를 그대로 복사한다. 따라서 `src/api/rag_service.py:647-677,679-760`의 `facts[].evidence[].chunk_id`, `session_assertions`, `graph_review_paths[].steps[].evidence[].chunk_id`, `source_chunk_ids`가 공개 Graph 이벤트로 전달된다. 새 evidence 경로도 `src/rag/evidence_assessment.py:206-213`에서 `source_evidence[].chunk_id`를 만든다. 더구나 `src/api/routes/chat.py:450-467`은 이 raw Graph payload를 `assistant_meta.graph_result`로 저장하고, `src/api/routes/sessions.py:100-110`은 저장된 `message.sources`를 필터 없이 history API로 반환한다.

독립 재현 결과:

```text
public_chunk_ids: ['internal-source-1']
public_fact_chunk: 'internal-fact-1'
public_path_chunk: 'internal-path-1'
public_assessment_chunk: 'internal-assessment-1'
stored_chunk_ids: ['internal-source-1']
```

이는 사용자가 보지 않아야 할 chunk ID, 승인 provenance 경로와 session 내부 상태가 SSE, DOM 입력 데이터, 저장 메시지/history 경계로 유출될 수 있다는 뜻이다. Developer 보고서의 “공개 SSE graph payload에서 내부 chunk 식별자를 제거했다”는 주장과 실제 코드가 불일치한다.

필수 최소 수정: Graph/SSE, `sources`, history replay/message API에 공통 allowlist sanitizer를 적용하여 문서명·페이지·사용자 표시용 상태만 반환하고 `chunk_id`, `source_chunk_ids`, `evidence_chunk_ids`, `session_assertions`, `assistant_meta`, `conversation_state`, provenance path를 공개하지 않아야 한다. raw 내부 metadata는 서버 내부에서만 보존하고, SSE 및 history 회귀 테스트에서 위 키의 재등장을 금지해야 한다.

### P1. safe baseline을 실제 runtime/운영 artifact로 소비하는 원자 적용·rollback 경로가 없음

`src/ontology/safe_baseline.py:48-97`은 lock-exact trusted projection과 pending 6개를 계산하지만, `:106-126`은 `concepts.safe.json`과 pending bundle 두 파일만 exclusive-create한다. `scripts/prepare_ontology_safe_baseline.py:28-59`도 이 임시 두 파일을 생성하고 종료한다. active manifest, provenance sidecar, Graph manifest를 versioned temporary tree에서 검증한 뒤 원자 교체하고 rollback하는 운영 명령은 이 Release B diff에 없다.

후보의 `data/ontology`에는 `concepts.json`만 있고 active/provenance artifact가 없다. `src/ontology/registry.py:622-633`의 default resolver는 active가 없으면 raw `BASE_ONTOLOGY_MANIFEST`를 선택한다. 독립 실행 결과는 다음과 같다.

```text
prepare: state=valid, trusted_concept_count=49, pending_correction_count=6
safe projection: check passed, concepts=49, aliases=109, candidate_aliases=18, retrieval_rules=4
trusted hash: ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2
raw default: ontology integrity state is quarantined (exit 1)
default registry: state=quarantined, concept_count=49, quarantined=6, approved_profiles=0
```

따라서 현재 산출물만으로는 안전 baseline을 runtime에 적용할 수 없고, 잘못된 시작 절차에서는 raw quarantined manifest를 계속 읽거나 승인 profile 0개로 동작한다. Developer가 보고한 임시 GraphDB 검증은 운영 적용 경로와 rollback을 대신하지 않는다.

필수 최소 수정: 승인된 operation이 0개인 safe projection도 입력으로 받을 수 있는 별도 operator-gated publish/rollback 명령을 추가하거나 기존 merge/apply 경로를 명시적으로 확장한다. versioned temporary active/provenance/Graph artifact를 검증한 뒤에만 원자 swap하고, 실패 시 이전 세트를 복원하며, runtime은 raw quarantined base로 묵시적 fallback하지 않아야 한다. 이 리뷰에서 apply하지 않는다.

### P1. 다중 clarification에서 이미 해결한 assertion을 삭제하여 질문이 반복되고 판단 조건이 사라짐

`src/rag/conversation_context.py:602-633`은 pending slot 집합이 달라질 때 새 `ConversationState`를 만들면서 `user_assertions=()`로 초기화한다. 실제 route는 `src/api/routes/chat.py:720-727`에서 매 응답의 남은 slot을 이 함수에 전달한다.

독립 재현: `condition-a`, `condition-b` 두 슬롯에서 `condition-a=yes` assertion을 보유한 상태로 남은 슬롯 `condition-b`를 전달한 결과:

```text
{'before_assertions': ['condition-a'],
 'remaining_slots': ['condition-b'],
 'after_assertions': []}
```

두 번째 답변을 처리할 때 첫 번째 확인 결과가 없어져 evidence engine이 `condition-a`를 다시 미해결로 판단할 수 있다. 현재 테스트는 단일 slot 중심이며 이 2-slot 계약을 닫지 않는다.

필수 최소 수정: 남은 slot만 교체하되 기존 assertion을 보존하거나, 해결된 slot을 안정적으로 filter하는 경로로 바꾸고 2개 이상 slot의 `a 해결 → b 질문 → b 해결 → a 재질문 없음` API/state 회귀를 추가해야 한다. topic switch, same-turn retry, persistence failure의 기존 경계는 유지해야 한다.

### P2. 백엔드 evidence schema v2와 프론트엔드 render contract가 서로 다름

`src/rag/evidence_assessment.py:286-305`가 생성하는 payload의 top-level key는 `schema_version`, `evidence_assessment`, `clarification`뿐이며 `display.primary_text`가 없다. 반면 `frontend/js/pages/chat.js:1132-1135`의 `isSchemaV2EvidencePayload`는 `schema_version == 2`이면서 `display.primary_text`가 있어야 true이고, `:1235-1246`은 false이면 legacy renderer를 선택한다. 백엔드 `src/api/rag_service.py:1034-1057`의 renderability 판정도 schema v2/evidence assessment를 인식하지 않는다.

승인 profile과 direct source chunk를 이용한 독립 재현:

```text
payload_keys=['clarification', 'evidence_assessment', 'schema_version']
has_display=False
renderable=False
```

즉 실제 evaluator가 만든 새 payload에서는 structured evidence panel이 선택되지 않는다. `tests/test_frontend_assistant_display.mjs:91-130`의 schema v2 테스트는 `display.primary_text`를 fixture에서 직접 만들어 백엔드 계약 누락을 검출하지 못한다.

필수 최소 수정: 백엔드가 프론트엔드 계약에 맞는 `display.primary_text`를 생성하거나 두 계층이 공유하는 단일 schema/predicate로 통일하고, 실제 `evaluate_approved_evidence()` 출력물을 그대로 넣는 통합 회귀를 추가해야 한다. 특정 질환·질문·concept ID를 예외 처리해서는 안 된다.

## 계약·비회귀 점검

- 새 production 코드에서 특정 질환, 질문 문구, 수술명, HIRA/MX122/51040 또는 concept ID를 분기하는 하드코딩은 확인되지 않았다. 일반 yes/no parser와 기존 generic policy logic은 domain hardcoding으로 세지 않았다.
- `src/ontology/registry.py:348-372`는 active integrity가 valid이고 provenance에 승인 operation path가 있을 때만 decision profile을 반환한다. user assertion/clarification choice가 ontology 또는 Graph 승인 knowledge로 쓰이는 promotion path는 확인되지 않았다.
- safe baseline 결과의 6개 ID는 pending bundle에만 있고, raw registry에서는 quarantined이며 `approved_profiles=0`이다. 미승인 6개를 active/retrieval로 승격시키는 동작은 수행되지 않았다.
- `source_grounded_answers.py`의 기존 domain-specific 구현과 관련 테스트가 삭제되고 generic evidence engine으로 대체된 것은 diff상 확인되지만, 삭제만으로 기능 은닉이라고 단정할 증거는 없었다. 다만 실제 active approved artifact가 없는 상태이므로 generic engine의 운영 경로는 위 P1/P2가 닫히기 전까지 검증되지 않은 상태다. 미승인 hair-loss knowledge를 되살리는 수정은 요구하지 않는다.
- 수술종수·HIRA·MX122·계산·세션·관리자 Graph 관련 기존 회귀를 포함한 focused suite는 통과했지만, 보호 앱/운영 active artifact를 대상으로 한 검증은 경계상 수행하지 않았다. 이 결과가 safe baseline 운영 적용을 대신하지 않는다.

## 독립 검증 증거

| 검증 | 결과 |
| --- | --- |
| Release B 관련 Python focused suite | `260 passed, 1 warning` |
| 전체 pytest, 임시 DB/user/log, E2E flag 미주입 | `1090 passed, 3 warnings` |
| 후보 + `INSURANCE_RAG_ISOLATED_E2E=1` | `1 passed, 2 failed, 1 warning` |
| 기준 commit archive + 같은 flag | `1 passed, 2 failed, 1 warning`; 동일한 기존 flag 충돌 재현 |
| Node test | `45 passed, 0 failed` on `Node v24.15.0`; Node 18 executable은 원격 환경에서 확인되지 않음 |
| frontend build 및 `node --check` | 통과; 생성 bundle hash가 후보 `frontend/dist/app.min.js`와 일치 |
| isolated Playwright | 임시 `node_modules` symlink, loopback `127.0.0.1:18768`, 임시 DB/user/secret/log로 `13 passed` |
| safe baseline sync | trusted 49, pending 6, hash `ccfb...fe3b2`, valid |
| raw/base sync | `quarantined`, exit 1 |
| `git diff --check` | exit 0 |

Playwright 종료 후 후보 `node_modules` symlink, 18768 listener, E2E process, review temp artifact가 남지 않았다. 후보는 detached HEAD `b1c0...`이며 15 tracked changes와 9 untracked artifacts가 있는 unstaged/uncommitted 상태다. untracked 항목은 Markdown/JSON/Python 텍스트 파일뿐이며 debug breakpoint, private key, credential artifact, binary는 확인되지 않았다.

보호 메인은 clean이고 HEAD는 `fa8d...`, 그 checkout의 `origin/master`와 실제 GitHub `ls-remote origin/master`는 `b1c0...`이다. 기존 uvicorn 외 서비스는 건드리지 않았고 보호 port `18080`에는 접근하지 않았다. 보호 운영 DB·계정·로그·active ontology/provenance·Graph/index에는 쓰기를 수행하지 않았다.

## 최소 Developer fixback prompt

```text
Release B Review Team 독립 검토 결과 CHANGES_REQUESTED입니다. 제품/운영 데이터를 적용하지 말고 DGX 격리 workspace에서 다음 네 가지 최소 수정만 수행하십시오.

1. src/rag/conversation_context.py:602-633의 다중 slot 전환에서 기존 user_assertions를 보존하고, 2+ slot의 a 해결 -> b 질문 -> b 해결 -> a 재질문 없음 회귀를 추가하십시오.
2. src/rag/evidence_assessment.py와 frontend/js/pages/chat.js의 schema v2 계약을 하나로 맞추십시오. 실제 evaluate_approved_evidence() payload를 사용하는 renderability/UI 통합 회귀를 추가하고 domain-specific 예외를 만들지 마십시오.
3. SSE graph, sources, history/message API, persisted assistant metadata에 공통 public allowlist를 적용하십시오. chunk_id/source_chunk_ids/evidence_chunk_ids/session_assertions/assistant_meta/conversation_state/provenance path는 public payload에 없어야 합니다.
4. safe baseline을 trusted 49 + approved operation 0으로도 처리할 수 있는 operator-gated versioned temp active/provenance/Graph validate -> atomic swap -> rollback 경로를 제공하고, runtime의 raw quarantined fallback을 fail-closed로 막으십시오. pending 6개는 승인/apply하지 말고 보호 main/18080/운영 GraphDB/index에는 접근하거나 쓰지 마십시오.

수정 후 새 보고서에 재현 명령, focused/full/Node/build/isolated Playwright 결과와 public payload 부재 증거를 남기고 Review Team 재검토를 요청하십시오.
```

## Verdict

`CHANGES_REQUESTED`

REVIEW_RELEASE_B_CHANGES_REQUESTED
