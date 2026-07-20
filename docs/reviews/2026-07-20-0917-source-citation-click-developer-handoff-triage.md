# 출처 근거 배지 클릭 복구 Developer 인계

- Timestamp: 2026-07-20 09:17 KST
- Project root: `/Users/june_kim/Projects/insurance-rag-chatbot`
- Baseline: `master` / `3a8b6af06a359b72cbe903dcffc4b24f19c062aa`
- Developer thread: `019eaf4a-6338-7812-bf3b-663df7d83d4f`
- Review Team thread: `019ecf26-a373-7bf2-bc0a-62c13deb349f`
- Scope: UAT 전에 일반 질의 답변의 출처 근거 배지를 클릭하여 인증된 원본 PDF의 인용 페이지를 새 탭 또는 새 창으로 여는 기능만 복구

## Reported

- 실사용에서 근거 배지에 마우스를 올렸을 때 텍스트 청크 미리보기는 정상 동작한다.
- 같은 근거 배지를 클릭했을 때 원본 자료의 해당 페이지를 팝업 또는 새 창으로 여는 기능은 동작하지 않는다.
- 사용자는 UAT 전에 이 기능만 실제로 재작동하도록 요청했다.

## Observed

- `frontend/js/pages/chat.js`의 `renderSourceBadgeHtml()`은 근거를 클릭 불가능한 `span.src-badge`로 렌더링한다.
- 채팅의 delegated click handler에는 근거 배지 클릭 분기가 없다.
- `frontend/css/chat.css`와 `tests/test_frontend_source_preview_settings.mjs`는 hover 청크 미리보기만 구현·검증한다.
- 공개 응답 payload에는 `filename`, `doc_short`, `page`, `page_end`, `chunk_id`, `snippet`이 남아 있어 원문 문서와 페이지를 식별할 데이터는 보존된다.
- `src/config.py`의 `PDF_SOURCES`가 등록 원문 PDF의 권위 있는 allowlist이지만, 현재 API에는 그 allowlist만을 통해 인증 사용자에게 PDF를 inline 제공하는 경로가 없다.
- 현재 SPA 이력에서도 근거 배지는 처음부터 비클릭 `span`으로 구현되어 있다. 따라서 현재 추적 가능한 코드 기준으로는 최근 답변 로직 변경의 회귀라기보다 SPA 이관 과정에서 원문 열기 경로가 누락된 상태다.

## Not Verified

- 로그인된 운영 브라우저에서 클릭이 아무 동작도 하지 않는 현상은 이번 triage 작성 시점에 자동화로 재현하지 않았다. 사용자의 실사용 관찰과 코드 경로가 서로 일치한다.
- 브라우저별 PDF viewer의 정확한 확대·스크롤 위치는 구현 후 실제 브라우저 검증이 필요하다. 수용 기준은 URL fragment `#page=N`을 포함해 인용 페이지를 요청하는 것이다.

## Findings

1. **P1 — 출처 추적 기능 누락:** 답변의 표시 근거에서 원문 페이지로 이동할 수 없어 UAT의 근거 대조와 실무 검증 흐름이 끊긴다.
2. **P1 — 안전한 문서 제공 경로 부재:** 프론트에서 로컬 파일 경로나 임의 입력 경로를 직접 열면 안 된다. 인증·권한 확인 후 `PDF_SOURCES`에 등록된 PDF만 제공해야 한다.
3. **P2 — 접근성/회귀 검증 부재:** 근거 배지가 클릭 가능한 의미 요소가 아니며 키보드 포커스, 클릭 회귀, 비PDF/불완전 출처의 비활성 처리가 테스트되지 않는다.

## Decision

`DEVELOPER_FIXBACK`

수정 범위는 출처 배지 클릭과 안전한 원문 PDF 제공 경로에 한정한다. RAG 검색, 답변 생성, 온톨로지/GraphDB, 계산 규칙, 모델 설정은 변경하지 않는다.

## Required Implementation Contract

1. 먼저 회귀 테스트를 추가하고 현재 코드에서 실패하는 RED를 확인한다.
2. 인증된 same-origin GET endpoint를 추가한다. 요청한 문서는 경로 문자열을 직접 결합하지 말고 `config.PDF_SOURCES`의 등록 항목과 Unicode 정규화된 basename 또는 `doc_short`로만 매칭한다.
3. endpoint는 `chat.stream`에 준하는 로그인/권한 검사를 수행하고, 등록되어 실제 존재하는 `.pdf`만 `inline`으로 반환한다. 경로 순회, 미등록, 누락, 비PDF 입력은 fail-closed로 거부한다.
4. PDF 근거 배지는 hover 청크 미리보기를 그대로 유지하면서 클릭/키보드로 열 수 있는 의미 요소로 렌더링한다. URL query는 안전하게 인코딩하고 인용 시작 페이지를 `#page=N`으로 붙인다.
5. 새 탭/창은 opener 접근을 차단한다. 비PDF 또는 문서/페이지 식별 정보가 부족한 근거는 기존처럼 미리보기만 제공하고 클릭 가능하게 표시하지 않는다.
6. 기존 표시 label, snippet, page/page_end, 중복 제거 계약을 훼손하지 않는다.
7. frontend CSS에 pointer/focus-visible 상태를 최소 범위로 추가한다.
8. backend 테스트는 성공, 인증 실패, 권한 실패, 미등록 문서, 경로 순회, 누락 파일, 비PDF를 포함한다. frontend 테스트는 hover 보존, 클릭 URL/페이지, 특수문자 인코딩, 비PDF 비활성을 포함한다.
9. focused Python/Node 테스트 후 관련 상위 테스트와 frontend build/syntax 검증을 수행한다.
10. 가능하면 격리된 localhost에서 실제 브라우저로 hover와 click을 검증하고, 열린 URL·HTTP 상태·`Content-Type: application/pdf`를 기록한다.
11. Planner가 수정 중인 아래 UAT 파일은 건드리지 않는다.
    - `reports/practitioner_uat/v1.2.0/README.md`
    - `reports/practitioner_uat/v1.2.0/practitioner_uat_v1_2_0.xlsx`
12. 보호 main/운영 서비스/운영 데이터는 변경하지 않는다. stage, commit, push, merge, tag, restart, deploy를 수행하지 않는다.

## Acceptance Criteria

- hover 시 기존 텍스트 청크 미리보기가 그대로 보인다.
- 클릭 또는 키보드 활성화 시 인증된 same-origin 경로가 새 탭/창으로 열리고 URL에 정확한 인용 페이지 `#page=N`이 포함된다.
- 응답은 등록된 원본 PDF이며 inline `application/pdf`다.
- 임의 경로·미등록 문서·누락 파일·비PDF·비인증 접근은 원문 내용을 노출하지 않는다.
- 일반 질의 답변, 검색 결과, 출처 label/snippet, 온톨로지, GraphDB, 계산 규칙에는 기능 변화가 없다.
- 테스트와 격리 실사용 검증 증거가 남고 작업공간에는 임시 서버/파일/프로세스가 남지 않는다.

Completion marker: `DEVELOPER_SOURCE_CITATION_CLICK_READY_FOR_REVIEW`
