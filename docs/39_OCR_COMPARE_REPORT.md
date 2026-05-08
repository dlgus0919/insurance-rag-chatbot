# OCR 비교 파이프라인 최종 통합 보고서

## 1) 구현 범위
- 명세: `docs/39_CODEX_SPEC_OCR_COMPARE_FINAL.md`
- 반영 파일:
  - `src/parser/ocr_preprocessor.py` (신규)
  - `src/parser/hybrid_ocr.py` (신규)
  - `src/parser/clova_ocr.py` (수정: timeout/retry + bbox 재구성 + layout_regions)
  - `scripts/ocr_compare.py` (수정: hybrid/clova/all + per-page JSON + summary.json)
  - `tests/test_ocr_preprocessor.py` (신규)
  - `tests/test_hybrid_ocr.py` (신규)
  - `tests/test_clova_ocr.py` (확장)

## 2) `pytest -q` 결과
```bash
177 passed, 5 warnings in 1.61s
```

## 3) `summary.json` 원문 인용
파일: `reports/ocr_compare/실무가이드/summary.json`

```json
{
  "run_at": "2026-05-08T14:28:16",
  "doc_short": "실무가이드",
  "pages": [
    60,
    61,
    62,
    63,
    64,
    65,
    66,
    67,
    68,
    69,
    70
  ],
  "engines": {
    "hybrid": {
      "avg_elapsed_sec": 40.626,
      "avg_korean_ratio": 0.626,
      "avg_noise_ratio": 0.011,
      "table_blocks": 10,
      "header_score_avg": 0.182,
      "grade": {
        "PASS": 10,
        "MARGINAL": 0,
        "FAIL": 17
      },
      "skipped_pages": [],
      "status": "SUCCESS"
    },
    "clova": {
      "avg_elapsed_sec": null,
      "avg_korean_ratio": null,
      "avg_noise_ratio": null,
      "table_blocks": 0,
      "header_score_avg": null,
      "grade": {
        "PASS": 0,
        "MARGINAL": 0,
        "FAIL": 0
      },
      "skipped_pages": [
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70
      ],
      "status": "SKIPPED"
    }
  }
}
```

## 4) p066 표 헤더 비교

| 엔진 | 인식된 헤더 | 키워드 점수 |
|---|---|---|
| Hybrid | `["수술종수", "col_2", "col_3", "col_4", "col_5"]` | `1/5` (0.20) |
| CLOVA | SKIPPED (API DNS 해석 실패) | `0/5` (실측 불가) |

핵심 검증 포인트(`'舍' -> '수술종수'`)는 Hybrid 결과에서 유지 확인됨.

## 5) figure 마스킹 영향 (p066)
- p066 감지 figure 개수: `0`
- 저장된 figure PNG 경로: `없음`

참고: figure PNG는 다른 페이지에서 생성됨  
예: `reports/ocr_compare/실무가이드/p063_figures/p063_fig00.png`

## 6) 처리 속도 비교
- Hybrid: `40.626초/페이지` (11p 평균)
- CLOVA: 전 페이지 SKIPPED (DNS 실패로 평균 계산 불가)

## 7) 권장 엔진 결론
- 현재 실행 환경 기준 권장: **Hybrid**
- 이유:
  1. 네트워크/DNS 제약 없이 로컬에서 완주
  2. p066 헤더 핵심 포인트(`수술종수`) 복원 확인
  3. 구조화 JSON/이미지 산출물을 안정적으로 생성

## 8) 파일 체크리스트 확인
요구 경로 `reports/ocr_compare/실무가이드/` 기준:

- `p060_original.png ~ p070_original.png`: ✅ 11개
- `p060_hybrid.json ~ p070_hybrid.json`: ✅ 11개
- `p060_clova.json ~ p070_clova.json`: ✅ 11개
- `summary.json`: ✅ 1개

## 9) 구현 시 판단 사항
- 명세 교정사항(교정 1~3)을 우선 적용:
  - `run_easyocr_fallback` 함수명 정정
  - Hybrid table은 `_extract_table_twopass` 재사용
  - `table_json.rows`를 dict 리스트 형식으로 통일
- CLOVA는 페이지 단위 SKIPPED를 기록하고 전체 실행을 중단하지 않도록 처리.

## 10) Git 반영 상태
- 커밋: `9cb78f0`
- 브랜치: `master`
- 원격 반영: `origin/master` 푸시 완료
