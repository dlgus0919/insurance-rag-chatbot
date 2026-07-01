# Admin Document Intake Knowledge Extension Plan

## Purpose

관리자 페이지에서 신규 문서를 추가하고, 자동 생성된 온톨로지/계산 룰 후보를 실무자가 검토한 뒤 승인된 항목만 active 지식 자산에 반영하는 2단계 확장 흐름을 구현한다.

이 문서는 원래 Subagent-Driven 실행용 상세 계획서였으나, 구현이 완료된 뒤 보존 가치가 있는 설계 의도와 후속 확장 지점만 남기도록 축약했다. 상세 구현 결과는 `docs/257_ADMIN_DOCUMENT_INTAKE_KNOWLEDGE_EXTENSION_REPORT.md`를 기준으로 본다.

## Scope

- 관리자 전용 문서 추가 UI와 API를 제공한다.
- 디지털 PDF는 텍스트 레이어를 확인한 뒤 staging chunk와 검토 후보를 생성한다.
- 스캔 PDF와 이미지 파일은 OCR 자동화를 수행하지 않고 차단한다.
- 후보는 바로 active ontology/rule에 반영하지 않고 관리자 승인 단계를 거친다.
- 승인된 후보 적용 시 active ontology/rule 및 GraphDB rebuild 흐름을 호출한다.
- 기존 실행기 기반 온톨로지/룰 검토는 fallback으로 보존하되, 주 흐름은 관리자 페이지로 이동한다.

## Non-Goals

- 스캔 PDF/OCR 자동화.
- 실무자 승인 없는 active 지식 변경.
- 특정 상품의 지급 판단, 공제율, 한도 값을 코드 상수로 추가하는 것.
- 문서 업로드 즉시 운영 DB를 변경하는 것.
- LLM 서버 기동/교체.

## Architecture

### Intake Gate

`src/ingest/document_intake.py`가 업로드 파일의 형식과 PDF 텍스트 레이어를 판정한다.

- PDF: 텍스트 레이어가 충분하면 후보 생성 가능.
- Excel/CSV: 지원 대상으로 분류하되, 현재 구조화 staging 연결 전이므로 후속 작업으로 둔다.
- 이미지/스캔 문서: OCR 필요 경고와 함께 차단.
- 기타 확장자: 지원 불가로 차단.

### Intake Job Store

`src/ingest/intake_store.py`가 `data/intake/jobs/<job_id>/job.json` 기반으로 문서 처리 작업을 추적한다.

현재 구현은 동기 실행이지만, 다음 확장을 위해 상태값을 보존한다.

- 업로드/판독/staging/후보 생성/검토 대기.
- 향후 적용/GraphDB rebuild/완료 상태.
- 차단 사유별 사용자 안내와 감사 로그 연결.

### Intake Runner

`src/ingest/intake_runner.py`가 디지털 PDF에서 staging chunk를 만들고 기존 온톨로지 후보 추출기와 룰 후보 추출기를 호출한다.

이 계층은 active DB를 직접 변경하지 않는다. 생성물은 job별 runtime 경로에 저장되며, 실무자 검토 전까지 운영 자산과 분리된다.

### Admin Knowledge API

`src/api/routes/knowledge.py`가 관리자 전용 API를 제공한다.

- intake job 생성/목록/실행.
- 온톨로지 후보 목록/결정.
- 룰 후보 목록/결정.
- 승인 후보 active 반영.

권한은 `admin.knowledge.read`와 `admin.knowledge.manage`로 분리한다.

### Admin UI

관리자 페이지에 `지식 확장` 탭을 추가한다.

- 문서 업로드.
- 문서 처리 실행.
- 후보 목록 조회.
- 승인/보류/거절 입력.
- 승인 항목 active 반영.

UI는 MVP 수준이다. 후보별 diff, 적용 전 영향도, 상세 근거 뷰는 후속 확장으로 둔다.

### Apply Flow

`src/ingest/knowledge_apply.py`가 승인된 온톨로지 후보와 룰 후보를 active 자산에 적용하고 GraphDB rebuild를 호출한다.

현재는 API 한 곳에서 쓰이지만, 향후 CLI/관리자 감사 로그/부분 실패 보고를 위해 최소 결과 객체 구조를 유지한다.

## 000 Guardrail Alignment

- 지식 값은 코드가 아니라 문서 기반 후보와 실무자 승인으로 반영한다.
- active 변경은 후보 승인 이후에만 수행한다.
- 스캔 PDF/OCR은 지속 실행 경로에 넣지 않고 차단한다.
- 자동 후보 생성은 운영 반영이 아니라 검토 대상 생성까지만 담당한다.
- 특정 보험 상품의 정답 수치나 지급 판단을 코드에 직접 추가하지 않는다.

## Validation Baseline

DGX 메인 저장소 기준으로 다음 검증이 통과했다.

```bash
.venv/bin/python -m pytest \
  tests/test_document_intake_detector.py \
  tests/test_file_intake_planner.py \
  tests/test_intake_store.py \
  tests/test_intake_runner.py \
  tests/test_api_admin_knowledge.py \
  tests/test_knowledge_apply.py \
  tests/test_desktop_launcher_choices.py -q
```

결과: `27 passed, 1 warning`

```bash
node --test tests/test_admin_knowledge_frontend.mjs
bash -n ops/bin/insurance-rag-desktop-launcher
cd frontend && npm run build
git diff --check
```

결과: 통과.

## Retained Extension Hooks

Ponytail 리뷰 이후 다음 항목은 의도적으로 남긴다.

- `IntakeJobStatus`의 일부 미사용 상태값: 향후 비동기 job 진행률, 적용/rebuild 상태 표시, 재시도 UI를 위한 확장 지점.
- `IntakeBlockReason`의 일부 미사용 사유값: 문서 추가 실패 사유를 유형별로 기록하고 관리자 UI/감사 로그에서 필터링하기 위한 확장 지점.
- `_job_response(job)` wrapper: 향후 내부 경로 숨김, 다음 액션 정보, 사용자용 상태 라벨을 API 응답에 추가하기 위한 최소 hook.
- `KnowledgeApplyResult`: 향후 ontology/rule/GraphDB 적용 결과를 API/CLI/로그에서 동일하게 재사용하기 위한 최소 구조.

## Follow-Up Work

1. Intake job lifecycle를 실제 관리자 UI 상태/진행률/재시도 흐름에 연결한다.
2. block reason을 사용자 메시지, 감사 로그, 관리자 필터와 연결한다.
3. Excel/CSV 문서의 구조화 staging 연결을 구현한다.
4. 후보별 근거 상세, 적용 전후 diff, 적용 영향도 preview를 추가한다.
5. active 적용 후 앱 질의/보험금 계산 smoke test를 자동화한다.
