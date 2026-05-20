# Large Model RAG Evaluation Plan

## 목적

SGLang 기반 대형 로컬 LLM이 보험 RAG 검색 결과를 정확히 해석하는지 평가하기 위한 자동화 테스트를 추가했다. 테스트는 단일 문서 질의, 여러 문서의 근거를 함께 확인해야 하는 질의, OCR 문서 질의, 문서별 코드 충돌, prompt injection, 존재하지 않는 코드에 대한 환각 방지를 포함한다.

## 추가 파일

- `eval/large_model_rag_qa.jsonl`: 대형 모델 RAG 평가셋
- `scripts/eval_large_model_rag.py`: 모델별 순차 평가 실행기

## 평가 범위

- 심평원 코드/점수 표: 코드와 점수, 같은 행 매칭 확인
- 실손 약관: 보상 불가/판정 필요와 출처 확인
- 실무가이드 OCR: 수술종수, 장해 지급률, 장해판정기준 확인
- 상담사례집 OCR: 상담 사례 기반 설명 확인
- Cross-doc: 심평원 `QZ966`과 자사 약관 `QZ961`을 통일하지 않는지 확인
- Safety/robustness: 출처 무시 지시를 거부하고 출처를 유지하는지 확인
- Negative control: 없는 코드에 대해 근거 없는 항목/점수를 만들지 않는지 확인

## 실행 예시

현재 활성 SGLang 모델 하나만 평가:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
python scripts/eval_large_model_rag.py --models gpt-oss-20b --no-switch
```

운영 wrapper로 두 모델을 순차 전환하며 평가:

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
python scripts/eval_large_model_rag.py   --models gpt-oss-20b,gemma-4-26b-a4b-nvfp4
```

빠른 부분 평가:

```bash
python scripts/eval_large_model_rag.py --models gpt-oss-20b --limit 4
```

## 결과물

결과는 `reports/large_model_rag_eval/` 아래에 JSONL과 Markdown으로 저장된다. JSONL은 각 문항의 답변, top source, 실패 check를 포함하므로 모델별 결점 분석에 사용한다.

## 판정 방식

각 케이스는 다음을 조합해 판정한다.

- 기대 문서/페이지가 검색 top-k에 포함되는지
- 필수 키워드/코드/정규식이 답변에 포함되는지
- 금지 키워드/코드가 답변에 포함되지 않는지
- 문서별 기대 코드가 해당 문서명과 함께 답변에 나타나는지
- `[출처:` 표기가 유지되는지
- `[근거 검증 경고]`가 발생하지 않는지
- 빈 응답, `<pad>` 반복, 과도한 반복 출력이 아닌지

## 해석 기준

이 스크립트는 완전한 법무/보상 품질 평가가 아니라, 대형 모델 편입 후 빠르게 결함을 찾는 회귀 테스트다. 특히 실패한 케이스는 검색 실패, 근거 해석 실패, 출력 형식 실패, 모델 런타임 품질 문제로 분류해 후속 개선 대상으로 삼는다.
