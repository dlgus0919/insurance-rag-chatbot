# 286. UAT MRI 세대별 근거 정합성 운영 Fixback 보고서

## 범위와 경계

- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-fixback-20260720`
- 기준 커밋: `1c6812007eb7d24feeb512b28afe078ab770adbb`
- 보호 메인, 운영 API/LLM, safe-baseline, GraphDB, 활성 계산 룰, 사용자/대화/감사 데이터는 수정하지 않았다.
- 이번 후보는 일반적인 재청크 provenance 보강과 사용자용 구조화 패널 렌더링에 한정한다. 특정 의료행위, 세대, 금액, 질문 문구를 제품 코드에 추가하지 않았다.

## 읽기 전용 진단

운영 감사 기록의 해당 turn(감사 ID `500`)은 `policy_generation=4th`, `effective_index_mode=v2_only`로 기록되었고, 최종 source 수는 0건이었다. 사용자 원문과 식별 정보는 출력하지 않았다.

canonical/v2 원본 메타데이터 비교에서는 자사 약관의 직접 근거 canonical 행 `약관_ch_002310`이 `policy_generation=4th`, 동일 문서 파일, 페이지 `8-31`을 갖는 것을 확인했다. v2에는 `약관_ch_002310`과 `약관_ch_010151` 두 variant가 존재했고 각 행의 source/canonical/variant ID가 달랐지만 문서·페이지·구간 메타데이터와 정규화 본문 지문은 동등했다. v2 행의 세대 메타데이터는 비어 있었다. 기존 로더는 전체 본문 해시와 모든 provenance 필드의 완전 일치를 먼저 요구했으므로, 재청크 경계 또는 variant ID가 달라지는 경우 canonical 세대 메타데이터를 보강하지 못할 수 있었다. 회귀 fixture는 본문 경계가 달라지는 경우도 별도로 고정한다.

또한 답변 본문은 missing 경로의 내부 요약을 이미 제거했지만, SPA의 `renderGraphReviewPathsHtml()`은 `graph_review_paths[].summary`를 그대로 표시했다. 따라서 같은 기술 문구가 구조화 패널에 남았다.

## 구현

1. `load_source_metadata_lookup()`은 indexed 행의 `id`, `source_chunk_id`, `canonical_chunk_id`, `variant_chunk_id`를 canonical 원본 ID와 먼저 대조한다. 유일한 canonical 행이고 세대 값이 충돌하지 않을 때만 canonical 메타데이터를 alias에 보강한다.
2. 명시 ID가 canonical 원본에 없을 때만 안정 provenance fallback을 사용한다. 문서 식별자, 페이지 범위, 구간 메타데이터가 있는 후보만 고려하고, canonical 후보들이 동일 문서/구간/본문 지문/상품 속성/세대의 단일 동등 class일 때만 정렬상 첫 canonical 대표를 사용한다. 둘 이상의 class 또는 세대 충돌은 매핑하지 않는다.
3. 구조화 검토 패널은 `status=missing`인 경로의 `summary`만 렌더하지 않는다. 상태 배지, 필요한 증빙, 정상 경로의 요약과 그 외 사용자용 정보는 유지한다.

## RED -> GREEN 회귀

RED 확인:

- 명시적 canonical ID가 있으나 재청크 본문 경계가 달라진 행은 세대 필터 전에 4세대 메타데이터를 보강하지 못했다.
- `status=missing` 경로의 내부 기술 요약이 구조화 패널 HTML에 노출됐다.

GREEN 확인:

- 명시 canonical provenance 경로, 명시 ID 없는 단일 동등 provenance class fallback, 세대 충돌 fail-closed, 기존 unique exact provenance 호환: `5 passed`.
- missing summary 비렌더링과 정상 확정 summary 보존: Node `6 passed`.

## 검증 결과

| 명령 | 결과 |
| --- | --- |
| `pytest tests/test_pipeline.py -q -k 'crosswalks_rechunked_source_metadata or equivalent_stable_provenance or generation_conflicts or conflicting_explicit_generation or unique_exact_provenance'` | 5 passed |
| `node --test tests/test_frontend_assistant_display.mjs` | 6 passed |
| `pytest tests/test_pipeline.py tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py -q` | 140 passed, warning 1 |
| `node --test tests/test_frontend_assistant_display.mjs tests/test_frontend_source_preview_settings.mjs` | 12 passed |
| `node --test tests/*.mjs` | 48 passed |
| `node --check frontend/js/pages/chat.js` | passed |
| `npm --prefix frontend run build` | passed |
| `pytest -q` with isolated temporary DB/lock/cache | 1159 passed, 1 failed, warnings 3 |
| `git diff --check` | passed |

전체 pytest의 유일 실패는 `test_resolve_default_ontology_manifest_prefers_env`다. `INSURANCE_SAFE_BASELINE_RUNTIME_ROOT=safe-baseline-v1.2.0-r2` 환경에서 runtime root가 테스트 전용 `INSURANCE_ONTOLOGY_MANIFEST`보다 우선되는 기존 환경 경계이며, 보호 메인 `1c681200...`에서 같은 임시 환경으로 단건 재현했다. 이번 후보의 provenance 또는 SPA 변경으로 새로 생긴 실패가 아니다.

## 불변 경계

- `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
- `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
- `src/claim_calculation/processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
- r2 Graph DB SHA-256: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`

모두 변경 전 기준과 일치한다. 보호 메인은 `1c6812007eb7d24feeb512b28afe078ab770adbb`에 그대로 두었고, 운영 서비스 재기동, Graph/ontology 재빌드, active rule 변경, push는 수행하지 않았다.

## 남은 위험과 다음 단계

실제 Chrome UAT는 후보가 보호 메인에 독립 리뷰 후 반영되고 API만 재기동된 뒤 수행해야 한다. provenance가 명시 ID도 없고 단일 동등 class도 만들지 못하는 입력은 의도적으로 세대를 확정하지 않고 fail-closed로 남는다. 운영 DB에 존재하는 WAL/SHM sidecar는 실행 중인 앱의 런타임 파일로 관찰만 했으며 삭제·변경하지 않았다.
