# UAT MRI Runtime Grounding Operational Fixback 독립 Review

- Review 시각: 2026-07-20 19:12:50 KST
- 후보 workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-fixback-20260720`
- 후보: `8b141c9049e3fb69d47e3b2e8804c991432c7dd8`
- 기준/보호 main: `1c6812007eb7d24feeb512b28afe078ab770adbb`
- handoff: `/Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-20-1903-uat-mri-operational-fixback-review-team-handoff.md`
- 검토 경계: read-only. 보호 main, 18080, 서비스, 운영 데이터, Graph/ontology/rule/user/chat data에는 쓰지 않았다.

## Findings

### 없음: 후보 diff에서 조치가 필요한 결함을 확인하지 못함

검토 대상 6개 파일의 실제 diff, 독립 fixture, focused/related/full Python, Node, 구문 및 임시 dist 재빌드를 확인했다. 명시 provenance 충돌은 fallback 없이 제외되고, 허용된 unique exact provenance와 동일 equivalence class만 복구되며, `status=missing` summary만 SPA 구조화 패널에서 숨겨진다. MRI/금액/세대/질문 문자열은 변경된 제품 코드 diff에 없었다.

### 환경 관찰: 후보 결함이 아닌 pytest 실행 환경 차이

기본 환경에서 후보 full pytest는 다음 권한 오류로 중단됐다.

```text
2 failed, 1154 passed, 3 warnings
PermissionError: [Errno 13] Permission denied: /tmp/insurance-rag-ontology-rebuild.lock
```

실패 지점은 `scripts/ontology_review.py:102`이고, 같은 코드의 `scripts/ontology_review.py:52`가 `INSURANCE_ONTOLOGY_REBUILD_LOCK` override를 제공한다. 후보 내부 코드/산출물 변경과 무관하게 임시 lock을 명시해 재실행한 full pytest는 `1160 passed, 3 warnings in 15.71s`였다.

별도로 `INSURANCE_SAFE_BASELINE_RUNTIME_ROOT=/srv/ai-ops/runtime/insurance-rag-chatbot/safe-baseline-v1.2.0-r2`를 둔 `test_resolve_default_ontology_manifest_prefers_env`를 후보와 보호 main에서 각각 실행했다. 양쪽 모두 `1 failed, 23 deselected`로 동일하게 `tests/test_ontology_registry.py:249`에서 runtime active manifest가 test-local `INSURANCE_ONTOLOGY_MANIFEST`보다 우선하는 기존 환경 계약을 재현했다. 이는 이번 후보의 provenance/SPA 변경에서 새로 발생한 실패가 아니다.

## 구현 경계 확인

- `src/retrieval/pair_mapping.py:115-166,177-186,212-240`: canonical/source/variant ID를 먼저 검사한다. 알려진 명시 ID와 선택 세대가 충돌하면 `_equivalent_canonical_match()`가 `None`을 반환하고 `has_explicit_match=True` 경로가 provenance fallback을 타지 않는다. ID가 없는 경우 exact provenance를 먼저 사용하고, 이후 안정 문서/페이지/구간 key로 제한한다. 복수 후보는 본문 hash, 안정 provenance, `product_type`/`is_own_company`, 세대가 하나의 equivalence class일 때만 deterministic representative를 선택한다. 세대 혼입·복수 class는 제외한다.
- `src/rag/pipeline.py:1690-1703,2257-2264`: hydration 후 직접 조항 속성 질의에만 선택 세대 필터를 적용한다. 일반 coverage/claim 질의와 세대 미선택 경로는 기존 필터 계약을 유지한다.
- `frontend/js/pages/chat.js:1480-1498`: raw `status`가 `missing`인 경로의 summary만 비렌더링한다. label/status, required evidence, exclusion/limit/other rule rows와 정상 summary는 유지한다.
- 변경된 제품 코드 diff에서 `MRI`, `MRA`, `300`, `200`, `4세대`, `5세대`, `연간`, `보상한도`, 질문 문구가 검색되지 않았다. 계산 rule, processing policy, ontology, Graph artifact 변경도 diff에 없었다.

## 독립 재현 및 테스트

### Provenance / generation 경계

후보에서 실행:

```text
pytest tests/test_pipeline.py -k "crosswalks_rechunked_source_metadata or equivalent_stable_provenance or generation_conflicts or conflicting_explicit_generation or unique_exact_provenance"
5 passed, 62 deselected in 0.21s
```

추가 임시 JSONL fixture에서 unique canonical은 `canonical-4`, 동일 본문/안정 key의 4th/5th 복수 후보는 mapping 없음, changed indexed body가 명시 ID 없이 stable key만 가질 때도 ambiguous fixture는 mapping 없음으로 재현했다. fixture는 `/tmp`에만 만들고 종료 시 정리했다.

### Python

- `tests/test_pipeline.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py`: `140 passed, 1 warning in 1.83s`
- 임시 `INSURANCE_ONTOLOGY_REBUILD_LOCK`와 `-p no:cacheprovider`를 사용한 전체 pytest: `1160 passed, 3 warnings in 15.71s`
- 기본 lock 환경 전체 pytest: `1154 passed, 2 failed, 3 warnings`; 위 환경 관찰과 동일한 `/tmp` lock permission 문제

### Node / frontend

- `node --test tests/test_frontend_assistant_display.mjs`: `6 passed`
- `node --test tests/test_frontend_assistant_display.mjs tests/test_frontend_source_preview_settings.mjs`: `12 passed`
- `node --test tests/*.mjs`: `48 passed`
- `node --check frontend/js/pages/chat.js`: passed
- 보호 checkout의 `frontend/node_modules`를 `NODE_PATH`로 read-only 참조하고 후보 source를 `/tmp`로 build했다. 후보와 재생성 결과가 모두 byte-for-byte 일치했다.
  - `frontend/dist/app.min.js`: `f8637b8958bf5b75be9442b8a362624a056fff34e1fb834b93cc2f7424ffbdec`
  - rebuilt app: 동일 hash, `app_dist_match=YES`
  - `frontend/dist/graph-viz.min.js`: `ad17e2fc878320c85c4c9f6f3ca0edf8fce5713ab25b988db47b7616ea7dd80e`
  - rebuilt graph: 동일 hash, `graph_dist_match=YES`

## 불변성 및 해시

- 후보 `git status --short`: clean; candidate head는 `8b141c9...`, parent는 `1c68120...`.
- `git diff --check 1c6812007eb7d24feeb512b28afe078ab770adbb`: passed.
- 실제 diff는 다음 6개 파일뿐이다: `docs/286_UAT_MRI_RUNTIME_GROUNDING_OPERATIONAL_FIXBACK_REPORT.md`, `frontend/dist/app.min.js`, `frontend/js/pages/chat.js`, `src/retrieval/pair_mapping.py`, `tests/test_frontend_assistant_display.mjs`, `tests/test_pipeline.py`.
- frozen hash 재확인:
  - `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
  - `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
  - `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
  - r2 `insurance_graph.sqlite`: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`
- 보호 main HEAD는 expected `1c6812007eb7d24feeb512b28afe078ab770adbb`와 동일하다. 보호 checkout은 review 전부터 존재한 것으로 판단되는 untracked `.claude/`, `insurance_chat.db-wal`(0 bytes, 18:33:32), `insurance_chat.db-shm`(32768 bytes, 18:34:45)가 있고 `ops/` 일부 permission warning이 있어 porcelain상 clean하지 않다. 이 파일들을 삭제·변경하지 않았고 보호 18080에는 접근하지 않았다.
- 후보에는 review 실행 후 sidecar/untracked 산출물이 없으며, 임시 build/lock/fixture는 `/tmp`에만 생성하고 종료 시 정리했다.

## Verdict

`PASS`

이 PASS는 정확히 검토한 candidate diff에 대한 판정이다. 보호 main 통합, API-only 배포, runtime promotion은 별도 승인 게이트로 남기며, 운영 r2 환경에서 재현된 ontology manifest precedence 테스트 실패는 배포 전 환경 계약을 별도로 정리해야 한다. 이번 review에서는 integration, push, service restart, active promotion, Graph/ontology rebuild를 수행하지 않았다.

REVIEW_TEAM_UAT_MRI_OPERATIONAL_FIXBACK_VERDICT_COMPLETE_NO_INTEGRATION_NO_PUSH
