# RAG Grounding Logic Implementation Report

## 목적

LLM 서버 호출 없이 RAG 검색/근거 조립 로직을 개선해, 단일 문서 질의와 다문서 비교 질의에서 근거 누락과 문서별 값 통일 오류 가능성을 낮췄다.

## 변경 내용

- `RagPipeline.build_prompt()`를 추가해 일반 `answer()` 경로와 Streamlit 스트리밍 경로가 같은 구조화 근거 조립 로직을 사용하게 했다.
- 문서별 비교 질의에서 요청 문서가 최종 검색 후보에서 누락되지 않도록 문서 커버리지 보강 로직을 추가했다.
- 질문/문서 필터에서 요청 문서 축약명을 추론하는 helper를 추가하고, `자사_SOL건강`처럼 공백 포함 별칭도 인식하도록 했다.
- 퀵 코드 검색과 약관 정형 검색에도 strict evidence context 및 evidence warning을 적용해 일반 RAG와 guardrail을 맞췄다.
- 코드 evidence 추출 시 행 주변 window를 보존해 검증 경고의 근거 텍스트가 더 설명적으로 남도록 했다.
- 관련 단위 테스트를 추가해 문서 추론, 문서 커버리지 helper, hit 병합 동작을 고정했다.

## 수정 파일

- `src/rag/pipeline.py`
- `src/rag/evidence.py`
- `src/rag/quick_code.py`
- `src/rag/insurance_form.py`
- `src/ui/streamlit_app.py`
- `tests/test_pipeline.py`
- `docs/86_RAG_GROUNDING_LOGIC_IMPL_REPORT.md`

## 검증

```bash
source .venv/bin/activate
python -m py_compile src/rag/pipeline.py src/rag/evidence.py src/rag/quick_code.py src/rag/insurance_form.py src/ui/streamlit_app.py
pytest tests/test_pipeline.py tests/test_evidence.py tests/test_quick_code.py tests/test_insurance_form.py -q
pytest -q
```

결과:

- targeted tests: `49 passed`
- full tests: `276 passed, 3 warnings`

## 미수행 및 남은 과제

- LLM 서버 호출, Streamlit 실기동, 대형 모델 품질 평가는 수행하지 않았다.
- 심평원 수가표의 row-level 직접 색인은 아직 별도 작업으로 남아 있다. `식도조루술`, `요실금수술 접근법별 코드`처럼 특정 표 행이 핵심인 질의는 후속으로 표 행 단위 parquet/sqlite 색인을 추가해야 안정성이 더 올라간다.
- 대형 모델 평가 스크립트는 추후 SGLang/vLLM provider 공용 실행 옵션으로 일반화하는 것이 좋다.
