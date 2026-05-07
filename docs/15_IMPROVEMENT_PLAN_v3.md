# RAG 챗봇 개선 계획서 v3 — 역할 인증 · OpenAI 통합 · 클라우드 배포

> **작성:** 기획자
> **작성일:** 2026-05-06
> **기반 상태:** M14 완료 (카테고리 필터·퀵 코드·약관 정형 검색·PDF 미리보기 적용된 Streamlit 알파)
> **대상 마일스톤:** M15 → M16 → M17
> **참고:** [13_IMPROVEMENT_PLAN_v2.md](./13_IMPROVEMENT_PLAN_v2.md) · [14_CODEX_SPEC_M13M14.md](./14_CODEX_SPEC_M13M14.md)

---

## 1. 배경

현 챗봇은 사내 임직원용 단일 비밀번호 게이트, Ollama 기반 로컬 LLM, 로컬 실행 전용 환경에서 동작합니다 (M12·M14). 사용자(현장 운영자)가 다음 세 가지 확장을 요청했습니다.

1. 일반 직원 / 시스템 관리자 계정 분리 + 활동 로그 사용자별 추적
2. ChatGPT API(OpenAI) 모델 선택 추가
3. 클라우드 웹 서버 게시 환경 구축

본 계획서는 세 가지 요구를 분석하고 구현 가능 범위를 결정한 뒤, M15·M16·M17 세 마일스톤으로 분할합니다.

## 2. 요구사항 분석 및 결정 사항

### 2.1 역할 기반 인증 (M15)

**현황:** `_check_auth`가 단일 평문 `APP_PASSWORD`로 통과 여부만 판정. 로그에는 8자리 무작위 `session_id`만 기록되어 "어느 사람"이 무엇을 했는지 추적 불가.

**결정:**
- 단일 비밀번호 → **사용자명(ID) + 비밀번호 + 역할(role)** 모델로 전환
- 사용자 저장소: 프로젝트 루트의 `users.json` 파일 (gitignore, 권한 제한)
- 역할: `employee` / `admin` 2종
- 비밀번호: bcrypt(또는 passlib pbkdf2_sha256) 해시로 저장. 평문 비교 deprecated
- 모든 감사 로그 이벤트에 `user_id`·`role` 자동 부착
- 부트스트랩: 첫 실행 시 admin 계정이 없으면 CLI로 `python scripts/manage_users.py init`을 안내
- `APP_PASSWORD` 마이그레이션: 본 마일스톤에서 사용 중단. README에 안내

**관리자 기능 (알파 범위):**
- 로그 조회: 날짜·사용자·이벤트 유형 필터 + 표 표시
- 로그 통계: 일별 질문 수, 사용자별 질문 수, 모드별 분포, 평균 응답 시간
- 사용자 관리: 목록 / 추가 / 비밀번호 리셋 (삭제는 알파 범위 외)
- 시스템 상태: Ollama 연결 상태, 인덱스 크기, 사용 가능한 모델 목록
- 로그 CSV 다운로드

**비범위(베타 이월):** 사용자 삭제, 비밀번호 정책 강화, 세션 만료, SSO/OAuth, 권한 세분화(rerank 사용 가능 여부 등).

### 2.2 OpenAI(ChatGPT) 모델 통합 (M16)

**현황:** `OllamaClient`만 존재. `streamlit_app.py`가 직접 `OllamaClient`를 인스턴스화하고 `generate`/`generate_stream` 호출.

**결정:**
- LLM 추상화 도입: `LLMClient` 프로토콜 정의, `OllamaClient`·`OpenAIClient`가 모두 구현
- `src/llm/factory.py`로 모델 ID 패턴(`gpt-*`/`openai:*` vs 그 외)에 따라 적절한 클라이언트를 인스턴스화
- 모델 선택 UI: 기존 단일 selectbox → "Local · Ollama" / "Cloud · OpenAI" 그룹 표기
- OpenAI 후보 모델: `gpt-4o-mini` (기본·저렴·빠름), `gpt-4o`, `gpt-4.1-mini`, `gpt-4.1`
- API 키 미설정(`OPENAI_API_KEY`가 비어 있음) → OpenAI 모델 비활성화 + 안내
- OpenAI 모델 선택 시 UI 상단에 경고 배너: "선택된 모델은 외부 OpenAI 서버를 호출합니다. 입력된 질문과 검색된 청크가 OpenAI로 전송됩니다."
- 비용 보호: `OPENAI_MAX_TOKENS` 기본 1500 (env 가변), 호출당 입력+출력 토큰 로깅 (관리자 통계로 노출)
- 스트리밍 지원: `OpenAIClient.generate_stream` 구현 (SSE)

**API 키 보안 — 사용자 가이드:**
1. 사용자가 보유한 OpenAI API 키를 프로젝트 루트의 `.env` 파일에 다음과 같이 직접 추가
   ```
   OPENAI_API_KEY=<OPENAI_API_KEY>
   OPENAI_DEFAULT_MODEL=gpt-4o-mini
   OPENAI_MAX_TOKENS=1500
   ```
2. `.env`는 이미 `.gitignore`에 포함되어 있으므로 절대 커밋되지 않음 — 별도 점검 필수
3. 클라우드 배포 시에는 `.env` 대신 플랫폼 secrets 기능 사용 (Streamlit Secrets / HF Secrets — M17 가이드)

### 2.3 클라우드 웹 서버 게시 (M17)

#### 2.3.1 핵심 질문: exaone3.5:7.8b를 무료 웹 호스팅에서 실행 가능한가?

**모델 사양 검토:**
| 항목 | 값 |
|---|---|
| 파라미터 | 7.8B |
| Q4_K_M 양자화 (Ollama 기본) | 약 4.7GB |
| 추론 시 RAM 권장 | 6~8GB |
| Apple Silicon Metal 가속 가능 | 예 (사용자 M4 환경) |
| CPU 추론 가능 | 예 (속도 매우 느림) |

**무료 호스팅 옵션 비교:**

| 플랫폼 | RAM | GPU | 모델 호스팅 가능성 | 비고 |
|---|---|---|---|---|
| Streamlit Community Cloud | 1GB | 없음 | ❌ 절대 불가 | 7B 모델 로드 자체 불가 |
| Hugging Face Spaces (CPU 무료) | 16GB | 없음 | ⚠️ 가능하나 비실용 | 응답 1~수 분, 다운로드/공개 정책 이슈 |
| Hugging Face Spaces (ZeroGPU) | T4 임시 할당 | 임시 GPU | ⚠️ 가능하나 부적합 | 큐 대기, 공개 기본 — 사내 데이터 부적합 |
| Render Free | 512MB | 없음 | ❌ 불가 | 슬립·메모리 부족 |
| Vercel / Netlify | 서버리스 | 없음 | ❌ 불가 | LLM 추론 부적합 |
| Google Cloud Run 무료 티어 | 가변 | 없음 | ❌ 불가 | 메모리·타임아웃 |
| Oracle Cloud Always Free | 24GB ARM | 없음 | ⚠️ CPU 추론만 | 응답 수십 초~분, 운영 안정성 낮음 |
| Fly.io / Railway 무료 크레딧 | 가변 | 없음 | ❌ 불가 | 크레딧 소진 후 중단 |

**결론:**
> 무료 웹 호스팅에서 exaone3.5:7.8b를 사용자가 만족할 만한 응답 속도(< 30초)로 실행하는 것은 사실상 **불가능**합니다.

따라서 사용자 요구사항대로 **클라우드 배포에서는 OpenAI API 전용**으로 동작하고, **로컬 실행 시에는 Ollama + OpenAI 둘 다 선택 가능**한 이중 구성으로 구현합니다.

#### 2.3.2 1차 배포 플랫폼 결정

**Streamlit Community Cloud (1차 권장):**
- 장점: GitHub 연동만으로 배포, 무료, secrets 관리 UI 내장, Streamlit 네이티브
- 단점: 1GB RAM — Ollama 임포트는 가능하나 호출은 OpenAI로 강제
- 단점: 인덱스(BM25 + Chroma)가 RAM에 적재되어야 하므로 1GB 한도가 빡빡함 → Chroma 임베딩 차원 / 청크 수에 따라 OOM 위험. 1차 검증 필요.

**Hugging Face Spaces (대안):**
- 16GB RAM, Streamlit SDK 지원, 무료
- 단점: 기본 공개 — Private Space 가능하나 무료 한도·다운로드 정책 확인 필요

**1차 결정: Streamlit Community Cloud로 시도, 메모리 부족·인덱스 적재 실패 시 HF Spaces로 전환.**

#### 2.3.3 클라우드 배포에 필요한 사전 정리

**(A) 데이터/인덱스:**
- 1.4GB 분량의 임베딩 인덱스(`data/index/chroma`, `data/index/bm25.pkl`)와 PDF 원본을 어떻게 배포 환경에 둘 것인가?
- 옵션 1: GitHub LFS에 올림 — Streamlit Cloud 가능, HF Spaces도 가능, 1GB 무료 한도
- 옵션 2: GitHub Release 자산으로 zip 첨부, 부팅 시 다운로드 — 1차 단순
- **결정: 옵션 2로 시작, 부팅 시 인덱스가 없으면 GitHub Release에서 다운로드.** 5GB 한도 내. 향후 LFS로 전환.

**(B) PDF 원본 라이선스/공개 위험:**
- 「건강보험 행위 급여·비급여 목록」 — 공공 고시 (공개 가능)
- 「신한 이지로운 실손의료보험 약관」 — 공개 약관 (보통 인터넷에 공시되어 있음)
- 「보상가이드북」 — 사내 자료 가능성 → **공개 저장소 업로드 금지 검토 필요**

→ 1차 클라우드 배포에서는 공공/공시 자료 2종만 인덱싱하여 올리고, 사내 가이드북은 로컬 전용 분기로 둘 수 있게 한다 (`config.py`의 `PDF_SOURCES`에 `cloud_safe: bool` 플래그 추가, 클라우드 빌드 시 `cloud_safe=True`만 인덱싱).

**(C) 비밀 관리:**
- `.env` 대신 Streamlit secrets (`secrets.toml`) — 코드는 동일하게 `os.getenv()`로 접근 (Streamlit이 secrets를 환경변수로 주입). HF Spaces도 Settings → Variables and secrets 사용
- `users.json`은 secrets에 JSON 문자열로 저장 → 부팅 시 파일로 풀어 사용

**(D) LLM 강제:**
- 클라우드 환경에서는 Ollama 호출이 가능하더라도 응답 불가능 → `ALLOW_OLLAMA=false`(기본값 `true`)로 환경변수 추가, false일 때 모델 선택지에서 Ollama 항목을 모두 숨김

**(E) 로그 영속성:**
- Streamlit Cloud / HF Spaces는 ephemeral storage — 재시작 시 `logs/` 휘발
- 알파에서는 휘발 허용 + 관리자가 정기적으로 로그 CSV 다운로드 권장
- 베타에서는 외부 객체 저장소(S3/R2/GCS) 백업 검토

## 3. 마일스톤 분할

| M | 이름 | 범위 | 의존 |
|---|---|---|---|
| **M15** | 역할 기반 인증 + 관리자 대시보드 | 사용자 모델 / 로그인 UI / 사용자별 로그 / 관리자 페이지 | M14 |
| **M16** | LLM 추상화 + OpenAI 통합 | LLMClient 프로토콜 / OpenAIClient / 모델 선택 UI 통합 / 비용·외부 전송 안내 | M14 (M15와 독립적이지만 관리자 통계에서 모델/사용자 결합 활용) |
| **M17** | 클라우드 배포 준비 | `cloud_safe` 플래그 / `ALLOW_OLLAMA` 가드 / secrets 가이드 / 인덱스 자산 다운로드 / 배포 가이드 문서 | M15 + M16 |

순차 진행 권장 (M15 → M16 → M17). M15와 M16은 독립적으로도 머지 가능.

## 4. 위험 및 완화

| 위험 | 영향 | 완화 |
|---|---|---|
| bcrypt 의존성 추가로 빌드 실패 가능 | 인증 모듈 동작 불가 | passlib(pbkdf2_sha256) 우선 — 순수 Python, wheel 불필요 |
| `users.json` 손상 시 전 사용자 잠김 | 로그인 불가 | `manage_users.py reset-admin` 부트스트랩 명령. 백업 가이드 |
| OpenAI API 키 노출 | 과금·악용 | `.env`/secrets, gitignore 점검, 키 부재 시 모델 비활성화, 사용량 모니터링 |
| OpenAI 응답이 한국어 인용 형식을 따르지 않음 | 답변 품질 회귀 | 기존 SYSTEM_PROMPT 그대로 적용 + 모델별 미세조정은 베타 |
| 클라우드 무료 티어 RAM 부족(1GB) | 배포 실패 | 인덱스 크기 측정 후 청크 수 축소·임베딩 차원 압축 또는 HF Spaces 전환 |
| 사내 가이드북 PDF의 공개 저장소 업로드 위험 | 정보 유출 | `cloud_safe=False`로 분기, 클라우드 빌드에서 제외 |
| 클라우드의 ephemeral 로그 휘발 | 감사 증거 손실 | 알파에서는 정기 CSV 다운로드 안내, 베타에서 객체 저장소 연동 |
| 로컬 환경에서 OpenAI 모델 사용 시 비용 누적 | 예상 외 청구 | 토큰 한도 + 관리자 대시보드의 누적 토큰 통계 |

## 5. 성공 지표

| 지표 | M14 (현재) | M15 목표 | M16 목표 | M17 목표 |
|---|---|---|---|---|
| 사용자 식별 가능한 로그 비율 | 0% | 100% | 100% | 100% |
| 관리자 페이지 접근 시간 | — | 1클릭(사이드바) | 동일 | 동일 |
| OpenAI 모델 선택 → 첫 토큰 시간 | — | — | 5초 이하 | 동일 |
| OpenAI 응답에서 출처 인용 형식 일치율 | — | — | 80%+ | 동일 |
| 클라우드 배포 성공 (Streamlit Cloud 또는 HF Spaces) | ❌ | ❌ | ❌ | ✅ |
| 클라우드 응답 시간 (gpt-4o-mini) | — | — | — | 10초 이하 |

## 6. 비범위 / 베타 이월

- 사용자 삭제 (UI에서)
- 비밀번호 정책 강화 (대문자/특수문자 강제)
- 세션 자동 만료 / 강제 로그아웃 / 동시 세션 제한
- SSO·OAuth (Google Workspace 등)
- 클라우드 로그 영속 저장 (S3/R2)
- exaone3.5 등 7B+ 로컬 모델 클라우드 호스팅
- 자체 추론 백엔드(GPU 인스턴스) 운영
- M18 (top-k/온도 자동 설정) — 별도 1차 사용 데이터 누적 후 진행

## 7. 사용자(범준 님)가 직접 수행해야 할 작업

> Codex 구현 후 또는 동시에 진행 필요.

1. **OpenAI API 키 입력**: `.env`에 다음 라인 추가 (값은 실제 키)
   ```
   OPENAI_API_KEY=<OPENAI_API_KEY>
   OPENAI_DEFAULT_MODEL=gpt-4o-mini
   OPENAI_MAX_TOKENS=1500
   ```
   Codex 구현 완료 후 즉시.
2. **관리자 계정 부트스트랩**: `python scripts/manage_users.py init` 실행 후 표시되는 안내에 따라 admin 사용자명·비밀번호 설정. 비밀번호는 안전한 곳에 보관.
3. **임직원 계정 추가**: `python scripts/manage_users.py add --role employee` 또는 admin 로그인 후 관리자 페이지에서 사용자 추가.
4. **클라우드 배포 결정 (M17 시점)**: Streamlit Community Cloud 또는 HF Spaces 중 선택. 가이드 문서 따라 GitHub repo 연결.
5. **사내 PDF 공개 가능 여부 검토**: 「보상가이드북.pdf」가 공개 저장소 업로드 가능한지 회사 정책 확인. 불가능 시 `cloud_safe=False` 유지.
6. **클라우드 배포 후 secrets 입력**: 플랫폼 secrets UI에서 `OPENAI_API_KEY`, `USERS_JSON`, `APP_PASSWORD`(미사용이지만 호환), `ALLOW_OLLAMA=false` 입력.

---

*상세 구현 명세는 [16_CODEX_SPEC_M15M16M17.md](./16_CODEX_SPEC_M15M16M17.md)를 따른다.*
