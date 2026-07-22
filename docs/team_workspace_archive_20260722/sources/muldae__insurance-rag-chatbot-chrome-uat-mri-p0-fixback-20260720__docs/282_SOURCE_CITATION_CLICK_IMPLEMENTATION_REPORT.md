# 282. 출처 근거 PDF 열기 구현 보고서

## 범위

일반 질의 답변의 출처 배지에서 기존 청크 미리보기를 유지하면서, 등록된 PDF 근거만 인용 페이지로 새 탭에서 열 수 있게 했다. RAG, 온톨로지, GraphDB, 보험금 계산, LLM 설정은 변경하지 않았다.

## 구현

- `GET /api/chat/sources/pdf`를 추가했다. 인증된 `chat.stream` 권한 사용자만 `doc_short` 또는 PDF 파일명으로 `config.PDF_SOURCES`의 단일 등록 항목을 찾을 수 있다.
- 경로 구분자, 미등록 문서, 누락 파일, 비PDF는 모두 404로 차단한다. 허용된 파일은 `application/pdf`, `Content-Disposition: inline`으로만 제공한다.
- PDF 파일명과 유효한 시작 페이지를 가진 출처 배지는 same-origin 링크로 렌더링한다. URL query는 인코딩하며 `#page=N`, `target="_blank"`, `rel="noopener noreferrer"`를 사용한다.
- 비PDF 또는 페이지가 없는 출처는 기존 `span`과 hover 미리보기로 남긴다. PDF 링크에는 키보드 focus-visible 상태도 추가했다.
- 배포 번들 `frontend/dist/app.min.js`를 다시 생성했다.

## TDD 및 검증

- Backend RED: endpoint 부재 상태에서 성공/인증 회귀가 `2 failed, 1 passed`로 실패했다. 실패 원인은 모두 `404`였다.
- Backend GREEN: `PYTHONPATH=. /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest tests/test_api_source_pdf.py -q` 결과 `3 passed`.
- Frontend RED: PDF badge 링크 회귀가 `5 passed, 1 failed`로 실패했다. 기존 HTML은 `span.src-badge`만 반환했다.
- Frontend GREEN: `node --test tests/test_frontend_source_preview_settings.mjs` 결과 `6 passed`.
- 관련 Python 회귀: `tests/test_api_source_pdf.py`, `test_api_rbac.py`, `test_api_auth_system.py`, `test_public_payloads.py`, `test_pdf_view.py` 결과 `24 passed`.
- 프런트엔드 Node 회귀 9개 파일 결과 `47 passed`; `node --check frontend/js/pages/chat.js` 통과; `npm --prefix frontend run build` 통과.
- `git diff --check` 통과.

## 격리 및 미실행 항목

- 실제 브라우저 클릭 검증은 수행하지 않았다. 보호된 `18080`은 운영 관찰 전용이며, 이번 범위에서는 격리 API 서버를 별도로 기동하지 않았다. 대신 FastAPI `TestClient`로 실제 inline PDF 응답과 인증/권한/차단 경로를 검증했고, Node 렌더링 회귀로 hover·링크·URL fragment 계약을 확인했다.
- 보호 main, 운영 `18080`, Planner checkout, 서비스, 운영 데이터는 변경하지 않았다. stage, commit, push, merge, tag도 수행하지 않았다.
