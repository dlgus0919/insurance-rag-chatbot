# UAT MRI 세대별 근거 정합성 후보 Review Team 인계

## 검토 대상

- 후보 커밋: `51405559a92be7c7bb8daa19a0a5e466a5d0e233`
- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-runtime-grounding-20260720`
- 브랜치: `codex/uat-mri-runtime-grounding-20260720`
- 기준 커밋: 보호 메인 `2ea0d81666bd121b9b52d7d40c2deca4f1122d87`
- 구현 보고서: `docs/285_UAT_MRI_RUNTIME_GROUNDING_FIX_REPORT.md`
- 원인/범위 명세: `docs/reviews/2026-07-20-1647-uat-mri-runtime-grounding-regression-triage.md`

Review Team은 읽기 전용으로 후보를 검토한다. 보호 메인 통합, 서비스 재기동, 운영 데이터 변경,
GraphDB/ontology/계산 룰 변경, push는 금지한다.

## 확인된 운영 결함

Chrome 실사용에서 4세대가 선택된 상태로 MRI/MRA 연간 한도를 물었으나 5세대·무관 예시의
`200만원`이 최종 답변에 승격됐다. UI와 API에는 `4th`가 전달됐지만 v2 재청크 인덱스의
식별자가 canonical 청크와 달라 세대 메타데이터 보강이 실패했고, 세대 미확인 hit이 기존
필터를 통과했다. Graph의 `missing` 요약도 최종 말풍선 본문에 남았다.

## 후보 변경 요약

1. canonical 청크와 재청크 인덱스의 출처를 정규화 본문 해시와 안정 메타데이터로 보수적으로
   교차 연결한다. 일치가 유일하지 않으면 매핑하지 않는다.
2. 선택 세대가 있는 직접 조항 속성 질의에서만 선택 세대가 확인된 hit을 남겨 fail-closed 한다.
3. 구조화 Graph 패널에 포함된 `missing` 경로의 동일 요약 문장만 답변 본문에서 제거한다.
4. 특정 MRI, 금액, 세대, 질문 문자열을 제품 코드에 하드코딩하지 않는다.

## 독립 검토 요구

1. provenance key가 실제 데이터에서 충분히 보수적이며 오교차 가능성이 없는지 확인한다.
   - 동일 본문·동일 페이지가 복수 canonical 행으로 존재하면 반드시 매핑하지 않아야 한다.
   - 재청크 본문이 달라 매핑되지 않는 경우는 세대 직접 속성 답변에서 fail-closed 해야 한다.
2. 엄격 세대 필터의 범위가 직접 조항 속성 질의로 제한되는지 확인한다.
   - 일반 보상 가능성 질의, 세대 미선택 질의, 정상 추가질문/출처 흐름을 훼손하면 안 된다.
   - 질문 문자열, MRI, 300/200만원 하드코딩이 없어야 한다.
3. Graph `missing` 요약 제거가 구조화 패널이 실제 표시되는 경우의 동일 문장에만 적용되는지
   확인한다. 사용자에게 필요한 추가 확인 질문·정상 본문·출처는 보존해야 한다.
4. 회귀 테스트가 구현을 단순 추종하지 않고 다음 실패 경계를 실제로 고정하는지 확인한다.
   - rechunk ID 불일치 + 세대 메타데이터 보강
   - generation-empty hit의 직접 속성 답변 제외
   - missing summary 본문 제거
5. focused/관련/전체 pytest를 독립 실행한다. 운영 safe-baseline 환경과 테스트 격리 경계를
   분리하고, 환경 실패가 있으면 제품 회귀와 구분해 근거를 제시한다.
6. 다음 불변값을 확인한다.
   - 계산 룰 3개 SHA-256
   - r2 Graph DB SHA-256
   - 보호 메인 HEAD/status
   - SGLang/API/GraphDB/온톨로지/대화·계정 데이터 미변경

## 판정

- `PASS`: 일반화·회귀·불변 경계가 모두 충족됨. 보호 메인 API-only 배포 후보로 인계 가능.
- `CHANGES_REQUESTED`: 오교차, 과도한 필터, 사용자 정보 손실, 테스트 공백 또는 하드코딩 발견.
- `BLOCKED`: 읽기 권한이나 실행 환경 문제로 핵심 경계를 확인할 수 없음.

완료 표식:

`REVIEW_TEAM_UAT_MRI_RUNTIME_GROUNDING_CANDIDATE_VERDICT_COMPLETE_NO_INTEGRATION_NO_PUSH`
