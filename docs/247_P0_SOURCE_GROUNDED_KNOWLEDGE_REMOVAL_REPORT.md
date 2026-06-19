# 247. P0 Source-Grounded Knowledge Removal Report

## Summary

P0 계획에 따라 보험금 계산, RAG deterministic guard, GraphRAG 추출 경로에서 제품별 공제율·한도·지급비율을 Python 상수로 직접 보유하던 부분을 source-grounded 데이터 계층으로 분리했다. 코드는 승인된 rule manifest와 Graph extraction policy를 읽어 해석하는 엔진 역할만 수행한다.

## Changed Areas

### Claim Calculation

- `data/rules/claim_deductible_rules.active.json`에 실손 세대별 공제 규칙, 처방조제 공제, 상급병실료 차액, 건강보험 미적용 특례를 source reference와 함께 저장했다.
- `src/claim_calculation/rule_registry.py`를 추가해 active rule만 로드하고, source reference가 없는 rule은 거부하도록 했다.
- `src/claim_calculation/deductible_rules.py`는 기존 public API를 유지하되 manifest-backed compatibility wrapper로 전환했다.
- `src/claim_calculation/pipeline.py`에서 LLM `formula_intent` 실행 권한을 제거했다. 최종 금액은 approved rule layer가 산출하고, LLM 산식은 review note로만 남긴다.
- `FakePlanner`는 금액 파싱과 상태 분기만 수행하도록 축소했다. 테스트 환경에서도 도메인 산식을 생성하지 않는다.

### RAG Deterministic Answers

- `src/rag/source_grounded_answers.py`를 추가했다.
- 없는 코드 단정 방지, 4/5세대 비중증 비급여 비교, 심평원 수가표 직접 행 답변은 모두 제공된 source row 또는 approved rule row에서만 값을 읽는다.
- `src/rag/pipeline.py`의 질문별 하드코딩 deterministic answer block을 source-grounded builder 호출로 분리했다.

### GraphRAG Extraction

- `data/ontology/policies/graph_extraction_markers.active.json`에 BenefitLimit/DeductibleRule marker와 SOL 별표7 등급별 지급비율 정책을 분리했다.
- `src/graph/extractors.py`는 marker policy와 SOL 등급 정책을 로드해 후보 노드를 생성한다.
- 이 정책은 계산 rule이 아니라 Graph 후보 연결용 정책이다. 최종 지급 판단에는 claim rule manifest 또는 source evidence가 필요하다.

## Validation

통과:

```bash
python -m json.tool data/rules/claim_deductible_rules.active.json
python -m json.tool data/rules/claim_deductible_rules.schema.json
python -m json.tool data/ontology/policies/graph_extraction_markers.active.json
python -m json.tool data/ontology/policies/graph_extraction_markers.schema.json
git diff --check
python -m pytest tests/test_graph_extraction_marker_policy.py tests/test_graph_extractors.py tests/test_claim_calculation_pipeline.py::test_fake_planner_amount_formatting_variations -q
python -m pytest tests/test_claim_rule_registry.py tests/test_deductible_rules.py tests/test_claim_calculation_pipeline.py tests/test_claim_planner.py tests/test_source_grounded_answers.py tests/test_pipeline.py tests/test_logic_final_round_2.py tests/test_graph_extraction_marker_policy.py tests/test_graph_extractors.py -q
```

결과:

- 좁은 회귀: `8 passed`
- P0 관련 회귀: `136 passed`

미실행:

- `python -m pytest -q` 전체 테스트는 현재 작업트리의 로컬 Python 환경에 `fastapi`와 `aiosqlite`가 없어 API 계열 테스트 collection 단계에서 중단됐다.
- `tests/test_api_chat_stream.py`도 같은 이유로 별도 실행 시 collection 단계에서 중단됐다. `requirements.txt`에는 `aiosqlite>=0.20`이 명시되어 있으므로, DGX 또는 완전한 venv에서 재검증해야 한다.

## Self-Inspection

- Python production 코드에 제품별 공제율·한도·지급비율 값이 직접 산식 상수로 남지 않도록 검색했다.
- 남은 수치 값은 `data/rules/*`, `data/ontology/policies/*`, 또는 테스트 fixture에 위치한다.
- `src/rag/source_grounded_answers.py`와 `src/claim_calculation/pipeline.py`에는 산식 해석 알고리즘이 남아 있으나, 입력 값은 approved rule/source row에서 읽는다.
- Ponytail 검토에서 `facility_grade=all` rule 중복 반환과 비활성 Graph marker 로드 가능성을 수정했다.
- 이번 변경은 Streamlit legacy, raw source data, runtime index를 수정하지 않았다.

## Remaining Risk

- 일부 legacy-compatible rule row는 정확한 indexed source가 부족해 `source_status`에 `legacy_behavior_without_exact_indexed_amount` 또는 유사 상태를 명시했다. 이 행들은 다음 단계에서 실무자 승인/근거 보강 대상으로 분리하는 것이 적절하다.
- Graph extraction marker policy에는 후보 연결용 지급비율/한도 표현이 포함되어 있다. 이는 계산 rule이 아니며, 운영 반영 전 practitioner approval workflow와 GraphDB rebuild 검증이 필요하다.
- API 계열 전체 테스트와 chat stream 테스트는 현재 로컬 환경 미충족으로 미검증이다.
