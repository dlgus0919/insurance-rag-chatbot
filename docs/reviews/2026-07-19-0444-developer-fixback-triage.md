# Release B CHANGES_REQUESTED 개발자 수정 트리아지

- 작성 시각: 2026-07-19 04:44 KST
- 기준 리뷰: `docs/reviews/2026-07-19-044050-release-b-conversational-evidence-resolution-review.md`
- 수정 대상 workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-conversational-evidence-resolution-20260719`
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 판정: `CHANGES_REQUESTED`

## 경계

- 기존 Release B 미커밋 변경을 보존한 같은 격리 workspace에서만 수정한다.
- 보호 메인, 18080, 운영 DB·계정·대화·로그, active ontology/provenance, GraphDB, BM25/Chroma, rule manifest를 변경하지 않는다.
- candidate apply, practitioner 승인, Graph rebuild, reindex, deploy, restart, stage, commit, push를 수행하지 않는다.
- 미승인 6개 concept는 계속 pending으로 둔다.
- 특정 질환, 질문 문구, 수술명, concept ID, HIRA/MX122 코드에 종속된 예외를 만들지 않는다.

## 필수 수정 1 — public payload allowlist

독립 재현에서 SSE와 history payload에 다음 내부 정보가 남았다.

- `chunk_id`
- `source_chunk_ids`
- `evidence_chunk_ids`
- `session_assertions`
- `assistant_meta`
- `conversation_state`
- provenance operation path 및 내부 evidence path

수정 요구:

- SSE graph, sources, message/history replay에 공유 public allowlist sanitizer를 사용한다.
- 문서명, 페이지, 사용자 표시용 상태 등 승인된 표시 필드만 반환한다.
- 서버 내부 persistence에 필요한 raw metadata는 내부 전용으로 보존하되 외부 API/SSE/DOM으로 직렬화하지 않는다.
- nested list/dict 전체에 대해 deny key 재귀 제거가 아니라 명시적 public schema/allowlist를 우선한다.
- SSE 첫 응답, 재시도 replay, history GET, export 경로의 회귀 테스트를 추가한다.

완료 증거: 위 금지 key를 여러 nested 위치에 주입해도 public payload 전체 재귀 검색 결과가 0건이어야 한다.

## 필수 수정 2 — safe baseline operator-gated publish/rollback

현재 generator는 `concepts.safe.json`과 pending bundle만 만들고 runtime이 소비할 active/provenance/Graph artifact를 적용할 수 없다. active가 없으면 raw quarantined base로 fallback한다.

수정 요구:

- trusted 49 + approved operation 0인 safe projection을 입력으로 받는 별도 operator-gated prepare/publish/rollback 계약을 제공한다.
- 기본 실행은 dry-run/prepare이며 운영 경로를 쓰지 않는다.
- versioned temporary tree에 active manifest, provenance sidecar, GraphDB, Graph manifest를 만든다.
- schema, base lock, content hash, provenance hash, Graph manifest hash, Graph integrity를 모두 검증한 경우에만 publish 가능하게 한다.
- publish는 동일 파일시스템 내 원자 rename/swap으로 세트 단위 적용하며 부분 교체를 금지한다.
- 이전 세트 백업과 명시적 rollback 명령을 제공한다.
- 시작 시 active 세트가 없거나 invalid/quarantined면 raw base로 조용히 fallback하지 않고 fail-closed 진단을 반환한다. 개발/test 입력처럼 명시적 base path를 준 경우만 예외적으로 base registry를 허용한다.
- 이 작업에서는 실제 publish/rollback을 운영 경로에 실행하지 않고 임시 root에서만 검증한다.

완료 증거: 임시 root에서 prepare → verify → publish → runtime resolver가 active 49/valid/profile 0을 선택 → 의도적 실패 주입 시 이전 세트 유지 → rollback 성공을 검증한다.

## 필수 수정 3 — 다중 clarification assertion 보존

`src/rag/conversation_context.py`의 pending slot 교체가 `user_assertions=()`로 초기화해 이미 확인한 조건을 잃는다.

수정 요구:

- 남은 slot 집합을 갱신해도 기존 assertion을 보존한다.
- 해결된 slot의 assertion은 안정적으로 유지하고 동일 질문을 다시 만들지 않는다.
- topic switch에서는 새 topic과 무관한 상태만 명시적으로 초기화한다.
- 같은 turn retry, persistence failure, history reload 계약을 유지한다.

완료 증거: 2개 이상 slot에서 `a 해결 → b만 질문 → b 해결 → a 재질문 없음`, history reload 후 동일 상태, retry 중복 없음 API/state 회귀를 추가한다.

## 필수 수정 4 — evidence schema 단일 계약

백엔드 `evaluate_approved_evidence()`의 schema v2에는 `display.primary_text`가 없지만 프런트는 그 필드를 요구해 structured panel을 선택하지 않는다.

수정 요구:

- 백엔드와 프런트가 공유하는 단일 schema/predicate를 정의한다.
- 백엔드가 표시 데이터를 canonical payload에 포함하거나 프런트가 canonical evidence assessment를 직접 표시하도록 한 방향을 선택한다.
- `rag_service` renderability 판정도 동일 계약을 사용한다.
- 특정 질환/문구 예외를 추가하지 않는다.

완료 증거: fixture를 손으로 꾸미지 말고 실제 `evaluate_approved_evidence()` 반환값을 API/SSE/프런트 renderer에 그대로 넣는 통합 회귀에서 structured panel이 표시되어야 한다.

## 유지해야 할 비회귀

- 기존 공개 `apply_policy_clause_decision` 계약과 GraphRetriever 구형 호출 호환
- same `turn_id` idempotent replay 및 persistence failure 시 no-done
- 수술종수 우선 응답, HIRA 직접 코드 경로
- MX122 선택 후 4세대/산정특례 모름 계산
- 계산→일반 질의 연속성, chat history restore/export
- 관리자 Graph 시각화와 실제 기동 모델 표시
- pending 6개 미승인 및 승인 profile provenance gate

## 필수 검증·보고

- 리뷰가 독립 재현한 4개 finding 각각의 실패 전/통과 후 테스트
- Release B focused suite
- 전체 pytest
- Node tests, frontend build, bundle syntax
- 격리 Playwright 13개 이상 및 새 multi-slot/history/public-payload UI 경로
- 임시 root의 safe publish/failure injection/rollback 테스트
- `git diff --check`, git status, 임시 symlink/listener/DB/log 정리
- 보호 메인/운영 artifact hash 및 서비스 비변경 확인
- 수정 보고서: `docs/277_CONVERSATIONAL_EVIDENCE_RESOLUTION_FIXBACK_REPORT.md`
- 최종 표식: `DEVELOPER_RELEASE_B_FIXBACK_READY_FOR_REREVIEW`
