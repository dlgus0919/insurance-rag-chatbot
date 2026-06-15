# 223. LLM 모델 평가 구현 및 Smoke 결과 보고

## 기준 문서 정정

이번 작업의 기준 문서는 DGX SSH 셋업 문서인 `217`이 아니라 다음 두 문서다.

- `docs/221_LLM_MODEL_SUPPORT_AND_EVALUATION_PLAN.md`
- `docs/222_ONTOLOGY_LLM_ENRICHMENT_EVALUATION_IMPLEMENTATION_PLAN.md`

`217_CODEX_DGX_TAILSCALE_SSH_SETUP.md`는 연결성 참고 문서로만 취급했고, 모델 평가 구현 범위에는 포함하지 않았다.

## 구현 범위

### 답변 생성 LLM 평가

- 첨부 실손약관 품질점검 XLSX를 JSONL 평가셋으로 변환하는 `scripts/convert_policy_xlsx_eval.py`를 추가했다.
- 파생 평가셋 `eval/policy_xlsx_qa.jsonl`에는 40개 문항이 포함된다.
- 분류 커버리지:
  - 계약 전·후 알릴의무 5
  - 계약 성립·철회·무효 5
  - 보험료 납입·연체·부활 4
  - 보험금 지급·청구 3
  - 보상하는/하지 않는 사항 3
  - 비급여 실손의료비 특약 8
  - 다수보험 처리 2
  - 해지·해약환급금 3
  - 갱신·재가입 2
  - 분쟁·약관해석 2
  - 제도성 특별약관 3
- `scripts/eval_large_model_rag.py`를 SGLang 전용에서 provider-aware 평가로 확장했다.
  - `sglang:<model>`, `vllm:<model>`, `ollama:<model>` 형식 지원
  - vLLM base URL/switch command 지원
  - `required_clause_terms`, `required_numbers`, `required_groups` 채점 추가
  - 한국어 띄어쓰기와 일부 조사 차이를 필수어 매칭에서 허용
  - `--stop-llm-after` 추가로 평가 후 SGLang/vLLM tmux session 정리

### 온톨로지 후보 LLM enrichment 평가

- `src/ontology/llm_enrichment.py`를 추가했다.
  - 후보 입력 payload 구성
  - JSON-only prompt 생성
  - 출력 schema validation
  - invalid JSON/schema 실패 시 `hold`, `high`, `schema_uncertain` 안전 fallback
  - unsafe approval 감지
  - reason code alias 정규화
- `scripts/eval_ontology_llm_enrichment.py`를 추가했다.
  - 동일 후보 입력을 여러 모델에 순차 투입
  - dry-run template mode 지원
  - JSONL/Markdown report 생성
  - 모델별 `json_validity`, `schema_validity`, `unsafe_approval_count` 집계

### Optional 모델 표시

- `gemma-4-26b-a4b-nvfp4`를 삭제하지 않고 `optional` 상태로 표시하도록 변경했다.
- `/api/system/models` 응답의 `ModelInfo`에 `status`, `use_case`, `optional` 필드를 추가했다.
- 현재 smoke 결과만으로 Qwen 30B/80B 중 하나를 삭제 후보로 확정하지 않았다. 두 모델 모두 온톨로지 batch 후보로 `reserved` 상태를 유지하는 것이 안전하다.

## DGX Smoke 실행 결과

### 답변 생성 baseline

실행:

```bash
.venv/bin/python scripts/eval_large_model_rag.py \
  --cases eval/policy_xlsx_qa.jsonl \
  --models gpt-oss-20b \
  --limit 3 \
  --label policy_xlsx_smoke_gptoss_v3 \
  --stop-llm-after
```

결과:

- `sglang:gpt-oss-20b`: 3/3 pass
- report:
  - `reports/large_model_rag_eval/large_model_rag_eval_policy_xlsx_smoke_gptoss_v3.jsonl`
  - `reports/large_model_rag_eval/large_model_rag_eval_policy_xlsx_smoke_gptoss_v3.md`
- 초기 실행에서는 `보통약관` generic clause와 항 단위 exact match 때문에 실패가 발생했다.
- 이를 `제16조`, `제15조` 같은 조 단위 채점으로 수정했고, 한국어 띄어쓰기/조사 차이도 보정했다.

### 온톨로지 enrichment smoke

최종 Qwen 30B 실행:

```bash
.venv/bin/python scripts/eval_ontology_llm_enrichment.py \
  --input /tmp/ontology_rule_candidates_dgx.json \
  --models qwen3-30b-a3b-instruct-2507-fp8 \
  --limit 2 \
  --start-llm \
  --stop-llm-after \
  --label qwen30_ontology_smoke_20260611_v3
```

결과:

- `sglang:qwen3-30b-a3b-instruct-2507-fp8`
- `json_validity`: 100%
- `schema_validity`: 100%
- `unsafe_approval_count`: 0
- decision: `hold` 2건

최종 Qwen 80B 실행:

```bash
.venv/bin/python scripts/eval_ontology_llm_enrichment.py \
  --input /tmp/ontology_rule_candidates_dgx.json \
  --models qwen3-next-80b-a3b-instruct-fp8 \
  --limit 2 \
  --start-llm \
  --stop-llm-after \
  --label qwen80_ontology_smoke_20260611_v3
```

결과:

- `sglang:qwen3-next-80b-a3b-instruct-fp8`
- `json_validity`: 100%
- `schema_validity`: 100%
- `unsafe_approval_count`: 0
- decision: `reject` 2건

해석:

- 두 모델 모두 최종 validator 기준 schema 안정성 smoke를 통과했다.
- 30B는 보수적으로 `hold`를 선택했고, 80B는 위험 후보를 더 강하게 `reject`했다.
- 이 결과는 2건 smoke이므로 최종 모델 고정 근거로는 부족하다.
- 다만 온톨로지 enrichment pipeline의 실제 LLM 호출, schema validation, unsafe approval 차단, start/stop lifecycle은 검증됐다.

## 검증 명령

DGX 기준:

```bash
.venv/bin/python -m compileall -q \
  scripts/eval_large_model_rag.py \
  scripts/convert_policy_xlsx_eval.py \
  scripts/eval_ontology_llm_enrichment.py \
  src/llm/factory.py \
  src/api/routes/system.py \
  src/api/schemas/system.py \
  src/ontology/llm_enrichment.py
```

```bash
.venv/bin/python -m pytest \
  tests/test_large_model_eval.py \
  tests/test_llm_factory.py \
  tests/test_api_auth_system.py \
  tests/test_ontology_llm_enrichment.py \
  tests/test_policy_xlsx_converter.py \
  -q
```

결과:

- `44 passed, 1 warning`
- warning은 `passlib`의 Python 3.13 예정 `crypt` deprecation이며 이번 변경과 무관하다.

LLM endpoint 정리 확인:

- `http://127.0.0.1:30000/v1/models`: connection refused
- `http://127.0.0.1:30001/v1/models`: connection refused
- 남은 tmux session: `insurance-rag-api`만 확인

## 남은 판단

- 이번 결과만으로 답변 생성 주력 모델을 새로 고정하지 않는다. `gpt-oss-20b`는 3문항 smoke 기준 baseline 가능성을 확인했지만, 40문항 전체와 다른 후보 모델 비교가 필요하다.
- 이번 결과만으로 Qwen 30B와 Qwen 80B 중 하나를 삭제 후보로 확정하지 않는다.
- `gemma-4-26b-a4b-nvfp4`만 사용자의 사전 판단에 따라 Optional로 표시한다. 실제 파일 삭제는 수행하지 않았다.
- 다음 배치에서는 `eval/policy_xlsx_qa.jsonl` 40문항 전체와 ontology 후보 50~100건 기준으로 모델별 ranking table을 생성한 뒤 `docs/221`의 decision matrix에 병합해야 한다.

## Self-Inspection

- 요청 범위 밖의 운영 ontology manifest, GraphDB, DB rebuild는 수행하지 않았다.
- 원본 XLSX는 커밋 대상에 포함하지 않았다.
- `reports/` 산출물은 `.gitignore` 대상이므로 작업 공간 evidence로만 남기고, 커밋에는 이 보고서와 재현 가능한 스크립트/평가셋만 포함한다.
- `CLAUDE.md` 삭제와 `docs/217_CODEX_DGX_TAILSCALE_SSH_SETUP.md` untracked 파일은 기존 상태로 간주하여 스테이징하지 않는다.
