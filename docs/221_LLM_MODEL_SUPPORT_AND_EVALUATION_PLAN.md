# 221. LLM Model Support Hardening and Evaluation Plan

## 목적

DGX에 존재하는 LLM 파일을 모두 앱 후보로 취급하지 않고, 실제 앱 코드와 전환 스크립트가 지원하는 모델만 노출한다. 이후 기능별 평가를 통해 답변 생성 LLM과 온톨로지 후보 추출 LLM을 최소한으로 고정한다.

## 지원 모델 목록 고정 패치

변경 원칙:

- SGLang 후보는 `SGLANG_MODEL_INFO` allowlist 안의 모델만 허용한다.
- vLLM 후보는 `LOCAL_LARGE_MODEL_INFO` allowlist 안의 모델만 허용한다.
- `/srv/ai-ops/llm/models`에 디렉터리가 있다는 이유만으로 SGLang 후보에 자동 편입하지 않는다.
- live endpoint가 allowlist 밖 모델을 `/models`에 광고해도 앱 모델 목록과 런타임 목록에 노출하지 않는다.
- 직접 `build_llm(..., provider=...)`를 호출해도 provider와 모델 조합이 지원되지 않으면 즉시 거절한다.

현재 코드 기준 provider별 지원 목록:

| provider | 지원 모델 | 상태 |
|---|---|---|
| SGLang | `gpt-oss-20b` | 검증완료 baseline |
| SGLang | `gpt-oss-120b` | 검증대상, 메모리 부족 이력 |
| SGLang | `qwen3-30b-a3b-instruct-2507-fp8` | 검증대상, 온톨로지 후보 추출 비교 |
| SGLang | `qwen3-next-80b-a3b-instruct-fp8` | 검증대상, 온톨로지 후보 추출 비교 |
| SGLang | `qwen3-next-80b-a3b-thinking-fp8` | 검증대상, reasoning 비교 |
| SGLang | `nemotron-3-nano-30b-a3b-nvfp4` | 비활성, SGLang 기본 후보 제외 |
| vLLM | `gemma-4-26b-a4b-nvfp4` | 삭제검토, 31B 대체 가능성 평가 |
| vLLM | `gemma-4-31b-it-nvfp4` | 검증대상, Gemma4/이미지 인식 후보 |
| vLLM | `nemotron-3-nano-30b-a3b-nvfp4` | 검증대상, 삭제 가능성 평가 |
| vLLM | `exaone-4.0-32b-awq` | 검증대상, 한국어 비교/삭제 가능성 평가 |
| Ollama | `exaone3.5:7.8b` | 경량 fallback |
| Ollama | `llama-3.3-70b-instruct-q4-k-m` | 대형 fallback, 중복성 평가 |

삭제 금지 원칙:

- `qwen3-next-80b-a3b-instruct-fp8`와 `qwen3-30b-a3b-instruct-2507-fp8`는 온톨로지 후보 추출 비교가 끝날 때까지 삭제하지 않는다.
- `gemma-4-31b-it-nvfp4`는 이미지 인식 후보 기능 검토가 끝날 때까지 삭제하지 않는다.
- `gemma-4-26b-a4b-nvfp4`는 31B가 대체 가능하다는 전제로 삭제 후보에 둔다. 단, vLLM 31B 품질/기동성이 확인되기 전에는 제거하지 않는다.

## 답변 생성 LLM 평가 설계

### 평가 목적

일반 질의에서 보험 약관 근거를 정확히 찾아 요약하고, 약관 조항과 조건을 왜곡하지 않는 모델을 1개 주력 답변 모델로 고정한다. 필요하면 경량 fallback 1개만 별도 유지한다.

### 평가셋

기본 평가셋은 첨부 엑셀 `/Users/june_kim/Downloads/실손약관_챗봇_품질점검_평가셋 (1).xlsx`를 사용한다.

확인된 구조:

- 시트: `챗봇 품질점검 평가셋`
- 실제 문항: 40개
- 컬럼: `번호`, `분류`, `질문`, `참조 조문`, `핵심 정답 (채점 기준)`, `챗봇 답변 (기록란)`, `평가`, `비고`
- 대상 문서: `신한 이지로운 실손의료보험(무배당)` 2026년 4월 적용 약관

문항 분포:

| 분류 | 문항 수 |
|---|---:|
| 계약 전·후 알릴의무 | 5 |
| 계약 성립·철회·무효 | 5 |
| 보험료 납입·연체·부활 | 4 |
| 보험금 지급·청구 | 3 |
| 보상하는/하지 않는 사항 | 3 |
| 비급여 실손의료비 특약 | 8 |
| 다수보험 처리 | 2 |
| 해지·해약환급금 | 3 |
| 갱신·재가입 | 2 |
| 분쟁·약관해석 | 2 |
| 제도성 특별약관 | 3 |

### 평가 데이터 변환

엑셀을 직접 커밋하지 않고, 실행 시 변환하거나 파생 JSONL을 생성한다.

권장 JSONL schema:

```json
{
  "id": "policy_xlsx_001",
  "category": "계약 전·후 알릴의무",
  "question": "계약자가 계약 전 알릴의무(고지의무)를 위반했을 때 보험회사가 할 수 있는 조치는?",
  "doc_sources": ["약관"],
  "reference_clause": "보통약관 제16조",
  "expected_answer": "보험금 지급사유 발생 여부와 관계없이 ...",
  "required_terms": ["계약 전 알릴의무", "1개월", "계약 해지"],
  "required_numbers": ["1개월"],
  "required_clause_terms": ["제16조"]
}
```

`required_terms`는 최초에는 자동 추출하되, 최종 고정 전에는 사람이 한 번 보정한다. 숫자, 기간, 조항, 지급/면책/해지/부활 같은 법적 효과는 반드시 별도 필드로 분리한다.

### 평가 방식

두 단계로 분리한다.

1. 검색 고정 평가
   - 동일 질의에 대해 검색 top-k와 출처가 같은지 확인한다.
   - `doc_filter=["약관"]`를 적용하여 실손약관 평가셋이 다른 문서로 새지 않게 한다.
   - 실패 항목은 모델 문제가 아니라 retrieval/index 문제로 분리한다.

2. 답변 생성 평가
   - 동일 검색 context를 고정한 뒤 모델별 답변만 비교한다.
   - 체크 항목:
     - 참조 조문 또는 동등 조항 언급
     - 핵심 정답의 조건, 예외, 기간, 수치 포함
     - 지급/면책/해지/부활 같은 법적 효과의 반대 표현 없음
     - `[출처:` 표기 유지
     - 근거 없는 일반론 또는 약관 밖 설명 없음
     - 빈 응답, `<pad>` 반복, 과도한 반복 없음

자동 점수는 `pass`, `partial`, `fail` 3단계로 둔다.

- `pass`: 필수 조항/조건/수치가 모두 맞고 금지 표현 없음
- `partial`: 방향은 맞지만 조건, 예외, 기간 중 일부 누락
- `fail`: 조항 오인, 반대 결론, 근거 없는 확정, 출력 형식 붕괴

### 답변 생성 후보 모델

우선순위:

1. `sglang:gpt-oss-20b` - 현재 baseline
2. `sglang:qwen3-30b-a3b-instruct-2507-fp8`
3. `sglang:qwen3-next-80b-a3b-instruct-fp8`
4. `vllm:gemma-4-31b-it-nvfp4`
5. `vllm:gemma-4-26b-a4b-nvfp4` - 삭제 후보 검증
6. `vllm:exaone-4.0-32b-awq` - 한국어 비교, 삭제 후보 검증
7. `vllm:nemotron-3-nano-30b-a3b-nvfp4` - 삭제 후보 검증

후순위:

- `sglang:gpt-oss-120b`: 기동 실패 또는 메모리 부족이 재현되면 삭제 후보로 분류한다.
- `ollama:llama-3.3-70b-instruct-q4-k-m`: Ollama 대형 fallback을 유지할 실익이 없으면 삭제 후보로 분류한다.

고정 기준:

- 40문항 기준 pass 비율 85% 이상
- 치명 실패율 5% 이하
- 조항/기간/수치 오류 0건에 가까울 것
- 평균 지연과 기동 시간을 운영 가능한 범위로 유지
- 31B Gemma4가 26B Gemma4와 동급 이상이면 26B는 삭제 후보 확정

## 온톨로지 후보 추출 LLM 평가 설계

### 현재 전제

현재 `scripts/extract_ontology_candidates.py`의 `--llm`, `--model`, `--start-llm` 옵션은 batch LLM 서버 기동 정책을 갖고 있지만, 후보 생성 핵심 로직은 규칙 기반 추출과 template/display metadata 중심이다. 따라서 지금 상태 그대로 Qwen 80B와 Qwen 30B를 비교하면 모델별 품질 차이를 측정할 수 없다.

모델 고정을 위해서는 먼저 LLM이 실제로 영향을 주는 단계를 명확히 추가해야 한다.

권장 추가 단계:

- 후보 alias 정제
- 후보 설명 생성
- 예시 질문 생성
- evidence와 target concept 정합성 판정 보조
- JSON schema 기반 품질 태깅

이 단계는 `src/ontology/llm_batch.py`의 모델 기동 정책과 연결하되, 최종 승인/차단은 기존 guardrail과 실무자 승인 정책이 계속 담당한다.

### 온톨로지 평가 후보 모델

1. `sglang:qwen3-next-80b-a3b-instruct-fp8`
2. `sglang:qwen3-30b-a3b-instruct-2507-fp8`
3. `sglang:gpt-oss-20b` - fallback baseline

`Ollama`는 온톨로지 후보 추출 batch 정책에서 제외한다.

### 평가셋

세 종류의 고정 입력을 사용한다.

1. 실제 raw/processed corpus slice
   - `data/processed/chunks_canonical_manifest.jsonl`
   - `data/index/graph/insurance_graph.sqlite`의 `graph_evidence`
   - `--source-limit`와 `--limit`를 고정

2. 기존 실무자 검토 이력
   - `applied` 후보: 좋은 alias/개념 연결의 positive seed
   - `held` 후보: evidence mismatch, too broad, needs more evidence 등 보류 사유 seed
   - `rejected` 후보: 문장 조각, 중복, 소유권 충돌, 정책 위험 negative seed

3. 합성 edge case
   - 조사로 끝나는 표현
   - 너무 넓은 표현
   - 지급/면책/감액/한도 판단 표현
   - 여러 concept에 걸친 multi-owner alias
   - 같은 표현이 evidence 문맥에서는 맞지만 target concept이 틀린 경우

### 평가 지표

| 지표 | 의미 |
|---|---|
| JSON validity | schema 파싱 성공률 |
| alias precision | 승인 가능한 alias 비율 |
| fragment rate | 문장 조각/조사 끝 표현 비율 |
| evidence alignment | 원문 근거와 target concept 정합성 |
| ownership conflict rate | 같은 alias가 여러 concept에 잘못 붙는 비율 |
| guardrail rejection rate | guardrail이 차단한 비율과 사유 |
| useful candidate count | 실무자가 실제 승인 가능한 후보 수 |
| review burden | 사람이 읽고 판단해야 하는 후보 수 |
| latency/cost | 기동 시간, 추론 시간, 실패율 |

고정 기준:

- Qwen 30B가 Qwen 80B 대비 승인 가능 후보 품질이 동등하고 review burden이 유의하게 늘지 않으면 30B를 기본으로 고정한다.
- Qwen 80B가 evidence alignment와 alias precision에서 명확히 우수하면 80B를 비지속 batch 전용으로 유지한다.
- 두 모델 차이가 작고 80B 기동 비용이 크면 30B를 기본, 80B를 보존 모델로 둔다.

## 실행 순서

1. 지원 모델 목록 고정 패치 검증
   - `python -m pytest tests/test_llm_factory.py -q`
   - `python -m compileall -q src/llm/factory.py`

2. 엑셀 평가셋 변환기 추가
   - 입력: `/Users/june_kim/Downloads/실손약관_챗봇_품질점검_평가셋 (1).xlsx`
   - 출력: `eval/policy_xlsx_qa.jsonl`
   - 변환 후 원본 엑셀은 저장소에 커밋하지 않는다.

3. 답변 생성 평가기 확장
   - `scripts/eval_large_model_rag.py`를 provider-prefixed 모델에 대응하도록 확장한다.
   - SGLang은 `/srv/ai-ops/bin/switch-sglang-model`, vLLM은 `/srv/ai-ops/bin/switch-vllm-model`을 사용한다.
   - 모델은 한 번에 하나만 기동한다.

4. 답변 생성 모델 비교 실행
   - baseline quick run: 각 모델 5문항
   - full run: 통과 모델만 40문항 전체
   - 결과: `reports/large_model_rag_eval/`

5. 온톨로지 LLM 영향 단계 구현
   - LLM JSON enrichment 추가
   - `qwen3-next-80b-a3b-instruct-fp8`와 `qwen3-30b-a3b-instruct-2507-fp8`를 같은 입력으로 비교

6. 삭제 후보 확정
   - 기동 실패, 품질 열세, 대체 모델 존재, 운영 용도 부재가 모두 확인된 모델만 삭제한다.
   - 삭제 전 `docs/`에 평가 근거와 보존/삭제 판단을 남긴다.

## 보류 위험

- 현재 온톨로지 후보 추출은 모델별 차이를 바로 측정할 수 없는 구조다. 모델 고정 전 LLM enrichment 단계를 먼저 구현해야 한다.
- `gpt-oss-120b`는 용량이 크고 메모리 부족 이력이 있으므로, 전체 평가가 아니라 기동 가능성 smoke test부터 해야 한다.
- `gemma-4-26b-a4b-nvfp4`는 삭제 후보지만 기존 vLLM 검증완료 이력이 있으므로 31B 대체 검증 전 제거하면 안 된다.
