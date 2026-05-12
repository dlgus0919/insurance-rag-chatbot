# 54 OCR QA 평가셋 구현 보고서

## 변경 요약
- `eval/ocr_qa.jsonl` 신규 생성: OCR 문서 전용 QA 40건.
- `scripts/eval.py` 수정:
  - `--ocr` 플래그 추가.
  - 수술종수/장해 지급률/키워드 평가 helper 추가.
  - OCR 모드 지표 출력 추가: `grade_accuracy`, `rate_accuracy`, `keyword_coverage`.
  - OCR 모드에서 Ollama 연결 불가 시 retrieval-only로 graceful skip.
  - `doc_sources`가 있는 문항은 검색 단계부터 문서 필터 적용.
  - OCR LLM 평가 프롬프트는 2문장 이내 출력 지시와 최대 `num_ctx=4096` 적용.

## 평가 문항 분포
```text
총 40건
surgery_grade: 12
surgery_description: 4
disability_rate: 14
disability_criteria: 4
consultation: 4
cross_doc: 2
```

## 검증 결과
```text
python -c "import json; [json.loads(l) for l in open('eval/ocr_qa.jsonl', encoding='utf-8')]"
=> 통과

wc -l eval/ocr_qa.jsonl
=> 40 eval/ocr_qa.jsonl

pytest -q
=> 225 passed, 5 warnings
```

## OCR 평가 실행 결과
실행 명령:
```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 python scripts/eval.py --ocr
```

요약:
```text
retrieval recall@8: 0.975
출처 페이지 정확도: N/A (LLM skip)
수술종수 정확도 (grade_accuracy): N/A
장해 지급률 정확도 (rate_accuracy): N/A
키워드 포함율 (keyword_coverage): N/A
```

MISS:
```text
[11] surgery_grade recall=MISS top_pages=['188', '63', '25']
문항: 사지골 사지관절 가관절수술의 수술종수는?
기대 페이지: 64
```

원인 분석:
- 실제 정답 행은 `실무가이드_ch_005119` p.64에 존재한다.
- p.63에도 `사지골 사지관절` 계열 표가 있어 BM25/dense 융합에서 더 강하게 잡혔다.
- 현재 일반 RAG 검색은 표 내부 특정 행을 별도 row 단위로 boost하지 않아, 같은 장의 인접 표가 상위권을 선점할 수 있다.

## LLM 평가 상태
- configured 모델 `exaone3.5:7.8b`로 `python scripts/eval.py --ocr` LLM 평가를 시도했다.
- 로컬 Ollama 호출은 가능했지만 첫 OCR QA 답변이 3분 이상 반환되지 않아 전체 40문항 LLM 평가는 중단했다.
- 같은 이유로 `python scripts/eval.py`, `python scripts/eval.py --v2` 회귀 LLM 평가는 완료하지 못했다.
- 따라서 이번 보고서의 정량 결과는 retrieval-only 기준이며, `grade_accuracy`, `rate_accuracy`, `keyword_coverage`는 N/A로 남긴다.

## 개선 권장사항
- OCR 표 검색에는 row-level exact match 또는 table row boost를 추가하는 것이 좋다.
- 특히 수술명 질의는 `수술명` 컬럼 exact/부분 일치를 dense/BM25보다 우선하는 보조 검색기를 두면 p.64 같은 MISS를 줄일 수 있다.
- LLM 평가 자동화를 위해 `OllamaClient`에 `num_predict` 옵션 또는 평가 전용 timeout/`--retrieval-only` 플래그를 추가하는 후속 명세가 필요하다.

## 잔여 블로커
- LLM 전체 평가는 현재 로컬 configured 모델 지연으로 미완료.
- retrieval-only 기준은 통과했지만, 답변 생성 기반 정확도는 별도 실행 환경 또는 더 빠른 평가 모델로 재검증해야 한다.
- Git 커밋 및 GitHub push는 본 보고서 작성 후 수행하며, 최종 응답에서 완료 여부와 커밋 해시를 공유한다.
