# 대화형 근거 확인 Fixback 2 구현 보고서

- 작성일: 2026-07-19
- 범위: prepared registry 주입, GraphDB 읽기 전용 무결성, safe runtime root 소비
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 작업 위치: DGX 격리 작업공간

## 결론

Release B의 safe baseline 경로가 prepared ontology와 다른 GraphDB를 만들거나,
검증하지 않은 GraphDB를 runtime에서 사용하는 경로를 최소 범위로 차단했다. 명시한
safe runtime root가 있으면 ontology registry와 GraphDB가 같은 published artifact를
사용하며, 누락 또는 손상 시 raw/base로 fallback하지 않고 시작 단계에서 실패한다.

운영 active ontology, provenance, GraphDB, 검색 인덱스, 계정, 대화, 로그, 서비스는
변경하지 않았다. pending correction 6건도 승인하거나 적용하지 않았다.

## 구현 내용

### 1. prepared registry 기반 Graph 생성

- safe-baseline CLI의 `prepare`가 Graph 생성기에 prepared registry를 넘기고 strict
  모드를 강제한다.
- 따라서 raw/base 전체 또는 임의 registry가 Graph seed에 섞이는 경로를 막는다.

### 2. GraphDB 읽기 전용 무결성 검증

- prepared release 검증은 SQLite GraphDB를 읽기 전용으로 열어 필수 테이블,
  내부 manifest, 실제 노드·관계·근거·별칭 수를 확인한다.
- 외부 graph manifest, DB 내부 manifest, prepared ontology metadata가 모두 같은
  hash와 count를 가리키는지 비교한다.
- DB 손상, 필수 테이블 누락, 내부·외부 manifest 불일치는 publish 전과 runtime load
  모두에서 fail-closed 처리한다.

### 3. 명시 safe runtime root의 실제 소비

- `INSURANCE_SAFE_BASELINE_RUNTIME_ROOT`가 설정되면 기본 ontology registry와 RAG의
  Graph 경로가 그 root 아래 artifact만 사용한다.
- safe runtime artifact가 없거나 GraphDB가 손상되면 raw ontology 또는 기존 GraphDB로
  조용히 대체하지 않는다.

## 전체 입력 CLI 종료 원인 분리

전체 입력 경로는 실제 청크 5,781건과 표준코드 527,679행을 GraphDB로 적재한다.
처음 실행은 `prepare` Python 명령까지 전달된 것이 shell trace로 확인됐다. 다만 이전
보조 스크립트가 `set -e`로 즉시 종료되고 종료 trap에서 임시 root를 삭제해 Python의
exit code와 stderr를 보존하지 못했다.

동일 시각대에는 GPU 메모리 부족 기록이 반복됐고 시스템 가용 메모리도 약 8.4GiB였다.
반면 CPU OOM killer 기록과 해당 cgroup의 OOM kill counter는 확인되지 않았다. 따라서
명령 전달 문제는 아니지만, 이 CLI가 GPU OOM 또는 CPU OOM으로 종료됐다고 확정할 수는
없다. GPU 자원 압박은 강한 동시 환경 증거로만 기록한다. 지시에 따라 전체 재빌드는
반복하지 않았다.

## 최소 실제 산출물 대체 검증

실제 raw ontology와 base lock을 사용해 55개 raw 중 49개 trusted, 6개 pending
correction이라는 safe baseline을 만들었다. Graph 생성 입력은 실제 청크 1건과 빈
표준코드 스키마로 제한했다. 이 검증은 아래 제어 계약을 확인하지만 전체 데이터 품질
또는 전체 Graph 규모는 검증하지 않는다.

| 계약 | 결과 |
| --- | --- |
| prepare와 verify | trusted 49개, 정상 완료 |
| 손상된 GraphDB verify | 거부 |
| 손상 상태 publish | 거부, runtime tree 불변 |
| 복구 후 publish | 정상 완료 |
| safe root 기본 registry/RAG 해석 | valid, profile 0, safe Graph 경로 사용 |
| rollback | 이전 runtime tree 복원 |

검증하지 못한 항목은 전체 5,781 청크·527,679 표준코드 행의 Graph 적재 시간, 메모리
사용량, 최종 node/edge count와 운영 root의 controlled publish다. 이는 별도 자원 여유
확보와 명시적 운영 승인 아래에서만 수행해야 한다.

## 검증 결과

| 검증 | 실제 결과 |
| --- | --- |
| prepared registry strict mode, Graph manifest/DB, safe runtime focused | `48 passed` |
| 대화·근거·수가·수술종수·보험금·세션·관리자 Graph focused | `222 passed, 1 warning` |
| Node 프런트엔드 회귀 | `15 passed` |
| 프런트엔드 build 및 JavaScript syntax | 통과 |
| 격리 Playwright (`chat.spec.js`, `isolated-claim-flow.spec.js`) | `13 passed` |
| 전체 pytest (임시 DB·계정·로그 경로) | `1109 passed, 3 warnings` |
| raw/base ontology sync | 의도된 `quarantined` 차단, exit 1 |
| 임시 safe baseline ontology sync | 49 concepts, 통과 |
| `git diff --check` | 통과 |

격리 Playwright는 임시 루프백 포트, 임시 SQLite DB, 임시 테스트 계정과 읽기 전용
표준코드 참조만 사용했다. 정식 테스트 실행을 위해 보호 checkout의 기존 Playwright
의존성을 읽기 전용 심볼릭 링크로 잠시 참조했고, 실행 직후 링크와 모든 임시 root를
제거했다.

## 변경 파일

- `scripts/prepare_ontology_safe_baseline.py`
- `src/config.py`
- `src/ontology/registry.py`
- `src/ontology/safe_baseline.py`
- `src/rag/pipeline.py`
- `tests/test_prepare_ontology_safe_baseline_cli.py`
- `tests/test_safe_baseline.py`
- 기존 Release B의 대화·프런트엔드·회귀 테스트 변경

## 운영 경계와 남은 위험

- 보호 main은 기준 커밋 상태로 clean이며, 이번 작업 중 파일을 수정하지 않았다.
- active manifest/provenance, 운영 GraphDB·인덱스, 운영 DB·계정·대화·로그에 쓰지
  않았고 API/LLM/service를 재시작하지 않았다.
- stage, commit, push, deploy를 수행하지 않았다.
- raw/base의 quarantine 차단은 배포 전 정상 상태다. 운영에서 safe baseline을 실제로
  publish하려면 전체 Graph 입력을 별도 자원 계획으로 검증하고, release artifact와
  rollback 계획을 검토한 뒤 명시적인 운영 승인을 받아야 한다.
