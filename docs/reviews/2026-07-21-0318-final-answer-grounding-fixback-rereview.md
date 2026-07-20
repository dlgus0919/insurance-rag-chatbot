# 최종 말풍선 근거 경계 P0 Fixback 재검토

- 검토일: 2026-07-21 03:18 KST
- 후보 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-final-answer-grounding-20260721`
- 후보 기준: `3353fead2492b4ab9f64fbc45bb45445ebf2f6e7`
- 범위: 이전 독립 리뷰의 P0-1(비교 완결성), P0-2(모든 경로의 보상 판단 fail-closed) 수정본만 읽기 전용으로 재검토
- 운영 경계: 코드·테스트·문서만 읽고 검증했다. 서비스 재시작, GraphDB/온톨로지 재빌드, 인덱싱, 후보 승격, 활성 계산 규칙/매니페스트/원문/운영 데이터 변경, stage/commit/push는 수행하지 않았다.

## 판정

`CHANGES_REQUESTED`

비교 완결성 P0-1은 해결되었고, formal/quickcode 공통 helper도 추가되었다. 그러나 보상 판단 여부가 일부 검색 의도 반환 분기에서 누락되어, 자연스러운 **수가/수술 코드 + 보상 여부** 및 **조항 + 보상 여부** 질의가 여전히 LLM 생성으로 우회한다. 이는 이전 P0-2의 실질 경로가 남아 있는 것이므로 메인 반영 또는 UAT 진행 전 수정이 필요하다.

## 독립 검증 결과

다음 집중 회귀를 독립 실행했다.

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest \
  -p no:cacheprovider \
  tests/test_pipeline.py tests/test_api_rag_service_payload.py \
  tests/test_api_chat_stream.py tests/test_search_intent.py \
  tests/test_graph_context.py tests/test_clause_detail_rows.py -q
```

결과: `191 passed, 1 warning`. 경고는 공유 환경 `passlib`의 `crypt` deprecation 1건이다. `git diff --check`도 통과했다.

출처 payload 및 클릭 계약은 별도로 아래를 실행해 통과했다.

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest \
  -p no:cacheprovider tests/test_api_source_pdf.py -q
node --test tests/test_frontend_source_preview_settings.mjs
```

결과: Python `3 passed, 1 warning`, Node `8/8 passed`. 후보 diff에도 프론트엔드·PDF endpoint 파일은 포함되지 않았다.

### 통과한 P0-1: 일반 비교축 완결성

무상태 fixture에서 `alpha와 beta 검사X의 연간 보상한도를 비교해줘.`에 `alpha` 직접 근거만 제공하면 다음으로 종료했다.

```text
origin=policy_comparison
grounding_state=insufficient
source_chunk_ids=[]
```

공개 문구에는 `123만원`이 없었다. 양쪽 직접 근거를 모두 제공한 경우에만 `policy_comparison/direct`와 `attribute-alpha`, `attribute-beta` 두 source ID 및 두 수치가 함께 남았다. 비교축 추출은 `\d+세대` 일반 패턴과 질문의 축 쌍에서 동작하며, P0 수정 부분에 MRI 또는 특정 세대 조합을 비교 조건으로 사용한 흔적은 없었다.

### 통과한 specialized helper의 정상 경로

- 승인 직접 근거가 없는 단순 `검사X 보상 가능 여부` fixture는 formal/quickcode 모두 `coverage_insufficient`로 종료했고 LLM 호출은 없었으며 source는 유지됐다.
- 승인 직접 근거 fixture는 `coverage_grounded/direct`의 조건부 공개 답변과 source ID를 유지했다.
- 순수 수가코드 조회는 `llm/none`으로 남아 registry 평가를 호출하지 않았다.

## 발견 사항

### P0 — 실제 code/clause/cross-document 복합 보상 질의에서 coverage flag가 사라진다

`src/rag/search_intent.py:180`은 `requires_coverage = _is_coverage_judgment(compact)`를 계산한다. 그러나 아래 세 반환 분기는 이 값을 `SearchIntentPlan.requires_coverage_judgment`에 전달하지 않는다.

- `clause_or_appendix_lookup` (`240-251`)
- `cross_doc_compare` (`253-264`)
- `procedure_code_lookup` (`266-276`)

반면 `src/api/rag_service.py:436-438`의 `resolve_specialized_coverage_disposition()`은 이 plan 필드가 false이면 바로 `llm/none`을 반환한다. 이어 `src/api/routes/chat.py:784-800`의 공통 스트리밍 분기가 LLM을 호출한다. 즉 helper 자체는 올바른 위치에 추가되었지만, helper가 받는 intent 계약이 실제 복합 질의를 보상 판단으로 보존하지 못한다.

무상태 재현 결과는 다음과 같다.

```text
질의: 식도조루술 수가 코드와 실손 보상 여부를 알려줘.
raw _is_coverage_judgment: True
route: quickcode
plan.intent: procedure_code_lookup
plan.requires_coverage_judgment: False
specialized disposition: llm / none
registry evaluation calls: 0
```

같은 결함은 다음 자연어에도 재현됐다.

```text
제3조에 따르면 식도조루술은 보상 가능한가요?
약관 면책조항상 탈모는 보상되나요?
```

두 질의 모두 원시 보상 판정은 true이고 route는 formal이지만 `clause_or_appendix_lookup` plan의 coverage flag가 false라 specialized helper는 `llm/none`을 반환한다.

또한 `4세대와 5세대 검사X의 연간 보상한도를 비교해서 보상 가능 여부도 알려줘.`는 양쪽 직접 속성 근거가 있으면 `cross_doc_compare` plan의 coverage flag 누락 때문에 `policy_comparison/direct`로 두 한도 수치를 공개한다. 직접 보장·면책 근거 없이 보상 여부까지 묻는 경우에는 `coverage_insufficient`로 전환되어야 한다.

현재 추가된 테스트는 보상 여부만 담은 query를 formal/quickcode route로 강제해 helper의 동작 자체는 확인하지만, 실제 `procedure_code_lookup` 또는 `clause_or_appendix_lookup` 분류를 거치는 복합 질의를 포착하지 못한다.

## 요구 수정

검색 전략 자체를 사례별로 바꾸지 말고, 이미 계산한 `requires_coverage`를 모든 relevant 반환 plan에 보존해야 한다.

1. `clause_or_appendix_lookup`, `cross_doc_compare`, `procedure_code_lookup`에도 `requires_coverage_judgment=requires_coverage`를 전달한다.
2. 실제 라우팅을 사용한 회귀를 추가한다. route를 강제하지 말고 아래를 포함한다.
   - quickcode: 수가/수술 코드 + `보상 여부` 질의가 승인 근거 없을 때 `coverage_insufficient`, LLM 미호출, source 유지, audit count 0인지.
   - formal: 조항/면책 + `보상 가능` 질의가 같은 경계를 지키는지.
   - general cross-document: 두 직접 속성 근거가 있어도 `보상 가능 여부`를 함께 요구하면 승인 직접 보장·면책 근거 없이는 수치 노출 없이 `coverage_insufficient`인지.
   - 기존 순수 수가/수술종수/조항 설명 질의는 ordinary LLM 또는 기존 결정적 속성 경로를 유지하는지.
3. focused suite와 전체 suite를 다시 실행하고, source hover/click payload와 active rule/manifest/GraphDB/ontology/raw data/frontend 파일 무변경을 재확인한다.

## Developer Fix Prompt

> 후보 작업공간 `/srv/shared/workspaces/muldae/insurance-rag-chatbot-final-answer-grounding-20260721`에서 이번 P0 fixback만 수정하세요. 현재 `classify_search_intent()`는 원시 `requires_coverage`를 계산하지만 `clause_or_appendix_lookup`, `cross_doc_compare`, `procedure_code_lookup` 반환 plan에 `requires_coverage_judgment`를 전달하지 않아 실제 formal/quickcode/general 복합 보상 질의가 `resolve_specialized_coverage_disposition()`을 `llm/none`으로 우회합니다. 사례별 문자열·MRI·특정 세대 하드코딩을 추가하지 말고, 기존에 계산한 `requires_coverage` 계약을 해당 세 일반 분기에 보존하세요. 실제 route를 강제하지 않은 회귀를 추가해야 합니다: (1) `식도조루술 수가 코드와 실손 보상 여부를 알려줘.`는 quickcode에서 승인 직접근거 없으면 LLM 미호출·source 유지·`coverage_insufficient`·audit grounded count 0, (2) `제3조에 따르면 식도조루술은 보상 가능한가요?` 또는 면책 조항 질의는 formal에서 동일, (3) `4세대와 5세대 검사X의 연간 보상한도를 비교해서 보상 가능 여부도 알려줘.`는 양쪽 속성 근거가 있더라도 승인 직접 보장·면책 근거 없으면 수치 비교를 공개하지 않고 fail-closed, (4) 순수 수가/수술종수/조항 설명은 기존 일반 경로를 유지합니다. 기존 one-sided comparison, approved direct evidence, source payload/public finalization 회귀도 유지하세요. 활성 계산 규칙·매니페스트·GraphDB/온톨로지·원문·운영 데이터·프론트엔드·서비스 설정은 변경하지 말고 stage/commit/push/restart/rebuild/reindex도 하지 마세요. focused와 전체 pytest 결과 및 구현 보고서를 갱신하세요.

## 범위 확인

후보 변경은 API/RAG/Graph prompt context/search intent, 대응 테스트, 두 보고서로 한정되어 있다. 활성 계산 규칙, 승인 manifest, GraphDB/온톨로지, 원본 자료, 사용자/대화 데이터, 프론트엔드, PDF endpoint, 운영 설정은 변경 목록에 없다. 이 보고서 외 후보 상태는 수정하지 않았다.
