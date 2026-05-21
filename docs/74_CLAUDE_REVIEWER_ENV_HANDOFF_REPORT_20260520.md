# Claude 검토자 전달용 환경/운영 보고서 (2026-05-20)

## 1) 목적

본 문서는 현재 프로젝트의 실제 개발/운영 구조와 SGLang 전환 진행 상태를 Claude(검토자/기획자)가 빠르게 파악하고, 리뷰/명세 작업을 일관되게 수행할 수 있도록 정리한 핸드오프 보고서다.

## 2) 현재 협업 구조 (확정)

- 개발자(개인): VS Code Remote SSH로 DGX 각자 계정에서 개인 Codex/Claude 사용
- 공용 운영/검증: `ai-hang` 계정의 공용 wrapper 및 점검 스크립트 사용
- 프로젝트 메인 경로(DGX): `/srv/shared/projects/insurance-rag-chatbot`
- Streamlit 운영 흐름:
  - DGX 내부: `127.0.0.1:8501`
  - 사용자 접속: `ssh -L 8501:localhost:8501 ...` 후 `http://localhost:8501`

## 3) LLM 운영 현황

- 현재 안정 운영 baseline: Ollama `exaone3.5:7.8b`
- 전환 목표: SGLang(OpenAI-compatible endpoint) 기반 로컬 LLM
- 원칙: 완전 교체가 아닌 **Ollama fallback 유지**

관련 문서:
- `docs/72_DGX_SPARK_SGLANG_LOCAL_LLM_PLAN.md`
- `docs/73_DGX_SGLANG_C_STAGE_EXECUTION_AND_PROVIDER_UI_PLAN.md`

## 4) Stage 진행 상태

- Stage1 handoff 패키지 로컬 준비 완료
  - `handoff/llm_stage1_20260519/downloads/models/gpt-oss-20b`
  - `handoff/llm_stage1_20260519/downloads/models/Gemma-4-26B-A4B-NVFP4`
  - `handoff/llm_stage1_20260519/downloads/sglang_wheelhouse`
- 현재 C단계: DGX에서 SGLang 설치/실행 확인 진행 중

## 5) 코드 관점 핵심 사실 (리뷰 포인트)

1. Streamlit 앱은 `src/llm/factory.py` 기반 분기 구조를 이미 보유
2. 다만 `scripts/eval.py`, `scripts/cli.py`는 Ollama 직접 의존이 남아 있음
3. 따라서 “UI 답변 경로 전환”과 “평가/CLI 완전 전환”은 분리해서 검증해야 함

## 6) Claude 리뷰 요청 우선순위

1. **Provider 추상화 일관성 리뷰**
   - `scripts/eval.py`, `scripts/cli.py`를 factory/provider 기반으로 전환하는 명세 타당성 검토
2. **UI 설계 리뷰**
   - 모델 드롭다운 외에 Provider 드롭다운(Ollama/SGLang) 분리 도입안 검토
3. **회귀 리스크 리뷰**
   - 기존 retrieval/eval 기준(청크/인덱스/recall)을 깨지 않는 전환 절차 검증
4. **운영 롤백 리뷰**
   - SGLang 장애 시 Ollama 즉시 복귀 경로의 절차/로그 기준 검토

## 7) Provider 드롭다운 확장 사양(후속 구현 기준)

- 추가 UI:
  - `LLM Provider`: `Ollama`, `SGLang(OpenAI-compatible)`
  - `Model`: Provider별 후보군만 표시
- 세션 상태:
  - `selected_provider`
  - `selected_model_by_provider`
- 환경변수(예정):
  - `LOCAL_LLM_PROVIDER`
  - `LOCAL_LLM_BASE_URL`
  - `LOCAL_LLM_API_KEY`
  - `LOCAL_LLM_MODEL`
  - `LOCAL_LLM_CANDIDATE_MODELS`
- 제약:
  - 앱 모델명은 served-model-name 사용(물리 경로 미노출)

## 8) 운영/보안 주의사항

- 모델 파일/휠/압축 파일은 Git 커밋 금지
- secrets(`env.sh`, API 키, JSON key 등) 출력/공유 금지
- 공용 repo는 검증 완료된 결과만 반영
- 대형 모델 전환은 단일 모델 운영 안정화 후 확장

## 9) 즉시 다음 액션

1. C단계 완료 증적 수집 (`/v1/models`, `/v1/chat/completions` 테스트)
2. Streamlit 경유 응답 확인(성능/품질/안정성 3축)
3. 실패 시 즉시 Ollama fallback 복귀
4. 이후 provider 드롭다운 분리 구현 명세 확정 및 코드 작업 착수

## 10) 참고

- DGX 운영 기본 런북: `docs/DGX_SPARK_RUNBOOK.md`
- AI 리뷰어 가이드: `docs/AI_REVIEWER_GUIDE.md`
- 본 보고서 작성 기준일: **2026-05-20**
