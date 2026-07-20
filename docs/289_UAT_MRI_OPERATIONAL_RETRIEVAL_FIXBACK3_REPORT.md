# UAT MRI 운영 검색 3차 Fixback 보고서

- 작업일: 2026-07-20
- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-operational-retrieval-fixback-20260720`
- 부모 후보: `14f68c7f09228d0ccc69426b7a936115bfb1041b`
- 보호 메인 및 운영 런타임: 미변경

## 수정 범위

### 판단형 활용을 보상 판단으로 유지

순수 보상·지급 한도, 횟수, 보장·지급 기간, 공제, 비율 명사형은 `policy_attribute_lookup`을 유지한다. 반면 다음 판단형 활용은 coverage/claim 경계로 보낸다.

- `지급 여부`
- `지급되는지`
- `보험금은?`
- `보험금 지급 판단`

일반 `검사X` fixture로 위 활용형과 기존 순수 명사형을 함께 고정했다. 특정 의료행위, 세대, 금액, 문서 또는 chunk ID 분기는 추가하지 않았다.

### 180자 의미 중심 원문 미리보기

direct attribute 검색의 compact 텍스트는 매칭과 답변 산정에만 사용한다. 공개 출처에는 최대 180자의 raw display evidence를 사용한다.

- anchor와 선택 수치가 멀거나 선택 전 인접 금액·횟수·비율이 있으면 `anchor 주변 raw prefix + \`...\` + 선택 수치 주변 raw suffix`를 결합한다.
- 두 부분의 공백과 줄바꿈은 보존한다.
- API는 display evidence가 외부 경로에서 길게 들어와도 동일한 180자 상한을 방어적으로 적용한다. 일반 chunk의 기존 180자 계약은 유지한다.
- 선택값 앞의 공제액과 선택값 뒤의 횟수가 대표 source preview에 남지 않도록 일반 fixture와 실제 v2 source로 검증했다.

## RED에서 GREEN으로

| 경계 | RED | GREEN |
|---|---:|---:|
| 지급 여부·보험금 활용형 | `policy_attribute_lookup`으로 잘못 분류 | coverage judgment 유지 |
| 긴 raw display evidence | 상한 미정의 또는 180자 초과 | 최대 180자, anchor·선택 금액·공백 유지 |
| API display evidence 방어 | 271자 public snippet | 최대 180자, 앞·뒤 의미 경계 유지 |

## 실제 v2 읽기 전용 Smoke

- 4세대 직접 속성 질문: p.71, `300만원`, source preview 길이 180 이하, 원문 공백 보존, `3만원`·`10회` 미노출.
- 5세대 직접 속성 질문: p.286, `200만원`, source preview 길이 180 이하, 원문 공백 보존.
- 4·5세대 비교: 양쪽 세대 source 유지.
- 보장 가능성 질문: coverage/clarification 경계 유지.

## 검증 결과

| 명령/범위 | 결과 |
|---|---:|
| 새 RED regressions | `3 failed` |
| 새 GREEN regressions | `3 passed` |
| search intent/pipeline/API payload focused | `118 passed` |
| Graph/API/계산/수술종수/세션 관련 회귀 | `175 passed, 1 warning` |
| 전체 pytest (임시 DB·lock) | `1173 passed, 3 warnings` |
| 전체 Node + chat.js syntax | `50 passed`, syntax 통과 |
| frontend production build | 통과 |
| actual v2 read-only smoke | 4세대/5세대/비교/clarification 통과 |
| `git diff --check` | 통과 |

## 불변 경계

- `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
- `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
- `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`
- safe-baseline r2 Graph SQLite: `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`

GraphDB, ontology, active rule/manifest, protected main, API/LLM 서비스, 사용자·대화·감사 데이터에는 쓰기 작업을 수행하지 않았다.

## 남은 위험

이 후보는 격리 source lookup과 테스트 환경에서만 검증했다. 보호 메인 통합과 운영 Chrome UAT는 별도 승인 이후에 수행해야 한다. source가 선택 근거를 유일하게 정할 수 없으면 기존 fail-closed 경로를 유지한다.
