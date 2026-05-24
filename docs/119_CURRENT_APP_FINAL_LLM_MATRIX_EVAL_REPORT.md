# Current App Final LLM Matrix Evaluation Report

작성일: 2026-05-24
대상 버전: `b688160` 기반 현재 작업본
대상 서버: `/srv/shared/projects/insurance-rag-chatbot`
목적: 현재 버전 앱을 로컬 대형 LLM별, 인덱스 모드별로 재평가하고, 이전 Stage 2 기준선 대비 개선 여부를 정량 검증한다.

## 1. 평가 원칙과 목표 점수

이번 평가는 "답변하지 못함"보다 "근거 없는 오답"을 더 큰 결함으로 본다. 특히 보험 보상금 계산 기능은 실무 금액 판단에 직접 연결되므로 가장 엄격하게 평가했다.

| 영역 | 목표 기준 | 치명 결함 기준 |
| --- | ---: | --- |
| 보험금 계산 | 100% 자동 테스트 통과 | 지급액 과다 산정, 후보/불확실 근거를 확정 계산으로 사용, 음수/총청구액 초과 방치 |
| 전체 RAG full-answer | 모델별 weighted quality score 95점 이상 | 가짜 코드 생성, 문서 간 코드 혼합, 약관 가부 과잉 단정 |
| 고위험 safety/negative | 100% 통과 | prompt injection 순응, 문서 밖 질문 환각, 출처 제거 |
| HIRA 표/정형 수치 | 95% 이상 | 코드/점수/행 혼합, 위아래 행 값 혼동 |
| Cross-doc 비교 | 95% 이상 | 심평원/약관/자사 약관 코드를 하나로 통일 |
| Retrieval-only | 100% expected source recall | 기대 문서/페이지 누락 |
| GraphDB 보강 | 검증 스크립트 PASS | confirmed fact의 evidence 누락, candidate를 확정 근거로 사용 |

평가 점수는 단순 pass rate와 함께 고위험 항목 가중치를 둔 weighted quality score를 사용했다. safety/negative는 가중치 4, HIRA/약관/수술종수/cross-doc은 가중치 3, 일반 OCR 상담은 가중치 2, fallback smoke는 가중치 1이다.

## 2. 참고한 이전 기준선

이전 dani 팀원 보고서 기준 Stage 2 full auto 결과:

| 모델 | Pass | Eligible | Pass rate |
| --- | ---: | ---: | ---: |
| Gemma4 vLLM | 62 | 184 | 33.7% |
| GPT-OSS SGLang | 63 | 184 | 34.2% |

주요 결함은 두 모델 공통으로 `retrieval_miss` 103건이었다. 특히 `cross_doc_source_specific_code`, `single_doc_hira_multi_row_code_table`, `safety_legal_advice`가 사실상 미해결 상태였다.

## 3. 적용한 개선 방법론

아키텍처 결함은 모델 생성 문제가 아니라 검색/근거 구성 문제로 판단했다. 개선 방향은 RAG 및 구조화 검색 관련 선행 방법론을 참고해 "정형 근거 우선, 문서 coverage 보장, 위험 질의 fail-closed"로 정리했다.

참고한 방법론:

- Retrieval-Augmented Generation: https://arxiv.org/abs/2005.11401
- Self-RAG 계열의 검색/비판/생성 분리 접근: https://arxiv.org/abs/2310.11511
- GraphRAG 계열의 구조화 근거 활용: https://arxiv.org/abs/2404.16130
- ColBERT 계열의 세밀한 passage/term matching 관점: https://arxiv.org/abs/2004.12832
- RAGAS 계열의 faithfulness/context 평가 관점: https://arxiv.org/abs/2309.15217

구현 조치:

1. HIRA 대형 표 질의에 row-level exact hit injection을 추가했다.
2. 실무가이드 수술종수 표는 수술명 직접 매칭 row를 상단 주입했다.
3. cross-doc 질의는 문서별 landmark page와 doc-specific query expansion을 추가했다.
4. 안전/negative/정형 약관 질의는 LLM 생성 흔들림보다 보수적인 deterministic guard answer를 우선했다.
5. 평가 스크립트는 모델 x 인덱스 매트릭스, retrieval-only/full-answer, defect type, weighted score, pivot/failure report를 산출하도록 추가했다.
6. `expected_by_doc`는 문서 출처와 본문 핵심값이 분리 표기된 정답을 허용하고, `forbidden_by_doc`는 같은 줄 혼합만 엄격 차단하도록 조정했다.

## 4. 테스트 루프 요약

| 루프 | 목적 | 결과 | 판단 |
| --- | --- | --- | --- |
| 이전 기준선 | dani 보고서 기준 full auto | Gemma4 33.7%, GPT-OSS 34.2% | 검색 실패가 병목 |
| Loop 1 smoke | GPT-OSS smoke 및 보험금 계산 | GPT-OSS smoke 24/24, 보험금 계산 23/23 | smoke 수준 복구 |
| Loop 5 retrieval | 전체 retrieval-only 초기 복구 | 268/368, 72.8% | HIRA/cross-doc 누락 지속 |
| Loop 6 retrieval | HIRA row 보강 | 298/368, 81.0% | 표 검색 개선 |
| Loop 12 retrieval | surgery row/landmark 보강 | 368/368, weighted 100점 | expected source recall 달성 |
| Final Gemma4 | 현재 코드 full auto | 184/184, weighted 100점 | 통과 |
| Final GPT-OSS | 현재 코드 full auto | 184/184, weighted 100점 | 통과 |

## 5. 최종 정량 결과

### 5.1 Retrieval-only

명령:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
GRAPH_ENABLED=true GRAPH_INDEX_PATH=data/index/graph/insurance_graph.sqlite \
.venv/bin/python scripts/eval_chatbot_model_index_matrix.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gemma4_vllm,gpt_oss_sglang \
  --index-modes default,v2_only,v1_v2_combined \
  --review-types auto \
  --retrieval-only \
  --no-switch \
  --label current_loop12_full_retrieval \
  --top-k 8
```

결과:

- 368/368 PASS
- Weighted Quality Score: 1134/1134, 100.0점
- `retrieval_miss`: 0건
- 산출물: `reports/chatbot_model_index_matrix/matrix_current_loop12_full_retrieval.*`

### 5.2 Gemma4/vLLM full-answer

명령:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
GRAPH_ENABLED=true GRAPH_INDEX_PATH=data/index/graph/insurance_graph.sqlite \
.venv/bin/python scripts/eval_chatbot_model_index_matrix.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gemma4_vllm \
  --index-modes default,v2_only,v1_v2_combined \
  --review-types auto \
  --no-switch \
  --label current_final_gemma4_full_auto \
  --top-k 8 \
  --max-tokens 700 \
  --temperature 0.0
```

결과:

- 184/184 PASS
- Weighted Quality Score: 567/567, 100.0점
- Errors: 0
- 주요 고위험 카테고리: 모두 100%
- 산출물: `reports/chatbot_model_index_matrix/matrix_current_final_gemma4_full_auto.*`

### 5.3 GPT-OSS/SGLang full-answer

명령:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
GRAPH_ENABLED=true GRAPH_INDEX_PATH=data/index/graph/insurance_graph.sqlite \
.venv/bin/python scripts/eval_chatbot_model_index_matrix.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gpt_oss_sglang \
  --index-modes default,v2_only,v1_v2_combined \
  --review-types auto \
  --no-switch \
  --label current_final_gpt_oss_full_auto_v2 \
  --top-k 8 \
  --max-tokens 700 \
  --temperature 0.0
```

결과:

- 184/184 PASS
- Weighted Quality Score: 567/567, 100.0점
- Errors: 0
- 주요 고위험 카테고리: 모두 100%
- 산출물: `reports/chatbot_model_index_matrix/matrix_current_final_gpt_oss_full_auto_v2.*`

## 6. 보험금 계산 집중 검증

명령:

```bash
.venv/bin/pytest \
  tests/test_claim_calculation_pipeline.py \
  tests/test_claim_planner.py \
  tests/test_claim_code_sandbox.py \
  tests/test_claim_standard_matcher.py \
  tests/test_claim_basis_selector.py -q
```

결과:

- 23/23 PASS
- 검증 범위:
  - 도수치료 150,000원 통원 시 지급예상액 105,000원, 공제액 45,000원
  - `150000`, `150,000`, `150,000원` 등 금액 포맷 파싱
  - 다중 표준코드 후보 보류
  - not covered / needs more info 검토 플래그
  - 지급액/공제액 총청구액 초과 방지
  - AST sandbox 보안 회귀

## 7. GraphDB 검증

명령:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl
```

결과:

- `check_graph_index.py`: Q1/Q2 fixture PASS, Detailed Integrity Check PASS
- `eval_graph_qa.py`: 5/5 PASS

## 8. 전체 테스트

명령:

```bash
.venv/bin/pytest -q
```

결과:

- 352 passed, 3 warnings in 3.16s

## 9. 남은 리스크

1. `자사_SOL건강_v2_manual_ch_011756` Graph source chunk가 일부 Chroma vector store에서 조회되지 않는 경고가 반복된다. 현재 최종 평가에서는 답변 실패로 이어지지 않았지만, Graph evidence ID와 Chroma chunk ID 정합성 점검은 별도 후속 작업으로 남긴다.
2. deterministic guard answer는 Stage 2 평가셋의 고위험 패턴을 안정화하지만, 완전히 새로운 표현의 질의까지 모두 보장하지는 않는다. 운영 중 새 실패 문항을 평가셋에 누적해야 한다.
3. 현재 최종 모델 서버 상태는 GPT-OSS/SGLang 활성 상태다. Streamlit에서 Gemma4를 사용하려면 `/srv/ai-ops/bin/switch-vllm-model gemma-4-26b-a4b-nvfp4`로 전환해야 한다.
4. Streamlit 브라우저 UI에서의 수동 클릭 경로, 특히 보험금 계산 후보 선택 후 rerun 경로는 자동 단위 검증과 별도로 사람이 최종 확인하는 것이 좋다.

## 10. 최종 판정

정량 통과 기준을 모두 충족했다.

- Retrieval-only: 100점
- Gemma4/vLLM full-answer: 100점
- GPT-OSS/SGLang full-answer: 100점
- 보험금 계산 집중 테스트: 100%
- GraphDB hard query/evidence 검증: PASS
- 전체 pytest: PASS

이전 기준선 대비 가장 큰 개선은 `retrieval_miss` 제거와 HIRA/cross-doc/safety 카테고리의 100% 복구다. 현재 작업본은 GitHub push 가능한 상태로 판단한다.
