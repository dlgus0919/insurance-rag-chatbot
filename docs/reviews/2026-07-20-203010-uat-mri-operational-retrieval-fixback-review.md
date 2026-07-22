# UAT MRI 운영 검색 fixback 독립 Review

- Review 시각: 2026-07-20 20:30:10 KST
- 후보 workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720`
- 후보: `53f658344dbb79d248a532b8109194b28a2f125b`
- 기준/보호 main: `ba3426eb8b75eabb8be5d1c6e3d8c64195470d59`
- 인계서: `/Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-20-2016-uat-mri-operational-retrieval-fixback-review-team-handoff.md`
- 범위: read-only 독립 검토. protected main 통합, commit, push, restart, 18080 접근, 운영 API/Graph/ontology/rule/data 변경은 수행하지 않았다.

## Findings

### P1: claim/calculation 의도가 policy attribute lookup으로 우회됨

근거:

- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720/src/rag/search_intent.py:105-113`의 `_is_coverage_judgment()`는 보상 가능성 표현만 검사하고 `청구`, `계산`, 일반 `지급`을 판단 단서로 포함하지 않는다.
- 같은 파일 `:165-209`에서 `has_policy_attribute and not requires_coverage`가 generic coverage/claim 경로보다 먼저 반환된다.
- `/src/rag/pipeline.py:2334-2342`는 이 intent일 때 `source_chunk_lookup` 전체를 직접 순회해 근거를 회수한다.

후보에서 다음 read-only 재현을 실행했다.

```text
classify_search_intent("5세대 MRI 연간 보상한도는?")
  policy_attribute_lookup, coverage=False
classify_search_intent("5세대 MRI 연간 보상한도 계산해줘")
  policy_attribute_lookup, coverage=False
classify_search_intent("5세대 MRI 연간 보상한도 청구하면?")
  policy_attribute_lookup, coverage=False
classify_search_intent("5세대 MRI 보상비율로 계산해줘")
  policy_attribute_lookup, coverage=False
```

MRI가 아닌 일반 fixture에서도 동일하게 재현했다.

```text
query: 5세대 검사X 연간 보상한도 계산해줘
intent=policy_attribute_lookup coverage=False
hits=[('policy-row', '검사X는1년간보상한도200만원입니다.')]
query: 5세대 검사X 연간 보상한도 청구하면?
intent=policy_attribute_lookup coverage=False
hits=[('policy-row', '검사X는1년간보상한도200만원입니다.')]
```

영향은 약관 속성만 묻는 질문과 청구/계산/지급 판단을 구분하지 못해, 방문·증빙·가입조건 확인 질문과 전용 계산 경로를 우회하고 단순 한도 근거를 action-oriented 질문의 답처럼 제공할 수 있다는 것이다. 기존의 `보장되나요` 변형은 coverage flag가 유지되지만, handoff가 요구한 청구·지급·계산 경계 전체를 닫지는 못한다.

최소 fixback 요구:

1. `_is_coverage_judgment()` 또는 동등한 공통 predicate에 `청구`, `계산`, `보험금`, 지급 판단 표현을 추가한다. 단, 순수 `보상한도`, `보상비율`, `지급한도`, `보장기간` 같은 속성 명사형은 계속 attribute lookup으로 남겨야 한다.
2. 다음 일반화된 regression을 추가한다: 순수 속성 질의는 `policy_attribute_lookup/coverage=False`, `검사X ... 계산해줘`, `검사X ... 청구하면?`, `검사X ... 지급받을 수 있나요?`는 coverage/claim clarification path와 `coverage=True`로 진입한다.
3. 변경 후 focused와 전체 회귀를 다시 실행한다. MRI/금액 문자열만 추가해 통과시키는 조건부 예외는 금지한다.

### P1: direct hit의 compact document가 API source snippet과 hover preview를 훼손함

근거:

- `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720/src/rag/pipeline.py:1830-1845`가 원문을 `_compact_text()`로 공백 제거한 뒤 `evidence_text`와 `Hit.document`에 저장한다.
- `_compact_text()`는 같은 파일 `:763-764`에서 모든 whitespace를 제거한다.
- `/src/api/rag_service.py:196-209`는 `Chunk.text[:180]`을 public `snippet`으로 전송한다.
- frontend `/frontend/js/pages/chat.js:1609-1625`는 그 snippet을 source badge의 title/data preview로 그대로 노출한다. page metadata 자체는 유지되지만 snippet이 선택된 조항을 대표한다는 계약은 깨진다.

실제 v2 read-only smoke에서 후보 canonical `data/processed/chunks.jsonl`과 보호 checkout의 `data/processed/chunks_v2_manual.jsonl`을 source lookup에 주입했다.

```text
lookup_rows=11562, load_seconds=0.438
4th: hit 약관_ch_002441, page=71, document contains 300만원=True,
     deterministic answer contains 300만원=True,
     source_snippet_has_amount=False
5th: hit 표준약관_ch_005435, page=286, document contains 200만원=True,
     deterministic answer contains 200만원=True,
     source_snippet_has_amount=False
```

두 snippet 모두 공백이 제거되어 있었고, 첫 180자에는 실제 질의 금액 대신 인접 표의 `350만원`/`5만원` 등 다른 수치가 노출됐다. 따라서 최종 deterministic answer와 page는 우연히 맞더라도 public source/hover는 원문 왜곡 및 잘못된 수치 인상을 준다. 실제 hit document도 한 chunk 안에 `350만원`, `250만원`, `300만원` 또는 `200만원`이 함께 있어 OCR 표의 인접 행 혼입 위험을 남긴다.

최소 fixback 요구:

1. anchor/단위 matching에만 compact text를 사용하고, 사용자에게 전달하는 `Hit.document` 또는 별도 display evidence에는 원문 whitespace를 보존한 bounded window를 사용한다. 원문 window는 선택된 anchor와 해당 금액/횟수/기간 단위를 포함해야 한다.
2. `chunk_to_source()`와 frontend `sourcePreviewText()` 경로가 compact matching text를 public snippet으로 사용하지 않도록 한다.
3. API payload regression에서 4th `300만원`, 5th `200만원`이 각각 snippet/hover에 존재하고, 원문 공백이 보존되며, page 71/286이 유지되는지 확인한다. 다른 인접 수치가 snippet의 대표 근거로 남지 않아야 한다.

## 추가 검토 결과

- 변경된 제품 코드에는 특정 MRI/MRA, 금액, 문서명, lane, chunk ID를 조건으로 하는 예외가 없다. anchor는 질문 token과 generic category를 사용한다.
- `_policy_attribute_anchor_positions()` (`pipeline.py:1743-1768`)는 긴 anchor만 3개 순서 fragment로 보강하고 각 fragment 간 거리를 96자로 제한하며 짧은 약어는 exact match만 사용한다. 별도의 MRI-specific anchor는 확인되지 않았다. 다만 실제 v2 hit가 여러 표 행을 compact chunk로 묶어 반환하므로 위 P1 display finding의 raw bounded-window fix가 함께 필요하다.
- `_policy_attribute_number_matches()` (`pipeline.py:1771-1782`)는 limit 질의에서 금액/횟수/기간 단위를 구분한다. 실제 v2 결과의 deterministic answer는 4th 300만원, 5th 200만원으로 확인됐다. 그러나 청구/계산 intent 우회와 compact mixed-row display가 먼저 해결되어야 운영 승격할 수 있다.
- 실제 lookup 전체 순회는 11,562 rows를 대상으로 query당 약 18-24 ms로 계측됐다. 현재 규모에서 별도 index/cache를 요구할 성능 결함은 확인하지 못했다.

## 독립 테스트

- focused: `pytest tests/test_search_intent.py tests/test_pipeline.py -k "policy_attribute or generation_sources or requires_money_measure"` -> `5 passed, 76 deselected`.
- candidate full without lock override: `1163 passed, 2 failed, 3 warnings`; 두 실패는 `scripts/ontology_review.py:102`의 기존 `/tmp/insurance-rag-ontology-rebuild.lock` permission error였다.
- candidate full with temporary `/tmp` `INSURANCE_ONTOLOGY_REBUILD_LOCK`: `1165 passed, 3 warnings in 17.69s`.
- Node: `node --test tests/*.mjs` -> `48 passed`; `node --check frontend/js/pages/chat.js` -> passed.
- frontend production build: 보호 checkout의 의존성을 `NODE_PATH`로 read-only 참조하고 `/tmp`에만 build했다. `app.min.js`와 `graph-viz.min.js` 모두 `cmp` byte-for-byte 일치.
- 초기 graph build 명령은 후보에 `node_modules`가 없어 `3d-force-graph` resolve 실패했지만, 후보에 link를 만들지 않고 `NODE_PATH` read-only 방식으로 재빌드해 통과했다.

## 불변성 및 frozen hash

- 후보 HEAD: `53f658344dbb79d248a532b8109194b28a2f125b`; candidate status clean.
- `git diff --check ba3426eb8b75eabb8be5d1c6e3d8c64195470d59`: passed.
- 보호 main HEAD: `ba3426eb8b75eabb8be5d1c6e3d8c64195470d59`; 통합·push·재기동·운영 API 요청은 수행하지 않았다.
- frozen hashes:
  - `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
  - `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
  - `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
  - safe-baseline r2 Graph SQLite: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`

## Verdict

`CHANGES_REQUESTED`

Review Team은 제품 코드를 수정하지 않았다. 위 두 P1 fixback을 Developer가 일반화된 regression과 함께 반영한 뒤, 해당 delta만 재검토해야 한다. 현재 후보는 운영 승격·protected main 통합 대상이 아니다.

## Ready-to-send Developer fixback prompt

```text
Review Team CHANGES_REQUESTED. 제품 코드의 최소 fixback만 수행하십시오.

1) src/rag/search_intent.py에서 순수 policy attribute 명사형과 청구/지급/계산/보험금 판단을 분리하십시오. 현재 `5세대 검사X 연간 보상한도 계산해줘`와 `... 청구하면?`이 policy_attribute_lookup, coverage=False로 분류되어 clarification/calculation 경로를 우회합니다. MRI 전용 조건은 금지합니다. 순수 한도/횟수/기간/공제/비율 조회는 유지하고, 일반 검사X fixture로 RED/GREEN 회귀를 추가하십시오.

2) src/rag/pipeline.py:1830-1845의 compact_text는 matching 전용으로 제한하십시오. 실제 v2에서 4th/5th answer/page는 맞지만 API snippet/hover에는 각각 300만원/200만원이 빠지고 공백이 제거됩니다. raw whitespace를 보존한 bounded display evidence를 사용하고, 해당 금액과 anchor가 snippet에 포함되도록 src/api/rag_service.py와 frontend preview 계약을 최소 보정하십시오. 인접 350/5만원 수치가 대표 snippet으로 노출되지 않아야 합니다.

검증: generic intent focused, actual v2 read-only 4th/5th/comparison/clarification smoke, API payload + frontend preview regression, related/full pytest, Node/build, diff-check. 계산 rule/ontology/Graph/운영 data/active manifest는 변경하지 마십시오.
```

REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK_CHANGES_REQUESTED_NO_INTEGRATION_NO_PUSH
