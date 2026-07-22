# 246. 프로젝트 전체 로직 검토 및 다음 페이즈 개발 보고서

> 상태: P0~P2 수행 전 기준의 선행 검토 기록이다. P0~P2 수행 후 최신 원점 재검토와 남은 작업은 `docs/250_PROJECT_LOGIC_REVIEW_POST_P0_P2_FINDINGS.md`를 우선한다.

작성일: 2026-06-17  
기준 저장소: `/srv/shared/projects/insurance-rag-chatbot`  
기준 버전: `v1.0.6`  
기준 커밋: `8c9ceff chore(release): publish v1.0.6 project state`

## 1. 목적

이 문서는 DGX 메인 저장소 기준 현재 프로젝트 로직을 원점에서 검토하고, 다음 개발 페이즈에서 우선 수행해야 할 작업을 정리한다.

검토의 중심 기준은 다음과 같다.

- `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`의 하드코딩 지식 금지 원칙
- FastAPI + 정적 SPA를 정식 앱 경로로 두는 현재 운영 구조
- 보정본 OCR 데이터가 일반 질의와 평가의 기본 근거에 포함되어야 한다는 원칙
- 보험금 계산은 LLM 생성이 아니라 source-grounded rule layer에서 수행해야 한다는 원칙
- DGX Spark 환경에서 실제 기동 가능한 모델과 데이터만 운영 후보로 유지한다는 원칙

이번 검토에서는 코드 수정, 문서 정리, 데이터 삭제, 모델 서버 기동을 수행하지 않았다. 검토 결과와 다음 작업 범위만 정리한다.

## 2. 현재 기준 상태

### 2.1 Git 상태

DGX 메인 저장소는 검토 당시 다음 상태였다.

```text
## master...origin/master
```

현재 `master`는 GitHub 원격과 일치하며, `v1.0.6` 태그가 기준 커밋에 붙어 있다.

### 2.2 검증 결과

전체 테스트는 통과했다.

```bash
.venv/bin/python -m pytest -q
```

결과:

```text
726 passed, 3 warnings in 12.09s
```

추가로 다음 검증을 수행했다.

```bash
bash -n ops/bin/insurance-rag-common \
  ops/bin/insurance-rag-desktop-launcher \
  ops/bin/insurance-rag-up \
  ops/bin/switch-trtllm-model
```

```bash
node --check frontend/js/*.js frontend/js/modules/*.js frontend/js/pages/*.js frontend/js/ui/*.js
```

```bash
.venv/bin/python -m py_compile scripts/run_hospital_receipt_ocr.py
```

위 검증들은 모두 통과했다.

### 2.3 현재 구조 요약

현재 프로젝트는 다음 구성으로 운영된다.

- API: `src/api/main.py` 기반 FastAPI
- 프론트엔드: `frontend/` 정적 SPA
- 검색: BM25 + Chroma + RRF + reranker
- 일반 질의: 자동 Top-K/temperature + adaptive-k
- GraphRAG: `src/graph/` 기반 보험 개념/근거 경로 보강
- 온톨로지: 후보 추출, 실무자 승인, 개발용 자동 승인, approved manifest 기반
- 보험금 계산: 표준코드 매칭 + GraphRAG 근거 + deterministic 계산 + LLM 산식 보조 경로
- OCR: 약관/실무가이드/상담사례집 보정본 OCR index, 병원 영수증 OCR A-D 실험 harness
- 모델: SGLang/vLLM/OpenAI-compatible endpoint 중심, 120B는 DGX Spark 편입 불가 결론

## 3. 핵심 결론

현재 시스템은 테스트 기준으로 안정적이지만, 다음 페이즈의 주된 작업은 기능 추가가 아니라 **보험 지식이 코드에 남아 있는 부분을 source-grounded data/rule layer로 옮기는 것**이다.

특히 다음 영역은 `000번 원칙`과 충돌하거나 충돌 가능성이 크다.

1. 보험금 계산 공제율/한도/최소공제금액이 Python 상수로 남아 있다.
2. 일반 질의 답변 경로에 특정 질문 패턴별 deterministic answer block이 남아 있다.
3. GraphRAG extractor에 보험 한도/공제/키워드가 코드 상수로 남아 있다.
4. 오래된 README와 Streamlit 중심 설명이 현재 운영 구조와 충돌한다.
5. 120B 모델 편입 불가 결론이 일부 runtime metadata에 완전히 반영되지 않았다.

## 4. 우선순위별 다음 개발 작업

## P0. 보험금 계산 rule table 외부화

### 문제

`src/claim_calculation/deductible_rules.py`에는 다음 지식이 Python 상수로 직접 들어 있다.

- 4세대/5세대 공제율
- 급여/비급여/3대비급여/중증비급여/비중증비급여 구분
- 최소공제금액
- 건당 한도
- 연간 한도
- 처방약 공제금액

이는 `000번 원칙`의 다음 금지 항목과 직접 충돌한다.

- 공제율, 한도, 지급 조건을 Python 상수나 질문별 분기로 확정하는 방식
- 약관 개정 시 코드를 수정해야만 값이 바뀌는 구조
- 청구 항목명 문자열만 보고 코드에 박힌 공제율을 적용하는 것

### 다음 작업

계산 규칙을 코드가 아니라 approved rule table로 분리한다.

권장 구조:

```text
data/rules/
  claim_deductible_rules.schema.json
  claim_deductible_rules.active.json
  claim_deductible_rules.sources.jsonl
```

또는 SQLite 기반 rule registry:

```text
data/index/rules/claim_rules.sqlite
```

필수 필드:

- `rule_id`
- `generation`
- `category`
- `visit_type`
- `facility_grade`
- `copay_ratio`
- `min_deductible`
- `per_visit_limit`
- `annual_limit`
- `annual_visit_limit`
- `source_doc`
- `source_page`
- `source_clause`
- `source_chunk_id`
- `approval_status`
- `effective_from`
- `effective_to`

### 구현 원칙

- 계산기는 rule table을 읽고 해석만 한다.
- 코드에는 rule 값 자체를 두지 않는다.
- rule table에 source reference가 없으면 자동 계산에 쓰지 않는다.
- LLM은 계산식을 만들지 않고, 계산 결과 설명만 담당한다.
- 기존 `DeductibleRule` dataclass는 유지해도 되지만, 생성 원천은 파일/DB로 바꾼다.

### 검증 기준

- 기존 보험금 계산 테스트가 모두 통과해야 한다.
- rule 파일에서 값을 제거하면 계산 테스트가 실패해야 한다.
- source reference가 없는 rule은 계산에 사용되지 않아야 한다.
- 4세대/5세대 예시 계산 결과가 기존 평가셋과 일치해야 한다.

## P0. 일반 질의 deterministic answer block 제거

### 문제

`src/rag/pipeline.py`의 `_deterministic_guard_answer()`는 일부 질문에 대해 직접 답변을 구성한다.

확인된 위험 유형:

- 특정 코드 `QZ999`에 대한 직접 응답
- 특정 수술명/카테고리/지급비율 답변
- 4세대/5세대 비중증 비급여 공제 비교 계산
- 질문 문자열 패턴 기반 금액 계산

일부 guard는 안전장치로 볼 수 있지만, 수치와 지급률이 들어간 답변 블록은 하드코딩 지식으로 오해될 수 있다.

### 다음 작업

`_deterministic_guard_answer()`를 다음 두 종류로 분리한다.

1. 안전 guard
   - 근거 없음
   - 문서 충돌
   - 코드 미존재
   - source evidence 부족

2. source-grounded answer builder
   - clause_detail_rows
   - GraphDB fact
   - HIRA table row
   - approved rule table

직접 답변 블록은 제거하고, 필요한 답변은 source row에서 값과 문구를 읽어 구성한다.

### 검증 기준

- 기존 clause_detail 평가 문항이 통과해야 한다.
- 특정 질문 문장을 바꿔도 같은 source row가 검색되면 답변이 유지되어야 한다.
- source row를 제거하면 답변이 “근거 없음/검토 필요”로 바뀌어야 한다.
- 지급률/공제율/한도 값이 Python 문자열에 남아 있지 않아야 한다.

## P0. GraphRAG extractor 지식 상수 정리

### 문제

`src/graph/extractors.py`에는 다음 유형의 보험 지식 상수가 남아 있다.

- `BENEFIT_LIMITS`
- `DEDUCTIBLE_RULES`
- 특정 한도 키워드
- 특정 공제 topic
- 특정 지급/면책/한도 분류 keyword

GraphRAG extractor는 일반화된 extractor여야 하며, 보험 지식 자체는 ontology/rule manifest/source evidence에 있어야 한다.

### 다음 작업

Graph extractor를 다음 구조로 바꾼다.

```text
data/ontology/
  concepts.active.json
  relation_patterns.active.json
  claim_rule_markers.active.json
```

또는 기존 ontology manifest에 다음을 추가한다.

- benefit limit marker
- deductible marker
- claim unit marker
- exclusion marker
- required document marker

단, marker는 처리 기준만 담아야 하며 특정 상품의 정답 수치나 지급 판단을 담으면 안 된다.

### 검증 기준

- GraphDB rebuild 결과 node/edge 수가 기존과 비교 가능해야 한다.
- source evidence 없는 rule node가 생성되지 않아야 한다.
- extractor 설정 파일 변경만으로 새 문서 편입이 가능해야 한다.
- Python 코드 수정 없이 신규 PDF/Excel 데이터의 rule 후보 추출이 가능해야 한다.

## P1. LLM 산식 생성 경로 축소

### 문제

보험금 계산 파이프라인에는 `LLMPlanner`가 산식 코드를 생성하고, AST sandbox가 이를 실행하는 경로가 남아 있다.

현재는 deterministic baseline이 있는 경우 LLM 결과를 덮어쓰는 보호 로직이 있다. 그러나 baseline이 약하거나 표준코드 매칭이 부족한 경우 LLM 산식 경로가 계산 결과에 영향을 줄 수 있다.

### 다음 작업

LLM 산식 생성 경로를 운영 기본값에서 제거하거나, 다음 역할로 축소한다.

- 계산 가능/불가능 판단 금지
- 공제율/한도 생성 금지
- 실행 코드 생성 금지
- 누락 정보 질문 생성만 허용
- 계산 설명 문구 생성만 허용

계산은 rule table interpreter가 수행한다.

### 검증 기준

- LLM endpoint가 없어도 보험금 계산 핵심 경로가 동작해야 한다.
- LLM이 잘못된 산식을 반환해도 최종 계산값에 반영되지 않아야 한다.
- sandbox 실행 경로는 테스트/legacy로 격리되어야 한다.

## P1. README와 운영 문서 현실화

### 문제

`README.md`에는 아직 다음 과거 정보가 남아 있다.

- Streamlit 중심 운영 설명
- Discord bot 중심 조작 설명
- Ollama 기본 모델 설명
- 베타 Stage 2 상태
- 보험금 자동 계산 미착수 설명

현재 공식 구조는 FastAPI + SPA + DGX + SGLang/vLLM + GraphRAG + 온톨로지 승인 + 보험금 계산이다.

### 다음 작업

README를 현재 운영 구조 기준으로 축소한다.

권장 구성:

- 프로젝트 개요
- 현재 공식 실행 경로
- DGX 운영 경로
- 로컬 개발 경로
- 데이터/원본 문서 Git 제외 원칙
- 테스트 명령
- legacy Streamlit 상태
- 문서 index

Streamlit은 “보존된 legacy”로만 표시한다.

### 검증 기준

- README만 보고도 현재 앱 실행 경로가 FastAPI + SPA임을 알 수 있어야 한다.
- Streamlit을 신규 기능 대상으로 오해하지 않아야 한다.
- 데이터/비밀/원본 문서 Git 금지 원칙이 명확해야 한다.

## P1. 120B 모델 편입 불가 결론의 runtime metadata 반영

### 문제

SGLang model metadata에서는 `gpt-oss-120b`가 disabled로 표시되어 있다. 하지만 TRTLLM model metadata에는 120B가 `experimental`로 남아 있다.

현재는 `TRTLLM_STRICT_AVAILABLE_MODELS=true`라 endpoint가 살아 있지 않으면 노출되지 않는 보호가 있다. 즉시 장애는 아니지만, 프로젝트 결론과 metadata 표현이 완전히 일치하지 않는다.

### 다음 작업

120B를 다음 상태로 정리한다.

- 운영 후보: 제외
- 테스트 후보: 제외
- 문서상 보존: “DGX Spark 단일 장비 편입 불가”
- 코드상 상태: `disabled` 또는 `unsupported_on_dgx_spark`

TRTLLM 스위치 스크립트는 삭제하지 않아도 된다. 다만 기본 경로로 오해되지 않도록 metadata와 launcher 안내를 정리한다.

### 검증 기준

- `/api/system/models`에서 120B가 일반 선택 후보로 나오지 않아야 한다.
- endpoint가 우연히 살아 있지 않은 상태에서 120B 선택지가 나타나지 않아야 한다.
- 120B 관련 스크립트는 “실험/보존” 상태가 명확해야 한다.

## P1. clause_detail_rows 기본 경로와 데이터 패키징 정리

### 문제

`clause_detail_rows`는 `v2_only`, `v1_v2_combined`에는 존재하지만, 기본 `data/index/clause_detail_rows.jsonl`은 존재하지 않았다.

현재 chat route는 기본 index를 `v2_only`로 강제하므로 일반 사용 경로에서는 큰 문제는 아니다. 그러나 API나 내부 호출에서 `default`를 쓰면 clause_detail_rows 기반 보강이 빠질 수 있다.

### 다음 작업

- 운영 기본 index를 명확히 `v2_only`로 통일한다.
- `default`라는 이름이 OCR 제외처럼 보이지 않도록 제거하거나 alias 처리한다.
- clause_detail_rows 생성 여부를 app startup/system diagnostics에 표시한다.

### 검증 기준

- 일반 질의에서 OCR 보정본 index가 빠지는 경로가 없어야 한다.
- clause_detail_lookup 문항이 `v2_only`에서 source row 기반으로 응답해야 한다.
- row 파일 누락 시 경고가 표시되어야 한다.

## P1. 신규 파일 추가/DB화 파이프라인 설계 착수

### 문제

사용자 목표는 운영 중에도 PDF/Excel 신규 편입이 가능하고, 신규 로직 개발 없이 DB화와 온톨로지 편입까지 이어지는 구조다.

현재는 개별 스크립트와 실험 구현은 많지만, 앱의 “신규 파일 추가” 진입점부터 ingestion, table extraction, OCR/digital PDF 분기, ontology candidate generation, index rebuild까지 이어지는 통합 워크플로우는 아직 완성되지 않았다.

### 다음 작업

최소 버전은 다음 단계까지만 구현한다.

1. 파일 업로드/선택
2. 파일 타입 판정
   - Excel
   - digital PDF
   - scanned PDF/image
3. 처리 계획 dry-run 표시
4. 사용자가 승인하면 batch job 실행
5. 산출물 검증
6. index rebuild
7. ontology candidate 생성
8. 실무자 승인 대기 상태 표시

### 검증 기준

- 새 파일 추가 후 코드 수정 없이 검색 가능해야 한다.
- 처리 실패 시 원본 파일과 산출물이 추적 가능해야 한다.
- 원본/대용량 산출물은 Git에 들어가지 않아야 한다.

## P2. 데이터와 저장공간 운영 정리

### 확인된 상태

검토 당시 대략적인 크기는 다음과 같았다.

```text
data        9.5G
.git        28G
.venv       6.5G
.venv-vllm  8.0G
```

또한 ignored 상태의 다음 산출물이 많이 남아 있다.

- OCR backup index
- processed backup
- hospital receipt runtime output
- `._*` macOS AppleDouble 파일
- `__pycache__`
- 과거 batch report
- 대용량 원본 PDF/XLSX

### 다음 작업

삭제는 별도 승인 작업으로 분리한다.

권장 순서:

1. 현재 운영에서 쓰는 index와 DB를 식별한다.
2. 삭제 후보와 보존 후보를 표로 만든다.
3. `/tmp` 또는 외부 archive로 이동 가능한 파일을 먼저 분리한다.
4. Git pack 27GiB 문제는 history rewrite가 필요하므로 별도 프로젝트로 분리한다.

### 검증 기준

- 삭제 전후 `du`, `df`, app smoke test를 남긴다.
- 운영 index, DB, approved ontology manifest를 삭제하지 않아야 한다.
- 삭제 대상은 commit하지 않는다.

## P2. 병원 영수증 OCR 기능의 운영 범위 결정

### 현재 결론

A-D 온디바이스 OCR 실험 결과만으로는 병원 영수증 세부내역을 자동 보험금 계산 입력으로 승격하기 어렵다.

따라서 다음 페이즈에서는 둘 중 하나를 선택해야 한다.

1. 병원 영수증 OCR을 운영 계산 자동화 범위에서 제외하고, human review 입력 보조로만 둔다.
2. 외부 OCR 또는 전문 문서 AI 사용 가능성을 별도 정책 검토 대상으로 둔다.

망분리/온디바이스 원칙을 유지한다면 1번이 현실적이다.

### 다음 작업

- OCR 결과를 claim_items_ready로 자동 승격하는 조건을 매우 보수적으로 유지한다.
- 검증 실패 row는 human task로만 남긴다.
- 영수증 OCR UI는 “자동 계산”이 아니라 “입력 초안 생성”으로 표현한다.

### 검증 기준

- 검증 실패 row가 자동 계산에 들어가지 않아야 한다.
- 합계 불일치/column shift/OCR 누락이 human task에 남아야 한다.
- 개인정보/민감정보가 로그에 노출되지 않아야 한다.

## P2. 테스트 체계 정리

### 현재 상태

전체 pytest는 빠르고 안정적으로 통과한다. 다만 실제 운영 검증은 다음 범위가 섞여 있다.

- 순수 단위 테스트
- RAG 검색 테스트
- GraphDB 테스트
- OCR 실험 테스트
- LLM endpoint 의존 테스트
- DGX runtime smoke

### 다음 작업

테스트를 marker 기준으로 나눈다.

권장 marker:

- `unit`
- `api`
- `rag`
- `graph`
- `ocr`
- `llm`
- `dgx`
- `slow`

기본 CI/로컬 검증은 `unit + api + rag lightweight`만 실행하고, DGX runtime 검증은 별도 명령으로 분리한다.

### 검증 기준

- 기본 테스트가 1분 안에 끝나야 한다.
- DGX 모델 서버가 없어도 기본 테스트는 실패하지 않아야 한다.
- LLM/OCR heavy 테스트는 명시적으로 선택해야 한다.

## 5. 권장 개발 순서

다음 페이즈는 아래 순서가 가장 안전하다.

### Phase 1. 계산 rule table 외부화

가장 먼저 해야 한다. 보험금 계산은 사용자 신뢰와 직접 연결되며, 현재 가장 명확한 000번 원칙 위반 후보가 이 영역이다.

작업 결과:

- `deductible_rules.py`의 수치 상수 제거
- approved rule table 추가
- rule source reference 추가
- 기존 계산 테스트 유지

### Phase 2. deterministic answer block 제거

일반 질의 답변에서 질문별 하드코딩을 제거한다.

작업 결과:

- `_deterministic_guard_answer()` 축소
- source-grounded answer builder로 대체
- clause_detail_rows/HIRA/GraphDB 기반 답변 강화

### Phase 3. GraphRAG extractor 정책화

Graph extractor의 보험 지식 상수를 ontology/rule marker로 이동한다.

작업 결과:

- Graph rebuild 재현성 강화
- 신규 문서 편입 확장성 확보
- 하드코딩 지식 감소

### Phase 4. 운영 모델 registry 정리

120B 편입 불가 결론을 code metadata와 launcher 안내에 반영한다.

작업 결과:

- 120B가 일반 모델 후보로 오해되지 않음
- Qwen/Gemma 등 실제 사용 모델만 운영 후보로 유지

### Phase 5. README와 운영 문서 정리

현재 구조와 충돌하는 오래된 안내를 정리한다.

작업 결과:

- 신규 개발자가 README만 보고도 현재 앱 구조를 이해
- Streamlit legacy 혼동 제거
- DGX 실행/검증 절차 정리

### Phase 6. 신규 파일 추가 파이프라인 설계/구현

계산/답변 하드코딩 제거가 어느 정도 끝난 뒤 진행하는 것이 좋다. 신규 파일 편입은 기존 지식 체계가 source-grounded로 정리된 다음 붙여야 한다.

## 6. 당장 시작할 목표 설정 프롬프트

다음 작업을 시작할 때 사용할 수 있는 목표 프롬프트는 아래와 같다.

```text
DGX 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot` 기준으로 000번 원칙을 준수하도록 보험금 계산 rule table 외부화 작업을 수행하세요.

목표:
1. `src/claim_calculation/deductible_rules.py`에 남아 있는 공제율, 최소공제금액, 한도, 처방약 공제금액 등 보험 계산 지식 상수를 approved rule table 또는 source-grounded rule manifest로 분리합니다.
2. Python 코드는 rule 값을 보유하지 않고, rule table을 로드해 deterministic interpreter로 계산만 수행하게 합니다.
3. rule row에는 generation, category, visit_type, facility_grade, copay_ratio, min_deductible, per_visit_limit, annual_limit, source_doc, source_page/source_clause/source_chunk_id, approval_status를 포함합니다.
4. source reference가 없거나 approval_status가 active가 아닌 rule은 자동 계산에 사용하지 않습니다.
5. 기존 보험금 계산 테스트를 유지하고, rule table 누락/invalid 상태에서 계산이 실패하거나 review_required로 전환되는 회귀 테스트를 추가합니다.

검증:
- `.venv/bin/python -m pytest tests/test_claim_calculation_pipeline.py tests/test_claim_code_sandbox.py tests/test_claim_planner.py -q`
- 가능하면 `.venv/bin/python -m pytest -q`
- 000번 원칙 위반 여부를 self-inspection으로 보고합니다.

주의:
- 특정 상품의 지급 판단을 새 정책 파일에 임의로 추가하지 마세요.
- LLM이 계산 rule을 생성하게 하지 마세요.
- 원본 PDF/XLSX, OCR 산출물, 대용량 runtime data는 커밋하지 마세요.
```

## 7. 남은 위험

- 테스트는 통과하지만, 테스트 통과가 000번 원칙 준수를 보장하지는 않는다.
- 현재 계산 rule은 동작상 안정적일 수 있으나, 약관 개정이나 신규 상품 편입 시 코드 수정이 필요하므로 확장성 위험이 크다.
- deterministic answer block은 품질 보정 목적으로 생긴 것으로 보이나, 장기적으로는 평가 문항 최적화처럼 보일 위험이 있다.
- GraphRAG extractor는 현재 성능을 위해 keyword 기반 보강이 많다. 이를 무조건 제거하면 검색 품질이 떨어질 수 있으므로, 삭제가 아니라 policy/ontology 이동이 맞다.
- README 정리는 기능 안정화 이후 해도 되지만, 팀 협업 혼동을 줄이려면 오래 미루지 않는 편이 좋다.

## 8. 결론

다음 페이즈의 핵심은 새 기능 추가보다 **하드코딩 지식 제거와 source-grounded rule/data layer 강화**다.

우선순위는 다음과 같다.

1. 보험금 계산 rule table 외부화
2. 일반 질의 deterministic answer block 제거
3. GraphRAG extractor 지식 상수 정책화
4. 120B 모델 편입 불가 상태 metadata 정리
5. README/운영 문서 현실화
6. 신규 파일 추가 파이프라인 구현

이 순서를 따르면 현재 기능을 유지하면서도, 신규 PDF/Excel 편입과 온톨로지 확장을 코드 수정 없이 수행할 수 있는 구조에 가까워진다.
