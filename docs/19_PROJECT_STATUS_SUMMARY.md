# 프로젝트 현황 요약

> 작성일: 2026-05-07
> 기준 브랜치: `master`
> 기준 HEAD: `e2c7ae8 feat: add per-account chat persistence and multi-thread sidebar (M-ux-3/4)`

---

## 1. 현재 상태

보험 문서 RAG 챗봇은 Streamlit Community Cloud에서 로그인 후 질의가 가능한 상태다. 현재 GitHub `master`에는 알파 종료 보정과 UX 보정까지 반영되어 있으며, 베타 개발 착수 전 코드 기준 알파 완료 상태로 볼 수 있다.

핵심 파이프라인은 유지된다.

```text
BGE-M3 임베딩 -> Chroma dense 검색 -> BM25 -> RRF -> reranker -> LLM 답변 -> 출처 첨부
```

최근 변경은 이 파이프라인 구조를 바꾸지 않는다. 검색 진단, 출처 표시, 질의 확장, smoke QA v2, Cloud 로그 축소, 채팅 영속화는 모두 기존 검색/생성 흐름의 전후단 보정이다.

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

현재 웹앱은 Chat Completions 스트리밍 클라이언트를 사용한다. 따라서 후보 모델은 현재 앱의 `v1/chat/completions` 스트리밍 경로와 호환되는 모델만 노출한다.

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
- `83982eb`: RAG 단계별 검색 진단 정보 추가
- `2d306d1`: LLM이 인용한 출처 중심으로 UI 출처 표시 제한
- `053dc6e`: 교통사고·상해 관련 검색 질의 확장
- `b80c014`: 약관 정형 검색 smoke QA v2 추가
- `ecb7fd2`: Streamlit Cloud 로그 노이즈 축소
- `4bcead6`: 검색 진단 체크박스 제거 및 일반 질의 debug 상시 수집
- `04cd43f`: 물결표 Markdown 취소선 렌더링 방지
- `e2c7ae8`: 계정별 채팅 영속화와 멀티 채팅 사이드바 추가

---

## 5. 검증 상태

현재 로컬 회귀 테스트:

```text
pytest -q --ignore=tests/test_vector_store.py
119 passed, 5 warnings
```

경고는 `tests/test_pdf_view.py` 실행 중 발생하는 PyMuPDF/SWIG deprecation warning이며, 현재 기능 실패는 아니다.

최근 Streamlit Cloud 테스트에서는 GitHub에 반영된 상태 기준으로 로그인 후 질의가 정상 작동하는 것으로 확인되었다.

---

## 6. 남은 리스크

검색 품질 측면에서는 알파 기준 보정이 완료되었지만, 100개 이상 약관과 타사 약관이 들어오면 메타 필터 없이 검색 노이즈가 다시 커질 수 있다.

Streamlit Cloud에서는 채팅 내역이 `data/chat_history/`에 저장되지만, Community Cloud 파일시스템 특성상 재시작 시 휘발될 수 있다. 로컬 실행에서는 영속 저장으로 동작한다.

모델 운영 측면에서는 `gpt-5.5`가 고성능 모델인 만큼 비용과 응답 지연이 커질 수 있다. 기본값을 `gpt-5.2-chat-latest`로 둔 현재 정책은 비용과 품질의 균형을 고려한 선택이다.

---

## 7. 권장 다음 작업

1. 베타 1: 다중 약관과 메타 스키마 확장
   - `insurance_company`, `is_own_company`, `product_name`, `effective_date`, `coverage_category`, `clause_type` 등을 청크 메타에 추가한다.

2. 베타 1: 약관 배치 인제스트
   - 약관 폴더와 메타 파일을 입력받아 다수 PDF를 한 번에 인덱싱하는 `scripts/ingest_batch.py`를 설계한다.

3. 베타 1: 자사·타사/상품/시행일 필터와 약관 비교 모드
   - 사내 직원이 자사 약관과 타사 약관을 분리해 검색하고 비교할 수 있도록 UI와 retrieval filter를 확장한다.

4. 베타 2: OCR 및 표·이미지 보존 인덱싱
   - 스캔본 약관 입수 후 PaddleOCR + PP-Structure 기반 OCR 파이프라인을 검증한다.
