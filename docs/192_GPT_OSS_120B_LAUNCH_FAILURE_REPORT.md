# 192. GPT-OSS 120B DGX 기동 실패 보고서

## 요약

`gpt-oss-120b` 모델 파일 다운로드는 완료되었으나, DGX Spark 단일 장비에서 SGLang 서버로 기동하는 데 실패했다. 실패 원인은 모델 파일 누락이 아니라 서버 초기화 단계의 메모리 부족으로 판단된다.

## 확인한 상태

- 모델 경로: `/srv/ai-ops/llm/models/gpt-oss-120b`
- 필수 파일: `config.json`, `chat_template.jinja`, `model-00000-of-00014.safetensors`부터 `model-00014-of-00014.safetensors`까지 존재
- 이전 검증 과정에서 남은 HF 캐시 `.incomplete` 파일 5개는 실행 완료 판정을 막고 있었으므로 삭제하지 않고 격리
- 격리 경로: `/srv/ai-ops/llm/models/gpt-oss-120b/.cache/huggingface/incomplete-quarantine-20260608-194746`

## 기동 시도

SGLang으로 세 차례 기동을 시도했다.

1. 기본 설정: `context-length 32768`, `mem-fraction 0.90`
2. 보수 설정: `context-length 8192`, `mem-fraction 0.65`, 단일 요청 제한
3. 초보수 설정: `context-length 4096`, `mem-fraction 0.45`, `max-running-requests 1`, `max-total-tokens 4096`

모든 시도에서 `/v1/models` ready 상태까지 도달하지 못했다.

## 실패 근거

SGLang 로그에서 다음 오류가 반복되었다.

```text
RuntimeError: Rank 0 scheduler died during initialization (exit code: -9).
If exit code is -9 (SIGKILL), a common cause is the OS OOM killer.
```

보수 설정에서도 메모리와 스왑을 거의 모두 사용했다.

- RAM: 119GiB 중 108GiB 이상 사용
- Swap: 15GiB 거의 전량 사용
- 증상: SSH 응답 지연 및 일시 타임아웃, SGLang 포트 `30000` 미개방

따라서 `max_tokens` 또는 앱 프롬프트 문제가 아니라, 모델 서버 초기화 및 weight/scheduler 준비 단계에서 메모리 압박이 발생한 것으로 판단한다.

## 최종 정리 상태

- `gpt-oss-120b` SGLang 서버: 종료됨
- vLLM 서버: 미기동
- 앱 포트 `18080`: 정상
- Ollama serve: 정상
- 현재 앱 모델 목록: `ollama:exaone3.5:7.8b`
- DGX 메모리: 정상 회복

## 결론

현재 DGX Spark 단일 장비와 현 SGLang 구성에서는 `gpt-oss-120b`를 앱 실사용 모델로 편입하기 어렵다. 모델 파일은 보존하되, 운영 실행기와 프론트엔드 모델 선택 목록에서는 `다운로드 완료 / 기동 검증 실패` 상태로 분리하는 것이 적절하다.

추가 검토를 하려면 더 큰 메모리 여유가 있는 장비, 멀티 GPU/분산 추론, 더 강한 양자화 포맷, 또는 SGLang 외의 별도 서빙 백엔드 검증이 필요하다.
