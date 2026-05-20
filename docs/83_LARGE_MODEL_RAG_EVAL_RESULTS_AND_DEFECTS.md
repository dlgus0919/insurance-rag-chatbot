# Large Model RAG Evaluation Results And Defects

## 목적

대형 로컬 LLM을 활용한 보험 RAG 답변 로직을 검증하기 위해 자동화 질문-답변 평가셋과 실행 스크립트를 추가하고, 현재 DGX Spark에 준비된 `gpt-oss-20b`, `gemma-4-26b-a4b-nvfp4`에 대해 실제 평가를 수행했다.

## 추가한 평가 자산

- `eval/large_model_rag_qa.jsonl`
  - 12개 평가 케이스.
  - 단일 문서 질의, 다문서 코드 충돌, 심평원 표 코드/점수, 약관 보상/면책, OCR 실무가이드, OCR 상담사례집, prompt injection, 없는 코드 환각 방지를 포함한다.
- `scripts/eval_large_model_rag.py`
  - SGLang 모델을 순차 전환하며 동일 평가셋을 실행한다.
  - 결과는 `reports/large_model_rag_eval/`에 JSONL/Markdown으로 저장한다.
  - 유니코드 하이픈과 `%` 앞 공백 차이를 정규화해 의미상 동일한 답변이 false negative가 되지 않도록 처리한다.
- `tests/test_large_model_eval.py`
  - 평가기 정규화, citation-only 답변 감지, `<pad>` 반복 감지를 고정한다.

## 실행 결과

최신 실행 결과:

- `gpt-oss-20b`: `9/12 PASS`
  - 결과 파일:
    - `reports/large_model_rag_eval/large_model_rag_eval_gpt_oss_20b_20260520_norm.jsonl`
    - `reports/large_model_rag_eval/large_model_rag_eval_gpt_oss_20b_20260520_norm.md`
  - 총 평가 응답 시간: 약 `212.0s`
  - 문항당 평균: 약 `17.7s`
- `gemma-4-26b-a4b-nvfp4`: `0/12 PASS`
  - 결과 파일:
    - `reports/large_model_rag_eval/large_model_rag_eval_gemma4_20260520_norm.jsonl`
    - `reports/large_model_rag_eval/large_model_rag_eval_gemma4_20260520_norm.md`
  - 총 평가 응답 시간: 약 `471.6s`
  - 문항당 평균: 약 `39.3s`

## gpt-oss-20b 결함 분석

`gpt-oss-20b`는 로봇 수술 코드 충돌, 약관 면책, 3대비급여, 실무가이드 OCR 수술종수/장해 기준, prompt injection, 없는 코드 환각 방지에서는 통과했다. 현재 주요 결함은 생성 모델보다 검색/근거 선택 단계에 가깝다.

### 1. 심평원 식도조루술 코드/점수 검색 실패

- 케이스: `lm_002_hira_esophagostomy_code_score`
- 기대: 심평원 `p.531`, `Q2333`, `14,110.89`
- 실제 top source: `p.753`, `p.440`, `p.444` 등
- 답변: 제공된 문서에서 확인되지 않는다고 응답
- 해석:
  - 모델이 추론을 잘못했다기보다, 검색 단계에서 정확한 표 행이 들어오지 않았다.
  - 수술명 기반 질의가 심평원 대형 표의 특정 행으로 안정적으로 연결되지 않는다.

### 2. 심평원 요실금수술 접근법별 코드 검색/행 매칭 실패

- 케이스: `lm_003_hira_urinary_incontinence_code_rows`
- 기대: 심평원 `p.553`, `R3564`, `R3565`, `R3562`, `R3563`
- 실제 top source: `p.982`, `p.440`, `p.438` 등
- 답변: 일부 코드를 생성했지만 `R3563`을 누락하고 관련 없는 `R3566` 이후 항목까지 섞었다.
- 해석:
  - 검색 결과에 기대 페이지가 없는데도 모델이 유사 항목을 조합했다.
  - 표 행 단위 citation과 코드-항목명-점수 같은 row-level grounding이 필요하다.

### 3. 상담사례집 계약 전 알릴 의무 expected page miss

- 케이스: `lm_009_casebook_duty_to_disclose`
- 기대: 상담사례집 `p.65`
- 실제 top source: `p.118`, `p.295`, `p.134`, `p.56`
- 답변: 고지의무 위반 시 해지/보험금 지급 거부 등 내용 자체는 대체로 그럴듯하나 기대 페이지가 검색되지 않았다.
- 해석:
  - 상담사례집 OCR 질의에서 유사 사례 페이지가 산재해 검색된다.
  - 이 케이스는 expected page 정합성도 재검토하고, 필요하면 사례집 section/title 기반 metadata boost를 추가해야 한다.

## Gemma4 결함 분석

`gemma-4-26b-a4b-nvfp4`는 현재 RAG 품질 평가 대상 모델로 보기 어렵다.

- RAG 평가에서는 12개 케이스 모두 citation-only 답변 또는 본문 없는 답변으로 실패했다.
- direct `/v1/chat/completions` 단독 호출에서도 `<pad>` 반복이 반환됐다.
- 따라서 현재 결함은 검색이나 프롬프트 문제가 아니라 SGLang에서 이 Gemma4 NVFP4 체크포인트를 로드/생성하는 런타임 설정 문제로 보는 것이 타당하다.

후속 검증 후보:

- Gemma4 전용 chat template 또는 tokenizer 설정 재확인
- SGLang의 해당 NVIDIA NVFP4 체크포인트 지원 상태 재확인
- stop token, eos token, pad token, sampling defaults 확인
- 같은 모델의 다른 quantization 또는 다른 serving engine 비교
- Gemma4는 이 문제가 해결되기 전까지 Streamlit 운영 선택지에서 기본 활성화하지 않는 것이 안전하다.

## 평가 중 발견한 운영 리스크

- 모델 전환/로딩 과정에서 Hugging Face Hub unauthenticated warning이 관찰됐다.
  - 완전 오프라인 운영 기준에서는 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, 로컬 모델 경로만으로 기동되는지 별도 검증이 필요하다.
- SGLang 대형 모델이 GPU 메모리를 크게 점유하므로 평가 스크립트는 embedder를 CPU로 로드하도록 기본값을 둔다.
- `gpt-oss-20b`는 답변 품질은 현재 운영 후보로 쓸 수 있으나, 심평원 표 코드 검색은 LLM 교체만으로 해결되지 않는다.

## 권장 후속 작업

1. 심평원 표를 row-level searchable artifact로 분리한다.
   - 코드, 항목명, 점수, 페이지, 표 파일명을 별도 색인한다.
   - 질의에 수가코드/수술명/점수가 포함되면 row index를 우선 검색한다.
2. 검색 결과에 기대 문서/페이지가 없을 때 모델이 유사 코드를 조합하지 못하도록 table-code 질문용 evidence gate를 강화한다.
3. 상담사례집은 사례 제목/절/페이지 metadata를 boost하거나, expected page를 재검토한다.
4. Gemma4는 direct generation이 정상화될 때까지 대형 모델 A/B 후보로만 유지하고 운영 기본값에서는 제외한다.
5. 대형 모델 평가를 정기 smoke로 운영하려면 `gpt-oss-20b` 기준 실패 3건을 known defect로 등록하고, 검색 개선 후 pass 기준을 상향한다.

## 검증 명령

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate

python -m py_compile scripts/eval_large_model_rag.py
pytest tests/test_large_model_eval.py tests/test_evidence.py tests/test_pipeline.py -q
pytest -q

python scripts/eval_large_model_rag.py --models gpt-oss-20b --label gpt_oss_20b_20260520_norm
python scripts/eval_large_model_rag.py --models gemma-4-26b-a4b-nvfp4 --label gemma4_20260520_norm
```

검증 결과:

- `tests/test_large_model_eval.py tests/test_evidence.py tests/test_pipeline.py`: `40 passed`
- 전체 pytest: `272 passed, 3 warnings`
- `gpt-oss-20b`: `9/12 passed`
- `gemma-4-26b-a4b-nvfp4`: `0/12 passed`
