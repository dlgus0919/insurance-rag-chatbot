# 272. 채팅 스레드 연속성 및 도메인 조회 안정화 릴리스 보고서

## 1. 릴리스 범위와 경계

기준 커밋 `0ad60f1`에서 시작한 채팅 스레드·수술종수·보험금 계산 안정화 작업을 소스 커밋 `ac42d9f`로 릴리스했다. 보호 메인 저장소와 운영 앱에는 검증을 통과한 변경만 반영했으며, Qwen/SGLang 서버와 모델 파일은 중지·교체·재기동하지 않았다.

이번 릴리스는 다음만 포함한다.

- 일반 질의와 보험금 계산의 단일 스레드 저장, 이전 스레드 복원, 세션 전환 경쟁 차단, 저장 뒤 SSE `done` 전송
- 직전 계산 스냅샷을 이용한 일반 질의·재계산 문맥 연결
- 수술종수 의도 정규화와 근거 기반 수술명 resolver
- 비급여 도수치료의 표준코드 선택 및 승인 룰 기반 계산
- 승인된 계산 룰 두 건의 active manifest·GraphDB 반영

원본 약관, 운영 대화, 실제 사용자 계정, 다른 pending 후보는 변경하지 않았다.

## 2. 채팅·수술종수·계산 구현 결과

### 2.1 채팅 스레드 연속성

- 이전 채팅을 최신 활동 기준으로 안정적으로 복원한다.
- 일반 질의와 보험금 계산을 하나의 타임라인에 저장한다.
- 세션이 전환되면 이전 요청의 늦은 응답을 무효화해 다른 스레드에 섞이지 않게 한다.
- 계산 스냅샷 v1/v2를 모두 읽고, 후속 일반 질의에서 직전 계산을 구조화된 맥락으로 참조한다.
- assistant 응답 저장이 끝난 뒤에만 SSE `done`을 전송한다.

### 2.2 수술종수 조회

- `1~5종`, `1-5종`, 붙여 쓴 `몇종`을 같은 수술종수 의도로 정규화한다.
- 정확 수술명, 승인 별칭/GraphDB 확정 근거, 후보 확인 순으로 해석한다.
- 명시적 수가 의도가 없는 수술종수 질의에는 HIRA 수가표를 추가하지 않으며, 수술명 접미사 `술`을 음주 표현으로 오인하지 않는다.

| 질의 | 최종 동작 | 근거 |
| --- | --- | --- |
| 결장폴립절제술 1-5종 | 4종 | 실무가이드 p.110 |
| 결장경하 폴립절제술 1-5종 | 2종 | 실무가이드 p.167 |
| 대장용종절제술 1-5종 | 확정하지 않고 개복/내시경 여부 확인 요청 | 서로 다른 확정 근거가 존재 |

`Q7701`처럼 승인된 코드-수술 연결이 없는 입력은 후보 확인 상태로 유지한다.

### 2.3 4세대 비급여 도수치료

- 급여/비급여 금액 범위를 표준코드 매칭에 전달한다.
- 비급여 도수치료는 `MX122`를 우선하고, 명시 입력 코드는 그 입력을 우선한다.
- 코드가 모호하면 0원 지급으로 확정하지 않고 `needs_code_selection`/산정 보류로 남긴다.
- 4세대 도수치료군은 일반 비급여 건당 25만원 fallback을 쓰지 않고, 승인된 `3대비급여_도수` 룰만 쓴다.

## 3. 승인·적용한 계산 룰

dry-run에서 다음 두 후보만 선택됨을 확인하고 백업 후 적용했다. 기존 일반 비급여 pending 후보를 포함한 다른 후보는 승격하지 않았다.

| 후보 ID | 방문 유형 | active rule | 상태 |
| --- | --- | --- | --- |
| `rulecand.add.deductible.4th.three_major_manual.hospitalization` | 입원 | `deductible.4th.three_major_manual.hospitalization` | candidate `applied`, rule `active` |
| `rulecand.add.deductible.4th.three_major_manual.outpatient` | 통원 | `deductible.4th.three_major_manual.outpatient` | candidate `applied`, rule `active` |

두 룰은 공제율 30%, 최소공제 30,000원, 연 3,500,000원·50회, 최초 10회 이후 호전 증빙 검토 조건을 active manifest에 반영한다. 누적 청구 이력·증빙이 없으면 예상 지급액은 계산하되 검토 필요 상태를 유지한다.

- `claim_deductible_rules.active.json` SHA-256: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
- `rule_links.active.json` SHA-256: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
- active rule link: 정확히 2건

## 4. GraphDB 반영과 무결성

active rule links를 사용해 `v1_v2_combined` GraphDB를 재빌드했다. 데이터와 근거는 읽기 전용으로 사용했다.

| 항목 | 결과 |
| --- | ---: |
| Graph nodes | 545,238 |
| Graph edges | 46,269 |
| Evidence | 27,020 |
| Aliases | 528,225 |
| 신규 active rule nodes | 2 |
| 신규 rule edges | 14 (근거 10, 주제 4) |
| Graph integrity | PASS |

Graph-vector 동기화는 24,617건 중 24,612건을 직접 연결했다. 누락 5건은 `rule_link_manifest`가 traceability 용도로 만든 synthetic `rule_source` 근거이며, Chroma 원문 청크가 없는 의도된 예외다. 실제 원문 콘텐츠는 24,612/24,612건 직접 연결됐다.

## 5. 검증 결과

| 검증 | 결과 |
| --- | --- |
| Task 11 combined focused pytest | 266 passed, 1 warning |
| 전체 pytest (보호 메인) | 955 passed, 3 warnings |
| Node 단위 테스트 | 7 passed |
| `node --check frontend/js/pages/chat.js` | 통과 |
| `npm --prefix frontend run build` | 통과 |
| Playwright 격리 E2E | 10 passed |
| `git diff --check` | 통과 |
| Graph rule-link tests | 6 passed |

Node의 ES module 재파싱 경고와 Python의 외부 라이브러리 deprecation 경고만 남았으며 실패는 없다. 보호 메인에서의 Playwright는 운영 DB 변경을 피하기 위해 실행하지 않았고, 동일 소스의 격리 DB·테스트 계정 환경에서 실행했다. 격리 E2E의 인덱스 prewarm 경고는 worktree에 BM25 파일이 없는 환경 제한이며 테스트 mock과 릴리스 동작에는 영향을 주지 않았다.

## 6. 운영 앱 smoke

앱만 교체 기동했고 LLM 서버는 유지했다. live 모델 API에는 `sglang:qwen3-next-80b-a3b-instruct-fp8` 한 개만 노출됐다.

격리 DB·테스트 계정으로 실행한 smoke 결과:

- health 정상, 실행 모델 목록 정상
- 동일 스레드에 보험금 계산, 계산 후 후속 일반 질의, 일반 Qwen 질의, 수술종수 세 질의를 저장해 메시지 12건 확인
- 4세대 통원 비급여 도수치료 `MX122`, 500,000원: 공제 150,000원, 예상 지급 350,000원, 검토 필요 유지
- “보상하지 않는다면” 후속 질의에서 이전 350,000원과 0원 시나리오를 함께 확인
- 세 수술종수 질의는 2.2의 계약대로 응답

초기 임시 smoke wrapper가 격리 환경 변수를 전달하지 않아 운영 DB에 테스트 사용자 ID의 `LOGIN_FAILED` 감사 이벤트 2건을 남겼다. 계정, 대화, 계산, 룰, 인덱스 데이터는 변경되지 않았으며 감사 기록 보존 원칙에 따라 해당 두 항목은 삭제하지 않았다. 이후 직접 환경 변수를 전달한 격리 앱에서 모든 smoke를 재실행해 통과했다.

## 7. 롤백과 정리

- 소스 롤백은 이전 main 커밋으로 되돌린 뒤, active rule manifest와 active link manifest를 해당 커밋 상태로 복원하고 GraphDB를 재빌드하는 순서로 수행한다.
- 운영 LLM 서버는 이 작업 중 중지하지 않았다.
- 검증 후 제거한 경로: 격리 chat-procedure worktree, 두 rule-review backup 디렉터리, 임시 smoke 서버 디렉터리, 임시 port 18081 서버, 임시 FastAPI 로그 1개.
- 보호 메인에서 운영 SQLite의 WAL/SHM 파일은 실행 중인 앱 런타임 산출물이므로 커밋·삭제하지 않았다.

## 8. 000번 규칙 자체 점검과 남은 위험

- 새 보험 지급 수치와 조건은 코드 상수가 아니라 승인된 active rule manifest와 그 근거 link에서 읽는다.
- 수술종수는 실제 표 근거와 승인된 alias/GraphDB 관계를 사용하며, 의학 동의어를 임의 하드코딩하지 않는다.
- 나머지 pending 룰 후보는 여전히 실무자 승인 전이며 active manifest에 적용하지 않았다.
- synthetic rule-source 5건은 retrieval vector가 없는 traceability-only 노드라는 점을 Graph 진단에서 계속 구분해야 한다.
- 운영 DB의 실패 로그인 감사 이벤트 2건은 삭제하지 않았으므로 이후 운영 감사 시 테스트 흔적으로 인지해야 한다.
