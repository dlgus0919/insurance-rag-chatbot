# v1.2.0 일반 질의 온톨로지 후보 재구축 구현 보고서

## 상태

- 상태: Review Team 검토 대기 후보
- 범위: DGX 격리 작업공간과 candidate release만 변경
- 운영 반영: 미수행
- 커밋, 태그, push: 미수행

이 보고서는 실무자 판정에 따라 준비한 v1.2.0 후보와 fixback 결과를 설명한다. 운영 active ontology, 운영 GraphDB, 색인, 앱 서비스, LLM 서버, 운영 계정과 대화 데이터는 변경하지 않았다.

## 실무자 판정 반영

기존 신뢰 기준선 49개에 일반 질의용 승인 6개를 추가하여 후보 manifest는 55개 concept로 구성했다. 신규 6개에는 지급 금액, 공제율, 지급 결론, 계산 hook 또는 runtime decision profile을 넣지 않았다.

| 승인 concept | 승인된 active alias |
| --- | --- |
| 청구 서류 요건 | 보험금 청구 서류, 청구 구비서류, 추가 청구서류 |
| 지급 기한 | 보험금 지급기일, 보험금 지급 지연 사유, 지급예정일 |
| 한방 치료 문맥 | 한방 치료, 한의원 진료, 한방 의료기관 |
| 치과 치료 분류 | 치과 치료, 치과 질환, 치아 질환 |
| 해외 의료기관 | 해외 의료기관, 해외 진료, 외국 의료기관 |
| 무청구 이력 할인 | 무사고 할인, 무청구 할인 |

승인된 active alias는 정확히 **17개**다. 마지막 concept에는 `비급여 보험료 차등제`를 추가하지 않았고 aliases, candidate aliases, retrieval, Graph alias 모두에서 부재함을 검증했다. `K00-K08`은 근거 metadata일 뿐 alias로 승격하지 않았다.

거절된 source authority 후보 1개, 기존 held 후보 3개, provenance가 부족한 탈모 관련 6개는 후보 runtime projection과 Graph seed에서 제외했다. 이 10개는 감사 artifact에는 남아 있으나 검색 alias나 결정 payload로 복원되지 않는다.

## 구현 변경

- `data/ontology/concepts.json`: 실무자 승인 6개를 canonical alias와 planner/retrieval metadata로 반영하고, 거절 대상 10개를 제외했다.
- `data/ontology/policies/base_manifest.lock.json`: 후보 manifest의 canonical hash로 갱신했다.
- `data/ontology/ontology_manifest.schema.json`, `src/ontology/registry.py`: planner의 구조화 context, clarification field, evidence category를 schema와 registry loader가 보존하게 했다.
- `scripts/prepare_ontology_safe_baseline.py`: ontology concept manifest와 Graph build용 canonical document JSONL을 분리하고, EOF까지 모든 nonblank JSONL 행을 JSON object로 검증한다. 명시한 optional overlay가 없으면 build 전 fail-closed하며, 생략하면 source descriptor에 `absent` 상태를 기록한다.
- `src/ontology/safe_baseline.py`, `src/graph/store.py`, `src/graph/visualization.py`: candidate Graph의 stable source descriptor와 SHA-256을 외부/내부 manifest에 동일하게 기록하고, `mode=ro&immutable=1` 검증, WAL checkpoint 및 sidecar 부재 검증을 수행한다. 후보 root 전체의 디렉터리는 `2750`, 파일은 `640`으로 정규화한다.
- `scripts/build_graph_visualization_snapshot.py`: candidate snapshot도 immutable read로 생성한다.
- `frontend/package-lock.json`: top-level 및 root package version만 `1.2.0`으로 맞췄으며 dependency graph, resolved URL, integrity 값은 바꾸지 않았다.
- `tests/test_prepare_ontology_safe_baseline_cli.py`, `tests/test_safe_baseline.py`: trailing malformed/non-object JSONL, source descriptor mismatch, optional overlay 부재, immutable SQLite, sidecar, 내부/외부 manifest 동등성, candidate root의 monitor/log/exit 파일까지 포함한 권한 정규화를 회귀로 고정했다.
- `tests/test_v120_ontology_practitioner_decisions.py`: 승인 6개, 정확한 17개 alias, 금지 표현 및 거절 10개 부재, frozen calculation-rule hash, 후보 Graph alias seed를 검증한다.
- `tests/test_ontology_registry.py`: 기존 `OntologyConcept` 위치 인자 생성 계약을 고정했다. 새 planner 필드 3개는 기존 모든 필드 뒤에 기본값으로 추가했다.
- `tests/test_graph_query_planner.py`: 기존 source-grounded planner assertion은 약화하지 않고 test-local forensic fixture로 분리했다. 이 fixture는 runtime fallback이 아니다.
- `docs/review_artifacts/2026-07-19-v1.2.0-practitioner-decision-audit.json`: 실무자 판정, 승인 field path, 거절 감사 기록을 후보 전용으로 보존한다.

## 이전 시도와 fixback

1. attempt1은 ontology concepts JSON을 Graph builder의 canonical document JSONL 자리에 전달해 JSON decode 오류로 종료했다. 최대 RSS는 102,824 KiB였고, 자원 부족이나 운영 영향은 없었다.
2. attempt2는 Graph build 자체에는 성공했지만 승인 표현이 `candidate_aliases`에 남아 canonical name만 Graph alias로 seed되는 결함이 발견됐다.
3. attempt3은 승인 표현을 active alias로 승격해 Graph를 재구축했으나, build evidence root의 group-write 권한, ephemeral `/tmp` source path, optional overlay의 missing-path 기록, SQLite sidecar 허용 문제가 남아 release gate를 통과하지 못했다.
4. attempt4는 attempt3을 덮어쓰지 않는 별도 candidate root에서 위 문제를 보정해 재구축한 최종 검토 후보다.

## 최종 manifest key-set fixback

Review Team은 외부 Graph manifest에 있는 키만 순회하던 검증 때문에, SQLite 내부 `graph_build_manifest`에만 추가된 키가 값 불일치 없이 통과할 수 있음을 확인했다. `_graph_artifact_errors()`는 이제 외부에 없는 내부 키와 내부에 없는 외부 키를 모두 정렬된 순서로 비교해 fail-closed한다.

회귀 테스트는 sidecar 없이 checkpoint한 SQLite 내부 manifest에 `unexpected_internal_key`를 추가하고, 외부 manifest는 그대로 둔다. 이 경우 `verify_safe_baseline_release`와 operator-gated `publish_safe_baseline_release`가 모두 거부하며, publish 실패 뒤 기존 runtime artifact 바이트가 변하지 않음을 확인한다. 이 수정은 attempt4 후보 산출물, 실무자 판정, ontology/Graph hash, 승인 alias, 계산 룰에 변경을 가하지 않는다.

## attempt4 후보 Graph

candidate release root는 `/srv/shared/workspaces/muldae/ontology-v1.2.0-candidate-release-20260719-attempt4`이며, release id는 `v1.2.0-general-ontology`다.

- prepare exit: 0, time exit: 0
- 경과 시간: 53.93초
- 최대 RSS: 681,656 KiB
- swap 위험선 진입: 0회
- ontology content hash: `ffad858ea1339bf5196a5445395aed5003a6344990f7ae32c0ef3a039e33861b`
- ontology provenance content hash: `bf6e6df6d458f1f896103b428c3b302d71ca658c24d046f5d4dccc24aa2fecf7`
- Graph DB SHA-256: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`
- Graph metadata: nodes 545,238, edges 46,269, aliases 528,227, evidence 27,020
- visualization snapshot: schema 1, 150 nodes, 33 edges, SHA-256 `54da38a3ca53eff4bdd90a6be4d3e94ef0dbc4a3a0839dbd0605d29d4cdee9c2`

canonical document source는 `/srv/shared/projects/insurance-rag-chatbot/data/processed/chunks_canonical_manifest.jsonl`이며 SHA-256은 `88aedbb1e80b168fe99eadeb4107dd1cf7746fcffccc09e1834b0ff089cb6ef1`이다. candidate Graph의 외부 manifest와 SQLite 내부 manifest는 동일한 stable source descriptor와 문자열 값을 가지며, optional active overlay는 인자를 생략해 `state=absent`로 기록했다. 검증 시 source 존재성과 SHA-256이 달라지면 fail-closed한다.

safe-baseline verify의 trusted concept count는 55다. SQLite는 `mode=ro&immutable=1`로 재검증했으며 integrity check는 `ok`, foreign-key violation은 0건, `-wal` 및 `-shm` sidecar는 0건이다. 승인 6개 node와 17개 alias가 모두 있고, 거절 10개와 금지 표현은 Graph 및 registry seed에 없다.

candidate root 전체에는 monitor, stdout/stderr, exit code, Graph, ontology, snapshot을 포함해 디렉터리 `2750`, 파일 `640`을 적용했다. `find <attempt4-root> -perm /022 -print`는 0건이다.

## 검증 결과

| 검증 | 결과 |
| --- | --- |
| safe-baseline / CLI / registry / Graph / API / 계산 focused | 158 passed, warning 1건 |
| manifest key-set 회귀 | 수정 전 1 failed, 수정 후 1 passed |
| attempt4 fixback focused | 34 passed |
| 전체 pytest (별도 lock 및 임시 SQLite) | 1,130 passed, warning 3건, 14.99초 |
| Node 단위 테스트 | 45 passed |
| `node --check frontend/js/pages/chat.js` | 통과 |
| frontend production build | 통과. 보호 main의 기존 `node_modules`를 읽기 전용 임시 symlink로 사용 후 제거 |
| ontology sync | 통과: concepts 55, aliases 126, candidate aliases 18, retrieval rules 10 |
| safe baseline candidate verify | 통과: trusted concept count 55 |
| candidate Graph immutable verify | 통과: internal/external manifest key 17개가 동일, 값 불일치 0, integrity `ok`, FK 0, sidecar 0 |
| `git diff --check` | 통과 |

`candidate aliases 18`은 후보 검토용 표현 수이며, 실무자가 승인하여 active alias로 승격한 표현 수와 다르다. 승인 active alias 수는 위 표와 같이 정확히 17개다.

## 동결 경계

다음 active calculation boundary 파일은 시작과 종료 시 같은 SHA-256을 유지했다.

| 파일 | SHA-256 |
| --- | --- |
| `data/rules/claim_deductible_rules.active.json` | `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818` |
| `data/rules/rule_links.active.json` | `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9` |
| `src/claim_calculation/processing_policy.py` | `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f` |

보호 main은 변경하지 않았고 clean 상태를 유지했다. 운영 active manifest, 운영 GraphDB, BM25/Chroma index, 운영 DB와 로그, 서비스와 LLM 프로세스는 이 작업에서 수정하거나 재시작하지 않았다.

## 다음 승인 및 롤백

현재 후보는 Review Team 검토 후 별도 운영 반영 승인이 있어야만 active manifest와 운영 GraphDB에 적용할 수 있다. 이 보고서의 candidate release는 운영 상태와 분리되어 있으므로, 승인 전 중단이 필요하면 candidate release와 격리 작업공간만 폐기하면 된다. 운영 롤백 작업은 필요하지 않다.

남은 위험은 승인 6개 일반 질의 alias의 실사용 검색 품질과, candidate release의 source descriptor가 가리키는 읽기 전용 canonical source가 향후 변경될 때 verify가 의도적으로 fail-closed한다는 점이다. 운영 반영 전에는 실무자 검토와 별도 release gate가 필요하다.
