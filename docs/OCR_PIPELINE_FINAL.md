# 최종 OCR 파이프라인 설계 기록

> 작성 기준일: 2026-05-11
> 적용 대상: Claim 실무종합가이드 (스캔본 PDF, 130+ 페이지)
> 확정 파이프라인: **True Hybrid (PP-Structure + CLOVA) + Vision LLM 후처리**

---

## 1. 개발 경과 요약

| 버전 | 핵심 변경 | 결과 |
|---|---|---|
| v38–39 | PaddleOCR 표 재구성 실험 | 복잡한 병합 셀 복원 불안정 |
| v40 | CLOVA OCR 로컬 실행 도입 | 한국어 텍스트 품질 개선 |
| v41 | True Hybrid 파이프라인 구축 | PP-Structure 레이아웃 + CLOVA OCR 조합 |
| v42 | figure 마스킹 제거 | figure 영역을 CLOVA에 전달하지 않는 방식으로 전환 |
| v43 | CLOVA native table 감지 통합 | `tables[]` 응답으로 셀별 bbox/span 복원 |
| v44 | 엔드포인트 검증 + 전체 60–70페이지 재실행 | 11/11 SUCCESS |
| v45 | 다단 헤더 자동 감지 + Vision LLM 그림 셀 정제 | `수술종수` 헤더 분리, `[그림]` 마킹 |
| v46 | 숫자 셀 Vision 정제 (1차) | 전부 blank 행 후보 처리 — 부분 복원 |
| v47 | 숫자 셀 Vision 정제 (개선) | 부분 blank 포함 처리, 21건 수정 / 0건 미해결 |

---

## 2. 확정 아키텍처

```
[원본 스캔 PDF]
       │
       ▼
┌─────────────────────────────┐
│  PP-Structure (PaddleOCR)   │  레이아웃 분석
│  content_type 분류:          │  text / table / figure / title
│  bbox 좌표 추출              │
└────────────┬────────────────┘
             │ 각 영역 bbox → 페이지 이미지에서 크롭
             ▼
┌─────────────────────────────┐
│  CLOVA OCR API              │  텍스트·표 정밀 인식
│  - text 영역: inferText 추출 │
│  - table 영역: native tables[]│  셀별 행·열·span·텍스트
└────────────┬────────────────┘
             │ table block 존재 시
             ▼ (--vision-clean 플래그 활성화 시)
┌─────────────────────────────┐
│  Vision LLM (OpenAI)        │  표 후처리 (2단계)
│  Step 1: 그림 셀 감지        │  gpt-4o-mini
│          → "[그림]" 마킹     │
│  Step 2: 숫자 셀 보정        │  gpt-4.1
│          → 수술종수 blank 복원│
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  LayoutBlock JSON 직렬화     │  table_json, text, html, raw 메타
└─────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  ocr_chunker.py             │  RAG 청크 변환 → ChromaDB / BM25 인덱싱
└─────────────────────────────┘
```

---

## 3. 핵심 모듈 역할

### `src/parser/clova_ocr.py`

| 함수 | 역할 |
|---|---|
| `clova_ocr_page()` | 페이지 이미지를 받아 CLOVA API 호출, LayoutBlock 리스트 반환 |
| `_request_clova()` | API 호출 (enableTableDetection: True) |
| `_detect_header_rows()` | row-0에 colSpan > 1 셀이 있으면 2행 헤더로 자동 감지 |
| `_build_column_headers()` | 병합 헤더의 하위 행 값을 실제 컬럼명으로 구성 |
| `_table_to_json()` | 다단 헤더 감지 결과에 따라 data row 시작 위치 조정 |
| `_native_table_to_block()` | CLOVA `tables[]` 응답을 LayoutBlock (table_json 포함)으로 변환 |

### `src/parser/table_vision_cleaner.py`

| 함수 | 역할 |
|---|---|
| `clean_table_blocks()` | table block의 그림 셀을 `[그림]`으로 교체 |
| `_crop_table_image()` | block.bbox 기반 표 영역 크롭 |
| `_same_table_shape()` | Vision 응답의 headers/rows 구조 검증 (방어 로직) |

모델: `gpt-4o-mini`

### `src/parser/numeric_cell_refiner.py`

| 함수 | 역할 |
|---|---|
| `refine_numeric_cells()` | 수술종수 컬럼 blank 행을 Vision LLM으로 재판독 |
| `_grade_column_roles()` | `1-3종/1-5종/신1-5종` 또는 `수술종수*` 3컬럼을 그룹으로 식별 |
| `_needs_refinement()` | all blank / partial blank / invalid 값 행을 후보로 판정 |
| `_crop_grade_columns_image()` | 표 전체 크롭 + 수술종수 영역 확대 크롭 (오른쪽 42%) |
| `_extract_valid_corrections_and_unresolved()` | Vision 응답 검증, 허용 값(1/2/3/"") 외 무시 |

모델: `gpt-4.1` (환경변수 `OCR_NUMERIC_VISION_MODEL`로 override 가능)

### `scripts/run_true_hybrid_local.py`

```
python scripts/run_true_hybrid_local.py \
    --doc 실무가이드 \
    --pages 60-70 \
    --vision-clean
```

`--vision-clean` 플래그가 없으면 Vision LLM 단계 완전 생략 (기존 동작 보장).

---

## 4. `raw` 메타데이터 구조

table block의 `block.raw` 예시:

```json
{
  "native_table": true,
  "vision_cleaned": true,
  "numeric_refined": true,
  "numeric_corrections": [
    {
      "row_index": 0,
      "col": "1-3종",
      "from": "",
      "to": "1",
      "method": "vision_llm",
      "reason": "complete_surgery_grade_group",
      "confidence": "high"
    }
  ],
  "numeric_unresolved_cells": null
}
```

---

## 5. 다단 헤더 처리 규칙

CLOVA `tables[]` 응답에서 row-0에 `columnSpan > 1`인 셀이 존재하면 2행 헤더로 자동 감지.

```
Before (기존):
headers: ['수술명', '수술해설', '수술종수', '수술종수_2', '수술종수_3']
row[0]:  {'수술명': '수술명', '수술해설': '수술해설', ...}   ← 헤더 값이 데이터 행에 혼입

After (v45):
headers: ['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']
row[0]:  {'수술명': '베이커낭종 적출술', '수술해설': '무릎 뒤쪽...', '1-3종': '', '1-5종': '2', '신1-5종': '2'}
```

---

## 6. 수술종수 숫자 보정 규칙 (v47)

- 트리거: 수술종수 그룹 컬럼(3개) 중 하나라도 blank/invalid이고, 해당 행에 수술명/수술해설 텍스트가 있을 것
- 허용 값: `"1"`, `"2"`, `"3"`, `""` (진짜 공란)
- `[그림]` 셀 또는 텍스트 없는 빈 행은 blank 유지
- Vision LLM 응답 실패 시 1회 retry → 이후에도 실패하면 원본 유지 (graceful degradation)

p068 검증 결과: 수정 21건, unresolved 0건

---

## 7. 실행 검증 결과

| 항목 | 결과 |
|---|---|
| 실무가이드 60–70페이지 True Hybrid | 11/11 SUCCESS (약 166초) |
| p064 Vision 그림 정제 | `[그림]` 마킹 확인, `vision_cleaned=True` |
| p068 숫자 정제 | 21건 수정, `numeric_refined=True` |
| 전체 단위 테스트 | 201 passed, 0 failed |

---

## 8. 전체 문서 확장 계획 (다음 단계)

현재 로컬 검증이 완료된 상태. 전체 문서 적용 전 아래 항목 확인 필요.

1. **CLOVA API 비용 계획**: 130+ 페이지 일괄 처리 시 API 호출 횟수·비용 산정
2. **Vision LLM 비용 계획**: `--vision-clean` 적용 시 표 페이지당 2회 API 호출 (그림 정제 + 숫자 정제)
3. **처리 시간 추정**: 페이지당 약 15–51초 → 전체 130페이지 약 35–110분 예상
4. **병렬화**: `--pages` 범위를 분할 병렬 실행하는 wrapper 스크립트 고려
5. **재실행 보호**: 이미 성공한 페이지는 skip하는 로직이 기존에 구현되어 있음 (`--force` 없으면 skip)
6. **인덱스 재빌드**: 전체 완료 후 `scripts/ingest.py --include-ocr --stage all` 실행 필요
