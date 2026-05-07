# 베타 단계 개발자 전달 프롬프트

> 작성일: 2026-05-07
> 기준 브랜치: `master`
> 기준 HEAD: `e2c7ae8 feat: add per-account chat persistence and multi-thread sidebar (M-ux-3/4)`
> 목적: 알파 완료 상태의 보험 문서 RAG 챗봇을 베타 1 개발로 이어받기 위한 Codex/개발자 작업 지시문

---

## 프롬프트

당신은 보험 문서 RAG 챗봇 프로젝트의 베타 단계 개발자입니다. 프로젝트는 신한EZ손해보험 사내 캡스톤 용도의 Streamlit 기반 보험 문서 RAG 챗봇이며, 현재 알파 구현은 완료된 상태입니다. Streamlit Cloud 배포도 이미 되어 있고 로그인 후 질의가 동작합니다.

### 1. 현재 상태를 먼저 확인하세요

작업 시작 전 아래 파일을 읽고 현재 구조를 파악하세요.

- `README.md`
- `docs/17_DEPLOY_GUIDE.md`
- `docs/19_PROJECT_STATUS_SUMMARY.md`
- `docs/20_INTEGRATION_ROADMAP.md`
- `docs/21_CODEX_SPEC_ALPHA_FINAL.md`
- `docs/22_CODEX_SPEC_UX_FIXES.md`
- `docs/24_UX_FIXES_IMPLEMENTATION_REPORT.md`

현재 핵심 파이프라인은 다음 구조입니다.

```text
BGE-M3 임베딩 -> Chroma dense 검색 -> BM25 -> RRF -> reranker -> LLM 답변 -> 출처 첨부
```

이 파이프라인은 베타 1에서 유지해야 합니다. 검색 품질 보정을 위해 메타데이터와 필터를 확장할 수는 있지만, 기존 로컬 테스트 및 Streamlit Cloud 질의 경로를 깨는 대규모 재작성은 하지 마세요.

### 2. 현재 알파 완료 범위

이미 완료된 기능은 다음과 같습니다.

- 멀티 문서 RAG: 심평원 고시, 약관, 보상가이드북 구조 지원
- 일반 질의, 퀵 코드 검색, 약관 정형 검색
- BGE-M3 + Chroma + BM25 + RRF + reranker
- OpenAI/Ollama LLM 선택
- Streamlit Cloud 배포 설정
- 역할 기반 로그인, 관리자 페이지, 감사 로그
- 검색 진단 탭
- 출처 expander와 PDF 미리보기
- 대화 내보내기
- 계정별 채팅 저장과 멀티 채팅 사이드바
- smoke QA v2와 회귀 테스트

최근 검증 기준:

```bash
pytest -q --ignore=tests/test_vector_store.py
# 119 passed, 5 warnings
```

### 3. 베타 1 목표

베타 1의 목표는 "다중 약관 + 메타 강화 + 약관 비교가 가능한 사내 테스트 버전"입니다.

우선순위는 다음 순서입니다.

1. M18 — 메타 스키마 확장
2. M19 — 다중 약관 배치 인제스트
3. M20 — 자사·타사/상품/시행일/보장종목 필터
4. M21 — 약관 비교 모드

OCR, GraphRAG, 보험금 자동 계산은 베타 1의 직접 구현 범위가 아닙니다. 단, 베타 1 설계가 Phase C/D 확장을 막지 않도록 데이터 구조와 인터페이스를 보수적으로 잡으세요.

### 4. M18 — 메타 스키마 확장

목표: 100개 이상 약관을 인덱싱할 때 검색 노이즈를 줄이기 위해 청크 메타데이터를 확장합니다.

권장 신규 메타 필드:

- `insurance_company`: 보험사명
- `is_own_company`: 자사 약관 여부
- `product_name`: 상품명
- `product_type`: 실손, 상해, 건강, 여행 등
- `effective_date`: 시행일
- `version`: 약관 버전 또는 개정 식별자
- `coverage_category`: 질병급여, 질병비급여, 3대비급여, 상해급여, 상해비급여 등
- `clause_type`: 보상하는 사항, 보상하지 않는 사항, 면책, 정의, 계약, 기타

구현 시 기존 `Chunk.metadata` 구조를 유지하면서 필드를 추가하세요. 기존 단일 약관/심평원 문서 인제스트가 깨지면 안 됩니다.

권장 산출:

- `src/config.py`의 문서 소스 정의 확장 또는 별도 메타 로더 추가
- `src/parser/chunker.py` 메타 주입 보정
- 관련 단위 테스트
- 메타 예시 파일 또는 문서

### 5. M19 — 다중 약관 배치 인제스트

목표: 여러 약관 PDF와 메타 정보를 한 번에 인덱싱할 수 있게 합니다.

권장 방향:

- `scripts/ingest_batch.py` 신규 작성
- 입력 예시:
  - `data/policies/` 하위 PDF 폴더
  - `data/policies/metadata.csv` 또는 `metadata.json`
- 출력은 기존 `data/chunks.jsonl`, `data/chroma/`, `data/bm25.pkl` 흐름과 호환
- 기존 `scripts/ingest.py` 단일/기존 인제스트 경로는 유지

수용 기준:

- 기존 `python scripts/ingest.py` 경로가 유지됨
- 샘플 메타 2~3건으로 배치 인제스트 테스트 가능
- 누락 메타가 있어도 명확한 오류 또는 기본값 처리
- `pytest -q --ignore=tests/test_vector_store.py` 통과

### 6. M20 — 필터 UI 및 검색 라우팅

목표: 사용자가 자사/타사, 상품명, 시행일, 보장종목 기준으로 검색 대상을 좁힐 수 있게 합니다.

권장 UI:

- 사이드바에 자사/타사 토글
- 보험사 선택
- 상품명 선택
- 시행일 또는 버전 선택
- 보장종목 선택

권장 검색 동작:

- 선택된 필터를 Chroma/BM25/RRF 이후의 hit 필터링 또는 검색 전 doc filter로 적용
- 질의에 보험사명/상품명이 명시된 경우 해당 메타를 우선 적용
- 필터가 너무 좁아 결과가 없을 경우 사용자에게 명확한 안내 표시

주의:

- 기존 `doc_short` 기반 필터는 유지하세요.
- 기존 일반 질의/퀵 코드/약관 정형 검색 모드가 모두 깨지지 않아야 합니다.

### 7. M21 — 약관 비교 모드

목표: 동일 질문 또는 보장종목에 대해 여러 약관의 관련 조항을 비교할 수 있게 합니다.

권장 방식:

- 검색 모드에 `약관 비교` 추가
- 입력:
  - 비교 질문
  - 비교 대상 보험사/상품 복수 선택
  - 보장종목 선택
- 출력:
  - 보험사/상품별 핵심 조항 요약
  - 보상/비보상/조건부 여부
  - 주요 출처
  - 차이점 요약 표

LLM 프롬프트는 기존 `src/llm/prompt.py` 패턴을 따르되, 출처 없는 단정은 금지하세요.

### 8. 검증 기준

모든 커밋 전 최소 검증:

```bash
pytest -q --ignore=tests/test_vector_store.py
python -c "import tomllib; tomllib.load(open('.streamlit/config.toml','rb'))"
git diff --check
```

가능하면 다음도 실행하세요.

```bash
HF_MODEL_DOWNLOAD=false python scripts/eval.py
HF_MODEL_DOWNLOAD=false python scripts/eval.py --v2
```

Streamlit Cloud는 이미 배포되어 있으므로, GitHub `master` push 후 Cloud 재시작으로 웹 테스트를 진행합니다.

### 9. 보안 및 배포 주의

- 실제 OpenAI API 키, 실제 사용자 비밀번호 hash, 실제 `USERS_JSON`을 커밋하지 마세요.
- `assets.zip`은 Git에 커밋하지 마세요. 릴리스 자산으로 관리합니다.
- `data/chat_history/`는 Git에 커밋하지 마세요.
- Streamlit Secrets의 배포 값은 `docs/17_DEPLOY_GUIDE.md`를 따릅니다.

커밋 전 보안 검색:

```bash
rg -n "sk-|sk-proj-|pbkdf2-sha256\\$29000" README.md docs src tests .env.example
```

placeholder(`sk-...`, `sk-test`)만 허용됩니다.

### 10. 커밋 및 보고 방식

- 기능 단위로 작은 커밋을 만드세요.
- 각 명세 기반 구현이 끝나면 `docs/`에 간결한 구현 보고서를 작성하세요.
- 기존 로컬/Cloud 파이프라인 영향 여부를 보고서에 명시하세요.
- GitHub push 전 `git status --short`로 의도하지 않은 파일이 staged 되었는지 확인하세요.

권장 베타 1 첫 커밋:

```text
feat: extend policy metadata schema for beta filters (M18)
```

---

## 베타 개발자에게 남기는 핵심 판단

베타 1은 GraphRAG나 OCR을 먼저 붙이는 단계가 아닙니다. 먼저 다중 약관을 안정적으로 넣고, 메타 필터로 검색 노이즈를 통제하는 것이 우선입니다. 현재 알파 파이프라인은 이미 웹 배포와 질의가 가능하므로, 베타 작업은 "검색 대상 확장과 업무 필터링" 중심으로 좁혀 진행하세요.
