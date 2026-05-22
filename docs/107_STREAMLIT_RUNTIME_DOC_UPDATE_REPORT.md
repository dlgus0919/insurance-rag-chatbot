# Streamlit Runtime Guide Update Report

## 배경

팀원이 GitHub `master`를 pull한 뒤 Streamlit을 실행하기 전에 준비해야 하는 런타임 파일과 실행 절차를 최신 DGX 상태에 맞게 정리했다.

## 수정 파일

- `docs/103_STREAMLIT_RUNTIME_PREP_GUIDE.md`
  - pull 이후 준비 절차를 기준으로 전체 재정리.
  - GitHub에 올라가지 않는 필수 런타임 파일과 준비 방법을 명시.
  - 공용 repo와 개인 워크스페이스 실행 절차를 구분.
- `docs/80_STREAMLIT_LARGE_MODEL_TEST_GUIDE.md`
  - SGLang 단일 슬롯 기준의 오래된 설명을 vLLM Gemma4, SGLang GPT-OSS, Ollama fallback 구조로 갱신.
  - 최신 Gemma4/vLLM streaming fix 이후의 smoke test 기준을 추가.

## 현재 확인 상태

- Streamlit 프로세스는 중단했고 `8501` 포트가 비어 있음을 확인했다.
- Gemma4/vLLM 서버는 별도 요청이 없어 유지했다.
- 공용 repo와 `/srv/ai-ops`에 필요한 OCR 데이터, 비급여 DB, 임베딩/reranker, LLM 모델, env/wrapper 파일이 존재함을 확인했다.

## 검증

문서 변경이므로 코드 테스트는 실행하지 않았다. 커밋 전 Markdown 파일의 whitespace 검사를 수행한다.
