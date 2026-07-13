# 267. 데스크톱 실행기 Ollama 활성 모델 판정 수정 보고서

## 문제

DGX 재시동 직후 Ollama 서비스는 실행 중이지만 LLM은 메모리에 로드되어 있지 않을 수 있다. 기존 실행기는 `/api/tags`의 설치 모델 목록을 읽어 Llama 3.3 70B를 `현재 실행 중인 Ollama 유지`로 표시했다. 이 선택지는 `--no-llm-switch`로 앱을 시작하므로, 실제로 유지할 모델 서버가 없는 상태와 충돌했다.

## 원인 확인

2026-07-13 DGX에서 다음 상태를 재현했다.

- `ollama ps`: 모델 없음
- `GET /api/ps`: `{"models":[]}`
- `GET /api/tags`: Llama 3.3 70B와 Exaone 설치 정보 존재
- 기존 `/srv/ai-ops/bin/insurance-rag-desktop-launcher --choices`: `current|ollama|llama-3.3-70b-instruct-q4-k-m:latest` 출력

설치 목록과 메모리 상의 활성 목록을 혼용한 것이 직접 원인이다.

## 수정

- 활성 Ollama 모델 판정은 `/api/ps`만 사용하도록 `detect_ollama_active_model`을 추가했다.
- 설치된 Ollama 모델 조회는 `/api/tags` 전용 `detect_ollama_installed_model`로 분리했다.
- 기본 실행기, `--choices`, `--status`의 `현재 실행 중인 Ollama 유지`는 활성 모델만 사용한다.
- `--model-choices`의 시작 후보는 설치 모델을 계속 사용한다.
- 설치돼 있지만 미기동인 Llama가 현재 모델로 노출되지 않는 회귀 테스트와, 실제 `/api/ps` 모델이 우선되는 테스트를 추가했다.

## 검증

```bash
bash -n ops/bin/insurance-rag-desktop-launcher
/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest tests/test_desktop_launcher_choices.py -q
bash ops/bin/insurance-rag-desktop-launcher --choices
bash ops/bin/insurance-rag-desktop-launcher --status
bash ops/bin/insurance-rag-desktop-launcher --model-choices
```

결과:

- 실행기 회귀 테스트: `8 passed`
- 재시동 직후와 같은 실제 DGX 상태에서 `--choices`는 `model|select|available`만 출력했다.
- 같은 상태의 `--status`는 `ollama=`로 비어 있었다.
- `--model-choices`에는 설치된 Llama 3.3 70B가 `start|ollama|...` 시작 후보로 유지됐다.

## 범위와 남은 위험

이번 수정은 실행기 상태 판정만 변경한다. Llama 3.3 70B를 실제로 선택하여 기동하는 경로, 모델의 메모리 적합성, 응답 품질은 변경하거나 재검증하지 않았다.
