# 232. clause_detail_lookup Source-grounded Patch Report

## 목적

`docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`와 `docs/231_CLAUSE_DETAIL_LOOKUP_SOURCE_GROUNDED_PLAN.md` 기준으로 `clause_detail_lookup` 답변을 보정본 OCR 원문 근거에 더 가깝게 고정했다.

핵심 원칙은 다음과 같다.

- 보험 지식 값 자체를 코드에 하드코딩하지 않는다.
- 숫자, 표 번호, 조항 번호는 검색된 원문 chunk/row에서만 추출한다.
- 프롬프트만 조정하지 않고 deterministic row evidence layer를 우선 적용한다.
- OCR 보정본 인덱스 기준으로 평가한다.

## 변경 내용

### 1. 원문 row evidence 추출

`src/rag/pipeline.py`에 `ClauseDetailEvidenceRow`와 관련 helper를 추가했다.

- 질문에서 `급여`, `비급여`, `입원`, `통원`, `1회`, `자기부담금`, `공제금액` 등 일반 facet을 추출한다.
- 검색 chunk를 OCR/table-like row 후보로 분리한다.
- row 안에 실제 존재하는 수치 표현만 추출한다.
- `<표1>`, `제3조` 등 source label을 원문에서 추출하고 답변 출처에 표시한다.
- `비급여` 안의 `급여` 부분 문자열 충돌을 방지한다.
- `급여(상해·질병)`처럼 row 머리와 본문이 OCR 분리된 경우 prefix를 다음 수치 row에 연결한다.
- 질문에 `1회`가 명시된 경우 row에도 `1회` 기준이 있는 근거를 우선 사용한다.

### 2. deterministic 답변 경로 개선

`_deterministic_clause_detail_answer()`는 기존 line 기반 fallback 전에 source-grounded row evidence 답변을 먼저 생성한다.

답변은 다음 구조를 따른다.

1. 원문 근거 row
2. row에서 직접 추출한 수치
3. 문서/조항/표/page/chunk 출처
4. 표시한 row 기준의 수치 요약

표시하지 않은 후보 row의 숫자는 수치 요약에 포함하지 않도록 정리했다.

### 3. 회귀 테스트

`tests/test_pipeline.py`에 다음 검증을 추가했다.

- 입원 자기부담금/보상비율 질문에서 source row 기반 답변이 `80%`, `20%`, `제3조`, `<표1>`, `chunk`를 포함하는지 확인
- 수치가 없는 자기부담금 row는 evidence row로 쓰지 않는지 확인
- `3대 비급여` 질문에서 잘못 분리된 `급여(3대)` row fragment가 우선 선택되지 않는지 확인

## 검증 결과

### 로컬 단위 테스트

```bash
python -m pytest tests/test_pipeline.py -q
```

결과:

```text
47 passed
```

### DGX 단위 테스트

```bash
ssh dgx-codex 'cd /srv/shared/projects/insurance-rag-chatbot && .venv/bin/python -m pytest tests/test_pipeline.py -q'
```

결과:

```text
47 passed
```

### DGX 보정본 OCR 인덱스 실데이터 스모크

대상:

- `policy_xlsx_018`: 급여(상해·질병) 입원치료 자기부담금/공제 비율
- `policy_xlsx_019`: 급여 통원치료 자기부담금 산정
- `policy_xlsx_026`: 3대 비급여 치료 1회당 공제금액

조건:

- `index_mode=v2_only`
- LLM 서버 미사용
- `DummyLLM`으로 deterministic `clause_detail_lookup` 경로만 검증
- 평가 기준은 `scripts/eval_large_model_rag.py::evaluate_answer`

결과:

```text
policy_xlsx_018: pass
policy_xlsx_019: pass
policy_xlsx_026: pass
```

## Self-inspection

### 요구사항 부합

- 000번 규칙의 하드코딩 지식 금지 원칙을 지켰다.
- 231번 계획의 source-grounded row evidence 방향을 구현했다.
- 보정본 OCR 인덱스 기준 실데이터 스모크를 수행했다.

### 남은 위험

- OCR 표 구조가 완전히 복원된 것은 아니므로, row 머리와 본문 연결은 휴리스틱이다.
- 3대 비급여 질문에서 핵심 수치 요약은 정리되었지만, 보조 근거 row에는 일반 비급여 통원 row가 함께 표시될 수 있다.
- 현재 facet 정책은 코드 상수로 존재한다. 보험 지식 값은 아니지만, 장기적으로는 `data/rag/policies/clause_detail_lookup.json` 같은 외부 정책 파일로 분리하는 편이 더 안전하다.

### 다음 개선 후보

1. OCR table row ownership 복원
   - `<표1>` 아래의 row가 어떤 보장 구분에 속하는지 parent heading을 함께 저장한다.
2. clause detail facet policy 외부화
   - row boundary, facet group, conflict rule을 데이터 정책 파일로 분리한다.
3. 평가셋 확대
   - 현재는 clause detail 대표 3문항 smoke다.
   - 통원, 입원, 3대 비급여, 상급병실료, 보상한도 문항을 별도 suite로 확장한다.

