# Chat Thread, Procedure Search, and Claim Calculation Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이전 채팅 열람을 안정화하고, 하나의 채팅 스레드 안에서 보험금 계산·재계산·일반 질의가 같은 대화 맥락과 계산 근거를 자연스럽게 공유하도록 한다. 수술종수 질의는 수가코드 조회로 이탈하지 않고 정확한 수술명·등급 체계·문서 근거를 결정적으로 답하며, 4세대 도수치료 계산은 비급여 표준코드와 실무자 승인 룰을 올바르게 선택한다.

**Architecture:** 채팅 스레드를 유일한 대화 경계로 삼고, `general`/`claim`은 타임라인을 교체하는 모드가 아니라 입력 UI만 바꾸는 표시 상태로 제한한다. 서버는 저장된 계산 스냅샷을 버전과 상태가 있는 구조화 이벤트로 관리하고, 일반 질의와 재계산이 동일한 `ClaimThreadContext`를 사용하게 한다. 프런트엔드는 세션 전환마다 요청 세대를 발급하여 늦게 도착한 응답이 다른 스레드 화면이나 활성 세션을 덮어쓰지 못하게 한다. 별도의 결정적 `ProcedureGradeResolution` 계층이 질문 파싱·GraphDB·구조화 표를 하나의 우선순위 계약으로 묶고, 계산 파이프라인은 청구 금액의 급여/비급여 범위를 표준코드 매칭에 전달한 뒤 승인된 4세대 3대비급여 하위 룰만 적용한다.

**Tech Stack:** FastAPI, SQLAlchemy async SQLite, GraphDB SQLite, Parquet 구조화 표, 승인형 claim-rule manifest, Pydantic, 정적 SPA JavaScript, SSE, pytest/anyio, Node test runner, Playwright.

## Global Constraints

- 대화·계산 데이터의 기준 저장소는 서버 DB이며 브라우저 로컬 상태를 대화 원본으로 사용하지 않는다.
- 일반 질의와 보험금 계산은 같은 `session_id` 아래 시간순으로 함께 표시한다.
- 모드 전환만으로 메시지, 활성 세션, 계산 스냅샷 또는 진행 중인 폼을 삭제하지 않는다.
- 사용자 소유가 확인된 세션만 조회·계산·후속 질의에 사용할 수 있다.
- 계산 결과의 금액·분류·공제 규칙은 저장된 계산 스냅샷과 승인된 계산 파이프라인만 권위로 사용한다. LLM이 금액을 재구성하지 않는다.
- 후보 선택 대기 결과는 열람 가능하게 저장하되, 완료된 계산처럼 후속 계산의 기준으로 사용하지 않는다.
- 수술종수 질의는 사용자가 `수가`, `수가코드`, `심평원`, `수가표`, `점수`, `수술코드`를 명시하지 않은 한 심평원 직접 조회로 보내지 않는다.
- 수술명은 정확 일치 또는 승인된 별칭만 자동 확정한다. 의미상 유사하지만 근거가 없는 명칭은 후보와 구별 기준을 제시하고 확인을 요청한다.
- GraphDB의 확정 `HAS_GRADE` 사실이 있으면 요청한 등급 체계와 원문 페이지를 답변 첫 문장에 결정적으로 표시한다. 일반 RAG/LLM이 이를 수가코드 표나 포괄적 검토 문구로 덮어쓰지 못하게 한다.
- 미승인 claim-rule 후보는 운영 계산에 사용하지 않는다. 후보가 없거나 근거 필드가 불완전하면 기존 후보를 억지로 승인하지 않고 원문 근거에서 새 후보를 만든다.
- 표준코드가 모호한 계산은 `0원 공제 / 0원 지급`의 완료 계산으로 표시하지 않는다. 후보 선택 대기 상태와 제외 사유를 구조적으로 저장한다.
- 4세대 도수·체외충격파·증식치료 룰은 일반 비급여 건당 한도와 혼용하지 않고 전용 공제율·연간 한도·횟수 한도를 사용한다.
- 기존 `claim_snapshot` schema version 1 기록은 계속 열람하고 후속 질의에 사용할 수 있어야 한다.
- 사용자 원문, 계정 정보, 대화 내용 또는 계산 데이터를 테스트 fixture와 로그에 복사하지 않는다.
- 구현은 현재 진행 중인 Developer 변경과 병합한 최신 `master` 기준의 격리 작업공간에서 수행한다.
- 사용자 승인 없이 기존 대화 DB를 삭제하거나 재작성하지 않는다.

---

## Investigation Summary

### 확인된 결함

1. `frontend/js/pages/chat.js:setMode()`는 `currentSession`은 유지하면서 `msgs`와 타임라인 DOM을 환영 화면으로 교체한다. 같은 스레드에서 계산 모드와 일반 모드를 오가면 실제 DB 연결은 남아 있어도 사용자가 보는 대화는 사라진다.
2. `loadSessions()`는 이전 활성 세션을 표시할 수 있지만 메시지를 자동 복원하지 않는다. 모듈 재로딩 후 `currentSession`은 메모리에서 사라지므로 새로고침 복원도 안정적이지 않다.
3. `loadHist()`는 진행 중인 SSE/계산 요청을 중단하지 않고, 요청 순서 검증 없이 응답을 렌더링한다. 이전 요청의 늦은 `done` 이벤트가 새로 선택한 세션 ID와 화면을 덮어쓸 수 있다.
4. `/sessions/{id}/messages`는 `created_at`만으로 정렬한다. 같은 시간값을 가진 메시지의 순서를 보장하는 보조 키가 없다.
5. 세션 목록은 최초 `created_at`으로만 정렬하여 오래된 스레드에 새 메시지를 추가해도 최근 대화 상단으로 올라오지 않는다.
6. `build_claim_snapshot_context()`는 정상 계산된 항목의 이름·분류·청구액·공제액·지급액을 구조화 컨텍스트에 포함하지 않는다. 최근 메시지 260자 안에 우연히 남은 텍스트에 의존하므로 항목이 많거나 답변이 길면 연결이 끊긴다.
7. 일반 질의의 문서 검색은 현재 질문만 사용한다. `그 항목`, `그 금액`, `왜 그렇게 공제됐어?` 같은 참조 표현은 계산 스냅샷을 검색 질의에 반영하지 못한다.
8. 계산 스냅샷이 둘 이상이면 `select_claim_snapshot()`은 사용자가 `최근 계산`을 명시하지 않는 한 무조건 명확화 질문을 반환한다. 후보 선택 재계산만 해도 스냅샷이 여러 개 생겨 자연스러운 후속 질문이 자주 차단된다.
9. 후보 선택 대기 응답은 계산 스냅샷에 `candidates`를 저장하지 않아 이전 채팅을 다시 열었을 때 원래 선택 UI를 완전하게 복원할 수 없다.
10. `/chat/stream`은 DB 저장보다 `done` 이벤트를 먼저 보낸다. 커밋 실패 또는 직후 세션 조회 시 사용자가 본 답변과 저장된 내역이 잠시 또는 영구적으로 달라질 수 있다.

### 현재 테스트의 공백

- 기존 Playwright는 저장된 계산 카드 한 건을 클릭해 복원하는 정상 경로만 검증한다.
- 새로고침 자동 복원, 모드 전환 후 타임라인 유지, 진행 중 세션 전환, 늦은 응답 차단, 실패 rollback 테스트가 없다.
- 현재 단위 테스트는 다중 스냅샷에서 명확화를 요구하는 기존 동작을 정답으로 고정하고 있어 사용자가 기대하는 최근 계산 기본 선택과 반대다.

### 추가 조사: 수술명·수술종수 검색

1. `23278c3`에서 추가된 심평원 의도 게이트는 필요한 보완이며 현재 DGX 회귀 테스트도 통과한다. 그러나 이 패치는 수가표로 잘못 이탈하는 경로만 막고 정확한 수술종수 답변을 생성하는 경로는 완성하지 않는다.
2. `GraphQueryPlanner.grade_system_rx`는 `1~5종`을 인식하지만 결과를 `1~5종` 그대로 저장한다. 하위 조회기는 `1-5종`만 기준값으로 사용하므로 사용자가 물은 체계를 좁히지 못한다.
3. `grade_value_rx`는 `1~5종` 안의 `5종`을 별도 등급 값으로 다시 포착한다. 따라서 “1~5종에서 몇종”을 “5종 수술 목록”처럼 오해할 수 있다.
4. 의도 분류는 `몇 종`만 포함하고 `몇종`, `몇종으로`를 포함하지 않는다. 실제 앱샷의 “몇종으로 줘?”가 `ordinary_rag`로 떨어진다.
5. `_extract_surgery_name_from_query()`는 `X의 1-5종` 형태 중심이어서 `X은 1~5종에서 몇종...`과 `X 종수를 알려줘`를 놓친다. 이때 구조화 표 직접 조회가 생략되고 일반 RAG가 답변을 주도한다.
6. `TableStore.lookup_surgery_grade()`는 부분 일치 결과의 첫 행을 반환한다. `결장폴립절제술`을 물어도 더 긴 `소장 또는 결장 폴립절제술`이 먼저 선택될 수 있다.
7. GraphDB에는 다음 확정 근거가 존재한다.
   - `결장폴립절제술`: 1-3종 2종 / 1-5종 4종 / 신1-5종 4종, 실무가이드 p.110.
   - `결장경하 폴립절제술`: 1-3종 1종 / 1-5종 2종 / 신1-5종 1종, 실무가이드 p.167.
8. `대장용종절제술`은 현재 GraphDB의 정확 노드나 승인 별칭이 아니다. 데이터상 개복 `결장폴립절제술` 4종과 내시경 `결장경하 폴립절제술` 2종이 모두 후보이므로 자동 동의어 치환은 위험하다. “결장경/내시경을 이용했는지”를 확인해야 한다.
9. 수가코드 `Q7701`은 표준코드 DB에 `결장경하 종양 수술-폴립 절제술`로 존재하지만 GraphDB 수술 노드와 검증된 연결이 없다. 코드 질의는 코드→표준명→수술 후보의 근거 있는 연결이 없으면 종수를 확정하면 안 된다.
10. 현재 답변 경로에는 확정 `HAS_GRADE`를 최종 문장으로 고정하는 결정적 빌더가 없다. GraphDB가 정답을 갖고도 LLM이 수가코드 표나 일반 보장 검토 문구를 앞세울 수 있다.

### 추가 조사: 4세대 도수치료 계산

1. 앱샷의 `도수치료`, 비급여 500,000원 입력은 이름 매칭에서 두 표준코드가 동시에 반환된다.
   - `51040 도수치료`: 급여 항목, 급여 외 산정 불가, 면책.
   - `MX122 도수치료 [1일당]`: 비급여 특약1(도수), 추가 확인.
2. 따라서 0원/0원의 직접 원인은 “액티브 룰 없음” 하나가 아니라, 비급여 금액 입력임에도 급여 `51040`을 제거하지 못해 코드 선택 대기 상태가 된 것이다. 현재 UI는 이 보류 상태를 계산된 0원처럼 보여 오해를 만든다.
3. `MX122`를 명시하면 현재는 250,000원 공제 / 250,000원 지급으로 계산된다. 이는 정확한 4세대 3대비급여 전용 룰이 없어 `_4TH_NON_BENEFIT_ALIASES`가 일반 비급여 룰의 건당 지급한도 250,000원을 재사용하기 때문이다.
4. 자사 4세대 약관 `약관_ch_002441`~`약관_ch_002443`의 직접 근거는 도수·체외충격파·증식치료에 대해 다음을 정한다.
   - 1회당 공제: 30,000원과 보장대상 의료비의 30% 중 큰 금액.
   - 연간 한도: 3,500,000원, 도수·체외충격파·증식치료 합산 50회.
   - 최초 10회 이후: 객관적 증상 개선·병변 호전 확인 후 10회 단위 보장.
5. 현재 pending 후보에는 4세대 `3대비급여` 전용 후보가 없다. 존재하는 일반 비급여 후보는 원문 30%를 `copay_ratio=0.7`처럼 역산하거나 하위 유형·연간 한도를 보존하지 못하므로 이번 해결을 위해 승인하면 안 된다.
6. 후보 추출기의 일반 비율 로직은 문서의 백분율을 지급률로 가정해 `1 - percent`를 공제율로 저장한다. 공제율을 직접 서술한 약관에서는 의미가 반전되므로 근거 문맥에 따른 비율 종류 구분이 필요하다.
7. 청구 이력이 한도 내이고 최초 10회 또는 호전 확인 조건이 충족된 단일 500,000원 `MX122` 계산의 약관상 공제는 150,000원, 예상 지급은 350,000원이다. 연간 누적 금액·횟수와 10회 이후 증빙은 별도 확인 상태로 남겨야 한다.

## Considered Approaches

### A. 프런트엔드 최소 패치

`setMode()`의 `renderWelcome()`만 제거하고 `loadHist()`에서 SSE를 취소한다. 빠르지만 정상 계산 항목이 서버 컨텍스트에서 유실되는 문제, 후보 스냅샷 복원, 다중 계산 선택 규칙은 해결하지 못한다.

### B. 스레드 중심 상태 계약 정비 — 권장

타임라인은 항상 하나로 유지하고, 서버에 버전·상태가 있는 계산 이벤트와 공통 `ClaimThreadContext`를 둔다. 프런트 세션 전환 경쟁 상태와 서버 계산 문맥을 함께 고치므로 두 사용자 증상을 같은 원인 계층에서 해결할 수 있다.

### C. 별도 Conversation Orchestrator 도입

모든 메시지를 새 이벤트 저장소와 대화 상태 머신으로 이전한다. 장기적으로 깔끔하지만 현재 SQLite 데이터 마이그레이션과 API 전면 교체가 필요해 이번 안정화 범위를 넘는다.

**Decision:** B를 구현한다. 기존 DB 테이블과 메시지 JSON을 호환 유지하여 대량 마이그레이션 없이 문제를 해결한다.

### 수술명 해소 방식

- **자유로운 fuzzy 자동 치환:** 검색 성공률은 높아 보이지만 개복 4종과 내시경 2종을 잘못 합칠 수 있어 제외한다.
- **GraphDB 재색인만 수행:** 원본 데이터의 정확 노드는 살릴 수 있으나 질문 파서·표 우선순위·최종 답변 덮어쓰기 문제를 해결하지 못해 단독 해법으로 사용하지 않는다.
- **정확 일치 → 승인 별칭 → 근거 후보 확인의 결정적 resolver:** 확정 사실과 모호성을 분리하고 앱샷의 세 질의를 모두 설명할 수 있으므로 채택한다.

### 도수치료 계산 방식

- **기존 pending 비급여 후보 승인:** 비율 의미와 하위 유형이 잘못 추출되어 있어 제외한다.
- **표준코드 매칭만 보완:** 0원/0원 보류 표시는 해결하지만 `MX122` 선택 후 일반 비급여 건당 한도를 잘못 적용하는 문제는 남아 단독 해법으로 사용하지 않는다.
- **비급여 범위 기반 코드 선택 + 4세대 도수치료군 전용 승인 룰:** 코드와 공제 규칙 두 계층을 함께 바로잡고 원문 근거를 유지하므로 채택한다.

---

## File Structure

- Create: `frontend/js/modules/chat-thread-state.js`
  활성 세션, 세션 로드 세대, AbortController, URL의 `session` 파라미터를 관리하는 순수 상태 모듈.
- Modify: `frontend/js/pages/chat.js`
  통합 타임라인 유지, 안정적인 세션 전환, 계산 폼/일반 입력 모드 분리, 저장된 계산 이벤트 복원.
- Modify: `frontend/js/modules/session.js`
  중복된 인메모리 세션 ID를 `chat-thread-state` 계약에 위임하거나 제거.
- Modify: `frontend/js/config.js`
  필요한 경우 호환용 세션 URL 키만 정의하고 대화 본문은 저장하지 않음.
- Create: `tests/test_frontend_chat_thread_state.mjs`
  요청 세대, 늦은 응답 무시, URL 복원 단위 테스트.
- Modify: `tests/e2e/chat.spec.js`
  이전 내역 복원, 모드 연속성, 요청 경쟁, 계산→일반 질의 통합 E2E.
- Modify: `src/api/models.py`
  DB 스키마 변경 없이 기존 `created_at`을 유지. 이번 계획에서는 `updated_at` 컬럼을 추가하지 않는다.
- Modify: `src/api/schemas/sessions.py`
  계산된 `last_activity_at` 필드를 세션 목록 응답에 추가.
- Modify: `src/api/routes/sessions.py`
  최근 메시지 시각 기반 정렬과 `(created_at, id)` 메시지 순서 보장.
- Create: `src/claim_calculation/thread_context.py`
  스냅샷 추출, v1/v2 호환, 완료 상태 판정, 최근 계산 선택, 프롬프트·검색용 구조화 컨텍스트 생성.
- Modify: `src/claim_calculation/thread_recalculation.py`
  공통 thread context를 사용하고 자연스러운 최근 계산 기본 선택 규칙을 적용.
- Modify: `src/api/routes/claim.py`
  schema v2 계산 이벤트와 후보 선택 상태를 저장.
- Modify: `src/api/rag_service.py`
  중복 스냅샷 추출 코드를 제거하고 일반 질의의 참조 해소·검색 질의 보강에 공통 thread context를 사용.
- Modify: `src/api/routes/chat.py`
  공통 문맥 라우팅, 저장 후 `done` 전송, 요청별 세션 ID 고정.
- Modify: `tests/test_api_sessions_db.py`
  최근 활동 정렬과 안정적인 메시지 순서 테스트.
- Create: `tests/test_claim_thread_context.py`
  v1/v2, 후보/완료, 일반 질의 참조, 상세 계산 컨텍스트 테스트.
- Modify: `tests/test_claim_thread_snapshot.py`
  schema v2 저장·복원 계약 테스트.
- Modify: `tests/test_claim_thread_recalculation.py`
  최근 완료 계산 기본 선택과 명시적 과거 계산 선택 테스트.
- Modify: `tests/test_api_chat_stream.py`
  계산 문맥을 사용한 일반 질의, 저장 순서, 같은 스레드 유지 API 회귀.
- Create: `src/rag/procedure_grade.py`
  수술명·등급 체계 파싱 결과와 GraphDB/구조화 표의 exact·alias·candidate 상태를 통합하는 결정적 resolver 및 답변 빌더.
- Modify: `src/graph/query_planner.py`
  `~` 정규화, 겹치는 등급 값 제거, 붙여 쓴 `몇종` 의도 및 수술명 조사 패턴 보완.
- Modify: `src/graph/retriever.py`
  정확 노드·승인 별칭 우선과 제한된 후보 반환, 수가코드 연결의 근거 상태 보존.
- Modify: `src/rag/table_store.py`
  수술명 정확 일치 우선, 부분 일치는 후보 목록으로 반환하고 첫 행 자동 선택을 금지.
- Modify: `src/rag/pipeline.py`
  `ProcedureGradeResolution`을 HIRA/일반 RAG보다 먼저 적용하고 확정 수술종수 답변을 보호.
- Create: `tests/test_procedure_grade_resolution.py`
  앱샷의 세 수술명, `1~5종`, 코드 질의, 확정/모호/누락 계약 회귀.
- Modify: `tests/test_graph_query_planner.py`, `tests/test_pipeline.py`, `tests/test_table_store.py`, `tests/test_graph_retriever.py`
  파싱·HIRA 억제·exact ranking·candidate provenance 회귀.
- Modify: `src/claim_calculation/standard_matcher.py`
  금액 범위(`benefit`/`nonpay`/`mixed`/`unknown`)를 매칭 조건에 포함하고 후보 수를 제한.
- Modify: `src/claim_calculation/pipeline.py`
  4세대 도수치료군 분류, 보류 상태의 0원 완료 표시 제거, 전용 룰 및 누적 한도 확인 상태 적용.
- Modify: `src/claim_calculation/deductible_rules.py`
  `3대비급여_도수` 정확 룰 조회를 추가하고 해당 유형의 일반 비급여 fallback을 금지.
- Modify: `scripts/extract_claim_rule_candidates.py`
  공제율·지급률 의미를 구분하고 3대비급여 하위 유형과 연간 금액·횟수 한도를 후보에 보존.
- Modify after practitioner approval: `data/rules/claim_deductible_rules.active.json`
  `약관_ch_002441`~`약관_ch_002443` 근거의 4세대 도수치료군 입원/통원 룰만 승격.
- Modify: `tests/test_claim_standard_matcher.py`, `tests/test_claim_calculation_pipeline.py`, `tests/test_deductible_rules.py`, `tests/test_claim_rule_candidate_review.py`
  비급여 범위 선택, exact code 우선, 잘못된 fallback 제거, 승인 전후 계산 결과 회귀.
- Create: `docs/272_CHAT_THREAD_AND_DOMAIN_LOOKUP_STABILIZATION_REPORT.md`
  구현 결과, 데이터 호환성, 수술명·계산 근거, 검증 명령, 운영 smoke 결과. `docs/271_RUNTIME_LLM_AND_HAIR_LOSS_RELEASE_REPORT.md`와 번호 충돌을 피한다.

---

### Task 1: Freeze the Reproduction Contract

**Files:**
- Create: `tests/test_frontend_chat_thread_state.mjs`
- Modify: `tests/e2e/chat.spec.js`
- Modify: `tests/test_api_sessions_db.py`
- Create: `tests/test_claim_thread_context.py`

**Interfaces:**
- Consumes: 현재 `/sessions`, `/sessions/{id}/messages`, `/claim/calculate`, `/chat/stream` 계약.
- Produces: 이후 Task가 통과시켜야 하는 실패 재현 테스트.

- [ ] **Step 1: Add failing frontend state tests**

`tests/test_frontend_chat_thread_state.mjs`에 아래 계약을 작성한다.

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { createChatThreadState } from '../frontend/js/modules/chat-thread-state.js';

test('ignores a late history response after another session is selected', () => {
  const state = createChatThreadState();
  const first = state.beginLoad('session-a');
  const second = state.beginLoad('session-b');

  assert.equal(state.canCommit(first), false);
  assert.equal(state.canCommit(second), true);
  assert.equal(state.activeSessionId(), 'session-b');
});

test('mode changes do not replace the active thread', () => {
  const state = createChatThreadState();
  const load = state.beginLoad('session-a');
  state.commitLoad(load);

  state.setInputMode('claim');
  state.setInputMode('general');

  assert.equal(state.activeSessionId(), 'session-a');
  assert.equal(state.inputMode(), 'general');
});
```

- [ ] **Step 2: Add failing E2E scenarios**

`tests/e2e/chat.spec.js`에 다음 네 시나리오를 각각 독립 테스트로 추가한다.

```js
test('새로고침 후 URL의 이전 스레드를 자동 복원함', async ({ page }) => {
  await page.goto('/chat?session=session-a');
  await expect(page.locator('[data-session-id="session-a"]')).toHaveClass(/active/);
  await expect(page.locator('#chat-msgs')).toContainText('이전 답변 A');
});

test('일반 질의와 보험금 계산 모드 전환이 같은 타임라인을 유지함', async ({ page }) => {
  await page.click('[data-mode="claim"]');
  await expect(page.locator('#chat-msgs')).toContainText('기존 일반 답변');
  await page.click('[data-mode="general"]');
  await expect(page.locator('#chat-msgs')).toContainText('보험금 계산 결과');
});

test('느린 이전 세션 응답이 새 세션 화면을 덮어쓰지 않음', async ({ page }) => {
  await page.click('[data-session-id="session-a"]');
  await page.click('[data-session-id="session-b"]');
  await expect(page.locator('#chat-msgs')).toContainText('세션 B 답변');
  await expect(page.locator('#chat-msgs')).not.toContainText('세션 A의 늦은 답변');
});

test('계산 직후 일반 후속 질문이 동일 session_id를 전송함', async ({ page }) => {
  const captured = { claim: null, chat: null };
  await page.route('**/api/claim/calculate', async (route) => {
    captured.claim = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: 'mixed-session', claimed_amount: '150000', payable_amount: '105000',
        deductible: '45000', formula_intent: '', executed_code: '', applied_basis: [],
        requires_review: false, review_reasons: [], notes: '', candidates: [],
        policy_generation: '5th', special_calculation_status: 'not_applied',
        line_results: [], calculation_status: 'auto_calculated', warnings: [],
      }),
    });
  });
  await page.route('**/api/chat/stream', async (route) => {
    captured.chat = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'event: final\ndata: {"answer":"공제 설명"}\n\nevent: done\ndata: {"session_id":"mixed-session","answer":"공제 설명","persisted":true}\n\n',
    });
  });
  await page.click('[data-mode="claim"]');
  await page.click('[data-action="send-claim"]');
  await page.click('[data-mode="general"]');
  await page.fill('#chat-input', '그 공제금액이 나온 이유를 설명해 주세요');
  await page.keyboard.press('Enter');
  await expect.poll(() => captured.chat?.session_id).toBe('mixed-session');
  expect(captured.claim.session_id).toBeNull();
});
```

- [ ] **Step 3: Add failing backend contracts**

다음 기대값을 테스트에 고정한다.

```python
from types import SimpleNamespace

from src.claim_calculation.thread_context import (
    build_claim_thread_context,
    select_active_claim_snapshot,
)


def _snapshot_message(snapshot: dict) -> SimpleNamespace:
    return SimpleNamespace(
        role="assistant",
        content="보험금 계산 결과",
        sources=[{"__kind": "assistant_meta", "claim_snapshot": snapshot}],
    )


def test_thread_context_includes_completed_line_details():
    snapshot = {
        "schema_version": 2,
        "state": "completed",
        "result": {
            "line_results": [{
                "input_name": "도수치료",
                "category": "3대비급여",
                "claimed_amount": "150000",
                "deductible": "45000",
                "payable_amount": "105000",
                "calculation_status": "calculated",
            }],
        },
    }
    context = build_claim_thread_context([_snapshot_message(snapshot)], "그 계산을 설명해줘")
    assert "도수치료" in context.prompt_context
    assert "3대비급여" in context.prompt_context
    assert "청구 150000원" in context.prompt_context
    assert "공제 45000원" in context.prompt_context
    assert "지급 105000원" in context.prompt_context


def test_latest_completed_snapshot_is_default_after_candidate_selection():
    snapshots = [
        {"schema_version": 2, "state": "candidate_pending", "claim_id": "candidate"},
        {"schema_version": 2, "state": "completed", "claim_id": "completed"},
    ]
    selected = select_active_claim_snapshot(snapshots, "그 계산에서 왜 공제됐나요?")
    assert selected["state"] == "completed"
```

- [ ] **Step 4: Run the reproduction suite**

Run:

```bash
node --test tests/test_frontend_chat_thread_state.mjs
python -m pytest -q tests/test_api_sessions_db.py tests/test_claim_thread_context.py tests/test_claim_thread_snapshot.py tests/test_claim_thread_recalculation.py
npx playwright test tests/e2e/chat.spec.js --project=chromium
```

Expected: 새 테스트가 누락 모듈, 타임라인 초기화, 최근 계산 선택 실패로 실패한다. 기존 테스트 실패와 새 재현 실패를 구분해 기록한다.

---

### Task 2: Make Session History Loading Deterministic

**Files:**
- Create: `frontend/js/modules/chat-thread-state.js`
- Modify: `frontend/js/pages/chat.js`
- Modify: `frontend/js/modules/session.js`
- Modify: `src/api/schemas/sessions.py`
- Modify: `src/api/routes/sessions.py`
- Test: `tests/test_frontend_chat_thread_state.mjs`
- Test: `tests/test_api_sessions_db.py`

**Interfaces:**
- Produces: `createChatThreadState()`, `SessionResponse.last_activity_at`, 안정적인 메시지 순서.
- Consumes: 기존 사용자 소유권 검사와 `/sessions` API.

- [ ] **Step 1: Implement a request-generation state module**

`frontend/js/modules/chat-thread-state.js`에 다음 API를 구현한다.

```js
export function createChatThreadState() {
  let activeSession = '';
  let mode = 'general';
  let revision = 0;
  let loadController = null;

  return {
    beginLoad(sessionId) {
      loadController?.abort();
      loadController = new AbortController();
      activeSession = sessionId || '';
      revision += 1;
      return { sessionId: activeSession, revision, signal: loadController.signal };
    },
    canCommit(token) {
      return token.sessionId === activeSession && token.revision === revision && !token.signal.aborted;
    },
    commitLoad(token) {
      return this.canCommit(token);
    },
    clear() {
      loadController?.abort();
      activeSession = '';
      revision += 1;
    },
    activeSessionId: () => activeSession,
    setInputMode(value) { mode = value === 'claim' ? 'claim' : 'general'; },
    inputMode: () => mode,
  };
}
```

- [ ] **Step 2: Stabilize session list ordering without a DB migration**

`SessionResponse`에 `last_activity_at: datetime`을 추가한다. `list_sessions()`의 집계 서브쿼리는 메시지 개수와 `max(ChatMessage.created_at)`을 함께 계산하고 다음 순서로 정렬한다.

```python
last_activity = func.coalesce(count_subquery.c.last_message_at, ChatSession.created_at)
query = query.order_by(last_activity.desc(), ChatSession.created_at.desc(), ChatSession.id.desc())
```

메시지 조회와 export는 다음 순서를 사용한다.

```python
.order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
```

- [ ] **Step 3: Make history selection atomic in the SPA**

`loadHist()`는 다음 순서로 동작하게 수정한다.

1. 진행 중인 채팅/계산 요청을 `abortActiveChat()`로 중지한다.
2. `chatThreadState.beginLoad(sessionId)`로 토큰을 발급한다.
3. 로딩 표시만 렌더링하고 기존 활성 세션은 응답 성공 전까지 보존한다.
4. 응답 후 `canCommit(token)`이 참일 때만 DOM, `currentSession`, active class, URL을 갱신한다.
5. 실패하면 이전 세션과 화면을 유지하고 오류를 표시한다.

URL 갱신은 다음 형태로 제한한다.

```js
const url = new URL(window.location.href);
url.searchParams.set('session', sessionId);
window.history.replaceState({}, '', `${url.pathname}?${url.searchParams}`);
```

- [ ] **Step 4: Restore the requested session after list loading**

`initChatPage()`는 `loadSessions()` 결과를 받은 뒤 URL의 `session`이 사용자 소유 목록에 있을 때만 `loadHist()`를 호출한다. `?new=`가 있으면 자동 복원하지 않는다.

- [ ] **Step 5: Verify focused history tests**

Run:

```bash
node --test tests/test_frontend_chat_thread_state.mjs
python -m pytest -q tests/test_api_sessions_db.py tests/test_api_sessions_export.py
npx playwright test tests/e2e/chat.spec.js --project=chromium --grep "스레드|세션|내역|새로고침"
```

Expected: 세션 정렬·메시지 순서·자동 복원·늦은 응답 차단 시나리오가 모두 통과한다.

---

### Task 3: Preserve One Timeline Across Input Modes

**Files:**
- Modify: `frontend/js/pages/chat.js`
- Modify: `tests/e2e/chat.spec.js`

**Interfaces:**
- Consumes: Task 2의 활성 세션 상태.
- Produces: 일반/계산 입력 UI와 무관한 단일 메시지 타임라인.

- [ ] **Step 1: Remove destructive mode switching**

`setMode()`에서 다음 두 동작을 제거한다.

```js
msgs = [];
renderWelcome();
```

대신 `syncModeChrome()`, 탭 active 상태, 계산 입력 패널 표시만 바꾼다. `currentSession`과 `#chat-msgs`는 변경하지 않는다.

- [ ] **Step 2: Keep the claim form as a draft editor**

세션 전환 시 계산 폼은 다음 규칙을 적용한다.

- 새 채팅: 빈 기본 폼.
- 이전 스레드 열기: 가장 최근 완료 계산 스냅샷의 입력값을 읽기 전용 복원 버튼으로 불러올 수 있게 함.
- 단순 모드 전환: 현재 입력 중인 폼을 유지.
- 다른 스레드로 전환: 이전 스레드의 폼 draft는 폐기하고 선택한 스레드의 최근 계산을 기준으로 초기화.

복원 버튼은 기존 계산을 자동 재실행하지 않고 사용자가 확인 후 `계산`을 눌러야 한다.

- [ ] **Step 3: Do not use `msgs` as a second history source**

`msgs`가 export나 전송에 사용되지 않는 현재 상태를 확인한 뒤 제거하거나 화면 전용 캐시로 명시한다. 서버 메시지 DB와 충돌하는 로컬 대화 원본으로 사용하지 않는다.

- [ ] **Step 4: Verify the mixed timeline**

Run:

```bash
npx playwright test tests/e2e/chat.spec.js --project=chromium --grep "모드 전환|같은 타임라인|계산 직후"
```

Expected: 일반 질문 → 계산 → 일반 후속 질문의 세 사용자 메시지와 세 응답이 같은 타임라인에 순서대로 남는다.

---

### Task 4: Version and Classify Claim Snapshots

**Files:**
- Create: `src/claim_calculation/thread_context.py`
- Modify: `src/api/routes/claim.py`
- Modify: `src/api/rag_service.py`
- Modify: `src/api/routes/chat.py`
- Test: `tests/test_claim_thread_context.py`
- Test: `tests/test_claim_thread_snapshot.py`

**Interfaces:**
- Produces: `extract_claim_snapshots()`, `snapshot_state()`, `select_active_claim_snapshot()`, `build_claim_thread_context()`.
- Consumes: 기존 message `sources`의 `assistant_meta.claim_snapshot`.

- [ ] **Step 1: Define schema v2 without rewriting old rows**

새 계산 저장 형식은 다음과 같다.

```python
{
    "schema_version": 2,
    "state": "candidate_pending" | "completed" | "conditional",
    "claim_id": "uuid",
    "created_at": "ISO-8601",
    "input": {"items": [...], "context": {...}},
    "result": {
        "claimed_amount": "...",
        "deductible": "...",
        "payable_amount": "...",
        "line_results": [...],
        "candidates": [...],
        "calculation_status": "...",
        "requires_review": False,
    },
}
```

`snapshot_state()`는 v1에 `state`가 없으면 `candidates`가 있을 때 `candidate_pending`, 그 외에는 `completed`로 해석한다.

- [ ] **Step 2: Save candidate UI data**

`_claim_snapshot_source()`가 `response.candidates`를 `result.candidates`에 포함하도록 하고, 후보가 있으면 `state="candidate_pending"`를 저장한다. 후보 선택 후 성공 결과는 별도 `completed` 스냅샷으로 저장한다.

- [ ] **Step 3: Centralize snapshot extraction**

`rag_service.py`와 `chat.py`의 중복 `_extract_claim_snapshots` 구현을 제거하고 다음 공통 함수만 사용한다.

```python
def extract_claim_snapshots(messages: Sequence[Any]) -> list[dict[str, Any]]: ...
def completed_claim_snapshots(messages: Sequence[Any]) -> list[dict[str, Any]]: ...
```

- [ ] **Step 4: Restore candidate and completed cards**

프런트의 기존 `extractAssistantUiPayload()`와 `renderClaimResultHtml()`가 v1/v2 모두 처리하는지 검증하고, `candidate_pending`은 후보 버튼을, `completed`는 계산 카드를 렌더링한다.

- [ ] **Step 5: Verify snapshot compatibility**

Run:

```bash
python -m pytest -q tests/test_claim_thread_context.py tests/test_claim_thread_snapshot.py tests/test_api_claim_calculation.py
npx playwright test tests/e2e/chat.spec.js --project=chromium --grep "스냅샷|후보|계산 결과 카드"
```

Expected: 기존 v1 계산 카드, v2 후보 카드, v2 완료 카드가 모두 복원된다.

---

### Task 5: Build a Complete Claim Conversation Context

**Files:**
- Modify: `src/claim_calculation/thread_context.py`
- Modify: `src/api/rag_service.py`
- Test: `tests/test_claim_thread_context.py`
- Test: `tests/test_claim_thread_snapshot.py`

**Interfaces:**
- Produces: `ClaimThreadContext`, `contextualize_claim_query()`.
- Consumes: 완료된 계산 스냅샷과 현재 사용자 질문.

- [ ] **Step 1: Add the typed context result**

```python
@dataclass(frozen=True)
class ClaimThreadContext:
    active_snapshot: dict[str, Any] | None
    prompt_context: str
    retrieval_terms: tuple[str, ...]
    references_claim: bool
```

- [ ] **Step 2: Include every authoritative line field**

활성 계산의 각 항목을 다음 형식으로 제한·정제해 `prompt_context`에 포함한다.

```text
[이 스레드의 활성 보험금 계산]
- 계산 기준: 5세대 / 산정특례 미적용
- 도수치료 [3대비급여]: 청구 150000원 / 공제 45000원 / 지급 105000원 / 상태 calculated
- 비타민D 주사 [미분류 비급여]: 청구 48000원 / 공제 0원 / 지급 0원 / 상태 human_task
```

과거 완료 계산은 전체 항목을 반복하지 않고 claim id, 생성 시각, 총액만 최대 2건 요약한다.

- [ ] **Step 3: Detect whether the current question refers to a calculation**

다음 경우에만 `references_claim=True`로 설정한다.

- `그 계산`, `위 계산`, `방금 계산`, `그 금액`, `공제금액`, `지급금액`, `계산 결과` 같은 참조 표현이 있음.
- 현재 질문에 활성 스냅샷의 항목명 또는 계산 금액이 포함됨.
- 명시적인 재계산 의도가 감지됨.

명백히 독립적인 진단코드·수술종수·새 보상 질문은 계산 컨텍스트로 검색 질의를 오염시키지 않는다.

- [ ] **Step 4: Contextualize retrieval without changing the user question**

`prepare_retrieved_context()`는 원본 질문을 답변·감사 로그에 유지하고, 검색에만 다음 보강 질의를 사용한다.

```python
retrieval_question = contextualize_claim_query(question, claim_context)
hits, debug = pipeline.retrieve_hits(retrieval_question, **retrieval_kwargs)
prompt = pipeline.build_prompt(question, chunks, graph_context=graph_context)
prompt = f"{claim_context.prompt_context}\n\n{history_context}\n\n{prompt}"
```

- [ ] **Step 5: Verify context precision and isolation**

Run:

```bash
python -m pytest -q tests/test_claim_thread_context.py tests/test_claim_thread_snapshot.py tests/test_pipeline.py
```

Expected: 지시대명사 후속 질문은 항목명과 계산 기준으로 보강되고, 독립 질문은 원문 검색 질의를 그대로 사용한다.

---

### Task 6: Make Follow-up Selection Natural but Safe

**Files:**
- Modify: `src/claim_calculation/thread_recalculation.py`
- Modify: `src/api/routes/chat.py`
- Test: `tests/test_claim_thread_recalculation.py`
- Test: `tests/test_api_chat_stream.py`

**Interfaces:**
- Consumes: Task 4~5의 완료 스냅샷 목록과 활성 context.
- Produces: 최근 완료 계산 기본 선택, 명시적 과거 계산 선택, 안전한 명확화.

- [ ] **Step 1: Replace unconditional multi-snapshot clarification**

선택 규칙을 다음 우선순위로 변경한다.

1. `첫 번째 계산`, `두 번째 계산`, claim id 등 명시적 선택자가 있으면 해당 완료 계산.
2. `최근/마지막/직전/방금`이 있으면 최신 완료 계산.
3. 선택자가 없으면 최신 완료 계산을 기본값으로 사용.
4. 최신 계산에 대상 항목이 없으면 과거 완료 계산 중 항목이 유일하게 일치하는 계산을 선택.
5. 서로 다른 복수 계산에서 같은 대상명이 일치하고 결과가 달라 안전하게 고를 수 없을 때만 명확화.

- [ ] **Step 2: Preserve narrow deterministic authority**

재계산 파서는 금액을 LLM에 맡기지 않는다. 다음 표현군만 기존 계산 파이프라인으로 연결한다.

- 제외: `보상하지 않는다면`, `제외하면`, `빼면`
- 분류 변경: `급여 본인부담으로`, `비급여로`, `3대비급여로`
- 산정특례 상태 변경: `산정특례 적용/미적용으로`

그 외 `보상된다면`처럼 분류가 불명확한 요청은 기존 명확화 질문을 유지한다.

- [ ] **Step 3: Persist the resolved calculation as the new active snapshot**

재계산 성공 결과는 schema v2 `completed`로 저장하고 이후 일반 질의와 재계산의 최신 기준이 되게 한다. 명확화 답변은 계산 스냅샷을 만들지 않는다.

- [ ] **Step 4: Verify natural follow-ups**

Run:

```bash
python -m pytest -q tests/test_claim_thread_recalculation.py tests/test_api_chat_stream.py -k "claim or recalculation or snapshot"
```

Expected: 후보 선택 후 `그 계산에서 도수치료를 빼면?`은 최신 완료 계산을 사용하고, 실제로 모호한 과거 참조만 질문을 되돌린다.

---

### Task 7: Make Persistence and SSE Completion Atomic

**Files:**
- Modify: `src/api/routes/chat.py`
- Modify: `frontend/js/pages/chat.js`
- Modify: `tests/test_api_chat_stream.py`
- Modify: `tests/e2e/chat.spec.js`

**Interfaces:**
- Consumes: 기존 SSE `final`, `done`, `error` 이벤트.
- Produces: durable `done` 의미와 요청별 세션 소유권.

- [ ] **Step 1: Persist before emitting `done`**

일반 답변과 claim follow-up 모두 다음 순서를 사용한다.

```python
yield _sse("final", {"answer": answer})
await _persist_turn(...)
yield _sse("done", {"session_id": chat_session.id, "answer": answer, "persisted": True})
```

DB 커밋이 실패하면 `done`을 보내지 않고 `CHAT_HISTORY_PERSIST_FAILED` 오류 이벤트를 보낸다.

- [ ] **Step 2: Bind each frontend request to its originating session**

`streamChat()`과 `calculateClaim()`은 시작 시 `requestSessionId`와 thread-state revision을 캡처한다. 완료 시 현재 revision과 일치하는 경우에만 DOM과 `currentSession`을 갱신한다. 세션 전환 시 두 요청 모두 abort한다.

- [ ] **Step 3: Render failed optimistic user messages explicitly**

요청 실패 시 이미 화면에 추가된 사용자 메시지를 삭제하지 않고 `전송 실패` 상태와 재시도 버튼을 표시한다. 재시도는 원래 session id와 payload를 사용한다.

- [ ] **Step 4: Verify persistence ordering and cancellation**

Run:

```bash
python -m pytest -q tests/test_api_chat_stream.py -k "persist or done or cancelled"
npx playwright test tests/e2e/chat.spec.js --project=chromium --grep "느린|전송 실패|저장|세션 전환"
```

Expected: `done` 관찰 직후 세션 메시지 API에서 해당 turn이 조회되고, 취소된 이전 요청은 새 화면이나 활성 session id를 변경하지 않는다.

---

### Task 8: Verify Chat Continuity on DGX Main-App Conditions

**Files:**
- Modify only if required by build: `frontend/dist/app.min.js`

**Interfaces:**
- Consumes: Task 1~7의 테스트·빌드 결과.
- Produces: 운영 반영 가능 여부와 재현 가능한 smoke 기록.

- [ ] **Step 1: Run the focused local/DGX suite**

Run in the dependency-complete DGX isolated workspace:

```bash
python -m pytest -q \
  tests/test_api_sessions_db.py \
  tests/test_api_sessions_export.py \
  tests/test_claim_thread_context.py \
  tests/test_claim_thread_snapshot.py \
  tests/test_claim_thread_recalculation.py \
  tests/test_api_claim_calculation.py \
  tests/test_api_chat_stream.py
node --test tests/test_frontend_chat_thread_state.mjs tests/test_frontend_assistant_display.mjs
npm --prefix frontend run build
npx playwright test tests/e2e/chat.spec.js --project=chromium
git diff --check
```

Expected: 전부 통과. 기존 기준선 실패가 있으면 이번 변경 전 DGX 기준과 대조하여 새 회귀인지 분리한다.

- [ ] **Step 2: Run the full regression suite**

Run:

```bash
python -m pytest -q
```

Expected: 이번 변경으로 새 실패가 생기지 않는다. 실패를 skip/xfail로 숨기지 않는다.

- [ ] **Step 3: Perform six live smoke scenarios**

DGX 메인 앱과 같은 브라우저 조건에서 다음을 확인한다.

1. 일반 질문 스레드를 새로고침하고 이전 메시지가 자동 복원된다.
2. 기록 A를 연 직후 기록 B를 빠르게 열어도 B만 표시된다.
3. 일반 질문 → 계산 모드 → 보험금 계산 → 일반 모드 전환 후 모든 메시지가 한 타임라인에 남는다.
4. `그 공제금액이 나온 이유를 설명해 주세요`가 최신 계산의 항목·세대·공제값을 참조한다.
5. 후보 선택 후 `그 계산에서 도수치료를 빼면 얼마인가요?`가 최신 완료 계산을 기준으로 재계산한다.
6. 완전히 다른 진단코드 질문은 이전 계산 항목으로 오염되지 않는다.

- [ ] **Step 4: Capture chat-continuity verification evidence**

Task 11의 최종 보고서에 넣을 수 있도록 다음을 작업 로그에 기록한다.

- 변경 파일과 데이터 호환성
- v1/v2 스냅샷 처리 규칙
- 테스트 명령과 정확한 결과 수치
- 여섯 live smoke 결과
- 기존 DB를 삭제·재작성하지 않았다는 확인
- 남은 위험과 rollback 방법

- [ ] **Step 5: Review checkpoint**

커밋·push·DGX 메인 앱 반영은 모든 focused test, E2E, live smoke가 통과한 뒤 별도 승인 또는 기존 릴리스 지시에 따라 수행한다. 실패가 남으면 검증된 범위만 부분 배포하지 말고 fixback 상태로 보고한다.

---

### Task 9: Resolve Procedure Names and Surgery Grades Deterministically

**Files:**
- Create: `src/rag/procedure_grade.py`
- Modify: `src/graph/query_planner.py`
- Modify: `src/graph/retriever.py`
- Modify: `src/rag/table_store.py`
- Modify: `src/rag/pipeline.py`
- Create: `tests/test_procedure_grade_resolution.py`
- Modify: `tests/test_graph_query_planner.py`
- Modify: `tests/test_graph_retriever.py`
- Modify: `tests/test_table_store.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: 사용자 질문, `GraphQueryPlan`, 확정 `HAS_GRADE` facts, 실무가이드 surgery-grade Parquet 행, 승인 별칭.
- Produces: `confirmed`, `candidate_pending`, `not_found` 중 하나인 `ProcedureGradeResolution`과 사용자 표시용 결정적 답변.

- [ ] **Step 1: Add failing query-planner regressions**

`tests/test_graph_query_planner.py`에 앱샷 표현을 그대로 고정한다.

```python
import pytest


@pytest.mark.parametrize(
    ("query", "procedure", "grade_system"),
    [
        ("결장폴립절제술은 1~5종에서 몇종으로 줘?", "결장폴립절제술", "1-5종"),
        ("결장경하 폴립절제술 종수를 알려줘", "결장경하 폴립절제술", None),
    ],
)
def test_surgery_grade_query_normalizes_compact_korean_forms(query, procedure, grade_system):
    plan = GraphQueryPlanner().plan(query)

    assert plan.procedure_name == procedure
    assert plan.grade_system == grade_system
    assert plan.grade_value is None
    assert "surgery_grade_lookup" in plan.intents
```

- [ ] **Step 2: Prove the current parser fails for the right reasons**

Run:

```bash
python -m pytest -q tests/test_graph_query_planner.py -k "surgery_grade_query_normalizes_compact"
```

Expected before implementation: `1~5종` 미정규화, 내부 `5종` 오탐 또는 `몇종으로` 의도 누락으로 실패한다.

- [ ] **Step 3: Normalize grade spans before extracting a grade value**

`src/graph/query_planner.py`에서 등급 체계 span을 먼저 제거한 뒤 독립 등급 값만 찾는다.

```python
def _extract_grade_request(self, query: str) -> tuple[str | None, str | None]:
    system_match = self.grade_system_rx.search(query)
    grade_system = None
    value_source = query
    if system_match:
        grade_system = re.sub(r"\s+", "", system_match.group(1)).replace("~", "-")
        value_source = f"{query[:system_match.start()]} {query[system_match.end():]}"
    value_match = self.grade_value_rx.search(value_source)
    return grade_system, value_match.group(1) if value_match else None
```

의도 토큰은 `re.search(r"몇\s*종|어떤\s*종|종수|등급", query)`로 통합한다. 수술명 추출은 조사 `은/는/이/가/의`와 `종수를 알려줘`를 지원하되, 일반 명사 `수술종수` 자체를 수술명으로 반환하지 않는다.

- [ ] **Step 4: Introduce the resolution contract**

`src/rag/procedure_grade.py`에 다음 최소 계약을 둔다.

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ProcedureGradeCandidate:
    canonical_name: str
    grades: dict[str, str]
    source_doc: str
    source_page: str
    match_kind: Literal["exact", "approved_alias", "candidate"]
    distinction: str = ""


@dataclass(frozen=True)
class ProcedureGradeResolution:
    status: Literal["confirmed", "candidate_pending", "not_found"]
    query_name: str
    requested_system: str | None
    selected: ProcedureGradeCandidate | None
    candidates: tuple[ProcedureGradeCandidate, ...] = ()
    clarification_question: str = ""
```

해소 순서는 다음으로 고정한다.

1. GraphDB 정확 canonical name의 confirmed `HAS_GRADE`.
2. 실무자 승인 별칭이 가리키는 정확 canonical name.
3. 구조화 표의 정확 정규화 이름.
4. 최대 3개의 출처 있는 후보와 구별 질문.
5. 근거가 없으면 `not_found`; 임의 치환 금지.

- [ ] **Step 5: Make TableStore exact-first and candidate-aware**

`lookup_surgery_grade()`가 부분 일치 첫 행을 반환하지 않도록 분리한다.

```python
def lookup_surgery_grade_exact(self, surgery_name: str) -> dict | None: ...

def search_surgery_grade_candidates(
    self,
    surgery_name: str,
    *,
    limit: int = 3,
) -> list[dict]: ...
```

정확 정규화 이름은 유일할 때만 확정한다. 부분 일치·용어 치환 결과는 점수와 source page를 포함한 후보로만 반환한다.

- [ ] **Step 6: Lock the three user-visible outcomes**

`tests/test_procedure_grade_resolution.py`에 다음 계약을 작성하고 구현한다.

```python
def test_exact_open_colon_polypectomy_is_fourth_grade(...):
    result = resolve("결장폴립절제술은 1~5종에서 몇종으로 줘?")
    assert result.status == "confirmed"
    assert result.selected.grades["1-5종"] == "4종"
    assert result.selected.source_page == "110"


def test_exact_endoscopic_colon_polypectomy_is_second_grade(...):
    result = resolve("결장경하 폴립절제술 종수를 알려줘")
    assert result.status == "confirmed"
    assert result.selected.grades["1-5종"] == "2종"
    assert result.selected.source_page == "167"


def test_unapproved_colon_polyp_synonym_requires_procedure_confirmation(...):
    result = resolve("대장용종절제술은 1~5종에서 몇종으로 줘?")
    assert result.status == "candidate_pending"
    assert {item.canonical_name for item in result.candidates} == {
        "결장폴립절제술",
        "결장경하 폴립절제술",
    }
    assert "결장경" in result.clarification_question or "내시경" in result.clarification_question
```

- [ ] **Step 7: Make the resolved answer authoritative in the RAG pipeline**

`src/rag/pipeline.py`에서 `surgery_grade_lookup`은 HIRA와 일반 RAG보다 먼저 resolver를 호출한다.

- `confirmed`: `결장경하 폴립절제술은 1-5종 기준 2종입니다. (실무가이드 p.167)`처럼 요청한 체계·값·출처를 첫 문장에 고정한다.
- `candidate_pending`: 두 수술명, 각각의 잠정 종수와 개복/결장경 차이를 보여주고 한 개의 명확화 질문을 반환한다.
- `not_found`: 수가표를 대신 보여주지 않고 수술기록지의 정확 수술명 또는 수술코드를 요청한다.
- 모든 세 상태에서 단독 `술 → 음주 후 상해` 보정을 노출하지 않는다.
- 사용자가 수가 의도를 명시하지 않았다면 `build_hira_fee_answer()`를 호출하지 않는다.

- [ ] **Step 8: Treat Q7701 as a provenance-bearing bridge, not an implicit alias**

`Q7701`은 표준코드 exact lookup 후 `결장경하 종양 수술-폴립 절제술`을 얻는다. GraphDB에 코드→수술 관계가 confirmed로 승인되어 있으면 해당 수술 종수로 이동하고, 그렇지 않으면 후보 확인 상태를 반환한다. 코드 문자열 유사도만으로 `결장경하 폴립절제술`을 확정하지 않는다.

- [ ] **Step 9: Run focused surgery-grade verification**

Run:

```bash
python -m pytest -q \
  tests/test_graph_query_planner.py \
  tests/test_graph_retriever.py \
  tests/test_table_store.py \
  tests/test_procedure_grade_resolution.py \
  tests/test_pipeline.py -k "surgery or grade or hira"
```

Expected: 앱샷 세 질의의 확정/확인 결과가 통과하고, 일반 수술종수 질문에는 HIRA 수가표 문구가 0건이다.

- [ ] **Step 10: Commit checkpoint**

```bash
git add src/rag/procedure_grade.py src/graph/query_planner.py src/graph/retriever.py src/rag/table_store.py src/rag/pipeline.py tests/test_procedure_grade_resolution.py tests/test_graph_query_planner.py tests/test_graph_retriever.py tests/test_table_store.py tests/test_pipeline.py
git commit -m "fix(rag): resolve surgery grades deterministically"
```

---

### Task 10: Fix 4th-Generation Manual-Therapy Matching and Rules

**Files:**
- Modify: `src/claim_calculation/standard_matcher.py`
- Modify: `src/claim_calculation/pipeline.py`
- Modify: `src/claim_calculation/deductible_rules.py`
- Modify: `scripts/extract_claim_rule_candidates.py`
- Modify only after practitioner approval: `data/rules/claim_deductible_rules.active.json`
- Modify: `tests/test_claim_standard_matcher.py`
- Modify: `tests/test_claim_calculation_pipeline.py`
- Modify: `tests/test_deductible_rules.py`
- Modify: `tests/test_claim_rule_candidate_review.py`

**Interfaces:**
- Consumes: `ClaimItemInput` 금액 구분, 표준코드 DB, 자사 4세대 약관 chunk `약관_ch_002441`~`약관_ch_002443`, 승인 후보 로그.
- Produces: 범위에 맞는 bounded 표준코드 결과, 명시적인 계산 보류 상태, 승인된 `3대비급여_도수` 공제 룰.

- [ ] **Step 1: Add failing scope-aware matcher tests**

```python
def test_nonpay_manual_therapy_prefers_mx122():
    matches = match_standard_code("도수치료", care_scope="nonpay")
    assert [match.std_cd for match in matches] == ["MX122"]


def test_unknown_scope_keeps_bounded_disambiguation():
    matches = match_standard_code("도수치료", care_scope="unknown", limit=6)
    assert {match.std_cd for match in matches} == {"51040", "MX122"}
    assert all(match.requires_user_disambiguation for match in matches)


def test_explicit_code_still_wins():
    assert match_standard_code("도수치료", "51040", care_scope="nonpay")[0].std_cd == "51040"
```

- [ ] **Step 2: Prove current matching cannot use the amount scope**

Run:

```bash
python -m pytest -q tests/test_claim_standard_matcher.py -k "manual_therapy or scope"
```

Expected before implementation: 함수가 `care_scope`를 받지 않거나 두 후보를 함께 반환하여 실패한다.

- [ ] **Step 3: Add care-scope filtering without weakening exact-code behavior**

`match_standard_code()` 계약을 다음과 같이 확장한다.

```python
def match_standard_code(
    input_name: str,
    input_code: str = "",
    *,
    care_scope: Literal["benefit", "nonpay", "mixed", "unknown"] = "unknown",
    limit: int = 6,
) -> list[StandardMatch]: ...
```

계산 파이프라인은 급여 본인부담 0원·비급여 양수이면 `nonpay`, 반대이면 `benefit`, 둘 다 양수이면 `mixed`, 금액 정보가 없으면 `unknown`을 전달한다. 이름 검색에서 `nonpay`는 급여·급여외 산정불가·면책 전용 행을 제외하므로 `MX122`가 남는다. 사용자가 코드를 직접 입력한 경우에는 exact code가 항상 우선하며 불일치 자체를 review reason으로 기록한다.

- [ ] **Step 4: Correct the calculation-state contract**

표준코드 후보가 둘 이상이면 line item을 다음 상태로 저장한다.

```python
{
    "calculation_status": "needs_code_selection",
    "excluded_from_calculation": True,
    "deductible_amount": None,
    "payable_amount": None,
    "candidates": [...],
}
```

전체 결과는 `blocked_missing_info`이며 UI 문구는 “표준코드 선택 전 산정 보류”다. 0원은 확정 면책 또는 실제 0원 계산에만 사용한다. 후보 표시 수는 최대 6개로 제한하고 전체 DB 후보를 검토 사유 본문에 덤프하지 않는다.

- [ ] **Step 5: Generate new source-grounded rule candidates; approve none of the current pending rows**

현재 pending 일반 비급여 후보는 승인하지 않는다. `약관_ch_002441`~`약관_ch_002443`에서 다음 `proposed_rule` payload를 가진 두 후보를 새로 만든다.

```json
{
  "rule_id": "deductible.4th.three_major_manual.hospitalization",
  "generation": "4th",
  "category": "3대비급여_도수",
  "visit_type": "hospitalization",
  "facility_grade": "all",
  "copay_ratio": "0.3",
  "min_deductible": "30000",
  "min_deductible_by_facility": {
    "clinic": "30000",
    "hospital": "30000",
    "general_hospital": "30000",
    "tertiary_hospital": "30000"
  },
  "per_visit_limit": null,
  "annual_limit": "3500000",
  "annual_visit_limit": 50,
  "description": "4세대 도수치료군: 1회당 3만원과 보장대상의료비 30% 중 큰 금액, 연 350만원·50회",
  "source_doc": "약관",
  "source_page": "71-78",
  "source_clause": "제3조 보장종목별 보상내용 / 3대비급여 특별약관",
  "source_chunk_id": "약관_ch_002441",
  "additional_source_refs": ["약관_ch_002442", "약관_ch_002443"],
  "source_status": "source_grounded",
  "approval_status": "candidate"
}
```

통원 후보는 동일 필드에서 `visit_type=outpatient`으로 만든다. 후보 근거에는 최초 10회 이후 증상 개선 확인 규칙(`약관_ch_002442`)과 동일 방문 복수 치료 횟수 규칙(`약관_ch_002443`)을 함께 연결한다. 이 계획 승인과 룰 후보의 실무 승인 기록은 별도 단계이며 자동 승격하지 않는다.

- [ ] **Step 6: Fix percentage semantics in candidate extraction**

`scripts/extract_claim_rule_candidates.py`는 백분율 주변의 `공제금액`, `본인부담`, `지급`, `보상` 문맥을 구분한다.

- `공제금액 ... 30%`, `본인부담 30%` → `copay_ratio=0.3`.
- `80% 보상`, `지급률 80%` → `copay_ratio=0.2` 또는 별도 `payout_ratio=0.8`.
- 의미를 확정할 수 없으면 후보를 생성하지 않고 review reason을 남긴다.
- `3대비급여`는 도수치료군·주사료·MRI/MRA의 서로 다른 연간 한도를 하나의 generic row로 합치지 않는다.

- [ ] **Step 7: Apply an exact subtype rule only after review approval**

`_classify_claim_category()`는 도수·체외충격파·증식치료를 generic `3대비급여`보다 먼저 `3대비급여_도수`로 분류한다. `lookup_rule("4th", "3대비급여_도수", ...)`는 exact active row만 허용하고 일반 `비급여` fallback을 사용하지 않는다.

승인 전에는 계산을 `blocked_missing_info`로 보류하며 “4세대 도수치료군 전용 승인 룰 없음”을 표시한다. 승인 후에는 단일 지급액을 계산하되 누적 청구 이력이 없으면 연간 350만원·50회 및 최초 10회 이후 호전 증빙을 `estimated_review_required` 사유로 남긴다.

- [ ] **Step 8: Replace the legacy alias test with source-backed assertions**

```python
def test_4th_manual_therapy_uses_exact_three_major_rule():
    rule = lookup_rule("4th", "3대비급여_도수", "outpatient")
    assert rule.copay_ratio == Decimal("0.3")
    assert rule.get_min_deductible(FACILITY_CLINIC) == Decimal("30000")
    assert rule.per_visit_limit is None
    assert rule.annual_limit == Decimal("3500000")
    assert rule.annual_visit_limit == 50
    assert rule.source_chunk_id == "약관_ch_002441"


def test_4th_manual_therapy_500k_estimate_is_350k_payable():
    result = calculate(nonpay_amount="500000", code="MX122", generation="4th")
    assert result.total_deductible == Decimal("150000")
    assert result.total_payable == Decimal("350000")
    assert result.calculation_status == "estimated_review_required"
```

기존 `test_4th_3major_alias`는 삭제로 숨기지 말고 “generic alias를 사용하지 않는다”는 회귀로 교체한다.

- [ ] **Step 9: Verify approval boundaries and calculations**

Run:

```bash
python -m pytest -q \
  tests/test_claim_standard_matcher.py \
  tests/test_claim_calculation_pipeline.py \
  tests/test_deductible_rules.py \
  tests/test_claim_rule_candidate_review.py
python scripts/claim_rule_candidate_review.py --summary
python scripts/claim_rule_candidate_review.py --list-json
git diff --check
```

Expected: 잘못된 기존 후보는 pending 상태 그대로이며 active manifest에는 명시적으로 승인한 두 row만 들어간다. `도수치료` 비급여 500,000원은 `MX122` 및 150,000원 공제 / 350,000원 지급으로 계산되고 누적 한도 확인 표시가 남는다.

- [ ] **Step 10: Commit checkpoint**

```bash
git add src/claim_calculation/standard_matcher.py src/claim_calculation/pipeline.py src/claim_calculation/deductible_rules.py scripts/extract_claim_rule_candidates.py tests/test_claim_standard_matcher.py tests/test_claim_calculation_pipeline.py tests/test_deductible_rules.py tests/test_claim_rule_candidate_review.py
# 실무 승인 및 apply 검증까지 끝난 경우에만 다음 파일을 추가한다.
git add data/rules/claim_deductible_rules.active.json data/rules/rule_links.active.json data/rules/review/candidates.jsonl data/rules/review/review_log.jsonl
git commit -m "fix(claim): apply grounded manual therapy rules"
```

---

### Task 11: Combined Regression, Live Smoke, and Release Gate

**Files:**
- Create: `docs/272_CHAT_THREAD_AND_DOMAIN_LOOKUP_STABILIZATION_REPORT.md`
- Modify only if required by build: `frontend/dist/app.min.js`

**Interfaces:**
- Consumes: Task 1~10의 코드, 승인 기록, 테스트 결과, DGX 운영 앱 상태.
- Produces: 배포 가능한 단일 검증 판정 또는 구체적인 fixback 목록.

- [ ] **Step 1: Run the complete focused suite**

```bash
python -m pytest -q \
  tests/test_api_sessions_db.py \
  tests/test_api_sessions_export.py \
  tests/test_claim_thread_context.py \
  tests/test_claim_thread_snapshot.py \
  tests/test_claim_thread_recalculation.py \
  tests/test_api_claim_calculation.py \
  tests/test_api_chat_stream.py \
  tests/test_graph_query_planner.py \
  tests/test_graph_retriever.py \
  tests/test_table_store.py \
  tests/test_procedure_grade_resolution.py \
  tests/test_pipeline.py \
  tests/test_claim_standard_matcher.py \
  tests/test_claim_calculation_pipeline.py \
  tests/test_deductible_rules.py \
  tests/test_claim_rule_candidate_review.py
node --test tests/test_frontend_chat_thread_state.mjs tests/test_frontend_assistant_display.mjs
npm --prefix frontend run build
npx playwright test tests/e2e/chat.spec.js --project=chromium
git diff --check
```

- [ ] **Step 2: Run the full regression suite and compare the protected baseline**

```bash
python -m pytest -q
```

새 실패는 모두 해결한다. 기존 기준선 실패가 있으면 동일 DGX commit의 변경 전 격리 작업공간에서 재현하여 이번 변경과 독립인지 증명하고 보고서에 명시한다. skip/xfail로 숨기지 않는다.

- [ ] **Step 3: Verify ten fresh-session live scenarios**

DGX 앱을 새 세션·새 URL로 열고 캐시된 과거 답변이 아닌 새 응답을 확인한다.

1. 이전 채팅 새로고침 복원.
2. 세션 A/B 빠른 전환 시 B만 표시.
3. 일반→계산→일반 모드에서 한 타임라인 유지.
4. 최신 계산 공제 이유 후속 질문이 구조화 스냅샷을 참조.
5. `결장폴립절제술은 1~5종에서 몇종으로 줘?` → 4종, p.110, HIRA 표 없음.
6. `결장경하 폴립절제술 종수를 알려줘` → 2종, p.167, HIRA 표 없음.
7. `대장용종절제술은 1~5종에서 몇종으로 줘?` → 개복/결장경 후보와 확인 질문, 임의 확정 없음.
8. `수술코드 Q7701 1~5종에서 몇종이야?` → 승인된 코드 연결이 있으면 근거 포함 확정, 없으면 후보 확인.
9. 4세대 비급여 도수치료 500,000원 → `MX122`, 공제 150,000원, 지급 350,000원, 누적 한도 확인 표시.
10. 명시 코드 `51040` 또는 범위 미상 도수치료 → 각각 면책 근거 또는 코드 선택 보류이며 계산 완료 0/0으로 위장하지 않음.

각 수술 응답에서 `심평원 수가표 직접 조회`, 불필요한 수가코드 표, `술 → 음주 후 상해`가 없는지 텍스트 assertion으로 확인한다.

- [ ] **Step 4: Verify the running artifact, not only source files**

- DGX 보호 메인의 commit이 검증 commit과 일치하는지 확인한다.
- 앱 프로세스 시작 시각이 배포 commit 이후인지 확인한다.
- 브라우저가 참조하는 실제 JS bundle hash와 빌드 산출물이 일치하는지 확인한다.
- Qwen/SGLang 프로세스는 이번 앱 패치 검증을 위해 재시작하지 않는다.
- 인증된 테스트 계정의 새 테스트 스레드만 사용하고 기존 사용자 대화·계정을 변경하지 않는다.

- [ ] **Step 5: Write the combined implementation report**

`docs/272_CHAT_THREAD_AND_DOMAIN_LOOKUP_STABILIZATION_REPORT.md`에 다음을 기록한다.

- 변경 파일과 데이터 호환성
- 수술명별 exact/alias/candidate 판정표와 원문 페이지
- 새 룰 후보 ID, 승인자·승인 시각·근거 chunk, active manifest hash
- `도수치료` 500,000원 계산식과 누적 한도 제한
- focused/full/E2E/live smoke의 정확한 명령과 결과 수치
- DGX 실행 artifact commit·프로세스·bundle 확인
- 남은 위험과 rollback 방법

- [ ] **Step 6: Release checkpoint**

모든 테스트와 10개 live smoke가 통과하고 필요한 룰 후보의 실무 승인 기록이 확인된 경우에만 커밋·push·DGX 메인 앱 반영 대상으로 판정한다. 하나라도 실패하면 배포하지 않고 실패 증상, 재현 질문, 관련 계층, 수정 요구를 fixback 목록으로 작성한다.

---

## Acceptance Criteria

- 이전 채팅을 클릭하거나 `?session=<id>`로 새로고침하면 동일한 메시지와 계산 카드가 안정적으로 복원된다.
- 세션 A/B를 빠르게 전환해도 늦은 응답이 다른 세션 화면이나 ID를 덮어쓰지 않는다.
- 일반/보험금 계산 모드를 전환해도 타임라인이 지워지지 않는다.
- 계산과 일반 질의가 동일한 `session_id`로 저장된다.
- 정상 계산 항목의 이름·분류·청구·공제·지급값이 일반 후속 질의 컨텍스트에 구조적으로 전달된다.
- 다중 스냅샷에서는 최신 완료 계산이 기본이고 실제 모호한 경우에만 명확화를 요구한다.
- 후보 선택 대기와 완료 계산이 재열람 시 각각 올바른 UI로 복원된다.
- 독립 일반 질문은 과거 계산 컨텍스트로 오염되지 않는다.
- SSE `done`은 DB 저장 성공 이후에만 전달된다.
- 기존 schema v1 채팅 기록을 삭제하거나 변환하지 않고 계속 열람할 수 있다.
- `결장폴립절제술`의 1-5종은 4종(p.110), `결장경하 폴립절제술`은 2종(p.167)으로 답하며 수가표가 대신 노출되지 않는다.
- `대장용종절제술`은 승인 별칭이 없는 동안 개복/결장경 후보를 구분해 확인하고 임의로 한 종수를 확정하지 않는다.
- `1~5종`은 `1-5종`으로 정규화되고 내부 `5종`을 별도 등급 값으로 오해하지 않는다.
- GraphDB confirmed `HAS_GRADE`와 사용자 표시 답변이 동일하며 출처 페이지가 보존된다.
- 비급여 500,000원 `도수치료`는 금액 범위로 `MX122`를 선택하고, 승인된 4세대 전용 룰 기준 공제 150,000원·지급 350,000원을 표시한다.
- 표준코드 모호성 또는 전용 룰 미승인 상태는 0원 완료 계산이 아니라 구조화된 산정 보류로 표시된다.
- 기존 오류 후보는 승인하지 않으며 새 전용 룰은 원문 chunk·승인 로그·active manifest를 모두 추적할 수 있다.

## Plan Self-Review

- 네 사용자 요구사항은 Task 2~3(내역 열람), Task 4~7(계산·일반 질의 연속성), Task 9(수술명·수술종수), Task 10(도수치료 표준코드·룰)에 각각 대응한다.
- 프런트 화면만 고치는 최소 패치가 아니라 서버 문맥 유실과 다중 스냅샷 선택 규칙까지 포함한다.
- 수술명은 fuzzy 자동 확정이 아니라 exact/approved alias/candidate 상태로 분리하여 개복 4종과 내시경 2종 오판을 막는다.
- 도수치료 문제는 0원 표시만 바꾸지 않고 표준코드 선택과 4세대 전용 룰 부재를 함께 해결한다.
- DB 컬럼 마이그레이션 없이 최근 활동 정렬을 계산하므로 기존 운영 DB 위험을 줄인다.
- 계산 권위는 기존 결정적 파이프라인에 유지되며 LLM에 금액 계산을 위임하지 않는다.
- 미승인 후보를 자동 승격하지 않고 실무자 승인 gate를 유지한다.
- 구현 단계에서 사용할 함수 이름과 책임, 테스트 명령, 성공 기준을 명시했다.
