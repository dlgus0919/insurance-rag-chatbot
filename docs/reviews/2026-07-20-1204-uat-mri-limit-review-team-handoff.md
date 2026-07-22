# UAT MRI/MRA 연간 한도 P0 패치 검토 인수인계

## 검토 대상

- 격리 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-uat-mri-limit-20260720`
- 기준 및 현재 HEAD: `f4d4495eed2e1a58e63c692125a9cbce64533c8b`
- 상태: 미커밋 패치 6개 파일, `git diff --check` 통과
- 변경 파일:
  - `src/api/rag_service.py`
  - `src/api/routes/chat.py`
  - `src/graph/query_planner.py`
  - `src/graph/retriever.py`
  - `tests/test_api_chat_stream.py`
  - `tests/test_graph_query_planner.py`

## 재현 결함과 확인된 원인

- UI에서 5세대를 선택했지만 Graph 계획에는 세대 범위가 전달되지 않아 세대 확인을 다시 요구했다.
- 승인된 긴 별칭 `자기공명영상진단(MRI/MRA)`이 확인된 뒤에도 내부의 짧은 미확정 후보 `자기공명`이 다시 추가되어 불필요한 용어 확인 질문을 만들었다.
- 5세대 직접 원문 `표준약관_ch_005607` p.407은 연간 200만원, 4세대 직접 원문 `약관_ch_002441` p.74는 연간 300만원을 명시한다. 패치는 이 수치를 코드에 하드코딩하지 않는다.

## 개발자 검증 증거

- Graph 계획기와 채팅 전달 경로 집중 회귀: `59 passed`
- `git diff --check`: 통과
- 운영 인덱스와 원문은 읽기 전용으로 확인했다.
- 격리 API 전체 smoke는 활성 안전 베이스라인 SQLite sidecar 감지로 fail-closed되어 완료하지 못했다. 운영 파일을 수정하거나 우회하지 않았다.
- 보호 메인, 운영 앱, 활성 계산 룰, 룰 hash, GraphDB, 온톨로지, UAT 파일, 원격 저장소는 변경하지 않았다.

## 필수 검토 항목

1. UI 세대 범위가 Graph 계획까지 일반 계약으로 전달되는가.
2. 사용자 문장에 단일 세대가 명시되었는데 UI 선택과 충돌할 때의 우선순위가 제품 원칙에 맞고 테스트로 고정됐는가.
3. 명시적 4세대/5세대 비교만 단일 세대 필터를 해제하며, 비교 판정이 채팅과 Graph 계획에서 일관적인가.
4. 확인된 긴 별칭이 같은 canonical의 짧은 후보를 억제하되, 실제로 모호한 짧은 단독 입력은 계속 확인 질문을 내는가.
5. 한도/횟수/기간 같은 약관 속성 질의에서만 방문·증빙 질문을 억제하고, 실제 보험금 계산·청구 판단 질의에는 필요한 확인 질문이 남는가.
6. MRI/MRA 또는 한도 수치 전용 하드코딩 없이 000번 원칙을 지켰는가.
7. 4세대와 5세대 근거가 섞이지 않고, 충분한 직접 근거가 있을 때 결론을 먼저 합성할 수 있는가.
8. 탈모 후속 대화, 수술종수/수가코드, 보험금 계산 경로에 회귀 위험이 없는가.
9. 활성 계산 룰, GraphDB, 온톨로지, 데이터에 변경이 전혀 없는가.
10. 격리 API smoke 미완료 상태를 감안해도 보호 메인 적용 후 Chrome 운영 UAT로 검증 가능한 수준인가.

## 판정 형식

- `PASS`: 보호 메인 반영 후 운영 Chrome 재시험 가능
- `CHANGES_REQUIRED`: 파일/행과 재현 가능한 수정 요구를 명시
- `BLOCKED`: 접근 불가능한 필수 증거를 명시
- 완료 marker: `REVIEW_TEAM_UAT_MRI_LIMIT_REVIEW_COMPLETE`
