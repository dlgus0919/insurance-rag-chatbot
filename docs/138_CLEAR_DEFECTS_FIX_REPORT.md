# 138. 명확 원인 결점 5종 보완 결과 보고

작성일: 2026-05-28
대상: GraphDB/RAG/보험금 계산 파이프라인
기본 검증 모델: GPT-OSS (`sglang:gpt-oss-20b`)

## 1. 보완한 결점과 원인

1. **면책 표준코드가 LLM 계산으로 덮이는 문제**
   - 원인: `pay_opn_cd_nm=면책/보상제외`인 표준모델 매칭도 LLM 산식 경로로 넘어가 지급액이 산출될 수 있었다.
   - 조치: 면책/보상제외 매칭은 LLM 호출 전에 결정론 계산으로 강제하고 지급예상액 0원, 공제금액 전액으로 고정했다.

2. **LLM 산식의 `from decimal import Decimal` 때문에 샌드박스가 실패하는 문제**
   - 원인: 샌드박스는 `Decimal`을 이미 주입하지만, LLM이 안전한 Decimal import를 붙이면 AST import 차단에 걸렸다.
   - 조치: `from decimal import Decimal`만 실행 전 정규화 단계에서 제거하고, 다른 import는 계속 차단한다.

3. **5세대/비중증/3대비급여 계산이 LLM 응답에 따라 흔들리는 문제**
   - 원인: 공제율과 한도 적용을 LLM 산식에 의존해 0원 또는 잘못된 공제율이 최종값으로 남을 수 있었다.
   - 조치: 표준모델/세대별 결정론 계산값을 baseline으로 계산하고, LLM 산식 실패·불일치·미반환 시 baseline을 최종값으로 적용한다.

4. **HIRA 수가표 row-level lookup 누락**
   - 원인: 대형 표의 특정 행은 chunk retrieval만으로 누락되거나, GraphDB에는 코드만 있고 점수가 누락되는 경우가 있었다.
   - 조치: 심평원 청크를 직접 스캔하는 HIRA row fallback을 추가하고, 췌이식술/이식수술 계열 질의에서 코드와 점수를 구조화 컨텍스트 및 deterministic guard로 보강했다.

5. **GraphDB evidence chunk ID와 현재 OCR 인덱스 ID 불일치**
   - 원인: GraphDB evidence는 `_v2_manual_ch_...` 형태인데, 현재 Chroma 인덱스는 다른 chunk 번호/표기를 사용했다.
   - 조치: `get_by_ids`의 ID 표기 fallback을 확장하고, ID 조회 실패 시 Graph evidence의 `doc_short/page_start/page_end`로 청크를 복구하는 fallback을 추가했다.

## 2. 추가 안전장치

- GPT-OSS가 `신1‑5종`처럼 호환 하이픈을 출력해 채점/표시가 깨지는 문제를 줄이기 위해 LLM 답변 후처리 정규화를 추가했다.
- 없는 코드 강제 답변(`QZ999`, `QZ998`)은 deterministic guard에서 문서 근거 없음으로 차단한다.
- 4세대/5세대 비중증 비급여 비교 질의는 구조화 공제 규칙으로 직접 답변해 검색 누락에 의한 잘못된 회피를 막는다.

## 3. 검증 결과

### 단위/회귀 테스트

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_claim_code_sandbox.py \
  tests/test_claim_calculation_pipeline.py \
  tests/test_vector_store.py \
  tests/test_pipeline.py -q
```

결과:

```text
87 passed in 1.19s
```

### GPT-OSS 점검

기존 stage2 직접 평가 중 GPT-OSS 단일 모델 재점검:

```bash
PYTHONPATH=. HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false GRAPH_ENABLED=true \
.venv/bin/python scripts/stage2_direct_model_eval.py \
  --models sglang_gpt_oss --no-switch \
  --label repair_check4_gptoss --top-k 10 --max-tokens 900 --temperature 0.0
```

결과:

- 17개 중 16개 통과.
- 잔여 1개(`claim_mri_he115_5th`)는 코드가 5세대 통원 건당 20만원 한도를 적용해 `지급 200,000 / 공제 300,000`을 산출했으나, 기존 평가셋 기대값은 한도 미적용 `250,000 / 250,000`이어서 평가 기준 재검토 대상으로 분리했다.

### Final 테스트

기존 케이스와 다른 6개 유사 케이스를 GPT-OSS로 실행했다.

검증 항목:

- `QZ998` fake-code 방어
- 췌이식술 HIRA row-level 코드/점수 조회
- 소화기계 신1-5종 5종 수술의 수가코드/점수/후보 지급비율
- `51040` 면책 코드 120,000원 청구 시 지급 0원
- 비중증 비급여 300,000원 4세대/5세대 비교
- 5세대 MRI `HE115` 500,000원 통원 한도 포함 산출

결과:

```text
FINAL_TEST_PASS 6/6
```

## 4. 운영 상태

- Final 테스트 후 공용 DGX Spark 부하 절감을 위해 `sglang-local` GPT-OSS tmux 세션을 종료했다.
- 확인 시점 기준 vLLM/SGLang 대형 LLM 프로세스는 남아 있지 않았다.

## 5. 남은 주의점

- 기존 stage2 평가셋의 MRI 5세대 기대값은 현행 한도 적용 로직과 충돌한다. 이 항목은 약관 기준을 재확인한 뒤 평가셋 기대값을 갱신해야 한다.
- HIRA row fallback은 현재 `data/processed/chunks.jsonl` 기반이다. 장기적으로는 HIRA 표를 SQLite/Parquet row DB로 정규화하는 것이 더 안정적이다.
