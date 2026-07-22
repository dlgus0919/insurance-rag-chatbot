# UAT MRI 운영 검색 fixback2 독립 재검토

- Review 시각: 2026-07-20 21:10:38 KST
- Workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720`
- 이전 후보: `53f658344dbb79d248a532b8109194b28a2f125b`
- Fixback2: `14f68c7f09228d0ccc69426b7a936115bfb1041b`
- Base/protected main: `ba3426eb8b75eabb8be5d1c6e3d8c64195470d59`
- Handoff: `/Users/june_kim/Projects/insurance-rag-chatbot/docs/reviews/2026-07-20-2106-uat-mri-operational-retrieval-fixback2-rereview-handoff.md`
- 범위: read-only 독립 재검토. 통합, commit, push, restart, 18080 접근, 운영 API/Graph/ontology/rule/data 쓰기는 수행하지 않았다.

## Findings

### P1: 판단형 한국어 활용 `지급 여부`가 여전히 속성 조회로 우회됨

수정된 `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720/src/rag/search_intent.py:35-40,110-118`의 `_CLAIM_DECISION_PHRASE_RX`는 `청구`, `계산`, `보험금 지급/판단` 일부 활용형을 보강했지만 `지급 여부`를 포함하지 않는다. 그 결과 다음 독립 재현이 남아 있다.

```text
검사X 연간 보상한도는?                 policy_attribute_lookup False
검사X 연간 보상한도 계산해줘           coverage_judgment True
검사X 연간 보상한도 청구하면?           coverage_judgment True
검사X 연간 보상한도 지급받을 수 있나요? coverage_judgment True
검사X 연간 보상한도 보험금 판단이 필요해 coverage_judgment True
검사X 보상한도 지급 여부는?            policy_attribute_lookup False
검사X 보상한도 보험금은?               policy_attribute_lookup False
```

순수 한도·횟수·기간·공제·비율 명사형은 모두 `policy_attribute_lookup/coverage=False`로 유지됐다. 따라서 현재 남은 결함은 순수 속성 경계를 넓힌 것이 아니라, 판단형 표현의 fail-open 누락이다. `지급 여부`와 `보험금은?` 같은 질문은 보상 가능성/계산에 필요한 추가 조건을 확인하지 않고 직접 약관 속성 검색으로 진입할 수 있다.

최소 수정 요구:

1. `_CLAIM_DECISION_PHRASE_RX` 또는 공통 predicate에 `지급 여부`, `지급되는지`, `보험금 지급 판단` 등 판단형 활용을 추가한다.
2. `지급한도`, `지급기간`, `보상한도`, `보상비율` 같은 순수 속성 명사형은 계속 attribute lookup으로 남긴다.
3. 일반 `검사X` fixture로 위 두 누락 사례와 기존 5개 순수 명사형을 함께 회귀 고정한다. MRI/금액/특정 문서 조건은 추가하지 않는다.

### P1: `display_evidence`에 의미 단위 보존 상한이 없어 기존 180자 UI 계약을 우회함

수정된 `/src/rag/pipeline.py:767-779,1888-1895`는 compact offset으로 raw window를 복구하지만 `_raw_display_window()`는 선택 수치 뒤 81자를 붙일 뿐 전체 길이 상한이 없다. `/src/api/rag_service.py:202-210`은 `display_evidence`가 있으면 `snippet[:180]`을 적용하지 않고 그대로 public payload로 보낸다. frontend `/frontend/js/pages/chat.js:1609-1625`는 이 값을 title/data preview에 그대로 넣는다.

실제 v2 read-only smoke 결과:

```text
4th: p.71, selected 300만원, display_evidence length=228,
     snippet length=228, amount present=True, whitespace preserved=True
5th: p.286, selected 200만원, display_evidence length=130,
     snippet length=130, amount present=True, whitespace preserved=True
```

4세대 display window는 228자로 기존 일반 snippet 180자 제한을 48자 초과한다. 현재 실제 창에는 선택 금액 뒤의 인접 `10회` 문맥과 선택 금액 앞의 `3만원` 공제 문맥까지 함께 들어간다. 5세대는 130자지만 `보상기간 예시` 문맥을 선택해 직접 표 조항과 구분이 약하다. 현재 값이 즉시 HTML을 깨뜨리지는 않았으나, `display_evidence` 길이가 source row와 anchor 위치에 따라 계속 증가할 수 있어 payload/UI 안전성이 코드 계약으로 보장되지 않는다.

최소 수정 요구:

1. `_raw_display_window()`와 `chunk_to_source()` 양쪽에 명시적인 의미 단위 보존 hard cap을 둔다. 예를 들어 승인된 `MAX_DISPLAY_EVIDENCE_CHARS=240` 이하로 제한하되, anchor·선택 수치·단위는 반드시 남기고 줄/문장 경계에서 자른다. 기존 UI가 180자를 계약으로 요구하면 180자를 사용하되, 선택 수치를 보존하도록 window 시작점을 조정한다.
2. `display_evidence`가 cap을 우회하더라도 public snippet과 `data-source-preview`의 실제 길이가 같은 상한을 넘지 않는 regression을 추가한다.
3. actual v2 p.71/p.286에서 `300만원`/`200만원`, 원문 whitespace, 올바른 page가 유지되고 인접 금액이 대표 근거처럼 남지 않는지 확인한다.

## 해소된 부분과 실제 v2 확인

- 계산/청구/지급받기/보험금 판단의 기본 4개 action fixture는 coverage judgment로 전환됐다.
- 순수 속성 5개 fixture는 attribute lookup으로 유지됐다.
- actual v2 direct hit는 4th `약관_ch_002441`, p.71, 300만원과 5th `표준약관_ch_005435`, p.286, 200만원을 반환했다.
- 비교 질의는 4th와 5th source를 함께 반환했고, 보장 판단 질의는 `ambiguous_medical_term`, `coverage=True`, direct attribute hit 없음으로 유지됐다.
- compact matching text와 raw `display_evidence`가 분리되어 answer/source 금액과 공백은 기존보다 개선됐지만 위 길이 상한 결함이 남았다.
- 변경된 제품 코드 diff에는 특정 MRI/MRA, 세대, 금액, 문서명, chunk ID 예외가 추가되지 않았다.

## 독립 검증

- focused: `7 passed, 108 deselected`.
- 전체 pytest, 임시 `INSURANCE_ONTOLOGY_REBUILD_LOCK` 사용: `1170 passed, 3 warnings in 16.35s`.
- 전체 Node: `49 passed`; `node --check frontend/js/pages/chat.js`: passed.
- frontend production build는 보호 checkout 의존성을 `NODE_PATH`로 read-only 참조하고 `/tmp`에 출력했으며 기존 dist와 byte-for-byte 일치했다.
- 후보 `git diff --check`: passed; candidate status clean.
- 실제 source lookup은 11,562 rows, 최초 load 약 0.438초, direct query 약 18-24ms로 계측되어 이번 delta에서 별도 성능 blocker는 확인하지 못했다.
- frozen hash:
  - `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
  - `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
  - `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
  - safe-baseline r2 Graph SQLite: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`
- protected main HEAD는 기준 커밋을 유지했다. 운영 상태, Graph/ontology/active rule, 사용자·대화·감사 데이터는 변경하지 않았다.

## Verdict

`CHANGES_REQUESTED`

Fixback2는 이전 두 결함의 대표 사례를 개선했지만, `지급 여부` 판단형 누락과 `display_evidence`의 의미 단위 보존 상한 부재 때문에 운영 승격 대상이 아니다. 위 두 최소 수정만 Developer가 반영한 후 delta 재검토가 필요하다.

## Ready-to-send Developer fixback prompt

```text
Review Team CHANGES_REQUESTED. 현재 fixback2의 최소 delta만 수정하십시오.

1) src/rag/search_intent.py의 claim predicate에 `지급 여부`, `지급되는지`, `보험금 지급 판단` 활용형을 보강하십시오. `검사X 보상한도 지급 여부는?`가 현재 policy_attribute_lookup/coverage=False로 남습니다. 순수 `보상한도/횟수한도/보장기간/공제금액/보상비율` 명사형은 유지하고 MRI-specific 조건은 금지하십시오.

2) src/rag/pipeline.py의 raw display window와 src/api/rag_service.py public snippet에 명시적인 의미 단위 보존 hard cap을 추가하십시오. 실제 v2 4th p.71 window가 228자입니다. 승인된 상한(예: 240자 또는 기존 UI 180자)을 코드와 테스트에 고정하고, anchor/선택 금액/단위/원문 whitespace는 보존하되 줄·문장 경계에서 자르십시오. frontend hover/data-source-preview도 같은 상한을 지켜야 합니다.

검증: 지급 여부 adversarial intent fixture, pure noun regression, actual v2 4th/5th/comparison/clarification, p.71/p.286 payload/hover length and amount, focused/full pytest, Node/build, diff-check. 운영 API/Graph/ontology/rules/active data는 변경하지 마십시오.
```

REVIEW_TEAM_UAT_MRI_OPERATIONAL_RETRIEVAL_FIXBACK2_CHANGES_REQUESTED_NO_INTEGRATION_NO_PUSH
