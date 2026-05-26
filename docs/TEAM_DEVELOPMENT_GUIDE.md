# 팀 개발 통합 가이드

작성일: 2026-05-18
프로젝트: insurance-rag-chatbot
DGX Host: aitopatom-255d
Tailscale IP: 100.88.5.57

---

## 1. 문서 목적

이 문서는 DGX Spark 기반 `insurance-rag-chatbot` 프로젝트에서 관리자와 팀원이 공통으로 참고하는 실무형 통합 가이드다.

**이 문서 하나로 다음을 이해할 수 있어야 한다.**

- 개인 workspace와 공용 운영 repo의 역할 분리
- Discord Bot 기반 공용 에이전트 사용법
- 수정 → 리뷰 → 검증 → 커밋 흐름
- 금지 사항과 사고 대응 절차

관련 상세 문서:

- [DGX_SPARK_RUNBOOK.md](./DGX_SPARK_RUNBOOK.md) — 운영 환경 상세
- [127_DGX_SPARK_TEAM_PULL_AND_SPA_RUN_GUIDE.md](./127_DGX_SPARK_TEAM_PULL_AND_SPA_RUN_GUIDE.md) — 팀원이 GitHub `master` pull 후 개인 workspace에서 FastAPI + SPA 버전을 실행하는 절차
- [AI_REVIEWER_GUIDE.md](./AI_REVIEWER_GUIDE.md) — Claude 리뷰어 역할
- [PERSONAL_AGENT_WORKFLOW.md](./PERSONAL_AGENT_WORKFLOW.md) — 팀원 개인 에이전트 규칙
- [DISCORD_HARNESS_RUNBOOK.md](./DISCORD_HARNESS_RUNBOOK.md) — Discord Bot 상세

---

## 2. 전체 아키텍처

```
팀원 (dani, eundeo, ihyun)
│
│  VS Code Remote SSH  →  개인 Linux 계정
│  개인 workspace: /srv/shared/workspaces/<user>/insurance-rag-chatbot
│  개인 Codex / Claude Code Extension
│  개인 branch에서 작업
│
│  ↓ Discord로 리뷰/반영 요청
│
Discord Bot (#dgx-ops 채널)
│
├── /status, /repo-diff, /repo-guard        → 상태 확인 (read-only)
├── /codex                                  → read-only 조사/요약
├── /claude                                 → 리뷰/리스크 분석
├── /codex-apply                            → 공용 repo 직접 수정
└── /apply-from-workspace                   → 팀원 workspace → 공용 repo 반영
│
└── /srv/ai-ops/bin wrappers (ai-hang 계정)
        codex-task / codex-apply-task / claude-review
        │
        ├── 공용 repo: /srv/shared/projects/insurance-rag-chatbot
        ├── Streamlit (127.0.0.1:8501)
        ├── Ollama (exaone3.5:7.8b)
        └── Chroma (count: 7825)
```

---

## 3. 역할 분담

### 관리자 (ai-hang)

| 역할 | 설명 |
|------|------|
| 공용 운영 repo 상태 관리 | 공용 repo의 최종 상태 책임 |
| Discord Bot 관리 | run-discord-harness 실행/재시작 |
| Streamlit 앱 운영 | run-insurance-rag 실행/재시작 |
| secrets 권한 관리 | /srv/ai-ops/secrets 접근 권한 통제 |
| 공용 에이전트 wrapper 관리 | /srv/ai-ops/bin 스크립트 관리 |
| 최종 commit/push 판단 | 팀원 작업 반영 후 커밋 결정 |
| generated data 정책 결정 | index/eval 변경 커밋 여부 판단 |

### 팀원 개발자 (dani, eundeo, ihyun)

| 역할 | 설명 |
|------|------|
| 개인 계정으로 접속 | 반드시 자기 Linux 계정으로 SSH |
| 개인 workspace에서 작업 | /srv/shared/workspaces/<user>/ |
| 공용 repo 직접 수정 금지 | /srv/shared/projects 직접 편집 불가 |
| 개인 에이전트 사용 | 개인 Codex / Claude Extension |
| 작업 공유 | Discord에 작업 요약 전달 |
| 반영 요청 | /apply-from-workspace 사용 |

### 공용 에이전트

| 에이전트 | 역할 | 수정 가능 여부 |
|----------|------|----------------|
| /codex | 조사/요약 (read-only) | 아니오 |
| /claude | 리뷰/리스크 분석 | 아니오 |
| /codex-apply | 공용 repo 직접 수정 | 예 (commit/push는 사람이) |
| /apply-from-workspace | 팀원 workspace → 공용 repo 반영 | 예 (commit/push는 사람이) |

> **원칙**: 공용 에이전트는 자동 commit/push를 하지 않는다. 항상 사람이 최종 확인 후 커밋한다.

---

## 4. 기본 접속 절차

### SSH 접속

```bash
ssh <user>@100.88.5.57
```

접속 후 반드시 확인:

```bash
whoami   # 자기 계정인지 확인
```

### VS Code Remote SSH

1. VS Code에서 Remote SSH 확장 설치
2. `aitopatom-255d` 또는 `100.88.5.57` 로 연결
3. **자기 계정으로 접속했는지 확인**
4. 폴더 열기 시 공용 repo가 아닌 **개인 workspace**를 열 것

```
개인 workspace: /srv/shared/workspaces/<user>/insurance-rag-chatbot
공용 repo (직접 편집 금지): /srv/shared/projects/insurance-rag-chatbot
```

### Streamlit 앱 접속

로컬 SSH 터널을 열고:

```bash
ssh -L 8501:localhost:8501 <user>@100.88.5.57
```

브라우저에서:

```
http://localhost:8501
```

8501 포트가 이미 사용 중이면 다른 포트로 포워딩:

```bash
ssh -L 8502:localhost:8501 <user>@100.88.5.57
# 브라우저: http://localhost:8502
```

---

## 5. 개인 workspace 생성

### 최초 생성

```bash
mkdir -p /srv/shared/workspaces/$USER
cd /srv/shared/workspaces/$USER
git clone https://github.com/koreaben777/insurance-rag-chatbot.git
cd insurance-rag-chatbot
git checkout -b feature/$USER/<task-name>
```

### workspace 경로 기준

```
/srv/shared/workspaces/dani/insurance-rag-chatbot
/srv/shared/workspaces/eundeo/insurance-rag-chatbot
/srv/shared/workspaces/ihyun/insurance-rag-chatbot
```

### dubious ownership 오류

**원인**: 다른 사용자가 소유한 repo를 현재 계정이 조작하려 할 때 발생.

```
fatal: detected dubious ownership in repository at '...'
```

**해결 원칙**:

- 반드시 해당 repo를 소유한 사용자 계정으로 접속해서 작업한다.
- 타인의 workspace를 다른 계정으로 직접 조작하지 않는다.
- 관리자가 임시로 확인해야 하는 경우에만 아래 명령 사용 가능:

```bash
git config --global --add safe.directory /srv/shared/workspaces/<user>/insurance-rag-chatbot
```

> **주의**: 이 명령은 임시 확인 목적으로만 사용한다. 다른 팀원의 workspace를 정기적으로 조작하는 용도로 사용하지 않는다.

---

## 6. 개인 에이전트 사용법

팀원은 VS Code Extension을 통해 개인 Codex / Claude Code를 사용한다.

### 정책

| 항목 | 규칙 |
|------|------|
| 계정 | 개인 ChatGPT Plus / Claude Pro 계정 각자 사용 |
| 토큰 저장 위치 | `/home/<user>/` 아래에만 저장 |
| 금지 저장 위치 | `/srv/shared`, `/srv/ai-ops` 아래 저장 금지 |
| 교차 로그인 금지 | ai-hang 계정에서 개인 계정 로그인 금지 |
| secrets 노출 금지 | 공용 secrets를 개인 에이전트에 전달 금지 |
| CLI 설치 | 필수 아님. Extension 중심 사용 |

### 개인 에이전트 작업 범위

- 자기 workspace의 코드/문서 수정
- 자기 개인 workspace 안의 개인 branch에서만 git add/commit 가능
- 공용 운영 repo에서는 팀원이 직접 git add/commit하지 않음
- 공용 repo에 대한 read 조회

### 개인 에이전트 작업 금지

- 공용 repo(`/srv/shared/projects/`) 직접 수정
- `/srv/ai-ops/` 경로 조작
- secrets 파일 열람
- 타인 workspace 조작

---

## 7. 공용 Discord Bot 명령어

### 명령어 목록

| 명령 | 용도 | 수정 가능 여부 |
|------|------|----------------|
| `/help` | 명령어 안내 | 아니오 |
| `/rag` | Streamlit 접속 안내 | 아니오 |
| `/status` | DGX 상태 확인 | 아니오 |
| `/workflow` | 협업 흐름 안내 | 아니오 |
| `/agent-policy` | 보안 정책 안내 | 아니오 |
| `/workspace` | workspace 생성 안내 | 아니오 |
| `/logs` | 로그 경로 안내 | 아니오 |
| `/codex` | read-only Codex 조사/요약 | 아니오 |
| `/claude` | Claude 리뷰/리스크 분석 | 아니오 |
| `/codex-apply` | 공용 repo 직접 수정 | 예 |
| `/apply-from-workspace` | 팀원 workspace 변경 공용 repo 반영 | 예 |
| `/repo-diff` | 공용 repo diff 요약 | 아니오 |
| `/repo-guard` | protected path 변경 감지 | 아니오 |

### 실무 예시

**저장소 상태 요약 (read-only)**

```
/codex task: 현재 저장소 상태를 한 문단으로 요약해줘. 파일은 수정하지 마. model: gpt-5.4 reasoning: low
```

**코드 리뷰 요청**

```
/claude task: 현재 git diff를 리뷰하고 커밋 가능 여부를 판단해줘. 파일은 수정하지 마. model: sonnet
```

**공용 repo 직접 수정 (소규모)**

```
/codex-apply task: docs/TEAM_DEVELOPMENT_GUIDE.md의 오타만 수정해줘. 다른 파일은 수정하지 말고 git add, commit, push는 하지 마. model: gpt-5.4 reasoning: low
```

**팀원 workspace 변경 반영**

```
/apply-from-workspace user: eundeo branch: feature/eundeo/foo task: 팀원 workspace의 변경을 검토하고 필요한 부분만 공용 repo에 반영해줘. git add, commit, push는 하지 마. model: gpt-5.4 reasoning: low
```

**상태 확인**

```
/status
/repo-diff
/repo-guard
```

---

## 8. 표준 개발 흐름

### A. 개인 작업 흐름 (팀원 기준)

```
1. 개인 workspace에서 branch 생성
   git checkout -b feature/$USER/<task-name>

2. VS Code Extension으로 개인 Codex/Claude 사용하여 코드/문서 수정

3. 가능한 범위의 로컬 확인

4. Discord에 작업 내용 요약 공유

5. /apply-from-workspace로 공용 repo 반영 요청
   /apply-from-workspace user: <user> branch: feature/<user>/<task> task: ...

6. /repo-diff 로 변경 내용 확인

7. /repo-guard 로 protected path 변경 감지

8. /claude 로 리뷰 요청

9. 사람(관리자)이 최종 확인 후 commit/push
```

### B. 공용 repo 직접 수정 흐름 (소규모 수정)

```
1. /codex-apply 로 단위 수정 요청
   (git add, commit, push 금지 명시)

2. /repo-diff 로 변경 내용 확인

3. /repo-guard 로 protected path 감지

4. /claude 로 리뷰

5. 필요 시 수동 추가 수정

6. 관리자가 stage 확인 후 commit/push
```

### C. 리뷰 중심 흐름

```
1. /codex 로 현재 상태 요약

2. /claude 로 리스크/커밋 가능성 리뷰

3. 사람이 승인 판단

4. commit/push
```

---

## 9. Git 정책

### 현재 공용 repo 보류 변경

현재 공용 repo에는 다음 변경이 보류 상태일 수 있다:

```
M data/index/bm25.pkl
M data/processed/chunks.jsonl
M eval/smoke_qa_v2.jsonl
```

| 파일 | 정책 |
|------|------|
| `data/index/bm25.pkl` | 생성물/바이너리 인덱스 — 커밋 보류 |
| `data/processed/chunks.jsonl` | 생성물/대용량 데이터 — 커밋 보류 |
| `eval/smoke_qa_v2.jsonl` | 평가셋 수정 — 별도 검토 후 커밋 가능 |

### 커밋 전 필수 절차

문서/코드 변경을 커밋할 때는 반드시 파일을 명시적으로 stage:

```bash
git add docs/TEAM_DEVELOPMENT_GUIDE.md
git diff --cached --name-only
```

출력에 **의도한 파일만** 있어야 한다. 불필요한 파일이 포함되면 커밋하지 않는다.

### 커밋 금지 항목

> **절대 커밋하지 않는다:**

- `git add .` 또는 `git add -A` 무심코 사용
- generated data (data/index/, data/processed/) 함께 커밋
- raw PDF/XLSX 파일 커밋
- secret, env 파일 커밋
- 타인의 workspace 파일 커밋

---

## 10. Protected Path 정책

### 수정/커밋 주의 또는 금지 경로

```
.env
.env.*
users.json
users.json.tmp
CLOVA_OCR_CUSTOM_API_EXTERNAL*.json
raw/
*.pdf
*.xlsx
*.xls
data/extracted/
data/extracted_v2_manual/
data/index/
data/chat_history/
logs/
.ai-ops/
.venv/
```

### /repo-guard 사용법

```
/repo-guard
```

**결과 해석**:

| 상황 | 대응 |
|------|------|
| `data/index/bm25.pkl` warning | 현재 알려진 보류 변경 — 예상 가능, 무시 가능 |
| 새로운 protected path 변경 감지 | 반드시 사람이 원인 확인 후 처리 |
| `.env`, `users.json` 등 감지 | 즉시 커밋 금지, 원인 분석 |

---

## 11. 테스트/검증 절차

### 운영 상태 확인 (관리자)

```bash
/srv/ai-ops/bin/check-insurance-rag
/srv/ai-ops/bin/check-discord-harness
```

### Discord 상태 확인 (전체)

```
/status
/repo-diff
/repo-guard
```

### 앱 직접 확인

1. SSH 터널 후 `http://localhost:8501` 접속
2. 질문 입력 테스트
3. 로컬 Ollama 답변 생성 확인

### 정상 기준

```
Ollama model:         exaone3.5:7.8b
Chroma count:         7825
retrieval recall@8:   1.000
Streamlit:            http://127.0.0.1:8501
```

### eval 실행 (관리자 판단)

```bash
cd /srv/shared/projects/insurance-rag-chatbot
python scripts/eval.py --ocr
```

환경에 따라 `HF_MODEL_DOWNLOAD`, `RERANKER_ENABLED`, `OLLAMA_HOST` 등을 앞에 붙여 실행할 수 있다.

---

## 12. Streamlit / Discord Bot 운영

### Streamlit 시작

먼저 기존 세션 여부를 확인한다:

```bash
tmux ls
```

기존 세션이 있으면 재접속:

```bash
tmux attach -t insurance-rag
```

기존 세션이 없을 때만 새로 생성:

```bash
tmux new -s insurance-rag
/srv/ai-ops/bin/run-insurance-rag
```

### Discord Bot 시작

먼저 기존 세션 여부를 확인한다:

```bash
tmux ls
```

기존 세션이 있으면 재접속:

```bash
tmux attach -t discord-harness
```

기존 세션이 없을 때만 새로 생성:

```bash
tmux new -s discord-harness
/srv/ai-ops/bin/run-discord-harness
```

> **원칙**: 기존 세션이 없을 때만 `tmux new -s ...`를 사용한다. 기존 세션이 있으면 `tmux attach -t ...`로 재접속한다. 세션을 중복 생성하면 `duplicate session` 오류가 발생한다.

### tmux 조작

| 동작 | 명령 |
|------|------|
| 세션 유지하고 나가기 (detach) | `Ctrl + B`, `D` |
| 세션 목록 확인 | `tmux ls` |
| insurance-rag 세션 재접속 | `tmux attach -t insurance-rag` |
| discord-harness 세션 재접속 | `tmux attach -t discord-harness` |

### 로그 경로

```
/srv/ai-ops/logs/codex/          # codex-task 전체 로그
/srv/ai-ops/logs/codex-apply/    # codex-apply-task 전체 로그
/srv/ai-ops/logs/claude/         # claude-review 전체 로그
/srv/ai-ops/logs/discord/        # Discord bot 로그
```

### Secrets 경로 (경로만, 내용 열람 금지)

```
/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh
/srv/ai-ops/secrets/discord-harness/env.sh
```

> **보안 원칙**: secrets 파일의 경로만 참고한다. 파일 내용은 관리자만 접근하며, Discord나 어떤 채널에도 출력하지 않는다.

---

## 13. 보안 규칙

> 이 규칙들은 전체 팀원과 에이전트에 공통 적용된다.

### 절대 금지

| 금지 행위 | 이유 |
|-----------|------|
| secrets 값 출력 | 노출 시 즉각적인 보안 사고 |
| `/srv/ai-ops/secrets` 직접 열람 (팀원) | 권한 분리 원칙 |
| Bot token 노출 | 노출 즉시 Discord Bot 탈취 가능 |
| 개인 token을 `/srv/shared`, `/srv/ai-ops`에 저장 | 공용 서버 오염 |
| Discord에서 secret/env 값 요청 | 채널 로그에 남음 |
| 자동 commit/push | 검증 없는 변경 반영 |
| `git add .` 또는 `git add -A` | 의도치 않은 파일 포함 |
| `sudo` 무단 사용 | 시스템 권한 침해 |
| `rm -rf` 대규모 삭제 | 복구 불가 데이터 손실 |
| `--dangerously-bypass-approvals-and-sandbox` | 에이전트 안전장치 우회 |
| `--yolo` 옵션 | 에이전트 안전장치 우회 |
| 공용 repo 직접 수정 (팀원) | 검증 없는 운영 repo 오염 |

### 사고 발생 시

- **Bot token 노출**: 즉시 Discord Developer Portal에서 token reset → 관리자에게 보고
- **secrets 파일 유출**: 관리자에게 즉시 보고 → 해당 서비스 credential 교체
- **의도치 않은 파일 커밋**: 커밋 되돌리기 전에 반드시 관리자와 상의

---

## 14. 장애 대응

### Discord 명령어가 서버에 안 보임

```bash
/srv/ai-ops/bin/check-discord-harness
```

로그에서 `Synced 13 commands` 확인. 안 보이면:

1. Discord 앱에서 `Cmd + R` (Mac) 또는 `Ctrl + R` (Windows/Linux) 새로고침
2. `bot.py`의 `setup_hook()` 내 `copy_global_to` 설정 확인
3. Discord Developer Portal에서 명령어 등록 상태 확인

### Discord Bot이 응답 없음 / 종료됨

기존 세션에 재접속해서 상태 확인:

```bash
tmux attach -t discord-harness
```

세션 자체가 죽었으면 재생성:

```bash
tmux kill-session -t discord-harness 2>/dev/null || true
tmux new -s discord-harness
/srv/ai-ops/bin/run-discord-harness
```

### Streamlit 앱이 꺼짐

```bash
tmux attach -t insurance-rag
/srv/ai-ops/bin/run-insurance-rag
```

### dubious ownership 오류

```
fatal: detected dubious ownership in repository at '...'
```

→ 해당 repo 소유자의 계정으로 SSH 재접속 후 작업.
→ 관리자 임시 확인 목적으로만 `git config --global --add safe.directory` 사용 가능.

### /codex-apply가 의도와 다른 수정 생성

1. 커밋하지 않는다.
2. `/repo-diff` 로 변경 범위 확인
3. `/repo-guard` 로 protected path 침범 여부 확인
4. 수동으로 되돌리기 (`git checkout -- <file>` 또는 `git restore <file>`)
5. 필요 시 `/claude` 에 리뷰 요청

### Protected path warning 발생

1. 기존 보류 변경(`data/index/bm25.pkl` 등)인지 확인
2. 기존 보류 변경이면 → 예상된 warning, 무시 가능
3. 새로운 protected 경로 변경이면 → 커밋 금지, 원인 분석 후 관리자 판단

---

## 15. OpenClaw 보류 상태

> 현재 OpenClaw는 사용하지 않는다.

Discord Harness와 공용 에이전트 흐름이 안정화된 후 별도 검토 예정.

현재 사용 중인 구조:

```
Discord Bot
→ /srv/ai-ops/bin wrappers (codex-task, codex-apply-task, claude-review)
→ Codex / Claude / Streamlit / Ollama
```

---

## 16. 최종 체크리스트

### 관리자 체크리스트

```
□ Discord Bot running (tmux ls에 discord-harness 확인)
□ Streamlit running (tmux ls에 insurance-rag 확인)
□ /status 정상
□ /repo-diff 확인
□ /repo-guard 확인 (기존 보류 변경만 있는지)
□ git diff --cached --name-only 로 stage 파일 확인
□ 의도한 파일만 stage된 경우에만 commit
□ secrets 권한 확인 (팀원이 접근하지 않았는지)
```

### 팀원 체크리스트

```
□ 개인 workspace에서 작업 중인지 확인
□ whoami 로 올바른 계정인지 확인
□ VS Code Extension이 개인 계정으로 로그인되어 있는지 확인
□ 공용 repo(/srv/shared/projects/) 직접 수정하지 않았는지 확인
□ 작업 요약을 Discord에 공유
□ 반영 요청은 /apply-from-workspace 사용
□ secret/env 값을 Discord나 코드에 포함하지 않았는지 확인
```

### 공용 에이전트 사용 체크리스트

```
□ /codex는 read-only — task에 "파일은 수정하지 마" 명시
□ /codex-apply는 공용 repo 직접 수정 — "git add, commit, push는 하지 마" 명시
□ /apply-from-workspace는 user, branch, task 파라미터 모두 명시
□ 수정 후 반드시 /repo-diff → /repo-guard → /claude 순서로 확인
□ 에이전트 결과 확인 후 사람이 최종 commit 결정
```

---

*이 문서는 [DGX_SPARK_RUNBOOK.md](./DGX_SPARK_RUNBOOK.md), [AI_REVIEWER_GUIDE.md](./AI_REVIEWER_GUIDE.md), [PERSONAL_AGENT_WORKFLOW.md](./PERSONAL_AGENT_WORKFLOW.md), [DISCORD_HARNESS_RUNBOOK.md](./DISCORD_HARNESS_RUNBOOK.md)를 요약·통합한 실무 가이드입니다.*
