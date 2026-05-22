# Streamlit Evidence Validation Import Fix Report

## 배경

Streamlit 일반 질의 실행 후 답변 후처리 단계에서 `NameError: name 'append_evidence_validation_warning' is not defined`가 발생했다.

## 원인

`src/ui/streamlit_app.py`의 `_stream_answer()`는 답변 생성 후 `append_evidence_validation_warning()`을 호출하지만, 해당 함수가 정의된 `src.rag.evidence`에서 import하지 않았다. Python은 함수 내부 이름을 실행 시점에 평가하므로 앱 import와 로그인은 통과했지만 실제 질문 처리 시점에 오류가 발생했다.

## 수정 내용

- `src/ui/streamlit_app.py`
  - `from src.rag.evidence import append_evidence_validation_warning` 추가.
  - 직전 vLLM readiness/auth 수정 상태를 유지했다.
- `tests/test_streamlit_app.py`
  - `_stream_answer()`를 fake pipeline으로 직접 호출하는 회귀 테스트 추가.
  - Streamlit `spinner`/`empty`를 monkeypatch해 LLM 서버 없이 답변 후처리 경로를 검증한다.

## 검증

```bash
.venv/bin/pytest tests/test_streamlit_app.py tests/test_evidence.py tests/test_llm_factory.py -q
# 33 passed, 1 warning

.venv/bin/pytest -q
# 304 passed, 3 warnings
```

추가로 `git diff --check`와 `py_compile`을 실행해 문법 및 whitespace 문제를 확인했다.

## 운영 메모

이번 문제는 대형 모델, 인덱스, RAG 검색 실패가 아니라 UI 스트리밍 답변 경로의 import 누락이다. Streamlit 프로세스는 수정 전 모두 중단했으며, 수정 후 `scripts/prepare_streamlit_runtime.sh --run-streamlit --replace`로 재실행하면 된다.
