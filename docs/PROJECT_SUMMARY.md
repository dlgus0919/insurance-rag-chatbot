# 보험 문서 RAG 챗봇 — 개발 진행 요약

> 작성일: 2026-05-12  
> 대상: 신규 참여 개발자 온보딩 / 인수인계용

---

## 1. 프로젝트 개요

국내 보험사 실무 문서 2종(스캔 PDF)을 OCR 처리하여 RAG 챗봇의 검색 인덱스를 구축하는 파이프라인이다.

| 문서 | 페이지 수 | 특성 |
|---|---|---|
| 실무가이드 | 330p | 수술분류표·장해분류표 포함, 복잡한 다열 표 |
| 상담사례집 | 351p | 보험 분쟁 상담 사례 텍스트 위주 |

**역할 분리 원칙**: Claude(기획·검토) ↔ Codex(구현·테스트). Claude가 `docs/` 폴더에 Markdown 명세를 작성하면 Codex가 구현하고, Claude가 결과를 검토하는 방식으로 진행한다.

---

## 2. 기술 스택

| 레이어 | 내용 |
|---|---|
| OCR 엔진 | CLOVA OCR (Naver Cloud) + PP-Structure (레이아웃 검출, 선택적 사용) |
| Vision 후처리 | Claude claude-sonnet-4-5 Vision (표 정제, 수술종수 보정) |
| 검색 백엔드 | ChromaDB (벡터) + BM25 |
| 프론트엔드 | Streamlit Cloud |
| 파이프라인 | `scripts/run_full_ocr.py` → `scripts/ingest.py` |

---

## 3. OCR 파이프라인 진화 이력

### Phase 1 — 기반 구축 (명세 #38–40)

- `src/parser/clova_ocr.py` : CLOVA 응답에서 텍스트 블록·테이블 블록 추출
- `src/parser/ocr_chunker.py` : 블록을 RAG용 청크로 분할
- PP-Structure 기반 레이아웃 감지 → CLOVA 영역 매핑 ("True Hybrid")
- 결과 비교 HTML 생성 스크립트 (`scripts/generate_compare_html.py`)

### Phase 2 — True Hybrid 완성 (명세 #41–44)

- CLOVA 네이티브 테이블 감지 통합 (`--clova-native` 플래그)
- PP-Structure figure 마스킹 제거 → 텍스트 누락 감소
- CLOVA API 타임아웃·재시도 로직 강화
- 전체 실행 스크립트 `scripts/run_full_ocr.py` 완성  
  - `--doc all|실무가이드|상담사례집` + `--pages` 필터 + `--force` 재처리

### Phase 3 — 표 품질 개선 (명세 #45–46, #51–52)

**Vision LLM 표 정제** (`src/parser/table_vision_cleaner.py`)  
- 다단 헤더 병합, 셀 내용 수정 등 Vision LLM이 원본 이미지 보고 표를 재정제
- 실무가이드 기준 73%의 테이블에 적용됨

**수술종수 후보정** (`src/parser/numeric_cell_refiner.py`)  
- "1-3종 / 1-5종 / 신1-5종" 컬럼 빈 셀을 Vision LLM으로 채움  
- 처음에는 전체 table_json echo 방식 → max_tokens 초과로 실패  
  - **수정 (명세 #51)**: corrections-only delta 포맷, `max_tokens=512`  
  - **추가 수정 (명세 #52)**: 후보 행이 많을 때 chunk 분할 처리, `max_tokens=1536`으로 상향  
- 결과: 86개 테이블, 1,330+ 셀 자동 보정

### Phase 4 — 단어 순서 수정 (명세 #50–51)

**문제**: `_fields_to_lines()` 함수가 CLOVA 응답의 단어를 Y→X 좌표 순으로 재정렬하여 읽기 순서가 깨짐

- **1차 수정 (명세 #50)**: `lineBreak` 플래그 의존 제거 → Y-gap 기반 줄 분리로 변경
- **2차 수정 (명세 #51)**: Y-그룹 내부 단어 정렬을 `center_X` 기준 → **CLOVA 원본 field 인덱스** 순서로 변경  
  - 스캔 기울기로 인한 X 좌표 오차가 인접 단어를 뒤집는 버그 해결  
  - 검증: p255 "원칙적으로 각각" (정상), p064 수술종수 corrections 12건

### Phase 5 — 워크플로우 확정 (명세 #53)

- **기본 엔진을 CLOVA native로 확정** (PP-Structure 없이 CLOVA 자체 테이블 감지 사용)
- `python scripts/run_full_ocr.py --doc all --yes` = 기본 실행
- True Hybrid는 `--true-hybrid` 플래그로 선택 실행 가능 (코드 보존)

### Phase 6 — RAG 파이프라인 + LLM 품질 개선 (명세 #54–58)

**RAG 인덱스 구축 및 eval 자동화** (명세 #54)
- `scripts/ingest.py --include-ocr --stage all` 로 ChromaDB + BM25 인덱스 최초 구축
- 40건 OCR QA(`eval/ocr_qa.jsonl`) 자동 평가 파이프라인 완성
- 최초 baseline eval 결과: retrieval recall@8=0.975, grade_accuracy=0.353, rate_accuracy=0.357

**스테일 파일 정리** (명세 #55, #57)
- `data/extracted/실무가이드/text/` 내 manifest 미등록 stale 파일 13개 전체 삭제 완료
- `scripts/verify_p255_word_order.py` — Stale files: 0 확인

**수술명 행 부스팅** (명세 #56)
- `_extract_surgery_name_from_query()` + `_boost_surgery_name_table_rows()` 추가
- RRF 풀을 `final_top_k * 3`으로 확장, reranker 전 수술명 행 재정렬
- 결과: retrieval **recall@8 = 1.000** (ocr_011 MISS → HIT)

**LLM 품질 개선 A+B** (명세 #57 검토, #58 구현)
- **A — 시스템 프롬프트 개선:** SYSTEM_PROMPT 핵심 규칙 7 추가 + 수술종수·장해 지급률 few-shot 예시 2건
- **B — 구조화 행 주입:** `_extract_disability_region_from_query()` + `_build_structured_context()` 구현
  - 수술명 또는 장해 부위가 감지되면 `[구조화 데이터 — 검색 결과 기반]` 블록을 LLM 프롬프트 앞에 삽입
  - C 방안 호환 예약 파라미터 `table_store=None` 포함
- pytest: 235 passed (신규 테스트 6건 추가)
- LLM eval(grade_accuracy, rate_accuracy)은 Ollama 연결 환경에서 별도 수행 필요

### Phase 7 — 인덱스 고도화 + 문서화 (명세 #59–60)

**문서화** (명세 #59)
- `docs/PROJECT_SUMMARY.md` 갱신 (#54–#58 반영)
- `docs/59_STREAMLIT_OCR_QA_SCENARIO.md` 신규 작성: 실무가이드·상담사례집 기반 수동 QA 시나리오 14건 (S01~S14)

**Parquet 테이블 인덱스** (명세 #60)
- `scripts/build_table_index.py` 신규 작성: OCR 표 JSON → Parquet 변환
- 생성물:
  - `data/index/surgery_grades.parquet` — 수술종수표 **2,408행** (p33~p175, 192개 파일)
  - `data/index/disability_rates.parquet` — 장해분류표 **100행** (신체부위별 13개 파일)
- `src/rag/table_store.py` 신규: `TableStore` 직접 조회 인터페이스 (`lookup_surgery_grade`, `lookup_disability_rate`)
- `src/rag/pipeline.py`: C hook 활성화 — Parquet 조회 성공 시 `[구조화 데이터 — 직접 조회 (C)]` 블록 우선 주입, 실패 시 B(table_json) fallback
- pytest: **240 passed** (신규 테스트 5건 추가)

**핵심 조회 검증 완료:**

| 질의 | 결과 | 출처 |
|---|---|---|
| 충수절제술 1-5종 | 2종 | 실무가이드 p.109 |
| 두 눈이 멀었을 때 지급률 | 100% | 실무가이드 p.236 |
| 한 팔 손목 이상 지급률 | 60% | 실무가이드 p.255 |
| 두 귀 청력 상실 지급률 | 80% | 실무가이드 p.242 |

---

## 4. 현재 데이터 상태

### 전체 OCR 결과 (`data/extracted/`)

| 문서 | 처리 완료 | 영구 실패 | 비고 |
|---|---|---|---|
| 실무가이드 | 328/330p | p203, p297 | 빈/이미지 페이지 |
| 상담사례집 | 350/351p | p009 | 빈/이미지 페이지 |

**Vision/Numeric 처리 (실무가이드)**

| 항목 | 수치 |
|---|---|
| 테이블 블록 | 317개 |
| vision_cleaned | 231개 (73%) |
| numeric_refined | 86개 (27%) |
| corrections 총합 | ~1,330셀 |
| unresolved 셀 | 133셀 (31페이지) — 수동 확인 권장 |

> 상담사례집은 수술종수 컬럼이 없는 문서 특성상 `numeric_refined=0`이 정상

**Parquet 인덱스 (`data/index/`)**

| 파일 | 행 수 | 내용 |
|---|---|---|
| `surgery_grades.parquet` | 2,408 | 수술종수표 전체 (p33~p175, 신체부위별 라벨 포함) |
| `disability_rates.parquet` | 100 | 장해분류표 전체 (신체부위 15종, 지급률 정규화 완료) |

### manifest 구조 (페이지당 대표 필드)

```json
{
  "page_no": 63,
  "page_label": 64,
  "engine": "clova_native",
  "blocks": [
    {
      "type": "text",
      "file": "text/p063_b00.txt",
      "bbox": [...],
      "confidence": 0.95,
      "source_method": "ocr_clova"
    },
    {
      "type": "table",
      "file": "tables/p063_t00.txt",
      "vision_cleaned": true,
      "numeric_refined": true,
      "numeric_corrections": [...],
      "numeric_refiner_status": "refined",
      "numeric_refiner_chunks": [...]
    }
  ]
}
```

---

## 5. 파일 구조

```
보험 문서 RAG 챗봇/
├── src/
│   ├── parser/
│   │   ├── clova_ocr.py          # OCR 핵심: fields → LayoutBlock 변환
│   │   ├── numeric_cell_refiner.py # 수술종수 Vision 후보정
│   │   ├── table_vision_cleaner.py # 표 Vision 정제
│   │   ├── ocr_chunker.py         # 블록 → RAG 청크
│   │   └── ocr_engine.py          # PP-Structure 레이아웃 감지
│   ├── rag/
│   │   └── pipeline.py           # retrieve_hits, answer, 수술명/장해 구조화 컨텍스트
│   └── llm/
│       └── prompt.py             # SYSTEM_PROMPT, build_user_prompt
├── scripts/
│   ├── run_full_ocr.py            # 전체 OCR 실행 (메인 진입점)
│   └── ingest.py                  # ChromaDB + BM25 인덱스 구축
├── eval/
│   ├── ocr_qa.jsonl              # OCR 문서 40건 자동 평가 세트
│   ├── smoke_qa.jsonl            # 약관·심평원 스모크 평가 (15건)
│   └── smoke_qa_v2.jsonl         # 스모크 v2
├── data/
│   ├── extracted/
│   │   ├── 실무가이드/
│   │   │   ├── manifest.json
│   │   │   ├── text/p###_b##.txt
│   │   │   └── tables/p###_t##.txt
│   │   └── 상담사례집/
│   │       └── (동일 구조)
│   ├── index/
│   │   ├── surgery_grades.parquet   # 수술종수표 Parquet
│   │   └── disability_rates.parquet # 장해분류표 Parquet
│   └── processed/       (기존)
├── tests/                         # pytest 테스트 (235개, 전원 통과)
├── docs/                          # 명세서·보고서 아카이브
└── reports/                       # OCR 비교 HTML 결과물
```

---

## 6. 실행 명령어 요약

```bash
# 전체 OCR 실행 (기본 = CLOVA native)
python scripts/run_full_ocr.py --doc all --yes

# 특정 문서·페이지 재처리
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64,255 --force --yes

# True Hybrid 방식으로 실행
python scripts/run_full_ocr.py --doc all --true-hybrid --yes --output-dir reports/true_hybrid_run

# RAG 인덱스 재구축 (OCR 완료 후)
python scripts/ingest.py --include-ocr --stage all

# 전체 테스트
pytest -q

# OCR 자동 eval (LLM 포함, Ollama 실행 필요)
python scripts/eval.py --ocr

# retrieval-only eval (Ollama 불필요)
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py --ocr

# Parquet 테이블 인덱스 재생성 (OCR 데이터 변경 시)
python scripts/build_table_index.py
```

---

## 7. 잔여 과제

| 항목 | 우선순위 | 상태 | 비고 |
|---|---|---|---|
| A+B+C LLM eval 결과 확인 (grade/rate 측정) | 🔴 높음 | 진행 중 | `logs/eval_ocr_abc_*.log` |
| smoke_v2 recall 개선 (약관 청크 재분할) | 🟡 중간 | 명세 작성 완료 (#61) | eval 완료 후 착수 |
| Streamlit 챗봇 수동 QA | 🟡 중간 | 시나리오 준비 완료 | `docs/59_STREAMLIT_OCR_QA_SCENARIO.md` 기준 |
| Task 2 (보험금 자동 계산) 기획 | 🟡 중간 | 미착수 | Parquet 데이터 활용 |
| unresolved 셀 133개 수동 검토 | 🟢 낮음 | 미착수 | 원본 이미지와 대조 필요 |
| 영구 실패 3페이지 (NO_TEXT) | 🟢 낮음 | 미착수 | 빈 페이지로 추정 |
