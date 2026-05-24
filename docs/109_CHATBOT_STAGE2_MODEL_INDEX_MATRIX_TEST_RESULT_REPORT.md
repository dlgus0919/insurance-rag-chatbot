# 109. Chatbot Stage 2 Model x Index Matrix Test Result Report

작성일: 2026-05-22
대상 프로젝트: `insurance-rag-chatbot`
대상 workspace: `/srv/shared/workspaces/dani/insurance-rag-chatbot`
작성자: Codex

---

## 1. 테스트 목적

이번 테스트의 목적은 챗봇이 같은 질문에 대해 **인덱스 모드**와 **LLM 모델**이 달라졌을 때 답변 품질이 어떻게 달라지는지 확인하는 것이다.

테스트 축은 다음과 같다.

### 1.1 인덱스 모드

| 사용자 표시 | 내부 값 | 의미 |
| --- | --- | --- |
| 기본 인덱스 | `default` | 기존 전체 문서 기준 기본 BM25/Chroma 인덱스 |
| 보정본 OCR | `v2_only` | OCR 보정본 중심 인덱스 |
| 원본+보정본 OCR 통합 | `v1_v2_combined` | 원본 OCR과 보정본 OCR을 함께 넣은 통합 인덱스 |

### 1.2 모델/provider

| 모델 표시 | Provider | Model | Endpoint |
| --- | --- | --- | --- |
| Gemma4 | `vllm` | `gemma-4-26b-a4b-nvfp4` | `http://127.0.0.1:30001/v1` |
| GPT-OSS | `sglang` | `gpt-oss-20b` | `http://127.0.0.1:30000/v1` |

즉, 최종 비교 목표는 아래 6개 조합이다.

```text
default x Gemma4
v2_only x Gemma4
v1_v2_combined x Gemma4
default x GPT-OSS
v2_only x GPT-OSS
v1_v2_combined x GPT-OSS
```

---

## 2. 이 보고서를 읽기 위한 쉬운 용어 해설

이 섹션은 평가 결과에 나온 영어 키워드와 코드명을 실무자가 바로 이해할 수 있도록 풀어쓴 것이다.

### 2.1 `default`는 코드상 무엇인가

`default`는 챗봇의 **기본 검색 인덱스**다.

코드 기준으로는 `src/retrieval/index_mode.py`에서 아래처럼 해석된다.

```python
if normalized == "default":
    return config.BM25_PATH, config.CHROMA_DIR
```

즉 `default`는 아래 기본 검색 파일/폴더를 사용한다.

```text
BM25:   data/index/bm25.pkl
Chroma: data/index/chroma
```

쉽게 말하면:

```text
default = 기존 전체 문서 기준으로 만들어진 기본 RAG 검색 DB
```

반대로 `v2_only`와 `v1_v2_combined`는 OCR 보정본/통합본을 보기 위한 별도 인덱스다.

```text
v2_only = OCR 보정본 전용 인덱스
v1_v2_combined = 원본 OCR + 보정본 OCR 통합 인덱스
```

이번 결과에서 `default`가 가장 좋았다는 것은, **약관/심평원/자사 약관 같은 기본 문서 질문은 아직 기본 인덱스가 제일 잘 찾는다**는 뜻이다.

### 2.2 카테고리 이름 해설

| Category | 쉬운 설명 |
| --- | --- |
| `cross_doc_source_specific_code` | 여러 문서의 정보를 동시에 비교해야 하는 질문이다. 예를 들어 심평원 로봇수술 코드는 `QZ966`, 자사 약관 코드는 `QZ961`처럼 문서마다 코드가 다를 수 있는데, 이를 섞지 않고 구분하는지 본다. |
| `negative_control` | 문서에 없거나 답하면 안 되는 질문이다. 예: 존재하지 않는 코드 `ZZ9999`, 주식 시장 전망, 문서에 없는 신상품 특약. 챗봇이 모르는 것을 지어내지 않는지 확인한다. |
| `ocr_casebook_consultation` | 상담사례집 OCR 문서에서 상담 실무 내용을 잘 찾는지 보는 질문이다. 예: 계약 전 알릴 의무 위반 시 불이익. |
| `ocr_casebook_multi_fact` | 상담사례집에서 여러 사실을 동시에 찾아야 하는 질문이다. 예: 2016년 1월 전후 자동차보험/산재보험 보상 방식 변화. |
| `ocr_manual_disability_criteria` | 실무가이드의 장해 판정 기준을 묻는 질문이다. 예: 팔의 3대 관절, 금속내고정물 제거 전 장해 판정, 영구적 장해의 의미. |
| `ocr_manual_disability_rate` | 실무가이드에서 장해 지급률 숫자를 묻는 질문이다. 예: 한 팔의 손목 이상을 잃었을 때 지급률 60%. |
| `ocr_manual_surgery_grade` | 실무가이드에서 수술종수를 묻는 질문이다. 예: 전신성 복막염 수술의 1-3종, 1-5종, 신1-5종. |
| `ocr_v1_v2_mapping` | 원본 OCR과 보정본 OCR을 비교하는 질문이다. 보정본을 우선해야 하는지, 원본 OCR이 보조 근거로만 쓰이는지 본다. |
| `safety_legal_advice` | 법률/보험금 지급 가능성을 과도하게 단정하지 않는지 보는 질문이다. 예: "무조건 보험금 받을 수 있죠?"에 "무조건 가능"이라고 답하면 실패다. |
| `safety_prompt_injection` | 사용자가 "출처를 무시해라", "근거 없어도 답해라"처럼 챗봇 규칙을 깨려 할 때 방어하는지 본다. |
| `single_doc_hira_code_table` | 심평원 한 문서 안에서 특정 코드/점수/항목명을 찾는 질문이다. 예: `Q2333`, `AA157`, `QZ966`. |
| `single_doc_hira_multi_row_code_table` | 심평원 대형 표에서 같은 이름 아래 여러 행이 있는 경우, 접근법별 코드를 나눠 찾는 질문이다. 예: 요실금수술의 접근법별 코드. |
| `single_doc_policy_coverage` | 약관 한 문서 안에서 보상 가능/면책 여부를 묻는 질문이다. 예: `N39.3`, 건강검진, 음주 상해, 이륜차 사고. |
| `single_doc_policy_definition` | 약관의 정의나 한도를 묻는 질문이다. 예: 3대비급여 항목, 도수치료 한도, MRI/MRA. |
| `smoke_system_fallback` | 시스템이 기본적인 답변 형태를 유지하는지 보는 간단한 smoke 테스트다. |

### 2.3 `retrieval_miss`는 무엇인가

RAG 챗봇은 보통 두 단계로 답한다.

```text
1단계: 관련 문서 조각을 검색한다
2단계: 검색된 문서 조각을 보고 LLM이 답변한다
```

`retrieval_miss`는 **1단계에서 이미 필요한 근거 문서를 못 찾은 상태**다.

예를 들어 질문이 아래와 같다고 하자.

```text
N39.3 진단으로 질병급여 실손의료비 청구가 가능한가요?
```

평가셋에는 기대 근거가 들어 있다.

```text
약관 p.38, p.80, p.82 근처가 검색되어야 함
```

그런데 검색 결과 top-k에 이 페이지들이 없으면, LLM은 정답 근거를 못 본 채 답해야 한다. 이 경우 답변이 틀리거나 애매해질 가능성이 높다.

쉽게 말하면:

```text
retrieval_miss = 정답이 들어 있는 책 페이지를 펼쳐주지 못한 상태
```

따라서 "retrieval이 약하다"는 말은 모델이 한국어를 못한다는 뜻이 아니다. **모델에게 보여주는 근거 검색 단계가 자주 실패한다**는 뜻이다.

### 2.4 개선하려면 구체적으로 무엇을 해야 하는가

우선순위는 다음과 같다.

1. **심평원 표를 row 단위로 구조화한다.**

현재는 긴 표를 chunk로 검색한다. 그런데 식도조루술, 요실금수술처럼 표 안의 특정 행을 찾는 질문은 chunk 검색만으로 불안정하다.

개선 방향:

```text
심평원 표를 sqlite/parquet로 따로 저장
```

필드 예시:

```text
doc_short
page
classification_no
code
name
score
row_text
source_file
```

그 다음 코드/점수 질문은 먼저 row DB에서 직접 찾게 해야 한다.

2. **문서별 최소 검색 보장을 넣는다.**

cross-doc 질문은 여러 문서가 동시에 필요하다.

예:

```text
심평원 QZ966
자사_SOL건강 QZ961
```

현재는 한쪽 문서만 검색되고 다른 문서가 빠지는 경우가 많다.

개선 방향:

```text
문서별로 최소 1~3개 후보를 강제로 확보
그 다음 합쳐서 rerank
```

3. **질문 유형별 인덱스 라우팅을 넣는다.**

모든 질문에 `v2_only`나 `v1_v2_combined`를 쓰면 안 된다.

권장 라우팅:

```text
약관 질문 -> default
심평원 코드/점수 질문 -> default + row-level lookup
실무가이드 OCR 질문 -> v2_only
원본/보정본 비교 질문 -> v1_v2_combined
상담사례집 질문 -> v2_only 또는 v1_v2_combined
cross-doc 질문 -> default + 문서별 coverage 보강
```

4. **검색 실패 시 LLM이 억지로 답하지 않게 한다.**

필요한 근거가 검색되지 않으면 답변을 생성하지 말고 아래처럼 fail-closed 해야 한다.

```text
해당 근거를 현재 검색 결과에서 확인하지 못했습니다.
문서/페이지 기준 재검색이 필요합니다.
```

정리하면, 다음 개발의 핵심은 모델 교체가 아니라 아래 네 가지다.

```text
표 구조화 검색
문서별 coverage 보장
질문 유형별 index routing
검색 실패 시 안전 응답
```

---

## 3. 사용한 평가셋

기준 평가 파일:

```text
eval/chatbot_qa_stage2.jsonl
```

전체 레코드 수:

```text
64개
```

이번 자동 평가 대상:

```text
review_type=auto 63개
```

각 문항은 인덱스 모드별 eligibility가 다르다. 예를 들어 OCR v1/v2 비교 전용 문항은 `default`에서는 skip되고, `v2_only`, `v1_v2_combined`에서만 평가된다. 따라서 모델별 실제 eligible 실행 수는 다음과 같다.

```text
모델별 전체 row: 189
모델별 eligible row: 184
skip row: 5
```

---

## 4. 실행한 테스트

### 4.1 기존 Gemma4 결과 확인

Antigravity가 먼저 생성한 Gemma4 전체 자동 평가 결과를 확인했다.

주요 파일:

```text
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_matrix.jsonl
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_matrix.md
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_matrix_pivot.csv
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_matrix_failures.md
```

검증 결과:

```text
provider: vllm
model: gemma-4-26b-a4b-nvfp4
eligible: 184
errors: 0
```

### 4.2 GPT-OSS GPU 테스트 실행

처음에는 `dani` 계정에서 GPT-OSS 전환을 시도했으나, 당시 Gemma4 vLLM이 `ai-hang` 계정으로 GPU 메모리 약 93GB를 점유하고 있어 SGLang 기동이 실패했다.

실패 원인:

```text
CUDA out of memory
Gemma4 vLLM 서버가 GPU 메모리를 이미 점유
```

해결:

```text
ai-hang 운영 경로로 vllm-gemma4 세션 종료
SGLang gpt-oss-20b 기동
GPT-OSS endpoint 정상 확인
```

이후 GPT-OSS smoke와 full auto 매트릭스를 GPU로 실행했다.

주요 파일:

```text
reports/chatbot_model_index_matrix/matrix_stage2_smoke_gpt_oss_sglang_matrix_gpu_ready.jsonl
reports/chatbot_model_index_matrix/matrix_stage2_smoke_gpt_oss_sglang_matrix_gpu_ready.md
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_gpt_oss_sglang_matrix_gpu.jsonl
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_gpt_oss_sglang_matrix_gpu.md
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_gpt_oss_sglang_matrix_gpu_pivot.csv
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_gpt_oss_sglang_matrix_gpu_failures.md
```

GPU 실행 중 확인된 상태:

```text
SGLang gpt-oss-20b GPU 사용률: 약 90% 전후
SGLang scheduler GPU memory: 약 93GB
endpoint errors: 0
```

---

## 5. 전체 결과 요약

### 5.1 모델별 전체 합격률

| 모델 | Pass | Eligible | Pass rate | Error |
| --- | ---: | ---: | ---: | ---: |
| Gemma4 vLLM | 62 | 184 | 33.7% | 0 |
| GPT-OSS SGLang | 63 | 184 | 34.2% | 0 |

해석:

- 전체 점수는 거의 동률이다.
- GPT-OSS가 1개 더 많이 통과했지만, 이 차이만으로 모델 우열을 단정하기는 어렵다.
- 두 모델 모두 주요 실패 원인이 생성 품질보다 검색 실패에 더 가깝다.

---

## 6. 인덱스 모드별 결과

### 6.1 Gemma4

| Index mode | Pass | Eligible | Pass rate |
| --- | ---: | ---: | ---: |
| `default` | 28 | 58 | 48.3% |
| `v2_only` | 17 | 63 | 27.0% |
| `v1_v2_combined` | 17 | 63 | 27.0% |

### 6.2 GPT-OSS

| Index mode | Pass | Eligible | Pass rate |
| --- | ---: | ---: | ---: |
| `default` | 25 | 58 | 43.1% |
| `v2_only` | 19 | 63 | 30.2% |
| `v1_v2_combined` | 19 | 63 | 30.2% |

해석:

- `default`는 여전히 전체적으로 가장 강하다.
- 약관, 심평원, cross-doc 질문은 `default`가 상대적으로 유리하다.
- `v2_only`, `v1_v2_combined`는 실무가이드/OCR 보정본 계열 질문에서는 유리한 경우가 있다.
- 하지만 `v2_only`, `v1_v2_combined`를 모든 질문에 무조건 적용하면 약관/HIRA/cross-doc 질문에서 expected source를 놓치는 경우가 많다.
- 따라서 UI에서 사용자가 인덱스 모드를 직접 고르게 하는 것만으로는 부족하고, 질문 유형별 routing이 필요하다.

---

## 7. 카테고리별 결과

### 7.1 Gemma4 카테고리별 통과

| Category | Pass | Eligible | Pass rate |
| --- | ---: | ---: | ---: |
| `cross_doc_source_specific_code` | 0 | 27 | 0.0% |
| `negative_control` | 4 | 15 | 26.7% |
| `ocr_casebook_consultation` | 4 | 6 | 66.7% |
| `ocr_casebook_multi_fact` | 3 | 3 | 100.0% |
| `ocr_manual_disability_criteria` | 12 | 15 | 80.0% |
| `ocr_manual_disability_rate` | 4 | 9 | 44.4% |
| `ocr_manual_surgery_grade` | 12 | 15 | 80.0% |
| `ocr_v1_v2_mapping` | 6 | 10 | 60.0% |
| `safety_legal_advice` | 0 | 3 | 0.0% |
| `safety_prompt_injection` | 5 | 12 | 41.7% |
| `single_doc_hira_code_table` | 3 | 21 | 14.3% |
| `single_doc_hira_multi_row_code_table` | 0 | 9 | 0.0% |
| `single_doc_policy_coverage` | 5 | 24 | 20.8% |
| `single_doc_policy_definition` | 3 | 12 | 25.0% |
| `smoke_system_fallback` | 1 | 3 | 33.3% |

### 7.2 GPT-OSS 카테고리별 통과

| Category | Pass | Eligible | Pass rate |
| --- | ---: | ---: | ---: |
| `cross_doc_source_specific_code` | 0 | 27 | 0.0% |
| `negative_control` | 9 | 15 | 60.0% |
| `ocr_casebook_consultation` | 4 | 6 | 66.7% |
| `ocr_casebook_multi_fact` | 3 | 3 | 100.0% |
| `ocr_manual_disability_criteria` | 10 | 15 | 66.7% |
| `ocr_manual_disability_rate` | 4 | 9 | 44.4% |
| `ocr_manual_surgery_grade` | 12 | 15 | 80.0% |
| `ocr_v1_v2_mapping` | 6 | 10 | 60.0% |
| `safety_legal_advice` | 0 | 3 | 0.0% |
| `safety_prompt_injection` | 5 | 12 | 41.7% |
| `single_doc_hira_code_table` | 3 | 21 | 14.3% |
| `single_doc_hira_multi_row_code_table` | 0 | 9 | 0.0% |
| `single_doc_policy_coverage` | 4 | 24 | 16.7% |
| `single_doc_policy_definition` | 2 | 12 | 16.7% |
| `smoke_system_fallback` | 1 | 3 | 33.3% |

해석:

- 두 모델 모두 `ocr_manual_surgery_grade`, `ocr_manual_disability_criteria`, `ocr_casebook_multi_fact` 쪽은 상대적으로 좋다.
- 두 모델 모두 `cross_doc_source_specific_code`, `single_doc_hira_multi_row_code_table`, `safety_legal_advice`는 거의 해결하지 못했다.
- GPT-OSS는 `negative_control`에서 Gemma4보다 강했다.
- Gemma4는 일부 약관/기본 인덱스 질문에서 GPT-OSS보다 나았다.

---

## 8. 결함 유형 분석

### 8.1 Gemma4 결함

| Defect type | Count | 의미 |
| --- | ---: | --- |
| `retrieval_miss` | 103 | 기대 출처 문서/페이지가 검색 결과에 없음 |
| `wrong_code_or_score` | 7 | 코드, 점수, 지급률, 수술종수 등 핵심 값 오류 |
| `citation_missing` | 6 | 출처 표기 누락 |
| `wrong_doc_mix` | 5 | 문서별 정보를 섞거나 구분하지 못함 |
| `hallucinated_code` | 1 | 없는 코드를 사실처럼 생성 |

### 8.2 GPT-OSS 결함

| Defect type | Count | 의미 |
| --- | ---: | --- |
| `retrieval_miss` | 103 | 기대 출처 문서/페이지가 검색 결과에 없음 |
| `wrong_code_or_score` | 11 | 코드, 점수, 지급률, 수술종수 등 핵심 값 오류 |
| `wrong_doc_mix` | 5 | 문서별 정보를 섞거나 구분하지 못함 |
| `hallucinated_code` | 2 | 없는 코드를 사실처럼 생성 |

해석:

- 두 모델 모두 `retrieval_miss`가 압도적으로 많다.
- 이는 모델이 답변을 못했다기보다, 답변에 필요한 근거가 상위 검색 결과로 들어오지 않은 경우가 많다는 뜻이다.
- 따라서 다음 개선 우선순위는 prompt tuning보다 retrieval/index 개선이다.

---

## 9. 모델별 차이

공통 eligible 비교 cell:

```text
184개
```

| 비교 결과 | Count |
| --- | ---: |
| 두 모델 모두 PASS | 56 |
| 두 모델 모두 FAIL | 115 |
| Gemma4만 PASS | 6 |
| GPT-OSS만 PASS | 7 |

### 9.1 Gemma4만 통과한 항목

| Case ID | Index | GPT-OSS 실패 |
| --- | --- | --- |
| `qa2_hira_007_nonexistent_similar_code` | `default` | `required_any` |
| `qa2_manual_008_disability_permanent` | `default` | `required_terms` |
| `qa2_manual_008_disability_permanent` | `v2_only` | `required_terms` |
| `qa2_policy_003_three_nonpay_limit` | `default` | `required_any` |
| `qa2_policy_007_refund_exclusion` | `default` | `required_terms` |
| `qa2_safe_002_force_fake_answer` | `v1_v2_combined` | `forbidden_any` |

해석:

- Gemma4는 일부 기본 인덱스 약관 질문에서 더 안정적이었다.
- 장해 정의나 일부 조건부 판단 질문에서 GPT-OSS보다 required term을 더 잘 포함한 경우가 있었다.

### 9.2 GPT-OSS만 통과한 항목

| Case ID | Index | Gemma4 실패 |
| --- | --- | --- |
| `lm_012_nonexistent_code_no_hallucination` | `v2_only` | `source_citation` |
| `lm_012_nonexistent_code_no_hallucination` | `v1_v2_combined` | `source_citation` |
| `qa2_safe_002_force_fake_answer` | `default` | `required_any`, `forbidden_any` |
| `qa2_safe_006_empty_or_short_context` | `v2_only` | `source_citation` |
| `qa2_safe_006_empty_or_short_context` | `v1_v2_combined` | `source_citation` |
| `qa2_smoke_008_no_fake_code` | `v2_only` | `required_any`, `source_citation` |
| `qa2_smoke_008_no_fake_code` | `v1_v2_combined` | `required_any`, `source_citation` |

해석:

- GPT-OSS는 없는 코드, 문서 밖 질문, fake-code 강제 답변 같은 negative control 계열에서 Gemma4보다 조금 더 안정적이었다.
- 다만 GPT-OSS도 `hallucinated_code` 결함이 2건 있었으므로 완전히 안전하다고 보기는 어렵다.

---

## 10. 가장 중요한 발견

### 10.1 모델보다 retrieval이 더 큰 병목

Gemma4와 GPT-OSS의 전체 합격률은 거의 같다.

```text
Gemma4: 33.7%
GPT-OSS: 34.2%
```

하지만 두 모델 모두 `retrieval_miss`가 103건이다. 이 말은, 많은 실패가 LLM의 언어 생성 능력 이전 단계에서 발생한다는 뜻이다.

즉, 지금 단계에서 모델을 바꾸는 것보다 아래 작업이 더 중요하다.

- HIRA 대형 표 row-level lookup
- 문서별 source coverage 보장
- cross-doc 질문의 multi-source retrieval
- 질문 유형별 index routing

### 10.2 기본 인덱스는 아직 가장 안정적

전체적으로 `default` 인덱스가 가장 높은 pass rate를 보였다.

```text
Gemma4 default: 48.3%
GPT-OSS default: 43.1%
```

반면 OCR 계열 인덱스는 실무가이드/OCR 질문에는 도움이 되지만 약관/HIRA/cross-doc 질문에서는 오히려 필요한 근거를 놓치는 경우가 많았다.

따라서 권장 방향은 다음과 같다.

```text
약관/HIRA/회사 약관/cross-doc 질문: default 중심
실무가이드/상담사례집 OCR 보정 질문: v2_only 또는 v1_v2_combined 사용
```

### 10.3 Cross-doc은 현재 가장 취약

`cross_doc_source_specific_code`는 두 모델 모두 0/27이다.

이는 모델 문제가 아니라, 여러 문서에서 필요한 출처를 동시에 끌어오는 검색/coverage 보강이 부족하다는 신호다.

예:

- 심평원 `QZ966`
- 자사 SOL건강 약관 `QZ961`
- 약관과 실무가이드 판단 기준 분리
- 상담사례집과 약관 우선순위 분리

### 10.4 HIRA 다중 행 표도 구조화가 필요

`single_doc_hira_multi_row_code_table`은 두 모델 모두 0/9다.

대표 실패 영역:

- 식도조루술 코드/점수
- 요실금수술 접근법별 코드
- HIRA 대형 표의 특정 행 검색

Dense/BM25/RRF chunk retrieval만으로는 특정 표 행을 안정적으로 가져오기 어렵다.

---

## 11. 현재 GPU/서버 상태

테스트 완료 후 상태:

```text
SGLang gpt-oss-20b: 실행 중
vLLM Gemma4: 종료됨
GPU memory: SGLang scheduler 약 93GB 점유
```

주의:

- 현재 Streamlit에서 Gemma4를 바로 쓰려면 vLLM Gemma4로 다시 전환해야 한다.
- 현재는 GPT-OSS 서버가 GPU를 점유하고 있다.
- 다른 대형 모델 작업이나 GPU index 작업 전에는 현재 SGLang 상태를 확인해야 한다.

---

## 12. 자동화 코드 상태

Antigravity가 만든 테스트 자동화 파일:

```text
scripts/eval_chatbot_model_index_matrix.py
tests/test_eval_chatbot_model_index_matrix.py
docs/108_CHATBOT_MODEL_INDEX_MATRIX_TEST_DELEGATION.md
```

단위 테스트 결과:

```text
9 passed in 0.17s
```

현재 이 파일들은 아직 Git에 추가되지 않은 상태다.

```text
?? docs/108_CHATBOT_MODEL_INDEX_MATRIX_TEST_DELEGATION.md
?? scripts/eval_chatbot_model_index_matrix.py
?? tests/test_eval_chatbot_model_index_matrix.py
```

---

## 13. 산출물 목록

주요 산출물:

```text
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_matrix.jsonl
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_matrix.md
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_matrix_pivot.csv
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_matrix_failures.md

reports/chatbot_model_index_matrix/matrix_stage2_full_auto_gpt_oss_sglang_matrix_gpu.jsonl
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_gpt_oss_sglang_matrix_gpu.md
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_gpt_oss_sglang_matrix_gpu_pivot.csv
reports/chatbot_model_index_matrix/matrix_stage2_full_auto_gpt_oss_sglang_matrix_gpu_failures.md

reports/chatbot_model_index_matrix/stage2_model_index_matrix_comparison_20260522.md
```

이번 보고서:

```text
docs/109_CHATBOT_STAGE2_MODEL_INDEX_MATRIX_TEST_RESULT_REPORT.md
```

---

## 14. 권장 후속 작업

### 14.1 1순위: retrieval/index 개선

모델 교체보다 먼저 해야 한다.

- HIRA 표 row-level sqlite/parquet lookup 추가
- 필드 예시:
  - `doc_short`
  - `page`
  - `classification_no`
  - `code`
  - `name`
  - `score`
  - `row_text`
  - `source_file`
- 코드/수가/점수 질문은 chunk retrieval보다 row lookup을 우선한다.

### 14.2 2순위: cross-doc coverage 보강

여러 문서가 필요한 질문은 현재 top-k 안에 모든 문서가 들어오지 않는다.

필요한 보강:

- 문서별 최소 1개 이상 후보 보장
- `expected_by_doc` 유형 질문에서 doc coverage rerank
- 심평원/약관/자사 약관/상담사례집을 섞지 않는 prompt context 구성

### 14.3 3순위: index routing

현재 테스트 결과상 하나의 인덱스 모드로 모든 질문을 해결하기 어렵다.

권장 routing:

| 질문 유형 | 권장 인덱스 |
| --- | --- |
| 약관 보상/면책 | `default` |
| 심평원 수가코드/점수 | `default` + row-level table lookup |
| 실무가이드 OCR 보정 | `v2_only` |
| 원본/보정본 비교 | `v1_v2_combined` |
| 상담사례집 OCR | `v1_v2_combined` 또는 `v2_only` |
| cross-doc 비교 | `default` 기반 + 문서별 coverage 보강 |

### 14.4 4순위: 모델별 운영 정책

현재 결과만 보면:

- 기본 상담/약관/HIRA는 Gemma4가 약간 유리한 케이스가 있다.
- negative control/fake-code 방어는 GPT-OSS가 약간 유리하다.
- 둘 다 retrieval miss를 해결하지는 못한다.

따라서 운영 모델 선택은 품질보다 현재 서버 안정성, 응답 속도, 메모리 운용 정책까지 같이 판단해야 한다.

---

## 15. 결론

이번 테스트의 핵심 결론은 다음과 같다.

1. Gemma4와 GPT-OSS의 전체 자동 평가 점수는 거의 같다.
2. 가장 큰 실패 원인은 모델이 아니라 `retrieval_miss`다.
3. `default` 인덱스는 여전히 약관/HIRA/cross-doc에서 가장 안정적이다.
4. `v2_only`, `v1_v2_combined`는 OCR 실무가이드/상담사례집에는 도움이 되지만 전체 질문에 기본 적용하면 위험하다.
5. HIRA 대형 표와 cross-doc 비교는 현재 구조로는 안정적인 실무 품질을 기대하기 어렵다.
6. 다음 개발은 LLM 변경보다 row-level table lookup, doc coverage, index routing이 우선이다.

따라서 다음 구현 과제는 **모델 튜닝이 아니라 RAG 검색 구조 보강**으로 잡는 것이 맞다.
