# Developer Handoff Triage

- Timestamp: 2026-07-16 12:31 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f` (`Developer`, idle)
- Review Team thread: 현재 project root와 일치하는 기존 thread를 찾지 못함
- Scope/spec: 직전 HIRA 수가 게이트·기동 중 LLM UI 개선 검토 및 탈모 보상 답변 품질 개선 구현

## Reported

Developer는 직전 작업에서 다음을 보고했다.

- 수술종수 질의가 GraphDB의 일반 `코드` 문구만으로 HIRA 직접 조회를 실행하지 않도록 수정
- 수술명 접미사의 `술`을 음주 후 상해로 오인하지 않도록 수정
- Ollama 설치 목록과 실행 목록을 분리하고 로그인·채팅·관리자 화면에는 실행 중 모델만 표시
- 변경 범위 Python `86 passed`, DGX 격리 범위 `101 passed`, Node `5 passed`, 프런트엔드 빌드 성공
- 전체 pytest `902 passed, 1 failed`; 실패 1건은 수정 전에도 재현된 보험금 계산 기대값 불일치
- 커밋·push 미수행

## Observed

- 현재 `master`, HEAD `a7e0867d071e4a49d33a79020b4c040cf7f61920`이다.
- Developer 변경은 20개 추적 파일 수정과 `docs/269_HIRA_FEE_GATE_AND_RUNTIME_LLM_UI_FIX_REPORT.md` 추가 상태로 아직 미커밋이다.
- 직전 구현 보고서의 변경 파일과 실제 working-tree diff가 일치한다.
- 독립 재검증:
  - `python -m pytest -q tests/test_pipeline.py tests/test_graph_query_planner.py tests/test_ollama_client.py tests/test_llm_factory.py` → `86 passed`
  - `node --test tests/test_frontend_model_selection_sync.mjs tests/test_frontend_assistant_display.mjs` → `8 passed`
  - `npm run build` (`frontend/`) → graph/app 번들 빌드 성공
  - `git diff --check` → 통과
- `data/processed/chunks.jsonl`에는 4세대 자사 약관과 5세대 표준약관 모두 `노화현상으로 인한 탈모`의 조건부 보상 제외 원문이 존재한다.
- 현재 Graph planner에는 탈모 원인·질병성 탈모·노화성 탈모를 구조화하는 개념이나 추가 질문 규칙이 없다.
- 스트리밍 중 모델 원문을 표시한 뒤, renderable Graph payload가 있으면 서버와 프런트엔드가 모델 작성 4개 섹션을 잘라 최종 답변으로 교체한다. 이 때문에 생성 중 보인 유용한 조건 문장이 최종 답변에서 사라질 수 있다.

## Not Verified

- 현재 Mac Python에는 FastAPI DB 테스트 의존성 일부가 없어 `tests/test_api_admin.py`를 독립 재실행하지 않았다. Developer의 DGX `101 passed` 보고만 확인했다.
- 전체 pytest는 이번 triage에서 재실행하지 않았다. Developer가 보고한 기존 실패 1건의 DGX 원본 출력은 재확인하지 않았다.
- `localhost:18080`은 SSH tunnel이므로 실제 DGX 배포 commit과 현재 로컬 working tree의 동일성은 확인하지 않았다.
- 운영 브라우저에서 로그인·채팅·관리자 모델 노출을 직접 재검증하지 않았다.
- 문제 응답의 raw model stream은 저장되지 않아 사용자가 본 정확한 임시 문장은 복원하지 못했다.

## Findings

### P1 — 탈모 원인 구분과 정확 약관 근거가 최종 답변 계약에 없음

- Evidence: `data/processed/chunks.jsonl:2458`, `data/processed/chunks.jsonl:5454`, `src/graph/query_planner.py:218`, `src/api/rag_service.py:818`, `frontend/js/pages/chat.js:758`
- 일반 탈모 질의는 방문 구분·증빙만 질문하고, 노화성/질병성/치료 부작용 원인을 구조화하지 않는다.
- 검색된 정확 조항보다 generic `claim_condition_review` 경로가 답변을 지배하고, 모델이 생성한 구체 조건은 후처리에서 제거될 수 있다.
- Required resolution: 원인·치료 목적·일상생활 지장·급여/비급여 조건을 구조화하고, 직접 약관 근거를 canonical decision summary와 clarification payload로 전달한다. 내부 추론 노출로 해결하지 않는다.

### P2 — 띄어쓰기 없는 정상 음주 표현 회귀

- Evidence: `src/ontology/registry.py:56`
- `술을 마시고`, `술 먹고`는 인식하지만 `술먹고`, `술마시고`는 음주 표현으로 인식하지 못한다. 수술명 접미사 차단은 유지하면서 흔한 무공백 표현도 인식해야 한다.
- Required resolution: 문맥형 정규식과 회귀 테스트를 추가한다.

### P2 — 모든 의료 코드가 HIRA 직접 조회 게이트를 열 수 있음

- Evidence: `src/rag/pipeline.py:282`, `src/rag/pipeline.py:477`
- `_has_explicit_hira_fee_intent()`가 광범위한 `extract_code_terms()` 결과를 사용하여 `N39.3` 같은 진단코드도 HIRA 수가 직접 조회 대상으로 판정한다.
- Required resolution: HIRA 코드 형식과 진단코드를 구분하거나, 명시적 수가 의도가 없는 ICD 질의는 HIRA 직접 조회를 실행하지 않도록 테스트와 게이트를 정밀화한다.

## Decision

`DEVELOPER_FIXBACK`

새로 승인된 탈모 개선 구현이 필수 deliverable이고, 직전 패치에도 최소 보완점 두 건이 확인되었으므로 Review Team이 아니라 기존 Developer에 한 번의 통합 fixback을 보낸다.

## Dispatch

- Target thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Exact prompt:

```text
프로젝트: /Users/june_kim/Projects/insurance-rag-chatbot
검토 기록: docs/reviews/2026-07-16-1231-developer-handoff-triage.md

현재 working tree에는 당신이 직전에 구현한 HIRA 수가 게이트 및 실행 중 LLM UI 패치가 미커밋 상태로 남아 있습니다. 기존 변경을 되돌리거나 덮어쓰지 말고 그 위에서 최소 범위로 아래 fixback과 탈모 답변 개선을 함께 구현하세요. 커밋·push는 하지 마세요.

[A. 직전 개선 검토 fixback]
1. `술먹고 다쳤다`, `술마시고 넘어졌다`처럼 띄어쓰기 없는 독립 음주 표현도 `음주 후 상해`로 인식하되, `수술/절제술/폐쇄술/이식술` 접미사는 계속 오인하지 않게 하세요.
2. `_has_explicit_hira_fee_intent()`가 `N39.3` 같은 ICD 진단코드만으로 HIRA 직접 조회를 시작하지 않게 하세요. `Q2861`, `AA157` 같은 HIRA 수가코드 또는 `수가/수가코드/심평원/수가표/점수/수술코드`의 명시적 의도는 유지하세요.
3. 위 두 경계에 실패 우선 회귀 테스트를 추가하세요.

[B. 탈모 보상 답변 품질 개선]
1. 데이터 원문을 먼저 확인하세요. 4세대 자사 약관 `약관_ch_002457`과 5세대 표준약관 `표준약관_ch_005453`에는 `업무 또는 일상생활에 지장이 없는 경우`의 `노화현상으로 인한 탈모` 치료 관련 비급여 의료비 보상 제외 근거가 있습니다.
2. Graph/ontology에 최소한 다음 판단 차원을 추가하세요: 노화현상으로 인한 탈모, 의사 진단 질병성 탈모, 치료·약물 부작용 탈모, 치료/미용 목적, 업무·일상생활 지장 여부, 급여/비급여. 일반 `탈모`를 곧바로 보상 제외로 확정하지 마세요.
3. `탈모 보상 가능?`에는 원인이 노화인지, 의사 진단 질병 또는 치료 부작용인지 확인하는 질문이 구조화 `clarification_questions`에 반드시 포함되게 하세요. 진단명/코드, 의사소견, 치료 목적도 필요한 증빙으로 연결하세요.
4. 정확 약관 조항이 검색되면 generic `claim_condition_review`가 그 근거를 무효화하지 않게 하세요. 직접 원문 근거를 canonical decision summary/structured payload로 승격하고, GraphDB 누락만으로 정확 문서 근거를 `검토 필요`로 강등하지 마세요.
5. 선택 실손 세대는 단순 문자열 주입만으로 처리하지 말고 검색 필터·rerank에 반영해 4세대와 5세대가 혼재하지 않도록 하세요. 다만 5세대는 자사 상품 약관과 표준약관의 권위를 구분하여, 자사 5세대 상품 약관이 없으면 그 사실과 표준약관 참고 기준을 함께 표시하세요.
6. exact term `탈모`, `노화현상으로 인한 탈모`를 BM25/lexical 경로에서 보존·우선하고, 핵심 주제어가 없는 상담사례집 청크가 정확 조항보다 앞서지 않게 하세요.
7. 모델 내부 추론이나 임시 4개 섹션을 사용자에게 노출하는 방식으로 해결하지 마세요. 서버가 결론·적용 조건·추가 질문·근거를 구조화하고 프런트엔드는 그 canonical 결과를 렌더링하게 하세요.
8. 생성 중 보인 문장이 final 이벤트에서 사라지지 않게 하세요. raw 모델 템플릿을 먼저 스트리밍했다가 삭제하는 현재 경로를 정리하되, 기존 Graph 패널 중복 방지 기능은 유지하세요.
9. 사용자 답변에 `【claim_condition_review】` 같은 내부 식별자를 노출하지 말고 한국어 라벨을 사용하세요.

[필수 기대 동작]
- `탈모 보상 가능?` → 확정 불가, 원인 구분 질문, 노화성 탈모 조건부 면책 조항 안내
- `노화현상으로 인한 탈모는 보상 가능한가요?` → 선택 세대의 해당 조건과 비급여 보상 제외를 명확히 설명. 일상생활 지장 등 미확인 조건은 분리
- `질병 진단으로 인한 탈모 치료는?` → 노화성 면책을 자동 적용하지 않으며, 그렇다고 보상 가능을 자동 확정하지도 않음
- 동일 세션의 반복 질문에서도 현재 선택 세대를 유지하고 이전 답변의 세대가 오염되지 않음
- 생성 중과 저장·재조회 후의 핵심 결론/추가 질문이 동일함
- 관련 출처만 표시하고 정확 조항 페이지를 포함

[검증]
- planner/ontology/retrieval/postprocess/API/frontend 단위 회귀 테스트를 실패 우선으로 추가
- 직전 HIRA·모델 UI 테스트 전체 재실행
- 가능한 전체 pytest 및 Node 테스트, frontend build 실행
- DGX 격리 workspace에서 4세대/5세대 각각 새 세션으로 위 3개 질문을 실제 Qwen Instruct에 확인
- 운영 LLM 서버 설정, 모델 파일, 계정/대화/로그 데이터는 변경하지 말 것
- 구현 보고서를 docs/에 새 번호로 작성하고 변경 파일, 명령/결과, 미검증, 잔여 위험을 보고할 것
- 완료 표식은 `DEVELOPER_FIXBACK_COMPLETE`로 하고, stage/commit/push는 하지 말 것
```
