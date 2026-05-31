# 137. Stage 2 Direct 4-Model Evaluation Report

작성일: 2026-05-27
대상 프로젝트: `insurance-rag-chatbot`
실행 환경: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`
평가 고정 조건: OCR 인덱스 `v2_only` (`보정본 OCR만`)

## 1. 목표와 완료 범위

이번 평가는 기존 Stage 2 매트릭스의 단순 반복이 아니라, 실제 DB와 원본 문서 근거를 다시 확인한 뒤 새 테스트를 설계해 4개 대형 LLM에 동일하게 적용하는 것을 목표로 했다.

완료한 작업:

- 시작 전 현재 상태를 GitHub에 백업: `origin/codex/stage2-test-backup`
- 원본 문서/DB 근거 확인 후 테스트셋 재설계
- 일반 질의 8개, 보험금 계산 9개 구성
- 4개 대형 모델 동일 평가
  - `vllm_gemma4`
  - `vllm_nemotron`
  - `sglang_gpt_oss`
  - `sglang_qwen3`
- 챗봇 출력과 보험금 계산 결과를 JSONL/CSV/Markdown으로 저장
- 틀린 단정은 0점, 근거 부족/보류는 부분점수로 직접 채점

## 2. 원본 근거 탐색 결과

테스트 설계 전 실제 인덱스와 구조화 DB에 근거가 있는지 확인했다.

주요 확인 근거:

- 심평원 `BZ202603053039374.pdf` p.638
  - `자-806 췌이식술 Pancreas Transplantation`
  - `Q8061 가. 부분 Partial 147,455.74`
  - `Q8062 나. 췌장 및 십이지장 Pancreas and Duodenum 159,457.97`
- 심평원 p.812
  - `조-961 QZ966 로봇 보조 수술 Robot-assisted Surgery`
- 자사 SOL 건강 약관 p.268, p.300
  - 다빈치로봇 수술 정의
  - `로봇 보조 수술[시술시 소요재료 포함] QZ961`
- 비급여 표준모델 SQLite
  - `51040 도수치료 / 공상 / 급여 / 면책`
  - `MX122 도수치료 [1일당] / 이학요법료 / 비급여_특약1(도수) / 추가확인`
  - `HE115 기본자기공명영상진단... / 비급여_특약3 / 추가확인`
- GraphDB
  - 수술등급, 약관 별표, HIRA 코드 연결은 존재하나 일부 GraphDB source chunk ID가 현재 `v2_only` VectorStore에서 조회되지 않는 경고가 반복됨

웹 조사는 사용하지 않았다. 필요한 근거가 현재 프로젝트의 원문 chunk, SQLite, GraphDB 안에서 확인됐기 때문이다.

## 3. 새 테스트셋

일반 질의 8개:

| ID | 목적 |
| --- | --- |
| `general_graph_bronchoesophageal_grade_peer` | 기관지 식도루 폐쇄술 등급, 동등급 peer, SOL 별표 후보/확정 구분 |
| `general_digestive_grade5_codes_ratio` | 소화기계 5종 수술, HIRA 수가코드, SOL 지급비율 후보 구분 |
| `general_robot_code_doc_split` | 심평원 `QZ966`과 자사 SOL `QZ961` 문서별 분리 |
| `general_hira_pancreas_code_score` | 췌이식술 `Q8061/Q8062` 및 점수 행 검색 |
| `general_4th_5th_nonsevere_difference` | 4세대/5세대 비중증 비급여 공제율 차이 |
| `general_three_nonpay_definition` | 3대비급여 정의 |
| `general_disclosure_duty_casebook_policy` | 상담사례집/약관 기반 고지의무 위반 불이익 |
| `general_fake_robot_code_guard` | `QZ999` 프롬프트 인젝션/환각 방어 |

보험금 계산 9개:

| ID | 기대 결과 |
| --- | --- |
| `claim_dosu_ambiguous_5th_no_code` | 도수치료 코드 미입력 시 모호성 보류, 지급/공제 0 |
| `claim_dosu_mx122_4th` | 4세대 도수치료 10만원: 공제 3만원, 지급 7만원 |
| `claim_dosu_mx122_5th` | 5세대 비중증 도수치료 10만원: 공제 5만원, 지급 5만원 |
| `claim_mri_he115_5th` | 5세대 MRI 50만원: 공제 25만원, 지급 25만원 |
| `claim_nonsevere_200k_4th` | 4세대 비중증 비급여 20만원: 공제 6만원, 지급 14만원 |
| `claim_nonsevere_200k_5th` | 5세대 비중증 비급여 20만원: 공제 10만원, 지급 10만원 |
| `claim_upper_room_difference_5th` | 상급병실료 차액 12만원 x 3일: 지급 15만원 |
| `claim_health_insurance_unapplied_5th` | 건강보험 미적용 특례: 공제 후 40% 보상 |
| `claim_dosu_51040_excluded_5th` | 51040 면책 코드: 지급 0원, 전액 공제 |

## 4. 실행 산출물

평가 스크립트:

```text
scripts/stage2_direct_model_eval.py
```

원격 실행 결과:

```text
reports/stage2_direct_eval/stage2_direct_full4_20260527_181735.jsonl
reports/stage2_direct_eval/stage2_direct_full4_20260527_181735.md
reports/stage2_direct_eval/stage2_direct_full4_20260527_181735_pivot.csv
reports/stage2_direct_eval/stage2_direct_full4_20260527_181735_failures.md
```

실행 명령:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false GRAPH_ENABLED=true \
.venv/bin/python scripts/stage2_direct_model_eval.py \
  --models vllm_gemma4,vllm_nemotron,sglang_gpt_oss,sglang_qwen3 \
  --label full4_20260527_181735
```

## 5. 전체 결과

전체 68개 row(4모델 x 17문항) 기준:

```text
PASS: 14 / 68
평균 점수: 1.96 / 5
```

모델별:

| 모델 | 통과 | 평균 점수 |
| --- | ---: | ---: |
| `sglang_gpt_oss` | 5/17 (29.4%) | 2.29 |
| `sglang_qwen3` | 4/17 (23.5%) | 1.76 |
| `vllm_gemma4` | 2/17 (11.8%) | 2.00 |
| `vllm_nemotron` | 3/17 (17.6%) | 1.76 |

유형별:

| 유형 | 통과 | 평균 점수 |
| --- | ---: | ---: |
| 일반 질의 | 7/32 | 1.94 |
| 보험금 계산 | 7/36 | 1.97 |

주요 실패 유형:

| 실패 유형 | 발생 수 |
| --- | ---: |
| `missing_any` | 30 |
| `wrong_deductible` | 29 |
| `wrong_payable_amount` | 28 |
| `missing_required` | 20 |
| `missing_llm_formula_execution` | 12 |
| `forbidden` | 4 |

## 6. 핵심 발견

### 6.1 모델 교체보다 파이프라인 결함이 더 큼

4개 모델 모두 낮은 점수를 보였다. 특정 모델 하나의 문제가 아니라 검색/GraphDB/계산 파이프라인의 공통 결함이 반복된다.

대표적으로 보험금 계산은 모델별 자연어 능력과 무관하게 `wrong_payable_amount`, `wrong_deductible`이 반복됐다.

### 6.2 HIRA row-level 표 검색이 여전히 약함

원문에는 p.638에 췌이식술 `Q8061/Q8062`와 점수가 명확히 존재한다. 하지만 4개 모델 모두 `general_hira_pancreas_code_score`에서 실패했다.

이는 답변 모델 문제가 아니라, 특정 HIRA 표 행을 RAG 컨텍스트로 안정적으로 전달하지 못하는 검색 경로 문제다.

필요한 개선:

- HIRA 수가표 row-level lookup을 RAG보다 우선 적용
- 코드/점수 질문은 chunk 검색 대신 구조화 테이블 직접 조회
- `Q8061/Q8062`처럼 실제 row가 있는 경우 컨텍스트에 강제 삽입

### 6.3 GraphDB와 VectorStore 간 source chunk ID 불일치

평가 중 아래 유형의 경고가 반복됐다.

```text
Graph source chunks [...] not found in Chroma vector store. Ignored.
```

즉 GraphDB는 구조화 사실을 알고 있지만, 그 근거 chunk ID가 현재 `v2_only` VectorStore에서 조회되지 않는다. 이 경우 GraphDB 사실이 프롬프트에 요약으로는 들어가도, 근거 chunk 병합과 출처 보강이 약해진다.

필요한 개선:

- GraphDB build 시 현재 index mode별 chunk ID를 같이 저장
- `v2_only`, `v1_v2_combined`, `default`별 evidence ID alias 테이블 구축
- VectorStore에서 못 찾은 Graph evidence는 별도 source payload로라도 프롬프트와 UI에 유지

### 6.4 보험금 계산 LLM 산식 실행 경로가 불안정함

우리의 목표는 “LLM이 적용 조항에 따른 Python 계산식을 생성하고 샌드박스가 즉시 실행하여 결과를 출력”하는 것이다. 하지만 실제 실행에서 다음 문제가 반복됐다.

- LLM이 `from decimal import Decimal`을 포함하면 sandbox가 `모듈 import는 허용되지 않습니다`로 거부
- 일부 모델은 `claimed_amount`, `deductible`, `payable_amount` 필수 변수를 생성하지 않음
- LLM이 5세대 비중증 비급여에도 4세대 30% 공제율을 적용
- `51040` 면책 코드임에도 LLM 계산 경로에서 7만원 지급으로 잘못 산출

이는 “계산식을 생성해서 실행한다”는 구조 자체보다, LLM 산식을 받아들이기 전후의 deterministic guard가 부족한 문제다.

필요한 개선:

- sandbox에 `Decimal`을 기본 바인딩하고 LLM prompt에는 import 금지 명시
- LLM formula를 실행하기 전에 AST에서 필수 변수, 금지 import, 금액 보존식 검증
- StandardMatcher가 `면책`을 반환하면 LLM 산식 생성 전에 hard stop
- 4세대/5세대/중증/비중증 구분은 LLM에게 맡기지 말고 deterministic rule table에서 강제 주입

### 6.5 면책 코드는 LLM 계산 경로가 덮어쓰면 안 됨

`claim_dosu_51040_excluded_5th`는 모든 모델에서 실패했다.

기대:

```text
지급 0원 / 공제 100,000원 / 면책 검토 사유 표시
```

실제 일부 모델:

```text
지급 70,000원 / 공제 30,000원
```

즉 표준모델 DB가 이미 “면책”이라고 말하는 항목도 LLM 산식이 이를 무시하고 계산할 수 있다. 이 문제는 챗봇 답변 부정확성으로 직결되므로 최우선 수정 대상이다.

## 7. 직접 평가 결론

현재 상태에서는 4개 모델 중 어느 하나도 실무 운영 품질을 만족한다고 보기 어렵다. 다만 점수만 보면 `sglang_gpt_oss`가 가장 높았고, `vllm_gemma4`는 GraphDB 등급 질의 일부는 강했지만 fake-code 방어와 계산 안정성이 약했다.

하지만 핵심 결론은 모델 순위가 아니다.

우선순위는 다음과 같다.

1. 보험금 계산에서 면책/세대별 공제율을 deterministic rule로 강제한다.
2. LLM formula sandbox의 Decimal/import 문제와 필수 변수 검증을 수정한다.
3. HIRA row-level lookup을 RAG 앞단에 붙인다.
4. GraphDB evidence chunk ID를 현재 VectorStore 인덱스와 동기화한다.
5. 위 수정 후 동일 68-row 테스트를 재실행한다.

## 8. 다음 작업 권장 명세

다음 서브 에이전트 작업은 모델 추가 평가가 아니라 아래 로직 보강이어야 한다.

### 8.1 Claim Calculation Hard Guard

- `StandardMatch.pay_opn_cd_nm`이 `면책`, `보상제외`, `제외`, `미보상`이면 LLM planner 호출 전 `not_covered`로 종료
- 지급액 `0`, 공제액 `claimed_amount`로 고정
- review reason에 면책 코드와 표준명 표시

### 8.2 Deterministic Rule Injection

- 4세대/5세대, 급여/비급여/중증/비중증/3대비급여 분류는 LLM이 추론하지 않도록 rule table 결과를 변수로 주입
- LLM은 설명과 계산식 작성만 담당
- 산식 실행 후 deterministic expected range와 불일치하면 자동 보류

### 8.3 Sandbox Formula Normalization

- `Decimal`은 sandbox globals에 미리 제공
- LLM formula에서 `from decimal import Decimal`은 제거하거나 허용 가능한 안전 import로 정규화
- `claimed_amount`, `deductible`, `payable_amount` 누락 시 재시도 또는 계산 보류

### 8.4 HIRA Row Lookup

- `심평원` 코드/점수 질문은 `MedicalFeeCode` 또는 별도 row DB를 먼저 조회
- `Q8061/Q8062` 같은 row-level 결과를 RAG context 맨 앞에 삽입
- 행 주변의 `Q8051/Q8052` 같은 이웃 행과 섞이지 않도록 row-level citation을 별도 렌더링

### 8.5 Graph Evidence ID Sync

- GraphDB evidence에 `source_version`, `index_mode`, `chunk_id_aliases` 저장
- 현재 VectorStore에서 못 찾는 Graph evidence도 UI에서 “구조화 근거 출처”로 유지
- `Graph source chunks not found` 경고를 평가 실패 원인으로 추적

## 9. 검증 상태

실행 완료:

```bash
python -m py_compile scripts/stage2_direct_model_eval.py
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false GRAPH_ENABLED=true \
.venv/bin/python scripts/stage2_direct_model_eval.py \
  --models vllm_gemma4,vllm_nemotron,sglang_gpt_oss,sglang_qwen3 \
  --label full4_20260527_181735
```

미실행:

- 위 결함 수정 후 재평가
- 브라우저 UI에서 동일 17개 케이스 수동 재현
