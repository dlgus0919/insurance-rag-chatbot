# 103. Streamlit 전체 기능 실행 준비 통합 스크립트 가이드

## 목적

DGX Spark에서 Streamlit 챗봇의 전체 기능을 테스트하기 전에 필요했던 준비 명령을 하나의 스크립트로 통합했다.

추가된 스크립트:

```bash
scripts/prepare_streamlit_runtime.sh
```

이 스크립트는 이미 생성된 산출물은 건너뛰고, 누락된 산출물만 순서대로 만든다.

## 기본 실행

DGX에서 준비만 수행:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
bash scripts/prepare_streamlit_runtime.sh
```

맥북에서 SSH를 통해 한 번에 실행:

```bash
ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && bash scripts/prepare_streamlit_runtime.sh"
```

## 준비 후 Streamlit까지 한 번에 실행

기존 Streamlit 프로세스를 교체하고, 준비 완료 후 바로 앱을 실행:

```bash
ssh -t ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace"
```

Streamlit은 foreground로 실행된다. 종료하려면 해당 터미널에서 `Ctrl+C`를 누른다.

맥북 브라우저 접속용 터널은 다른 터미널에서 연다.

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

브라우저:

```text
http://localhost:8501
```

## 스크립트가 수행하는 작업

1. 프로젝트 `.venv`를 활성화한다.
2. `/srv/ai-ops/secrets/insurance-rag-chatbot/env.sh`가 있으면 로드한다.
3. 기본적으로 `scripts/prepare_offline_assets.py`를 실행해 오프라인 asset과 `offline.env`를 준비한다.
4. `data/extracted_v2_manual/`이 없고 `handoff/ocr_v2_manual_handoff_*.tar.gz`가 있으면 v2 manual handoff를 자동 반입한다.
5. v1 원본 OCR 청크를 생성한다.
   - `data/processed/chunks_v1_original_ocr.jsonl`
6. v1 rechunk 작업용 extracted 디렉터리를 만든다.
   - `data/extracted_v1_rechunked/`
7. 상담사례집 target 16페이지 보정 후 v1 rechunk 청크를 만든다.
   - `data/processed/chunks_v1_rechunked_only_sangdam.jsonl`
   - `data/processed/chunks_v1_rechunked_target16.jsonl`
8. v2 manual 청크를 만든다.
   - `data/processed/chunks_v2_manual.jsonl`
9. v2 manual 인덱스를 만든다.
   - `data/index_v2_manual/bm25.pkl`
   - `data/index_v2_manual/chroma/chroma.sqlite3`
10. v1/v2 combined 청크를 만든다.
    - `data/processed/chunks_v1_v2_combined.jsonl`
11. v1/v2 combined 인덱스를 만든다.
    - `data/index_v1_v2_combined/bm25.pkl`
    - `data/index_v1_v2_combined/chroma/chroma.sqlite3`
12. v1/v2 pair mapping을 만든다.
    - `data/mapping/v1_v2_pairs_실무가이드.jsonl`
    - `data/mapping/v1_v2_pairs_상담사례집.jsonl`
13. 최종 필수 산출물 존재 여부와 라인 수를 출력한다.
14. `--run-streamlit`이 있으면 `scripts/run_offline_streamlit_test.sh`를 이어서 실행한다.

## 기본 자원 정책

장기 운영 기본값은 다음과 같다.

```text
Streamlit 앱: CPU
RAG query embedding: CPU 기본
Reranker: CPU 기본
SGLang/vLLM 대형 LLM: GPU 0
인덱스 생성/대량 임베딩: GPU 0
```

`prepare_streamlit_runtime.sh`는 대량 인덱스/임베딩 생성 작업이 포함되어 있으므로 기본적으로 `CUDA_VISIBLE_DEVICES=0`으로 실행한다.

CPU로 인덱스를 만들고 싶으면:

```bash
bash scripts/prepare_streamlit_runtime.sh --cpu-index
```

## 주요 옵션

준비 후 Streamlit 실행:

```bash
bash scripts/prepare_streamlit_runtime.sh --run-streamlit
```

기존 Streamlit 교체:

```bash
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --replace
```

8502 포트로 실행:

```bash
bash scripts/prepare_streamlit_runtime.sh --run-streamlit --port 8502
```

오프라인 asset 준비/검증 생략:

```bash
bash scripts/prepare_streamlit_runtime.sh --skip-offline-assets
```

임베딩/reranker 로드 검증 생략:

```bash
bash scripts/prepare_streamlit_runtime.sh --no-verify-load
```

청크 재생성:

```bash
bash scripts/prepare_streamlit_runtime.sh --force-chunks
```

인덱스 재생성:

```bash
bash scripts/prepare_streamlit_runtime.sh --force-indexes
```

pair mapping 재생성:

```bash
bash scripts/prepare_streamlit_runtime.sh --force-mapping
```

v2 handoff 자동 반입 금지:

```bash
bash scripts/prepare_streamlit_runtime.sh --skip-v2-handoff-import
```

## 로그

준비 스크립트 로그는 repo 내부 `logs/`에 저장된다.

```text
logs/prepare_streamlit_runtime_YYYYMMDD_HHMMSS.log
```

Streamlit 실행 로그는 기존 런처 정책을 따른다.

```text
logs/offline_streamlit_test_YYYYMMDD_HHMMSS.log
```

## 완료 후 테스트할 기능

앱 접속 후 다음을 확인한다.

- 일반 질의
- 퀵 코드 검색
- 약관 정형 검색
- 보험금 지급예상액 계산
- OCR index mode 기본 인덱스
- OCR index mode 보정본 OCR만
- OCR index mode v1/v2 combined 비교 모드
- SGLang `gpt-oss-20b`
- vLLM `gemma-4-26b-a4b-nvfp4`
- Ollama `exaone3.5:7.8b` fallback

## 주의사항

- 이 스크립트는 필요한 경우 Chroma/BM25 인덱스를 생성하므로 시간이 오래 걸릴 수 있다.
- `--force-indexes`는 기존 인덱스 디렉터리를 재작성하므로 다른 팀원이 앱을 테스트 중일 때는 피한다.
- 런타임 산출물은 Git 커밋 대상이 아니다.
  - `data/extracted_v2_manual/`
  - `data/extracted_v1_rechunked/`
  - `data/processed/chunks_v1_*.jsonl`
  - `data/processed/chunks_v2_manual.jsonl`
  - `data/processed/chunks_v1_v2_combined.jsonl`
  - `data/index_v2_manual/`
  - `data/index_v1_v2_combined/`
  - `data/mapping/`
  - `reports/mapping_low_confidence/`

## 구현 검증

스크립트 구현 후 다음 검증을 수행했다.

```bash
bash -n scripts/prepare_streamlit_runtime.sh
bash scripts/prepare_streamlit_runtime.sh --help
```

대량 인덱스 재생성은 이미 사용자가 수동으로 완료한 상태이므로, 커밋 전 자동으로 다시 실행하지 않았다.
