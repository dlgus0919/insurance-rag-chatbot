# Chrome UAT MRI P0 Fixback 독립 재검토

## 범위

- handoff: `docs/reviews/2026-07-20-2248-chrome-uat-mri-p0-fixback-review-team-handoff.md`
- base: `48a6cf7a942a627c4b70cd6ee50997ec6d97b8e5`
- candidate: `dc83002fe4c3b3da6f475a7ac4cd68c2885dac98`
- candidate workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-chrome-uat-mri-p0-fixback-20260720`
- protected checkout: `/srv/shared/projects/insurance-rag-chatbot`
- 검토는 read-only로 수행했으며 protected checkout, API, GraphDB, ontology, active rule, DB, 서비스, LLM에는 쓰기를 수행하지 않았다.

## Findings

발견된 재현 가능한 결함 없음.

## 독립 확인

### 라우팅과 의도 경계

`src/rag/query_router.py:116-132`의 변경은 이미 분류된 `policy_attribute_lookup`에만 기존 general direct-retrieval 경로를 선택하게 한다. MRI, 금액, 문서, chunk ID 예외는 없다.

독립 실행 결과:

| 질의 유형 | 분류/경로 |
| --- | --- |
| `4세대 ... 연간 보상한도는?` | `policy_attribute_lookup` / `general` / `policy_attribute_direct_lookup` |
| `5세대 ... 연간 보상한도는?` | `policy_attribute_lookup` / `general` / `policy_attribute_direct_lookup` |
| `4세대와 5세대 ... 한도 비교` | `cross_doc_compare` / 기존 general 경로 |
| `5세대 MRI 연간 보장되나요?` | `ambiguous_medical_term`, `requires_coverage_judgment=True`, pure attribute 아님 |
| `5세대 MRI 보상한도 지급 여부는?` | `ambiguous_medical_term`, `requires_coverage_judgment=True`, pure attribute 아님 |
| `MRI 보험금 계산해줘` | `ambiguous_medical_term`, `requires_coverage_judgment=True`, pure attribute 아님 |
| `통원 치료비 청구 가능한가요?` | `coverage_judgment`, pure attribute 아님 |

UI가 만드는 payload는 `frontend/js/pages/chat.js:820-864`에서 `mode`, `policy_generation`, `index_mode`, `turn_id`를 `/chat/stream`에 전달한다. API는 `src/api/routes/chat.py:682-743`에서 route를 해석한 뒤 선택 세대와 대화 context를 direct retrieval에 전달한다.

### 실제 후보 source 선택

후보 `data/processed/chunks.jsonl`을 직접 읽어 `_direct_policy_attribute_hits()`를 호출했다.

- 4세대: `약관_ch_002441`, `policy_generation=4th`, `direct_policy_attribute=True`, `300만원`, display evidence 108자
- 5세대: `표준약관_ch_005435`, `policy_generation=5th`, `direct_policy_attribute=True`, `200만원`, display evidence 50자
- 비교 질의: 위 4세대와 5세대 후보를 모두 반환

후보 API 회귀 테스트에는 각 세대를 두 번 처리하는 UI-like `ChatRequest`가 포함되어 있으며, 선택 세대, `v2_only`, direct source, `resolved_route=general`, `resolved_intent=policy_attribute_lookup`, audit source count를 검증한다.

### 공개 응답과 source UI

- `src/api/public_payloads.py:58-84`는 assistant metadata 및 내부 marker를 public source에서 제거하고 표시용 filename/page/score/snippet/status만 반환한다.
- `src/api/public_payloads.py:265-298`은 Graph payload를 allowlist projection한다.
- `src/api/rag_service.py:983-1161`의 기존 answer normalization 경로는 embedded review template 및 trailing source citation을 정리한다.
- `src/api/rag_service.py:196-231`의 source snippet 상한은 180자다.
- `frontend/js/pages/chat.js:1609-1642`는 hover preview를 유지하면서 PDF만 encoded URL, `#page`, `target="_blank"`, `rel="noopener noreferrer"`로 클릭 가능하게 한다. 비PDF와 page 없는 source는 non-clickable이다.

### 검증 명령

- `pytest -p no:cacheprovider tests/test_query_router.py tests/test_search_intent.py tests/test_api_chat_stream.py -q` → `71 passed, 1 warning`
- `PYTHONDONTWRITEBYTECODE=1 INSURANCE_ONTOLOGY_REBUILD_LOCK=/tmp/review-chrome-uat-mri.lock ... pytest -p no:cacheprovider -q` → `1177 passed, 3 warnings`
- `node --test tests/*.mjs` → `50 passed`
- `node --check frontend/js/pages/chat.js` → pass
- candidate source를 `/tmp`에 bundle한 뒤 candidate `frontend/dist`와 `cmp` → `app_dist_match=YES`, `graph_dist_match=YES`
- `git diff --check 48a6cf7... dc83002...` → pass
- candidate diff path → 지정된 5개 파일만

계산·처리 정책 파일의 독립 SHA-256은 candidate에서 다음과 같았다.

- `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
- `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
- `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`

candidate worktree는 clean이었다. protected HEAD는 `48a6cf7a942a627c4b70cd6ee50997ec6d97b8e5`로 유지되었다. protected status에 보인 기존 `insurance_chat.db-wal`/`insurance_chat.db-shm`은 변경하지 않았다.

## 잔여 위험

byte-copy actual-v2 smoke에서 raw hit 일부의 mixed/empty `policy_generation` metadata가 관찰되었다. 그러나 selected-generation direct lookup의 최종 source와 응답은 위 독립 재현에서 정확했다. 이 raw metadata 정규화는 이번 P0 라우팅 fixback의 범위를 벗어나며, 최종 승격 전 실제 통합 환경의 Chrome UAT에서 최종 SSE bubble과 PDF click을 한 번 더 확인해야 한다.

## Verdict

`PASS`

별도 protected-main promotion gate와 서비스 재기동 이후 Chrome UAT를 진행할 수 있다. 이번 리뷰에서는 integration, restart, push, 운영 데이터 변경을 수행하지 않았다.

REVIEW_TEAM_CHROME_UAT_MRI_P0_FIXBACK_PASS_OR_CHANGES_REQUESTED
