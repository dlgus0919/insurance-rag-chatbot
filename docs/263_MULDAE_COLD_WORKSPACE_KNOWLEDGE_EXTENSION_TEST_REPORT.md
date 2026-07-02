# 263. Muldae Cold Workspace Knowledge Extension Test Report

## 1. 목적

이 문서는 DGX 메인 저장소의 `v1.0.16` 확장 로직을 `muldae` 독립 워크스페이스에서 cold 상태로 검증한 결과를 정리한다.

검증 목표는 다음과 같다.

- 관리자 페이지 기반 문서 추가 플로우가 cold workspace에서도 동작하는지 확인
- 스캔 PDF가 자동 OCR/후보 추출 단계로 넘어가지 않고 차단되는지 확인
- 텍스트 레이어가 있는 디지털 PDF가 문서 처리 상태로 등록되는지 확인
- 온톨로지/액티브 룰 후보 검토 화면이 관리자 UI에서 접근 가능한지 확인
- 테스트 중 active ontology/rule manifest 및 index가 임의 변경되지 않는지 확인

이번 검증에서는 LLM 서버를 새로 기동하거나 교체하지 않았다.

## 2. 검증 기준

- DGX main repository: `/srv/shared/projects/insurance-rag-chatbot`
- Muldae cold workspace: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test`
- 검증 커밋: `f6390b9`
- 검증 버전: `v1.0.16`
- 결과 산출물:
  - `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test/reports/muldae_cold_workspace/20260702-141414`

테스트는 DGX main을 source-of-truth로 두고, 실제 실행은 `muldae` 사용자 워크스페이스에서 수행했다. 이 구조는 메인 저장소의 active 데이터와 운영성 산출물을 직접 오염시키지 않기 위한 것이다.

## 3. 실행 결과 요약

| 구분 | 결과 | 비고 |
| --- | --- | --- |
| Python knowledge extension 테스트 | 통과 | `27 passed, 1 warning` |
| Admin frontend 테스트 | 통과 | `10 passed, 0 failed` |
| Python compile/import 경계 확인 | 통과 | syntax/import error 없음 |
| API health | 통과 | `{"status":"ok"}` |
| 테스트 admin 로그인 | 통과 | isolated users file 사용 |
| 스캔 PDF 차단 | 통과 | `blocked_scanned_pdf` |
| 디지털 PDF 처리 | 통과 | `waiting_review` |
| 온톨로지 후보 API | 통과 | `0`건, JSON 응답 정상 |
| 룰 후보 API | 통과 | `0`건, JSON 응답 정상 |
| 관리자 UI 브라우저 검증 | 통과 | 로그인, 관리자, 지식 확장, 문서 추가, 후보 검토 확인 |
| active manifest/index 안전성 | 통과 | tracked active/index 변경 없음 |
| 테스트 서버 정리 | 통과 | `18081` listener 없음 |

## 4. 주요 검증 내용

### 4.1 Cold workspace 상태 확인

`muldae` 워크스페이스는 `origin/master`와 같은 `f6390b9` 커밋으로 맞춘 뒤 테스트했다.

초기 cold 상태에서 다음 runtime path는 없거나 테스트 전용으로 격리되어 있었다.

- `data/intake/jobs`
- `data/ontology/review/candidates.jsonl`
- `data/rules/review/candidates.jsonl`
- `data/ontology/concepts.active.json`
- `data/rules/active_rule_manifest.json`
- `data/muldae_cold_test/insurance_chat.db`

### 4.2 정적 테스트

다음 테스트 로그가 run directory에 보존되어 있다.

- `pytest_static.log`
- `node_admin_frontend.log`
- `py_compile.log`

결과는 모두 통과였다.

### 4.3 스캔 PDF 차단

텍스트 레이어가 없는 테스트 PDF는 `blocked_scanned_pdf` 상태로 차단되었다.

확인된 차단 사유는 다음과 같다.

```text
scanned_pdf_text_layer_missing
```

관리자 UI에는 “스캔 PDF OCR 자동화를 수행하지 않으므로 후보 추출과 DB 반영을 진행하지 않는다”는 취지의 안내가 표시되었다. 이는 현재 정책인 “스캔 PDF/OCR 자동화는 수행하지 않고, 텍스트 레이어 유무만 자동 판독한다”는 요구와 일치한다.

### 4.4 디지털 PDF 처리

텍스트 레이어가 있는 테스트 PDF는 `waiting_review` 상태로 등록되었다.

이번 테스트용 PDF는 매우 작은 synthetic 문서였기 때문에 온톨로지 후보와 룰 후보는 모두 0건이었다.

이 결과는 후보 생성 품질 결함을 의미하지 않는다. 후보 생성 품질은 실제 자사 약관 PDF를 사용해 별도 검증해야 한다.

### 4.5 관리자 UI 검증

headless Chromium 기반 브라우저 검증에서 다음 화면 요소를 확인했다.

- 로그인 화면
- 관리자 화면
- 지식 확장 탭
- 문서 추가 섹션
- 문서 처리 상태 섹션
- 문서 처리 감사 로그 섹션
- 후보 검토 섹션

UI evidence는 다음 파일로 보존되어 있다.

- `ui_login.png`
- `ui_admin.png`
- `ui_knowledge.png`
- `ui_validation.json`
- `ui_knowledge_text.txt`

### 4.6 안전성 확인

테스트 후 active ontology/rule manifest 및 index 관련 tracked file 변경은 없었다.

따라서 이번 테스트는 “문서 추가와 후보 검토 대기 상태까지의 확장 플로우”를 검증했으며, 운영 DB 재빌드나 active manifest promotion은 수행하지 않았다.

## 5. 발견된 잔여 이슈

### 5.1 API 응답 shape 개선 필요

스캔 PDF 차단 사유는 nested detail에는 존재하지만, top-level `block_reason`은 비어 있다.

현재 UI 안내와 차단 동작은 정상이다. 다만 API 소비자가 차단 사유를 더 단순하게 읽을 수 있도록 top-level에도 같은 값을 제공하는 개선이 가능하다.

### 5.2 실제 약관 기반 후보 품질 검증 필요

이번 synthetic digital PDF는 후보 생성 smoke test에는 충분하지만, 온톨로지/룰 후보 품질을 평가하기에는 작고 단순하다.

다음 단계에서는 실제 자사 약관 PDF를 관리자 문서 추가 플로우로 넣어 다음을 확인해야 한다.

- 후보가 실제로 생성되는지
- 후보 설명이 실무자에게 이해 가능한지
- 승인/거절/보류 후 active 반영 경로가 정상인지
- GraphDB/검색 index rebuild까지 연결 가능한지

### 5.3 Muldae cold workspace embedding cache 경고

`uvicorn.log`에는 `BAAI/bge-m3` 로컬 캐시 누락에 따른 RAG prewarm warning이 남았다.

이번 테스트 범위는 관리자 지식 확장 플로우였기 때문에 해당 warning은 테스트를 막지 않았다. 다만 muldae 환경에서 일반 질의까지 검증하려면 embedding/model cache 또는 offline dependency 준비 상태를 별도로 맞춰야 한다.

## 6. Subagent Review 결과

Subagent 기반 검토를 2회 수행했다.

첫 검토에서는 다음 보완 사항이 발견되었다.

- UI live browser validation 증거 부족
- raw static test log 미보존
- cookie artifact 권한이 과하게 열려 있음
- `validation.json`과 `run_summary.md`의 잔여 이슈 분류 불일치

보완 후 재검토 결과는 `APPROVED`였다.

최종 확인된 사항은 다음과 같다.

- `known_issues`와 `Residual Issues` 정합성 확보
- PID 처리 문제는 잔여 이슈가 아닌 실행 메모로 분리
- 정적 로그, API 결과, UI 검증 플래그, 후보 0건 상태 통과
- cookie artifact 권한 `600`
- 테스트 포트 `18081` 정리 완료

## 7. 결론

관리자 UI 기반 2단계 지식 확장 플로우의 기본 골격은 cold workspace에서도 동작한다.

현재 확인된 동작은 다음 수준까지다.

1. 관리자가 문서를 추가한다.
2. 시스템이 스캔 PDF와 디지털 PDF를 구분한다.
3. 스캔 PDF는 OCR 자동화 없이 차단하고 안내한다.
4. 디지털 PDF는 처리 상태에 등록하고 후보 검토 단계로 연결한다.
5. 후보 검토 UI는 관리자 페이지에서 접근 가능하다.
6. 이 과정에서 active manifest/index는 자동 변경되지 않는다.

따라서 다음 개발 단계는 “실제 약관 PDF를 이용한 후보 생성 품질 검증”과 “승인된 후보를 active manifest/index/GraphDB에 반영하는 end-to-end 운영 테스트”다.

이번 커밋에서는 테스트 결과 보고서와 실행 계획 문서를 함께 저장해, DGX main에 남아 있던 테스트 계획 untracked 상태도 정리한다.
