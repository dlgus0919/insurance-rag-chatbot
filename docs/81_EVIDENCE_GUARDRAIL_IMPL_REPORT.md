# Evidence Guardrail Implementation Report

## 목적

문서별 코드·수가·수치 질의에서 LLM이 서로 다른 문서의 값을 하나로 통일하거나, 분류번호와 실제 코드를 혼동하는 오류를 줄이기 위해 strict evidence guardrail을 추가했다.

대표 회귀 사례는 로봇 수술 코드 질의다. 심평원 원문은 `조-961 QZ966 로봇 보조 수술`이고 자사 약관은 `QZ961`인데, 기존 답변은 심평원 코드까지 `QZ961`로 통일했다.

## 구현 내용

- `src/rag/evidence.py` 추가
  - 코드·수가·분류번호·문서별 비교 질의를 strict evidence 대상으로 감지
  - 검색 청크에서 문서, 페이지, 분류번호, 코드, 명칭/행을 구조화 evidence fact로 추출
  - 문서별 값이 다를 때 통일하지 않도록 LLM 입력 앞에 구조화 근거 블록 삽입
  - 답변에 문서-코드 불일치가 감지되면 `[근거 검증 경고]`를 후처리로 추가
- `src/rag/pipeline.py`
  - 일반 `answer()` 경로에 strict evidence context와 답변 검증 후처리 연결
- `src/ui/streamlit_app.py`
  - Streamlit 스트리밍 답변 경로에도 동일 guardrail 적용
- `src/llm/prompt.py`
  - 개별 사례가 아니라 일반 원칙 수준으로만 보강
  - 문서별 값을 통일하지 말 것, 분류번호와 코드를 구분할 것을 명시
- `tests/test_evidence.py`
  - 심평원 `QZ966`과 자사 `QZ961`을 분리 보존하는 회귀 테스트 추가
  - `QZ962`, `QZ965` 같은 인접 무관 행이 로봇 수술 코드로 섞이지 않는지 확인
  - 문서-코드 불일치 경고 동작 확인

## 설계 판단

프롬프트만으로 해결하지 않고, 구조화 evidence layer와 post-generation validation을 함께 적용했다. 이 방식은 특정 로봇 수술 사례뿐 아니라 수가코드, 지급률, 수술종수, 점수처럼 근거 값의 정확성이 중요한 보험 보상 업무 질의 전반에 확장 가능하다.

## 남은 과제

- 문서별 비교 질문에서 검색 자체를 문서별로 분리 실행하는 기능은 아직 추가하지 않았다.
- 현재 검증기는 문서명과 코드가 같은 답변 행에 나타나는 경우를 우선 검증한다.
- 향후 표 행 구조가 더 정제되면 evidence fact를 table store 또는 relational index에서 직접 조회하도록 확장할 수 있다.

## 검증

- `pytest tests/test_evidence.py tests/test_pipeline.py -q`: 36 passed
- `pytest -q`: 268 passed, 3 warnings
- 실제 `data/processed/chunks.jsonl` 로봇 수술 근거 추출 확인:
  - 심평원 p.812: 분류번호 `조-961`, 코드 `QZ966`, 명칭 `로봇 보조 수술`
  - 자사_SOL건강 p.268-269: 코드 `QZ961`, 명칭 `로봇 보조 수술[시술시 소요재료 포함]`
  - 자사_SOL건강 p.300-301: 코드 `QZ961`, 명칭 `로봇 보조 수술[시술시 소요재료 포함]`
- `RERANKER_ENABLED=false OLLAMA_MODEL=exaone3.5:7.8b python scripts/eval.py --ocr`:
  - retrieval recall@8: 1.000
  - 출처 페이지 정확도: 0.950
  - 스크립트 종료 코드는 1이었다. 검색 회귀는 없었으나, 현재 Ollama 생성 모델의 수술종수/장해 지급률 생성 품질 지표가 평가 기준에 미달했다.
