# 222. Ontology LLM Enrichment Evaluation Implementation Plan

## 결정 전제

현재 온톨로지 후보 추출의 핵심은 규칙 기반이다. 그러나 다음 작업들은 실제 메인 프로젝트에 적용 가능한 후보 아이디어로 간주하고, Qwen 80B와 Qwen 30B를 비교 평가한다.

- 규칙으로 뽑힌 alias 후보가 문장 조각인지 판단
- 후보 alias가 target concept과 같은 보험 업무 개념인지 판단
- 원문 근거가 후보 개념과 연결되는지 평가
- 실무자에게 보여줄 설명 생성
- 후보 개념이 사용되는 예시 질문 생성
- 너무 넓거나 위험한 표현인지 사유 구조화

평가의 목적은 "LLM이 지금 이미 이 일을 하고 있다"가 아니라, "이 일을 LLM에게 맡기는 설계를 메인 프로젝트에 넣을 가치가 있는지"를 검증하는 것이다.

이 문서는 `docs/221_LLM_MODEL_SUPPORT_AND_EVALUATION_PLAN.md`의 두 평가 목적 중 "온톨로지 후보 개념/alias 검토 보조 모델 선택"에 해당한다. 일반 질의 답변 생성 모델 선택은 별도 평가 축으로 유지한다.

## 전체 테스트 안에서의 역할

전체 LLM 최소화 테스트의 최종 산출물은 두 개다.

1. 질의에 대한 답 생성 모델
   - RAG 답변을 생성할 주력 모델
   - 약관 해석 정확도, 조항/수치 보존, 출처 표기, 응답 안정성 중심
2. 온톨로지 후보 개념 관련 모델
   - alias 정제, evidence 정합성 판단, 실무자 표시 설명/예시 질문 생성을 보조할 batch 모델
   - unsafe approval 방지, 보류/거절 사유 구조화, schema 안정성 중심

이 문서의 평가는 2번만 직접 다룬다. 따라서 이 평가에서 낮은 점수를 받은 모델이라도 답변 생성 평가에서 주력 또는 fallback 역할을 얻으면 삭제하면 안 된다. 반대로 답변 생성 평가에서 낮은 점수를 받은 모델이라도 이 평가에서 온톨로지 batch 역할을 얻으면 삭제하면 안 된다.

## 핵심 원칙

1. 운영 ontology에는 즉시 반영하지 않는다.
2. LLM 출력은 shadow 평가 산출물로 저장한다.
3. 최종 승인/거절/보류 권한은 기존 guardrail과 실무자 승인 workflow에 둔다.
4. 외부 API와 Ollama fallback은 사용하지 않는다.
5. Qwen 80B와 Qwen 30B는 같은 입력, 같은 prompt, 같은 schema로 비교한다.
6. 모델 선택 기준은 답변이 그럴듯한지가 아니라 "실무자 검토 부담을 줄이면서 위험 후보를 잘 막는지"다.
7. 답변 생성 모델 ranking과 온톨로지 enrichment 모델 ranking은 별도로 산출한다.

## 현재 코드상 삽입 지점

현재 후보 생성 흐름:

```text
processed chunks / graph evidence
  -> candidate_extractor.extract_reinforcement_candidates
  -> build_display_metadata
  -> build_codex_dev_review
  -> OntologyCandidate JSONL
  -> practitioner review / auto approval / apply
```

LLM enrichment는 다음 위치에 shadow 단계로 삽입한다.

```text
rules로 만든 draft candidate
  -> LLM enrichment shadow call
  -> schema validation
  -> 기존 rule guardrail과 비교
  -> evaluation report
  -> 운영 candidates.jsonl에는 기본적으로 쓰지 않음
```

`--apply`나 GraphDB rebuild와는 연결하지 않는다.

## 제안 모듈

### 1. `src/ontology/llm_enrichment.py`

역할:

- LLM 입력 payload 구성
- OpenAI-compatible local endpoint 호출
- JSON schema 파싱 및 검증
- 실패 시 안전한 fallback output 생성

주요 함수 후보:

```python
def build_enrichment_input(candidate, *, all_candidates, policy) -> dict:
    ...

def enrich_candidate_with_llm(candidate, client, *, policy, all_candidates) -> dict:
    ...

def validate_enrichment_output(payload: dict) -> tuple[dict, list[str]]:
    ...
```

### 2. `scripts/eval_ontology_llm_enrichment.py`

역할:

- 같은 후보 입력을 여러 모델에 순차 투입
- 모델별 LLM enrichment 결과를 JSONL/Markdown으로 저장
- 기존 guardrail/실무자 리뷰 이력과 비교
- 삭제/보존/고정 판단에 필요한 점수표 생성

출력 위치:

```text
reports/ontology_llm_enrichment_eval/
```

### 3. `scripts/extract_ontology_candidates.py` 확장

후보 옵션:

```bash
--llm-enrichment-mode off|shadow|apply
```

초기 구현은 `off`와 `shadow`만 허용한다.

- `off`: 현재와 동일
- `shadow`: LLM enrichment 결과를 candidate properties에 쓰지 않고 별도 evaluation artifact로 저장
- `apply`: 추후 별도 승인 후만 구현

## LLM 입력 schema

모델에는 사람이 판단할 때 필요한 최소 정보를 준다.

```json
{
  "candidate_id": "dev.cov.manual_therapy.x",
  "candidate_type": "alias_or_expansion",
  "target": {
    "concept_id": "cov.manual_therapy",
    "canonical_name": "도수치료",
    "node_type": "CoverageConcept",
    "known_aliases": ["도수치료", "비급여 도수치료"]
  },
  "candidate_aliases": ["즉 비급여 도수치료"],
  "source_evidence": [
    {
      "doc_short": "약관",
      "page": "38",
      "excerpt": "..."
    }
  ],
  "known_conflicts": [
    {
      "expression": "비급여 주사제",
      "other_concept_id": "cov.nonpay_injection"
    }
  ],
  "review_policy_summary": {
    "reject_sentence_fragments": true,
    "reject_payment_rule_changes": true,
    "reject_broad_terms": true
  }
}
```

## LLM 출력 schema

LLM 출력은 반드시 JSON만 허용한다.

```json
{
  "schema_version": 1,
  "overall_decision": "approve|hold|reject",
  "domain_fit": true,
  "evidence_fit": true,
  "risk_level": "low|medium|high",
  "confidence": 0.0,
  "alias_assessments": [
    {
      "expression": "즉 비급여 도수치료",
      "decision": "reject",
      "reason_codes": ["sentence_fragment"],
      "reason": "문장 접속 표현이 포함된 조각이므로 검색 alias로 부적절합니다.",
      "suggested_rewrite": "비급여 도수치료"
    }
  ],
  "refined_aliases": ["비급여 도수치료"],
  "practitioner_summary": "도수치료 관련 표현 후보입니다. 다만 원문 표현 중 일부는 문장 조각이므로 정제 후 검토가 필요합니다.",
  "example_questions": [
    "도수치료는 실손보험에서 보상되나요?",
    "비급여 도수치료 보상 한도는 어떻게 되나요?"
  ],
  "review_notes": "보상 한도 판단 자체는 ontology alias가 아니라 약관 rule에서 처리해야 합니다."
}
```

허용 reason code:

| code | 의미 |
|---|---|
| `safe_alias` | 같은 개념의 안전한 alias |
| `sentence_fragment` | 문장 조각 또는 조사로 끝나는 표현 |
| `too_broad` | 너무 넓은 표현 |
| `alias_mismatch` | 후보 concept과 다른 개념 |
| `evidence_mismatch` | 원문 근거와 target concept 연결 부정확 |
| `ownership_conflict` | 다른 concept 소유 표현과 충돌 |
| `policy_risk` | 지급/면책/감액/한도 판단으로 이어질 위험 |
| `needs_more_evidence` | 근거 부족 |
| `schema_uncertain` | 판단 불확실 또는 출력 불완전 |

## Prompt 정책

Prompt는 보수적으로 작성한다.

필수 지시:

- 보험금 지급, 면책, 감액, 한도 계산 rule을 새로 만들지 말 것
- alias 후보는 검색 보강 표현으로만 판단할 것
- target concept과 다른 개념이면 approve 금지
- evidence가 어긋나면 hold 또는 reject
- 문장 조각, 조사로 끝나는 표현, 접속 표현은 reject 또는 rewrite
- JSON 외 텍스트 출력 금지

## 평가 대상 모델

1. `sglang:qwen3-next-80b-a3b-instruct-fp8`
2. `sglang:qwen3-30b-a3b-instruct-2507-fp8`
3. `sglang:gpt-oss-20b`

비교 목표:

- Qwen 30B가 80B와 동등하면 30B를 기본 온톨로지 batch 모델로 고정한다.
- 80B가 evidence alignment와 unsafe approval 방지에서 명확히 우수하면 80B를 비지속 batch 전용 모델로 유지한다.
- GPT-OSS 20B는 fallback baseline으로만 평가한다.

## 평가 데이터 구성

### A. 실제 후보 재생

기존 규칙 기반 추출 결과를 고정 입력으로 쓴다.

```bash
.venv/bin/python scripts/extract_ontology_candidates.py \
  --dry-run \
  --limit 100 \
  --template-only > /tmp/ontology_rule_candidates.json
```

이 JSON의 후보들을 모든 모델에 동일하게 투입한다.

### B. 실무자 리뷰 이력 기반 gold seed

현재 review store의 이력을 사용한다.

- `applied`: approve에 가까운 positive seed
- `held`: 보류 사유 분류 검증 seed
- `rejected`: unsafe approval 방지 negative seed

모델은 최소한 다음을 만족해야 한다.

- 기존 rejected 후보를 approve하지 않을 것
- 기존 held 후보를 무리하게 approve하지 않을 것
- existing applied 후보의 safe alias를 과도하게 reject하지 않을 것

### C. 합성 edge case

운영 데이터에서 흔히 나오는 결함을 별도 fixture로 만든다.

예시:

- `진단서를`, `위한 진단서`: sentence fragment
- `보험금 지급여부`: policy risk / too broad
- `보장성보험`: too broad
- `비급여 주사제`: ownership conflict 가능
- evidence는 자동차보험인데 target은 실손인 경우: evidence mismatch

## 평가 지표

| 지표 | 합격 기준 |
|---|---|
| JSON parse success | 98% 이상 |
| schema validity | 98% 이상 |
| unsafe approval count | 0건 |
| rejected-as-approve rate | 0% |
| held-as-approve rate | 매우 낮을 것 |
| applied retention | applied 후보의 핵심 safe alias를 과도하게 잃지 않을 것 |
| sentence fragment rejection | 95% 이상 |
| evidence mismatch detection | 90% 이상 |
| ownership conflict detection | 90% 이상 |
| example question usability | 실무자 샘플 점검에서 80% 이상 유용 |
| latency | batch 작업으로 허용 가능하되 실패/timeout 빈도 기록 |

최종 선택은 다음 순서로 판단한다.

1. unsafe approval이 있는 모델은 탈락
2. JSON/schema 안정성이 낮은 모델은 탈락
3. evidence mismatch와 ownership conflict 탐지가 낮은 모델은 탈락
4. 남은 모델 중 Qwen 30B가 80B와 큰 차이가 없으면 30B를 기본으로 선택
5. 80B가 명확히 우수하면 80B를 온톨로지 batch 전용으로 유지

이 순위는 온톨로지 enrichment 전용 순위다. 답변 생성 모델 최종 순위와 충돌할 경우에는 `docs/221...`의 decision matrix에서 역할을 분리해 기록한다.

## 구현 단계

### Phase 1. Shadow evaluator만 구현

목표:

- 운영 후보 저장 파일을 바꾸지 않고 모델 비교만 가능하게 한다.

작업:

1. `src/ontology/llm_enrichment.py` 추가
2. JSON schema validator 추가
3. fake client 기반 unit test 추가
4. `scripts/eval_ontology_llm_enrichment.py` 추가
5. reports JSONL/Markdown writer 추가

검증:

```bash
.venv/bin/python -m pytest tests/test_ontology_llm_enrichment.py -q
.venv/bin/python scripts/eval_ontology_llm_enrichment.py \
  --input /tmp/ontology_rule_candidates.json \
  --models qwen3-30b-a3b-instruct-2507-fp8 \
  --limit 5 \
  --dry-run
```

### Phase 2. DGX 실제 모델 비교

목표:

- Qwen 80B/30B를 같은 후보 입력으로 비교한다.

실행 예:

```bash
.venv/bin/python scripts/eval_ontology_llm_enrichment.py \
  --input /tmp/ontology_rule_candidates.json \
  --models qwen3-next-80b-a3b-instruct-fp8,qwen3-30b-a3b-instruct-2507-fp8,gpt-oss-20b \
  --start-llm \
  --stop-llm-after \
  --limit 100
```

산출물:

```text
reports/ontology_llm_enrichment_eval/<timestamp>.jsonl
reports/ontology_llm_enrichment_eval/<timestamp>.md
```

### Phase 3. Extractor shadow option 연결

목표:

- 후보 추출 직후 shadow enrichment 평가를 붙일 수 있게 한다.

옵션:

```bash
scripts/extract_ontology_candidates.py \
  --llm auto \
  --model qwen3-30b-a3b-instruct-2507-fp8 \
  --llm-enrichment-mode shadow \
  --start-llm \
  --stop-llm-after
```

`shadow` 모드는 `data/ontology/review/candidates.jsonl`을 바꾸지 않고 report만 남긴다.

### Phase 4. 운영 반영 여부 결정

운영 반영은 별도 승인 후만 진행한다.

반영 후보:

- `display.summary`
- `display.example_questions`
- `properties.llm_enrichment.alias_assessments`
- `properties.llm_enrichment.reason_codes`

반영 금지:

- LLM 단독 approve
- LLM 단독 candidate_aliases 추가
- LLM 단독 `concepts.active.json` 수정
- LLM 단독 GraphDB rebuild

## 예상 결론 기준

Qwen 30B를 고정하는 경우:

- Qwen 80B 대비 unsafe approval이 증가하지 않음
- JSON/schema 안정성 동등
- example question/summary 품질이 실무자 검토에 충분
- batch 시간과 메모리 부담이 낮음

Qwen 80B를 유지하는 경우:

- Qwen 30B가 evidence mismatch나 ownership conflict를 놓침
- Qwen 80B가 보류/거절 사유를 더 안정적으로 구조화함
- 실무자 검토 부담 감소가 명확함

GPT-OSS 20B를 fallback으로 두는 경우:

- Qwen 계열 기동 실패 시에도 JSON은 안정적으로 생성
- 다만 ontology 고정 모델로는 Qwen 대비 품질 열세가 확인될 가능성이 높음

## 통합 decision matrix 연동

이 평가의 Markdown report는 각 모델에 대해 다음 필드를 산출해야 한다.

```json
{
  "model": "qwen3-next-80b-a3b-instruct-fp8",
  "ontology_role": "primary|fallback|reserved|none",
  "ontology_score_summary": {
    "json_validity": 0.99,
    "unsafe_approval_count": 0,
    "evidence_mismatch_detection": 0.92,
    "ownership_conflict_detection": 0.91
  },
  "delete_blocker": "ontology_role=primary"
}
```

`delete_blocker`는 답변 생성 평가와 통합할 때 사용한다. 온톨로지 평가에서 `primary`, `fallback`, `reserved` 중 하나라도 부여된 모델은 답변 생성 평가 결과와 무관하게 즉시 삭제하지 않는다.

## 안전장치

- LLM output은 항상 schema validator를 통과해야 한다.
- schema 실패 시 `overall_decision=hold`, `risk_level=high`, `reason_codes=["schema_uncertain"]`으로 대체한다.
- 기존 deterministic guardrail이 LLM보다 우선한다.
- 실무자 승인 전에는 active ontology와 GraphDB에 반영하지 않는다.
- 평가 중에는 한 번에 한 모델만 기동한다.
