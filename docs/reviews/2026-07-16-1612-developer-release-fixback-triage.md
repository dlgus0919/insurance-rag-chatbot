# Developer Release/Fixback Triage

- Timestamp: 2026-07-16 16:12 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f` (`Developer`, idle)
- Review Team thread: 현재 project root와 일치하는 기존 thread를 찾지 못함
- Scope/spec: 2026-07-16 Developer 보완 조치 통합 검토, 이상 없는 변경의 push/메인 앱 반영, 미완료 항목 fixback

## Reported

- Developer는 수술종수 질의와 HIRA 수가 조회를 분리하고, ICD 진단코드와 `수술` 접미사 오탐을 차단했다고 보고했다.
- 탈모 질문은 세대별 직접 약관 조항을 사용해 일반·질병성 탈모는 `추가 확인 필요`, 노화성 탈모는 `조건부 보상 제외 조항 확인`으로 분기한다고 보고했다.
- 로그인·채팅·관리자 화면은 실행 중인 LLM만 표시하고 정적 EXAONE 노출을 제거했다고 보고했다.
- DGX 범위별 Python `167 passed`, Node `9 passed`, 프런트엔드 빌드 성공, 전체 pytest `918 passed, 1 failed`를 보고했다. 단일 실패는 보호된 DGX 기준선에서도 재현된 보험금 계산 기대값 불일치라고 확인했다.
- 운영 active manifest와 GraphDB, stage/commit/push/운영 배포는 수행하지 않았다고 명시했다.

## Observed

- 현재 로컬 작업 트리는 `a7e0867` 위에 28개 이상 파일의 미커밋 변경을 보유하고 있다.
- 독립 focused Python 검증은 `105 passed`, 프런트엔드 Node 검증은 `9 passed`, `frontend` 번들은 성공했다. `git diff --check`도 통과했다.
- HIRA 직접 조회 게이트는 사용자 질문의 명시적 수가 의도만 검사하며, GraphDB 안내 문구나 `N39.3`만으로 조회를 시작하지 않는다.
- 탈모 canonical 답변, 세대 필터, 직접 근거 및 추가 질문 렌더링에 대한 코드와 회귀 테스트가 존재한다.
- 현재 라이브 DGX 터널 `GET http://127.0.0.1:18080/api/system/models`는 다음 두 모델을 동시에 반환한다.
  - `sglang:qwen3-next-80b-a3b-instruct-fp8`
  - `ollama:exaone3.5:7.8b`
- 따라서 로그인 화면의 EXAONE 노출은 브라우저 화면만의 문제가 아니라 운영 백엔드 응답에서도 재현되는 미해결 결함이다.
- 라이브 로그인 HTML의 `last-modified`는 2026-05-27로 확인되어, 오늘의 프런트엔드 변경이 운영 정적 자산에 아직 반영되지 않은 정황과 일치한다.
- Developer 보고서가 명시했듯 탈모 지식은 운영 active manifest와 GraphDB에 아직 적용되지 않았다. DGX가 active manifest를 사용 중이면 소스 `concepts.json`만 배포해서는 실사용 답변이 바뀌지 않는다.

## Not Verified

- DGX Ollama의 `/api/ps` 실제 응답과 앱이 사용하는 Ollama endpoint/환경 변수의 일치 여부.
- 기존 브라우저 프로필의 localStorage를 포함한 로그인 화면 재검증.
- 운영 active manifest 승인·적용, GraphDB 재빌드 및 실제 4·5세대 탈모 질의 결과.
- 오늘 변경의 commit/push, DGX 보호된 메인 저장소 fast-forward, 앱 서비스 재시작 및 실사용 smoke.

## Findings

1. 수술종수/HIRA/용어 경계 보완은 코드와 focused 회귀 기준으로 승인 가능하다.
2. 탈모 보완은 코드 수준으로 승인 가능하지만 운영 지식 반영 전제가 남아 있어 배포 완료로 판정할 수 없다.
3. EXAONE 비노출은 라이브 API에서 실패하므로 반드시 fixback 후 운영 검증해야 한다.
4. 전체 pytest의 기존 보험금 계산 실패 1건은 이번 변경으로 새로 생긴 회귀는 아니지만, 릴리스 보고에 기준선 위험으로 계속 명시해야 한다.

## Decision

`DEVELOPER_FIXBACK`

## Dispatch

- Developer에게 EXAONE 라이브 원인 규명, 운영 active manifest 적용, 전체 검증, 의도한 파일만 commit/push, DGX 메인 앱 반영과 라이브 재검증을 하나의 통합 지시로 전달한다.
- 모든 필수 검증이 끝나기 전에는 부분적으로 성공한 변경만 운영에 배포하지 않는다.
