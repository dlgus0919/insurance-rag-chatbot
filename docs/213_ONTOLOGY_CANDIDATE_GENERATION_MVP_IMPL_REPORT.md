# 213. Ontology Candidate Generation MVP Implementation Report

작성일: 2026-06-10

## Summary

`docs/212_ONTOLOGY_CANDIDATE_GENERATION_IMPLEMENTATION_PLAN.md`의 Phase 5 MVP 범위에 맞춰 승인 기반 온톨로지 후보 생성 파이프라인을 구현했다.

이번 구현은 운영 manifest를 직접 수정하지 않는다. 원천 chunk 또는 GraphDB evidence에서 기존 온톨로지 concept의 보강 후보를 생성하고, `data/ontology/review/candidates.jsonl`에 `pending` 후보로 저장한다.

## Implemented

### 1. 후보 생성 모듈

추가 파일:

- `src/ontology/candidate_extractor.py`
- `scripts/extract_ontology_candidates.py`
- `tests/test_ontology_candidate_extractor.py`

지원 범위:

- 기존 concept 보강 후보
- `alias_or_expansion`
- `candidate_aliases`
- retrieval expansion rule
- evidence tag 후보

후보 소스:

- `data/processed/*.jsonl`
- `data/index/graph/insurance_graph.sqlite`가 있으면 `graph_evidence`

### 2. 실무자 표시용 metadata

추가 파일:

- `src/ontology/candidate_display.py`
- `tests/test_ontology_candidate_display.py`

후보에는 `properties.display`가 들어간다.

- `summary`
- `similar_expressions`
- `example_questions`
- `approval_prompt`

`scripts/ontology_review.py --show`와 DGX `insurance-rag-ontology-review-gui`는 이 표시용 정보를 우선 보여준다.

### 3. 개발용 Codex review metadata

추가 파일:

- `src/ontology/candidate_reviewer.py`
- `tests/test_ontology_candidate_reviewer.py`

저위험 보강 후보에만 `properties.codex_dev_review.decision=approve`를 부여한다.

자동 승인 제외:

- 지급 rule
- 면책 rule
- 감액 rule
- 보험금 계산 rule
- source evidence 없는 후보
- 중위험/고위험 후보

### 4. DGX batch LLM 정책

추가 파일:

- `src/ontology/llm_batch.py`

정책:

- 외부 API 호출 없음
- Ollama fallback 없음
- 기본 모델: `qwen3-next-80b-a3b-instruct-fp8`
- 우선순위: `qwen3-next-80b-a3b-instruct-fp8` -> `qwen3-30b-a3b-instruct-2507-fp8` -> `gpt-oss-20b`
- `--start-llm`, `--stop-llm-after`, `--model`, `--llm auto|none|sglang|vllm`, `--template-only` 옵션 제공

### 5. Active manifest 병합 보강

수정 파일:

- `src/ontology/manifest_merge.py`
- `tests/test_ontology_manifest_merge.py`

기존에는 approved 후보를 새 concept로만 추가했다. 이번 변경으로 `alias_or_expansion`, `evidence_tag`, `search_query_expansion` 후보는 `target_concept_id`의 기존 concept에 alias, candidate_aliases, evidence_tags, retrieval expansion rule로 병합된다.

## Guardrails

- `data/ontology/concepts.json` 직접 수정 없음
- 운영 후보 전체 자동 승인 없음
- 지급/면책/감액/계산 rule 자동 승인 없음
- source evidence 없는 후보는 개발 자동 승인 대상 아님
- 실무자 UI는 내부 metadata 대신 표시용 요약을 우선 노출
- 목차/수가표/코드표 조각과 지나치게 일반적인 단어는 후보 추출에서 제외
- 기존 concept 표현과 형태적으로 연결되지 않은 보강 표현은 후보 생성 단계에서 제외
- `보험`, `담보`, `급여/비급여`, `보험금`, `지급`, `보상`, `특약`, `가입`, `자동차`, `포함`, `한함`처럼 보장 범위나 지급 판단으로 이어질 수 있거나 지나치게 넓은 표현은 alias 후보여도 개발 자동 승인 대상에서 제외

## Verification

로컬과 DGX에서 다음 범위의 검증을 수행했다.

```bash
bash -n ops/bin/insurance-rag-ontology-review-gui ops/bin/insurance-rag-desktop-launcher
.venv/bin/python -m py_compile src/ontology/*.py scripts/extract_ontology_candidates.py scripts/ontology_review.py
.venv/bin/python -m pytest tests/test_ontology_candidate_extractor.py tests/test_ontology_candidate_display.py tests/test_ontology_candidate_reviewer.py tests/test_ontology_review_store.py tests/test_ontology_manifest_merge.py tests/test_ontology_registry.py -q
.venv/bin/python scripts/extract_ontology_candidates.py --dry-run --limit 20 --template-only
.venv/bin/python scripts/ontology_review.py --summary
.venv/bin/python scripts/ontology_review.py --auto-approve-dev --dry-run
```

## Notes

초기 MVP는 보수적으로 동작한다. source evidence에서 신뢰할 수 있는 기존 concept 보강 표현을 찾지 못하면 후보를 생성하지 않는다. LLM 기반 자연화는 batch 옵션과 모델 기동 정책을 준비했으며, 기본 검증 경로는 `--template-only`로 재현 가능하게 유지한다.

DGX dry-run에서 생성되는 후보는 `pending` 후보 preview이며, `--dry-run`에서는 저장하지 않는다. `codex_dev_review.decision=approve`가 붙은 후보만 이후 `--auto-approve-dev` 대상이 될 수 있다.
