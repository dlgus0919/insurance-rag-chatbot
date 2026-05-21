# 89. Docs Index Collision Repair And Project Improvement Spec

작성일: 2026-05-21
작성 위치: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`
목적: `docs/` 문서 번호 충돌을 안전하게 보정하고, 현재 개발 상태에서 확인된 구조적 결점과 개선 방법론을 정리한다.

## 1. 현재 저장소 기준

- 기준 저장소: `https://github.com/koreaben777/insurance-rag-chatbot.git`
- 기준 디렉터리: `/srv/shared/projects/insurance-rag-chatbot`
- 현재 개발 기준은 Mac 로컬 저장소가 아니라 DGX Spark 메인 저장소다.
- 현재 앱 구조는 FastAPI 백엔드가 아니라 Streamlit 중심 RAG 앱이다.
- 주요 구성:
  - `src/rag/`: 검색, 프롬프트, 답변 생성 파이프라인
  - `src/retrieval/`: BM25/Chroma/reranker 검색 계층
  - `src/llm/`: Ollama, SGLang, vLLM, OpenAI-compatible provider 계층
  - `src/ui/`: Streamlit 사용자/관리자 UI
  - `scripts/`: ingestion, eval, large-model 평가, offline asset 준비 스크립트
  - `tests/`: pytest 회귀 테스트
  - `docs/`: 설계, 운영, 구현 보고서

## 2. Docs 번호 충돌 진단

2026-05-21 기준 `docs/*.md`의 2자리 숫자 prefix를 점검한 결과:

- 번호가 붙은 문서 수: 129개
- 사용 중인 최대 번호: `88`
- 중복 prefix 그룹: 26개
- 중복으로 추가 발생한 문서 수: 43개

중복 그룹은 다음과 같다.

```text
03, 05, 36, 39, 40, 41, 42, 43, 44, 45, 46, 48, 49, 50, 51,
54, 55, 56, 57, 58, 59, 60, 63, 64, 65, 67
```

### 2.1 원인

대부분의 중복은 단순 실수가 아니라 과거 작업 단위에서 같은 번호를 `SPEC`, `TASK`, `REPORT`, `PROMPT`, `RESULT` 문서 묶음으로 사용하면서 생긴 역사적 구조다. 예를 들어 하나의 개발 단계 번호 아래에 작업 명세, 실행 로그, 리뷰 보고서가 함께 존재한다.

### 2.2 위험

기존 문서 129개를 기계적으로 전부 rename하면 다음 위험이 크다.

- 과거 보고서와 대화에서 참조한 파일명이 깨진다.
- 외부 에이전트가 이미 인용한 문서 경로가 깨진다.
- Git history상 문서 의미보다 파일명 변경 noise가 커진다.
- 현재 개발과 무관한 대량 변경이 발생한다.

따라서 이번 보정은 기존 중복 파일명을 대량 변경하지 않고, 정책과 반입 규칙을 확정하는 방식으로 수행한다.

## 3. 보정 정책

### 3.1 역사적 문서 freeze

`01`부터 `88`까지의 기존 문서는 역사적 산출물로 freeze한다.

- 기존 중복 prefix는 즉시 rename하지 않는다.
- 기존 문서 링크와 참조를 보존한다.
- 이후 특정 문서를 재정리해야 할 때만 별도 승인 하에 rename 또는 archive 이동을 수행한다.

### 3.2 신규 문서 번호 정책

이 문서 이후 새 문서는 다음 원칙을 따른다.

- 새 numbered 문서는 `89` 이후 번호를 단조 증가로 사용한다.
- 같은 prefix를 재사용하지 않는다.
- 하나의 작업에 여러 문서가 필요하면 번호를 분리한다.
  - 예: `90_..._SPEC.md`, `91_..._IMPL_REPORT.md`, `92_..._EVAL_REPORT.md`
- 예외적으로 unnumbered 운영 문서는 `RUNBOOK`, `GUIDE`, `POLICY` 이름을 사용할 수 있으나, numbered 문서와 혼동되지 않게 한다.

### 3.3 외부 문서 반입 규칙

외부 에이전트가 작성한 문서가 내부적으로 `69`부터 `74` 같은 번호를 사용하더라도, DGX 저장소에 그대로 반입하지 않는다.

- 외부 번호는 원문 metadata로만 남긴다.
- DGX `docs/` 반입 시점의 다음 사용 가능 번호를 새로 부여한다.
- 예: 외부 `69_BACKEND_FINAL_DELIVERY_REPORT.md`는 현재 저장소에 반입한다면 `90_BACKEND_FINAL_DELIVERY_REPORT_IMPORTED.md`처럼 재번호화한다.
- 반입 문서 상단에 원본 경로, 원본 번호, 반입일, 반입자를 기록한다.

### 3.4 향후 정리 방법론

대규모 정리가 필요해질 경우 다음 절차를 따른다.

1. `docs/DOCS_INDEX.md`를 별도로 만들어 현행 파일명, 새 파일명, 문서 역할, 참조 관계를 표로 정리한다.
2. rename 대상은 active runbook/spec 위주로 제한한다.
3. 과거 보고서는 `docs/archive/`로 이동하되 원본 번호와 제목을 유지한다.
4. rename 전후 링크 검사를 수행한다.
5. rename만 하는 커밋과 내용 변경 커밋을 분리한다.

## 4. 현재 개발 현황 요약

현재 프로젝트는 보험 문서 RAG 챗봇으로서 다음 기능 축이 구현되어 있다.

- OCR 기반 보험 문서 데이터 추출 및 수동 보정 데이터 관리
- Chroma/BM25 기반 검색 인덱스와 retrieval eval
- Streamlit 기반 사용자/관리자 UI
- 로컬 LLM provider: Ollama, SGLang, vLLM 경로
- SGLang/vLLM 기반 대형 모델 편입 시도 및 DGX Spark 운영 문서화
- 완전 오프라인 실행을 위한 asset download/check 스크립트 기반 설계
- 최근 RAG grounding 강화를 위한 source coverage, evidence guard, document coverage prompt 개선

최근 검증 기준으로는 전체 pytest가 `276 passed`까지 확인된 이력이 있다. 다만 이 문서는 문서/구조 검토 명세이므로 대형 LLM 호출이나 장시간 eval은 수행하지 않았다.

## 5. 발견된 결점과 개선 여지

### 5.1 Backend 아키텍처 불일치

`docs/88_BACKEND_ARCHITECTURE_GAP_ANALYSIS.md`가 지적한 것처럼, 외부 backend delivery report는 FastAPI, SQLAlchemy, JWT/RBAC, PostgreSQL/Supabase 수준의 백엔드 구현 완료를 전제하지만 현재 DGX 저장소에는 해당 구현이 없다.

현재 repo의 실제 상태는 Streamlit 앱과 파일/JSON 기반 상태 저장에 가깝다.

개선 방법:

- 먼저 `ADR`을 작성해 Streamlit monolith 유지, FastAPI backend 전환, hybrid 구조 중 하나를 결정한다.
- 바로 FastAPI 대전환을 하지 말고 `src/rag`와 `src/llm`의 service boundary를 먼저 정리한다.
- API 전환이 필요하면 인증, 세션, 채팅 이력, 평가 실행, 관리자 기능을 endpoint 단위로 쪼개 phased migration한다.
- 외부 backend 문서는 import 전 재검증하고 현재 repo와 diffable한 코드 산출물이 있는지 확인한다.

### 5.2 문서 체계 sprawl

문서 수가 많고 번호 중복이 많아 신규 참여자가 최신 기준 문서를 찾기 어렵다.

개선 방법:

- 신규 문서는 `89` 이후 unique index를 사용한다.
- `README` 또는 `docs/00_START_HERE.md` 성격의 진입 문서를 갱신해 현재 기준 문서 5~10개만 안내한다.
- 과거 문서는 archive로 묶되 경로 변경은 별도 승인 후 수행한다.
- 외부 에이전트에게는 `87_AI_SUBDEVELOPER_ONBOARDING_HANDOFF.md`, `88_BACKEND_ARCHITECTURE_GAP_ANALYSIS.md`, 본 문서를 우선 읽히도록 한다.

### 5.3 근거 해석 오류와 structured evidence 부족

최근 로봇수술 코드 사례처럼 문서별 코드가 다를 때 LLM이 검색 결과를 통합·평균화하여 답하는 위험이 있다. 프롬프트 강화만으로는 완전 해결이 어렵다.

개선 방법:

- 문서별 row-level table index를 구축한다.
- HIRA/심평원 코드, 약관 코드, 지급 기준처럼 값 충돌 가능성이 큰 필드는 structured lookup을 우선 적용한다.
- LLM prompt에는 `문서별 값이 다르면 통합하지 말고 분리 보고` 원칙을 유지하되, 최종 판단은 retrieval 결과의 구조화 metadata에 의존한다.
- 자동 평가셋에 single-document, cross-document, conflict-aware 질의를 추가한다.

### 5.4 Provider와 모델 선택 UX 복잡도

현재 목표는 SGLang/vLLM 대형 모델을 운영하고 Ollama를 fallback으로 유지하는 것이다. 그러나 모델별 provider 지원 가능성이 다르며, 모든 모델을 모든 provider에서 동일 성능으로 제공할 수는 없다.

개선 방법:

- `provider -> model` 매핑을 config로 명확히 관리한다.
- UI에서는 provider 선택 후 해당 provider에서 사용 가능한 모델만 표시한다.
- 대형 모델은 앱 시작 전 또는 로그인 단계에서 1개를 선택해 로드하고, 소형 Ollama 모델은 세션 중 전환 가능하게 유지한다.
- Gemma4는 vLLM 경로를 포함해 별도 smoke/eval 결과를 축적한 뒤 기본값 후보로 승격한다.

### 5.5 완전 오프라인 실행 보장 부족

오프라인 실행 계획과 asset download script는 존재하지만, 실제 망분리 조건에서 embedding, reranker, tokenizer, LLM runtime이 외부 다운로드 없이 동작하는지 지속적으로 검증해야 한다.

개선 방법:

- `OFFLINE_MODE=true`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` 조건에서 별도 smoke test를 CI-like 절차로 만든다.
- embedding/reranker/model/tokenizer 경로 manifest를 관리한다.
- 다운로드 스크립트는 asset manifest와 checksum을 항상 생성한다.
- 캐시 미스 시 자동 다운로드하지 말고 명시적 오류와 복구 명령을 출력한다.

### 5.6 DGX 공유 개발 운영 리스크

DGX는 여러 팀원과 AI agent가 함께 사용하는 공유 개발 환경이다. 동시에 같은 master, 같은 port, 같은 GPU memory를 다루면 충돌 가능성이 있다.

개선 방법:

- 개인 작업은 `/srv/shared/workspaces/<user>/insurance-rag-chatbot` 또는 개인 branch에서 수행한다.
- `/srv/shared/projects/insurance-rag-chatbot`는 통합/운영 repo로 취급한다.
- 대형 LLM 테스트 전에는 `nvidia-smi`, `tmux ls`, 8501/30000/8000 port 사용 여부를 확인한다.
- push 전에는 `git status --short`, `git log --oneline -5`, 관련 테스트 결과를 보고한다.

### 5.7 보안과 runtime artifact 관리

모델 파일, handoff tarball, secrets, `.venv-*`, logs, runtime DB가 Git에 섞일 위험이 있다.

개선 방법:

- `.gitignore`에 모델/handoff/runtime 경로를 명시적으로 유지한다.
- push 전 `git status --short`에서 대형 파일과 secrets가 없는지 확인한다.
- `/srv/ai-ops/secrets`, `env.sh`, token 파일은 절대 출력하거나 커밋하지 않는다.
- 필요한 경우 secret scanner 또는 최소한 확장자/경로 기반 preflight 스크립트를 추가한다.

## 6. 개선 우선순위

### P0: 문서 인덱스와 기준 문서 정리

- 본 문서를 기준으로 `89` 이후 unique numbering을 적용한다.
- 외부 backend 문서 69~74는 그대로 반입하지 않는다.
- 신규 참여자에게 읽힐 최신 기준 문서 목록을 정한다.

완료 기준:

- 새 문서가 기존 prefix를 재사용하지 않는다.
- 외부 문서 반입 시 새 번호와 원본 metadata가 남는다.

### P1: 근거 충돌 인식형 RAG 평가 강화

- 문서별 코드/수치가 다른 질의를 포함한 평가셋을 추가한다.
- LLM 호출 없이 retrieval result만으로 conflict detection을 테스트한다.
- table row metadata와 source coverage를 평가 지표에 포함한다.

완료 기준:

- 문서별 값 충돌 질의에서 답변이 값을 통합하지 않고 분리하도록 검증된다.
- 관련 회귀 테스트가 추가된다.

### P1: Provider/model mapping 안정화

- provider별 지원 모델 config를 명확히 한다.
- Streamlit UI에서 provider와 model 선택지가 일관되게 표시된다.
- SGLang/vLLM/Gemma4/Ollama fallback의 운영 상태를 문서화한다.

완료 기준:

- 지원 불가능한 provider/model 조합이 UI에 나타나지 않는다.
- fallback 전환 방법이 문서와 wrapper로 재현 가능하다.

### P2: 오프라인 실행 검증 자동화

- offline asset manifest/checksum을 표준화한다.
- `OFFLINE_MODE=true` smoke test를 만든다.
- 외부 네트워크 없이 Streamlit 기동과 retrieval eval이 가능함을 검증한다.

완료 기준:

- embedding/reranker/tokenizer가 로컬 경로에서만 로드된다.
- 캐시 미스는 외부 다운로드 대신 명시적 실패로 처리된다.

### P2: Backend 방향성 ADR

- Streamlit 유지, FastAPI 전환, hybrid 중 하나를 결정한다.
- 전환한다면 API contract와 migration phase를 작성한다.

완료 기준:

- 외부 backend report와 현재 repo의 불일치가 해소되거나 폐기 결정된다.
- 다음 개발자가 어떤 backend 방향으로 작업해야 하는지 모호하지 않다.

## 7. 권장 검증 명령

문서 변경만 있을 때:

```bash
git status --short
git diff --check
```

코드 변경이 포함될 때:

```bash
pytest -q
```

RAG retrieval 회귀 확인:

```bash
RERANKER_ENABLED=false python scripts/eval.py --ocr
```

오프라인 smoke:

```bash
OFFLINE_MODE=true HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false python scripts/eval.py --ocr
```

대형 모델 검증은 GPU 점유와 팀원 작업 상태를 먼저 확인한 뒤 수행한다.

## 8. 이번 보정의 범위

이번 보정에서 수행한 것:

- 기존 `docs/` 번호 충돌 현황을 계량화했다.
- 기존 중복 문서를 대량 rename하지 않는 정책을 확정했다.
- `89` 이후 신규 문서 번호는 unique하게 관리하는 규칙을 세웠다.
- 외부 backend 문서의 69~74 번호를 그대로 반입하지 않는 규칙을 명시했다.
- 현재 개발 현황의 주요 결점과 개선 방법론을 우선순위별로 정리했다.

이번 보정에서 수행하지 않은 것:

- 기존 129개 numbered 문서의 대량 rename
- 과거 문서 archive 이동
- FastAPI backend 구현
- 대형 LLM 실행 또는 Streamlit GPU 테스트
- Git commit/push

위 항목들은 별도 승인과 작업 단위 분리가 필요하다.
