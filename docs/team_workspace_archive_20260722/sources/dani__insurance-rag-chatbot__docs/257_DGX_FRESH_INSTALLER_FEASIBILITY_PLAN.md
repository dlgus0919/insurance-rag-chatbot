# 257 DGX Spark 신규 장비 통합 설치 프로그램 기술 검토

작성일: 2026-07-01
대상: 새것의 DGX Spark에 보험 RAG 챗봇을 처음 설치하는 회사 사용자
목표: 초보 설치자도 클릭 몇 번으로 코드, 모델, DB, 실행 아이콘까지 설치할 수 있는 통합 설치 프로그램 설계

## 결론

가능하다. 다만 현재 저장소에는 "이미 준비된 DGX에서 앱을 실행하는 wrapper"는 있지만, "완전 새 DGX에 처음 설치하는 installer"는 아직 없다.

가장 현실적인 방식은 다음 조합이다.

1. 현재 개발 DGX에서 설치 번들을 생성한다.
2. 새 DGX에서는 `보험챗봇_통합설치.desktop` 또는 `install.sh`를 실행한다.
3. 설치 마법사에서 모델 설치 범위와 DB 설치 방식을 선택한다.
4. installer가 기존 wrapper와 빌드 스크립트를 호출해 설치, 검증, 데스크톱 실행 아이콘 생성을 끝낸다.

운영 배포 기준 추천안은 **사내 NAS 또는 외장 SSD에 오프라인 설치 번들을 저장하고, 새 DGX가 그 번들에서 복사 설치하는 방식**이다. 외부 와이파이 직접 다운로드도 기술적으로는 가능하지만, 회사 보안 정책과 대용량 다운로드 실패 가능성 때문에 기본 권장안은 아니다.

## 현재 확인된 자산 규모

현재 DGX 기준 대략적인 용량은 다음과 같다.

| 구분 | 용량 |
| --- | ---: |
| 전체 LLM 모델 디렉터리 `/srv/ai-ops/llm/models` | 약 383GB |
| embedding/reranker `/srv/ai-ops/models` | 약 6.5GB |
| 프로젝트 `data` 런타임 자산 | 약 3.4GB |
| 앱 채팅 SQLite `insurance_chat.db` | 약 192KB |

주요 LLM 모델별 용량:

| 모델 | 용량 |
| --- | ---: |
| `qwen3-next-80b-a3b-instruct-fp8` | 약 77GB |
| `qwen3-next-80b-a3b-thinking-fp8` | 약 77GB |
| `gpt-oss-120b` | 약 65GB |
| `llama-3.3-70b-instruct-q4-k-m` | 약 40GB |
| `gemma-4-31b-it-nvfp4` | 약 31GB |
| `qwen3-30b-a3b-instruct-2507-fp8` | 약 30GB |
| `nemotron-3-nano-30b-a3b-nvfp4` | 약 19GB |
| `gemma-4-26b-a4b-nvfp4` | 약 18GB |
| `exaone-4.0-32b-awq` | 약 17GB |
| `gpt-oss-20b` | 약 13GB |

따라서 "현재 DGX와 완전히 동일하게 설치"는 400GB 이상의 설치 원본 저장 공간과 복사 시간이 필요하다.

## 기존 코드에서 재사용 가능한 부분

현재 저장소에는 신규 설치 프로그램의 하위 단계로 재사용할 수 있는 구성 요소가 이미 있다.

| 기존 구성 | 역할 |
| --- | --- |
| `ops/bin/insurance-rag-up` | FastAPI + SPA 앱 실행 |
| `ops/bin/insurance-rag-prepare` | 런타임 DB/index 준비 상태 점검 및 일부 재생성 |
| `ops/bin/insurance-rag-status` | 앱/모델/자산 상태 점검 |
| `ops/install_ai_ops_wrappers.sh` | `/srv/ai-ops/bin` wrapper와 데스크톱 아이콘 설치 |
| `ops/bin/switch-sglang-model` | SGLang 모델 실행 전환 |
| `ops/bin/switch-vllm-model` | vLLM 모델 실행 전환 |
| `ops/bin/prepare-llm-model-assets` | 이미 받은 모델의 chat template 등 보정 |
| `scripts/prepare_streamlit_runtime.sh` | OCR v2/combined index, mapping 등 런타임 자산 준비 |
| `scripts/build_relational_db.py` | 비급여 표준모델 SQLite 생성 |
| `scripts/build_graph_index.py` | GraphDB SQLite 생성 |
| `scripts/manage_users.py` | 첫 관리자 계정 생성 |

부족한 부분은 상위 installer다. 즉, "새 DGX에서 필요한 패키지를 설치하고, 모델/DB 선택지를 묻고, 번들 또는 네트워크에서 자산을 가져오고, 최종 smoke test까지 수행하는 프로그램"을 새로 만들어야 한다.

## 통합 설치 프로그램 구성안

최소 구성은 다음 파일들로 충분하다.

```text
ops/install/
  insurance-rag-install          # 새 DGX에서 실행하는 메인 설치기
  create-offline-bundle          # 현재 DGX에서 설치 번들을 만드는 도구
  installer_manifest.json        # 코드, data, 모델, 검증 규칙 manifest
  model_manifest.json            # 모델별 provider, 경로, 용량, 필수 파일
  db_profiles.json               # DB/index 설치 프로파일
  insurance-rag-install.desktop  # 클릭형 설치 아이콘
```

설치기는 bash + Python 표준 라이브러리 조합으로 만들 수 있다. GUI는 DGX 데스크톱 환경에서 `zenity`가 있으면 체크박스 마법사를 띄우고, 없으면 터미널 메뉴로 fallback한다. 새 의존성은 늘리지 않는 것이 안전하다.

## 설치 마법사에서 물어볼 항목

### 1. 설치 소스

- 외장 SSD/USB 설치 번들
- 사내 NAS 설치 번들
- 외부 와이파이 직접 다운로드
- 혼합 방식: 코드는 Git에서 받고, 모델/DB는 번들에서 복사

### 2. 모델 설치 범위

- 기본 모델 1개만 설치
  - 예: `qwen3-next-80b-a3b-instruct-fp8`
  - 최소 운영용
- 기능별 기본 모델 설치
  - 답변용 LLM, embedding, reranker, OCR/보조 모델 등 필요한 기본값만 설치
- 선택 모델 추가 설치
  - 설치자가 체크박스로 필요한 LLM만 선택
- 현재 개발 DGX와 동일하게 전체 모델 설치
  - `/srv/ai-ops/llm/models` 전체 복제

### 3. DB/index 설치 방식

- 현재 빌드된 DB/index 그대로 설치
  - 즉시 사용 가능
  - 현재 개발 DGX와 같은 검색 결과 재현에 유리
- 빈 운영 DB로 시작
  - 사용자 계정, 채팅 기록, audit log는 새로 생성
  - 회사 운영용 기본값으로 적합
- 승인 프로세스부터 시작
  - ontology 후보/승인 workflow를 새로 시작
  - GraphDB/index는 승인 후 재생성
- 완전 동일 복제
  - data/index, GraphDB, ontology/rules, 앱 DB까지 복사
  - 개발 장비 상태 재현에는 좋지만 개인정보/사용자 기록 포함 여부를 별도 확인해야 함

### 4. 관리자 계정

- 새 관리자 계정과 비밀번호를 설치 중 생성
- 기존 `users.json`은 기본적으로 복사하지 않음
- 필요 시에만 별도 승인 후 계정 파일 이관

## 설치 선택지별 상세 설명

## 선택지 A: 외장 SSD 오프라인 설치 번들

현재 DGX에서 설치 번들을 만든 뒤 외장 SSD로 새 DGX에 옮기는 방식이다.

예상 구조:

```text
insurance-rag-offline-bundle/
  manifest.json
  install.sh
  app.tar.zst
  ai-ops-wrappers.tar.zst
  models/
    qwen3-next-80b-a3b-instruct-fp8.tar.zst
    gpt-oss-20b.tar.zst
    ...
  embedding-reranker.tar.zst
  data-runtime-current.tar.zst
  data-empty-approval.tar.zst
  checksums.sha256
```

장점:

- 외부 인터넷 없이 설치 가능
- 회사 보안 정책에 맞추기 쉽다.
- 다운로드 실패가 없다.
- 설치 속도가 네트워크보다 예측 가능하다.
- DGX 1대 설치에는 가장 단순하다.

단점:

- 외장 SSD가 필요하다.
- 전체 동일 설치는 400GB 이상을 옮겨야 한다.
- 번들 버전이 오래되면 다시 만들어야 한다.
- 외장 SSD 분실/반출입 관리가 필요하다.

적합한 경우:

- 새 DGX 1대 또는 소수 장비 설치
- 회사망/외부망 접속이 불확실한 환경
- "설치 담당자가 명령어를 잘 몰라도 되는" 배포

## 선택지 B: 사내 NAS 설치 번들

설치 번들을 회사 내부 NAS 또는 파일 서버에 올려두고, 새 DGX가 NAS에서 복사해 설치하는 방식이다.

예상 구조:

```text
/nas/insurance-rag/releases/2026-07-01/
  manifest.json
  install.sh
  app.tar.zst
  models/
  data/
  checksums.sha256
```

설치 흐름:

1. 현재 DGX 또는 빌드용 장비에서 번들을 생성한다.
2. 번들을 사내 NAS에 업로드한다.
3. 새 DGX에서 설치 아이콘을 실행한다.
4. 설치기가 NAS 경로를 입력받거나 기본 NAS 경로를 사용한다.
5. 선택한 모델/DB만 새 DGX로 복사한다.

장점:

- 여러 대의 DGX에 반복 설치하기 좋다.
- 외장 SSD를 들고 다닐 필요가 없다.
- 중앙에서 번들 버전 관리가 가능하다.
- 모델을 매번 외부 인터넷에서 받지 않아도 된다.
- 설치 로그와 버전 추적을 표준화하기 쉽다.

단점:

- NAS 접근 권한과 네트워크 설정이 필요하다.
- NAS 속도가 느리면 대용량 모델 복사가 오래 걸린다.
- 초기 NAS 업로드와 권한 설계가 필요하다.
- 사내망이 없는 장소에서는 사용할 수 없다.

적합한 경우:

- 회사 내부에서 여러 DGX에 배포할 가능성이 있는 경우
- 운영팀이 설치 번들을 중앙 관리해야 하는 경우
- 모델/DB 버전을 통제해야 하는 경우

## 선택지 C: 외부 와이파이 직접 다운로드 설치

새 DGX가 외부 와이파이에 연결되어 GitHub, Python package index, Hugging Face 등에서 직접 내려받는 방식이다.

장점:

- 별도 번들을 만들지 않아도 된다.
- 최신 코드를 바로 가져오기 쉽다.
- 설치 원본 저장소 관리가 단순하다.

단점:

- 회사 보안 정책상 금지될 수 있다.
- 모델 다운로드가 매우 크다. 기본 모델만 약 77GB, 전체 모델은 약 383GB다.
- Hugging Face 토큰, 모델 접근 권한, 라이선스 동의가 필요할 수 있다.
- 다운로드 중단/속도 저하/방화벽 문제로 설치 실패 가능성이 높다.
- 설치 결과가 시점에 따라 달라질 수 있다.

적합한 경우:

- 임시 개발/검증 장비
- 회사 정책상 외부망 연결이 허용된 경우
- 최소 모델만 빠르게 내려받아 테스트하는 경우

운영 배포용 기본값으로는 권장하지 않는다.

## 선택지 D: 혼합 방식

코드는 Git 또는 사내 Git에서 받고, 대용량 모델과 DB/index만 외장 SSD 또는 NAS에서 복사하는 방식이다.

장점:

- 코드 업데이트가 쉽다.
- 대용량 모델 다운로드 실패를 피할 수 있다.
- 설치 번들 크기를 줄일 수 있다.
- 운영 패치와 대용량 자산 배포를 분리할 수 있다.

단점:

- Git 접근과 번들 접근이 모두 필요하다.
- 설치기가 버전 호환성을 더 엄격히 검사해야 한다.
- 코드와 data/model manifest가 어긋나면 실행 오류가 날 수 있다.

적합한 경우:

- 앱 코드는 자주 바뀌지만 모델/DB는 자주 바뀌지 않는 운영 환경
- 사내 Git과 NAS를 모두 사용할 수 있는 환경

## DB/index 프로파일 설계

설치기에는 다음 프로파일을 제공하는 것이 좋다.

| 프로파일 | 포함 항목 | 용도 |
| --- | --- | --- |
| `current-runtime` | `data/processed`, `data/index*`, `data/mapping`, `data/ontology`, `data/rules`, GraphDB | 현재 검색/계산 상태 그대로 사용 |
| `empty-approval` | schema, rules 기본 파일, 원본 문서, 승인 UI | 승인 후보 검토부터 새로 시작 |
| `rebuild-from-source` | 원본 PDF/XLSX/OCR 결과, 빌드 스크립트 | 새 DGX에서 index/GraphDB 재생성 |
| `full-clone` | runtime data + 앱 DB + users.json 선택 포함 | 개발 DGX와 최대한 동일 재현 |

운영 배포 기본값은 `current-runtime` + 새 관리자 계정 생성이 적합하다. `full-clone`은 사용자 계정, 채팅 기록, 감사 로그가 섞일 수 있으므로 별도 승인 없이는 기본값으로 두지 않는다.

## 모델 프로파일 설계

설치기에는 다음 프로파일을 제공하는 것이 좋다.

| 프로파일 | 포함 모델 | 용도 |
| --- | --- | --- |
| `minimal` | embedding/reranker + 기본 LLM 1개 | 회사 사용자 기본 운영 |
| `functional-defaults` | 기본 LLM + 보조 경량/대체 모델 | 장애 시 대체 모델 준비 |
| `selected` | 설치자가 체크한 모델 | 저장 공간 절약 |
| `full-current` | 현재 `/srv/ai-ops/llm/models` 전체 | 개발 DGX와 동일 재현 |

모델별 필수 파일 검증은 `config.json`, tokenizer 파일, safetensors index, `chat_template.jinja` 등 provider별로 manifest에 둔다. 설치 후에는 기존 `switch-sglang-model` 또는 `switch-vllm-model`로 실제 1회 smoke test를 수행한다.

## 추가 설치해야 하는 서브 프로그램과 라이브러리

SSD 설치 번들은 모델 파일만 담으면 안 된다. 새 DGX에서 외부망을 쓰지 않고 설치하려면 모델 구동 런타임, 앱 실행 환경, 검색/DB 런타임을 함께 넣어야 한다.

### 1. 모델 구동 런타임

| 구성 | 포함 이유 | 현재 기준 |
| --- | --- | --- |
| SGLang 실행 환경 | Qwen 80B 일반 답변 모델과 Qwen 30B 온톨로지 모델 구동 | `.venv-sglang` 약 8.6GB |
| vLLM 실행 환경 | Gemma 등 선택 모델 구동 | `.venv-vllm` 약 8.0GB |
| SGLang wrapper | 모델 전환, tmux 기동, health/smoke test | `/srv/ai-ops/bin/switch-sglang-model`, `run-sglang-local` |
| vLLM wrapper | vLLM 모델 전환, tmux 기동, health/smoke test | `/srv/ai-ops/bin/switch-vllm-model` |
| chat template 보정 도구 | 모델별 `chat_template.jinja` 보정 | `/srv/ai-ops/bin/prepare-llm-model-assets` |

TensorRT-LLM과 `gpt-oss-120b`는 현재 DGX Spark 운영 선택지에서 제외되어 있으므로 기본 설치 번들에는 넣지 않는다. 진단용으로만 남길 때는 Docker image와 TensorRT-LLM 설정까지 별도 optional 번들로 분리한다.

### 2. 앱 실행 환경

| 구성 | 포함 이유 | 현재 기준 |
| --- | --- | --- |
| 앱 Python venv | FastAPI, RAG, Chroma, sentence-transformers, OCR/파서 의존성 | `.venv` 약 6.5GB |
| Node.js/npm runtime | frontend build, JS 테스트, 정적 번들 재생성 | 시스템 `node`, `npm` |
| frontend 의존성 | SPA build에 필요 | `frontend/node_modules` 약 19MB |
| root package 의존성 | Playwright/e2e 또는 JS 테스트 보조 | `node_modules` 소형 |

기본 운영 설치에서는 이미 빌드된 frontend 산출물을 포함하고, 재빌드가 필요할 때만 `npm install` 또는 번들된 `node_modules`를 사용한다.

### 3. 앱 wrapper와 데스크톱 실행 도구

새 DGX에는 최소 다음 wrapper가 설치되어야 한다.

```text
/srv/ai-ops/bin/insurance-rag-common
/srv/ai-ops/bin/insurance-rag-prepare
/srv/ai-ops/bin/insurance-rag-status
/srv/ai-ops/bin/insurance-rag-up
/srv/ai-ops/bin/insurance-rag-desktop-launcher
/srv/ai-ops/bin/insurance-rag-ontology-review-gui
/srv/ai-ops/bin/insurance-rag-rule-candidate-review-gui
/srv/ai-ops/bin/insurance-rag-rule-review-gui
/srv/ai-ops/bin/switch-sglang-model
/srv/ai-ops/bin/switch-vllm-model
/srv/ai-ops/bin/run-sglang-local
/srv/ai-ops/bin/prepare-llm-model-assets
```

설치 아이콘은 `ops/install_ai_ops_wrappers.sh`의 방식을 재사용해 Desktop에 `.desktop` 파일을 배치한다.

### 4. 시스템 패키지와 명령어

설치기가 사전에 확인해야 하는 기본 명령어는 다음이다.

```text
python3
git
curl
tmux
rsync
tar
sha256sum
node
npm
zenity
lsof
ss
fuser
```

`zenity`는 클릭형 설치 마법사와 GUI launcher에 필요하다. 없으면 터미널 메뉴로 fallback할 수 있다. `tmux`는 앱과 모델 서버를 SSH 종료 후에도 유지하는 데 필요하다.

### 5. 검색, DB, 승인 workflow 런타임

| 구성 | 포함 이유 |
| --- | --- |
| embedding 모델 | 문서 검색 vector embedding |
| reranker 모델 | 검색 결과 재정렬 |
| `data/processed` | chunk/canonical manifest |
| `data/index`, `data/index_v2_manual`, `data/index_v1_v2_combined` | BM25/Chroma 검색 인덱스 |
| `data/index/graph/insurance_graph.sqlite` | GraphDB 기반 검토 경로 |
| `data/mapping` | v1/v2 OCR chunk 매핑 |
| `data/ontology` | 온톨로지 manifest/schema/policy |
| `data/rules` | 보험금 계산 규칙 manifest |

사용자 계정 파일, 채팅 기록, API key는 기본 번들에 포함하지 않고 새 설치 중 생성한다.

## 기술 구현 흐름

### 현재 DGX에서 번들 생성

```text
create-offline-bundle
  1. Git commit/tag 확인
  2. 앱 코드 archive 생성
  3. 선택된 모델 archive 생성
  4. embedding/reranker archive 생성
  5. 선택된 DB/index profile archive 생성
  6. checksums.sha256 생성
  7. manifest.json 생성
```

### 새 DGX에서 설치

```text
insurance-rag-install
  1. root/sudo 권한, GPU, 디스크 여유 공간 확인
  2. 설치 소스 선택: SSD/NAS/외부 다운로드
  3. 모델 profile 선택
  4. DB/index profile 선택
  5. /srv/shared/projects/insurance-rag-chatbot 설치
  6. /srv/ai-ops/bin wrapper 설치
  7. Python venv, SGLang/vLLM venv 준비 또는 번들 복원
  8. 모델/embedding/reranker 복사
  9. DB/index 복원 또는 빌드
  10. 관리자 계정 생성
  11. 데스크톱 실행 아이콘 생성
  12. insurance-rag-prepare 실행
  13. 기본 모델 switch smoke test
  14. 앱 health check
```

## 검증 기준

설치 완료 조건은 다음으로 잡는다.

- `insurance-rag-prepare` 성공
- 기본 모델 switch 성공
- `/api/health` 성공
- `/api/system/models`에서 선택 모델 표시
- 관리자 로그인 가능
- 샘플 질의 1건 응답
- GraphDB/index 파일 존재
- 설치 manifest와 checksum 검증 통과

## 보안 및 운영 주의사항

- `.env`, API key, 기존 `users.json`, 기존 채팅 기록은 기본 번들에 넣지 않는다.
- 새 DGX 설치 시 `API_JWT_SECRET`은 새로 생성한다.
- 첫 관리자 계정은 설치 중 새로 만든다.
- 외부 와이파이 다운로드 방식은 회사 보안 정책 확인 후에만 사용한다.
- 모델 라이선스와 반입 승인 상태를 manifest에 기록한다.
- 설치 로그는 `/srv/ai-ops/logs/installer/`에 저장한다.
- 실패 시 재실행 가능하도록 단계별 marker 파일을 남긴다.

## 구현 가능성 판단

기술적으로 가능하다.

가장 작은 구현은 기존 wrapper를 그대로 두고, 그 위에 installer와 manifest만 추가하는 방식이다. 새 LLM serving 코드를 만들 필요는 없다. 모델 실행은 기존 `switch-sglang-model`, `switch-vllm-model`, `insurance-rag-up`을 재사용한다.

우선순위는 다음이 좋다.

1. `minimal` + `current-runtime` 설치기 구현
2. 외장 SSD 오프라인 번들 생성/설치 지원
3. 사내 NAS 경로 설치 지원
4. 선택 모델 설치 UI 추가
5. 외부 와이파이 직접 다운로드는 마지막 옵션으로 추가

## 권장 최종안

회사 배포용 기본값:

- 설치 매체: 사내 NAS 또는 외장 SSD 오프라인 번들
- 모델: `minimal` 또는 `functional-defaults`
- DB/index: `current-runtime`
- 사용자/채팅 DB: 새로 생성
- 관리자 계정: 설치 중 생성
- 실행: 데스크톱 아이콘 + `/srv/ai-ops/bin/insurance-rag-up`

이 구성이 "처음 설치하는 사람도 클릭 몇 번으로 설치"라는 요구에 가장 가깝고, 회사 보안/대용량 모델/재현성 문제를 동시에 줄인다.
