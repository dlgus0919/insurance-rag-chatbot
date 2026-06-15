# 224. Ontology LLM Model Selection Report

## 기준 문서 정정

이번 작업의 기준 문서는 다음 두 문서다.

- `docs/221_LLM_MODEL_SUPPORT_AND_EVALUATION_PLAN.md`: 전체 LLM 지원 모델 고정 및 기능별 평가 계획
- `docs/222_ONTOLOGY_LLM_ENRICHMENT_EVALUATION_IMPLEMENTATION_PLAN.md`: 온톨로지 후보 enrichment 평가 구현 계획

이 보고서는 `222` 계획 중 온톨로지 후보 개념/alias 검토 보조 모델 선택 결과를 정리한다. `223_LLM_MODEL_EVALUATION_IMPLEMENTATION_REPORT.md`는 smoke 단계 구현 보고서이며, 최종 모델 선택 근거는 본 문서를 기준으로 한다.

## 작업 일시와 저장소

- 작성 시각: 2026-06-12 00:10 KST
- 기준 저장소: DGX `/srv/shared/projects/insurance-rag-chatbot`
- 기준 브랜치: `master`

## 구현 보완

기존 shadow 평가에는 JSON/schema 안정성과 unsafe approval 수만 있었다. 모델 선택을 실제로 수행하기에는 edge-case 정답 기준이 부족했으므로 다음을 추가했다.

- `scripts/eval_ontology_llm_enrichment.py`
  - `--extra-input`으로 gold/synthetic edge-case 후보 추가 입력 지원
  - 후보별 `expected_enrichment` 평가 지원
  - expected decision, forbidden decision, required reason code 검증
  - Markdown summary에 `expected_pass` 지표 추가
- `src/ontology/llm_enrichment.py`
  - 모델별 `expected_total`, `expected_pass`, `expected_pass_rate` summary 추가
- `eval/ontology_llm_enrichment_cases.jsonl`
  - 안전 alias 승인, 문장 조각, 지급 판단 risk, ownership conflict, evidence mismatch를 포함한 안정적인 edge-case 6건 추가
  - 이 중 5건은 expected 평가 대상이고 1건은 ownership conflict 탐지를 위한 context row

## 평가 입력

실제 규칙 후보:

```bash
.venv/bin/python scripts/extract_ontology_candidates.py \
  --dry-run \
  --limit 100 \
  --template-only > /tmp/ontology_rule_candidates_goal.json
```

- `source_count`: 2000
- `generated_count`: 14
- 실제 후보: 14건
- gold/edge fixture: 6건
- 총 평가 후보: 20건

모델 비교:

```bash
.venv/bin/python scripts/eval_ontology_llm_enrichment.py \
  --input /tmp/ontology_rule_candidates_goal.json \
  --extra-input eval/ontology_llm_enrichment_cases.jsonl \
  --models qwen3-next-80b-a3b-instruct-fp8,qwen3-30b-a3b-instruct-2507-fp8,gpt-oss-20b \
  --start-llm \
  --stop-llm-after \
  --label ontology_goal_full_20260611_v2
```

산출물:

- `reports/ontology_llm_enrichment_eval/ontology_goal_full_20260611_v2.jsonl`
- `reports/ontology_llm_enrichment_eval/ontology_goal_full_20260611_v2.md`

## 평가 결과

| model | json_validity | schema_validity | unsafe_approval | expected_pass | 결정 |
|---|---:|---:|---:|---:|---|
| `sglang:qwen3-30b-a3b-instruct-2507-fp8` | 100.00% | 100.00% | 0 | 5/5 | 온톨로지 enrichment 주력 |
| `sglang:qwen3-next-80b-a3b-instruct-fp8` | 100.00% | 100.00% | 0 | 4/5 | Optional |
| `sglang:gpt-oss-20b` | 100.00% | 95.00% | 0 | 5/5 | 온톨로지 역할 없음 |

세 모델 모두 unsafe approval은 없었다. 그러나 최종 모델 선택 기준은 단순 통과 여부가 아니라 schema 안정성과 edge-case 사유 구조화 정확도다.

세부 결점:

- `qwen3-next-80b-a3b-instruct-fp8`
  - `gold.reject.policy_risk`에서 최종 decision은 `reject`로 맞췄다.
  - 그러나 required reason code `policy_risk`를 내지 못하고 `ownership_conflict`, `sentence_fragment`로 분류했다.
  - 지급 판단 후보를 차단하더라도 사유 구조화가 흔들리면 실무자 검토 화면에서 잘못된 보류/거절 안내가 될 수 있다.
- `gpt-oss-20b`
  - `dev.cov.nonpay_injection.15a4e6a5b270`에서 schema validation 실패가 발생했다.
  - expected edge-case는 5/5였지만 schema validity가 95%로 gate 기준 98%를 넘지 못했다.

## 최종 모델 역할

| model | answer role | ontology role | Optional | 보존/삭제 판단 |
|---|---|---|---:|---|
| `qwen3-30b-a3b-instruct-2507-fp8` | 미확정 | `ontology_enrichment_primary_model` | false | 보존 |
| `qwen3-next-80b-a3b-instruct-fp8` | 미확정 | none | true | 삭제 가능 표시, 즉시 삭제 금지 |
| `gpt-oss-20b` | 기존 답변 생성 baseline | none | false | 답변 생성 baseline 역할 때문에 보존 |

따라서 앱 코드의 지원 모델 metadata는 다음처럼 고정한다.

- `qwen3-30b-a3b-instruct-2507-fp8`
  - `status`: `ontology_primary`
  - `use_case`: 온톨로지 후보 enrichment 주력 batch 모델
- `qwen3-next-80b-a3b-instruct-fp8`
  - `status`: `optional`
  - `use_case`: 온톨로지 enrichment 비교 후 Optional
- `gpt-oss-20b`
  - 기존 `validated` 유지
  - 온톨로지 모델로는 탈락했지만 답변 생성 baseline이므로 Optional이나 삭제 후보로 낮추지 않는다.

## 안전성 판단

이번 평가는 운영 ontology manifest에 직접 반영하지 않았다.

- `data/ontology/concepts.json` 변경 없음
- `data/ontology/concepts.active.json` 변경 없음
- GraphDB rebuild 미실행
- LLM 출력은 shadow evaluation report로만 저장
- 평가 후 `--stop-llm-after`로 테스트 기동 모델 세션 정리

온톨로지 후보 적용은 여전히 기존 실무자 승인 workflow와 guardrail을 거쳐야 한다.

## 결론

온톨로지 후보 enrichment 주력 모델은 `qwen3-30b-a3b-instruct-2507-fp8`로 확정한다.

`qwen3-next-80b-a3b-instruct-fp8`는 같은 schema 안정성을 보였지만 edge-case 사유 구조화에서 30B보다 열세였으므로 Optional로 표시한다. 단, 물리 삭제는 하지 않는다.

`gpt-oss-20b`는 온톨로지 enrichment 용도로는 선택하지 않는다. 다만 기존 답변 생성 baseline이므로 보존한다.
