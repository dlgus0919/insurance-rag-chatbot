# 96. Chatbot QA Stage 2 Authoring Report

작성일: 2026-05-21
대상 프로젝트: `insurance-rag-chatbot`
작성자: Antigravity

본 보고서는 `docs/95_CHATBOT_QA_TESTSET_EXPANSION_SPEC.md` 명세에 따라 진행된 **Stage 2 챗봇 QA 테스트셋 확장, 수동 검증지 작성 및 툴 검증 결과**를 요약하고, 후속 작업을 진행할 팀원에게 전달할 내용을 기록합니다.

---

## 1. 추가 및 수정된 평가 파일

- **[NEW] [chatbot_qa_stage2.jsonl](file:///srv/shared/projects/insurance-rag-chatbot/eval/chatbot_qa_stage2.jsonl)**: 64개의 자동화 평가용 통합 확장셋 JSONL 파일. 기존 12개 시드에 심평원, 약관, 실무가이드, 원본/보정본 맵핑(v1/v2 pair), 크로스 문서 검증 및 안전성(Safety) 문항 등 52개 신규 문항을 추가로 수록.
- **[NEW] [chatbot_manual_review_stage2.md](file:///srv/shared/projects/insurance-rag-chatbot/eval/chatbot_manual_review_stage2.md)**: 사람이 실무 기준(6대 차원: 근거 정확성, 문서별 구분, 실무 유용성, 불확실성 표현, 출처 신뢰도, 환각 방지)에 따라 평가하기 위한 8가지 실무 시나리오 수동 질문지.
- **[MODIFY] [eval_large_model_rag.py](file:///srv/shared/projects/insurance-rag-chatbot/scripts/eval_large_model_rag.py)**: `--retrieval-only` 플래그 추가 및 `Hit` 객체 속성(`text` 필드 부재)으로 인해 발생하는 `AttributeError` 해결을 위해 `Hit`을 `Chunk` 객체로 변환하여 bypass하는 파이프라인 검증 로직 추가.
- **[NEW] [96_CHATBOT_QA_STAGE2_AUTHORING_REPORT.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/96_CHATBOT_QA_STAGE2_AUTHORING_REPORT.md)**: 본 보고서 파일.

---

## 2. 문항 수 및 카테고리 분포

`eval/chatbot_qa_stage2.jsonl`에 작성된 64개 자동 평가 문항의 난이도(Difficulty) 및 평가 목적별 분포는 다음과 같습니다.

### 2.1 난이도(Difficulty) 분포
- **Smoke (8개)**: RAG 파이프라인 및 LLM 기초 응답성 검증 (초진료 수가, N39.3 면책 기초, 복막염 종수, 손목 장해 지급률 등)
- **Standard (46개)**: 일반 RAG 기능, 대형 표 행 분리 검색, 약관 보상 예외, 크로스 문서 정보 분리, 안전성 가드 등
- **Hard (10개)**: 고난도 크로스 문서 분리 비교, 프롬프트 인젝션 방어, 가짜 코드 환각 방지 제어 등

### 2.2 카테고리 분포
- `single_doc_hira_code_table`: 3개
- `single_doc_hira_multi_row_code_table`: 3개
- `single_doc_policy_coverage`: 4개
- `single_doc_policy_definition`: 3개
- `ocr_manual_surgery_grade`: 4개
- `ocr_manual_disability_rate`: 4개
- `ocr_manual_disability_criteria`: 2개
- `ocr_casebook_consultation`: 3개
- `ocr_casebook_multi_fact`: 2개
- `cross_doc_source_specific_code`: 3개
- `safety_prompt_injection`: 2개
- `negative_control`: 3개
- `smoke_system_fallback`: 1개
- 기타 HIRA 취약점, 약관 보상 판정, OCR v2 Canonical, OCR v1/v2 Pair Mapping 등 세부 실무 케이스 분류 총 64문항 탑재.

---

## 3. 평가 방식 분석

- **자동 평가 가능 문항**: **64개 문항** (전체 JSONL 레코드. `review_type: "auto"` 기준)
- **수동 평가 문항**: **8개 문항** (`chatbot_manual_review_stage2.md`에 별도로 정의된 상담 및 심사 실무 시나리오 기반)

---

## 4. Expected Page 재검토 필요 문항 목록 (Retrieval Fail)

RAM/GPU 점유 제약으로 인해 LLM 호출을 건너뛰는 `--retrieval-only` 모드로 64개 전체 문항에 대한 검색 재현율(Recall) 검증을 실시했습니다.
그 결과, 총 **47개 문항은 PASS**하였으나, 아래 **17개 문항은 FAIL**(`failures=retrieval_expected_sources`)하였습니다. 이는 기대 출처 페이지(`expected_sources`)가 RAG 검색 상위 결과(top-k)에 포함되지 않았음을 뜻하므로, 인덱싱된 청크 페이지 정보와의 오차 또는 RAG 검색기 튜닝 여부에 대한 재검토가 필요합니다.

| 문항 ID | 카테고리 / 질문 내용 요약 | 실패 원인 분석 |
| :--- | :--- | :--- |
| `lm_002_hira_esophagostomy_code_score` | 심평원 식도조루술 수가코드/점수 | 대형 표의 특정 페이지 누락 혹은 검색 밀도 밀림 |
| `lm_003_hira_urinary_incontinence_code_rows` | 심평원 요실금수술 접근법별 수가코드 | 대형 표 검색 재현 실패 |
| `qa2_hira_001_esophagostomy` | 식도조루술 수가코드/점수 조회 (Smoke 보강) | `lm_002`와 동일한 재현 실패 현상 |
| `qa2_hira_002_urinary_incontinence_rows` | 요실금수술 접근법별 코드 분리 (Standard) | `lm_003`과 동일한 재현 실패 현상 |
| `qa2_hira_005_same_name_multiple_rows` | 요실금수술 접근법별 코드 차이 행별 대조 | 수가표 특정 행 검색 성능 저하 |
| `qa2_manual_006_appendectomy_grade` | 충수절제술 수술종수 분류 조회 | 실무가이드 인덱스 검색 누락 또는 페이지 매핑 미세 불일치 |
| `qa2_pair_004_source_disclosure` | 원본 및 보정본 통합 활용 시 판단 기준 명시 | v1/v2 페어 맵핑 데이터 및 가이드라인 검색 누락 |
| `qa2_pair_005_no_original_override` | 원본에만 존재하는 문구의 보정본 덮어쓰기 방지 | 보정본 우선 원칙 문서 검색 누락 |
| `qa2_pair_006_index_mode_compare_manual` | v2_only 와 combined 모드 비교 질문 | 인덱스 모드 대조용 특정 청크 검색 누락 |
| `qa2_cross_002_robot_compensation_split` | 로봇수술 실손 보상 약관별 충돌 여부 분리 | 약관 및 사례집 교차 검색 재현율 부족 |
| `qa2_cross_003_manual_vs_policy_surgery` | 실무가이드 수술종수 vs 약관 보상 제외 구분 | 이종 문서 간의 교차 매칭 검색 실패 |
| `qa2_cross_004_drunk_injury_policy_vs_driver` | 음주 상태 상해 실손 vs 운전자보험 보상 비교 | 약관과 운전자보험 약관 동시 검색 실패 |
| `qa2_cross_005_motorcycle_policy_vs_company` | 이륜자동차 운전 중 상해 보상/알릴의무 비교 | 부담보/통지의무 관련 다중 문서 검색 누락 |
| `qa2_cross_006_refund_policy_vs_company` | 본인부담금 상한제 환급금 실손 약관 비교 | 환급금 반환 규정 페이지 검색 밀림 |
| `qa2_cross_007_hira_code_vs_policy_code` | 심평원 수가코드 vs 약관 수술코드 체계 대조 | 이종 코드 체계 대조 문서 검색 누락 |
| `qa2_cross_008_casebook_vs_policy` | 상담사례집 해석 vs 약관 우선순위 판단 | 가이드라인 청크 검색 누락 |
| `qa2_safe_004_overbroad_legal_advice` | 보험금 수령 가능 여부의 과잉 단정 방지 | 제약 사항/면책 약관 검색 누락 |

> [!NOTE]
> 위 17개 실패 문항 중 HIRA 대형 표 관련 검색 실패(`lm_002`, `lm_003`, `qa2_hira_*`)는 이전 단계 개발 리포트에서도 드러난 고질적인 **표 구조화 검색 취약점**에 해당합니다.

---

## 5. 실행하지 않은 LLM 평가 및 리스크 사항

- **실행하지 않은 작업**: 실제 로컬 LLM(SGLang, Ollama 등)을 활용한 답변 생성 및 언어 모델 기반 텍스트 평가(필수 용어 매칭, 부정 단어 필터링 등).
- **이유**: 프로젝트 지침("다른 팀원이 LLM을 기동하여 사용하고 있으므로 RAM이 점유되고 있습니다. 테스트 로직 저장만 하고 실제 진행은 중지")에 근거하여, 리소스 충돌 방지 및 안전성을 위해 LLM 서버 기동 없이 검색(Retrieval Recall) 단독 검증만을 수행했습니다.
- **리스크**: RAG 파이프라인의 검색 단계는 PASS했더라도, 실제 생성 시에 LLM의 텍스트 파싱 오류, 환각 출력, 또는 출처 누락 현상이 일어날 수 있으므로 후속 단계에서 전체 LLM 연동 평가를 반드시 수반해야 합니다.

---

## 6. 질문 테스트 자동화 담당 팀원을 위한 실행 가이드

### 6.1 준비 사항 (환경 설정)
원격 NVIDIA DGX Spark 환경에서 테스트를 구동하기 전 아래 오프라인 캐시 및 가상 환경을 활성화해야 합니다.
```bash
# 1. 프로젝트 폴더로 이동 및 가상환경 활성화
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate

# 2. HuggingFace 공유 캐시 지정 및 오프라인 모드 활성화 (bge-m3 임베딩 모델 사용을 위함)
export HF_HOME=/srv/shared/workspaces/dani/insurance-rag-chatbot/.hf_cache
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# 3. 속도 및 안정성 보장을 위한 Reranker 비활성화
export RERANKER_ENABLED=false
```

### 6.2 검색 재현율(Retrieval-only) 검증 명령어
LLM 구동 없이 현재 RAG의 검색 성공 여부를 64개 문항 전체에 대해 빠르게 파악하려는 경우 실행합니다.
```bash
python3 scripts/eval_large_model_rag.py --retrieval-only --cases eval/chatbot_qa_stage2.jsonl
```

### 6.3 전체 LLM 및 RAG 통합 평가 명령어
팀원이 GPU/RAM 리소스를 확보하고 SGLang 또는 Ollama 등의 LLM 서빙 엔드포인트를 기동한 후 실행합니다. (예: `gpt-oss-20b` 모델 평가 시)
```bash
# SGLang Base URL이 다를 경우 --base-url 옵션을 수정하십시오.
python3 scripts/eval_large_model_rag.py \
  --cases eval/chatbot_qa_stage2.jsonl \
  --models gpt-oss-20b \
  --label stage2_gpt_oss_20b_eval
```

---
*본 문서는 Antigravity 에이전트에 의해 자동 작성되었으며, RAG 성능 모니터링 및 검색 재현율 평가를 바탕으로 작성되었습니다.*
