# 149. GraphDB Stage 4 UI Audit View Report

작성일: 2026-05-28
대상 단계: `145_GRAPHDB_ONTOLOGY_IMPROVEMENT_STAGE_PLAN.md`의 Stage 4

## 1. 작업 목적

Stage 4의 목적은 구조화 검토 경로를 개발자용 enum이 아니라 보상 업무 담당자가 바로 이해할 수 있는 화면 정보로 바꾸는 것이다.

핵심 개선 방향:

- `complication_review`, `review_required` 같은 내부 값을 그대로 노출하지 않는다.
- 검토 경로의 종류와 상태를 업무형 라벨로 표시한다.
- 증빙 요구와 검토 조치를 답변/계산 결과에서 더 쉽게 구분한다.

## 2. 변경 내용

### 2.1 API payload에 표시 라벨 추가

수정 파일:

- `src/api/rag_service.py`

추가 함수:

- `graph_review_status_label()`
- `graph_review_path_type_label()`

추가 payload 필드:

- `path_type_label`
- `status_label`

라벨 예시:

- `complication_review` -> `합병증/후유증 검토`
- `diagnosis_review` -> `진단코드 검토`
- `claim_condition_review` -> `청구 조건 검토`
- `confirmed` -> `확정 근거`
- `review_required` -> `검토 필요`
- `candidate` -> `검토 후보`
- `missing` -> `구조화 근거 없음`

### 2.2 Streamlit 구조화 검토 경로 표시 개선

수정 파일:

- `src/ui/streamlit_app.py`

변경 내용:

- 내부 status enum 대신 업무형 라벨을 먼저 표시한다.
- 표시 형식:

```text
합병증/후유증 검토 · 검토 필요: 질문에서 합병증 상황이 주장되어 관련 약관 조항과 증빙 요건을 검토했습니다.
```

- 기존 `필요 증빙`, `권장 검토 조치` 표시는 유지한다.

## 3. 검증 결과

실행 명령:

```bash
python -m py_compile src/api/rag_service.py src/ui/streamlit_app.py
python -m pytest tests/test_api_rag_service_payload.py -q
```

결과:

```text
1 passed in 0.57s
```

비고:

- 기존 `tests/test_api_chat_stream.py`는 로컬 환경에서 `aiosqlite` 미설치로 수집 단계가 실패할 수 있어, 이번 표시 라벨 검증은 DB 초기화를 요구하지 않는 독립 단위 테스트로 분리했다.

## 4. 남은 작업

다음 단계는 Stage 5 `Evaluation and Rebuild Gate`다.

중점:

- review path 평가셋과 평가 스크립트를 보강한다.
- GraphDB rebuild 후 새 `rule_types`, `rule_summary`, review path 안전장치가 실제 SQLite에 반영되는지 검증한다.
- 전체 관련 테스트를 DGX 환경에서 실행한다.
