# 122. Remote Repo Cleanup and Team Guide Push Report

작성일: 2026-05-26

## 목적

DGX Spark 공용 메인 프로젝트 폴더(`/srv/shared/projects/insurance-rag-chatbot`)의 미반영 변경을 정리하고, 팀원이 개인 워크스페이스에서 `git pull` 후 최신 Streamlit 앱과 신규 LLM 후보 모델을 실행할 수 있도록 가이드를 보강했다.

## 핵심 변경

- `docs/121_TEAM_PULL_AND_STREAMLIT_RUN_GUIDE_DGX_SPARK.md` 신규 작성
  - 팀원 개인 계정/개인 workspace 기준 pull, 비-Git 런타임 파일 복사, Streamlit 실행, 터널링, 모델 선택, 문제 해결 절차를 상세화했다.
- `docs/80_STREAMLIT_LARGE_MODEL_TEST_GUIDE.md` 갱신
  - 현재 신규 모델 정책과 `121` 가이드 우선순위를 반영했다.
- 신규 모델 기본값 반영
  - SGLang 기본 후보: `qwen3-30b-a3b-instruct-2507-fp8`, `gpt-oss-20b`
  - vLLM 기본 후보: `nemotron-3-nano-30b-a3b-nvfp4`, `gemma-4-26b-a4b-nvfp4`
- `scripts/run_offline_streamlit_test.sh`와 `scripts/prepare_offline_assets.py`의 offline env 기본 모델 목록을 현재 DGX Spark 모델 구성에 맞게 조정했다.
- 모델 기본값 변경에 맞춰 `tests/test_llm_factory.py`의 monkeypatch 범위를 보정했다.

## 포함된 기존 미반영 작업

- current app LLM matrix 평가 스크립트와 테스트
- Stage 2 평가셋 허용 표현 보정
- HIRA 표/문서 coverage 보강이 포함된 RAG pipeline 변경
- loop/final 평가 보고서
- Nemotron/Qwen 다운로드 및 런타임 설정 보고서

## 검증

원격 DGX Spark 공용 repo에서 실행:

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

결과:

```text
352 passed, 3 warnings in 3.10s
```

추가 확인:

- `python3 -m py_compile scripts/eval_chatbot_model_index_matrix.py scripts/prepare_offline_assets.py src/config.py src/rag/pipeline.py`
- `bash -n scripts/run_offline_streamlit_test.sh`
- `bash -n scripts/prepare_streamlit_runtime.sh`
- Streamlit health: `http://127.0.0.1:8501/_stcore/health` 응답 `ok`
- 활성 vLLM endpoint: `nemotron-3-nano-30b-a3b-nvfp4`

## 남은 주의사항

- GitHub에는 `/srv/ai-ops` 모델 파일과 `data/` 인덱스 산출물이 포함되지 않는다. 팀원은 `docs/121_TEAM_PULL_AND_STREAMLIT_RUN_GUIDE_DGX_SPARK.md`의 복사 절차를 따라야 한다.
- Nemotron은 vLLM 경로만 권장한다. SGLang 경로는 첫 chat completion 단계가 불안정하다.
- Qwen은 SGLang smoke 검증은 통과했지만, 보험 RAG 품질은 별도 matrix 평가로 확인해야 한다.
