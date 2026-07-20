# 최종 말풍선 근거 경계 Intent-Contract P0 Fixback 재검토

- 검토일: 2026-07-21 KST
- 후보 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-final-answer-grounding-20260721`
- 후보 기준: `3353fead2492b4ab9f64fbc45bb45445ebf2f6e7`
- 선행 보고서: `docs/reviews/2026-07-21-0318-final-answer-grounding-fixback-rereview.md`
- 검토 범위: 이전 P0의 intent-contract 세 반환 분기 수정과 해당 자동 라우팅 회귀만 독립 읽기 전용으로 재검토
- 운영 경계: 코드·테스트·문서만 읽고 검증했다. 후보 승격, stage/commit/push, merge, 배포, 서비스 재시작, GraphDB/온톨로지 재빌드, 인덱싱, 활성 규칙·매니페스트·원문·운영 데이터 변경은 수행하지 않았다.

## 판정

`PASS` — 후보 코드 검토 기준으로 P0 intent-contract 수정은 타당하다. 이는 후보를 main에 반영하거나 배포·재시작할 권한이 아니다.

## P0 재현 결과

자동 route를 강제하지 않고 `classify_search_intent()`와 `resolve_query_route()`를 함께 사용한 무상태 fixture를 독립 실행했다.

| 질의 유형 | 실제 route / intent | 결과 |
| --- | --- | --- |
| `시술Y 수가 코드와 실손 보상 여부` | `quickcode` / `procedure_code_lookup` | `requires_coverage_judgment=True`, 승인 직접 근거가 없으면 `coverage_insufficient`, 수치 미노출, source 유지 |
| `제3조 면책조항상 시술Y는 보상 가능한가요` | `formal` / `clause_or_appendix_lookup` | 동일하게 fail-closed |
| `alpha와 beta ... 보상한도를 비교해서 보상 가능 여부` | `general` / `cross_doc_compare` | 두 직접 속성 근거가 있어도 승인 직접 보장·면책 근거가 없으면 `coverage_insufficient`, `123만원`·`456만원` 미노출 |
| 일반 `alpha와 beta ... 보상한도 비교` | `general` / cross-document | 한쪽 근거만 있으면 `policy_comparison/insufficient`; 양쪽 직접 근거일 때만 `policy_comparison/direct`와 두 source ID |

전문화 helper를 직접 확인했을 때 앞의 quickcode/formal 두 질의는 registry 평가를 각각 1회 거쳐 `coverage_insufficient`가 되었고, `source_chunk_ids`는 비어 있었다. 반면 선택된 public source는 그대로 남았다. 승인 직접 근거 fixture는 `coverage_grounded/conditional` 및 선택 source ID를 유지했다.

`chat_stream()` 수준 자동 route 회귀도 별도 실행했다. quickcode, formal, general-comparison 보상 질의는 모두 LLM 호출 0회, `coverage_insufficient`, audit `grounded_source_count=0`, public source 보존으로 통과했다.

## 구현 타당성

생산 코드 수정은 `src/rag/search_intent.py`의 세 일반 반환 분기에 이미 계산된 `requires_coverage`를 보존하는 세 줄이다.

- `clause_or_appendix_lookup`
- `cross_doc_compare`
- `procedure_code_lookup`

판단 키워드나 라우터를 사례별로 추가하지 않았다. 특히 P0 수정 production hunk에는 MRI/MRA, 특정 세대, 특정 시술명, 특정 금액의 분기 조건이 없다. 기존 `_is_coverage_judgment()`의 단일 판정 계약만 각 검색 전략으로 전달한다.

`chat_stream()`에는 LLM 스트림 호출 지점이 하나이며, formal/quickcode는 모두 route별 검색 뒤 `resolve_specialized_coverage_disposition()`을 통과한다. 일반 경로는 `prepare_retrieved_context()`가 만든 disposition을 같은 공통 지점에서 소비한다. 새 자동-route 테스트는 `resolve_query_route()`를 monkeypatch하지 않고, 잘못된 route의 retrieval helper가 호출되면 실패하도록 구성되어 있어 이전의 route-forcing 테스트 공백을 보완한다.

## 호환성 확인

- 순수 수가코드 조회: `quickcode` / non-decision / 기존 LLM 경로 유지
- 순수 수술종수 조회: `general` / non-decision 유지
- 순수 조항·면책 내용 설명: `formal` / non-decision 유지
- `입원치료 자기부담금 비율`: `policy_attribute_lookup` / non-decision 유지
- 승인 직접 근거 보상 판단: LLM 없이 grounded conditional 답변 유지
- 불완전·완전 일반 비교: 기존 비교 완결성 계약 유지

따라서 이번 수정은 보상 판단으로 이미 분류된 질문의 권한 경계만 닫고, 단순 코드·종수·조항 설명을 새로 차단하지 않는다.

## 독립 검증

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest -q \
  -p no:cacheprovider \
  tests/test_search_intent.py tests/test_pipeline.py tests/test_graph_context.py \
  tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py \
  tests/test_clause_detail_rows.py tests/test_api_source_pdf.py
```

결과: `203 passed, 1 warning in 2.60s`; `git diff --check` 통과.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest -q \
  -p no:cacheprovider
```

결과: `1204 passed, 3 warnings in 15.35s`.

```bash
node --test tests/test_frontend_source_preview_settings.mjs
```

결과: `8/8 passed`. Node의 ES module type 경고 1건은 기존 `frontend/package.json` 설정 경고이며, 프론트엔드 파일은 이번 후보 diff에 없다. API PDF source 테스트도 focused suite에서 `3 passed`로 포함되어 있다.

Python 경고는 공유 환경 `passlib`의 `crypt` deprecation 1건과 기존 OCR test의 Pillow `Image.getdata` deprecation 2건이다.

## 범위 및 남은 운영 검증

후보 변경 목록은 API/RAG/Graph prompt context/search intent, 관련 테스트, 구현·리뷰 보고서로 한정된다. 활성 보험금 계산 규칙, 승인 매니페스트, GraphDB/온톨로지, 원본 PDF/OCR, 사용자·대화 데이터, 프론트엔드, PDF endpoint, 운영 설정은 변경되지 않았다.

후보 코드 차원의 P0는 닫혔다. main 반영 후에는 별도 운영 UAT에서 실제 검색 데이터와 Chrome으로 최종 말풍선, 출처 hover, 원본 PDF의 해당 페이지 열기를 다시 확인해야 한다.
