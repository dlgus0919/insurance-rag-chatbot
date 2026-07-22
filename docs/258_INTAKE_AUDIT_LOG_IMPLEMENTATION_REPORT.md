# 258. Intake Audit Log Implementation Report

## Summary

관리자 문서 intake job에 job별 `audit_log.jsonl`을 추가하고, 관리자 페이지에서 현재 단계, 차단/실패 이유, 다음 조치를 확인할 수 있게 했다.

이번 변경은 운영 감사와 실무자 안내를 위한 기록 계층이다. 보험 지급 판단, 공제율, 한도, 보상액 산정 규칙을 새로 추가하지 않았고, active 지식 자산을 직접 변경하지 않는다.

## Changed Files

- `src/ingest/intake_store.py`: intake job별 audit event append/read 기능 추가.
- `src/ingest/intake_runner.py`: 스캔 PDF 차단, 미지원 파일, 후보 추출 실패 경로에 block reason, next action, 세부 정보를 기록.
- `src/api/routes/knowledge.py`: 관리자 권한으로 job별 audit log를 조회하는 API 추가.
- `src/api/schemas/knowledge.py`: audit response schema 추가.
- `frontend/js/modules/admin.js`: 관리자 지식 확장 화면에서 audit detail 조회와 표시 기능 추가.
- `frontend/js/config.js`, `frontend/html/admin.html`, `frontend/js/pages/admin.js`, `frontend/css/admin.css`, `frontend/dist/app.min.js`: 관리자 UI 연결과 빌드 산출물 갱신.
- `tests/test_intake_store.py`, `tests/test_intake_runner.py`, `tests/test_api_admin_knowledge.py`, `tests/test_admin_knowledge_frontend.mjs`: 회귀 테스트 추가 및 갱신.

## Behavior

- 새 intake job이 생성되면 `created` audit event가 기록된다.
- job 상태가 바뀌면 `updated`, `blocked`, `failed`, `completed` 성격의 audit event가 append-only 방식으로 기록된다.
- 스캔 PDF처럼 현재 자동 처리하지 않는 입력은 후보 추출로 넘어가지 않고, 차단 이유와 다음 조치를 남긴다.
- 원본 파일 누락, Excel staging 미연결, 미지원 파일 형식도 차단/실패 이유와 다음 조치를 남긴다.
- 후보 추출 실패는 job 상태를 `failed`로 만들고, 예외 타입과 메시지를 audit detail에 남긴다.
- 관리자 페이지의 지식 확장 영역에서 각 job의 `상세` 버튼을 누르면 현재 단계, 이유, 다음 조치, 세부 정보를 볼 수 있다.

## Guardrail Check

- 특정 상품의 정답 수치, 지급 판단, 공제율, 한도 값을 추가하지 않았다.
- 감사 로그는 운영 상태 설명과 조치 안내만 담당한다.
- 스캔 PDF OCR 자동화는 추가하지 않았다.
- 온톨로지 후보, active rule, GraphDB, 검색 인덱스 적용 경로를 자동으로 우회하지 않았다.

## Validation

- `.venv/bin/python -m pytest tests/test_intake_store.py tests/test_intake_runner.py tests/test_api_admin_knowledge.py tests/test_document_intake_detector.py tests/test_file_intake_planner.py -q`
  - Result: `24 passed, 1 warning in 0.28s`
  - Warning: `passlib`의 `crypt` deprecation warning. 이번 변경과 직접 관련 없음.
- `node --test tests/test_admin_knowledge_frontend.mjs`
  - Result: `8 passed`
  - Warning: Node의 `MODULE_TYPELESS_PACKAGE_JSON` 경고. 기존 package type 설정 관련이며 이번 변경과 직접 관련 없음.
- `bash -n ops/bin/insurance-rag-desktop-launcher`
  - Result: passed.
- `cd frontend && npm run build`
  - Result: passed. `frontend/dist/app.min.js` 갱신.
- `git diff --check`
  - Result: passed.

## Remaining Risks

- 전체 audit log 검색, 기간 필터, 다운로드 기능은 아직 없다.
- Excel staging 연결 전에는 Excel 입력이 `excel_staging_not_ready`로 차단되며, 실제 Excel 구조화 후보 생성은 후속 작업이다.
- audit detail은 job별 로컬 JSONL을 읽는 구조라 대량 job 환경에서는 별도 집계 인덱스가 필요할 수 있다. 현재 범위에서는 과잉 구현을 피하기 위해 추가하지 않았다.
