# OCR v2 Manual Dataset Integration Handoff

작성일: 2026-05-16  
대상: DGX Spark 이관 이후 수동 보정 OCR 데이터셋 편입 담당 에이전트  
기준 worktree: `/Users/june_kim/.codex/worktrees/64ac/보험 문서 RAG 챗봇`  
기준 branch: `codex/ocr-v2-manual-sangdam-saryejip-p326-p350`  
최종 관련 커밋:

- `f6f836a` `Complete OCR v2 manual dataset and final integrity report`
- `3cd03bf` `Record final OCR dataset push blocker`

---

## 1. 목적

이 문서는 완성된 `data/extracted_v2_manual/` 수동 보정 OCR 데이터셋을 추후 DGX Spark 운영 프로젝트에 안전하게 편입하기 위한 인수인계 문서다.

핵심 원칙:

- 기존 운영 OCR 경로 `data/extracted/`는 즉시 덮어쓰지 않는다.
- 수동 보정본은 별도 경로 `data/extracted_v2_manual/`로 먼저 이관한다.
- 별도 chunks/index/eval을 만든 뒤 품질 기준을 만족할 때만 운영 승격을 결정한다.
- 수동 보정 데이터셋과 검토 이미지 산출물은 GitHub remote에 올리지 않는다.

---

## 2. 데이터셋 현황

최종 수동 보정 데이터셋:

- 경로: `data/extracted_v2_manual/`
- 크기: 약 `12M`
- 파일 수: `2,472`
- 전체 배치: `27/27` 완료
- `상담사례집`: `14/14` 완료
- `실무가이드`: `13/13` 완료
- 전체 validator: `27/27 PASS`
- 실패: `0`

문서별 manifest 상태:

| 문서 | manifest pages | text blocks | table blocks | batch status |
|---|---:|---:|---:|---|
| `실무가이드` | 328 | 612 | 313 | 13/13 `corrected_validated` |
| `상담사례집` | 350 | 932 | 133 | 14/14 `corrected_validated` |

원본 운영 OCR과 동일하게 source missing page는 유지한다.

- `실무가이드`: p203, p297 source missing
- `상담사례집`: p009 source missing

이 missing page는 정상 결측이다. 임의로 빈 페이지를 만들거나 source dataset을 보정하지 않는다.

---

## 3. 품질 검증 요약

최종 무결성 검증 결과:

- Aggregate table blocks: `537 -> 446`
- Aggregate false-positive tables: `89 -> 0`
- Aggregate text artifacts: `18 -> 16`

남은 `text_artifact` 16건은 validator regex의 false-positive로 판정됐다. 주식/배경 이미지 OCR 잡음이 아니라 정상 영문 의학/해부 용어다.

대표 잔류 정상 용어:

- `Radical curative surgery`
- `Carpal Tunnel Synd`
- `Tarsal Tunnel Synd`
- `American Medical Association`
- `HESS Screen test`
- `fine needle aspiration`
- `fine aspiration biopsy`

중요 보정 사례:

- `상담사례집 B07 p151-p175`
  - `p151_t01`을 단순 text downcast하면 critical numeric overlap이 `0.2`로 하락했다.
  - 최종 조치: table block 유지, JSON schema를 `quote_type`, `quote_text` 2-column으로 정규화.
  - 결과: false-positive `1 -> 0`, p151 numeric overlap `1.0`, validator PASS.

---

## 4. 전달용 압축본

전달용 압축본에는 필수 편입 데이터와 검증 메타데이터만 포함한다.

포함 대상:

- `data/extracted_v2_manual/`
- `reports/ocr_v2_manual/full_integrity_summary.json`
- `reports/ocr_v2_manual/validation_*.json`
- `docs/67A_OCR_V2_MANUAL_BATCH_PLAN.md`
- `docs/67A_OCR_V2_MANUAL_BATCH_PLAN.json`
- `docs/67A_OCR_V2_MANUAL_SETUP_REPORT.md`
- `docs/67A_B07_FINALIZE_AND_AUTOMATION_NORMALIZE_REPORT.md`
- `docs/67A_BATCH_*_REPORT.md`
- `docs/67B_OCR_V2_MANUAL_FINAL_COMPLETION_REPORT.md`
- v2 manual helper scripts:
  - `scripts/generate_v2_manual_batch_plan.py`
  - `scripts/prepare_v2_manual_batch.py`
  - `scripts/render_v2_manual_batch_pages.py`
  - `scripts/validate_v2_manual_batch.py`

제외 대상:

- `reports/ocr_v2_manual/images/` 전체 원본 페이지 이미지
- 기존 운영 `data/extracted/`
- 기존 운영 `data/processed/chunks.jsonl`
- 기존 운영 `data/index/`
- `data/index_v2_manual/`
- `chunks_v2_manual.jsonl`
- secret/env/log/cache 파일

압축본은 Git 편입 대상이 아니다. DGX 이관 시 `rsync` 또는 `scp`로 별도 전송한다.

---

## 5. master 편입 시 필요한 코드 작업

현재 master의 `scripts/ingest.py`는 기본적으로 `data/extracted/`, `data/processed/chunks.jsonl`, `data/index/` 고정 경로를 사용한다. v2 manual을 안전하게 검증하려면 path override가 필요하다.

필수 코드 변경:

1. `scripts/ingest.py`
   - `--extracted-root`
   - `--chunks-path`
   - `--index-root`
   - `build_chunks()`와 `build_index()`가 CLI 인자를 사용하도록 수정

2. `scripts/eval.py`
   - `--bm25-path`
   - `--chroma-dir`
   - 필요 시 `--disable-table-store`

3. `.gitignore`
   - `data/extracted_v2_manual/`
   - `data/processed/chunks_v2_manual.jsonl`
   - `data/index_v2_manual/`
   - `reports/ocr_v2_manual/`
   - 전달용 archive 확장자 또는 handoff 디렉터리

4. v2 helper scripts 선별 편입
   - validator는 추후 회귀 검증에 필요하므로 master에 포함 권장
   - prepare/render/generate scripts는 재작업/추가 감사에 필요하면 포함

주의:

- worktree 전체 merge 금지.
- large OCR dataset 포함 commit 금지.
- code/doc만 선별 편입한다.

---

## 6. DGX 편입 절차 제안

### Phase 1. 압축본 전송

예시:

```bash
rsync -avP /path/to/ocr_v2_manual_handoff_20260516.tar.gz \
  ai-hang@100.88.5.57:/srv/shared/projects/insurance-rag-chatbot/
```

### Phase 2. DGX에서 압축 해제

```bash
cd /srv/shared/projects/insurance-rag-chatbot
tar -xzf ocr_v2_manual_handoff_20260516.tar.gz
```

해제 후 기대 경로:

- `/srv/shared/projects/insurance-rag-chatbot/data/extracted_v2_manual/`
- `/srv/shared/projects/insurance-rag-chatbot/reports/ocr_v2_manual/*.json`
- `/srv/shared/projects/insurance-rag-chatbot/docs/67*.md`

### Phase 3. 무결성 검증

```bash
python3 scripts/validate_v2_manual_batch.py \
  --doc 상담사례집 \
  --page-start 0 \
  --page-end 25 \
  --source-root data/extracted \
  --target-root data/extracted_v2_manual \
  --output reports/ocr_v2_manual/recheck_상담사례집_p000-p025.json
```

단일 샘플 검증 후 전체 batch 검증은 `full_integrity_summary.json`의 batch plan을 참고해 반복 실행한다.

### Phase 4. v2 chunks 생성

master에 path override가 들어간 뒤에만 실행한다.

```bash
python scripts/ingest.py \
  --include-ocr \
  --stage chunks \
  --extracted-root data/extracted_v2_manual \
  --chunks-path data/processed/chunks_v2_manual.jsonl
```

### Phase 5. v2 index 생성

```bash
python scripts/ingest.py \
  --stage index \
  --chunks-path data/processed/chunks_v2_manual.jsonl \
  --index-root data/index_v2_manual
```

### Phase 6. v2 eval

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
python scripts/eval.py --ocr \
  --bm25-path data/index_v2_manual/bm25.pkl \
  --chroma-dir data/index_v2_manual/chroma
```

LLM 포함 eval은 Ollama와 target model이 정상일 때 별도로 실행한다.

---

## 7. 운영 승격 기준

v2 manual을 운영 데이터로 채택하려면 아래 조건을 만족해야 한다.

- `pytest -q` 통과
- OCR retrieval eval `recall@8 = 1.000` 유지
- 기존 운영 index 대비 주요 수술종수/장해지급률 질의 품질 하락 없음
- `scripts/build_table_index.py` 재생성 후:
  - `surgery_grades.parquet` 정상 생성
  - `disability_rates.parquet` 정상 생성
  - 핵심 lookup 테스트 통과
- Streamlit smoke QA 통과
- 긴 문서/표 질의에서 LLM 답변 악화 없음

승격 전까지 운영 앱은 기존 `data/extracted/`, `data/processed/chunks.jsonl`, `data/index/`를 계속 사용한다.

---

## 8. 기존 워크플로우와 충돌 위험

### 8-1. 경로 충돌

기존 경로:

- `data/extracted/`
- `data/processed/chunks.jsonl`
- `data/index/`

v2 검증 경로:

- `data/extracted_v2_manual/`
- `data/processed/chunks_v2_manual.jsonl`
- `data/index_v2_manual/`

위 경로를 분리하지 않으면 기존 운영 index가 덮일 수 있다.

### 8-2. source missing page 처리

known missing source page:

- `실무가이드`: p203, p297
- `상담사례집`: p009

validator는 source manifest에 없는 페이지를 failure가 아니라 `skipped_missing_source_pages`로 처리해야 한다. source dataset을 임의 수정하지 않는다.

### 8-3. p151 quote table 처리

`상담사례집 p151_t01`은 false-positive처럼 보이나 numeric overlap 보존을 위해 table로 유지해야 한다. 단순 downcast 금지.

### 8-4. table index 영향

v2 manual의 table count가 기존보다 줄었다. false-positive table 제거는 긍정적이지만, `build_table_index.py`가 기대하는 수술종수/장해표 추출량이 변할 수 있다. 반드시 parquet 재생성과 lookup 검증을 수행한다.

### 8-5. GitHub push 위험

`data/extracted_v2_manual/`과 `reports/ocr_v2_manual/images/`는 외부 GitHub remote push 대상이 아니다. GitHub에는 코드, 문서, 작은 검증 summary만 올린다.

### 8-6. DGX 운영 중 재인제스트 위험

`ingest.py --stage all`은 `chunks.jsonl`과 `data/index/`를 재생성한다. v2 검증 중에는 반드시 별도 경로를 사용해야 한다.

---

## 9. 다른 에이전트에게 줄 실행 지시 요약

다른 에이전트가 편입을 맡을 경우 아래 순서를 따르게 한다.

1. master에 path override 코드가 있는지 확인한다.
2. 압축본을 DGX 프로젝트 루트에 해제한다.
3. `data/extracted_v2_manual/` 존재와 manifest를 확인한다.
4. sample validator를 실행한다.
5. `chunks_v2_manual.jsonl`을 생성한다.
6. `data/index_v2_manual/`을 생성한다.
7. `eval.py --ocr`를 v2 index 대상으로 실행한다.
8. table parquet를 v2 기준으로 재생성할지 별도 판단한다.
9. 운영 승격 전 기존 index를 덮어쓰지 않는다.

---

## 10. 아직 수행하지 않은 작업

- `data/processed/chunks_v2_manual.jsonl` 생성
- `data/index_v2_manual/` 생성
- v2 manual retrieval eval
- v2 manual LLM eval
- v2 기준 table parquet 재생성
- Streamlit v2 source switching
- 운영 승격

위 작업은 모두 장시간 quality gate이며, DGX Spark에서 명시 승인 후 수행한다.

