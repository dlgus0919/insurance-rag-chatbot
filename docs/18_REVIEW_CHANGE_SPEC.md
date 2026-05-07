# 최신 변경 사항 명세 - 검토자 보고용

> 작성일: 2026-05-06
> 대상 브랜치: `master`
> 기준 커밋: `64d398b Allow optional HuggingFace embedding download on cloud`
> 기준 문서: `docs/16_CODEX_SPEC_M15M16M17.md` 초안 및 `docs/17_DEPLOY_GUIDE.md`

---

## 1. 현재 개발 상태

프로젝트는 M15-M17 범위의 핵심 기능이 구현된 상태다.

- M15: 역할 기반 로그인, 사용자 저장소, 관리자 대시보드
- M16: Ollama/OpenAI 공통 LLM 팩토리, OpenAI 모델 선택, 토큰 사용량 로깅
- M17: Streamlit Community Cloud 배포 준비, 공개 인덱스 자산 부트스트랩, Cloud 전용 Ollama 비활성화
- 추가 핫픽스: GPT-5 계열 Chat Completions payload 수정
- 추가 Cloud 대응: Streamlit Cloud에서만 BGE-M3 HuggingFace 원격 다운로드 허용 옵션 추가

현재 원격 저장소 `origin/master`는 로컬 `master`의 HEAD와 동일한 `64d398b`까지 반영되어 있다.

---

## 2. 지난 명세 이후 주요 변경

### 2.1 Cloud 배포용 인덱스 부트스트랩

`scripts/bootstrap_assets.py`와 Streamlit 시작 로직이 추가되어, Cloud 배포 시 `INDEX_RELEASE_URL`에서 `assets.zip`을 내려받고 `data/index/` 및 공개 PDF 자산을 복원한다.

영향 범위:
- `src/ui/streamlit_app.py`
- `scripts/bootstrap_assets.py`
- `tests/test_bootstrap_assets.py`
- `docs/17_DEPLOY_GUIDE.md`

정책:
- 공개 가능 문서만 `assets.zip`에 포함한다.
- 사내 자료 가능성이 있는 문서는 GitHub Release asset에 포함하지 않는다.

### 2.2 OpenAI 통합 및 GPT-5 payload 수정

OpenAI 클라이언트와 LLM 팩토리가 추가되었고, Cloud에서는 `ALLOW_OLLAMA=false` 설정으로 OpenAI 모델만 사용하도록 구성할 수 있다.

이후 GPT-5 계열 모델 호출 오류를 피하기 위해 payload 분기가 수정되었다.

- GPT-5 계열: `max_completion_tokens` 사용
- GPT-4 계열 및 기존 모델: `temperature`, `max_tokens` 사용

영향 범위:
- `src/llm/base.py`
- `src/llm/factory.py`
- `src/llm/openai_client.py`
- `src/ui/streamlit_app.py`
- `tests/test_openai_client.py`
- `tests/test_llm_factory.py`

### 2.3 HuggingFace BGE-M3 원격 다운로드 옵션

Cloud에서 BGE-M3가 로컬 캐시에 없을 때 앱이 즉시 실패하던 문제를 해결하기 위해 `HF_MODEL_DOWNLOAD` 환경변수가 추가되었다.

기본 정책:
- 로컬 기본값: `HF_MODEL_DOWNLOAD=false`
- 로컬 인제스트/평가/개발 파이프라인: 기존처럼 HuggingFace 캐시 전용
- Streamlit Cloud 웹 게시 테스트: `HF_MODEL_DOWNLOAD=true` 설정 시에만 원격 다운로드 허용
- BGE-M3 로드 실패 시 BM25-only 폴백은 하지 않고 명확한 오류를 표시

영향 범위:
- `src/config.py`
- `src/retrieval/embedder.py`
- `src/ui/streamlit_app.py`
- `src/ui/admin_page.py`
- `.env.example`
- `README.md`
- `docs/17_DEPLOY_GUIDE.md`
- `tests/test_embedder.py`

핵심 동작:

```python
Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
```

---

## 3. Cloud 테스트 진단 결과

Streamlit Cloud에서 다음 설정 후 BGE-M3 로딩은 성공한 것으로 판단된다.

```toml
CLOUD_DEPLOY = "true"
ALLOW_OLLAMA = "false"
HF_MODEL_DOWNLOAD = "true"
EMBEDDING_MODEL = "BAAI/bge-m3"
```

관찰된 Cloud 로그 상태:
- Python 3.11 환경으로 재배포됨
- `assets.zip` 다운로드 완료
- BGE-M3 weight loading 진행 로그 확인
- 로그인 후 질의 가능

다만 첫 질의인 "보험 가입 후 이틀 뒤 교통사고가 발생한 경우 보상" 답변에서 출처가 비정상적으로 보였다.

현재 진단:
- 모델 로딩 문제는 아니다.
- 검색 질의가 `보험 가입 후`, `이틀 뒤`, `교통사고`, `보상` 같은 넓은 토큰을 포함한다.
- BM25가 `제15조(상해보험계약 후 알릴 의무)`, `제18조(보험계약의 성립)`, `제6조(보험가입금액 한도 등)` 같은 조항을 강하게 잡을 수 있다.
- 실제 답변 근거는 `상해급여/상해비급여 보상내용`, `보상하지 않는 사항`, `자동차보험/산재보험 보상분 제외`, `본인부담의료비`, `보장개시일/책임개시일` 쪽이어야 한다.
- 현재 자동 출처 첨부 로직은 상위 검색 결과를 답변 말미에 붙이므로, 약한 검색 결과가 근거처럼 보일 수 있다.

따라서 Cloud 게시 테스트의 다음 개선 대상은 인프라가 아니라 retrieval routing 및 출처 근거화 로직이다.

---

## 4. 검증 상태

현재 로컬 회귀 테스트 결과:

```text
pytest -q
102 passed, 5 warnings
```

경고는 `tests/test_pdf_view.py` 실행 중 PyMuPDF/SWIG 계열 deprecation warning이며, 현재 기능 실패는 아니다.

보안 문자열 점검 결과:
- 문서와 테스트에는 실제 키가 아닌 placeholder만 존재한다.
- 실제 OpenAI 키나 실제 사용자 password hash는 확인되지 않았다.

---

## 5. 검토자가 중점 확인할 사항

1. `HF_MODEL_DOWNLOAD` 정책이 로컬 파이프라인을 변경하지 않는지 확인
   - 기본값은 `false`
   - Cloud Secrets에서 명시적으로 켠 경우에만 원격 다운로드

2. Cloud에서 BGE-M3 실패 시 BM25-only로 숨기지 않는 정책이 요구사항과 일치하는지 확인
   - 현재는 실패 원인을 명확히 드러내는 방향

3. OpenAI GPT-5 계열 payload 분기가 API 요구사항과 맞는지 확인
   - GPT-5 계열은 `max_completion_tokens`
   - 비 GPT-5 계열은 `temperature`, `max_tokens`

4. Cloud 첫 질의 비정상 답변의 후속 개선 범위 확정
   - top-k 검색 결과 디버그 로깅
   - 교통사고/상해/보상 질의 확장
   - 관련 조항 부스팅
   - `제15조(상해보험계약 후 알릴 의무)` 오탐 downrank
   - 자동 출처 첨부 로직 개선

5. Streamlit watcher의 `torchvision` 관련 로그 노이즈 처리 여부
   - 답변 품질 원인은 아니지만 Cloud 로그 가독성을 크게 떨어뜨림
   - 별도 설정으로 file watcher를 제한하는 개선이 가능

---

## 6. 현재 작업트리 주의사항

현재 커밋된 상태와 별개로 로컬 작업트리에 다음 변경이 남아 있다.

- 수정됨: `docs/01_PROJECT_PLAN.md`
- 미추적: `assets.zip`
- 미추적: `docs/03_ARCHITECTURE_REPORT.md` 등 다수의 초안 문서

이 파일들은 현재 기준 커밋 `64d398b`에는 포함되어 있지 않다. 검토자는 GitHub의 `master` 기준 리뷰와 로컬 초안 리뷰를 분리해서 보는 것이 안전하다.

---

## 7. 다음 권장 작업

1. Cloud RAG 디버그 로그 추가
   - dense/BM25/RRF/rerank 단계별 상위 hit의 `chunk_id`, 문서명, 조항, 페이지, 점수 출력

2. 교통사고 보상 질의 전용 검색 보정
   - 확장어: `상해급여`, `상해비급여`, `보상하는 사항`, `보상하지 않는 사항`, `자동차보험`, `공제`, `산재보험`, `본인부담의료비`, `보장개시일`

3. 출처 첨부 개선
   - 단순 top-k citation append가 아니라 답변에 실제 사용된 근거 중심으로 제한

4. 약관 summary/table-of-contents 청크 metadata 품질 개선
   - 넓은 페이지 범위와 잘못 상속된 조항명이 출처에 노출되지 않도록 보정

5. Streamlit Cloud 로그 노이즈 축소
   - `transformers` optional vision module watcher 오류를 줄이는 설정 검토
