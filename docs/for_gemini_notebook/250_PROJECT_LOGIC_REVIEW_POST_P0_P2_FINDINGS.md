# 250. P0~P2 이후 프로젝트 로직 원점 재검토 결과

작성일: 2026-06-18  
기준 저장소: `/srv/shared/projects/insurance-rag-chatbot`  
기준 커밋: `4a557cd feat(project): apply p0 p2 hardening plan`

## 1. 검토 기준

- `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`
- P0~P2 수행 결과 보고서: `docs/247*`, `docs/248*`, `docs/249*`
- DGX master 실제 상태, `.gitignore`, 추적 파일, 운영 스크립트, 테스트 파일
- 현재 실행 중인 LLM 서버는 교체하거나 중단하지 않았다.

## 2. 확인 결과

### 2.1 000번 원칙 위반 여부

현재 추적 파일 기준으로 원본 PDF/XLSX, `.env`, venv, OCR/인덱스 산출물, 병원 영수증 runtime output은 Git 추적 대상이 아니다. `.gitignore`도 해당 항목을 막고 있다.

일반 질의의 `기본 인덱스` 표현은 사용자-facing alias로 남아 있으나, 현재 로직은 `v2_only`로 해석되므로 OCR 제외 경로를 기본값으로 제공하는 위반은 확인되지 않았다.

Streamlit 관련 코드와 문서는 legacy로 남아 있다. README는 FastAPI + SPA가 정식 경로이며 Streamlit은 신규 기능 대상이 아니라고 명시한다. 따라서 이번 검토에서는 삭제나 추가 수정을 하지 않는다.

### 2.2 정보 업데이트 필요

DGX에는 `docs/246_PROJECT_FULL_LOGIC_REVIEW_NEXT_PHASE_REPORT.md`와 `docs/superpowers/plans/`가 미추적 상태로 남아 있었다. 246번 문서는 P0~P2 수행 전 검토 기록이므로 최신 판단 문서처럼 읽히지 않도록 상태 문구를 추가해야 한다.

P0~P2 계획 문서는 실제 수행의 근거이므로 Git 추적 대상에 포함하는 편이 맞다.

### 2.3 운영 점검 도구 결함

`scripts/audit_runtime_artifacts.py`는 기본 실행 시 전체 파일 목록을 모두 JSON으로 출력한다. DGX 저장소에서는 이 출력이 지나치게 커져, 사람이 “얼마나 정리 후보가 있는지”를 빠르게 확인하기 어렵다.

이 문제는 운영 도구의 사용성 결함이며 보험 지식 로직 변경이 아니다. 최소 수정으로 `--summary-only` 옵션을 추가해 category별 용량만 볼 수 있게 한다.

## 3. 이번 작업 범위

1. 246번 문서에 선행 기록이라는 상태 문구를 추가한다.
2. P0~P2 계획 문서를 Git 추적 대상으로 포함한다.
3. runtime artifact 감사 스크립트에 `--summary-only` 옵션을 추가한다.
4. 관련 테스트와 전체 pytest를 DGX에서 실행한다.

## 4. 보류한 항목

- Streamlit legacy 파일 삭제: 사용자가 “업데이트하지 말라”고 한 범위이므로 이번에 건드리지 않는다.
- root의 무시된 PDF/XLSX, `.env`, venv, OCR output 삭제: 명시적 삭제 요청이 아니며 실행 중 작업과 사용자 산출물을 건드릴 수 있으므로 문서화만 한다.
- gpt-oss-120b 관련 추가 삭제: 이미 편입 불가 및 비선택 처리된 상태이며, 이번 요청은 LLM 서버 교체 금지 조건이 있다.

## 5. 결론

P0~P2 패치 이후 즉시 수정해야 할 생산 로직 결함은 발견되지 않았다. 남은 작업은 문서 추적 정리와 운영 감사 스크립트의 출력 축소 옵션 추가가 적절하다.
