# UAT MRI 운영 검색 fixback3 독립 재검토

- Review 시각: 2026-07-20 21:40:57 KST
- Workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720`
- 이전 후보: `14f68c7f09228d0ccc69426b7a936115bfb1041b`
- 검토 후보: `a988ef14ce988dfb1163b1897ba740e4249c8169`
- Base/protected main: `ba3426eb8b75eabb8be5d1c6e3d8c64195470d59`
- Handoff: `/Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-20-2120-uat-mri-operational-retrieval-fixback3-rereview-handoff.md`
- 범위: read-only 독립 재검토. 통합, commit, push, restart, 18080 접근, 운영 API/Graph/ontology/rule/data 쓰기는 수행하지 않았다.

## Findings

### 없음

Fixback2의 두 잔여 결함을 실제 후보 코드와 v2 read-only 경로에서 재검증했으며, 조치가 필요한 추가 결함을 확인하지 못했다.

## Intent 경계

후보 `/src/rag/search_intent.py:35-43,110-118`의 claim predicate를 일반 fixture로 검증했다.

```text
검사X 연간 보상한도는?                 policy_attribute_lookup False
검사X 지급한도는?                      policy_attribute_lookup False
검사X 지급기간은?                      policy_attribute_lookup False
검사X 보상한도 지급 여부는?            coverage_judgment True
검사X 보상한도 지급되는지 알려줘       coverage_judgment True
검사X 보상한도 보험금은?               coverage_judgment True
검사X 보상한도 보험금 지급 판단이 필요해 coverage_judgment True
```

순수 한도·기간 명사형은 attribute lookup으로 유지되고 지급 판단형은 coverage/claim 경로로 전환된다. 특정 MRI, 세대, 금액, 문서, chunk ID 조건은 변경 제품 코드에 추가되지 않았다.

## Display evidence/API 경계

- `/src/rag/pipeline.py:767-859,1887-1900`의 raw offset/window는 compact matching과 원문 display를 분리하고, prefix + `\n...\n` + suffix 조합을 최대 180자로 제한한다.
- `/src/api/rag_service.py:196-230`의 `_bounded_display_evidence()`는 외부 또는 비정상적으로 긴 metadata도 동일 180자 상한으로 재절단한다.
- 실제 v2 smoke:
  - 4세대 `약관_ch_002441`, p.71: display/snippet 108자, `300만원` 보존, whitespace 보존, `3만원`·`10회` 미노출, ellipsis 유지
  - 5세대 `표준약관_ch_005435`, p.286: display/snippet 50자, `200만원` 보존, whitespace 보존, 인접 수치 미노출
  - 비교 질의: 4th와 5th source 각각 유지
  - 보장 판단 질의: `ambiguous_medical_term`, `coverage=True`, direct attribute hit 없음
- 외부 긴 metadata fixture: API snippet 179자, prefix/suffix/ellipsis와 선택 `200만원` 모두 보존.
- source badge/hover는 bounded API snippet을 사용하며 Node 회귀에서 preview 길이와 raw whitespace를 확인했다.

## 독립 검증

- focused Python: `10 passed, 108 deselected`.
- 전체 pytest, 임시 `INSURANCE_ONTOLOGY_REBUILD_LOCK`: `1173 passed, 3 warnings in 16.62s`.
- 전체 Node: `50 passed`; `node --check frontend/js/pages/chat.js`: passed.
- frontend production build는 보호 checkout 의존성을 `NODE_PATH`로 read-only 참조하고 `/tmp`에 출력했다. app/graph dist 모두 `cmp` byte-for-byte 일치.
- 후보 HEAD `a988ef14ce988dfb1163b1897ba740e4249c8169`; candidate status clean.
- `git diff --check 14f68c7f09228d0ccc69426b7a936115bfb1041b`: passed.

## 불변성 및 frozen hash

- protected main HEAD는 `ba3426eb8b75eabb8be5d1c6e3d8c64195470d59`로 유지됐다.
- `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
- `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
- `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
- safe-baseline r2 Graph SQLite: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`
- GraphDB, ontology, active rules/manifest, 운영 API/LLM, 사용자·대화·감사 데이터는 변경하지 않았다.

## Verdict

`PASS`

정확히 검토한 fixback3 delta는 별도 승인 후 code promotion 대상으로 판단할 수 있다. protected main 통합과 운영 Chrome/API UAT는 별도 승인 게이트로 유지하며, 이 review에서는 수행하지 않았다.

REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK3_PASS_NO_INTEGRATION_NO_PUSH
