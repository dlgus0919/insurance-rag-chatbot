# UAT MRI 운영 검색 2차 Fixback 보고서

- 작업일: 2026-07-20
- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720`
- 대상 후보: `53f658344dbb79d248a532b8109194b28a2f125b` 위 최소 fixback
- 보호 메인 및 운영 런타임: 미변경

## 수정 범위

### 1. 약관 속성 조회와 보상 판단의 분리

`policy_attribute_lookup`은 한도, 횟수, 기간, 공제, 비율을 순수하게 조회하는 질문에만 사용한다. 청구, 계산, 보험금 또는 지급 판단 표현이 있으면 기존 보상 판단 경로를 유지하도록 공통 의도 판별을 보강했다.

`검사X` fixture로 다음 경계를 고정했다.

- 순수 속성 질문은 직접 약관 조회를 유지한다.
- `계산해줘`, `청구하면`, `지급받을 수 있나요`, `보험금 판단`은 보상 판단으로 분류되어 확인 질문과 계산 경계를 우회하지 않는다.

### 2. compact 매칭과 공개 원문 근거의 분리

직접 약관 속성 검색은 공백을 제거한 compact 텍스트를 매칭과 결정적 답변 산정에만 사용한다. 사용자가 보는 출처와 hover 미리보기에는 선택한 의료행위 anchor부터 선택된 한도·횟수·기간 단위까지의 원문 공백 보존 창을 `display_evidence`로 전달한다.

- 일반 fixture에서 선행 `350만원`은 공개 창에서 제외되고, 선택 근거 `200만원`과 원문 줄바꿈이 유지된다.
- 연간 한도 질의는 공제액 `3만원`보다 연간 조건이 앞에 연결된 `200만원`을 우선 선택한다.
- API source payload는 `display_evidence`가 있으면 그 제한된 원문 창을 사용하고, 일반 chunk는 기존 180자 snippet 계약을 유지한다.
- 프런트 source badge/hover는 API snippet을 그대로 사용하므로 원문 공백과 올바른 단위가 보존된다.

## RED에서 GREEN으로

| 경계 | RED | GREEN |
|---|---:|---:|
| 순수 속성 대 청구·계산 의도 | `1 failed, 1 passed, 11 deselected` | `2 passed, 11 deselected` |
| 연간 한도 대 인접 공제액 선택 | `1 failed, 71 deselected` (`3만원` 선택) | `2 passed, 70 deselected` |
| raw display evidence와 API source | compact snippet/단위 절단 재현 | `2 passed, 99 deselected` |

## 실제 v2 읽기 전용 Smoke

보호 데이터의 canonical/v2 index와 safe-baseline r2를 읽기 전용으로 사용했다.

- 4세대 직접 속성 질문: source 1건, p.71, 결정적 답변 및 공개 snippet에 `300만원`.
- 5세대 직접 속성 질문: source 2건 중 p.286 근거 포함, 결정적 답변 및 공개 snippet에 `200만원`.
- 4·5세대 비교 질문: 양쪽 세대 source를 함께 유지.
- 보장 가능성 질문: 보상 판단/clarification 경계를 유지.

## 검증 결과

| 명령/범위 | 결과 |
|---|---:|
| search intent, pipeline, API payload focused | `10 passed, 105 deselected` |
| Graph/API/계산/수술종수/세션 관련 회귀 | `174 passed, 1 warning` |
| 전체 pytest (임시 DB·lock) | `1170 passed, 3 warnings` |
| Node tests + chat.js syntax | `49 passed`, syntax 통과 |
| frontend production build | 통과 |
| actual v2 read-only smoke | 4세대 300만원, 5세대 200만원, 비교/clarification 통과 |
| `git diff --check` | 통과 |

## 불변 경계

다음 값은 작업 전후 동일하다.

- `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
- `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
- `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
- safe-baseline r2 Graph SQLite: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`

GraphDB, ontology, active rule/manifest, protected main, API/LLM 서비스, 사용자·대화·감사 데이터에는 쓰기 작업을 수행하지 않았다.

## 남은 위험

이 후보는 격리 read-only index smoke까지만 검증했다. 운영 API 및 Chrome UAT는 protected main 통합과 별도 승인 이후에만 수행해야 하며, source 원문이 서로 충돌하거나 선택 근거를 유일하게 정할 수 없으면 기존 fail-closed 경로를 유지한다.
