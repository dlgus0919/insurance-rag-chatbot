# DGX Spark 이관 설명서 (ChatGPT 전달용)

작성일: 2026-05-15  
기준 브랜치: `master` (`d4df1c4`)  
추가 참조 브랜치(매뉴얼 OCR 보정): `codex/ocr-v2-manual-sangdam-saryejip-p326-p350` (`c283d81`)

---

## 1) 프로젝트 한 줄 요약

신한EZ손해보험 사내 캡스톤용 보험 문서 RAG 챗봇으로, PDF/스캔 PDF를 OCR + 청킹 + 벡터/BM25 인덱싱 후 Streamlit 챗봇에서 검색/응답하는 시스템입니다.

---

## 2) 현재 운영 아키텍처

- 앱: Streamlit (`src/ui/streamlit_app.py`)
- 검색:
  - Dense: ChromaDB
  - Sparse: BM25
  - Fusion: RRF + (옵션) reranker
- 임베딩: `BAAI/bge-m3`
- LLM:
  - 기본 로컬: Ollama
  - 선택: OpenAI API
- OCR:
  - 기본 엔진: CLOVA Native
  - 보조 옵션: True Hybrid (코드 유지, 기본 비활성)
  - 표 품질 개선: Vision cleaner + numeric refiner

---

## 3) 주요 데이터 경로

- 원본 OCR 산출물(운영): `data/extracted/`
- 청크: `data/processed/chunks.jsonl`
- 검색 인덱스: `data/index/`
  - `bm25.pkl`
  - `chroma/`
  - `surgery_grades.parquet`
  - `disability_rates.parquet`
- 평가셋:
  - `eval/smoke_qa.jsonl`
  - `eval/smoke_qa_v2.jsonl`
  - `eval/ocr_qa.jsonl`

주의: 원본 PDF/XLSX/OCR 대용량 산출물은 GitHub에 직접 포함하지 않고, 별도 자산/스토리지로 관리합니다.

---

## 4) 문서 소스 구성 (config 기준)

`src/config.py`의 `PDF_SOURCES` 기준:

- 텍스트 PDF: 심평원, 약관류(복수), 표준약관
- 스캔 PDF(OCR 필수):
  - `실무가이드` (`Claim 실무종합가이드.pdf`)
  - `상담사례집` (`소비자 상담 주요 사례집.pdf`)

---

## 5) 검증된 핵심 실행 커맨드

### OCR

```bash
python scripts/run_full_ocr.py --doc all --yes
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64,255 --force --yes
```

### 인덱싱

```bash
python scripts/ingest.py --include-ocr --stage all
```

### 평가

```bash
pytest -q
python scripts/eval.py --ocr
```

retrieval-only(LLM 없이) 점검:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 \
python scripts/eval.py --ocr
```

---

## 6) DGX Spark 이관 시 필수 반영 항목

### 6-1. 런타임/패키지

- Python 3.11 권장
- `requirements.txt` 설치
- CUDA/GPU 환경에서 `sentence-transformers`, `torch` 동작 확인

### 6-2. 환경변수/시크릿

민감정보는 코드/문서에 하드코딩하지 말고 DGX 비밀 저장소로 주입:

- CLOVA OCR: invoke URL, secret key
- OpenAI: `OPENAI_API_KEY` (사용 시)
- 앱 설정:
  - `EMBEDDING_MODEL=BAAI/bge-m3`
  - `OLLAMA_HOST` (원격 Ollama 사용 시)
  - `RERANKER_ENABLED`
  - `HF_MODEL_DOWNLOAD` (폐쇄망 정책에 맞춰 설정)

### 6-3. 아티팩트/스토리지 전략

- `data/extracted`, `data/processed/chunks.jsonl`, `data/index`를 DGX 공유 스토리지에 영속화
- 재부팅/재배포 후에도 동일 경로를 마운트해 재사용
- Chroma index는 원자적으로 교체(임시 경로 생성 후 swap) 권장

### 6-4. 운영 실행 순서

1. OCR 산출물 동기화/검증
2. `ingest.py --include-ocr --stage all`
3. `pytest -q`
4. `eval.py --ocr` (또는 retrieval-only)
5. Streamlit 실행

---

## 7) 매뉴얼 OCR 보정 브랜치 포함 사항 (중요)

브랜치: `codex/ocr-v2-manual-sangdam-saryejip-p326-p350`  
최신 확인 커밋: `c283d81`

### 7-1. 브랜치 목적

- 기존 OCR(`data/extracted`)을 보존한 채,
- 별도 교정본 경로 `data/extracted_v2_manual/`에 배치 단위 수동 보정을 누적

### 7-2. 브랜치 전용 스크립트

- `scripts/generate_v2_manual_batch_plan.py`
- `scripts/prepare_v2_manual_batch.py`
- `scripts/render_v2_manual_batch_pages.py`
- `scripts/validate_v2_manual_batch.py`

### 7-3. 운영 원칙

- 절대 수정 금지:
  - `data/extracted/`
  - `data/processed/chunks.jsonl`
  - `data/index/`
- 보정 결과는 `data/extracted_v2_manual/`만 수정
- 배치별 검증 JSON/보고서 생성 후 커밋

### 7-4. 최근 정상화 이력

- B07(`상담사례집 p151-p175`) 이슈 해결:
  - 문제: `critical_numeric_drop` (p151 overlap 0.2)
  - 조치: `p151_t01` table 복원
  - 결과: validator `ok=true`, p151 overlap `1.0`
  - 커밋: `eb3584d3cdd0a5cf00e94f3da44e8582192d7ce4`

### 7-5. 진행 현황 (집계 기준)

- 실무가이드: 배치 준비 이력 1건(초기 준비 상태)
- 상담사례집: 다수 배치 진행 중이며, 최신 상태 기준
  - `corrected_validated`: 8개 배치
  - `prepared`: 1개 배치

---

## 8) DGX 이관 시 권장 전략 (본 프로젝트 기준)

1. **1차 이관 대상은 master 운영 파이프라인**
   - OCR/ingest/eval/앱 기동 안정화 우선
2. **2차 이관으로 v2_manual 브랜치 병행**
   - 별도 job으로 배치 보정 자동화
   - 운영 인덱스와 분리된 실험 인덱스(`index_v2_manual`) 사용
3. **병합 기준 명확화**
   - `validate_v2_manual_batch.py` 통과
   - 샘플 페이지 원본 대조 HTML 검토 완료
   - regression test 통과 후 master 반영

---

## 9) ChatGPT에게 요청할 작업 범위 템플릿

아래 범위를 ChatGPT에게 직접 전달하면 이관 작업을 빠르게 시작할 수 있습니다.

- 목적: DGX Spark에서 OCR+RAG 파이프라인 재현
- 범위:
  1) 환경 구축(Python/패키지/GPU 확인)
  2) 시크릿 주입(CLOVA/OpenAI)
  3) 데이터 마운트 전략 설계(`extracted`, `processed`, `index`)
  4) ingest/eval 실행 자동화 스크립트 작성
  5) Streamlit 서비스 기동 및 헬스체크
  6) (선택) v2_manual 브랜치 배치 보정 job 분리

