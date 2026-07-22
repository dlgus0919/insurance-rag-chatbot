# 234. Digital PDF Table Extraction Patch Report

작성일: 2026-06-15

## 목적

디지털 생성 PDF 약관의 시각적 표를 OCR/LLM 없이 텍스트 레이어와 PDF geometry 기반으로 구조화하고, 기존 `clause_detail_rows` evidence 계층에 연결했다.

000번 규칙 기준으로 이번 변경은 보험 지식 값을 코드에 넣지 않는다. 코드는 표 추출과 row 로딩만 수행하며, 답변 수치와 문구는 원천 PDF에서 추출된 `table_json` row 또는 기존 source text row에서 읽는다.

## 핵심 변경

- `src/parser/digital_pdf_tables.py`
  - `pdfplumber` 기반 디지털 PDF 표 탐지/추출
  - `table_json` 표준 스키마 생성
  - 추출 row provenance: `doc_short`, `page`, `bbox`, `pdf_filename`, `source_method=digital_pdf_table`
- `scripts/extract_digital_pdf_tables.py`
  - 등록된 디지털 `insurance_policy` PDF에 대해 `data/extracted_digital_pdf/{doc}/manifest.json`과 table artifact 생성
- `scripts/ingest.py`
  - 디지털 생성 보험 약관 PDF 청킹 시 표 chunk를 함께 생성
  - 대형 고시 PDF 전체 표 추출은 기본 제외
- `scripts/build_clause_detail_rows.py`
  - 기존 OCR `table_json` chunk와 별도 디지털 PDF table artifact를 함께 읽어 `clause_detail_rows.jsonl` 생성
- `src/rag/pipeline.py`
  - manifest row만으로 답변이 불충분할 때 text/table fallback row를 보완할 수 있도록 row 선택 조정
  - 공제/자기부담 질의에서 숫자만 있는 무관 row가 끼지 않도록 category context 필터 추가
- `config/clause_detail_lookup_policy.json`
  - deductible context에 `본인부담금`, `본인이 부담` 추가

## DGX 산출물 갱신

DGX 메인 저장소에서 LLM 서버를 새로 띄우지 않고 실행했다.

```bash
.venv/bin/python scripts/extract_digital_pdf_tables.py --doc-type insurance_policy
```

결과:

- `약관`: 172p, detected tables 125, table chunks 72
- `자사_SOL건강`: 493p, detected tables 269, table chunks 198
- `자사_SOL운전자`: 281p, detected tables 166, table chunks 104
- `표준약관`: 491p, detected tables 396, table chunks 282
- total table chunks: 656

```bash
.venv/bin/python scripts/build_clause_detail_rows.py --index-mode v2_only
.venv/bin/python scripts/build_clause_detail_rows.py --index-mode v1_v2_combined
```

결과:

- `v2_only`: table chunks 1,548, digital table chunks 656, rows 12,157
- `v1_v2_combined`: table chunks 1,724, digital table chunks 656, rows 13,267

생성된 `data/extracted_digital_pdf/**`와 `data/index_*/clause_detail_rows.jsonl`은 runtime/generated data로 Git 커밋 대상이 아니다.

## 검증

로컬:

```bash
python -m pytest tests/test_digital_pdf_tables.py tests/test_clause_detail_rows.py tests/test_ingest.py -q
python -m pytest tests/test_pipeline.py -q
python -m pytest tests/test_pipeline.py tests/test_clause_detail_rows.py -q
python -m py_compile src/rag/pipeline.py src/parser/digital_pdf_tables.py scripts/extract_digital_pdf_tables.py scripts/ingest.py scripts/build_clause_detail_rows.py
```

DGX:

```bash
.venv/bin/python -m pytest tests/test_digital_pdf_tables.py tests/test_clause_detail_rows.py tests/test_ingest.py tests/test_pipeline.py -q
.venv/bin/python -m py_compile src/rag/pipeline.py src/parser/digital_pdf_tables.py scripts/extract_digital_pdf_tables.py scripts/ingest.py scripts/build_clause_detail_rows.py src/config.py
```

DGX 실데이터 smoke:

- `policy_xlsx_018`: pass, `약관_tbl_000023` digital table row + source text 보완
- `policy_xlsx_019`: pass, `약관_tbl_000023` digital table row 사용
- `policy_xlsx_026`: pass, `약관_tbl_000038` / `약관_tbl_000045` digital table row 사용

## Self-inspection

- 000번 규칙 위반 없음: 정답 수치, 지급 판단, 공제율, 한도를 코드나 정책 파일에 새로 넣지 않았다.
- 망분리 실행성: 외부 API, 외부 LLM, 신규 LLM 서버 기동 없이 DGX 내부 Python dependency로 실행된다.
- 일회성/지속 실행 구분: 표 추출과 row manifest 생성은 신규 원천 데이터 편입 또는 인덱스 갱신 시 실행하는 비지속 배치다. 앱 질의 경로는 생성된 manifest만 읽는다.
- 남은 위험: 병합 셀/이어지는 표/장식성 표는 일부 불완전하게 row화될 수 있다. 현재는 source row provenance와 smoke 평가로 방어하며, 신규 파일 추가 전체 자동화는 별도 source registry와 비동기 ingest 작업으로 확장해야 한다.
