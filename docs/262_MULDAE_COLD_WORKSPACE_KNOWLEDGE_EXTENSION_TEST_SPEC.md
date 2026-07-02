# 262. muldae Cold Workspace 지식 확장 테스트 명세

## 목적

DGX 메인 저장소의 최신 `master`를 `muldae` 개인 워크스페이스에 pull한 뒤, DB/검색 인덱스가 빌드되지 않은 cold 상태에서 관리자 지식 확장 플로우가 안전하게 동작하는지 검증한다.

이 명세는 운영 DB 완성 검증이 아니라 신규 배포 또는 개인 개발 공간에서 다음 조건을 확인하기 위한 것이다.

- 앱과 관리자 지식 확장 UI가 cold workspace에서도 로드된다.
- OCR이 필요한 스캔 PDF는 자동 후보 추출로 넘어가지 않고 차단된다.
- 텍스트 레이어가 있는 디지털 PDF는 staging chunk와 후보 생성 단계까지 진행된다.
- 승인 항목 반영 단계에서 base DB/인덱스가 없으면 성공으로 오인하지 않고 원인을 표시한다.
- 메인 저장소의 active DB, search index, GraphDB는 변경하지 않는다.

## 테스트 대상 환경

- DGX 메인 저장소: `/srv/shared/projects/insurance-rag-chatbot`
- 개인 테스트 워크스페이스: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test`
- Python runtime: `/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python`
- 대상 branch: `master`
- 대상 버전: `v1.0.16`

## 사전 조건

1. DGX 메인 저장소 `master`와 GitHub `origin/master`가 같은 커밋을 가리킨다.
2. `muldae` 워크스페이스는 `origin/master` 기준 clean 상태다.
3. 다음 cold-state 산출물이 없어야 한다.

```bash
insurance_chat.db
data/index/chroma_v2
data/index/graph/insurance_graph.sqlite
data/intake/active_sources/chunks.jsonl
```

4. LLM 서버 기동은 이 테스트의 필수 조건이 아니다. 문서 판독, 후보 생성, 실패 안내 흐름이 검증 대상이다.

## 준비 명령

```bash
ssh dgx-spark-muldae
cd /srv/shared/workspaces/muldae

if [ ! -d insurance-rag-chatbot-cold-test/.git ]; then
  git clone https://github.com/koreaben777/insurance-rag-chatbot.git insurance-rag-chatbot-cold-test
fi

cd insurance-rag-chatbot-cold-test
git fetch origin
git checkout master
git pull --ff-only origin master
git status --short --branch
git rev-parse --short HEAD
```

## 정적 검증

```bash
cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test

/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest \
  tests/test_file_intake_planner.py \
  tests/test_intake_runner.py \
  tests/test_source_promotion.py \
  tests/test_knowledge_apply.py \
  tests/test_api_admin_knowledge.py \
  -q

node --test tests/test_admin_knowledge_frontend.mjs

/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m py_compile \
  scripts/build_index_from_canonical_manifest.py \
  scripts/build_graph_index.py \
  src/ingest/source_promotion.py \
  src/ingest/knowledge_apply.py
```

성공 기준:

- pytest가 통과한다.
- 관리자 프론트엔드 정적 테스트가 통과한다.
- Python 문법 검사가 통과한다.
- 위 검증 후 git working tree가 clean 상태를 유지한다.

## 관리자 앱 smoke

```bash
cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test

INSURANCE_APP_DATA_DIR="$PWD/data" \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m uvicorn src.api.main:app \
  --host 127.0.0.1 \
  --port 18081
```

브라우저 접속 경로:

```text
http://127.0.0.1:18081/admin
```

원격 접속이 필요한 경우 SSH local port forward를 사용한다.

```bash
ssh -L 18081:127.0.0.1:18081 dgx-spark-muldae
```

## 시나리오 A: cold 상태 로드

절차:

1. `/admin`에 접속한다.
2. 지식 확장 섹션을 연다.
3. intake job 목록, 후보 목록, 적용 버튼 영역이 로드되는지 확인한다.

기대 결과:

- 관리자 페이지가 500 오류 없이 열린다.
- DB/인덱스가 없어도 지식 확장 섹션 자체는 로드된다.
- 실패나 빈 상태는 사용자에게 설명 가능한 메시지로 표시된다.

## 시나리오 B: 스캔 PDF 차단

절차:

1. 텍스트 레이어가 없는 스캔 PDF를 업로드한다.
2. intake job 실행 또는 자동 처리 결과를 확인한다.

기대 결과:

- 상태가 `blocked_scanned_pdf` 또는 이에 준하는 차단 상태로 남는다.
- 후보 생성 단계로 진행하지 않는다.
- 다음 조치로 텍스트 레이어가 포함된 디지털 PDF 업로드가 안내된다.

성공으로 보지 않는 경우:

- 스캔 PDF에서 빈 후보가 생성된다.
- OCR 자동화를 시도한다.
- 사용자가 왜 막혔는지 알 수 없는 오류만 표시된다.

## 시나리오 C: 디지털 PDF staging 및 후보 생성

절차:

1. 텍스트 레이어가 있는 디지털 PDF를 업로드한다.
2. intake job을 실행한다.
3. job detail, staging chunk 경로, ontology/rule 후보 생성 수를 확인한다.

기대 결과:

- PDF 텍스트 레이어 판독이 통과한다.
- `data/intake/jobs/<job_id>/staging/chunks.jsonl`이 생성된다.
- 온톨로지 후보 또는 룰 후보가 review store에 pending 상태로 등록된다.
- active DB와 검색 인덱스는 아직 변경되지 않는다.

## 시나리오 D: 승인 항목 반영 실패 안내

절차:

1. 테스트 후보를 승인한다.
2. 관리자 UI에서 승인 항목 반영을 실행한다.
3. cold workspace에 base canonical data 또는 index가 없어 실패하는 경우의 표시를 확인한다.

기대 결과:

- 실패를 성공 toast로 표시하지 않는다.
- 실패 사유가 관리자에게 노출된다.
- `index_rebuilt=false` 또는 `graph_rebuilt=false`에 준하는 실패 상태가 확인된다.

주의:

- 이 시나리오의 실패는 P0-P2 구현 실패가 아닐 수 있다. cold workspace에는 운영 base data가 없기 때문이다.
- 실제 운영 반영 성공 검증은 base canonical data를 갖춘 staging workspace에서 별도로 수행한다.

## 결과 기록 항목

테스트 수행 후 다음 항목을 기록한다.

- 테스트 일시
- workspace commit hash
- cold-state 파일 존재 여부
- 정적 검증 결과
- 업로드 문서 종류
- intake job status
- block reason 또는 failure reason
- 생성된 staging chunks 수
- 생성된 ontology/rule 후보 수
- apply-approved 결과
- main repository 영향 없음 여부

## 판정 기준

PASS:

- 정적 검증이 통과한다.
- cold 상태에서 관리자 지식 확장 UI/API가 로드된다.
- 스캔 PDF가 차단된다.
- 디지털 PDF가 후보 생성까지 진행된다.
- apply 실패가 있을 경우 성공으로 오인하지 않는다.

NEEDS WORK:

- cold 상태에서 관리자 페이지 또는 API import가 깨진다.
- 스캔 PDF가 후보 생성으로 넘어간다.
- 디지털 PDF가 staging도 만들지 못하고 원인 없는 실패로 끝난다.
- apply 실패를 성공으로 표시한다.

BLOCKED:

- muldae 계정 접속 불가
- workspace 권한 문제
- 검증용 venv 접근 불가
- 테스트 파일 자체를 준비할 수 없음

## 후속 운영 반영 테스트

cold workspace 검증이 통과하면, 다음 페이즈에서는 base canonical data와 기존 active DB가 준비된 staging workspace에서 다음을 검증한다.

```bash
scripts/build_index_from_canonical_manifest.py --index-mode v2_only
scripts/build_index_from_canonical_manifest.py --index-mode v1_v2_combined
scripts/build_graph_index.py --rebuild
```

그리고 승인된 후보의 source chunk가 BM25/Chroma/GraphDB 검색 결과에 실제 포함되는지 확인한다.
