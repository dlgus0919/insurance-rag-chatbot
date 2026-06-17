# 217. Codex DGX Tailscale SSH 개발 셋업

작성일: 2026-06-11

## 목적

Codex Desktop의 OpenAI/ChatGPT 통신은 일반 인터넷 DNS와 라우팅을 사용하고, DGX 개발 접속만 Tailscale SSH 경로로 고정한다. 이 구성은 Tailscale DNS 또는 Exit Node가 Codex Desktop 내부 HTTP 클라이언트와 충돌하는 문제를 피하면서도, 로컬 Codex 채팅에서 DGX에 직접 SSH 로그인해 구현과 검증을 수행하기 위한 운영 기준이다.

## 현재 적용된 로컬 설정

Tailscale은 다음 정책으로 사용한다.

```bash
tailscale up --exit-node= --accept-dns=false --accept-routes=false
```

의도:

- `--exit-node=`: 일반 인터넷 트래픽을 Tailscale Exit Node로 보내지 않는다.
- `--accept-dns=false`: Codex Desktop이 Tailscale DNS를 기본 DNS로 사용하지 않게 한다.
- `--accept-routes=false`: DGX 직접 peer 접속 외 subnet route 수락을 막는다.

`~/.ssh/config`에는 Codex 전용 alias를 추가했다.

```sshconfig
Host dgx-codex
    HostName 100.88.5.57
    User ai-hang
    Port 22
    IdentityFile ~/.ssh/dgx_spark_codex_nopass
    IdentitiesOnly yes
    BatchMode yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
    ConnectTimeout 10
```

기존 SSH config는 `/Users/june_kim/.ssh/config.codex-setup-backup-20260611T0115Z`에 백업했다.

## Codex 개발 방식

Codex는 로컬 채팅에서 아래 형식으로 DGX 명령을 직접 실행한다.

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && git status --short'
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python -c "print(\"REMOTE_PY_OK\")"'
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python -m pytest -q'
```

원격 기준 프로젝트 경로:

```text
/srv/shared/projects/insurance-rag-chatbot
```

원격 기준 Python:

```text
/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python
```

대규모 수정은 다음 중 하나로 수행한다.

1. DGX 저장소에서 직접 브랜치 작업
2. 로컬에서 patch 생성 후 DGX에 적용
3. DGX에서 검증 후 GitHub에 push

patch 방식 예:

```bash
git diff > /tmp/change.patch
scp /tmp/change.patch dgx-codex:/tmp/change.patch
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && git apply /tmp/change.patch'
```

## 작업 전 점검

Codex 작업 시작 전 다음을 확인한다.

```bash
tailscale status
scutil --dns
curl -s -o /dev/null -w "chatgpt_bundle HTTP %{http_code}\n" https://chatgpt.com/backend-api/wham/config/bundle
curl -s -o /dev/null -w "openai_models HTTP %{http_code}\n" https://api.openai.com/v1/models
ssh dgx-codex 'hostname && whoami && cd /srv/shared/projects/insurance-rag-chatbot && git status --short'
```

정상 기준:

- `tailscale status`에 `aitopatom-255d` / `100.88.5.57`이 표시된다.
- `scutil --dns`의 기본 resolver가 `100.100.100.100`만 사용하지 않는다.
- `chatgpt.com/backend-api/wham/config/bundle`과 `api.openai.com/v1/models`는 인증 없이 호출 시 `401`을 반환한다.
- `ssh dgx-codex`가 `aitopatom-255d`, `ai-hang`을 반환한다.

## 주의사항

- Codex Desktop 원격 자동 연결 기능은 당분간 사용하지 않는다. 로컬 Codex가 명시적 `ssh dgx-codex` 명령으로만 DGX에 접속한다.
- MagicDNS 이름 대신 `100.88.5.57`을 사용한다. Tailscale DNS를 끈 상태에서도 접속 경로가 안정적이어야 하기 때문이다.
- Exit Node를 켜면 Codex Desktop의 cloud config bundle 로딩 문제가 재발할 수 있다.
- `--accept-routes=false`는 현재 DGX 직접 peer 접속 기준이다. 향후 DGX 뒤의 별도 subnet에 접근해야 하면 이 항목은 재검토한다.
- 비밀키, 토큰, `.env` 값은 채팅이나 문서에 출력하지 않는다.

## 2026-06-11 검증 결과

로컬 네트워크:

```text
chatgpt_bundle HTTP 401
openai_models HTTP 401
```

Tailscale:

```text
100.67.151.101  macbookair
100.88.5.57     aitopatom-255d
```

DGX SSH:

```text
aitopatom-255d
ai-hang
REMOTE_PY_OK
```

위 검증으로 로컬 Codex Desktop 통신과 DGX SSH 직접 개발 경로가 동시에 동작함을 확인했다.
