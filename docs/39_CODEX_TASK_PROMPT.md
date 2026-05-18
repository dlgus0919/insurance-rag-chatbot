# Codex 개발자 프롬프트 — OCR 비교 파이프라인 최종 통합 구현

## 역할

당신은 이 프로젝트의 개발자입니다. 기획·검토 에이전트가 작성한 명세를 구현하고, 구현 결과와 실행 결과를 보고서로 작성합니다.

---

## 배경 및 컨텍스트

보험 문서 RAG 챗봇 프로젝트에서 스캔 PDF 두 종류의 OCR 전처리를 구현 중입니다.

- **D6**: `Claim 실무종합가이드.pdf` (330p, 각 페이지 = 단일 JPEG 2360×3316px, 표·해부학 도식·한자 병기 포함)
- **D7**: `소비자 상담 주요 사례집.pdf` (351p, 주로 텍스트)

지금까지의 진행 상황:
- `scripts/ocr_verify.py`: EasyOCR/Tesseract 품질 검증 완료 (`docs/33_OCR_VERIFY_REPORT.md`)
- `scripts/ocr_extract.py`: PP-Structure 기반 1차 파이프라인 완료 — 그러나 PP-Structure `lang='korean'` 미지원으로 표 텍스트 오인식 확인 (`docs/35_OCR_PIPELINE_REPORT.md`)
- `src/parser/ocr_engine.py`: Two-Pass OCR (PP-Structure bbox + PaddleOCR Korean) 구현 완료 (`docs/36_OCR_V2_REPORT.md`)
- `src/parser/clova_ocr.py`: CLOVA OCR API 클라이언트 구현 완료 — 단, General 플랜은 `tables` 필드를 반환하지 않음을 확인, field bounding box 기반 재구성이 필요함

**이번 태스크**: 두 OCR 엔진(Hybrid vs CLOVA)을 공통 전처리 위에서 비교 실행하고, 기획자가 HTML 결과지를 생성할 수 있도록 구조화된 결과물을 저장한다.

---

## 구현 명세

`docs/39_CODEX_SPEC_OCR_COMPARE_FINAL.md` 를 정독하고 아래 순서로 구현하라.

### 구현 순서

1. **`src/parser/ocr_preprocessor.py` 신규 작성** (명세 섹션 2)
   - `preprocess_page()`: PP-Structure 레이아웃 탐지 + figure 마스킹 + figure PNG 저장
   - `FIGURE_SHRINK_PX = 8` 로 마스킹 영역을 축소하여 인접 텍스트 보호

2. **`src/parser/hybrid_ocr.py` 신규 작성** (명세 섹션 3)
   - `PreprocessResult`를 인수로 받아 마스킹된 이미지에서 Hybrid OCR 수행
   - 표 영역: PP-Structure 셀 bbox + PaddleOCR Korean
   - 텍스트 영역: 전체 region crop + PaddleOCR Korean

3. **`src/parser/clova_ocr.py` 수정** (명세 섹션 4)
   - `_REQUEST_TIMEOUT_SEC = 60`, `_MAX_RETRIES = 1` 적용
   - bbox 재구성 함수 5종 추가: `_group_fields_into_rows`, `_detect_column_x_ranges`, `_assign_fields_to_columns`, `reconstruct_table_from_fields`, 헬퍼 함수
   - `clova_ocr_page(layout_regions=...)` 인수 추가

4. **`scripts/ocr_compare.py` 수정** (명세 섹션 5)
   - `hybrid` / `clova` 엔진 처리
   - 공통 전처리(`preprocess_page`) 실행 → 이미지 저장 → 엔진별 JSON 저장
   - `summary.json` 생성
   - `--timeout` CLI 인수 추가

5. **단위 테스트 작성** (명세 섹션 6)
   - `tests/test_ocr_preprocessor.py` 신규
   - `tests/test_hybrid_ocr.py` 신규
   - `tests/test_clova_ocr.py` 추가 테스트 (bbox 재구성)

6. **검증 실행** (명세 섹션 7)
   - `pytest -q`
   - `python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines all --output-dir reports/ocr_compare/`

---

## 보고서 작성 요구사항

구현 완료 후 `docs/39_OCR_COMPARE_REPORT.md`를 작성한다.

**필수 포함 항목:**

1. `pytest -q` 결과 (전체 통과 수)

2. `reports/ocr_compare/실무가이드/summary.json` 전체 내용 인용

3. p066 표 헤더 비교표:

   | 엔진 | 인식된 헤더 | 키워드 점수 |
   |------|-----------|-----------|
   | Hybrid | (실제 출력) | (점수/5) |
   | CLOVA | (실제 출력) | (점수/5) |

4. figure 마스킹 영향 — p066에서 감지된 figure 개수, 저장된 PNG 경로

5. 처리 속도 (페이지당 평균 초, 엔진별)

6. 권장 엔진 결론 및 이유

**저장 파일 체크리스트 확인:**  
보고서 마지막에 아래 파일이 모두 생성됐는지 명시한다.

```
reports/ocr_compare/실무가이드/
  p060_original.png ~ p070_original.png  (11개)
  p060_hybrid.json ~ p070_hybrid.json    (11개)
  p060_clova.json ~ p070_clova.json      (11개)
  summary.json                            (1개)
```

---

## 주의사항

- `.env` 파일의 `CLOVA_OCR_URL`, `CLOVA_OCR_SECRET` 환경변수가 설정된 상태에서 실행한다
- `data/extracted/` 및 `reports/` 산출물은 `.gitignore` 정책 확인 후 커밋하지 않는다
- **HTML 결과지는 Codex가 생성하지 않는다.** 기획·검토 에이전트(Claude)가 JSON + PNG를 읽어 별도로 생성한다
- figure PNG는 저장만 하고 캡션/분석은 이번 범위에서 제외한다
- CLOVA API 타임아웃 발생 시 해당 페이지를 건너뛰고 summary에 SKIPPED로 기록한다 (전체 실행 중단 없음)
- 구현 중 명세에 불명확한 부분이 있으면 기존 코드 패턴을 따르되, 판단 내용을 보고서에 명시한다
