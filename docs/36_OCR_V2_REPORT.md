# OCR 엔진 개선 v2 구현 보고서

## 1) 작업 범위
- 명세: `docs/36_CODEX_SPEC_OCR_V2.md`
- 구현 완료 항목:
  - `src/parser/ocr_engine.py`: PP-Structure bbox + PaddleOCR Korean **Two-Pass OCR**
  - `src/parser/clova_ocr.py`: CLOVA OCR API 클라이언트 추가
  - `scripts/ocr_compare.py`: twopass/clova/all 비교 스크립트 추가
  - `tests/test_clova_ocr.py` 신규 + `tests/test_ocr_engine.py` 보강

## 2) 구현 상세

### M-ocr-v2-1 Two-Pass OCR
- `ocr_page()` 추가: PP-Structure(`lang='ch'`)로 레이아웃/표 셀 bbox 탐지 후, 영역별 `PaddleOCR(lang='korean')` 재인식
- `LayoutBlock.source_method`에 `ocr_ppstructure_twopass` 반영
- 표는 셀 bbox 기준으로 JSON/HTML 재구성하여 `table_json`에 저장
- 셀 좌표계/빈 crop 방어 로직 추가(클램프 + zero-size skip)

### M-ocr-v2-2 CLOVA OCR
- 환경변수 기반 클라이언트 구현:
  - `CLOVA_OCR_URL`
  - `CLOVA_OCR_SECRET`
- table/fields 응답을 `LayoutBlock`으로 변환
- 오류 처리:
  - 환경변수 미설정
  - HTTP 오류
  - OCR 실패 응답/JSON 파싱 실패

### M-ocr-v2-3 비교 스크립트
- `scripts/ocr_compare.py` 구현
- 출력:
  - `{engine}_pXXX_blocks.json`
  - `{engine}_pXXX_text.txt`
  - `{engine}_pXXX_tables.txt`
  - `summary.txt`
- 지표:
  - 페이지 평균 처리시간
  - 한글 비율/노이즈 비율/등급
  - 표 블록/셀 수
  - 헤더 키워드 점수(`score_table_header`)

### M-ocr-v2-4 테스트
- `tests/test_clova_ocr.py`: bbox/table 파싱, env 미설정, 성공 응답, HTTP 오류
- `tests/test_ocr_engine.py`: Korean OCR 싱글턴, two-pass `source_method` 확인

## 3) 핵심 검증: D6 p066 표 헤더 before/after

### 헤더 비교 (핵심 포인트)
- before (`data/extracted/실무가이드/tables/p066_t00.json`)
  - `["舍", "col_2", "col_3", "col_4", "col_5"]`
- after (`reports/ocr_compare/실무가이드/twopass_p066_blocks.json`)
  - `["수술종수", "col_2", "col_3", "col_4", "col_5"]`

검증 결과: **`'舍' -> '수술종수'` 치환 확인(성공)**  
(나머지 헤더는 추가 개선 여지 존재)

### 표 셀 텍스트 before/after 예시 (5개 이상)
- `1-3否` -> `1-3종`
- `(Ganglion）(旱)` -> `신경철Ganglion적출술관절부 관절`
- `,否(Osteocystoma)` -> `요골 골렁봉Osteocystohma 적제술 낭`
- `(iizarv人 ()` -> `일리자로브ilizarov` 포함 문장으로 복원
- `舍`(헤더/셀 노이즈) -> `수술명`, `반월판연골 봉합술` 등 의미 텍스트로 복원

### 품질 지표 변화 (p066 table)
- before text 파일: `data/extracted/실무가이드/tables/p066_t00_text.txt`
  - `korean_ratio=0.000`, `noise_ratio=0.207`, `grade=FAIL`
- after text 파일: `reports/ocr_compare/실무가이드/twopass_p066_tables.txt`
  - `korean_ratio=0.604`, `noise_ratio=0.050`, `grade=PASS`

## 4) 비교 실행 결과

실행:
```bash
python scripts/ocr_compare.py --doc 실무가이드 --pages 60-70 --engines twopass
```

요약 (`reports/ocr_compare/summary.txt`):
- pages: 11
- avg_elapsed_sec: 47.393
- avg_korean_ratio: 0.543
- avg_noise_ratio: 0.114
- table_blocks: 10
- table_cells: 536
- header_score_avg: 0.182 (페이지 평균)

추가 계산:
- 기존 추출본(이전) table 헤더 점수 평균: **0.000**
- 개선 twopass table 헤더 점수 평균: **0.280** (table 블록 기준)

## 5) CLOVA OCR 결과

### 구현/테스트 상태
- 코드 구현 및 단위 테스트는 완료
- `clova_ocr_page()` 동작(성공/실패/미설정)은 테스트로 검증됨

### 실데이터 비교 실행 상태
- 본 환경에서 로컬 보험 PDF 페이지를 외부 OCR API로 전송하는 실행은 정책 검토에서 차단됨
- 따라서 D6 60~70p의 CLOVA 실측 지표(헤더 점수/지연시간)는 본 보고서에 포함하지 못함

참고(스킵 동작 확인):
```bash
python scripts/ocr_compare.py --doc 실무가이드 --pages 65-65 --engines all --output-dir reports/ocr_compare_smoke
```
- `reports/ocr_compare_smoke/summary.txt`에서 `clova`가 미설정 시 SKIPPED 처리되는 것 확인

## 6) 엔진 비교 요약표

| 항목 | Two-Pass(이전) | Two-Pass(개선) | CLOVA OCR |
|---|---|---|---|
| 표 헤더 한글 인식 | `舍`/`col_*` 위주 | `수술종수` 복원 확인 | 실데이터 실행 차단 |
| 헤더 키워드 매칭 | 0/5 (p066) | 1/5 (p066 main table) | 실데이터 실행 차단 |
| 한글 비율 (p066 table) | 0.000 | 0.604 | 실데이터 실행 차단 |
| 처리 속도 | 기존 로그 미보존 | 47.393초/페이지(평균, D6 60~70) | 실데이터 실행 차단 |
| 로컬 실행 | ✅ | ✅ | API 연동 필요 |

## 7) pytest 결과

```bash
pytest -q
```

결과:
- `165 passed, 5 warnings in 2.01s`

## 8) 결론 및 다음 단계
- 핵심 검증 포인트인 **`'舍' -> '수술종수'`**는 달성됨
- two-pass로 D6 표 인식 품질이 의미 있게 개선됨(헤더/한글 비율/노이즈)
- 다음 단계:
  1. table header 정규화 룰(다중 헤더행 병합) 추가
  2. CLOVA 실데이터 비교는 정책 허용 범위에서 별도 실행
  3. 개선 결과를 `scripts/ocr_extract.py` 경로에 단계적으로 반영

## 9) Git 반영 상태
- 커밋: `fe2b612`
- 브랜치: `master`
- 원격 반영: `origin/master` 푸시 완료
