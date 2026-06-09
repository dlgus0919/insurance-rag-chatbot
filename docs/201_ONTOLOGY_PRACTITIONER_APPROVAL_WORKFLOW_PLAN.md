# 201. Ontology Practitioner Approval Workflow Plan

## 목적

하드코딩된 보험 판단 로직을 줄이기 위해 GraphDB/Ontology에 들어갈 후보 개념을 코드가 임의로 확정하지 않고, 실무자가 승인/보류/거절한 항목만 운영 온톨로지에 반영하는 워크플로우를 구축한다.

이번 계획의 핵심 요구는 DGX 바탕화면 실행기를 더블클릭했을 때, 승인 대기 중인 개념이 있으면 실무자가 별도 개발 지식 없이 검토하고 GraphDB 재구축까지 진행할 수 있게 하는 것이다.

## 현재 전제

- 운영 저장소: `/srv/shared/projects/insurance-rag-chatbot`
- DGX 바탕화면 실행기: `ops/bin/insurance-rag-desktop-launcher`
- 현재 온톨로지 manifest: `data/ontology/concepts.json`
- 현재 registry: `src/ontology/registry.py`
- 현재 GraphDB rebuild 경로: `ops/bin/insurance-rag-prepare`, `scripts/build_graph_index.py --rebuild`
- 현재 구현된 온톨로지는 운영 manifest 중심이며, 승인 대기/검토 이력/자동 적용/GUI 승인 흐름은 아직 별도 레이어로 분리되어 있지 않다.

## 설계 원칙

1. 운영 manifest는 실무자 승인 없이는 직접 변경하지 않는다.
2. LLM 자동 승인은 운영 후보에는 사용할 수 없고, `test_candidate=true` 후보에만 허용한다.
3. 승인/보류/거절 이력은 append-only 로그로 남긴다.
4. GraphDB 재구축 전에는 manifest/schema 검증과 이전 산출물 백업을 수행한다.
5. 실무자 승인 UI는 DGX 바탕화면 실행기에서 진입 가능해야 하며, 승인 완료 후 기존 앱 기동 흐름으로 돌아와야 한다.
6. 신규 보험/약관/원천 문서가 추가되어도 후보 생성과 승인 절차는 코드 수정 없이 manifest/candidate 데이터 갱신으로 처리한다.

## 데이터 모델

### 신규 후보 저장소

```text
data/ontology/review/candidates.jsonl
data/ontology/review/review_log.jsonl
data/ontology/review/applied_reviews.jsonl
data/ontology/concepts.active.json
data/ontology/backups/
```

`candidates.jsonl`은 운영 manifest에 들어가기 전의 후보만 저장한다. 후보는 원천 문서, 추출 근거, 위험도, 검토 상태를 포함한다.

필수 필드:

- `candidate_id`
- `concept_id`
- `canonical_name`
- `node_type`
- `aliases`
- `candidate_aliases`
- `evidence_tags`
- `planner`
- `retrieval`
- `properties`
- `source_evidence`
- `status`: `pending`, `approved`, `held`, `rejected`, `applied`
- `risk_flags`
- `test_candidate`
- `created_at`
- `extraction_run_id`

`source_evidence` 필드:

- `doc_short`
- `doc_name`
- `page`
- `chunk_id`
- `excerpt`
- `confidence`

### 승인 로그

`review_log.jsonl`은 실무자 또는 테스트 자동 승인자의 모든 판단을 append-only로 남긴다.

필수 필드:

- `review_id`
- `candidate_id`
- `decision`: `approve`, `hold`, `reject`
- `reviewer`
- `reviewer_type`: `practitioner`, `codex_test_auto`
- `reason`
- `created_at`
- `before_status`
- `after_status`

### 운영 manifest

운영 중 registry는 다음 우선순위로 manifest를 읽는다.

1. 환경변수 `INSURANCE_ONTOLOGY_MANIFEST`
2. `data/ontology/concepts.active.json`
3. `data/ontology/concepts.json`

`concepts.active.json`은 base manifest와 승인된 후보를 병합해 생성한다. base manifest를 직접 덮어쓰지 않으므로 rollback이 단순하다.

## 사용자 흐름

### 바탕화면 실행기 기본 흐름

1. 실무자가 DGX 바탕화면의 앱 실행 아이콘을 더블클릭한다.
2. 실행기가 `insurance-rag-ontology-review --pending-count`로 승인 대기 후보 수를 확인한다.
3. 승인 대기 후보가 없으면 기존 LLM 선택 및 앱 기동 흐름으로 진행한다.
4. 승인 대기 후보가 있으면 다음 선택창을 표시한다.
   - `개념 승인 검토 시작`
   - `나중에 검토하고 앱 실행`
   - `테스트 후보 LLM 자동 승인`
   - `취소`
5. `개념 승인 검토 시작`을 선택하면 후보 리스트와 원문 근거 요약을 표시한다.
6. 실무자는 각 후보에 대해 `승인`, `보류`, `거절` 중 하나를 선택한다.
7. 확인 버튼을 누르면 승인 로그를 저장한다.
8. 승인된 후보가 있으면 active manifest 생성, schema 검증, GraphDB 백업, GraphDB 재구축을 수행한다.
9. 재구축이 성공하면 완료 메시지를 보여주고 기존 LLM 선택 및 앱 기동 흐름으로 복귀한다.

### 테스트 후보 자동 승인 흐름

테스트 자동 승인은 운영 후보에 적용하지 않는다.

1. 실행기에서 `테스트 후보 LLM 자동 승인`을 선택한다.
2. `test_candidate=true`이고 `status=pending`인 후보만 대상으로 한다.
3. 자동 승인자는 `reviewer=codex-test-auto`, `reviewer_type=codex_test_auto`로 기록한다.
4. 자동 승인 전 확인창에 대상 후보 수와 “운영 후보는 제외됨”을 표시한다.
5. 승인 후 동일하게 active manifest 생성 및 GraphDB 재구축을 수행한다.

이 흐름은 회귀 테스트와 데모용이며, 실무 운영에서는 비활성화할 수 있도록 환경변수 `ENABLE_ONTOLOGY_TEST_AUTO_APPROVAL=false`를 지원한다.

## 구현 계획

### Phase 1. 승인 상태 저장소와 CLI

목표: GUI 없이도 후보 조회, 판단 저장, active manifest 생성, GraphDB rebuild가 가능하게 한다.

구현 항목:

- `src/ontology/review_store.py`
  - 후보 로드/저장
  - status 전환
  - review log append
  - 테스트 후보 필터
- `src/ontology/manifest_merge.py`
  - base manifest + approved candidates 병합
  - 중복 `concept_id` 및 alias 충돌 검출
  - `concepts.active.json` 생성
- `scripts/ontology_review.py`
  - `--pending-count`
  - `--list --json`
  - `--decide <candidate_id> --decision approve|hold|reject`
  - `--auto-approve-test`
  - `--apply --rebuild-graph`
- `tests/test_ontology_review_store.py`
- `tests/test_ontology_manifest_merge.py`

검증:

```bash
pytest tests/test_ontology_review_store.py tests/test_ontology_manifest_merge.py -q
python scripts/ontology_review.py --pending-count
python scripts/ontology_review.py --auto-approve-test --dry-run
```

### Phase 2. Registry와 GraphDB rebuild 연동

목표: 승인된 active manifest가 실제 retrieval/planner/GraphDB rebuild에 반영되게 한다.

구현 항목:

- `src/ontology/registry.py`
  - `INSURANCE_ONTOLOGY_MANIFEST` 지원
  - active manifest 우선 로딩
  - manifest source path 진단값 노출
- `scripts/check_ontology_sync.py`
  - active manifest 검증 지원
- `ops/bin/insurance-rag-prepare`
  - active manifest 존재 시 해당 manifest 기준 GraphDB rebuild
  - rebuild 전 `data/index/graph/insurance_graph.sqlite` 백업
- GraphDB rebuild lock
  - `/tmp/insurance-rag-ontology-rebuild.lock`

검증:

```bash
python scripts/check_ontology_sync.py --manifest data/ontology/concepts.active.json
python scripts/build_graph_index.py --rebuild
pytest tests/test_ontology_registry.py tests/test_graph_review_path_retriever.py -q
```

### Phase 3. DGX 바탕화면 실행기 승인 UI

목표: 실무자가 바탕화면 아이콘 클릭만으로 승인 workflow를 수행한다.

구현 항목:

- `ops/bin/insurance-rag-ontology-review-gui`
  - `zenity` 기반 승인 대기 알림
  - 후보 리스트 표시
  - 후보별 원문 근거 excerpt 표시
  - 승인/보류/거절 선택
  - 확인 후 CLI apply/rebuild 호출
  - 진행 상태 표시
- `ops/bin/insurance-rag-desktop-launcher`
  - LLM 선택 전에 ontology approval preflight 추가
  - 승인 완료 또는 나중에 검토 선택 후 기존 LLM 선택 흐름으로 복귀
  - 테스트 후보 자동 승인 선택지 추가

검증:

```bash
bash -n ops/bin/insurance-rag-ontology-review-gui
bash -n ops/bin/insurance-rag-desktop-launcher
DISPLAY=:0 ops/bin/insurance-rag-ontology-review-gui --dry-run
```

### Phase 4. 관리자 페이지 온톨로지 탭

목표: 실행기 외에도 관리자 페이지에서 후보와 승인 이력을 확인할 수 있게 한다.

구현 항목:

- API
  - `GET /api/admin/ontology/status`
  - `GET /api/admin/ontology/candidates`
  - `POST /api/admin/ontology/candidates/{candidate_id}/decision`
  - `POST /api/admin/ontology/apply`
  - `POST /api/admin/ontology/auto-approve-test`
- Frontend
  - 관리자 페이지 `온톨로지 승인` 탭
  - 후보 리스트
  - 원문 근거 excerpt
  - 승인/보류/거절 버튼
  - rebuild 진행 상태
  - review log 표시

검증:

```bash
pytest tests/test_admin_ontology_routes.py -q
pytest tests/e2e/admin_ontology.spec.js -q
```

### Phase 5. 후보 생성 파이프라인

목표: 원천 문서에서 후보를 추출하되, 운영 반영은 승인 후에만 수행한다.

구현 항목:

- `scripts/extract_ontology_candidates.py`
  - raw chunk/GraphDB/vector metadata 기반 후보 생성
  - source evidence 필수
  - 기존 manifest와 중복 제거
  - confidence/risk flag 산출
- 후보 타입
  - `ClaimCondition`
  - `ExclusionReason`
  - `BenefitLimit`
  - `DeductibleRule`
  - `RequiredDocument`
  - `CoordinationRule`
  - `RenewalOrGenerationRule`
- 테스트 fixture 후보 생성
  - `scripts/seed_test_ontology_candidates.py`

검증:

```bash
python scripts/extract_ontology_candidates.py --dry-run
python scripts/seed_test_ontology_candidates.py --output data/ontology/review/candidates.jsonl
pytest tests/test_ontology_candidate_extractor.py -q
```

## 오류 방지 정책

- `reject` 후보는 active manifest에 절대 병합하지 않는다.
- `hold` 후보는 다음 실행 때 계속 보류 상태로 표시하되 rebuild 대상에서 제외한다.
- `approved` 후보가 schema 검증에 실패하면 전체 적용을 중단한다.
- alias 충돌이 발생하면 해당 후보는 자동으로 `held` 처리하고 실무자에게 충돌 사유를 표시한다.
- GraphDB rebuild 실패 시 이전 `concepts.active.json`와 SQLite graph를 복구한다.
- 테스트 자동 승인은 `test_candidate=true` 후보만 대상으로 하며, 운영 후보가 섞이면 즉시 실패한다.

## 자체 검토

### 요구사항 충족 여부

- 바탕화면 실행기에서 승인 대기 여부를 확인하고 승인 UI로 진입하는 흐름을 포함했다.
- 실무자가 승인/보류/거절을 선택하고 확인 후 GraphDB 재구축까지 이어지는 흐름을 포함했다.
- 승인 완료 후 기존 앱 기동 프로세스로 복귀하는 흐름을 포함했다.
- 테스트용 LLM/Codex 자동 승인 옵션을 포함하되, 운영 후보에는 적용되지 않도록 제한했다.

### 확장성 검토

새 보험/약관/원천 문서가 추가되어도 후보 생성 결과가 `candidates.jsonl`에 쌓이고, 승인된 후보만 active manifest로 병합된다. 따라서 코드 수정 없이 데이터와 승인 workflow로 확장 가능하다.

### 유지보수성 검토

운영 manifest, 후보 저장소, 승인 로그, active manifest를 분리했기 때문에 장애 원인 추적과 rollback이 가능하다. CLI를 먼저 구현하고 GUI/API를 얹는 순서라 디버깅 경로도 단순하다.

### 위험 요소

- GraphDB rebuild는 시간이 걸릴 수 있으므로 실행기 GUI에서 진행 상태와 로그 위치를 명확히 표시해야 한다.
- `zenity` UI는 복잡한 대량 검토에는 불편할 수 있다. MVP 후 관리자 웹 탭을 병행 구축해야 한다.
- LLM 자동 승인은 테스트 편의 기능이지 운영 승인 기능이 아니다. 명칭과 UI 문구에서 이 점을 명확히 해야 한다.

## 목표 설정용 프롬프트

```text
목표: DGX 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot` 기준으로 온톨로지 실무자 승인 워크플로우 MVP를 구현합니다. 계획 문서 `docs/201_ONTOLOGY_PRACTITIONER_APPROVAL_WORKFLOW_PLAN.md`를 우선 읽고, Phase 1~3을 범위로 진행하세요.

구현 범위:
1. `data/ontology/review/` 기반 후보 저장소, 승인 로그, active manifest 생성 로직을 구현합니다.
2. `scripts/ontology_review.py` CLI를 만들어 pending 후보 조회, 승인/보류/거절, 테스트 후보 자동 승인, active manifest 적용, GraphDB rebuild 호출을 지원합니다.
3. `src/ontology/registry.py`가 `INSURANCE_ONTOLOGY_MANIFEST`와 `data/ontology/concepts.active.json`을 우선 로딩하도록 패치합니다.
4. DGX 바탕화면 실행기 `ops/bin/insurance-rag-desktop-launcher`에 ontology approval preflight를 추가하고, `zenity` 기반 `ops/bin/insurance-rag-ontology-review-gui`를 만들어 실무자가 승인 대기 후보를 검토할 수 있게 합니다.
5. 테스트 자동 승인은 반드시 `test_candidate=true` 후보에만 적용되게 하고, reviewer는 `codex-test-auto`로 audit log에 남기세요.
6. GraphDB rebuild 전에는 manifest/schema 검증과 기존 graph backup을 수행하고, 실패 시 이전 active manifest와 graph를 보존하세요.

검증:
- 관련 pytest를 추가하고 실행하세요.
- `bash -n ops/bin/insurance-rag-desktop-launcher ops/bin/insurance-rag-ontology-review-gui`를 통과시켜 주세요.
- 테스트 후보를 1개 생성해 `auto-approve-test -> active manifest 생성 -> GraphDB rebuild dry/live smoke` 흐름을 검증하세요.
- 기존 RAG/Graph retrieval 테스트가 깨지지 않는지 관련 테스트를 실행하세요.

주의:
- 운영 후보에 LLM 자동 승인을 적용하지 마세요.
- 사용자가 만든 기존 변경이나 미추적 파일을 되돌리지 마세요.
- 구현 완료 후 간결한 보고서를 `docs/`에 작성하고, 이상이 없을 때만 사용자 승인 후 커밋/푸시하세요.
```
