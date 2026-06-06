# 184. Legacy to Official Version Developer Handoff

## Purpose

이 문서는 레거시 개발 채팅에서 정식 버전 개발자 Codex 채팅으로 작업을 넘기기 위한 인계 메모다. 기준 커밋은 `v1.0.2` 릴리스 대상 작업이다.

## Current Release Scope

`v1.0.2`에는 다음 변경이 포함된다.

- 프론트 기본 설정 조정
  - Top-K 기본값: `10`
  - 온도 기본값: `0.2`
  - OCR 인덱스 기본값: `보정본 OCR만` (`v2_only`)
- Qwen Thinking 안정화
  - 내부 추론 문장 UI 노출 차단 유지
  - `reasoning_mode=on`에서 reasoning-only로 종료될 경우 final-only 1회 자동 재시도
  - 재시도 발생 시 warning/audit code: `THINKING_FINAL_RETRY`
- finish reason audit
  - stream 마지막 chunk의 `finish_reason` 수집
  - final-only retry 응답의 `finish_reason`은 `final_retry_finish_reason`으로 별도 기록
- 토큰 상한 정책
  - 일반 LLM 출력 상한: `OPENAI_MAX_TOKENS=1875`
  - Qwen Thinking reasoning-on 출력 상한: `SGLANG_REASONING_MAX_TOKENS=10240`

## Verification

릴리스 직전 DGX에서 확인한 검증은 다음과 같다.

```bash
.venv/bin/pytest tests/test_openai_compatible_client.py tests/test_api_chat_stream.py tests/test_qwen_thinking_template.py -q
# 32 passed, 1 warning

timeout 1200 .venv/bin/pytest tests/ -q
# 572 passed, 3 warnings
```

토큰 설정 확인:

```text
OPENAI_MAX_TOKENS=1875
SGLANG_REASONING_MAX_TOKENS=10240
Qwen reasoning-on payload max_tokens=10240
Qwen reasoning-off payload max_tokens=1875
```

## Operational Notes

- DGX 메인 저장소: `/srv/shared/projects/insurance-rag-chatbot`
- 쓰기/푸시 권한 계정: `ai-hang@100.88.5.57`
- 읽기 전용에 가까운 대체 alias: `dgx-spark-muldae`
- 레거시 채팅 종료 시점에는 `insurance-rag-api`, `sglang-local` tmux 세션을 내려둔 상태였다.
- `ollama` 데몬은 system user `ollama`로 계속 떠 있을 수 있다. 일반적으로 CPU/GPU 부하는 거의 없지만 완전 중지는 sudo 권한이 필요하다.

## Recommended Next Work

- `v1.0.2` 이후 정식 개발 채팅에서는 Qwen Thinking을 기본 모델로 고정하기보다, Instruct 모델과 Thinking 모델의 응답 품질/지연을 비교해 기본값을 재선정하는 것이 좋다.
- `finish_reason=length`가 반복되면 reasoning-on 상한을 더 올리기보다, 조기 retry 또는 thinking prompt 축약을 먼저 검토한다.
- 사용자-facing warning은 현재 진단용으로 유용하지만, 정식 UX에서는 관리자/진단 패널로 이동시키는 방안을 검토할 수 있다.
