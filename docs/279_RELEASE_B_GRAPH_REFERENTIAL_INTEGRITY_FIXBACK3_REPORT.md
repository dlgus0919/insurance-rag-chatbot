# Release B Graph 참조 무결성 Fixback 3 구현 보고서

- 작성일: 2026-07-19
- 범위: safe baseline Graph artifact의 읽기 전용 참조 무결성 검증
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`
- 작업 위치: DGX 격리 작업공간

## 결론

Graph manifest의 행 수와 hash가 일치하더라도, 노드가 삭제된 관계처럼 실제 참조가
끊긴 GraphDB가 `verify`와 `publish`를 통과할 수 있었다. 공용 Graph artifact 검증에
SQLite 무결성 검사와 참조 검사을 추가해, 두 경로 모두 같은 결함을 fail-closed로
거부하도록 수정했다.

운영 active ontology, provenance, GraphDB, 검색 인덱스, 운영 DB, 계정, 대화, 로그,
서비스는 변경하지 않았다. pending correction 6건도 승인하거나 적용하지 않았다.

## 원인과 최소 수정

기존 Graph 검증은 필수 테이블, 내부/외부 manifest, node/edge/evidence/alias 행 수를
비교했다. 따라서 삭제된 target node를 가리키는 edge처럼 행 수를 맞춘 orphan 참조는
검출하지 못했다.

`src/ontology/safe_baseline.py`의 공용 읽기 전용 Graph 검증 경로에 다음을 추가했다.

1. `PRAGMA integrity_check` 결과가 정확히 `ok` 하나인지 확인한다.
2. `PRAGMA foreign_key_check` 결과가 하나라도 있으면 거부한다.
3. schema에 외래키가 선언되지 않은 `graph_edges.source_evidence_id`는
   `graph_evidence`와의 논리 join으로 별도 검증한다.

`verify`와 `publish`는 기존처럼 같은 prepared-release 검증 함수를 사용하므로, 둘 중
한 경로만 통과하는 우회가 생기지 않는다. 검증은 SQLite read-only 연결만 사용하며
runtime tree에 쓰지 않는다.

## 실패 우선 재현과 회귀

수정 전 `tests/test_safe_baseline.py`에서 5건이 실패했다.

- orphan `graph_edges`의 source/target node 참조
- alias가 존재하지 않는 node를 참조하는 경우
- node evidence가 존재하지 않는 evidence를 참조하는 경우
- edge evidence가 존재하지 않는 edge를 참조하는 경우
- `source_evidence_id`가 존재하지 않는 evidence를 참조하는 경우

수정 후 safe-baseline 단위 테스트는 `22 passed`가 되었고, publish 거부 전후 runtime
tree의 바이트가 동일한지도 고정했다. 정상 Graph artifact는 계속 통과한다.

## 최소 실제 입력 검증

전체 Graph 재빌드는 실행하지 않았다. 실제 raw ontology와 base lock을 사용해 raw 55개,
trusted 49개, pending correction 6개 계약을 유지한 채, 소형 Graph fixture에서 orphan
target node를 만들었다.

| 항목 | 결과 |
| --- | --- |
| raw concepts | 55 |
| trusted concepts | 49 |
| pending corrections | 6 |
| orphan verify | 거부 |
| orphan publish | 거부 |
| publish 실패 후 runtime tree | 바이트 단위 불변 |

이 검증은 실제 raw/base 정책과 새 Graph 참조 무결성 계약을 함께 확인한다. 5,781개
청크와 527,679개 표준코드를 적재하는 전체 Graph 재빌드의 시간, 메모리, 최종 규모는
LLM 서버가 동작하는 현재 환경에서 반복하지 않았다.

## 검증 결과

| 검증 | 실제 결과 |
| --- | --- |
| safe baseline, CLI, Graph builder/store focused | `33 passed` |
| 대화·근거·수가·수술종수·보험금·세션·관리자 Graph focused | `230 passed, 1 warning` |
| 전체 pytest (임시 DB·계정·로그 경로) | `1115 passed, 3 warnings` |
| Node 프런트엔드 회귀 | `45 passed` |
| 프런트엔드 build 및 JavaScript syntax | 통과 |
| 격리 Playwright | `13 passed` |
| raw/base ontology sync | 의도된 `quarantined` 차단, exit 1 |
| `git diff --check` | 통과 |

Playwright는 임시 루프백 포트, 임시 SQLite DB, 테스트 계정, 읽기 전용 표준코드 참조만
사용했다. 검증에 필요한 기존 의존성은 보호 checkout에서 읽기 전용으로 잠시 참조했고,
검증 직후 격리 workspace의 symlink와 모든 임시 root를 제거했다.

## 변경 파일

- `src/ontology/safe_baseline.py`
- `tests/test_safe_baseline.py`
- `docs/279_RELEASE_B_GRAPH_REFERENTIAL_INTEGRITY_FIXBACK3_REPORT.md`

기존 Release B Fixback 2의 dirty 변경은 보존했으며, 이번 Fixback 3은 위 Graph artifact
무결성 경계만 추가한다.

## 운영 경계와 남은 위험

- 보호 main, active manifest/provenance, 운영 GraphDB·인덱스, 운영 DB·계정·대화·로그는
  읽기 전용 확인만 했으며 변경하지 않았다.
- candidate apply, practitioner 승인, GraphDB rebuild, reindex, API/LLM/service restart,
  stage, commit, push, deploy를 수행하지 않았다.
- raw/base의 6개 pending correction으로 인한 quarantine은 배포 전 기대 상태다.
- 전체 Graph artifact의 full rebuild 검증은 별도 자원 여유와 명시적 운영 승인 후 수행해야
  한다. 이번 최소 fixture 검증은 참조 무결성 fail-closed 계약만 다룬다.
