# 58 LLM A+B 구현 보고서

작성일: 2026-05-13

## 1) 수정 파일 및 함수

- `src/llm/prompt.py`
  - `SYSTEM_PROMPT`에 핵심 규칙 7 추가 (OCR 파이프 표 해석 규칙)
  - 예시 2건 추가 (수술종수/장해 지급률)
- `src/rag/pipeline.py`
  - `_extract_disability_region_from_query(question)` 추가
  - `_build_structured_context(question, chunks, table_store=None)` 추가
  - `answer()`에서 구조화 컨텍스트 선주입 로직 추가
  - 내부 변수명 `answer` → `answer_text`로 변경
- `tests/test_pipeline.py`
  - 장해 추출/구조화 컨텍스트 관련 테스트 6건 추가

## 2) 테스트 결과

### 신규 테스트 필터

```text
pytest tests/test_pipeline.py -v -k "disability or structured_context"
6 passed, 22 deselected
```

### 전체 회귀

```text
pytest -q
235 passed, 5 warnings in 2.59s
```

## 3) OCR eval 결과 (`--ocr`)

실행 로그: [eval_ocr_ab_20260513_104434.log](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/logs/eval_ocr_ab_20260513_104434.log)

```text
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:11434 python scripts/eval.py --ocr

Ollama 서버에 연결할 수 없어 --ocr LLM 답변 평가는 skip하고 retrieval-only로 진행합니다.
[01] surgery_grade recall=OK top_pages=['64', '67', '5'] llm=SKIP
[02] surgery_grade recall=OK top_pages=['64', '84', '67'] llm=SKIP
[03] surgery_grade recall=OK top_pages=['64', '197', '196'] llm=SKIP
[04] surgery_grade recall=OK top_pages=['107', '26', '173'] llm=SKIP
[05] surgery_grade recall=OK top_pages=['107', '26', '12'] llm=SKIP
[06] surgery_grade recall=OK top_pages=['167', '178', '192'] llm=SKIP
[07] surgery_grade recall=OK top_pages=['167', '178', '110'] llm=SKIP
[08] surgery_grade recall=OK top_pages=['167', '178', '201'] llm=SKIP
[09] surgery_grade recall=OK top_pages=['109', '28', '107'] llm=SKIP
[10] surgery_grade recall=OK top_pages=['108', '28', '10'] llm=SKIP
[11] surgery_grade recall=OK top_pages=['64', '188', '63'] llm=SKIP
[12] surgery_grade recall=OK top_pages=['26', '7', '10'] llm=SKIP
[13] surgery_description recall=OK top_pages=['64', '57', '52'] llm=SKIP
[14] surgery_description recall=OK top_pages=['64', '197', '188'] llm=SKIP
[15] surgery_description recall=OK top_pages=['107', '22', '108'] llm=SKIP
[16] surgery_description recall=OK top_pages=['167', '178', '192'] llm=SKIP
[17] disability_rate recall=OK top_pages=['236', '242', '236'] llm=SKIP
[18] disability_rate recall=OK top_pages=['236', '236', '255'] llm=SKIP
[19] disability_rate recall=OK top_pages=['242', '207', '227'] llm=SKIP
[20] disability_rate recall=OK top_pages=['242', '227', '216'] llm=SKIP
[21] disability_rate recall=OK top_pages=['245', '255', '229'] llm=SKIP
[22] disability_rate recall=OK top_pages=['251', '229', '256'] llm=SKIP
[23] disability_rate recall=OK top_pages=['229', '251', '218'] llm=SKIP
[24] disability_rate recall=OK top_pages=['255', '222', '224'] llm=SKIP
[25] disability_rate recall=OK top_pages=['255', '222', '224'] llm=SKIP
[26] disability_rate recall=OK top_pages=['255', '228', '257'] llm=SKIP
[27] disability_rate recall=OK top_pages=['257', '222', '228'] llm=SKIP
[28] disability_rate recall=OK top_pages=['264', '226', '228'] llm=SKIP
[29] disability_rate recall=OK top_pages=['264', '226', '228'] llm=SKIP
[30] disability_rate recall=OK top_pages=['247', '247', '209'] llm=SKIP
[31] disability_criteria recall=OK top_pages=['232', '225', '270'] llm=SKIP
[32] disability_criteria recall=OK top_pages=['257', '255', '267'] llm=SKIP
[33] disability_criteria recall=OK top_pages=['224', '255', '211'] llm=SKIP
[34] disability_criteria recall=OK top_pages=['262', '262', '258'] llm=SKIP
[35] consultation recall=OK top_pages=['59', '118', '55'] llm=SKIP
[36] consultation recall=OK top_pages=['187', '189', '29'] llm=SKIP
[37] consultation recall=OK top_pages=['100', '101', '268'] llm=SKIP
[38] consultation recall=OK top_pages=['270', '275', '271'] llm=SKIP
[39] cross_doc recall=OK top_pages=['107', '26', '108'] llm=SKIP
[40] cross_doc recall=OK top_pages=['222', '224', '255'] llm=SKIP
retrieval recall@8: 1.000
출처 페이지 정확도: N/A (LLM skip)
수술종수 정확도 (grade_accuracy): N/A
장해 지급률 정확도 (rate_accuracy): N/A
키워드 포함율 (keyword_coverage): N/A
```

## 4) Smoke eval 결과 (`eval.py`, `eval.py --v2`)

실행 로그:
- [eval_smoke_ab_20260513_104454.log](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/logs/eval_smoke_ab_20260513_104454.log)
- [eval_smoke_v2_ab_20260513_104501.log](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/logs/eval_smoke_v2_ab_20260513_104501.log)

```text
python scripts/eval.py
Ollama 서버에 연결할 수 없습니다. Ollama 데스크톱 앱 또는 `ollama serve`를 실행하세요.

python scripts/eval.py --v2
Ollama 서버에 연결할 수 없습니다. Ollama 데스크톱 앱 또는 `ollama serve`를 실행하세요.
```

## 5) 구조화 컨텍스트 실제 주입 샘플 2건

`answer()` 실행 시 프롬프트 앞에 삽입된 블록:

```text
[구조화 데이터 — 검색 결과 기반]
수술명: 충수절제술(맹장 수술) | 1-3종: 1 | 1-5종: 2 | 신1-5종: 2
출처: 실무가이드 p.109
```

```text
[구조화 데이터 — 검색 결과 기반]
장해 분류: 1) 한 팔의 손목 이상을 잃었을 때
지급률: 60%
출처: 실무가이드 p.255
```

## 6) `_build_structured_context()` 시그니처 (C 예약 파라미터 확인)

```python
def _build_structured_context(
    question: str,
    chunks: list[Chunk],
    table_store=None,
) -> str | None:
```

## 7) 최종 판정 / 잔여 블로커

- 코드/테스트 구현: 완료
- `pytest -q`: 통과
- OCR retrieval recall@8: 1.000 유지
- 잔여 블로커:
  - 현재 환경에서 Ollama LLM 연결 불가로 `grade_accuracy`, `rate_accuracy`, smoke LLM 지표를 산출하지 못함.
