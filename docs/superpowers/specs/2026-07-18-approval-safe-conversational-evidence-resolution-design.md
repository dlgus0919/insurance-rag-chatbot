# 승인 안전형 대화 연속성·근거 적용성 판정 설계

## 1. 문서 상태와 목적

- 상태: 설계 승인 완료
- 작성일: 2026-07-18
- 적용 대상: FastAPI + 정적 SPA 일반 보험 질의 경로, ontology 승인·병합 경로, GraphDB 운영 지식 경로
- 기준 원칙: `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`

이 설계는 다음 두 문제를 같은 원인 사슬에서 해결한다.

1. 좁은 근거 후보의 승인 과정에서 승인되지 않은 개념 필드가 active ontology와 GraphDB에 함께 유입될 수 있는 문제
2. 일반 보험 질의에서 후속 발화가 이전 확인 질문의 답으로 처리되지 않고, 현재 문장만으로 다시 라우팅·검색·결정되어 같은 질문과 답변을 반복하는 문제

이번 테스트의 탈모 대화는 회귀 입력 중 하나다. production 코드는 탈모, 질병성 또는 해당 문장에 맞춘 분기를 포함하지 않는다. 구현 단위는 `확인 요청 → 사용자 진술 → 조항 적용성 → 근거 권한 → 출력`이라는 주제 독립 계약이다.

설계 승인은 코드 구현·운영 active manifest 적용·GraphDB 재구축·서비스 재기동을 자동 승인하지 않는다. 운영 지식 변경은 별도 diff와 검증 결과를 제시한 뒤 active 적용 게이트에서 멈춘다.

## 2. 현재 결함

### 2.1 승인 범위 누출

현재 ontology 병합은 base concept 전체를 먼저 읽고 승인 후보를 보강하는 구조다. 따라서 `evidence_tag`처럼 좁은 후보를 적용해도 base에 존재하던 별칭, 질문, 검색 확장, 결정 프로필이 active 결과에 함께 남을 수 있다. 이 방식은 승인 후보만으로 실제 active 변경 내용을 재구성할 수 없게 한다.

운영 GraphDB가 active ontology를 입력으로 재구축되면 승인 범위 누출이 확정 노드와 조건 관계로 확대된다. 감사 로그가 존재해도 필드별 승인 provenance를 복원할 수 없으면 000 원칙의 운영 승인 경계를 충족하지 못한다.

### 2.2 일반 질의의 대화 상태 단절

일반 RAG 경로는 대화 이력을 프롬프트에 포함하지만 다음 구조화 단계는 현재 질문만 사용한다.

- query router
- Graph query planner/retriever
- source-grounded deterministic decision

결정형 답변이 선택되면 LLM 프롬프트의 대화 이력은 최종 판단에 관여하지 않는다. 요청 스키마에는 `clarification` 필드가 있지만 일반 API 경로에서 Graph 계획과 근거 판정에 연결되지 않는다.

### 2.3 문자열 중심 조건 인식

현재 결정 로직은 현재 질문에 특정 등록 표현이 포함되는지를 확인한다. 자연스러운 서술, 생략된 주어, 짧은 답변 또는 앞선 질문을 전제로 한 응답은 동일 조건으로 인식되지 않을 수 있다. 정확한 등록 표현이 인식되더라도 고정된 조건·질문 목록이 다시 붙어 이미 해결된 질문이 반복될 수 있다.

### 2.4 근거 권한과 적용성 혼동

직접 조항을 찾았다는 사실과 그 조항이 현재 사례에 적용된다는 판단이 분리되지 않는다. 관련 조항만 존재하는 사례에서도 답변 전체가 직접 조항의 확정 근거를 가진 것처럼 보일 수 있다.

### 2.5 중복 출력과 저장 순서

백엔드 본문과 canonical decision payload에 같은 요약·권한 문구가 들어가고 프런트엔드는 두 값을 모두 표시한다. 또한 현재 SSE 경로는 확정 `final`을 먼저 전송한 뒤 대화 저장을 시도하므로, 저장 실패 시 사용자가 본 응답과 채팅 이력이 달라질 수 있다.

## 3. 목표와 비목표

### 3.1 목표

- 승인 후보에 명시된 필드만 active ontology와 GraphDB로 승격한다.
- 승인 범위 무결성이 확인되지 않은 개념은 해당 개념 단위로 운영 해석에서 격리한다.
- 일반 질의에서도 이전 확인 요청과 사용자 후속 진술을 같은 세션에서 연결한다.
- 사용자 진술과 승인된 보험 지식을 분리한다.
- 직접 근거, 관련 근거, 근거 없음과 현재 사례 적용성을 분리한다.
- 이미 해결된 질문을 반복하지 않는다.
- 본문·결정 패널·확인 패널 사이의 의미 중복을 제거한다.
- 기존 채팅 이력과 assistant metadata를 마이그레이션 없이 읽는다.
- 추가 LLM 호출을 필수화하지 않고 DGX Spark의 GPU 부하 증가를 억제한다.

### 3.2 비목표

- 탈모의 의학적 원인 또는 보장 여부에 대한 새로운 지식 생성
- 승인되지 않은 질환 분류를 GraphDB에 추가
- 모든 채팅 메시지를 새로운 이벤트 저장소로 이전
- 기존 보험금 계산 스냅샷 계약의 전면 재작성
- 프롬프트 수정이나 모델 교체만으로 문제 해결
- 운영 대화 DB, 사용자 계정, 사용 로그의 삭제 또는 재작성

## 4. 검토한 접근

### 4.1 표현·동의어 추가

현재 실패 문구를 인식하도록 alias나 정규식을 추가하는 방식이다. 구현은 빠르지만 다른 문장과 다른 보험 주제에서 같은 단절이 재발한다. 질문별 하드코딩을 금지한 000 원칙에도 부합하지 않아 채택하지 않는다.

### 4.2 승인 교정 + 일반화된 확인 상태 계층

승인 병합의 무결성을 복구하고 기존 메시지 metadata에 구조화된 확인 상태를 기록한다. 라우팅 전에 후속 발화를 미해결 질문과 연결하고 일반 EvidenceAssessment 엔진이 근거 권한과 적용성을 판정한다. 현재 저장 구조를 유지하면서 근본 원인을 해결할 수 있어 채택한다.

### 4.3 전체 대화 이벤트 소싱 전환

모든 메시지와 상태를 새로운 이벤트 저장소로 이전하는 방식이다. 장기적으로 일관된 구조를 제공하지만 현재 SQLite 데이터 마이그레이션, API 전면 변경, 운영 롤백 위험이 과도해 이번 범위에서 제외한다.

## 5. 전체 아키텍처

작업은 두 개의 독립 릴리스로 분리한다.

### 5.1 릴리스 A: 승인 무결성 복구와 운영 격리

1. active manifest, 후보·검토·적용 로그, GraphDB, 현재 응답의 변경 전 증거를 읽기 전용으로 보존한다.
2. 승인 후보와 active 결과를 JSON path 단위로 비교한다.
3. 일반 승인 무결성 검사기를 도입한다.
4. 무결성이 확인되지 않은 개념만 runtime registry에서 격리한다.
5. corrected active manifest와 GraphDB 예상 diff를 dry-run으로 생성한다.
6. 별도의 active 적용 승인 후 원자적으로 교체한다.
7. corrected 결과를 이후 릴리스의 safe baseline으로 고정한다.

변경 전 active 상태는 forensic snapshot으로만 보존하며 기능 릴리스의 자동 롤백 대상으로 사용하지 않는다.

### 5.2 릴리스 B: 대화 연속성·근거 적용성 판정

1. 기존 assistant metadata에 버전이 있는 clarification state를 저장한다.
2. 현재 발화를 라우팅하기 전에 미해결 확인 요청과 대조한다.
3. 사용자 후속 진술을 세션 한정 assertion으로 기록한다.
4. router, Graph planner, retriever, 결정 엔진이 하나의 ResolvedConversationContext를 사용한다.
5. 일반 EvidenceAssessment 엔진이 근거 권한과 현재 사례 적용성을 분리한다.
6. backend와 frontend의 단일 출력 계약을 적용한다.
7. 저장 성공 후에만 확정 응답 이벤트를 전송한다.

## 6. 승인 무결성 계약

### 6.1 ApprovalPatch

승인 결과는 개념 전체가 아니라 허용된 변경 경로의 집합으로 표현한다.

```json
{
  "schema_version": 1,
  "candidate_id": "candidate-id",
  "base_manifest_hash": "sha256",
  "allowed_operations": [
    {
      "operation": "add",
      "path": "/concepts/cov.example/properties/evidence_tags/-",
      "value_hash": "sha256"
    }
  ],
  "approved_evidence": [
    {
      "chunk_id": "source-chunk-id",
      "content_hash": "sha256"
    }
  ],
  "reviewer": "reviewer-id",
  "reviewed_at": "ISO-8601",
  "expected_active_hash": "sha256"
}
```

### 6.2 병합 규칙

- 병합기는 승인된 operation과 path만 active 결과에 투영한다.
- 승인 당시 base hash가 현재 base와 다르면 stale 후보로 중단한다.
- 후보 유형이 허용하지 않는 field group 변경을 거부한다.
- active 결과에 승인 경로 밖 변경이 하나라도 있으면 전체 apply를 실패시킨다.
- hash 비교는 생성 시각 같은 가변 metadata를 제외하고 key 순서와 문자열 정규화가 고정된 canonical content를 기준으로 한다.
- 같은 ApprovalPatch를 반복 적용해도 결과가 바뀌지 않아야 한다.
- 각 active 변경 필드는 candidate id, 승인자, source evidence, 적용 시각을 역추적할 수 있어야 한다.
- GraphDB는 검증을 통과한 corrected active manifest만 입력으로 사용한다.

### 6.3 런타임 격리

registry는 개념 단위 integrity result를 확인한다.

- `valid`: 정상 로딩
- `quarantined`: 해당 개념을 결정·검색 확장·Graph 확정 근거에서 제외
- `stale`: manifest 또는 source hash가 달라 재검토 필요

특정 개념 ID나 질환명을 production 코드의 denylist로 두지 않는다. 격리 사유와 candidate id는 관리자 진단과 감사 로그에 표시하되 일반 사용자 답변에 내부 경로를 노출하지 않는다.

## 7. 대화 상태 계약

### 7.1 저장 위치

새 상태 테이블을 만들지 않는다. 기존 `messages`가 대화 원본이며 assistant message의 `assistant_meta`에 버전이 있는 상태를 추가한다. 이전 메시지에 해당 metadata가 없으면 schema v0으로 읽고 임의 상태를 복원하지 않는다.

### 7.2 ClarificationRequest

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "topic_anchor": "source-grounded topic anchor",
  "origin_turn_id": "uuid",
  "status": "pending",
  "slots": [
    {
      "slot_id": "evidence-condition-id",
      "question": "승인된 원문 조건에서 생성한 질문",
      "allowed_values": ["yes", "no", "unknown"],
      "evidence_chunk_ids": ["chunk-id"]
    }
  ],
  "ontology_manifest_hash": "sha256"
}
```

질문과 allowed value는 승인된 조항 조건 또는 일반 처리 스키마에서만 생성한다. 근거가 없는 의학적 분류를 질문으로 발명하지 않는다.

### 7.3 UserAssertion

```json
{
  "assertion_id": "uuid",
  "request_id": "uuid",
  "slot_id": "evidence-condition-id",
  "value": "no",
  "resolution": "confirmed_by_user",
  "source_message_id": 124,
  "supersedes": null
}
```

UserAssertion은 현재 세션의 사례 진술이다. 사용자 원문을 metadata에 복제하지 않고 원래 user message id를 참조한다. ontology concept, GraphDB fact 또는 보험 보장 판단으로 승격하지 않는다.

### 7.4 상태 수명

- `pending`: 확인 대기
- `resolved`: yes/no/unknown으로 답변됨
- `superseded`: 주제 전환 또는 새 명시 진술로 대체됨
- `stale`: manifest/source hash 변경으로 재사용 불가

같은 슬롯에 새 명시 진술이 오면 기존 기록을 삭제하지 않고 `supersedes`로 연결한다. `unknown`도 해결된 값이므로 같은 질문을 반복하지 않는다.

## 8. 후속 발화 처리

### 8.1 처리 순서

```text
현재 발화
+ 마지막 pending clarification
+ 기존 user assertions
+ UI에서 선택된 세대·방문 조건
→ ResolvedConversationContext
→ route resolution
→ Graph planning/retrieval
→ evidence assessment
→ display payload
→ atomic message persistence
→ final/done event
```

### 8.2 continuation 결과

- `new_question`: 독립 질문
- `clarification_response`: 기존 pending 요청의 답변
- `topic_switch`: 기존 요청을 superseded로 종료하고 새 주제 시작
- `ambiguous_continuation`: 진술을 확정하지 않고 질문 하나로 재확인

`clarification_response`는 최초 질문의 주제, 의도, 세대와 source scope를 유지한다. 검색 질의는 현재 짧은 문장만 사용하지 않고 topic anchor, 사용자 진술, 아직 미해결인 원문 조건을 포함한다.

### 8.3 ChatRequest.clarification

기존 필드는 서버가 발급한 `request_id`, `slot_id`, allowed value를 화면에서 명시 선택한 경우에만 신뢰한다. 자유 입력은 서버가 pending request와 대조한다. 브라우저 payload를 대화 상태의 원본으로 사용하지 않는다.

## 9. 일반 근거 적용성 엔진

### 9.1 입력

```text
ResolvedConversationContext
EvidenceBundle
ApprovedDecisionProfiles
```

ApprovedDecisionProfile은 source evidence와 승인 provenance가 있는 조건·효과만 포함한다. 승인 프로필이 없으면 결정 엔진은 `no_direct_evidence`로 종료한다.

### 9.2 EvidenceAssessment

```text
authority:
  own_policy | standard_policy | other_document
relevance:
  direct_clause | related_clause | unrelated
applicability:
  applies | does_not_apply | unknown
decision:
  supported | supported_exclusion | unresolved
```

문서 권한, 질문 관련성, 현재 사례 적용성, 판단 결과를 별도 축으로 유지한다. 표준약관의 직접 조항을 찾았다는 이유만으로 현재 사례에 적용되는 확정 판단으로 표시하지 않는다.

### 9.3 질문 생성

- 승인된 조항 조건 중 아직 unknown인 조건만 질문한다.
- 해결되거나 현재 조항과 무관해진 조건은 제거한다.
- 우선순위가 가장 높은 질문 하나만 표시한다.
- required evidence는 미해결 조건과 직접 연결된 항목만 표시한다.
- 승인되지 않은 의학적·보장 분류를 질문이나 답변에 추가하지 않는다.

### 9.4 production 코드 경계

금지:

```python
if "특정 질환" in question:
    return topic_specific_decision
```

허용:

```python
for condition in approved_profile.conditions:
    resolution = context.resolution_for(condition.id)
    assess_condition(condition, resolution)
```

이번 테스트 문장과 합성 fixture는 production 코드에서 참조하지 않는다.

## 10. 출력 계약

최종 payload는 다음 역할을 분리한다.

```text
display.primary_text
decision.status
decision.applicability
decision.conditions
decision.source_evidence
clarification.pending_slots
```

- `primary_text`: 사용자 결론을 한 번만 표시
- decision panel: 상태·적용 조건·근거를 표시하되 primary text를 반복하지 않음
- clarification panel: 미해결 슬롯만 표시
- source panel: 문서명, 페이지, chunk provenance 표시
- export: 동일 구조에서 본문과 근거를 각각 한 번만 조합
- legacy message: 기존 canonical summary를 읽을 때만 호환 정규화 수행

## 11. 실패 처리와 일관성

- 상태 JSON 손상: 해당 상태만 무시하고 감사 경고를 기록하며 근거 부족으로 종료
- approval integrity 실패: 해당 개념만 quarantined 처리
- 후속 발화 해석 불확실: assertion을 저장하지 않고 질문 한 개로 재확인
- 직접 근거 없음: 사용자 진술은 보존하되 `no_direct_evidence` 반환
- GraphDB 장애: Graph fact를 다른 근거로 가장하지 않고 문서 근거만 사용
- manifest/GraphDB 버전 불일치: 해당 지식 경로를 사용하지 않음
- 대화 저장 실패: 확정 `final`과 `done`을 전송하지 않고 재시도 상태 반환
- 재시도: 동일 request id를 사용하여 중복 진술·중복 메시지를 방지

스트리밍 token은 provisional 표시로 사용할 수 있지만 확정 답변은 사용자 메시지, assistant 메시지, assistant metadata가 같은 트랜잭션으로 저장된 후에만 전달한다.

## 12. 마이그레이션과 호환성

- 기존 messages와 sources JSON을 재작성하지 않는다.
- clarification metadata가 없는 과거 메시지는 정상 표시하되 대화 상태를 추정하지 않는다.
- 새 metadata는 `schema_version=1`로 저장한다.
- 기존 claim snapshot metadata와 같은 assistant_meta 안에서 이름이 충돌하지 않게 별도 key를 사용한다.
- 과거 canonical decision payload는 legacy renderer에서만 중복 정규화를 적용한다.
- corrected active manifest와 GraphDB는 새 버전과 해시를 기록한다.

## 13. 검증 전략

### 13.1 승인/manifest 테스트

- evidence-only 후보가 alias, question, retrieval expansion, decision profile을 승격하지 못한다.
- 승인 경로 밖 active 변경이 있으면 apply가 실패한다.
- stale base hash 후보는 적용되지 않는다.
- apply가 idempotent하다.
- active 필드별 승인 provenance를 복원할 수 있다.
- GraphDB는 corrected active manifest의 개념만 확정 노드로 만든다.
- 기존 감사 로그를 보존하고 correction record를 추가한다.

### 13.2 대화 상태 테스트

- pending 질문에 대한 명시 답변
- 짧은 답변과 자연스러운 서술형 답변
- unknown 응답
- 진술 번복과 supersedes 연결
- 독립 질문으로의 topic switch
- manifest 변경 후 stale 처리
- 이전 채팅 재열람 후 상태 복원
- 명시 UI selection과 자유 입력의 동일 결과

### 13.3 근거 판정 테스트

- 직접 적용 가능한 조항
- 관련 조항이나 현재 사례에 적용되지 않는 조항
- 적용 조건이 미확인인 조항
- 직접 근거가 없는 사례
- 승인 프로필이 없는 사례
- source authority와 applicability가 서로 다른 사례

### 13.4 프런트엔드 테스트

- primary text가 한 번만 표시된다.
- decision panel이 요약을 반복하지 않는다.
- `추가 확인 필요` 제목이 중복되지 않는다.
- 해결된 질문이 사라진다.
- 남은 질문만 한 개씩 표시된다.
- legacy 메시지가 오류 없이 렌더링된다.
- 저장 실패를 확정 답변으로 표시하지 않는다.

### 13.5 E2E

이번 테스트 대화를 회귀 입력으로 포함하되 다음 변형과 합성 주제를 함께 사용한다.

- 자연스러운 서술형 조건 답변
- `모름` 응답
- 질문 도중 새로운 주제로 전환
- 치료 목적 조건
- 방문 유형 조건
- 증빙 보유 조건
- 특약 가입 조건

모든 쓰기 E2E는 격리 포트, 격리 chat DB, 격리 GraphDB에서 먼저 실행한다. 운영 포트는 배포 전 GET-only smoke만 수행한다.

### 13.6 전체 회귀

- 수술명·수술종수 resolver
- HIRA 수가 의도 게이트
- 4세대 MX122 계산
- 일반 질의와 계산의 동일 스레드 연결
- 이전 채팅 열람
- 4·5세대 문서 권한 구분
- GraphDB 관리자 시각화
- 대화 내보내기

검증 순서는 focused Python, Node, 전체 Python, 격리 Playwright, ontology/Graph/vector sync, DGX 리소스·로그, 최종 사용자 수준 smoke 순이다.

## 14. 배포와 롤백

### 14.1 릴리스 A 게이트

1. 격리 작업공간 구현과 dry-run
2. 독립 리뷰
3. active/Graph 예상 diff 제시
4. 별도 active 적용 승인
5. corrected manifest 원자적 교체
6. 임시 GraphDB 빌드·검사 후 원자적 교체
7. 서비스 재기동과 fail-closed smoke

### 14.2 릴리스 B 게이트

1. focused·전체·E2E 통과
2. 기존 기능 회귀 없음
3. 릴리스 A safe baseline 유지 확인
4. 독립 리뷰
5. DGX 메인 반영 승인
6. 서비스 배포와 사용자 수준 smoke

### 14.3 롤백

- 감사 로그와 correction record는 롤백하지 않는다.
- 대화 DB를 삭제하거나 재작성하지 않는다.
- 기능 릴리스 실패 시 릴리스 A corrected safe baseline으로 복귀한다.
- GraphDB는 검증된 safe snapshot으로 원자적 교체한다.
- 불완전한 부분 배포에서는 새 결정 엔진을 활성화하지 않는다.
- 승인 범위 초과 상태는 기능 롤백 대상으로 사용하지 않는다.

## 15. 성능과 DGX 자원

- continuation과 slot resolution은 구조화 규칙으로 처리하고 추가 LLM 호출을 필수화하지 않는다.
- 요청 중 GraphDB 재구축이나 manifest 재병합을 수행하지 않는다.
- assistant metadata 크기는 최신 unresolved/resolved 상태에 필요한 bounded payload로 제한한다.
- 상태 복원은 세션의 bounded recent messages를 대상으로 수행한다.
- GPU 부하는 기존 답변 생성 경로보다 증가하지 않는 것을 합격 기준으로 둔다.

## 16. 완료 기준

- 승인 후보에 없는 active field가 0개다.
- active 변경 field의 승인 provenance 추적률이 100%다.
- 승인 범위 초과 GraphDB 확정 노드가 0개다.
- 후속 답변이 이전 pending request와 연결된다.
- 해결된 질문 반복이 0건이다.
- 직접 근거와 관련 근거의 오표시가 0건이다.
- 본문과 구조화 패널의 의미 중복이 0건이다.
- 실제 2턴 사례와 주제 독립 합성 사례가 모두 통과한다.
- 전체 Python, Node, Playwright 검증이 통과한다.
- 계산, 수술종수, 채팅 이력, 관리자 GraphDB 기능에 회귀가 없다.
- DGX main 코드와 운영 artifact 버전이 일치한다.
- 임시 DB, 로그, 디버그 코드가 저장소에 남지 않는다.

## 17. 구현 경계 요약

이 설계가 허용하는 변경은 일반 승인 무결성 검사, 일반 대화 확인 상태, 일반 근거 적용성 판정, 단일 출력 계약이다. 특정 테스트 문장을 위한 alias 추가, 질환별 Python 분기, 미승인 의학 지식의 ontology/GraphDB 승격, prompt-only 보완은 허용하지 않는다.
