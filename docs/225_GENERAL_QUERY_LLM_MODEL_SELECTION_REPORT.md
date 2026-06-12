# 일반 질의 LLM 모델 선정 및 보정본 OCR 재평가 보고서

## 1. 목적

질문 40개 평가 세트는 OCR 문서 데이터까지 포함한 전체 데이터베이스를 전제로 작성되었다. 따라서 기존 기본 인덱스 평가를 폐기하고, 보정본 OCR 수동 인덱스(`v2_only`)를 사용해 일반 질의 답변 모델을 다시 비교했다.

이번 작업의 목표는 다음과 같다.

- 일반 질의 답변용 메인 모델 1개를 확정한다.
- 온톨로지 후보 추출/정제 모델과 일반 답변 모델의 역할을 분리한다.
- 앱에서 노출되는 로컬 모델 후보를 평가 결론에 맞게 엄격히 고정한다.
- `gpt-oss-120b`는 기존 DGX 메모리 부족 결론에 따라 테스트 및 기본 후보에서 제외한다.

## 2. 평가 조건

| 항목 | 값 |
| --- | --- |
| 실행 위치 | DGX `/srv/shared/projects/insurance-rag-chatbot` |
| 평가 세트 | `eval/policy_xlsx_qa.jsonl` |
| 평가 문항 | 40개 |
| 검색 인덱스 | `--index-mode v2_only` |
| BM25 인덱스 | `data/index_v2_manual/bm25.pkl` |
| Chroma 인덱스 | `data/index_v2_manual/chroma/chroma.sqlite3` |
| 평가 라벨 | `policy_xlsx_answer_v2only_full_20260612_v1` |
| 모델 서버 정책 | 모델별 순차 기동, 각 평가 후 SGLang/vLLM 세션 정리 |
| 제외 모델 | `gpt-oss-120b` |

평가 결과 파일은 DGX의 `reports/large_model_rag_eval/large_model_rag_eval_policy_xlsx_answer_v2only_full_20260612_v1_*.jsonl`에 저장했다. 각 JSONL row의 `index_mode`는 모두 `v2_only`다.

## 3. 평가 기준

평가는 자동 채점 기준이다. 통과 여부는 기대 정답의 필수 용어, 숫자, 약관/조항 용어, 그룹 조건, 출력 건전성, 출처 제시 여부를 함께 확인한다.

답변 품질 평가는 다음 정성 지표를 함께 보았다.

- 보험 실무 답변으로 읽히는 어조와 형식
- 답변 길이와 정보 밀도
- 불필요한 장식 기호 또는 과도한 bullet 사용
- RAG 출처가 유지되는지 여부
- 실패 케이스의 성격이 단순 누락인지, 답변 형식 결함인지

평가 스크립트는 모든 케이스를 통과하지 못하면 `exit 1`을 반환한다. 이번 비교에서 각 모델은 일부 케이스를 놓쳤으므로 exit code는 만점 실패 신호이며, 결과 파일 저장 실패를 뜻하지 않는다.

## 4. 결과 요약

| 순위 | 모델 | Provider | 통과 | 실행 시간 | 평균 길이 | 출처 제시 | 출력 건전성 | 형식 품질 판단 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `qwen3-next-80b-a3b-instruct-fp8` | SGLang | 30/40 (75.0%) | 1168.3s | 732.5자 | 100.0% | 100.0% | 가장 높은 정답률. 장식 기호가 적고 답변 길이도 운영 답변으로 수용 가능 |
| 2 | `qwen3-30b-a3b-instruct-2507-fp8` | SGLang | 28/40 (70.0%) | 1049.7s | 1057.8자 | 100.0% | 100.0% | 정확도는 2위이나 답변이 길고 장식/목록 형식이 과다 |
| 3 | `qwen3-next-80b-a3b-thinking-fp8` | SGLang | 26/40 (65.0%) | 별도 summary 미기록 | 806.2자 | 100.0% | 100.0% | instruct 대비 정답률이 낮고 장식적 형식이 많음 |
| 3 | `gemma-4-26b-a4b-nvfp4` | vLLM | 26/40 (65.0%) | 839.0s | 716.9자 | 100.0% | 100.0% | 31B 모델이 이미지 후보 역할을 대체 가능하므로 삭제 후보 |
| 3 | `gemma-4-31b-it-nvfp4` | vLLM | 26/40 (65.0%) | 1664.5s | 584.7자 | 100.0% | 100.0% | 일반 답변 주력으로는 부족하나 이미지 인식 후보로 보존 |
| 6 | `gpt-oss-20b` | SGLang | 25/40 (62.5%) | 888.9s | 599.3자 | 100.0% | 100.0% | 정답률은 낮지만 저부하 fallback으로 유지 가능 |
| 7 | `exaone3.5:7.8b` | Ollama | 24/40 (60.0%) | 512.4s | 613.4자 | 100.0% | 100.0% | 가장 빠르지만 정확도 부족. Ollama fallback 후보로만 유지 |
| 8 | `llama-3.3-70b-instruct-q4-k-m` | Ollama | 22/40 (55.0%) | 2336.5s | 582.1자 | 97.5% | 100.0% | 느리고 정확도 낮아 기본 후보에서 제외 |
| 8 | `exaone-4.0-32b-awq` | vLLM | 22/40 (55.0%) | 1209.1s | 595.8자 | 100.0% | 100.0% | 정확도 열세로 삭제 후보 |
| 10 | `nemotron-3-nano-30b-a3b-nvfp4` | vLLM | 18/40 (45.0%) | 563.6s | 491.9자 | 100.0% | 72.5% | 출력 건전성 결함이 반복되어 삭제 후보 |

## 5. 선정 결론

### 일반 질의 답변 주력

`sglang:qwen3-next-80b-a3b-instruct-fp8`를 일반 질의 답변 주력 모델로 선정한다.

이유는 다음과 같다.

- 보정본 OCR 인덱스 기준 최고 통과율인 75.0%를 기록했다.
- 답변 길이가 30B보다 짧아 UI 응답으로 다루기 쉽다.
- 출처 제시와 출력 건전성이 모두 안정적이었다.
- thinking variant보다 정답률과 형식 안정성이 모두 낫다.

### 온톨로지 후보 추출/정제 주력

`sglang:qwen3-30b-a3b-instruct-2507-fp8`는 온톨로지 후보 추출/정제 주력 모델로 유지한다.

일반 답변 평가에서는 2위였지만, 답변 길이와 장식적 형식이 많아 일반 질의 주력에는 맞지 않았다. 반면 온톨로지 후보 enrichment처럼 구조화된 설명, alias 정제, 근거 판단, 예시 질문 생성이 필요한 batch 작업에는 여전히 적합하다.

### Fallback 및 보존 모델

| 역할 | 모델 | 결정 |
| --- | --- | --- |
| 저부하 fallback | `sglang:gpt-oss-20b` | 유지 |
| Ollama fallback | `ollama:exaone3.5:7.8b` | 기본 후보 1개로 축소 유지 |
| 이미지 인식 후보 | `vllm:gemma-4-31b-it-nvfp4` | 유지 |

### 비활성/삭제 후보

| 모델 | 결정 사유 |
| --- | --- |
| `gpt-oss-120b` | DGX 메모리 부족으로 기동 불가. 테스트 제외 및 기본 노출 차단 |
| `qwen3-next-80b-a3b-thinking-fp8` | instruct 대비 정답률과 형식 안정성 열세 |
| `gemma-4-26b-a4b-nvfp4` | `gemma-4-31b-it-nvfp4`가 이미지 후보 역할을 대체 |
| `nemotron-3-nano-30b-a3b-nvfp4` | 통과율 최저권 및 출력 건전성 결함 반복 |
| `exaone-4.0-32b-awq` | 일반 질의 정확도 열세 |
| `ollama:llama-3.3-70b-instruct-q4-k-m` | 느리고 정확도 낮아 기본 Ollama 후보에서 제외 |

## 6. 코드 반영 사항

- `scripts/eval_large_model_rag.py`
  - `--index-mode` 옵션을 추가했다.
  - 기본 평가 인덱스 모드를 `v2_only`로 설정했다.
  - `v2_only` 평가 시 `data/index_v2_manual`의 BM25/Chroma 인덱스를 사용하도록 연결했다.
  - 평가 결과 JSONL/Markdown에 `index_mode`를 기록한다.
- `scripts/run_answer_model_eval_batch.py`
  - 모델을 하나씩 순차 평가하고, 각 평가 후 SGLang/vLLM 세션과 프로세스 상태를 점검하는 배치 실행기를 추가했다.
  - 기본 인덱스 모드는 `v2_only`다.
- `src/config.py`
  - SGLang 기본 모델을 `qwen3-next-80b-a3b-instruct-fp8`로 고정했다.
  - SGLang 후보를 `qwen3-next-80b-a3b-instruct-fp8`, `qwen3-30b-a3b-instruct-2507-fp8`, `gpt-oss-20b`로 축소했다.
  - vLLM 기본 후보를 `gemma-4-31b-it-nvfp4`로 축소했다.
  - Ollama 기본 후보를 `exaone3.5:7.8b`로 축소했다.
  - `gpt-oss-120b`, thinking Qwen 80B, Gemma 26B, Nemotron, EXAONE 32B 등은 기본 비활성/삭제 후보로 분류했다.
- `src/llm/factory.py`
  - 모델 metadata에 `answer_primary`, `ontology_primary`, `fallback`, `vision_candidate`, `delete_candidate`, `disabled` 상태를 반영했다.
  - 비활성 SGLang/vLLM 모델은 UI 노출과 `build_llm` 생성을 차단한다.

## 7. 검증

로컬 검증:

```bash
python -m pytest tests/test_llm_factory.py tests/test_large_model_eval.py -q
python -m py_compile scripts/eval_large_model_rag.py scripts/run_answer_model_eval_batch.py src/config.py src/llm/factory.py
```

결과:

- `30 passed`
- Python compile 오류 없음

DGX 평가 산출물 확인:

```bash
ls -lh reports/large_model_rag_eval | grep policy_xlsx_answer_v2only_full_20260612_v1
```

확인 결과, 10개 모델의 JSONL/Markdown 결과와 batch summary 파일이 저장되어 있다.

## 8. 남은 위험

- 자동 채점은 필수 용어/숫자/조항 기준의 보수적 평가다. 최종 운영 품질 확정 전에는 상위 모델에 대해 사람 기준 샘플 리뷰를 추가하는 것이 좋다.
- Qwen 80B instruct는 일반 질의 성능이 가장 좋지만 메모리 점유가 크다. 운영에서는 모델 전환/기동 정책과 동시 실행 프로세스 정리가 중요하다.
- `v2_only` 인덱스가 최신 보정본 OCR 데이터로 계속 유지되어야 한다. 데이터 재빌드 후에는 같은 평가 스크립트로 회귀 평가를 반복해야 한다.
