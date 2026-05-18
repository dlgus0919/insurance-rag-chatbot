# Discord Harness Runbook
## 1. Purpose
Discord Harness는 Discord 서버에서 DGX Spark 운영 상태를 확인하고, 향후 공용 Codex/Claude wrapper를 안전하게 호출하기 위한 최소 봇이다.
초기 MVP에서는 다음 명령을 활성화한다.
- `/help`
- `/rag`
- `/status`
- `/workflow`
- `/agent-policy`
- `/workspace`
- `/logs`
다음 명령은 등록되어 있지만 MVP에서는 비활성화되어 있다.
- `/codex`
- `/claude`
`ENABLE_AGENT_COMMANDS=false` 상태에서는 `/codex`, `/claude`를 실행해도 실제 agent wrapper가 호출되지 않는다.
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
Synced 9 commands to guild <guild_id>
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
CLAUDE_REVIEW
DISCORD_LOG_DIR
```

값을 노출하지 않고 키만 확인:

```bash
grep -nE 'DISCORD|ENABLE|REPO_DIR|CHECK|CODEX|CLAUDE' \
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
Synced 9 commands to guild ...
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

개인 에이전트와 공용 에이전트의 협업 흐름을 안내한다.

요약:

1. VS Code Remote SSH로 개인 DGX Linux 계정에 접속
2. 개인 Codex/Claude Extension을 개인 계정/workspace에서 사용
3. /srv/shared/workspaces/<user>/insurance-rag-chatbot 에서 작업
4. 공용 운영 repo는 직접 수정하지 않음
5. Discord에 branch/diff 요약 공유
6. 공용 Claude/Codex wrapper가 리뷰 및 검증

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
Claude logs: /srv/ai-ops/logs/claude/
Discord logs: /srv/ai-ops/logs/discord/
```

MVP에서는 보안상 로그 tail을 Discord에 출력하지 않는다.

### /codex

MVP에서는 비활성화되어 있다.

정상 응답:

```
Agent commands are disabled in MVP.
```

### /claude

MVP에서는 비활성화되어 있다.

정상 응답:

```
Agent commands are disabled in MVP.
```

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

금지 사항:

* Discord에서 임의 shell command 실행
* sudo 실행
* secret/env 출력
* Discord에 로그 전체 출력
* 승인 없는 git push
* 승인 없는 ingest/reindex 실행
* 운영 데이터 삭제
* Bot token을 채팅, Git, 문서에 기록

현재 MVP는 /codex, /claude를 비활성화하여 agent wrapper 실행을 막는다.

향후 활성화 전 확인할 사항:

- ENABLE_AGENT_COMMANDS=true 전환 여부
- 명령별 role 제한
- timeout
- 동시 실행 lock
- 출력 마스킹
- 로그 저장 위치
- 실패 시 중단 정책

⸻

## 10. Troubleshooting

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
2. /srv/ai-ops/secrets/discord-harness/env.sh 업데이트
3. Bot 재시작
4. 로그와 문서에 토큰이 남았는지 확인

⸻

## 11. MVP Completion Criteria

Discord Harness MVP 완료 기준:

- /help responds
- /rag responds
- /workflow responds
- /agent-policy responds
- /workspace responds
- /status returns DGX health
- /logs returns log directories
- /codex returns disabled message
- /claude returns disabled message
- tmux discord-harness session is running
- check-discord-harness shows Synced 9 commands

현재 MVP에서는 OpenClaw를 사용하지 않는다. OpenClaw 연동은 Discord Harness와 권한 정책이 안정화된 후 진행한다.

⸻

## 12. Current Status

As of 2026-05-18:

```Plain text
Bot invited to Discord server
Slash commands synced: 9
/status works
/logs works
Streamlit process running
Ollama active
Chroma count: 7825
Agent commands disabled
OpenClaw not enabled
```
