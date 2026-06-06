# 183. Qwen Thinking Reasoning Mode Final Retry Fix Report

## Summary

Qwen3 Next Thinking 모델에서 프론트엔드의 `추론 모드`를 켰을 때 내부 추론만 생성되고 최종 답변이 나오지 않아 안전 fallback 문구가 표시되는 문제를 수정했다.

## Diagnosis

- 프론트엔드는 `reasoning_mode=on`을 정상 전달하고 있었다.
- 백엔드는 내부 추론 토큰을 화면에 노출하지 않기 위해 `</think>` 이전 토큰을 차단한다.
- 기존 Qwen Thinking 요청은 `max_tokens=1500`을 사용해 긴 reasoning이 `</think>`와 최종 답변에 도달하기 전에 종료될 수 있었다.
- 이 경우 백엔드는 의도대로 내부 추론을 숨기고 `THINKING_ONLY_OUTPUT` fallback을 표시했다.

## Fix

- `SGLANG_REASONING_MAX_TOKENS` 설정을 추가하고 테스트 기본값을 `10240`으로 두었다.
- Qwen Thinking `reasoning_mode=on` 요청에만 reasoning 전용 token limit을 적용한다.
- 그래도 최종 답변 없이 reasoning-only로 끝나면 같은 prompt를 `reasoning_mode=off`로 한 번 자동 재시도한다.
- 재시도 성공 시 fallback 문구 대신 최종 답변을 표시하고, audit/warning에는 `THINKING_FINAL_RETRY`를 남긴다.
- 재시도도 실패하면 기존 `THINKING_ONLY_OUTPUT` 안전 fallback을 유지한다.

## Verification

- `tests/test_openai_compatible_client.py`: 19 passed
- `tests/test_openai_compatible_client.py tests/test_api_chat_stream.py`: 30 passed
- `tests/test_openai_compatible_client.py tests/test_api_chat_stream.py tests/test_qwen_thinking_template.py`: 32 passed
- 전체 테스트: 572 passed, 3 warnings
- DGX live smoke: Qwen Thinking `reasoning_mode=on` 스트림 호출에서 fallback 없음, `<think>` 미노출, 한국어 최종 답변 생성 확인

## Notes

- 이 패치는 내부 추론 문장을 UI에 노출하지 않는 기존 보안/UX 정책을 유지한다.
- reasoning-on이 항상 모델 자체의 final을 직접 생성한다는 보장은 없으므로, 실사용 안정성을 위해 final-only retry를 안전망으로 둔다.

## 2026-06-05 추가 패치

- 테스트 목적의 Qwen Thinking reasoning-on 출력 한도를 `SGLANG_REASONING_MAX_TOKENS=10240`로 상향했다.
- OpenAI-compatible stream의 마지막 chunk에 포함되는 `finish_reason`을 `last_finish_reason`으로 수집한다.
- reasoning-only 후 final-only retry가 실행된 경우 재시도 응답의 `finish_reason`은 `last_final_retry_finish_reason`으로 분리해 저장한다.
- `/api/chat/stream` audit detail에 `finish_reason`, `final_retry_finish_reason`을 기록한다.

## 2026-06-06 v1.0.2 Token Cap Policy

- 로컬 모델 운용 기준에서 출력 비용보다 최종 답변 안정성과 실사용 여유를 우선해 토큰 상한을 1.25배 상향했다.
- 일반 OpenAI-compatible/local 모델 기본 출력 상한: `OPENAI_MAX_TOKENS=4096`.
- Qwen Thinking reasoning-on 전용 출력 상한: `SGLANG_REASONING_MAX_TOKENS=10240`.
- OCR/Vision 파서용 `max_tokens` 값은 별도 파서 안정화 파라미터이므로 이번 일반 챗봇/LLM 응답 상한 정책에는 포함하지 않았다.
