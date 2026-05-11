# Native Table 검증 및 OCR 재실행 보고서 (v44)

## 1) Phase 1: 엔드포인트 검증

실행 명령:
```bash
python scripts/verify_native_table.py
```

결과:
```text
[RESULT] tables_found=True count=1
[SAMPLE] 116cells / bbox=[{"x": 225.0, "y": 588.0}, {"x": 2095.0, "y": 572.0}, {"x": 2116.0, "y": 3050.0}, {"x": 246.0, "y": 3063.0}]
```

판정: `exit code 0`, CLOVA native `tables[]` 반환 확인.

## 2) Phase 2: OCR 재실행

CLOVA:
```bash
python scripts/run_clova_local.py --doc 실무가이드 --pages 60-70
```

결과 요약:
```text
SUCCESS: 11/11 | SKIPPED: 0/11 | 총 소요: 110.1초
```

True Hybrid:
```bash
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 60-70
```

결과 요약:
```text
SUCCESS: 11/11 | SKIPPED: 0/11 | 총 소요: 165.9초
```

## 3) Native Table 검증

실행 명령:
```bash
python -c "import json; d=json.load(open('reports/ocr_compare/실무가이드/p066_true_hybrid.json')); print(sum(1 for b in d['blocks'] if b.get('raw',{}).get('native_table')))"
```

결과:
```text
1
```

`p066_true_hybrid.json`의 table block 헤더:
```text
['수술명', '수술해설', '수술종수', '수술종수_2', '수술종수_3']
```

## 4) Phase 3: HTML 뷰어 생성

실행 명령:
```bash
python scripts/generate_ocr_html.py --doc 실무가이드
```

결과:
```text
[generate_ocr_html] wrote /Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/reports/ocr_compare_v43_review.html (166169 bytes)
```

파일 확인:
```text
-rw-r--r--@ 1 june_kim  staff   162K May 11 10:03 reports/ocr_compare_v43_review.html
```

HTML 내 `CLOVA 네이티브` 및 `기하학적 재구성` 배지 포함 확인.

## 5) 추가 보정

`clova_ocr_page()`가 native table block에 `raw={"native_table": True}`를 반환하지만, `scripts/run_clova_local.py`의 `_serialize_blocks()`가 기존에는 `raw`를 JSON에 보존하지 않았다.

명세 44의 성공 기준인 `p066_true_hybrid.json`의 `raw.native_table` 카운트를 만족하기 위해 `_serialize_blocks()`에 `raw` 필드 보존을 추가했다.

## 6) 테스트

관련 테스트:
```text
pytest tests/test_run_clova_local.py tests/test_run_true_hybrid_local.py tests/test_clova_ocr.py -q
22 passed in 0.13s
```

전체 테스트:
```text
pytest -q
188 passed, 5 warnings in 2.12s
```

## 7) Git 반영 상태

- 신규 스크립트 커밋: `d2aec6d`
- raw 메타데이터 보존 및 본 보고서 커밋: 푸시 완료
- JSON 결과 파일과 HTML 결과 파일은 명세대로 커밋 제외
