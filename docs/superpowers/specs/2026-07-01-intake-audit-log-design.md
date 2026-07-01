# Intake Audit Log Design

## Purpose

문서 추가 기반 지식 확장 흐름에서 운영 감사와 장애 추적을 우선 지원한다. 관리자 페이지에서는 감사 로그를 사람이 이해할 수 있도록 현재 단계, 차단/실패 이유, 다음 조치를 간결하게 보여준다.

## Decision Summary

- 저장 방식은 기존 review log 패턴과 같은 append-only JSONL을 사용한다.
- 정상 흐름은 핵심 상태 전환만 기록한다.
- 실패, 차단, 오류 이벤트에는 원인과 다음 조치에 필요한 세부 정보를 기록한다.
- 관리자 UI는 선택한 intake job의 로그만 보여주는 MVP로 시작한다.
- 전체 로그 검색, 기간 필터, 통계 화면은 후속 요구가 생길 때 추가한다.

## Storage Model

각 intake job 디렉터리에 현재 상태와 감사 로그를 분리해 저장한다.

```text
data/intake/jobs/<job_id>/job.json
data/intake/jobs/<job_id>/audit_log.jsonl
```

`job.json`은 현재 상태 조회를 위한 단일 source of truth다. `audit_log.jsonl`은 상태 전환 이력과 실패 원인을 보존하는 append-only 로그다.

전체 job을 가로지르는 전역 감사 로그는 이번 범위에 넣지 않는다. 관리자 페이지는 job 목록에서 특정 job을 선택한 뒤 해당 job의 로그를 조회한다.

## Event Schema

각 JSONL row는 다음 필드를 가진다.

```json
{
  "event_id": "uuid",
  "job_id": "intake_...",
  "timestamp": "2026-07-01T00:00:00.000000+00:00",
  "actor": "admin",
  "from_status": "uploaded",
  "to_status": "detecting_document_type",
  "event_type": "status_changed",
  "message": "PDF 텍스트 레이어를 검사합니다.",
  "block_reason": null,
  "next_action": null,
  "details": {}
}
```

필드 의미:

- `event_id`: 로그 row 식별자.
- `job_id`: intake job 식별자.
- `timestamp`: UTC ISO timestamp.
- `actor`: 작업 수행자. 시스템 내부 단계는 `system`을 사용할 수 있다.
- `from_status`, `to_status`: 상태 전환 전후 값.
- `event_type`: `status_changed`, `blocked`, `failed`, `applied` 등 최소 분류.
- `message`: 관리자 UI에 표시할 짧은 설명.
- `block_reason`: 실패/차단 이벤트에서만 채운다.
- `next_action`: 실패/차단 이벤트에서 관리자가 수행할 다음 조치.
- `details`: 실패/차단 진단에 필요한 최소 구조화 정보.

## Block Reason Policy

`IntakeBlockReason`은 운영 감사/로그 분류를 위한 enum으로 유지한다. 우선 다음 사유를 사용한다.

- `scanned_pdf_text_layer_missing`: PDF에 텍스트 레이어가 없거나 부족함.
- `ocr_file_unsupported`: 이미지 또는 스캔 문서라 OCR이 필요하지만 현재 자동 OCR 범위가 아님.
- `unsupported_file_type`: 지원하지 않는 파일 형식.

후속 구현에서 후보 추출 실패, active 적용 실패, GraphDB rebuild 실패를 추가할 수 있다. 단, 사유값은 UI 문구가 아니라 안정적인 machine-readable code로 유지한다.

## Status Policy

`IntakeJobStatus`는 job lifecycle의 현재 단계를 표현한다. 현재 동기 실행이라 모든 상태가 즉시 쓰이지 않더라도 다음 확장을 위해 유지한다.

- 업로드/판독/staging/후보 생성/검토 대기는 현재 흐름에서 사용한다.
- 적용/GraphDB rebuild/완료 상태는 승인 항목 적용을 job lifecycle에 연결할 때 사용한다.
- 실패/차단 상태는 감사 로그의 `block_reason`과 함께 관리자 안내에 사용한다.

상태값은 진행률 UI 자체가 아니라 감사 로그 해석의 기준값이다.

## Admin UI

관리자 페이지 `지식 확장` 탭에서 job별 감사 로그를 볼 수 있게 한다.

MVP 표시 항목:

- 현재 단계: `job.status`와 최신 audit event 기반 표시.
- 막힌 이유: 최신 실패/차단 event의 `block_reason`을 실무자 문구로 변환.
- 다음 조치: 최신 실패/차단 event의 `next_action`.
- 처리 이력: 핵심 상태 전환 목록.

예시:

```text
현재 단계: 스캔 PDF 차단
막힌 이유: PDF에 텍스트 레이어가 없거나 부족합니다.
다음 조치: 텍스트 레이어가 포함된 디지털 PDF를 업로드하세요.

처리 이력
- 업로드됨
- PDF 텍스트 레이어 검사
- 스캔 PDF로 차단됨
```

전체 감사 로그 검색, 기간 필터, CSV export는 이번 범위가 아니다.

## 000 Guardrail Alignment

- 로그는 지식 값을 생성하거나 수정하지 않는다.
- 실패 사유와 다음 조치는 운영 안내이며, 보험 지급 판단이나 공제율 값을 코드화하지 않는다.
- 스캔 PDF/OCR 자동화는 여전히 수행하지 않는다.
- active ontology/rule 변경은 기존 승인 흐름 뒤에서만 수행한다.

## Minimal Implementation Shape

후속 구현은 작은 함수 추가로 충분하다.

- `IntakeJobStore.append_audit_event(...)`
- `IntakeJobStore.load_audit_events(job_id)`
- `update_job(...)`에서 상태 전환 이벤트 자동 append
- 차단/실패 경로에서 `block_reason`, `next_action`, `details` 전달
- 관리자 API `GET /admin/knowledge/intake/jobs/{job_id}/audit`
- 관리자 UI의 job 상세 로그 표시

새 DB, 큐, 전역 검색 인덱스는 만들지 않는다.
