# 261. muldae Cold Workspace 지식 확장 테스트 준비

## 목적

DGX 메인 저장소의 `master`를 `muldae` 개인 워크스페이스에 새로 pull 또는 clone한 뒤, DB/검색 인덱스가 아직 빌드되지 않은 상태에서 지식 확장 플로우가 어디까지 안전하게 동작하는지 검증한다.

이 테스트는 운영 DB 완성 검증이 아니라 다음 항목을 확인하기 위한 cold workspace 검증이다.

- 코드만 받은 신규 워크스페이스에서 관리자 지식 확장 UI/API가 로드되는가
- 스캔 PDF 또는 텍스트 레이어 없는 PDF를 후보 추출 단계로 넘기지 않고 차단하는가
- 디지털 PDF는 staging chunk 생성과 후보 생성까지 진행되는가
- base canonical data 또는 active DB가 없을 때 apply/rebuild가 어떤 오류와 안내를 제공하는가

## 테스트 위치

권장 위치:

```bash
/srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test
```

이 경로는 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot`와 분리된 사용자 테스트 공간이다. 테스트 중 생성되는 `data/intake/jobs`, `data/intake/active_sources`, 임시 업로드 파일은 메인 저장소에 영향을 주지 않아야 한다.

## 사전 조건

- DGX 메인 저장소의 P0-P2 변경이 `origin/master`에 push되어 있어야 한다.
- `muldae` 워크스페이스는 새 clone 또는 clean pull 상태여야 한다.
- 테스트용 앱 실행에는 기존 DGX 메인 저장소의 검증된 Python venv를 재사용할 수 있다.

```bash
/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python
```

## 준비 명령

새 workspace를 만들 때:

```bash
mkdir -p /srv/shared/workspaces/muldae
cd /srv/shared/workspaces/muldae
git clone <repo-url> insurance-rag-chatbot-cold-test
cd insurance-rag-chatbot-cold-test
git checkout master
git pull --ff-only origin master
```

이미 workspace가 있을 때:

```bash
cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test
git fetch origin
git checkout master
git reset --hard origin/master
```

주의: `git reset --hard`는 이 cold-test 전용 워크스페이스에서만 사용한다. 개인 작업물이 있는 워크스페이스에는 사용하지 않는다.

## Cold 상태 확인

다음 파일/디렉터리가 없거나 비어 있으면 cold workspace 검증에 적합하다.

```bash
test ! -e insurance_chat.db
test ! -e data/index/chroma_v2
test ! -e data/index/graph/insurance_graph.sqlite
test ! -e data/intake/active_sources/chunks.jsonl
```

기존 산출물이 있으면 새 workspace를 만들거나, cold-test 전용 경로에서만 삭제 후 진행한다.

## 최소 API 검증

의존성은 메인 저장소 venv를 사용한다.

```bash
cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test
/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest \
  tests/test_file_intake_planner.py \
  tests/test_intake_runner.py \
  tests/test_source_promotion.py \
  tests/test_knowledge_apply.py \
  tests/test_api_admin_knowledge.py \
  -q
```

이 검증은 DB를 새로 빌드하지 않고 지식 확장 orchestration과 실패 안내 경로를 확인한다.

## 관리자 앱 cold smoke

실행 예시:

```bash
cd /srv/shared/workspaces/muldae/insurance-rag-chatbot-cold-test
INSURANCE_APP_DATA_DIR="$PWD/data" \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m uvicorn src.api.main:app \
  --host 127.0.0.1 \
  --port 18081
```

브라우저 또는 터널에서 `/admin`에 접속해 다음을 확인한다.

1. 지식 확장 섹션이 로드된다.
2. 문서 업로드 job 목록이 표시된다.
3. 스캔 PDF는 OCR 필요 안내와 함께 차단된다.
4. 디지털 PDF는 staging 및 후보 생성 단계로 이동한다.
5. 승인 항목 반영 버튼은 DB/인덱스 준비 부족 시 성공으로 오인하지 않고 실패 사유를 표시한다.

## 성공 기준

- cold 상태에서도 관리자 UI/API가 import 또는 라우팅 오류 없이 뜬다.
- 스캔 PDF는 후보 생성으로 넘어가지 않는다.
- 디지털 PDF는 후보 생성까지 진행된다.
- apply/rebuild가 실패한다면 실패 원인과 다음 조치가 관리자 UI/API 응답에서 확인된다.
- 메인 저장소의 active DB, index, GraphDB는 변경되지 않는다.

## 성공으로 보지 않는 것

다음은 cold workspace 테스트의 목적이 아니다.

- 기존 운영 DB와 동일한 질의 품질 검증
- 대량 문서 전체 재인덱싱 성능 검증
- 신규 문서가 실제 운영 GraphDB에 완전히 반영되는지 검증

이 항목은 base canonical data를 준비한 별도 staging 환경에서 수행해야 한다.

## 다음 단계

cold workspace 테스트가 통과하면, 다음 단계에서는 작은 디지털 PDF 1건과 필요한 base canonical data를 갖춘 staging workspace에서 `apply-approved`가 BM25/Chroma/GraphDB까지 끝까지 반영하는지 검증한다.
