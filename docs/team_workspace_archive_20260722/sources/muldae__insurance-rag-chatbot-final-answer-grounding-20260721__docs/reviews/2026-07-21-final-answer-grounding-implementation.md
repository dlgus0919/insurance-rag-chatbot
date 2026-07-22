# 최종 말풍선 근거·판단 경계 보강 구현 보고서

- 작업일: 2026-07-21
- 후보 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-final-answer-grounding-20260721`
- 후보 브랜치: `codex/final-answer-grounding-20260721`
- 기준 커밋: `3353fead2492b4ab9f64fbc45bb45445ebf2f6e7`
- 변경 상태: 후보 작업공간에만 적용됨. stage/commit/push/deploy/restart/reindex는 수행하지 않음.

## 확인한 결함 범위

이번 UAT의 핵심 실패는 같은 질문을 반복해도 재현된 직접 속성 질의의 원문 행·`chunk`·`source` 노출과, 보상 판단 질의가 승인된 직접 근거 없이 일반 검색/그래프 검토 문구를 따라 답하는 경로였다. 전자는 결정적 렌더러가 LLM을 거치지 않고 원문 행을 그대로 반환했기 때문에 로컬 LLM 품질만으로 설명되지 않는다. 후자는 프롬프트에 실무자용 그래프 검토 템플릿을 함께 넣고, 숫자·기간 속성과 보상 판단을 같은 결정적 경로로 취급한 파이프라인 경계 문제였다.

반복 질의의 문장 차이는 LLM 생성 구간에서 생길 수 있지만, 위 두 실패의 공통 원인은 모델 응답을 만들기 전에 적용되는 검색 의도·근거 권한·표시 렌더링 경로에 있다.

## 구현 내용

1. `AnswerDisposition`으로 최종 답변의 출처와 근거 상태를 분리했다.
   - 약관 속성 조회, 문서 비교, 승인된 보상 판단, 근거 부족 보상 판단, 조항 세부 조회, LLM 생성으로 답변 출처를 구분한다.
   - 보상/지급 판단은 승인된 직접 근거 프로필이 없으면 LLM으로 넘기지 않고 `coverage_insufficient` 안내로 종료한다.
   - 보상한도·횟수·기간 같은 속성 조회는 선택 세대와 직접 근거가 있을 때만 공개형 결정적 답변으로 반환한다.

2. 조항 세부 답변을 공개형으로 렌더링했다.
   - 사용자 답변에는 문서명·페이지와 필요한 수치/조건만 보이고 `chunk=`, `source=`, 행 ID, 원문 테이블 구조는 보이지 않는다.
   - 구조화된 행을 찾지 못한 경우에도 최대 두 개의 짧은 조항 요지와 문서·페이지 근거만 표시한다.
   - 파이프라인 직접 호출과 API 최종 표시 양쪽에서 내부 provenance 및 그래프 review 마커를 제거한다.

3. GraphDB 컨텍스트를 목적별로 분리했다.
   - 기존 `build_graph_context`는 실무자 화면용 검토 템플릿으로 그대로 둔다.
   - LLM 프롬프트에는 확인된 근거 사실과 안전한 추가 확인 질문만 전달하는 `build_prompt_graph_context`를 사용한다.
   - 누락·후보·검토 경로는 프롬프트의 사실 근거로 전달하지 않는다.

4. 검색 의도 분류를 보정했다.
   - `입원`, `통원`, `실손`, `특약` 같은 맥락 단어만으로 보상 판단으로 분류하지 않는다.
   - 실제 보상/지급/청구 가능성 판단 표현이 있을 때에만 보상 판단 안전 경로를 적용한다.
   - 따라서 `입원치료 자기부담금 비율`처럼 단순 속성을 묻는 질의는 불필요하게 보류되지 않는다.

5. 감사 로그에 최종 답변 권한 정보를 남긴다.
   - `answer_origin`, `grounding_state`, `grounded_source_count`를 `CHAT_QUERY` 감사 이벤트에 추가한다.
   - 내부 프롬프트나 모델 사고 과정은 기록하지 않는다.

6. 독립 리뷰의 P0 보완을 적용했다.
   - 비교 질의는 질문에 명시된 비교축을 먼저 추출하고, 각 축마다 직접 provenance가 있는 선택 근거가 모두 있어야만 `policy_comparison/direct`로 답한다.
   - 한쪽 근거만 있거나 비교축을 명시적으로 식별할 수 없으면 금액을 한쪽만 제시하지 않고, 공개형 비교 근거 부족 안내와 `policy_comparison/insufficient` 감사 상태로 종료한다.
   - formal·quickcode 및 일반 모드에서 자동으로 formal·quickcode로 라우팅된 경우에도, 검색 뒤 보상·지급 판단이면 동일한 승인 근거 평가를 수행한다.
   - 승인된 직접 근거가 없으면 LLM을 호출하지 않는다. 수가코드·단순 속성 같은 비보상 질의는 기존 LLM 보조 경로와 기존 출처 payload를 유지한다.

## 회귀 검증

다음 집중 테스트를 후보 작업공간에서 공유 가상환경으로 실행했다.

```bash
/srv/shared/projects/insurance-rag-chatbot/.venv/bin/pytest \
  tests/test_search_intent.py \
  tests/test_pipeline.py \
  tests/test_graph_context.py \
  tests/test_api_rag_service_payload.py \
  tests/test_api_chat_stream.py -q
```

결과: `177 passed, 1 warning in 1.96s`

경고는 공유 환경 `passlib`의 Python 3.13 예정 `crypt` deprecation 경고 1건이며, 이번 변경과 무관하다.

전체 회귀도 실행했다.

```bash
/srv/shared/projects/insurance-rag-chatbot/.venv/bin/pytest -q
```

결과: `1184 passed, 3 warnings in 14.77s`

추가 두 경고는 OCR 전처리 테스트에서 사용하는 Pillow `Image.getdata` deprecation 경고다. 전체 테스트의 최초 1회 실패는 내부 `source=... row_id=...` 표시를 기대하던 기존 테스트 1건이었으며, 실제 공개형 렌더링 계약에 맞춰 해당 테스트의 기대값을 문서명·페이지 근거와 내부 식별자 비노출로 갱신한 뒤 전체 회귀가 통과했다.

추가 회귀 항목은 다음을 포함한다.

- 같은 숫자 근거가 있어도 보상 판단에는 직접 승인 근거가 없으면 금액을 단정하지 않는지
- 입원/통원 맥락이 있는 자기부담금 비율 속성 질의가 보상 판단 보류로 오분류되지 않는지
- 프롬프트에서 GraphDB의 누락/검토 템플릿을 제외하는지
- 채팅 스트림이 `coverage_insufficient`에서 LLM을 호출하지 않는지
- 최종 표시에 내부 provenance가 남지 않는지

독립 리뷰 P0 보완 후에는 다음을 추가로 실행했다.

```bash
PYTHONPATH=. /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest -q \
  tests/test_pipeline.py \
  tests/test_api_rag_service_payload.py \
  tests/test_api_chat_stream.py
```

결과: `166 passed, 1 warning in 2.17s`

추가한 회귀 항목은 다음과 같다.

- 일반화한 비교축에서 한쪽 직접 근거만 있을 때 금액을 포함하지 않는 비교 보류가 되는지
- 모든 비교축에 직접 근거가 있을 때만 비교 답변과 해당 source chunk ID가 기록되는지
- explicit formal/quickcode 및 일반 모드의 자동 formal/quickcode에서 근거 부족 보상 판단이 LLM 없이 종료되는지
- 승인된 직접 보상 판단은 결정적 답변으로 유지되는지
- 비보상 수가코드 질의는 LLM 보조 답변과 기존 source payload를 계속 사용하는지

최종 전체 회귀는 다음과 같이 재실행했다.

```bash
PYTHONPATH=. /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest -q
```

결과: `1195 passed, 3 warnings in 15.12s`

## P0 의도 계약 Fixback (03:25 triage 반영)

### 근본 원인과 최소 수정

`classify_search_intent()`는 원시 `requires_coverage`를 계산하고도
`clause_or_appendix_lookup`, `cross_doc_compare`, `procedure_code_lookup`의
반환 `SearchIntentPlan`에 전달하지 않았다. 이 때문에 자연어의 조항/수가/비교
복합 질의는 실제 자동 라우팅 뒤 `requires_coverage_judgment=False`로 바뀌었고,
formal·quickcode 공통 보상 근거 gate 또는 일반 비교 fail-closed 경로를 우회할 수
있었다.

세 반환 분기에 이미 계산된 `requires_coverage`를
`requires_coverage_judgment`로 보존하는 세 줄만 추가했다. 특정 의료행위, 세대,
MRI 또는 문구 예외는 추가하지 않았다.

### 자동 라우팅 회귀

라우트를 강제하지 않은 실제 `resolve_query_route()` 및 `chat_stream()` 회귀를
추가했다.

- 수가 코드 + 실손 보상 여부 질의는 자동 quickcode에서 승인 직접 근거가 없으면
  LLM을 호출하지 않고 `coverage_insufficient`로 끝나며, public source는 유지하고
  감사 로그의 `grounded_source_count`는 0이다.
- 제3조/면책조항 + 보상 가능 여부 질의는 자동 formal에서 같은 경계를 지킨다.
- 두 축의 직접 속성 근거가 모두 있는 비교 + 보상 가능 여부 질의도 승인된 직접
  보장·면책 근거가 없으면 수치 비교를 최종 말풍선에 공개하지 않고
  `coverage_insufficient`로 끝난다.
- 순수 수가코드, 수술종수, 조항 설명은 기존 비보상 의도와 자동 라우팅을 유지한다.

수정 전 RED 실행에서는 위 세 복합 질의의 intent flag가 모두 false였고, 코드/조항
경로는 LLM 1회 호출, 비교 경로는 `123만원`/`456만원`을 포함한 답변으로 실패했다.
수정 후 같은 focused 회귀는 `9 passed, 1 warning in 0.61s`로 통과했다.

### Fixback 최종 검증

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest -q \
  -p no:cacheprovider \
  tests/test_search_intent.py tests/test_pipeline.py tests/test_graph_context.py \
  tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py \
  tests/test_clause_detail_rows.py tests/test_api_source_pdf.py
```

결과: `203 passed, 1 warning in 2.59s`

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -c \
  "from src.rag.search_intent import classify_search_intent; from src.api.rag_service import resolve_specialized_coverage_disposition; print('import OK')"
node --test tests/test_frontend_source_preview_settings.mjs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest -q -p no:cacheprovider
```

결과: `git diff --check` 통과, import `OK`, 출처 hover/PDF 페이지 열기 계약 Node
`8/8` 통과, 전체 Python 회귀 `1204 passed, 3 warnings in 15.54s`.
경고는 기존 `passlib`의 `crypt` deprecation 1건과 OCR 전처리 테스트의 Pillow
`Image.getdata` deprecation 2건이며 이번 수정과 무관하다. Node는 기존
`frontend/package.json`의 module type 미지정 경고만 출력했고, 프런트엔드 파일은
변경하지 않았다.

## 의도적으로 변경하지 않은 범위

- 액티브 보험금 계산 규칙과 승인 매니페스트
- GraphDB·온톨로지 데이터 및 재빌드
- 원본 PDF/OCR/사용자 계정·대화 데이터
- 출처 배지의 hover/click 및 원본 PDF 열기 기능
- 운영 서버 기동, 배포, 인덱싱, 재시작

## 남은 검증과 위험

후보 코드의 독립 리뷰 후에만 메인 반영을 판단한다. 반영 뒤에는 격리된 UAT 또는 Chrome에서 다음을 실제 데이터로 확인해야 한다.

- 4/5세대 MRI/MRA 연간 한도 속성 질의의 간결한 최종 말풍선과 원본 페이지 열기
- 승인되지 않은 보상 가능 여부 질의의 근거 부족 안내 및 LLM 미호출
- 단순 조항/자기부담금 속성 질의가 계속 정상 응답하는지

이번 변경은 근거 부족 상황에서 답변 범위를 보수적으로 줄인다. 따라서 기존에 일반 검색 결과로 단정하던 보상 판단 일부는 `확정할 수 없음`으로 바뀌며, 이는 승인 근거가 추가되기 전의 의도된 안전 동작이다.

비교축이 질문에 구체적으로 적히지 않은 비교 요청도 같은 이유로 보류된다. 이는 특정 4·5세대나 특정 의료 항목에만 맞춘 예외가 아니라, 어떤 비교 항목에도 동일하게 적용되는 근거 완결성 규칙이다.
