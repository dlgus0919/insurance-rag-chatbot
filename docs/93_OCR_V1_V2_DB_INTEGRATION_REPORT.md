# OCR v1/v2 DB 통합 작업 완료 보고서

- **작성일**: 2026-05-21
- **작업 명세**: [docs/92_OCR_V1_V2_DB_INTEGRATION_SPEC.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/92_OCR_V1_V2_DB_INTEGRATION_SPEC.md)
- **작업 대상**: 메인 원격 저장소 (`/srv/shared/projects/insurance-rag-chatbot`)

---

## 1. 개요
`dani` 실험 워크스페이스에서 구현 및 검증이 완료된 OCR v1/v2 이중화 매핑 및 크로스 밸리데이션(Cross-validation) 파이프라인 중 RAG 엔진에 필요한 핵심 컴포넌트를 선별하여 메인 저장소로 이식 및 병합을 완료하였습니다.

---

## 2. 주요 변경 및 포팅 내역

### 가. 신규 포팅 파일
1. **[src/retrieval/index_mode.py](file:///srv/shared/projects/insurance-rag-chatbot/src/retrieval/index_mode.py)**
   - RAG 시스템에서 인덱스 및 매핑 데이터를 참조하기 위한 3가지 검색 모드(`default`, `v2_only`, `v1_v2_combined`) 정의
2. **[src/retrieval/pair_mapping.py](file:///srv/shared/projects/insurance-rag-chatbot/src/retrieval/pair_mapping.py)**
   - 보정본(v2) 청크 ID와 원본(v1) OCR 청크 ID 간 매핑 정보를 캐싱 및 조회하는 `PairMappingStore` 클래스 구현
3. **[scripts/build_v1_v2_pair_mapping.py](file:///srv/shared/projects/insurance-rag-chatbot/scripts/build_v1_v2_pair_mapping.py)**
   - v1과 v2 청크 간의 텍스트 유사도 비교를 통해 매핑 JSONL 데이터를 생성하고, 신뢰도가 낮은 페어를 검출하는 리포팅 스크립트
4. **[scripts/build_ocr_combined_chunks.py](file:///srv/shared/projects/insurance-rag-chatbot/scripts/build_ocr_combined_chunks.py)**
   - 보정본(v2)과 원본(v1) OCR 추출 결과를 활용해 최종 결합 인덱스용 청크를 가공하는 빌드 스크립트
5. **[scripts/rechunk_v1_sangdam_target16.py](file:///srv/shared/projects/insurance-rag-chatbot/scripts/rechunk_v1_sangdam_target16.py)**
   - 명세 제약조건을 만족하도록 전면 리팩토링: `data/extracted_v1_rechunked/` 미존재 시 명시적 오류 발생, `--in-place` 옵션 없이는 원본 manifest 불변 보장, 경로 인자 설정 기능 구현

### 나. 기존 코드 최소 패치 병합
1. **[scripts/ingest.py](file:///srv/shared/projects/insurance-rag-chatbot/scripts/ingest.py)**
   - 청킹과 인덱싱 단계에서 추출 데이터 루트(`--extracted-root`), 청크 경로(`--chunks-path`), 인덱스 루트(`--index-root`)를 동적 파라미터로 입력받을 수 있도록 구조 패치
2. **[src/parser/ocr_chunker.py](file:///srv/shared/projects/insurance-rag-chatbot/src/parser/ocr_chunker.py)**
   - 파싱 단계에서 `volume`, `part`, `chapter`, `section` 등의 상위 헤더 컨텍스트(Hierarchy Context)가 단락 및 표/그림 데이터에 유실 없이 누적 전파되도록 업데이트
3. **[src/rag/pipeline.py](file:///srv/shared/projects/insurance-rag-chatbot/src/rag/pipeline.py)**
   - RAG 파이프라인 생성 시 `pair_mapping_store` 및 `v1_chunk_lookup` 바인딩 지원
   - `build_prompt` 실행 시, 기존 메인에 있던 **근거 충돌 감지(Conflict Detection)** 기능을 손상시키지 않고 **OCR 교차검증 컨텍스트(원본 OCR 참조)**를 안정적으로 전면 병합
4. **[src/llm/prompt.py](file:///srv/shared/projects/insurance-rag-chatbot/src/llm/prompt.py)**
   - 시스템 프롬프트(`SYSTEM_PROMPT`) 규칙 추가: v2(보정본)를 기본판단 기준으로 삼고 v1(원본)은 보조/교차검증용으로 활용하며, 충돌 시 명시하는 지침 병합

---

## 3. 검증 결과

### 가. 테스트 코드 이식 및 실행
- **[tests/test_build_v1_v2_pair_mapping.py](file:///srv/shared/projects/insurance-rag-chatbot/tests/test_build_v1_v2_pair_mapping.py)**를 정상적으로 이식하고 원격 서버 환경에서 가상환경 검증을 완료하였습니다.

```bash
/srv/shared/projects/insurance-rag-chatbot/.venv/bin/pytest /srv/shared/projects/insurance-rag-chatbot/tests/test_build_v1_v2_pair_mapping.py -v
```

- **실행 결과**:
  ```text
  ============================= test session starts ==============================
  platform linux -- Python 3.12.3, pytest-9.0.3, pluggy-1.6.0 -- /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python
  cachedir: .pytest_cache
  rootdir: /srv/shared/projects/insurance-rag-chatbot
  configfile: pyproject.toml
  plugins: anyio-4.13.0
  collected 1 item

  ../../srv/shared/projects/insurance-rag-chatbot/tests/test_build_v1_v2_pair_mapping.py::test_emit_low_confidence_report PASSED [100%]

  ============================== 1 passed in 0.01s ===============================
  ```

### 나. 저장소 클린 상태 점검
- Chroma DB, BM25 피클, 중간 JSONL 가공물 등의 런타임 캐시 데이터가 Git status에 침투하지 않은 깨끗한 상태를 확인하였습니다.

---

## 4. 미반영 내용 및 주의사항
- `dani` 워크스페이스 커밋 히스토리에 혼재되어 있던 **Streamlit 화면 레이아웃 및 LLM 런타임 provider 검증 로직 변경** 등은 메인 제품 코드의 안정성과 충돌을 방지하기 위해 이번 병합 대상에서 엄격히 배제되었습니다.
- 향후 평가 및 튜닝 시 `data/extracted_v1_rechunked` 데이터가 구축되는 시점에 맞춰 `rechunk_v1_sangdam_target16.py`와 `ingest.py`를 파라미터 조합으로 실행하여 정합성을 맞춰 나가야 합니다.
