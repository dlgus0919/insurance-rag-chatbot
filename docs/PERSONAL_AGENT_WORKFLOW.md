# Personal Agent Workflow
## 1. Purpose
이 문서는 DGX Spark 공유 개발 환경에서 팀원이 개인 Codex/Claude Code 계정을 사용하면서도 공용 운영 repo와 공용 secrets를 보호하기 위한 작업 규칙을 정의한다.
## 2. Roles
### Personal Agents
개인 에이전트는 각 팀원이 자기 Linux 계정에서 사용하는 Codex/Claude Code다.
- 개인 VS Code Remote SSH 세션에서 사용한다.
- 개인 ChatGPT Plus / Claude Pro 계정으로 로그인한다.
- 개인 workspace와 개인 branch에서만 작업한다.
- 공용 secrets에 접근하지 않는다.
- 공용 운영 repo를 직접 수정하지 않는다.
### Shared Core Agents
공용 에이전트는 `ai-hang` 계정에 설치된 Codex/Claude/Ollama wrapper다.
- `/srv/ai-ops/bin/codex-task`
- `/srv/ai-ops/bin/claude-review`
- `/srv/ai-ops/bin/check-insurance-rag`
- `/srv/ai-ops/bin/run-insurance-rag`
공용 에이전트는 공식 리뷰, 검증, 운영 상태 확인, 통합 판단에 사용한다.
## 3. Login Policy
각 팀원은 자기 Linux 계정에서만 개인 에이전트에 로그인한다.
```bash
whoami
codex login
claude auth
```
금지:

* ai-hang 계정에서 개인 계정 로그인
* 다른 팀원 계정에서 개인 계정 로그인
* 공용 secrets를 개인 에이전트에 노출
* 인증 파일을 Git에 추가
* 인증 파일을 /srv/shared 또는 /srv/ai-ops 아래에 저장

4. Workspace Layout

개인 작업은 아래 경로를 사용한다.

/srv/shared/workspaces/<user>/insurance-rag-chatbot

생성 예시:

mkdir -p /srv/shared/workspaces/$USER
cd /srv/shared/workspaces/$USER
git clone https://github.com/koreaben777/insurance-rag-chatbot.git
cd insurance-rag-chatbot
git checkout -b feature/$USER/<task-name>

git worktree는 초기 팀 운영에서는 사용하지 않는다. 필요 시 관리자 또는 숙련자가 통합 검증용으로만 사용한다.

5. Shared Runtime Data

대용량 운영 데이터는 개인 workspace에 복사하지 않는다.

운영 데이터 기준 경로:

/srv/shared/projects/insurance-rag-chatbot/data/extracted
/srv/shared/projects/insurance-rag-chatbot/data/processed
/srv/shared/projects/insurance-rag-chatbot/data/index

개인 작업에서 전체 OCR/ingest/eval이 필요하면 Discord 또는 관리자에게 공용 검증을 요청한다.

6. Protected Paths

다음 경로는 개인 작업에서 수정하지 않는다.

/srv/shared/projects/insurance-rag-chatbot
/srv/ai-ops/secrets
/srv/ai-ops/bin
/srv/ai-ops/logs

프로젝트 내부 Git 금지 항목:

.env
.env.*
users.json
CLOVA_OCR_CUSTOM_API_EXTERNAL*.json
*.pdf
*.xlsx
data/extracted/
data/extracted_v2_manual/
data/processed/
data/index/
logs/
.ai-ops/

7. Development Flow

1. 개인 workspace에서 branch 생성
2. 개인 Codex/Claude로 구현 보조
3. 가능한 범위의 작은 테스트 실행
4. diff 또는 branch 요약 작성
5. Discord에 리뷰 요청
6. 공용 Claude가 리뷰
7. 공용 Codex가 필요 시 수정 제안
8. 공용 검증 환경에서 pytest/eval/check 실행
9. 관리자 승인 후 merge/deploy

8. Discord Review Request Template

branch:
summary:
files changed:
tests run:
risk:
requested reviewer: claude/codex/both

9. Rules for Shared Agents

공용 에이전트는 다음 작업만 수행한다.

* 코드 리뷰
* 제한된 구현 작업
* 테스트/검증
* 운영 상태 점검
* 결과 요약

공용 에이전트는 다음 작업을 하지 않는다.

* secret 출력
* 임의 shell 실행
* sudo 실행
* 운영 데이터 삭제
* 승인 없는 git push
* 승인 없는 ingest 재실행

10. Incident Handling

개인 token이 공용 계정에 저장된 경우:

1. 즉시 해당 계정에서 logout
2. token revoke 또는 재발급
3. 관리자에게 공유
4. 관련 로그에 secret이 남았는지 확인

공용 repo가 오염된 경우:

1. 작업 중단
2. git status --short 공유
3. 관리자 판단 전 reset/clean 금지

