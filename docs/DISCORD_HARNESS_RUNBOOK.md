# Discord Harness Runbook
## 1. Purpose
Discord Harness는 Discord 서버에서 DGX Spark 운영 상태를 확인하고, 공용 Codex/Claude wrapper를 안전하게 호출하기 위한 봇이다.

활성화된 명령:
- `/help`
- `/rag`
- `/status`
- `/workflow`
- `/agent-policy`
- `/workspace`
- `/logs`
- `/codex`
- `/claude`
- `/codex-apply`
- `/apply-from-workspace`
- `/repo-diff`
- `/repo-guard`

`ENABLE_AGENT_COMMANDS=true` 상태에서 `/codex`, `/claude`, `/codex-apply`, `/apply-from-workspace`가 실제 agent wrapper를 호출한다.
`/repo-diff`, `/repo-guard`는 ENABLE_AGENT_COMMANDS 여부와 관계없이 agent role이 있으면 실행 가능하다.

---
## 2. Runtime Paths
```text
Harness root:
  /srv/ai-ops/discord-harness
Virtual environment:
  /srv/ai-ops/discord-harness/.venv
Bot entrypoint:
  /srv/ai-ops/discord-harness/bot.py
Secrets:
  /srv/ai-ops/secrets/discord-harness/env.sh
Logs:
  /srv/ai-ops/logs/discord/discord-harness.log
Run script:
  /srv/ai-ops/bin/run-discord-harness
Check script:
  /srv/ai-ops/bin/check-discord-harness

Wrappers:
  /srv/ai-ops/bin/codex-task          (read-only Codex)
  /srv/ai-ops/bin/codex-apply-task    (Codex with workspace-write)
  /srv/ai-ops/bin/claude-review       (Claude review)

Logs by type:
  /srv/ai-ops/logs/codex/             (codex-task 전체 로그)
  /srv/ai-ops/logs/codex-apply/       (codex-apply-task 전체 로그)
  /srv/ai-ops/logs/claude/            (claude-review 전체 로그)
  /srv/ai-ops/logs/discord/           (Discord bot 로그)

Shared repo:
  /srv/shared/projects/insurance-rag-chatbot
Team workspaces:
  /srv/shared/workspaces/<user>/insurance-rag-chatbot
```
⸻

## 3. Discord Configuration

Discord Developer Portal에서 봇을 생성하고 서버에 초대한다.

필수 scopes:

- bot
- applications.commands

권장 bot permissions:

- Send Messages
- Use Slash Commands
- Read Message History

초기 MVP에서는 privileged intents를 사용하지 않는다.

현재 MVP는 guild-scoped slash command로 동기화한다. 정상 동기화 시 로그에 다음이 표시된다.

```
Synced 13 commands to guild <guild_id>
Logged in as <bot_name>
Shard ID None has connected to Gateway
```

Shard ID None has connected to Gateway는 정상 Discord Gateway 연결 로그다.

⸻

## 4. Secrets

Discord Bot token과 서버/채널/역할 ID는 다음 파일에 저장한다.

```
/srv/ai-ops/secrets/discord-harness/env.sh
```

이 파일은 Git에 올리지 않는다.

필수 환경변수:

```
DISCORD_BOT_TOKEN
DISCORD_GUILD_ID
DISCORD_ALLOWED_CHANNEL_IDS
DISCORD_AGENT_ROLE_IDS
DISCORD_ADMIN_ROLE_IDS
ENABLE_AGENT_COMMANDS
REPO_DIR
INSURANCE_RAG_URL_HELP
CHECK_INSURANCE_RAG
CODEX_TASK
CODEX_APPLY_TASK
CLAUDE_REVIEW
WORKSPACE_ROOT
DISCORD_LOG_DIR
```

값을 노출하지 않고 키만 확인:

```bash
grep -nE 'DISCORD|ENABLE|REPO_DIR|CHECK|CODEX|CLAUDE|WORKSPACE' \
  /srv/ai-ops/secrets/discord-harness/env.sh | sed 's/=.*/=<hidden>/'
```

권장 권한:

```bash
chmod 700 /srv/ai-ops/secrets/discord-harness
chmod 600 /srv/ai-ops/secrets/discord-harness/env.sh
```

Bot token이 노출되면 즉시 Discord Developer Portal에서 reset token을 수행하고, env.sh를 갱신한 뒤 bot을 재시작한다.

⸻

## 5. Start

tmux 세션에서 실행한다.

```bash
tmux new -s discord-harness
/srv/ai-ops/bin/run-discord-harness
```

실행 후 tmux에서 빠져나오기:

```
Ctrl + B
D
```

다시 접속:

```bash
tmux attach -t discord-harness
```

중지:

```
Ctrl + C
```

기존 세션을 제거하고 다시 만들기:

```bash
tmux kill-session -t discord-harness 2>/dev/null || true
tmux new -s discord-harness
```

⸻

## 6. Check

Discord Harness 상태 확인:

```bash
/srv/ai-ops/bin/check-discord-harness
```

정상 예:

```
[1] Process
... /srv/ai-ops/discord-harness/.venv/bin/python bot.py
[2] Log tail
Synced 13 commands to guild ...
Logged in as ...
Shard ID None has connected to Gateway ...
```

⸻

## 7. Commands

### /help

사용 가능한 명령을 보여준다.

### /rag

Streamlit 앱 접속 방법을 안내한다.

현재 기본 안내:

```
ssh -L 8501:localhost:8501 <user>@100.88.5.57 then open http://localhost:8501
```

### /workflow

개인 에이전트와 공용 에이전트의 협업 흐름을 안내한다. (자세한 흐름은 [9. Recommended Workflow](#9-recommended-workflow) 참조)

### /agent-policy

개인/공용 에이전트 보안 정책을 안내한다.

주요 원칙:

- 개인 token은 /home/<user> 아래에만 저장
- /srv/shared 또는 /srv/ai-ops에 개인 token 저장 금지
- /srv/ai-ops/secrets 읽기/출력 금지
- 임의 shell, sudo, secret 출력, 승인 없는 git push 금지

### /workspace

개인 workspace 생성 방법을 안내한다.

```bash
mkdir -p /srv/shared/workspaces/$USER
cd /srv/shared/workspaces/$USER
git clone https://github.com/koreaben777/insurance-rag-chatbot.git
cd insurance-rag-chatbot
git checkout -b feature/$USER/<task-name>
```

### /status

다음 스크립트를 실행한다.

```bash
/srv/ai-ops/bin/check-insurance-rag
```

정상 기준:

```
SSH: active
Ollama: active
Ollama model: exaone3.5:7.8b
Chroma count: 7825
Streamlit process running
```

Discord 메시지 길이 제한 때문에 긴 출력은 ...[truncated]로 잘릴 수 있다. 핵심 상태값이 보이면 정상이다.

### /logs

로그 디렉터리 경로만 출력한다.

```
Codex logs: /srv/ai-ops/logs/codex/
Codex apply logs: /srv/ai-ops/logs/codex-apply/
Claude logs: /srv/ai-ops/logs/claude/
Discord logs: /srv/ai-ops/logs/discord/
```

보안상 로그 tail을 Discord에 출력하지 않는다.

### /codex

**용도:**
- read-only 조사, 요약, 계획, 리뷰 보조.
- 파일 수정용으로 쓰지 않는다.

**옵션:**

| 옵션 | 필수 | 선택지 |
|------|------|--------|
| task | 필수 | (자유 텍스트) |
| model | 선택 | gpt-5.5 (기본), gpt-5.4, gpt-5.3-codex |
| reasoning | 선택 | minimal, low, medium, high (기본), xhigh |

**정책:**
- read-only wrapper `/srv/ai-ops/bin/codex-task` 호출.
- 모델/추론 강도는 환경변수(`CODEX_MODEL`, `CODEX_REASONING_EFFORT`)로 wrapper에 전달.
- 전체 exec 로그 대신 요약 결과와 로그 경로만 Discord에 표시.
- 전체 로그는 `/srv/ai-ops/logs/codex/task_<timestamp>.log`에 저장.

### /claude

**용도:**
- diff 리뷰, 운영 리스크 분석, 문서 검토, 커밋 가능성 판단.
- 기본적으로 파일을 수정하지 않는다.

**옵션:**

| 옵션 | 필수 | 선택지 |
|------|------|--------|
| task | 필수 | (자유 텍스트) |
| model | 선택 | sonnet (기본), opus, haiku |

**로그:** `/srv/ai-ops/logs/claude/review_<timestamp>.log`

내부적으로 최신 Codex 로그를 `.ai-ops/codex-logs/latest-codex.log`에 복사하여 Claude가 참조할 수 있게 한다.

### /codex-apply

**용도:**
- 공용 운영 repo `/srv/shared/projects/insurance-rag-chatbot`를 직접 수정할 수 있는 Codex apply 명령.
- 작은 코드 수정, 문서 수정, 팀 공용 repo 반영 작업에 사용.
- 자동 commit/push는 하지 않는다.

**옵션:**

| 옵션 | 필수 | 선택지 |
|------|------|--------|
| task | 필수 | (자유 텍스트) |
| model | 선택 | gpt-5.5 (기본), gpt-5.4, gpt-5.3-codex |
| reasoning | 선택 | minimal, low, medium, high (기본), xhigh |

**내부 동작:**
- `/srv/ai-ops/bin/codex-apply-task` 호출.
- `--sandbox workspace-write` 사용.
- `--dangerously-bypass-approvals-and-sandbox`, `--yolo` 사용 금지.
- 작업 전후 `git status --short`, `git diff --stat`, `git diff --name-only` 출력.
- protected path guard 수행 (변경 감지 시 WARNING 표시).
- 전체 로그는 `/srv/ai-ops/logs/codex-apply/apply_<timestamp>.log`에 저장.
- Discord에는 `=== CODEX APPLY SUMMARY ===` 구간만 표시.

**사용 후 필수 점검:**
1. `/repo-diff` — 변경된 파일 확인
2. `/repo-guard` — protected path 변경 확인
3. 필요 시 `/claude` 리뷰

### /apply-from-workspace

**용도:**
- 팀원 개인 workspace의 변경사항을 검토하고 공용 repo에 필요한 변경을 반영.
- 핵심 통합 명령.

**옵션:**

| 옵션 | 필수 | 선택지 |
|------|------|--------|
| user | 필수 | DGX 계정명 |
| task | 필수 | (자유 텍스트) |
| branch | 선택 | 참조용 브랜치명 (자동 checkout 하지 않음) |
| model | 선택 | gpt-5.5 (기본), gpt-5.4, gpt-5.3-codex |
| reasoning | 선택 | minimal, low, medium, high (기본), xhigh |

**source workspace:** `/srv/shared/workspaces/<user>/insurance-rag-chatbot`

**정책:**
- `branch`가 제공되어도 자동 checkout하지 않는다. 현재 브랜치와 비교 정보만 출력.
- source workspace와 공용 repo 경로를 Codex에게 명확히 제공.
- 필요한 변경만 공용 repo에 반영.
- `git add`, `git commit`, `git push` 금지.
- 실행 후 `/repo-diff`, `/repo-guard`, `/claude` 리뷰 권장.

### /repo-diff

**용도:** 공용 repo의 현재 변경 요약 확인.

**출력:**
- `git status --short`
- `git diff --stat`
- `git diff --name-only`

Full diff는 Discord에 출력하지 않는다.

### /repo-guard

**용도:** 공용 repo의 현재 변경 중 protected path 변경 감지.

**현재 protected path:**

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

**주의:**
- 현재 보류 중인 기존 변경(`data/index/bm25.pkl`)으로 인해 WARNING이 나오는 것은 예상된 상태다.
- 새 protected path 변경이 감지되면 반드시 사람이 확인해야 한다.

⸻

## 8. Related Services

### Insurance RAG Streamlit

실행:

```bash
tmux new -s insurance-rag
/srv/ai-ops/bin/run-insurance-rag
```

상태 확인:

```bash
/srv/ai-ops/bin/check-insurance-rag
```

정상 기준:

```
chroma count: 7825
streamlit process running
```

### Ollama

상태 확인:

```bash
systemctl is-active ollama
curl http://localhost:11434/api/tags
```

현재 모델:

```
exaone3.5:7.8b
```

⸻

## 9. Security Policy

**허용:**

- `/codex-apply`를 통한 공용 repo 파일 수정
- `/apply-from-workspace`를 통한 팀원 workspace 변경 반영
- 모델/추론 강도 선택
- 공용 repo diff 요약 확인 (`/repo-diff`, `/repo-guard`)

**금지:**

- Discord Bot을 통한 자동 `git add`
- 자동 `git commit`
- 자동 `git push`
- secret/env 값 출력
- raw PDF/XLSX 수정
- generated index/data 임의 수정
- `sudo`
- `rm -rf`류 대규모 삭제
- `--dangerously-bypass-approvals-and-sandbox`
- `--yolo`
- Bot token을 채팅, Git, 문서에 기록
- Discord에 로그 전체 출력

**수정 후 원칙:**

모든 파일 수정(`/codex-apply`, `/apply-from-workspace`)은 자동 commit 없이 종료된다.
사람이 `/repo-diff`와 `/repo-guard`로 결과를 확인하고 commit 여부를 직접 판단한다.

⸻

## 10. Recommended Workflow

### 개인 작업 → 공용 repo 반영 흐름

1. 팀원이 VS Code Remote SSH에서 자기 workspace(`/srv/shared/workspaces/<user>/insurance-rag-chatbot`)에서 작업.
2. 개인 Codex/Claude extension으로 구현 보조.
3. Discord에 작업 요약 공유.
4. `/apply-from-workspace user=<user> task="..."` 로 공용 repo 반영 요청.
5. `/repo-diff` 로 변경 파일 확인.
6. `/repo-guard` 로 protected path 확인.
7. `/claude task="diff 리뷰"` 로 diff 리뷰.
8. 사람이 최종 확인 후 수동 commit/push.

### 공용 repo 직접 수정 흐름

1. `/codex-apply task="..."` 로 작은 단위 수정 요청.
2. `/repo-diff` 확인.
3. `/repo-guard` 확인.
4. `/claude task="diff 리뷰"` 리뷰.
5. 사람이 수동 commit/push 판단.

⸻

## 11. Troubleshooting

### Slash commands do not appear

Bot 로그 확인:

```bash
/srv/ai-ops/bin/check-discord-harness
```

Synced 0 commands가 보이면 bot.py의 setup_hook()에 다음이 있는지 확인한다.

```python
self.tree.copy_global_to(guild=guild)
synced = await self.tree.sync(guild=guild)
```

수정 후 bot을 재시작한다.

### Bot process is not running

```bash
tmux ls
tmux attach -t discord-harness
/srv/ai-ops/bin/run-discord-harness
```

또는 세션을 재생성한다.

```bash
tmux kill-session -t discord-harness 2>/dev/null || true
tmux new -s discord-harness
/srv/ai-ops/bin/run-discord-harness
```

### /status says Streamlit is not running

Streamlit을 실행한다.

```bash
tmux new -s insurance-rag
/srv/ai-ops/bin/run-insurance-rag
```

### Discord output is truncated

정상일 수 있다. Bot은 Discord 메시지 제한과 보안상 출력 길이를 제한한다. 핵심 상태값이 보이면 정상이다.

### Token exposed

1. Discord Developer Portal에서 Reset Token
2. `/srv/ai-ops/secrets/discord-harness/env.sh` 업데이트
3. Bot 재시작
4. 로그와 문서에 토큰이 남았는지 확인

### /codex-apply 후 protected path warning이 나오는 경우

- 기존 `data/index/bm25.pkl` warning은 현재 보류 중인 기존 변경으로 인해 예상 가능한 상태다.
- 새로 추가된 protected path 변경이 있는지 확인한다.
- 새 warning이 생겼다면 commit 전 반드시 사람이 직접 확인한다.

### /apply-from-workspace가 source workspace를 못 찾는 경우

- `/srv/shared/workspaces/<user>/insurance-rag-chatbot` 디렉터리가 존재하는지 확인한다.
- 팀원이 자신의 계정으로 workspace를 생성했는지 확인한다.
- `user` 옵션에 DGX 계정명을 정확히 입력했는지 확인한다.

### Git dubious ownership 문제가 나는 경우

- 팀원 workspace는 해당 팀원 계정으로 조작해야 한다.
- 예: eundeo workspace는 eundeo 계정에서 작업.
- 관리자가 임시 확인이 필요할 때만 `git config --global --add safe.directory` 추가 가능.

### /codex-apply가 변경을 만들었지만 의도와 다를 경우

- commit하지 않는다.
- `/repo-diff`로 변경 내용을 확인한다.
- 사람이 수동으로 수정하거나 `git checkout -- <file>`로 되돌린다.
- 자동 revert는 현재 정책상 수행하지 않는다.

⸻

## 12. MVP Completion Criteria

Discord Harness MVP 완료 기준:

- /help responds
- /rag responds
- /workflow responds
- /agent-policy responds
- /workspace responds
- /status returns DGX health
- /logs returns log directories
- /codex runs read-only Codex task
- /claude runs Claude review
- /codex-apply applies task to shared repo (no auto-commit)
- /apply-from-workspace applies workspace changes to shared repo (no auto-commit)
- /repo-diff returns shared repo diff summary
- /repo-guard detects protected path changes
- tmux discord-harness session is running
- check-discord-harness shows Synced 13 commands

현재 OpenClaw를 사용하지 않는다. OpenClaw 연동은 Discord Harness와 권한 정책이 안정화된 후 진행한다.
systemd 전환은 하지 않고 tmux로 운영 중이다.

⸻

## 13. Current Status

As of 2026-05-18:

```plain text
Discord Harness MVP 완료
공용 에이전트 명령 활성화 완료 (ENABLE_AGENT_COMMANDS=true)
Slash commands synced: 13
/codex 정상 (read-only)
/claude 정상
/codex-apply 정상 테스트 완료 (소규모 문서 생성)
/apply-from-workspace 정상 테스트 완료 (팀원 workspace 변경 반영)
/repo-diff 정상
/repo-guard 정상
  - data/index/bm25.pkl warning은 기존 변경으로 인해 예상된 상태
Streamlit 정상
Ollama 정상
Chroma count: 7825
OpenClaw 미적용
systemd 전환 없음 (tmux 운영 중)
```
