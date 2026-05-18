# DGX Spark 개발 환경 셋업 정리

insurance-rag-chatbot 팀 운영·개발 환경 통합 요약

| **항목**     | **값**                                       |
|--------------|----------------------------------------------|
| 작성일       | 2026-05-18                                   |
| DGX Host     | aitopatom-255d                               |
| Tailscale IP | 100.88.5.57                                  |
| 프로젝트     | insurance-rag-chatbot                        |
| GitHub       | github.com/koreaben777/insurance-rag-chatbot |
| 운영 채널    | Discord #dgx-ops                             |

## 1. 요약

- DGX Spark를 팀 공용 개발·운영 서버로 구성했고, 팀원은 각자 Linux 계정과 개인 workspace에서 개발한다.

- 공용 운영 repo는 /srv/shared/projects/insurance-rag-chatbot에 있으며, 팀원은 직접 수정하지 않고 Discord 공용 에이전트 경로로 반영한다.

- Streamlit, Ollama, Chroma 기반 RAG 앱이 정상 동작하며, 현재 Chroma count 정상 기준은 7825다.

- Discord Bot은 #dgx-ops 채널에서 /status, /codex, /claude, /codex-apply, /apply-from-workspace 등 13개 명령을 제공한다.

- OpenClaw는 보류 중이며, 현재는 Discord Harness + /srv/ai-ops/bin wrappers 구조로 운영한다.

## 2. 완료된 셋업 범위

| **영역** | **완료 상태** | **비고** |
|----|----|----|
| 네트워크 | 완료 | Tailscale IP 100.88.5.57, SSH 접속 가능 |
| 계정/권한 | 완료 | 팀원별 Linux 계정 및 dgxdev 공유 그룹 기반 운영 |
| 프로젝트 코드 | 완료 | GitHub와 DGX 공용 repo 동기화, 문서 커밋 push 완료 |
| 데이터/인덱스 | 완료/보류 혼재 | Chroma 7825 정상. bm25.pkl, chunks.jsonl, smoke_qa_v2는 로컬 보류 변경 유지 |
| Python/Node | 완료 | 프로젝트 venv, Node/npm, Codex/Claude wrapper 운영 |
| Ollama | 완료 | exaone3.5:7.8b 로컬 모델 동작 |
| Streamlit | 완료 | 127.0.0.1:8501에서 실행, SSH 터널로 팀원 접속 |
| Discord Harness | 완료 | #dgx-ops에서 공용 에이전트 명령 사용 가능 |
| 개인 workspace | 완료 | dani, eundeo, ihyun workspace 생성 및 테스트 완료 |
| OpenClaw | 보류 | Discord Harness 안정화 후 별도 검토 |

## 3. 운영 아키텍처

```text
팀원 개인 개발
→ VS Code Remote SSH
→ 개인 Linux 계정
→ /srv/shared/workspaces/<user>/insurance-rag-chatbot
→ 개인 Codex / Claude Code Extension
→ 개인 branch 작업

공용 운영
→ ai-hang 관리자 계정
→ /srv/shared/projects/insurance-rag-chatbot
→ Streamlit / Ollama / Chroma / Tailscale
→ /srv/ai-ops/bin wrappers

Discord #dgx-ops
→ 상태 확인
→ read-only 조사/리뷰
→ 공용 repo 직접 수정
→ 팀원 workspace 변경 반영
→ 결과 공유 및 사람이 최종 commit/push
```

## 4. 핵심 경로

| **분류** | **경로** | **설명** |
|----|----|----|
| 공용 운영 repo | /srv/shared/projects/insurance-rag-chatbot | 운영 기준 repo. 관리자와 공용 에이전트가 관리 |
| 개인 workspace | /srv/shared/workspaces/<user>/insurance-rag-chatbot | 팀원 개인 개발 공간 |
| 운영 스크립트 | /srv/ai-ops/bin | run/check 및 Codex/Claude wrapper |
| Secrets | /srv/ai-ops/secrets | 관리자 전용. 값 출력 금지 |
| Codex 로그 | /srv/ai-ops/logs/codex | read-only Codex 실행 로그 |
| Codex apply 로그 | /srv/ai-ops/logs/codex-apply | 공용 repo 수정 작업 로그 |
| Claude 로그 | /srv/ai-ops/logs/claude | 리뷰 로그 |
| Discord 로그 | /srv/ai-ops/logs/discord | Bot 실행 로그 |

## 5. 역할과 책임

| **역할** | **책임** | **금지/주의** |
|----|----|----|
| 관리자 ai-hang | 공용 repo, secrets, Discord Bot, Streamlit/Ollama, 최종 commit/push 관리 | 무심코 git add . 금지. secrets 출력 금지 |
| 팀원 dani/eundeo/ihyun | 개인 workspace에서 개발, 개인 VS Code Extension 사용, Discord로 반영 요청 | 공용 repo 직접 편집 금지. 타인 workspace 조작 금지 |
| 공용 Codex | read-only 조사 또는 /codex-apply로 공용 repo 수정, /apply-from-workspace로 팀원 변경 반영 | 자동 git add/commit/push 금지. protected path 주의 |
| 공용 Claude | diff 리뷰, 리스크 분석, 커밋 가능성 판단 | 기본적으로 파일 수정 금지 |

## 6. 접속과 기본 사용

### 6.1 SSH 접속

```bash
ssh <user>@100.88.5.57
whoami
```

팀원은 반드시 자기 계정으로 접속해야 하며, 개인 workspace를 열어야 한다.

### 6.2 Streamlit 앱 접속

```bash
ssh -L 8501:localhost:8501 <user>@100.88.5.57
# 브라우저: http://localhost:8501
```

로컬 8501 포트가 이미 사용 중이면 8502 등 다른 로컬 포트를 사용한다.

```bash
ssh -L 8502:localhost:8501 <user>@100.88.5.57
# 브라우저: http://localhost:8502
```

## 7. 개인 workspace 운영

```bash
mkdir -p /srv/shared/workspaces/$USER
cd /srv/shared/workspaces/$USER
git clone https://github.com/koreaben777/insurance-rag-chatbot.git
cd insurance-rag-chatbot
git checkout -b feature/$USER/<task-name>
```

| **사용자** | **workspace 예시**                                  |
|------------|-----------------------------------------------------|
| dani       | /srv/shared/workspaces/dani/insurance-rag-chatbot   |
| eundeo     | /srv/shared/workspaces/eundeo/insurance-rag-chatbot |
| ihyun      | /srv/shared/workspaces/ihyun/insurance-rag-chatbot  |

dubious ownership 오류가 나면 다른 사용자의 repo를 현재 계정으로 조작한 것이다. 해당 workspace 소유자 계정으로 접속해 작업한다.

## 8. Discord Bot 명령어

| **명령** | **용도** | **수정 가능 여부** |
|----|----|----|
| /help | 명령어 안내 | 아니오 |
| /rag | Streamlit 접속 안내 | 아니오 |
| /status | DGX 상태 확인 | 아니오 |
| /workflow | 협업 흐름 안내 | 아니오 |
| /agent-policy | 보안 정책 안내 | 아니오 |
| /workspace | workspace 생성 안내 | 아니오 |
| /logs | 로그 경로 안내 | 아니오 |
| /codex | read-only 조사/요약/계획 | 아니오 |
| /claude | 리뷰/리스크 분석 | 아니오 |
| /codex-apply | 공용 repo 직접 수정 | 예 |
| /apply-from-workspace | 팀원 workspace 변경을 공용 repo에 반영 | 예 |
| /repo-diff | 공용 repo diff 요약 | 아니오 |
| /repo-guard | protected path 변경 감지 | 아니오 |

### 8.1 사용 예시

```text
/codex task: 현재 저장소 상태를 한 문단으로 요약해줘. 파일은 수정하지 마. model: gpt-5.4 reasoning: low
/claude task: 현재 git diff를 리뷰하고 커밋 가능 여부를 판단해줘. 파일은 수정하지 마. model: sonnet
/codex-apply task: docs/TEAM_DEVELOPMENT_GUIDE.md의 오타만 수정해줘. 다른 파일은 수정하지 말고 git add, commit, push는 하지 마. model: gpt-5.4 reasoning: low
/apply-from-workspace user: eundeo branch: feature/eundeo/foo task: 팀원 workspace의 변경을 검토하고 필요한 부분만 공용 repo에 반영해줘. git add, commit, push는 하지 마. model: gpt-5.4 reasoning: low
/repo-diff
/repo-guard
```

## 9. 표준 개발 흐름

### 9.1 개인 작업 → 공용 repo 반영

1.  팀원이 개인 workspace에서 branch를 생성한다.

2.  VS Code Extension의 개인 Codex/Claude로 개발한다.

3.  Discord에 작업 요약을 공유한다.

4.  /apply-from-workspace로 공용 repo 반영을 요청한다.

5.  /repo-diff로 변경 범위를 확인한다.

6.  /repo-guard로 protected path 변경을 확인한다.

7.  /claude로 diff 리뷰를 받는다.

8.  관리자가 최종 확인 후 수동 commit/push한다.

### 9.2 공용 repo 직접 수정

9.  /codex-apply로 작은 단위 수정 요청을 한다.

10. /repo-diff와 /repo-guard로 결과를 확인한다.

11. /claude로 리뷰한다.

12. 필요 시 사람이 수동 수정한다.

13. 관리자가 stage 파일을 확인하고 commit/push한다.

## 10. Git 정책

현재 공용 repo에는 다음 보류 변경이 남아 있을 수 있다.

| **파일**                    | **정책**                             |
|-----------------------------|--------------------------------------|
| data/index/bm25.pkl         | 생성물/바이너리 인덱스 — 커밋 보류   |
| data/processed/chunks.jsonl | 생성물/대용량 데이터 — 커밋 보류     |
| eval/smoke_qa_v2.jsonl      | 평가셋 수정 — 별도 검토 후 커밋 가능 |

```bash
# 문서/코드 커밋 시 파일을 명시적으로 stage
git add docs/TEAM_DEVELOPMENT_GUIDE.md
git diff --cached --name-only

# 금지: 무심코 git add . 또는 git add -A 사용
```

## 11. Protected Path 정책

```text
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

현재 data/index/bm25.pkl warning은 알려진 보류 변경으로 예상 가능하다. 새로운 protected path 변경이 생기면 commit 전에 반드시 사람이 확인한다.

## 12. 검증과 운영 명령

```bash
/srv/ai-ops/bin/check-insurance-rag
/srv/ai-ops/bin/check-discord-harness

# Discord
/status
/repo-diff
/repo-guard
```

| **정상 기준**      | **값**         |
|--------------------|----------------|
| Ollama model       | exaone3.5:7.8b |
| Chroma count       | 7825           |
| retrieval recall@8 | 1.000          |
| Streamlit          | 127.0.0.1:8501 |

## 13. Streamlit / Discord Bot 운영

기존 세션이 없을 때만 tmux new를 사용한다. 기존 세션이 있으면 attach로 재접속한다.

```bash
tmux ls

# 새 세션
# tmux new -s insurance-rag
# /srv/ai-ops/bin/run-insurance-rag

# tmux new -s discord-harness
# /srv/ai-ops/bin/run-discord-harness

# 기존 세션 재접속
tmux attach -t insurance-rag
tmux attach -t discord-harness

# detach: Ctrl + B, D
```

## 14. 보안 규칙

- secrets 값, Bot token, API key, env 값을 Discord나 문서에 출력하지 않는다.

- 팀원은 /srv/ai-ops/secrets를 열람하지 않는다.

- 개인 token은 /home/<user> 아래에만 저장한다.

- Discord Bot을 통한 자동 git add/commit/push는 금지한다.

- sudo, rm -rf, 대규모 삭제, --dangerously-bypass-approvals-and-sandbox, --yolo는 금지한다.

- 공용 repo 직접 수정은 /codex-apply 또는 관리자 수동 작업으로만 수행한다.

## 15. 장애 대응

| **상황** | **대응** |
|----|----|
| Discord 명령어가 안 보임 | check-discord-harness 확인, Synced 13 commands 확인, Discord 앱 새로고침 |
| Discord Bot 응답 없음 | tmux attach -t discord-harness 후 run-discord-harness 재실행 |
| Streamlit 꺼짐 | tmux attach -t insurance-rag 후 run-insurance-rag 재실행 |
| dubious ownership | 해당 workspace 소유자 계정으로 접속. 관리자 임시 확인 시에만 safe.directory 사용 |
| /codex-apply 결과가 의도와 다름 | commit하지 않고 /repo-diff, /repo-guard 확인 후 수동 restore |
| protected path warning | 기존 보류 변경인지 확인. 새 protected 변경이면 commit 금지 후 원인 분석 |

## 16. OpenClaw 보류 상태

현재 OpenClaw는 사용하지 않는다. Discord Harness와 공용 에이전트 흐름이 안정화된 후 별도 검토한다.

```text
Discord Bot
→ /srv/ai-ops/bin wrappers
→ Codex / Claude / Streamlit / Ollama
```

## 17. 최종 체크리스트

| **대상** | **체크리스트** |
|----|----|
| 관리자 | Discord Bot running, Streamlit running, /status 정상, /repo-diff·/repo-guard 확인, stage 파일 확인 후 commit |
| 팀원 | 개인 workspace에서 작업, whoami 확인, VS Code Extension 개인 계정 사용, 공용 repo 직접 수정 금지 |
| 공용 에이전트 사용 | /codex는 read-only, /codex-apply와 /apply-from-workspace 후 /repo-diff → /repo-guard → /claude 확인 |

## 18. 참고 문서

- docs/DGX_SPARK_RUNBOOK.md — DGX 운영 환경 상세

- docs/AI_REVIEWER_GUIDE.md — Claude 리뷰어 역할

- docs/PERSONAL_AGENT_WORKFLOW.md — 개인 에이전트 규칙

- docs/DISCORD_HARNESS_RUNBOOK.md — Discord Bot 상세

- docs/TEAM_DEVELOPMENT_GUIDE.md — 팀 통합 개발 가이드
