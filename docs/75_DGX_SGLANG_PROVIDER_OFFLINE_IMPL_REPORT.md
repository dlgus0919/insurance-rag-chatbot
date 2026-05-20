# DGX Spark SGLang Provider/Offline 전환 구현 보고서

작성일: 2026-05-20  
작업 위치: `/srv/shared/projects/insurance-rag-chatbot`  
운영 기준: DGX Spark 원격 메인 프로젝트 디렉터리

## 1. 구현 요약

- SGLang을 별도 로컬 OpenAI-compatible provider로 추가했다.
- Streamlit UI를 `LLM Provider`와 `LLM 모델` 2단계 선택으로 분리했다.
- 기존 Ollama provider는 fallback으로 유지했다.
- `OFFLINE_MODE`와 로컬 `RERANKER_MODEL` 설정을 추가해 완전 오프라인 운영 경로를 명시했다.
- `gpt-oss-20b`의 chat template 400 문제는 `/srv/ai-ops/llm/templates/gpt_oss_harmony.jinja`를 `sglang serve --chat-template`로 지정해 해결했다.
- SGLang 응답의 Harmony channel marker는 앱 client에서 final channel만 추출하도록 처리했다.

## 2. DGX 운영 산출물

Git에 포함하지 않는 운영 파일:

- `/srv/ai-ops/llm/templates/gpt_oss_harmony.jinja`
- `/srv/ai-ops/bin/run-sglang-local`
- `/srv/ai-ops/bin/check-sglang-local`
- `/srv/ai-ops/logs/sglang/sglang-local.log`
- `/srv/ai-ops/llm/models/gpt-oss-20b/`

SGLang 기동 명령은 wrapper 기준:

```bash
/srv/ai-ops/bin/run-sglang-local
```

점검 명령:

```bash
/srv/ai-ops/bin/check-sglang-local
```

## 3. 주요 설정

권장 DGX 운영 env:

```env
OFFLINE_MODE=true
HF_MODEL_DOWNLOAD=false
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3
RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3
SGLANG_BASE_URL=http://127.0.0.1:30000/v1
SGLANG_API_KEY=EMPTY
SGLANG_DEFAULT_MODEL=gpt-oss-20b
SGLANG_REASONING_EFFORT=low
SGLANG_CANDIDATE_MODELS=gpt-oss-20b
ALLOW_OLLAMA=true
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=exaone3.5:7.8b
```

## 4. 검증 결과

- SGLang `/v1/models`: PASS
- SGLang `/v1/chat/completions`: PASS
- SGLang streaming smoke: PASS
- `gpt-oss-20b` final answer extraction: PASS
- `pytest -q`: `260 passed`, warnings 3건
- OCR retrieval eval:
  - 명령: `CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 .venv/bin/python scripts/eval.py --ocr`
  - 결과: `retrieval recall@8: 1.000`
- `data/processed/chunks.jsonl`: `7825` lines
- Chroma collection count: `7825`

## 5. 남은 운영 주의사항

- SGLang이 GPU 메모리를 크게 점유하므로, retrieval-only eval을 동시에 돌릴 때는 `CUDA_VISIBLE_DEVICES=`로 임베딩을 CPU에 올린다.
- `gpt-oss-20b`는 Harmony analysis/final channel을 출력하므로 앱 client 후처리를 제거하면 안 된다.
- OpenAI Cloud provider는 `OFFLINE_MODE=true`에서 UI 후보에 표시되지 않는다.
- `Gemma-4-26B-A4B-NVFP4`는 아직 2차 A/B 검증 전이다.

## 6. Git 관리

- `.venv-sglang/`, `handoff/`, `sglang_storage/`는 Git 제외 대상으로 추가했다.
- `/srv/ai-ops` 운영 산출물은 repo 커밋 대상이 아니다.
