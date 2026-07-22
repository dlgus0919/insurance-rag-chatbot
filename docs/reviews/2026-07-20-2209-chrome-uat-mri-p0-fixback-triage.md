# Chrome 운영 UAT MRI P0 fixback triage

## 판정

- 상태: `P0 FAIL / Developer 재진단 진행 중`
- 보호 메인 배포 커밋: `48a6cf7a942a627c4b70cd6ee50997ec6d97b8e5`
- 검증 브라우저: 사용자가 로그인해 둔 Chrome
- 검증 시각: 2026-07-20 22:06 KST

## 실사용 재현

1. `http://localhost:18080/chat`에 로그인된 상태로 접속했다.
2. 새 채팅에서 `4세대 실손`이 선택된 것을 확인했다.
3. `4세대 자기공명영상진단(MRI/MRA)의 연간 보상한도는?`을 입력했다.
4. 최종 말풍선은 `제공된 문서에서 확인되지 않습니다.`로 종료됐다.

기대 결과는 4세대 직접 약관 근거에 따른 연간 300만원 한도 안내다. 후보 worktree의 직접 `/api/v2/query` smoke 결과와 실제 UI 요청 경로가 일치하지 않으므로 후속 UAT를 중단한다.

## Developer 조사 범위

- 실제 UI 요청의 API 경로, payload, 세대 값, intent, session/history 값을 audit와 함께 추적한다.
- UI 번들, proxy/API, 실행 컨테이너·마운트와 보호 메인 커밋의 일치 여부를 확인한다.
- 세대 필드 누락·변환, 대체 endpoint, 이전 번들, 대화 이력 오염, exact-query route 우회를 각각 확인한다.
- 원인을 특정하기 전에는 수정하지 않는다.

## 변경 경계

- `muldae` 격리 worktree에서만 구현한다.
- 보호 메인 직접 수정, 통합, 재시작, push를 금지한다.
- GraphDB, ontology, active 계산 룰, manifest, 원본 문서, 운영 DB 및 사용자·채팅 데이터를 변경하지 않는다.
- MRI 문장 전용 하드코딩을 금지하고 일반화된 요청 계약 또는 검색 경계만 최소 수정한다.
- 계산/claim intent 경계, 공개 source snippet 180자, hover와 원본 PDF 클릭 계약을 보존한다.

## 재검토 게이트

Developer 후보가 준비되면 Review Team이 다음을 독립 확인한다.

- 실제 UI payload와 동일한 회귀 테스트
- 4세대 300만원, 5세대 200만원 반복, 4/5 비교
- `5세대 MRI 연간 보장되나요?` 및 `5세대 MRI 보상한도 지급 여부는?`의 claim/coverage 경계
- 내부 태그 미노출
- source snippet 180자 및 hover/click PDF 회귀
- 범위 외 데이터·룰·Graph 변경 부재
