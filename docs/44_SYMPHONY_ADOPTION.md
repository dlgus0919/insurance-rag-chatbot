# Symphony 적용 검토 및 프로젝트 워크플로우 제안

작성일: 2026-05-11

## 조사 요약

OpenAI의 Symphony는 코딩 에이전트를 직접 세션 단위로 관리하지 않고, 이슈·티켓·작업 단위를 중심으로 실행하도록 만드는 오케스트레이션 규격이다. 핵심은 “열린 작업마다 격리된 작업 공간과 에이전트 실행을 보장하고, 사람은 결과를 검토한다”는 운영 방식이다.

OpenAI 공개 글과 `openai/symphony` 저장소 기준 핵심 요소는 다음과 같다.

- 프로젝트 관리 보드(예: Linear)를 코딩 에이전트의 control plane으로 사용한다.
- 각 열린 작업은 독립 workspace에 매핑된다.
- 오케스트레이터는 작업 상태를 주기적으로 확인하고, 실행·재시도·중단·정리를 담당한다.
- 업무 정책과 에이전트 프롬프트는 저장소의 `WORKFLOW.md`에 둔다.
- 성공한 실행도 곧바로 `Done`이 아니라 `Human Review` 같은 검토 상태에서 끝날 수 있다.
- 사람이 에이전트 세션을 계속 조종하는 대신, 작업 정의·검토·가드레일 개선에 집중한다.

관련 원문:

- OpenAI, “An open-source spec for Codex orchestration: Symphony”, 2026-04-27
- GitHub `openai/symphony` `SPEC.md`
- OpenAI, “Harness engineering: leveraging Codex in an agent-first world”, 2026-02-11

## 현재 작업 환경에 맞춘 해석

현재 프로젝트의 실제 운영 방식은 다음과 같다.

- Claude: 프로젝트 검토자 및 기획자
- Codex: 프로젝트 개발자
- Claude가 개발 단계마다 `docs/`에 요구 명세를 작성
- Codex가 명세를 읽고 구현, 검증, 보고

따라서 지금 당장 필요한 것은 완전한 Symphony daemon이 아니라, Symphony의 “작업 단위 계약”과 “저장소 내 정책 문서화”를 먼저 도입하는 것이다.

이번 작업으로 루트에 `WORKFLOW.md`를 추가해 다음을 명문화했다.

- Claude / Codex / Human 역할
- `docs/NN_CODEX_SPEC_*.md` 중심 작업 단위
- Codex 실행 규칙
- 검증 및 보고 패킷
- 작은 수정 3회 후 보고서 작성 여부 확인 규칙
- 향후 Linear 또는 GitHub Issues 도입 시 확장 방향

## 권장 운영 방식

### 1. 작업은 문서 티켓으로 관리

기능 추가, 버그 수정, 구조 변경은 채팅으로만 넘기지 말고 `docs/NN_CODEX_SPEC_<topic>.md`로 남긴다. 이 문서가 Symphony의 ticket 역할을 한다.

### 2. Codex에게는 목표와 검증을 함께 전달

명세에는 반드시 “무엇을 바꿀지”뿐 아니라 “어떤 명령으로 성공을 확인할지”를 포함한다. 예:

```bash
pytest tests/test_clova_ocr.py -v
pytest -q
python -c "import src.parser.clova_ocr; print('import OK')"
```

### 3. 결과는 Human Review 상태로 끝낸다

Codex가 구현을 끝내도 바로 완료로 간주하지 않는다. 변경 파일, 검증 결과, 남은 위험을 보고한 뒤 Claude 또는 사람이 검토한다.

### 4. 반복 실패는 Codex 문제가 아니라 하네스 문제로 다룬다

같은 유형의 실수가 반복되면 프롬프트를 더 길게 쓰는 대신 다음 중 하나로 되돌린다.

- `WORKFLOW.md` 규칙 추가
- 테스트 추가
- 검증 스크립트 추가
- 문서 구조 개선
- 명세 템플릿 보강

### 5. 병렬화는 나중에 도입

현재는 동일 저장소에서 문서와 코드가 빠르게 변하므로 동시 Codex 실행은 충돌 위험이 있다. 우선 `max_concurrent_agents: 1`로 생각하고, 독립 작업이 명확해진 뒤 작업별 worktree 또는 브랜치 격리를 도입하는 것이 안전하다.

## 다음 단계 제안

1. 이후 Claude가 새 개발 명세를 만들 때 `WORKFLOW.md`의 Specification Template을 기준으로 작성한다.
2. Codex 작업 완료 보고서는 기존 `docs/NN_*_REPORT.md` 패턴을 따른다.
3. 반복되는 검증 명령을 `scripts/validate_task.py` 같은 단일 진입점으로 묶는 것을 검토한다.
4. 작업 수가 늘어나면 GitHub Issues 또는 Linear를 도입해 `docs/` 명세와 외부 티켓을 1:1로 연결한다.
