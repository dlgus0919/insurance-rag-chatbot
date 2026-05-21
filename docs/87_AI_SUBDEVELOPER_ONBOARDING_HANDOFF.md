# AI Subdeveloper Onboarding Handoff

작성일: 2026-05-21  
대상 프로젝트: `insurance-rag-chatbot`  
운영/개발 기준 환경: NVIDIA DGX Spark `aitopatom-255d`  
작성 목적: 새로 편입되는 AI 서브 개발자가 이 문서 하나만 보고 즉시 프로젝트 작업을 시작할 수 있게 하는 개발 인수인계

---

## 1. 가장 중요한 원칙

이 프로젝트의 현재 메인 개발 기준은 **맥북 로컬 저장소가 아니라 DGX Spark 원격 저장소**다.

반드시 아래 경로에서 작업한다.

```text
/srv/shared/projects/insurance-rag-chatbot
```

맥북 로컬 프로젝트 폴더는 참고나 임시 확인 용도로만 사용한다. 실제 코드 수정, 테스트, 문서 작성, 커밋, push는 사용자가 별도로 다르게 지시하지 않는 한 DGX Spark의 위 경로에서 수행한다.

기본 접속 명령:

```bash
ssh ai-hang@100.88.5.57
```

공용 프로젝트 폴더로 바로 접속:

```bash
ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot; bash -l"
```

맥북에서 Streamlit 앱을 볼 때:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

브라우저:

```text
http://localhost:8501
```

---

## 2. 현재 프로젝트 상태 요약

현재 DGX 기준 최신 확인 상태:

```text
branch: master
latest commit: 2401fde fix(rag): strengthen source-grounded retrieval logic
remote: https://github.com/koreaben777/insurance-rag-chatbot.git
project path: /srv/shared/projects/insurance-rag-chatbot
```

최근 주요 커밋:

```text
2401fde fix(rag): strengthen source-grounded retrieval logic
2b2109f Add Gemma4 vLLM provider path
68d5a93 Disable unsupported Gemma4 SGLang path
7c2a745 Add large model RAG evaluation harness
0425390 Add evidence guardrails for source-specific codes
```

정상 운영 기준:

```text
chunks.jsonl line count: 7825
Chroma collection count: 7825
retrieval eval: recall@8 = 1.000
기본 fallback Ollama model: exaone3.5:7.8b
SGLang 기본 대형 모델: gpt-oss-20b
vLLM Gemma4 모델: gemma-4-26b-a4b-nvfp4
Streamlit 내부 주소: 127.0.0.1:8501
```

---

## 3. 역할 분담

### 총괄 개발자 Codex

이 채팅의 Codex는 프로젝트 개발 총괄 역할을 맡는다.

주요 역할:

- 아키텍처 판단
- 구현 우선순위 결정
- DGX 메인 repo 기준 변경 수행
- 테스트와 회귀 검증
- Git 커밋/push 수행 여부 판단
- Claude/다른 에이전트 작업 결과 검토

### 신규 AI 서브 개발자

새 에이전트는 보조 구현자 또는 조사/검증 담당으로 편입된다.

기대 역할:

- 명확히 할당된 작은 범위의 코드 수정
- 테스트 실패 원인 분석
- 문서/런북 보강
- 평가 케이스 작성
- read-only 코드 탐색
- 총괄 Codex 또는 사용자의 명시 승인 후 제한적 구현

서브 개발자는 독단적으로 운영 데이터 삭제, 비밀정보 출력, ingest 재실행, 대형 모델 기동, push를 하지 않는다.

### Claude Code

Claude는 기본적으로 리뷰어/기획자 역할이다.

주요 역할:

- 요구사항 정리
- diff 리뷰
- 운영 리스크 분석
- 테스트 계획 검토
- Codex 구현 결과 검토

Claude는 사용자가 명시하지 않는 한 구현/커밋/push를 하지 않는다.

---

## 4. 접속과 작업 시작 절차

### 4.1 DGX 접속

```bash
ssh ai-hang@100.88.5.57
```

또는 프로젝트 루트로 바로 진입:

```bash
ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot; bash -l"
```

### 4.2 작업 전 반드시 확인

```bash
cd /srv/shared/projects/insurance-rag-chatbot
pwd
git status --short
git branch --show-current
git log --oneline -5
```

예상 기준:

```text
pwd -> /srv/shared/projects/insurance-rag-chatbot
branch -> master
```

`git status --short`에 이미 변경이 있으면 절대 되돌리지 말고 먼저 사용자/총괄 Codex에게 보고한다. 이 저장소는 여러 에이전트와 팀원이 공유하므로, 내가 만들지 않은 변경은 사용자 또는 다른 참여자의 작업으로 간주한다.

### 4.3 이 채팅에서의 원격 개발 방식

Codex가 맥북의 로컬 터미널에서 실행되는 상황이라도, 이 프로젝트의 실제 개발 명령은 SSH를 통해 DGX에서 수행한다.

read-only 확인 예:

```bash
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && git status --short"
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && sed -n '1,220p' src/rag/pipeline.py"
```

테스트 예:

```bash
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && source .venv/bin/activate && pytest -q"
```

파일 수정은 가능하면 작은 patch 단위로 수행하고, 수정 후에는 반드시 `git diff --check`와 관련 테스트를 실행한다. 로컬 맥북 저장소에서 같은 파일을 고쳐 DGX와 수동으로 맞추는 방식은 혼선을 만들기 쉬우므로 사용하지 않는다.

### 4.4 Python 환경

기본 앱/테스트 환경:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
```

SGLang 전용 환경:

```bash
source /srv/shared/projects/insurance-rag-chatbot/.venv-sglang/bin/activate
```

vLLM 전용 환경:

```bash
source /srv/shared/projects/insurance-rag-chatbot/.venv-vllm/bin/activate
```

일반 코드 테스트는 `.venv`를 사용한다. `.venv-sglang`, `.venv-vllm`은 대형 모델 서버 운영용이다.

---

## 5. 주요 경로

### 프로젝트와 데이터

```text
/srv/shared/projects/insurance-rag-chatbot
/srv/shared/projects/insurance-rag-chatbot/data/processed/chunks.jsonl
/srv/shared/projects/insurance-rag-chatbot/data/index/chroma
/srv/shared/projects/insurance-rag-chatbot/data/index/bm25.pkl
/srv/shared/projects/insurance-rag-chatbot/data/index/relational
```

### AI 운영 경로

```text
/srv/ai-ops
/srv/ai-ops/bin
/srv/ai-ops/logs
/srv/ai-ops/llm/models
/srv/ai-ops/secrets
```

### 비밀정보

```text
/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
```

이 파일은 값 출력 금지다. 키 이름만 확인할 때도 값을 마스킹한다.

예:

```bash
grep -nE 'OPENAI|CLOVA|APP_PASSWORD|OLLAMA|SGLANG|VLLM' /srv/ai-ops/secrets/insurance-rag-chatbot/env.sh | sed 's/=.*/=<hidden>/'
```

---

## 6. 운영 wrapper

공용 실행/점검 wrapper는 `/srv/ai-ops/bin`에 있다.

주요 wrapper:

```text
/srv/ai-ops/bin/run-insurance-rag
/srv/ai-ops/bin/check-insurance-rag
/srv/ai-ops/bin/check-ollama
/srv/ai-ops/bin/run-sglang-local
/srv/ai-ops/bin/check-sglang-local
/srv/ai-ops/bin/switch-sglang-model
/srv/ai-ops/bin/switch-vllm-model
/srv/ai-ops/bin/check-vllm-gemma4
/srv/ai-ops/bin/codex-task
/srv/ai-ops/bin/claude-review
```

주의:

- `run-*`, `switch-*`, `check-vllm-*`은 모델 서버나 Streamlit을 실제로 기동/점검할 수 있다.
- 대형 모델은 unified memory를 크게 점유한다.
- 팀원이 Spark를 사용 중이면 대형 모델 기동/전환을 임의 실행하지 않는다.
- 사용자가 “LLM 서버 호출 최소화” 또는 “모델 실행 금지”라고 하면 절대 호출하지 않는다.

---

## 7. Streamlit 앱 운영

앱 실행:

```bash
/srv/ai-ops/bin/run-insurance-rag
```

운영 시 tmux 권장:

```bash
tmux new -s insurance-rag
/srv/ai-ops/bin/run-insurance-rag
```

tmux detach:

```text
Ctrl+B, D
```

재접속:

```bash
tmux attach -t insurance-rag
```

포트 충돌 확인:

```bash
ss -ltnp | grep 8501
```

앱 접속 터널:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

---

## 8. LLM Provider 구조

현재 앱은 provider와 model을 분리해서 다룬다.

Provider:

```text
Ollama
SGLang
vLLM
OpenAI Cloud
```

운영 기준:

- Ollama: `exaone3.5:7.8b`, 안정 fallback
- SGLang: `gpt-oss-20b`, 로컬 OpenAI-compatible endpoint
- vLLM: `gemma-4-26b-a4b-nvfp4`, Gemma4 NVFP4 운영 경로
- OpenAI Cloud: offline mode에서는 숨김/사용 금지

중요 결정:

- `nvidia/Gemma-4-26B-A4B-NVFP4`는 SGLang에서 `<pad>` 반복 문제가 있어 SGLang provider에서는 비활성화했다.
- Gemma4는 vLLM provider에서 정상 한국어 응답까지 확인했다.
- 대형 모델은 동시에 여러 개 상주시키지 않는 것을 기본으로 한다. `switch-sglang-model`과 `switch-vllm-model`은 서로 반대쪽 세션을 내리도록 설계되어 있다.

대형 모델 전환:

```bash
/srv/ai-ops/bin/switch-sglang-model gpt-oss-20b
/srv/ai-ops/bin/check-sglang-local
```

```bash
/srv/ai-ops/bin/switch-vllm-model gemma-4-26b-a4b-nvfp4
/srv/ai-ops/bin/check-vllm-gemma4
```

위 명령은 실제 모델을 로드하므로 사용자 승인 없이 실행하지 않는다.

---

## 9. RAG 파이프라인 현재 구조

핵심 파일:

```text
src/rag/pipeline.py
src/rag/evidence.py
src/rag/quick_code.py
src/rag/insurance_form.py
src/retrieval/vector_store.py
src/retrieval/bm25.py
src/retrieval/reranker.py
src/llm/factory.py
src/llm/openai_compatible_client.py
src/ui/streamlit_app.py
```

최근 보강 사항:

- `RagPipeline.build_prompt()`로 일반 `answer()`와 Streamlit streaming prompt 조립을 통합했다.
- 문서별 비교 질의에서 요청 문서가 최종 검색 후보에서 누락되지 않도록 doc coverage 보강을 추가했다.
- strict evidence context와 evidence warning을 일반 RAG, 퀵 코드, 약관 정형 검색에 더 일관되게 적용했다.
- 로봇 수술처럼 문서별 코드가 다른 케이스에서 값을 임의 통일하지 않도록 guardrail을 추가했다.

남은 핵심 과제:

- 심평원 대형 표의 row-level direct lookup/index가 아직 부족하다.
- `식도조루술`, `요실금수술 접근법별 코드`처럼 특정 표 행이 필요한 질의는 dense/BM25/RRF만으로 불안정할 수 있다.
- 후속으로 심평원 수가표를 `분류번호`, `코드`, `항목명`, `점수`, `page`, `row_text` 단위로 parquet/sqlite 색인화하는 작업이 필요하다.

---

## 10. 테스트와 검증

일반 코드 변경 후 기본 검증:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
pytest -q
```

최근 정상 기준:

```text
276 passed, 3 warnings
```

검색 회귀 검증:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false python scripts/eval.py --ocr
```

정상 기준:

```text
recall@8 = 1.000
```

대형 모델 RAG 품질 평가:

```bash
python scripts/eval_large_model_rag.py --models gpt-oss-20b --label <label>
```

주의:

- `eval_large_model_rag.py`는 실제 LLM endpoint를 호출할 수 있다.
- 대형 모델 평가 전에는 현재 어떤 모델 서버가 떠 있는지 확인하고, 팀원 작업과 충돌하지 않도록 사용자 승인을 받는다.

---

## 11. Git 작업 규칙

작업 전:

```bash
git status --short
git branch --show-current
git log --oneline -5
```

수정 후:

```bash
git diff --stat
git diff --check
pytest -q
```

커밋은 사용자가 요청했거나 작업 명세에 명시된 경우에만 한다.

```bash
git add <files>
git commit -m "<type(scope): summary>"
```

push도 사용자가 명시적으로 요청한 경우에만 한다.

```bash
git push origin master
```

이 프로젝트에서는 사용자가 직접 `master` push를 지시한 이력이 있다. 하지만 매번 자동으로 push하지 않는다. 새 작업에서는 사용자의 최신 지시를 우선한다.

---

## 12. 절대 Git에 넣지 말 것

다음은 commit 금지다.

```text
.env
.env.*
users.json
users.json.tmp
CLOVA_OCR_CUSTOM_API_EXTERNAL*.json
logs/
data/chat_history/
raw/
backup/
backups/
*.pdf
*.xlsx
*.xls
data/extracted/
data/extracted_v2_manual/
data/index/chroma/
data/index/relational/*.sqlite
*.sqlite
*.db
.venv/
.venv-sglang/
.venv-vllm/
__pycache__/
.pytest_cache/
.ai-ops/
handoff/
handoff/llm_stage*_*/downloads/models/
```

모델 파일, wheelhouse, tarball, OCR 대량 산출물은 별도 handoff 또는 `/srv/ai-ops` 운영 경로에서 다룬다. GitHub에 올리지 않는다.

---

## 13. 민감정보 규칙

절대 출력하지 말 것:

```text
Discord Bot token
OpenAI API key
CLOVA OCR secret
APP_PASSWORD
users.json password hash
Tailscale auth key
개인 Codex/Claude OAuth token
```

`env.sh` 내용을 확인해야 하면 key 이름만 보고 값은 마스킹한다.

금지:

```bash
cat /srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
cat users.json
```

허용 예:

```bash
grep -nE 'SGLANG|VLLM|OLLAMA|OFFLINE|EMBEDDING|RERANKER' /srv/ai-ops/secrets/insurance-rag-chatbot/env.sh | sed 's/=.*/=<hidden>/'
```

---

## 14. 개인 에이전트와 공용 에이전트

팀원 개인 개발은 각자 Linux 계정과 개인 workspace에서 수행한다.

권장 개인 workspace:

```text
/srv/shared/workspaces/<user>/insurance-rag-chatbot
```

개인 에이전트는 개인 계정에서만 로그인한다.

```bash
whoami
codex login
claude auth
```

금지:

- `ai-hang` 공용 계정에 개인 Codex/Claude 로그인
- 개인 token을 `/srv/shared` 또는 `/srv/ai-ops`에 저장
- 공용 secrets 접근
- 공용 운영 repo 직접 수정

공용 agent wrapper:

```text
/srv/ai-ops/bin/codex-task
/srv/ai-ops/bin/claude-review
```

공용 wrapper는 리뷰/검증/제한된 구현 요청에 사용한다.

---

## 15. Discord 협업 구조

Discord는 작업 요청, 리뷰 요청, 로그 공유, 공용 agent 호출 창구로 설계되어 있다.

현재 관련 문서:

```text
docs/DISCORD_HARNESS_RUNBOOK.md
docs/PERSONAL_AGENT_WORKFLOW.md
```

초기 MVP 설계:

```text
Discord channel
  -> Discord Bot
  -> DGX manager/harness
  -> /srv/ai-ops/bin/codex-task 또는 claude-review 또는 check-insurance-rag
  -> 결과 요약을 Discord로 보고
```

보안 정책:

- 허용 channel 제한
- 허용 user/role 제한
- arbitrary shell 실행 금지
- sudo 금지
- secret 출력 금지
- git commit/push 자동화 금지
- 긴 로그 출력 제한
- 작업 queue/timeout 필요

---

## 16. 자주 하는 작업 예시

### 16.1 read-only 코드 조사

```bash
cd /srv/shared/projects/insurance-rag-chatbot
rg -n "RagPipeline|build_prompt|evidence" src tests docs
sed -n '1,220p' src/rag/pipeline.py
```

### 16.2 작은 코드 수정 후 테스트

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
pytest tests/test_pipeline.py tests/test_evidence.py -q
pytest -q
```

### 16.3 Streamlit 포트 사용 확인

```bash
ss -ltnp | grep 8501
```

프로세스 종료는 사용자가 명시한 경우에만 한다.

### 16.4 대형 모델 상태 확인

실제 모델 서버 호출이므로 사용자 승인 후에만 실행한다.

```bash
/srv/ai-ops/bin/check-sglang-local
/srv/ai-ops/bin/check-vllm-gemma4
```

---

## 17. 현재 주요 문서 읽기 순서

새 에이전트는 작업 전 아래 순서로 읽는다.

1. `docs/DGX_SPARK_RUNBOOK.md`
2. `docs/AI_REVIEWER_GUIDE.md`
3. `docs/PERSONAL_AGENT_WORKFLOW.md`
4. `docs/85_GEMMA4_VLLM_PROVIDER_IMPL_REPORT.md`
5. `docs/86_RAG_GROUNDING_LOGIC_IMPL_REPORT.md`
6. 해당 작업과 직접 관련된 `docs/*CODEX_SPEC*` 또는 구현 보고서

---

## 18. 현재 알려진 위험과 후속 과제

### 18.1 심평원 표 row-level retrieval

현재 가장 중요한 품질 과제다.

증상:

- 식도조루술 코드/점수 질의에서 기대 페이지/행을 놓칠 수 있음
- 요실금수술 접근법별 코드에서 일부 코드 누락 또는 유사 행 혼입 가능

원인:

- dense/BM25/RRF chunk retrieval만으로 대형 표의 특정 행을 안정적으로 찾기 어렵다.

권장 해결:

- 심평원 표를 row 단위 구조화 index로 분리
- 필드: `doc_short`, `page`, `classification_no`, `code`, `name`, `score`, `row_text`, `source_file`
- 코드/수가/점수/접근법별 질의에서는 row index를 우선 조회
- 근거가 없으면 LLM 생성 전에 fail-closed 응답

### 18.2 대형 모델 평가 일반화

현재 평가 harness는 SGLang 중심 흔적이 남아 있다. vLLM/Gemma4까지 정기 평가하려면 provider별 base URL, switch command, health check를 일반화해야 한다.

### 18.3 완전 오프라인 운영

완전 오프라인 환경에서는 아래가 로컬 경로에서만 로드되어야 한다.

```text
embedding model
reranker model
Ollama model
SGLang model
vLLM model
wheelhouse/dependency artifacts
```

`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `OFFLINE_MODE=true` 조건에서 회귀 검증이 필요하다.

---

## 19. 작업 보고 형식

작업 완료 보고에는 최소한 아래를 포함한다.

```text
변경 파일:
- ...

핵심 변경:
- ...

검증:
- command: result

미수행:
- LLM 서버 호출 미수행 등

위험/후속:
- ...
```

코드 개발 계획 또는 수정 명세서를 기반으로 구현을 완료했다면 `docs/`에 간결한 구현 보고서를 추가한다.

---

## 20. 새 에이전트 첫 행동 체크리스트

1. `ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot; bash -l"`
2. `git status --short`
3. `git log --oneline -5`
4. 이 문서와 관련 runbook/spec 읽기
5. 작업 범위를 사용자/총괄 Codex 지시와 대조
6. 내가 만들지 않은 변경이 있으면 보고
7. 필요한 파일만 수정
8. 관련 테스트 실행
9. 문서 보고 필요 여부 판단
10. commit/push는 명시 지시가 있을 때만 수행

---

## 21. 자체 검토 메모

이 문서는 다음 기준으로 자체 점검했다.

- DGX 원격 개발 기준을 최상단에 명시했는가: 예
- SSH 접속, Streamlit 터널, tmux, wrapper 사용법을 포함했는가: 예
- secret과 Git 금지 항목을 명확히 적었는가: 예
- 현재 LLM provider 구조와 Gemma4/vLLM 예외를 반영했는가: 예
- 최근 RAG grounding 개선과 남은 row-level retrieval 과제를 반영했는가: 예
- 새 에이전트가 첫 행동부터 검증/보고까지 따를 수 있는가: 예
- push/모델 실행/ingest/삭제 같은 위험 작업 제한을 명시했는가: 예
