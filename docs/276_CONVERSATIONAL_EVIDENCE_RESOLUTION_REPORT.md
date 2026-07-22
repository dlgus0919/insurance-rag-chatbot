# 대화형 근거 확인 및 안전 기준선 구현 보고서

- 작성일: 2026-07-19
- 범위: Release B - 대화형 근거 확인 및 안전 기준선
- 격리 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 작업 원칙: 보호 메인, 운영 active manifest, GraphDB, 검색 인덱스, 운영 대화 DB, 계정, 로그, 서비스는 변경하지 않음

## 결론

승인되지 않은 온톨로지 delta가 있는 raw/base를 운영 지식으로 사용하지 않고, 검증된 49개 concept만으로 만든 임시 safe baseline에서 대화형 근거 확인 경로를 검증했다. 사용자의 후속 진술은 세션 안의 확인 상태로만 보존하며, 온톨로지, GraphDB, 승인 지식으로 자동 승격하지 않는다.

원본 `concepts.json`의 기본 동기화 검사는 현재도 `quarantined`로 실패한다. 이는 배포 전 raw/base 상태를 정상으로 오인하지 않도록 하는 의도된 차단이며, 이번 구현에서 통과시키지 않았다. 별도 통제 절차로 safe baseline을 active/provenance와 GraphDB에 원자 적용하기 전까지 운영 반영은 금지된다.

## 구현 내용

### 1. 안전 기준선과 pending 교정 근거

- `src/ontology/safe_baseline.py`와 `scripts/prepare_ontology_safe_baseline.py`가 base lock에 맞는 concept만 projection으로 만든다.
- raw 55개 중 trusted 49개는 유지하고, provenance가 불충분한 6개는 runtime에서 사용하지 않는 pending correction artifact로 보존한다.
- correction artifact는 `status: pending`이며 승인, active apply, GraphDB rebuild, 인덱스 갱신을 수행하지 않는다.
- 임시 projection 검증 결과는 다음과 같다.

| 항목 | 결과 |
| --- | --- |
| trusted concept 수 | 49 |
| pending correction 수 | 6 |
| projection hash | `ccfbf4faa15bbd34993e1f09aa7fe90fb72f519de2cf955f0bbfa80b290fe3b2` |
| 임시 provenance hash | `a93d449...` |
| 임시 GraphDB | 2,540 nodes, 10,128 edges, integrity error 0건 |

임시 versioned active/provenance와 임시 GraphDB에서 hash/integrity 검증은 통과했다. 이 산출물은 모두 임시 경로에서만 생성했고 운영 active manifest 또는 운영 GraphDB로 승격하지 않았다.

### 2. 일반화된 대화형 근거 확인

- `src/rag/conversation_context.py`는 확인이 필요한 선택지를 schema v1 상태로 정규화해 세션 metadata에만 저장한다.
- `src/rag/evidence_assessment.py`는 승인된 구조화 근거의 결론, 적용 조건, 추가 확인 항목을 canonical payload로 만든다.
- `src/api/routes/chat.py`는 같은 `turn_id` 재시도에서 저장된 결과를 재생하고, 저장 실패 시 `done`을 전송하지 않는다.
- 후속 선택은 같은 `session_id`와 새 `turn_id`로 전달된다. 첫 응답의 세션 ID를 응답 row에 보존하므로 세션 목록 갱신 타이밍과 무관하게 같은 스레드로 이어진다.
- 공개 SSE graph payload에서는 내부 근거 chunk 식별자를 제거했다. 사용자의 자유 텍스트 확인 진술은 세션 assertion으로만 남고 ontology/Graph 승인 지식으로 승격되지 않는다.

### 3. 기존 API 계약 보존

- 기존 공개 함수 `apply_policy_clause_decision`과 `_merge_unique_text` 의존성을 호환 래퍼로 복구했다.
- 이 래퍼는 기존의 Graph payload deepcopy, plan의 clarification/required evidence 병합, canonical decision 설정, `claim_condition_review` 제거 계약을 유지한다.
- 새 evidence engine은 별도 경로로 계속 사용하므로 기존 호출자 호환을 위해 새 경로를 역전시키지 않는다.
- `conversation_context`가 없을 때는 기존 GraphRetriever 호출 시그니처를 그대로 사용하고, 실제 clarification이 있을 때만 새 선택 인자를 전달한다.

## 3건 전체 pytest 실패 분석

처음 전체 pytest는 `INSURANCE_RAG_ISOLATED_E2E=1`이 설정된 비교 환경에서 `1087 passed, 3 failed`였다.

| 테스트 | 최초 원인 | 조치 | 최종 판정 |
| --- | --- | --- | --- |
| `test_prepare_retrieved_context_hides_missing_graph_chunk_warning` | context가 없는데 `clarification=None` 키워드를 기존 fake GraphRetriever에 전달 | clarification이 실제 존재할 때만 새 호출 형식을 사용 | 이번 Release B 회귀, 수정됨 |
| `test_chat_stream_runs_recalculation_when_category_and_target_are_clear` | isolated E2E flag가 pipeline 생성을 의도적으로 생략해 `captured["pipeline"]`이 없음 | 제품 코드 변경 없음 | 기준 커밋에서도 동일 실패 |
| `test_claim_calculation_route_uses_fixed_rag_top_k` | 같은 isolated E2E flag로 `captured["top_k"]`이 없음 | 제품 코드 변경 없음 | 기준 커밋에서도 동일 실패 |

동일 환경에서 현재 격리본과 기준 커밋 `b1c0b658`를 각각 재현한 결과는 둘 다 `1 passed, 2 failed`였다. 두 기준선 실패는 일반 전체 pytest 환경에 `INSURANCE_RAG_ISOLATED_E2E=1`을 주입했을 때 발생하는 기존 테스트 환경 충돌이다. 운영 코드 변경으로 숨기지 않았고, 최종 전체 pytest는 임시 DB/사용자/로그 경로만 유지하되 해당 E2E 전용 플래그 없이 실행했다.

## 검증 결과

모든 Python 검증은 임시 대화 DB, 사용자 파일, 로그 경로를 사용했고 종료 후 제거했다. 표준코드 DB는 기존 파일을 읽기 전용으로 참조했다.

| 검증 | 결과 |
| --- | --- |
| `test_prepare_retrieved_context_hides_missing_graph_chunk_warning` + `test_api_rag_service_payload.py` | `27 passed, 1 warning` |
| safe baseline, conversation, evidence, chat, 수술종수, HIRA, MX122, 계산, 세션, 관리자 Graph focused suite | `214 passed, 1 warning` |
| 전체 pytest (임시 DB/사용자/로그, E2E 전용 flag 미주입) | `1090 passed, 3 warnings` |
| Node 프런트엔드/관리자 회귀 | `18 passed` |
| `npm --prefix frontend run build` 및 `node --check frontend/dist/app.min.js` | 통과 |
| isolated Playwright (`chat.spec.js`, `isolated-claim-flow.spec.js`) | `13 passed` |
| `git diff --check` | 통과 |

격리 Playwright는 loopback `127.0.0.1:18767`, 임시 DB, 임시 사용자, 임시 JWT secret 및 읽기 전용 표준코드 DB만 사용했다. 보호 `18080`에는 GET/HEAD를 포함한 접근도 하지 않았고, 운영 계정·대화·표준코드 DB에 쓰지 않았다. 브라우저 테스트가 확인한 흐름은 후보 선택/확인 선택이 같은 세션의 두 번째 payload로 전달되는 계약이다. 실제 API의 세션 저장과 복원은 `tests/test_api_chat_stream.py`의 직접 handler 회귀로 별도 검증했다.

## 배포 전 raw/base 차단과 임시 기준선 검증

다음 명령은 raw/base를 변경하지 않고 임시 projection을 만들었다.

```bash
python scripts/prepare_ontology_safe_baseline.py \
  --raw-base data/ontology/concepts.json \
  --base-lock data/ontology/policies/base_manifest.lock.json \
  --output-base <temporary>/concepts.safe.json \
  --pending-artifact <temporary>/pending-correction.json
python scripts/check_ontology_sync.py --manifest <temporary>/concepts.safe.json
```

결과는 `state: valid`, `trusted_concept_count: 49`, `pending_correction_count: 6`, ontology sync 통과였다.

반대로 기본 raw/base 검사인 아래 명령은 의도대로 non-zero로 종료했다.

```bash
python scripts/check_ontology_sync.py
```

결과: `ontology integrity state is quarantined` (exit code 1). 이 실패는 이번 구현으로 완화하거나 우회하지 않았다.

## 변경 파일

- `src/ontology/safe_baseline.py`
- `scripts/prepare_ontology_safe_baseline.py`
- `src/rag/conversation_context.py`
- `src/rag/evidence_assessment.py`
- `src/api/rag_service.py`
- `src/api/routes/chat.py`
- `src/api/schemas/chat.py`
- `src/rag/pipeline.py`
- `src/rag/source_grounded_answers.py`
- `src/graph/retriever.py`
- `src/ontology/registry.py`
- `frontend/js/pages/chat.js`
- `frontend/dist/app.min.js`
- `playwright.isolated.config.js`
- 관련 Python, Node, Playwright 회귀 테스트와 pending correction artifact

## 운영 경계와 남은 위험

- 보호 메인 checkout, 운영 active ontology/provenance, active rule, GraphDB, BM25/Chroma index, 운영 DB/계정/대화/로그, API/LLM 서비스는 변경하지 않았다.
- candidate apply, practitioner 승인, GraphDB rebuild, reindex, deploy, stage, commit, push를 수행하지 않았다.
- raw/base가 quarantined인 상태는 운영 반영 전 차단 상태다. 다음 단계에서는 Review Team이 safe baseline의 원자 적용, pending correction artifact의 실무자 승인 범위, 임시 GraphDB hash/integrity 결과를 심사해야 한다.
- 이번 격리 E2E는 write opt-in이 있는 임시 환경에서만 실행됐다. 보호 앱의 실제 사용자 흐름은 별도 배포 승인과 read-only/controlled smoke 절차를 거쳐야 한다.

## Self-inspection

- 특정 질환, 질문 문구, concept ID를 production runtime 분기로 추가하지 않았다.
- 새로운 insurance knowledge를 자동 승인하거나 active data에 적용하지 않았다.
- E2E 임시 server, port, node_modules symlink, pytest root는 종료 후 정리했다.
- 이 보고서는 격리 작업공간의 미커밋 구현과 검증 결과만 기록한다.
