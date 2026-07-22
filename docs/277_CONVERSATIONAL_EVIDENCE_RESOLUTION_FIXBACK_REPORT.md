# 대화형 근거 확인 Fixback 구현 보고서

- 작성일: 2026-07-19
- 범위: Release B 재검토 4개 결함의 최소 보완
- 작업공간: DGX 격리 작업공간
- 기준 커밋: `b1c0b658a621552bb9b98a035d8883d6fba1dca2`

## 결론

대화형 근거 확인의 공개 응답 경계, 다중 확인 선택 보존, schema v2 표시 계약,
safe baseline의 준비와 운영자 통제 경로를 보완했다. 이번 변경은 격리 테스트
루트에서만 검증했으며, 운영 active ontology, provenance, GraphDB, 검색 인덱스,
계정, 대화, 로그, 서비스에는 쓰지 않았다.

기본 raw/base ontology의 `check_ontology_sync.py` 실패는 의도된 배포 전 차단으로
유지했다. raw/base의 untrusted delta를 운영 fallback으로 사용하는 경로는 만들지
않았다.

## 보완 내용

### 1. 공개 응답의 내부 metadata 차단

- SSE, 출처, 세션 이력, 내보내기가 동일한 public allowlist를 사용한다.
- 내부 chunk 식별자, provenance, operation path, 세션 assertion, 저장용 metadata는
  외부 응답으로 전달하지 않는다.
- 내부 저장에는 필요한 allowlist 범위의 metadata만 보존해 재시도와 이력 복원 계약은
  유지한다.

### 2. 다중 확인 선택의 세션 보존

- 하나의 확인 요청에 여러 slot이 있을 때, 첫 slot의 사용자 assertion을 두 번째
  slot 선택으로 덮어쓰지 않는다.
- 동일 request의 모든 slot이 확인될 때만 resolved로 전환한다.
- 같은 세션에서 a -> b 선택 후 다시 이미 답한 질문을 반복하지 않는 회귀를 고정했다.

### 3. evaluator와 프런트엔드의 schema v2 표시 계약

- evaluator가 만드는 canonical payload에 `schema_version: 2`와 사용자 표시용
  `display.primary_text`를 포함한다.
- API와 프런트엔드는 동일한 구조화 조건, 추가 질문, 직접 근거를 렌더링한다.
- 내부 식별자나 임시 모델 템플릿은 사용자 화면에 표시하지 않는다.

### 4. safe baseline의 operator-gated 진입점

- 기존 `scripts/prepare_ontology_safe_baseline.py`의 artifact-only 생성 호환 모드는
  유지했다.
- 동일 CLI에 `prepare`, `verify`, `publish`, `rollback` subcommand를 추가했다.
- `prepare`는 명시한 release root, release id, runtime root와 입력 데이터 경로만
  사용해 versioned candidate를 준비하고 검증한다.
- `publish`는 `--runtime-root`와 `--confirm PUBLISH_SAFE_BASELINE` 없이는
  실행되지 않는다.
- `rollback`은 `--runtime-root`와 `--confirm ROLLBACK_SAFE_BASELINE` 없이는
  실행되지 않는다.
- publish는 active manifest, provenance, GraphDB 3종의 이전 바이트를 runtime root의
  단일 rollback snapshot으로 보존한다. 두 번째 swap 실패 시 3종을 모두 원복하며,
  명시 rollback 성공 시 snapshot을 제거한다.
- raw 또는 quarantined ontology를 대신 읽는 runtime fallback은 fail-closed로 거부한다.

예시는 다음과 같으며, 실제 운영 root에는 별도 승인 없이 실행하지 않는다.

```bash
python scripts/prepare_ontology_safe_baseline.py verify \
  --release-root <versioned-release-root> \
  --release-id <release-id>

python scripts/prepare_ontology_safe_baseline.py publish \
  --release-root <versioned-release-root> \
  --release-id <release-id> \
  --runtime-root <explicit-runtime-root> \
  --confirm PUBLISH_SAFE_BASELINE

python scripts/prepare_ontology_safe_baseline.py rollback \
  --runtime-root <explicit-runtime-root> \
  --confirm ROLLBACK_SAFE_BASELINE
```

## 검증 결과

| 검증 | 실제 결과 |
| --- | --- |
| CLI 명령 노출 및 publish/rollback fail-closed 계약, prepare validation, publish 실패 원복, explicit rollback | `11 passed` |
| 세션 assertion, public payload, SSE/이력, evaluator schema, safe baseline, 기존 chat/source 회귀 focused suite | `104 passed, 1 warning` |
| 프런트엔드 schema v2 표시 Node 테스트 | `5 passed` |
| `node --check frontend/js/pages/chat.js` | 통과 |
| `npm --prefix frontend run build` | 통과 |
| isolated Playwright (`chat.spec.js`, `isolated-claim-flow.spec.js`) | `13 passed` |
| 전체 pytest | `1100 passed, 3 warnings` |
| `git diff --check` | 통과 |

격리 Playwright는 임시 DB, 테스트 계정, 임시 JWT secret, loopback 포트 `18779`,
읽기 전용 표준코드 DB만 사용했다. 실행이 끝난 뒤 임시 서버, 테스트 root,
Playwright 산출물, node_modules symlink를 제거했다.

## 배포 전 차단 상태

기본 raw/base 검사:

```bash
python scripts/check_ontology_sync.py
```

결과: `ontology integrity state is quarantined`로 exit code 1. 이는 검증되지 않은
raw delta를 safe baseline 없이 운영에 적용하지 않도록 하는 정상 차단이다.
이번 작업은 이 상태를 우회하거나 운영 active manifest, provenance, GraphDB를
수정하지 않았다.

## 변경 파일

- `src/api/public_payloads.py`
- `src/api/routes/chat.py`
- `src/api/routes/sessions.py`
- `src/api/rag_service.py`
- `src/rag/conversation_context.py`
- `src/rag/evidence_assessment.py`
- `src/ontology/safe_baseline.py`
- `scripts/prepare_ontology_safe_baseline.py`
- `frontend/js/pages/chat.js`
- `frontend/dist/app.min.js`
- 관련 Python, Node, Playwright 회귀 테스트

## 미적용 항목과 남은 위험

- pending correction candidate 6건은 승인하거나 apply하지 않았다.
- 운영 safe baseline publish, active manifest/provenance 교체, GraphDB rebuild,
  reindex, API/LLM 재시작, deploy, stage, commit, push를 수행하지 않았다.
- operator CLI의 publish/rollback은 실제 운영 root가 아닌 `tmp_path` 기반 테스트로만
  검증했다. 운영 적용에는 별도 승인, release artifact 검증, controlled publish가
  필요하다.
