# 257. 관리자 문서 추가 기반 지식 확장 구현 보고서

## 목적

관리자 페이지에서 신규 약관/엑셀 문서를 추가하고, 문서 기반 후보를 검토한 뒤 승인된 온톨로지/룰만 운영 지식에 반영할 수 있는 2단계 확장 흐름을 구현했다.

이번 범위는 스캔 PDF/OCR 자동화를 포함하지 않는다. 업로드 문서가 스캔본 또는 이미지 계열이면 텍스트 레이어 부족/지원 불가 상태로 차단하고, 후보 추출 및 DB 재빌드 단계로 넘어가지 않는다.

## 핵심 변경

- 관리자 API에 `/admin/knowledge` 라우터를 추가했다.
- 신규 문서 intake job 저장소, 문서 형식 판독, PDF 텍스트 레이어 검사, staging chunk 생성 흐름을 추가했다.
- 온톨로지 후보와 액티브 룰 후보를 관리자 페이지에서 조회, 승인, 보류/거절할 수 있게 연결했다.
- 승인된 후보를 active manifest/rule에 반영하고 GraphDB 재빌드를 호출하는 적용 API를 추가했다.
- 관리자 페이지에 `지식 확장` 탭을 추가했다.
  - 문서 업로드
  - intake 실행
  - 온톨로지 후보 검토
  - 룰 후보 검토
  - 승인 항목 적용
- 실행기에는 기존 온톨로지/룰 검토 fallback을 보존하되, 관리자 페이지 우선 흐름을 안내하도록 문구를 조정했다.
- `fetchAPI`가 `FormData` 요청에서는 JSON `Content-Type`을 강제로 붙이지 않도록 수정했다.

## 000번 원칙 점검

- 특정 상품의 정답 수치, 지급 판단, 공제율, 한도 값을 코드에 새로 하드코딩하지 않았다.
- 문서 추가 후 바로 active ontology/rule을 변경하지 않고, 후보 생성 후 관리자 승인 단계를 거치도록 했다.
- 스캔 PDF/OCR 자동화는 이번 지속 실행 흐름에 넣지 않았고, 텍스트 레이어 없는 문서는 차단한다.
- active manifest/rule 적용은 승인 로그와 후보 상태를 기반으로 수행한다.

## 검증 결과

DGX 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot` 기준으로 검증했다.

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
```

결과: `4 passed`

```bash
bash -n ops/bin/insurance-rag-desktop-launcher
```

결과: 통과

```bash
cd frontend && npm run build
```

결과: `frontend/dist/app.min.js` 생성 성공

```bash
git diff --check
```

결과: 통과

## 남은 작업

- Excel 문서의 구조화 staging 연결은 현재 차단 메시지를 반환하는 상태다.
- 문서 기반 후보 생성 품질은 기존 후보 추출기와 룰 후보 추출기의 성능에 의존한다.
- 관리자 UI는 MVP 형태이며, 후보별 근거 상세 미리보기와 적용 전 영향도 diff는 후속 개선 대상이다.
- 실제 운영 반영 시에는 승인 후보 적용 후 앱 질의/계산 smoke 테스트를 별도로 수행해야 한다.
