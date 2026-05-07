# 프로젝트 현황 요약

> 작성일: 2026-05-07  
> 기준 브랜치: `master`  
> 기준 HEAD: `34da73a fix(reranker): prefer local_files_only=True to avoid network on startup`

---

## 1. 현재 상태

보험 문서 RAG 챗봇은 Streamlit Community Cloud에서 로그인 후 질의가 가능한 상태다. 현재 GitHub `master`에는 M15-M17 범위의 인증, OpenAI 통합, Cloud 배포 준비, 모델 후보 정리, 내보내기 보정, reranker 오프라인 우선 로딩 변경이 반영되어 있다.

핵심 파이프라인은 유지된다.

```text
BGE-M3 임베딩 -> Chroma dense 검색 -> BM25 -> RRF -> reranker -> LLM 답변 -> 출처 첨부
```

이번 모델 후보 정리는 이 파이프라인 구조를 바꾸지 않는다. OpenAI 모델 선택 목록과 배포 문서 예시를 최신 Chat Completions 지원 모델 기준으로 맞춘 변경이다.

---

## 2. 배포 및 런타임 구성

Streamlit Cloud 기준 주요 설정은 다음과 같다.

```toml
CLOUD_DEPLOY = "true"
ALLOW_OLLAMA = "false"
HF_MODEL_DOWNLOAD = "true"
EMBEDDING_MODEL = "BAAI/bge-m3"
OPENAI_DEFAULT_MODEL = "gpt-5.2-chat-latest"
OPENAI_CANDIDATE_MODELS = "gpt-5.5,gpt-5.2-chat-latest,gpt-5.4-mini,gpt-5-mini"
INDEX_RELEASE_URL = "https://github.com/koreaben777/insurance-rag-chatbot/releases/download/rag-assets-v1/assets.zip"
```

Cloud에서는 `INDEX_RELEASE_URL`의 `assets.zip`을 받아 공개 가능 PDF와 인덱스를 복원한다. BGE-M3는 `HF_MODEL_DOWNLOAD=true`일 때만 HuggingFace 원격 다운로드를 허용한다. 로컬 기본값은 여전히 캐시 우선이다.

---

## 3. OpenAI 모델 정책

현재 웹앱은 Chat Completions 스트리밍 클라이언트를 사용한다. 따라서 후보 모델은 `v1/chat/completions`와 streaming을 지원하는 모델만 노출한다.

현재 후보:

- `gpt-5.5`: 복잡한 약관 해석, 보상 판단, 장문 질의용
- `gpt-5.2-chat-latest`: 기본값, 일반 질의와 Cloud 테스트용
- `gpt-5.4-mini`: 속도와 비용을 고려한 중간급 모델
- `gpt-5-mini`: 단순 조회와 저비용 테스트용

제외 정책:

- `gpt-5.2-pro`, `gpt-5.2-pro-2025-12-11`, `gpt-5.5-pro`는 현재 웹앱 후보에서 제외한다.
- 이 계열은 앱의 기존 Chat Completions 스트리밍 경로에서 오류나 비스트리밍 제약을 유발할 수 있으므로, 별도 비스트리밍/Responses API 경로를 도입하기 전까지는 노출하지 않는다.

공식 문서 확인 결과 `gpt-5.5`, `gpt-5.4-mini`, `gpt-5.2-chat-latest`, `gpt-5-mini`는 Chat Completions와 streaming을 지원한다.

---

## 4. 최근 반영된 핵심 변경

- `d44138e`: 현재 OpenAI 스트리밍 경로와 맞지 않는 모델을 드롭다운에서 제외
- `8c864ca`: 대화 내보내기에서 메시지별 실제 사용 모델을 기록하고 CSV/JSON/TXT에 반영
- `34da73a`: reranker `CrossEncoder`를 로컬 캐시 우선으로 로드하고, 캐시 미스 시에만 다운로드 fallback 수행
- 현재 작업: OpenAI 후보 모델을 최신 Chat Completions 지원 모델 기준으로 정리하고 문서/환경 예시를 동기화

---

## 5. 검증 상태

현재 로컬 회귀 테스트:

```text
pytest -q
110 passed, 5 warnings
```

경고는 `tests/test_pdf_view.py` 실행 중 발생하는 PyMuPDF/SWIG deprecation warning이며, 현재 기능 실패는 아니다.

최근 Streamlit Cloud 테스트에서는 GitHub에 반영된 상태 기준으로 로그인 후 질의가 정상 작동하는 것으로 확인되었다.

---

## 6. 남은 리스크

검색 품질 측면에서는 특정 질의에서 약관 조항이 과도하게 넓게 매칭될 수 있다. 예를 들어 "보험 가입 후 이틀 뒤 교통사고" 유형은 `상해급여`, `상해비급여`, `자동차보험`, `산재보험`, `본인부담의료비`, `보장개시일` 관련 조항을 우선 찾아야 하지만, 일반 토큰 매칭으로 `계약 후 알릴 의무` 같은 조항이 섞일 수 있다.

운영 로그 측면에서는 Streamlit watcher가 `transformers`의 선택적 vision 모듈을 탐색하면서 `torchvision` 관련 로그 노이즈를 만들 수 있다. 답변 품질 문제는 아니지만 Cloud 로그 가독성을 떨어뜨린다.

모델 운영 측면에서는 `gpt-5.5`가 고성능 모델인 만큼 비용과 응답 지연이 커질 수 있다. 기본값을 `gpt-5.2-chat-latest`로 둔 현재 정책은 비용과 품질의 균형을 고려한 선택이다.

---

## 7. 권장 다음 작업

1. Cloud RAG 디버그 로그 추가
   - dense/BM25/RRF/rerank 단계의 상위 hit, 점수, chunk id, 문서명, 페이지를 확인 가능하게 한다.

2. 교통사고/상해 보상 질의 검색 보정
   - `상해급여`, `상해비급여`, `보상하지 않는 사항`, `자동차보험`, `산재보험`, `본인부담의료비`, `보장개시일` 확장어를 적용한다.

3. 출처 첨부 로직 개선
   - 단순 top-k 출처 첨부 대신 답변에서 실제 사용한 근거 중심으로 제한한다.

4. Cloud 로그 노이즈 축소
   - Streamlit file watcher 설정을 조정해 `transformers` optional module 탐색 로그를 줄인다.
