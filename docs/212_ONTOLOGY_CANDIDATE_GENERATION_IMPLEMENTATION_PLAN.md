# 212. Ontology Candidate Generation Implementation Plan

작성일: 2026-06-10

## 1. 목적

승인 기반 온톨로지 workflow의 다음 단계로, 원천 데이터와 개발 중 변경된 DB/GraphDB 로직에서 운영 반영 전 후보를 자동 생성한다.

이 기능은 운영 온톨로지를 직접 수정하지 않는다. 후보 생성기는 `data/ontology/review/candidates.jsonl`에 `pending` 후보를 만들고, 기존 승인 workflow가 실무자 승인 또는 개발용 Codex 자동 승인을 통해 `data/ontology/concepts.active.json`과 GraphDB rebuild로 이어지게 한다.

## 2. 범위

이번 구현 범위는 Phase 5의 1차 MVP다.

포함:

- 기존 개념 보강 후보 생성
  - alias 추가
  - `candidate_aliases` 추가
  - retrieval expansion term 추가
  - evidence tag 보강
- 실무자 표시용 요약 생성
  - 후보 개념 대표명
  - 부연설명
  - 유사 표현
  - 예시 질문
  - 원문 근거
- 개발용 Codex 자동 승인 metadata 생성
- raw 데이터셋 변경 시 수동 실행하는 비지속적 batch CLI

제외:

- 운영 실무자 승인 대체
- 신규 지급/면책/감액 rule 자동 승인
- 보험금 계산 rule 자동 변경
- 상시 실행 daemon
- Ollama fallback
- 외부 API 호출

## 3. 전체 흐름

```text
raw data / processed chunks / GraphDB evidence / standard-code DB / eval failure logs
-> 후보 용어 추출
-> 기존 ontology manifest와 정규화 비교
-> 후보 타입 분류
-> source_evidence 연결
-> 유사 표현 수집
-> 실무자 표시용 summary/example questions 생성
-> risk/review metadata 생성
-> 중복/충돌 제거
-> candidates.jsonl에 pending 후보 저장
-> 실무자 승인 UI 또는 개발용 Codex 자동 승인
-> approved 후보만 active manifest 병합
-> GraphDB rebuild
```

## 4. 후보 객체 형태

후보는 자유 텍스트가 아니라 `OntologyCandidate` schema를 따르는 구조화 객체다.

필수 필드:

- `candidate_id`
- `concept_id`
- `canonical_name`
- `node_type`
- `aliases`
- `candidate_aliases`
- `evidence_tags`
- `planner`
- `retrieval`
- `properties`
- `source_evidence`
- `status`
- `risk_flags`
- `test_candidate`
- `created_at`
- `extraction_run_id`

실무자 표시용 metadata는 `properties.display`에 둔다.

```json
{
  "properties": {
    "candidate_type": "alias_or_expansion",
    "display": {
      "summary": "교통수단 이용 중 발생한 상해를 묶어 검색하기 위한 개념입니다.",
      "similar_expressions": ["교통상해", "자동차 사고", "차량 탑승 중 사고"],
      "example_questions": [
        "교통사고로 입원했을 때 상해입원일당을 받을 수 있나요?",
        "오토바이 사고도 교통상해에 포함되나요?"
      ],
      "approval_prompt": "위 표현들을 같은 보험 업무 개념으로 묶어도 될까요?"
    }
  }
}
```

개발용 Codex 자동 승인 metadata는 `properties.codex_dev_review`에 둔다.

```json
{
  "properties": {
    "codex_dev_review": {
      "decision": "approve",
      "development_only": true,
      "domain_fit": true,
      "evidence_fit": true,
      "risk_level": "low",
      "reason": "기존 보상 조건 concept의 검색 확장 후보이며 지급 판단 rule을 변경하지 않습니다."
    }
  }
}
```

## 5. 실무자 표시 정책

승인 UI는 내부 metadata를 그대로 노출하지 않는다. 기본 화면은 다음 항목만 보여준다.

- 후보 개념
- 설명
- 유사 표현
- 예시 질문
- 원문 근거
- 주의 표시
- 승인 / 보류 / 거절 버튼

권장 표시 예:

```text
후보 개념: 교통사고 상해

설명:
자동차, 오토바이, 대중교통 등 교통수단 이용 중 발생한 상해를 묶어 검색하기 위한 개념입니다.

유사 표현:
교통상해, 자동차 사고, 차량 탑승 중 사고

예시 질문:
- 교통사고로 입원했을 때 상해입원일당을 받을 수 있나요?
- 오토바이 사고도 교통상해에 포함되나요?

원문 근거:
[약관명 / 12쪽]
"...교통사고로 인한 상해..."
```

상세 보기에서만 `concept_id`, `node_type`, `planner`, `retrieval`, `risk_flags`, `codex_dev_review`를 보여준다.

## 6. 후보 추출 소스

1차 MVP 우선순위:

1. `data/processed/*.jsonl`
2. `data/index/graph/insurance_graph.sqlite`
3. `data/index/relational/standard_codes.sqlite`
4. 평가 실패 로그 또는 검색 실패 질의

초기 구현은 `data/processed`와 GraphDB evidence를 우선 사용한다. 표준코드 DB와 평가 실패 로그는 후보 품질 검증 후 확장한다.

## 7. 후보 용어 추출 원리

규칙 기반 추출을 먼저 수행한다.

- 보험 도메인 키워드 주변 명사구 추출
- 괄호, 슬래시, 쉼표, 나열 표현 분리
- 같은 chunk 안 동시 출현 표현 수집
- 반복 출현 빈도 계산
- 기존 ontology의 `canonical_name`, `aliases`, `candidate_aliases`, retrieval expansion과 정규화 비교
- 기존 concept에 붙일 보강 후보인지 신규 후보인지 분류

보험 도메인 키워드 예:

```text
상해, 질병, 진단, 수술, 입원, 통원, 치료
담보, 특약, 보장, 면책, 부지급, 감액
비급여, 급여, 본인부담, 표준코드, EDI
교통사고, 운전자, 자동차, 오토바이
```

정규화 규칙:

- 앞뒤 공백 제거
- 중복 공백 제거
- 괄호 안 보조 표현 분리
- 구두점 일부 제거
- 한글/영문 대소문자 단순화
- 너무 짧거나 일반적인 표현 제외

## 8. 후보 타입과 위험도

자동 승인 가능성이 높은 저위험 후보:

- `alias_or_expansion`
- `evidence_tag`
- `display_only_summary`
- `search_query_expansion`

실무자 검토가 필요한 중위험 후보:

- `new_claim_condition`
- `new_disease_or_procedure`
- `new_required_document`

자동 승인 금지 고위험 후보:

- `exclusion_rule`
- `payment_logic`
- `deductible_rule`
- `benefit_limit`
- `coordination_rule`
- `coverage_decision_edge`

개발용 Codex 자동 승인 대상은 기본적으로 `alias_or_expansion`, `evidence_tag`, `search_query_expansion`에 한정한다.

## 9. 유사 표현 생성 방식

유사 표현은 LLM이 임의 발명하지 않고, 수집된 후보 표현을 정리하는 방식으로 생성한다.

1. 원문 기반 수집
   - 괄호 표현
   - 슬래시 표현
   - 쉼표/나열 표현
   - 같은 chunk 안 반복 동시 출현

2. 기존 ontology 기반 수집
   - 같은 concept의 기존 aliases
   - 같은 node_type의 유사 concept
   - 기존 retrieval expansion terms

3. 검색 기반 수집
   - 후보 대표명으로 BM25/Chroma/GraphDB evidence 조회
   - 상위 근거 chunk에서 반복되는 표현 추출

4. LLM 정리
   - 중복 제거
   - 표현을 실무자에게 자연스럽게 표시
   - 원문 근거에 없는 새 보장 판단은 추가하지 않음

## 10. 예시 질문 생성 방식

예시 질문은 template 기반으로 먼저 생성하고, LLM은 문장 자연화와 중복 제거에만 사용한다.

템플릿:

```text
ClaimCondition:
- "{개념명}에 해당하면 보험금을 받을 수 있나요?"
- "{유사표현}도 {개념명}에 포함되나요?"

Disease:
- "{질병명} 진단을 받으면 어떤 담보를 확인해야 하나요?"

Procedure:
- "{수술/처치명}은 수술비 보장 대상인가요?"

RequiredDocument:
- "{개념명} 청구에는 어떤 서류가 필요한가요?"

ExclusionReason:
- "{개념명}이면 보장이 제한될 수 있나요?"
```

고위험 타입의 예시 질문은 자동 승인 metadata를 만들지 않고 실무자 검토 대상으로만 생성한다.

## 11. DGX Batch LLM 정책

온톨로지 후보 추출은 raw 데이터셋 변경 시 실행하는 비지속적 batch 작업이다. 실행 시간이 길어도 괜찮으므로, 현재 떠 있는 endpoint에 의존하지 않고 작업에 적합한 DGX 로컬 모델을 명시적으로 기동할 수 있게 한다.

원칙:

- 외부 API 호출 금지
- Ollama fallback 사용 금지
- DGX 로컬 SGLang/vLLM 모델만 사용
- 필요한 경우 batch 시작 시 LLM 서버 기동
- 작업 후 서버 종료 여부는 옵션으로 제어
- LLM 기동 실패 또는 `--template-only`인 경우 template-only 후보 생성으로 degrade

모델 우선순위:

1. `qwen3-next-80b-a3b-instruct-fp8`
2. `qwen3-30b-a3b-instruct-2507-fp8`
3. `gpt-oss-20b`

기본값은 `qwen3-next-80b-a3b-instruct-fp8`이다.

제외:

- `gpt-oss-120b`: DGX Spark 메모리 부족 이력 때문에 기본 후보에서 제외
- Ollama GGUF fallback: 후보 추출 batch 정책에서 제외
- thinking/reasoning 계열 모델: JSON 구조화 산출 안정성 관점에서 기본값으로 제외

## 12. LLM 입출력 정책

LLM 입력:

- 후보 대표명
- 후보 타입
- 유사 표현 후보 목록
- 원문 excerpt 1~3개
- 기존 concept 요약
- 금지사항

LLM 출력은 JSON schema로 강제한다.

```json
{
  "summary": "string",
  "similar_expressions": ["string"],
  "example_questions": ["string"],
  "codex_dev_review": {
    "decision": "approve|hold|reject",
    "development_only": true,
    "domain_fit": true,
    "evidence_fit": true,
    "risk_level": "low|dev_only|medium|high",
    "reason": "string"
  }
}
```

후처리 검증:

- JSON parse 실패 시 template-only fallback
- source evidence가 없으면 자동 승인 metadata 제거
- high/medium risk면 자동 승인 metadata 제거
- 기존 alias 충돌 시 `held` 또는 실무자 검토 대상으로 분류
- LLM이 원문 근거에 없는 지급 판단을 만들면 해당 문장 제거 또는 후보 제외

## 13. CLI 설계

신규 스크립트:

```text
scripts/extract_ontology_candidates.py
```

주요 옵션:

```text
--source data/processed/chunks_canonical_manifest.jsonl
--output data/ontology/review/candidates.jsonl
--dry-run
--limit 100
--candidate-type alias_or_expansion
--template-only
--llm auto|none|sglang|vllm
--model qwen3-next-80b-a3b-instruct-fp8
--start-llm
--stop-llm-after
--llm-base-url http://127.0.0.1:30000/v1
--max-llm-candidates 100
--llm-timeout 120
--replace-existing
```

예상 실행:

```bash
.venv/bin/python scripts/extract_ontology_candidates.py \
  --source data/processed/chunks_canonical_manifest.jsonl \
  --output data/ontology/review/candidates.jsonl \
  --llm auto \
  --model qwen3-next-80b-a3b-instruct-fp8 \
  --start-llm \
  --stop-llm-after \
  --limit 100
```

후속 승인:

```bash
.venv/bin/python scripts/ontology_review.py --summary
.venv/bin/python scripts/ontology_review.py --auto-approve-dev --dry-run
ENABLE_ONTOLOGY_DEV_AUTO_APPROVAL=true /srv/ai-ops/bin/insurance-rag-ontology-review-gui
```

## 14. 구현 파일 계획

신규:

- `src/ontology/candidate_extractor.py`
- `src/ontology/candidate_display.py`
- `src/ontology/candidate_reviewer.py`
- `src/ontology/llm_batch.py`
- `scripts/extract_ontology_candidates.py`
- `tests/test_ontology_candidate_extractor.py`
- `tests/test_ontology_candidate_display.py`
- `tests/test_ontology_candidate_reviewer.py`

수정:

- `src/ontology/review_store.py`
  - display metadata validation helper 추가 가능
- `scripts/ontology_review.py`
  - 후보 상세 표시 시 `properties.display` 우선 표시
- `ops/bin/insurance-rag-ontology-review-gui`
  - 실무자용 표시 형식 적용

## 15. 검증 계획

단위 테스트:

```bash
.venv/bin/python -m pytest tests/test_ontology_candidate_extractor.py -q
.venv/bin/python -m pytest tests/test_ontology_candidate_display.py -q
.venv/bin/python -m pytest tests/test_ontology_candidate_reviewer.py -q
.venv/bin/python -m pytest tests/test_ontology_review_store.py tests/test_ontology_manifest_merge.py tests/test_ontology_registry.py -q
```

CLI 검증:

```bash
.venv/bin/python scripts/extract_ontology_candidates.py --dry-run --limit 20 --template-only
.venv/bin/python scripts/extract_ontology_candidates.py --dry-run --limit 20 --llm auto --model qwen3-next-80b-a3b-instruct-fp8 --start-llm --stop-llm-after
.venv/bin/python scripts/ontology_review.py --summary
.venv/bin/python scripts/ontology_review.py --auto-approve-dev --dry-run
```

통합 검증:

```bash
.venv/bin/python scripts/ontology_review.py --apply --rebuild-graph --dry-run
.venv/bin/python scripts/check_ontology_sync.py
```

GUI 검증:

```bash
bash -n ops/bin/insurance-rag-ontology-review-gui
/srv/ai-ops/bin/insurance-rag-ontology-review-gui --dry-run
```

## 16. 이상 여부 점검

점검 결과:

- 승인 후보는 구조화 객체로 유지하고, 실무자 UI는 사람이 이해 가능한 표시용 metadata만 우선 보여준다.
- 후보 생성은 운영 manifest를 직접 수정하지 않고 `pending` 후보 저장소만 갱신한다.
- 개발 자동 승인은 별도 `codex_dev_review` metadata와 risk flag가 있는 후보만 대상으로 한다.
- 운영 지급 판단, 면책, 감액, 계산 rule은 자동 승인 대상에서 제외한다.
- LLM은 batch 작업에만 사용하고, 외부 API와 Ollama fallback은 사용하지 않는다.
- 기본 batch 모델은 사용자의 요청대로 `qwen3-next-80b-a3b-instruct-fp8`이다.
- LLM 결과는 JSON schema와 deterministic guardrail로 검증한다.
- LLM 서버 기동 실패 시 template-only로 degrade할 수 있어 개발 흐름이 막히지 않는다.

남은 주의점:

- 실제 후보 추출 품질은 원천 chunk 품질과 GraphDB evidence 연결 품질에 의존한다.
- `qwen3-next-80b-a3b-instruct-fp8` 기동 시간이 길 수 있으므로 progress log와 timeout을 명확히 남겨야 한다.
- 초기 MVP는 alias/검색 확장 후보에 한정하고, 신규 판단 concept은 이후 단계로 분리해야 한다.

## 17. 구현 목표 설정 프롬프트

```text
목표: DGX 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot` 기준으로 승인 기반 온톨로지 후보 생성 파이프라인 Phase 5 MVP를 구현합니다. 우선 `docs/201_ONTOLOGY_PRACTITIONER_APPROVAL_WORKFLOW_PLAN.md`, `docs/202_ONTOLOGY_PRACTITIONER_APPROVAL_WORKFLOW_IMPL_REPORT.md`, `docs/211_ONTOLOGY_DEV_AUTO_APPROVAL_REPORT.md`, `docs/212_ONTOLOGY_CANDIDATE_GENERATION_IMPLEMENTATION_PLAN.md`를 읽고, 이번 작업 범위를 기존 개념 보강 후보(alias/candidate_aliases/retrieval expansion/evidence tag) 생성으로 제한하세요.

필수 요구사항:
1. `scripts/extract_ontology_candidates.py` CLI를 추가해 raw/processed chunk와 GraphDB evidence에서 pending ontology 후보를 생성하세요.
2. 후보는 `OntologyCandidate` schema를 따르고, `data/ontology/review/candidates.jsonl`에 저장되며, 운영 manifest를 직접 수정하면 안 됩니다.
3. 실무자 UI용 `properties.display.summary`, `similar_expressions`, `example_questions`, `approval_prompt`를 생성하세요.
4. 유사 표현은 원문, 기존 ontology, 검색 evidence에서 수집한 표현만 정리하고, LLM이 근거 없는 새 보장 판단을 만들지 못하게 하세요.
5. 예시 질문은 node_type/candidate_type별 template으로 먼저 생성하고, LLM은 문장 자연화와 중복 제거에만 사용하세요.
6. DGX batch LLM 정책은 외부 API와 Ollama fallback을 사용하지 않습니다. 기본 모델 우선순위는 `qwen3-next-80b-a3b-instruct-fp8` -> `qwen3-30b-a3b-instruct-2507-fp8` -> `gpt-oss-20b`입니다.
7. 후보 추출은 비지속적 batch 작업이므로, `--start-llm`, `--stop-llm-after`, `--model`, `--llm auto|none|sglang|vllm`, `--template-only` 옵션을 설계하세요.
8. 개발 자동 승인 대상은 `alias_or_expansion`, `evidence_tag`, `search_query_expansion` 같은 저위험 후보로 제한하고, 지급/면책/감액/계산 rule 후보에는 `codex_dev_review.decision=approve`를 붙이지 마세요.
9. `scripts/ontology_review.py --show`와 `ops/bin/insurance-rag-ontology-review-gui`는 `properties.display`를 우선 표시하도록 개선하세요.
10. 구현 완료 후 `docs/`에 간결한 구현 보고서를 추가하고, 관련 테스트와 DGX dry-run 검증을 수행하세요.

검증 명령:
- `bash -n ops/bin/insurance-rag-ontology-review-gui ops/bin/insurance-rag-desktop-launcher`
- `.venv/bin/python -m py_compile src/ontology/*.py scripts/extract_ontology_candidates.py scripts/ontology_review.py`
- `.venv/bin/python -m pytest tests/test_ontology_candidate_extractor.py tests/test_ontology_candidate_display.py tests/test_ontology_candidate_reviewer.py tests/test_ontology_review_store.py tests/test_ontology_manifest_merge.py tests/test_ontology_registry.py -q`
- `.venv/bin/python scripts/extract_ontology_candidates.py --dry-run --limit 20 --template-only`
- `.venv/bin/python scripts/ontology_review.py --summary`
- `.venv/bin/python scripts/ontology_review.py --auto-approve-dev --dry-run`

금지사항:
- 운영 manifest `data/ontology/concepts.json` 직접 수정 금지
- 운영 후보 전체 자동 승인 금지
- 외부 API 호출 금지
- Ollama fallback 사용 금지
- 지급/면책/감액/보험금 계산 rule 자동 승인 금지
- 사용자 승인 없는 git push 금지
```
