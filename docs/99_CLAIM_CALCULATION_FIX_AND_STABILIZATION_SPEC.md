# 99. Claim Calculation Fix And Stabilization Spec For Antigravity

작성일: 2026-05-21
작성 위치: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`
대상 작업자: Antigravity 서브 개발자
작업 성격: 보험금 계산 기능 회귀 복구, 런타임 오류 해결, MVP 안정화 명세

## 1. 배경

보험금 지급예상액 계산 파이프라인 구현 후 Streamlit 앱에서 `보험금 계산` 모드를 선택하면 다음 오류가 발생했다.

```text
임베딩 모델을 로컬 캐시에서 로드할 수 없습니다: BAAI/bge-m3.
README의 사전 단계에 따라 HuggingFace 캐시에 모델을 먼저 내려받으세요.
클라우드에서 원격 다운로드를 허용하려면 HF_MODEL_DOWNLOAD=true를 설정하세요.

검색 파이프라인을 사용할 수 없습니다.
```

현장 확인 결과 `/srv/ai-ops/models/embedding/bge-m3`와 `/srv/ai-ops/models/reranker/bge-reranker-v2-m3`는 존재한다. 따라서 원인은 단순 자산 부재가 아니다.

## 2. 현재 원인 분석

### 2.1 직접 원인: 앱 실행 방식 오류

Antigravity가 앱을 아래 방식으로 직접 실행했다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
nohup streamlit run src/ui/streamlit_app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true > streamlit.log 2>&1 &
```

이 방식은 `/srv/ai-ops/bin/run-insurance-rag` wrapper를 거치지 않으므로 `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`가 source되지 않는다. 그 결과 앱은 `src/config.py`의 기본값 `EMBEDDING_MODEL=BAAI/bge-m3`를 사용하고, `HF_MODEL_DOWNLOAD=false` 조건에서 HuggingFace 캐시만 찾다가 실패한다.

정상 실행 wrapper는 다음 env를 주입해야 한다.

```env
OFFLINE_MODE=true
HF_MODEL_DOWNLOAD=false
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3
RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3
```

### 2.2 구조적 원인: 검색 모드와 무관한 RAG 강제 로드

현재 `src/ui/streamlit_app.py`는 `main()`에서 검색 모드를 처리하기 전에 항상 다음을 실행한다.

```python
pipeline = _get_pipeline(model, top_k)
```

`보험금 계산` 모드는 Fake Planner를 켠 경우에도 반드시 RAG가 필요한 것이 아니다. 최소한 비급여 표준코드 DB 매칭과 계산 샌드박스만으로 동작할 수 있어야 한다. 그러나 현재 구조는 보험금 계산 화면 진입만으로 임베딩 모델, Chroma, BM25, reranker를 모두 로드한다. 이 때문에 임베딩 자산/env 문제가 보험금 계산 UI 전체를 차단한다.

### 2.3 기존 구현 회귀

Antigravity 구현 과정에서 Mac 로컬 `src/`, `docs/`, `tests/`가 원격 DGX 저장소로 통째로 rsync되었다. 그 결과 보험금 계산과 무관한 다음 회귀가 발생했다.

- `src/ui/streamlit_app.py`에서 OCR index mode 선택 UI 삭제
- `src/ui/streamlit_app.py`에서 `resolve_index_paths`, `PairMappingStore`, `load_chunk_lookup` 연동 삭제
- `_load_heavy_components(index_mode)`가 `_load_heavy_components()`로 축소되어 v1/v2 OCR 통합 인덱스 지원 제거
- `_build_question_log_details`, `_build_answer_log_details`의 `index_mode` 로그 필드 제거
- `src/ui/admin_page.py`에서 OCR Pair Mapping 관리자 진단 UI 삭제
- `tests/test_ocr_chunker.py`, `tests/test_pipeline.py`, `tests/test_streamlit_app.py` 일부 회귀 테스트 삭제
- `docs/DGX_SPARK_RUNBOOK.md`에서 SGLang/offline runbook 섹션 삭제
- `src/parser/ocr_chunker.py`에 중복 `return chunks` 추가
- `src/rag/evidence.py`에서 `Any`가 `any`로 바뀐 타입 힌트 품질 저하

이 회귀는 보험금 계산 기능과 무관하므로 반드시 원복 또는 재통합해야 한다.

## 3. 목표

이번 수정의 목표는 다음 네 가지다.

1. 현재 Streamlit 앱 실행 오류를 해결한다.
2. 보험금 계산 모드가 불필요하게 전체 RAG 파이프라인에 의존하지 않도록 lazy loading으로 고친다.
3. Antigravity 구현 중 섞여 들어간 기존 기능 회귀를 복구한다.
4. 보험금 계산 MVP를 안전하게 테스트 가능한 상태로 분리한다.

## 4. 금지 사항

다음 작업은 하지 않는다.

- 대형 LLM/SGLang/vLLM 모델을 새로 기동하지 않는다.
- 장시간 평가 스크립트나 GPU/RAM 점유 테스트를 실행하지 않는다.
- `data/index`, `data/processed`, 모델 파일, `.venv`, `streamlit.log`, `__pycache__`를 커밋하지 않는다.
- secret 파일 내용을 출력하지 않는다.
- Mac 로컬 프로젝트 폴더를 원본으로 삼아 DGX 전체 `src/`, `tests/`, `docs/`를 rsync하지 않는다.
- 기존 OCR v1/v2 통합 기능, 관리자 진단 기능, offline/SGLang runbook을 삭제하지 않는다.

## 5. 구현 지시

### 5.1 작업 기준

모든 작업은 DGX 메인 저장소에서 직접 수행한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
```

작업 시작 전 반드시 상태를 저장한다.

```bash
git status --short --branch
git diff --stat
```

현재 작업트리에는 Antigravity QA 산출물과 보험금 계산 산출물이 섞여 있다. 임의로 `git reset --hard` 또는 대량 삭제하지 말고, 아래 범위별로 필요한 파일만 원복/수정한다.

### 5.2 즉시 실행 문제 수정

운영 안내를 다음처럼 정정한다.

1. 현재 Antigravity가 직접 띄운 8501 프로세스는 중지한다.
2. 앱은 반드시 wrapper로 실행한다.

```bash
pkill -f 'streamlit run src/ui/streamlit_app.py --server.port 8501'
/srv/ai-ops/bin/run-insurance-rag
```

단, 위 명령은 사용자가 직접 테스트할 때 사용할 운영 절차다. 구현 중에는 Streamlit 서버를 장시간 백그라운드로 띄우지 않는다.

문서 또는 보고서에 다음 원칙을 명시한다.

- `streamlit run` 직접 실행은 개발 smoke에만 허용한다.
- 오프라인/운영 검증은 `/srv/ai-ops/bin/run-insurance-rag`를 사용한다.
- 직접 실행이 꼭 필요하면 아래 env를 함께 지정한다.

```bash
OFFLINE_MODE=true \
HF_MODEL_DOWNLOAD=false \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3 \
RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3 \
.venv/bin/streamlit run src/ui/streamlit_app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
```

### 5.3 Streamlit lazy pipeline loading

`src/ui/streamlit_app.py`를 수정한다.

현재 구조:

```python
try:
    pipeline = _get_pipeline(model, top_k)
except RuntimeError as exc:
    st.error(str(exc))
    pipeline = None

search_mode = st.radio(...)
```

수정 구조:

```python
search_mode = st.radio("검색 모드", SEARCH_MODES, horizontal=True, key="search_mode")

pipeline = None
pipeline_error = None

def get_pipeline_or_show_error() -> RagPipeline | None:
    nonlocal pipeline, pipeline_error
    if pipeline is not None:
        return pipeline
    if pipeline_error is not None:
        st.error(pipeline_error)
        return None
    try:
        pipeline = _get_pipeline(model, top_k, index_mode=index_mode)
        return pipeline
    except RuntimeError as exc:
        pipeline_error = str(exc)
        st.error(pipeline_error)
        return None
```

그리고 검색 모드별로 필요한 시점에만 호출한다.

- 일반 질의: 질문 제출 시 호출
- 퀵 코드 검색: 코드 검색 제출 시 호출
- 약관 정형 검색: 검색 제출 시 호출
- 보험금 계산:
  - Fake Planner 사용 + 기준 문서가 `비급여 표준모델`만 필요한 경우에는 pipeline 없이 실행
  - RAG 근거 검색이 필요한 경우에만 `get_pipeline_or_show_error()` 호출

보험금 계산 패널에는 다음 동작을 추가한다.

- `use_fake_planner=True`일 때는 “RAG 근거 검색 사용” 체크박스를 별도 제공한다.
- 기본값은 `False`로 둔다.
- `False`이면 `run_claim_calculation(rag_pipeline=None, ...)`로 실행한다.
- `True`이면 pipeline 로드 후 실행하되, 실패 시 “비급여 DB 단독 계산으로 계속” 버튼 또는 안내를 제공한다.

### 5.4 OCR v1/v2 통합 회귀 복구

`src/ui/streamlit_app.py`는 HEAD의 OCR index mode 기능을 보존해야 한다. 다음 요소를 복구한다.

- imports:
  - `resolve_index_paths`
  - `PairMappingStore`
  - `load_chunk_lookup`
- `OCR_INDEX_MODES`
- `_build_question_log_details(..., index_mode=...)`
- `_build_answer_log_details(..., index_mode=...)`
- `_load_heavy_components(index_mode: str)`
- `_get_pipeline(model, top_k, index_mode="default")`
- sidebar의 `OCR 인덱스 모드` selectbox
- 일반/퀵 코드/약관 정형 검색 로그와 handler에 `index_mode` 전달

보험금 계산 기능은 이 구조 위에 얹어야 하며, OCR index mode를 삭제하거나 축소하지 않는다.

### 5.5 관리자 진단 회귀 복구

`src/ui/admin_page.py`의 OCR Pair Mapping 관리자 전용 표시 블록을 복구한다.

표시 항목:

- 문서
- 매핑 파일 존재 여부
- 전체 pair
- 고신뢰
- 저신뢰
- v1 연결됨
- 고신뢰 비율

### 5.6 삭제된 테스트 복구

다음 테스트를 삭제하지 말고 복구한다.

- `tests/test_ocr_chunker.py::test_chunk_from_extracted_propagates_hierarchy_context`
- `tests/test_pipeline.py`의 pair mapping 관련 테스트/fixture
- `tests/test_streamlit_app.py`의 `index_mode` 로그 검증

보험금 계산 신규 테스트는 유지하되 기존 테스트를 약화시키지 않는다.

### 5.7 보험금 계산 파이프라인 안정화

#### 5.7.1 표준코드 다중 후보 처리

`src/claim_calculation/pipeline.py`에서 표준모델 매칭 후보가 2개 이상이면 첫 번째 후보로 계산하지 않는다.

수정 원칙:

- 후보가 2개 이상이면 `decision=needs_more_info` 또는 `requires_review=True`로 계산 보류
- UI에는 후보 목록을 보여주고 사용자가 표준코드 또는 항목을 명시하도록 유도
- 사용자 입력 `input_code`가 exact match이면 계산 가능

#### 5.7.2 청구금액/수량 파싱

현재 UI는 `isdigit()`만 허용한다. 아래 입력을 안전하게 처리한다.

- `150000`
- `150,000`
- `150000원`
- 공백 포함 입력

구현 지시:

- `src/claim_calculation/models.py` 또는 별도 `amounts.py`에 `parse_money`, `parse_quantity` helper 추가
- 음수, 0원, 비정상 문자열은 사용자 오류로 반환
- Decimal 기반으로 처리

#### 5.7.3 LLM Planner 검증 강화

`src/claim_calculation/planner.py`에서 다음을 적용한다.

- 프롬프트는 “JSON 하나만 출력, 코드블록 금지”로 정리
- `_parse_and_validate_json`에서 `decision` enum 검증
- `basis_summary`, `calculation_steps`, `uncertainties` 타입 검증
- `formula_intent`가 문자열인지 검증
- `decision=calculable`이면 `formula_intent` 필수
- `formula_intent` 실행 전 `claimed_amount`, `deductible`, `payable_amount` 할당 여부 검사

#### 5.7.4 샌드박스 보강

`src/claim_calculation/code_sandbox.py`를 보강한다.

- `print` 허용 제거
- `ast.Pow` 허용 여부 재검토. 보험금 계산에는 보통 불필요하므로 제거 권장
- `ast.Attribute` 호출은 `Decimal(...).quantize(...)` 정도만 엄격히 제한
- `ast.While`, `ast.For`, comprehension, lambda, subscript, globals 접근은 계속 금지
- 실행 전 코드 길이 제한
- 실행 timeout은 별도 프로세스 또는 signal 기반으로 구현 가능하면 추가
- 최소한 timeout 미구현 상태를 보고서에 “남은 위험”으로 명시

#### 5.7.5 결과 검증

계산 결과는 다음 조건을 만족해야 한다.

- `payable_amount >= 0`
- `deductible >= 0`
- `payable_amount <= total_claimed`
- `deductible <= total_claimed`
- `payable_amount + deductible`이 `total_claimed`를 초과하면 검토 필요
- `requires_review=True`일 때 UI가 이를 명확히 표시

### 5.8 Streamlit UI 개선

보험금 계산 UI는 다음 구조로 정리한다.

1. 청구 항목 입력
2. 보상 상황 입력
3. 계산 기준 문서 선택
4. 계산 모드
   - `비급여 DB 단독/Fake Planner`
   - `RAG 근거 포함/Fake Planner`
   - `RAG 근거 포함/LLM Planner`
5. 결과
   - 청구금액
   - 공제금액
   - 지급예상액
   - 검토 필요 사유
   - 표준코드 매칭 후보 또는 적용 코드
   - 적용 근거
   - 실행 산식

UI에서 “확정 지급액”이라는 표현은 금지하고 “지급예상액”으로만 표시한다.

## 6. 검증 명령

### 6.1 빠른 단위 테스트

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
pytest tests/test_claim_*.py tests/test_streamlit_app.py tests/test_ocr_chunker.py tests/test_pipeline.py -q
```

### 6.2 import smoke

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
python - <<'PY'
from src.claim_calculation.pipeline import run_claim_calculation
from src.ui.streamlit_app import SEARCH_MODES
print("claim pipeline import OK")
print(SEARCH_MODES)
PY
```

### 6.3 앱 실행 smoke

장시간 서버를 띄우지 않는다. wrapper/env 이슈를 검증할 때만 사용한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
source .venv/bin/activate
OFFLINE_MODE=true \
HF_MODEL_DOWNLOAD=false \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3 \
RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3 \
python - <<'PY'
from src import config
from src.retrieval.embedder import Embedder
print(config.EMBEDDING_MODEL)
Embedder(config.EMBEDDING_MODEL, allow_remote_download=config.HF_MODEL_DOWNLOAD)
print("embedding load OK")
PY
```

## 7. 수동 테스트 절차

사용자가 실제 앱에서 확인할 절차는 다음과 같다.

1. 기존 직접 실행 Streamlit이 있으면 종료한다.
2. wrapper로 앱 실행:

```bash
/srv/ai-ops/bin/run-insurance-rag
```

3. Mac에서 터널:

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

4. 브라우저:

```text
http://localhost:8501
```

5. `보험금 계산` 모드에서 Fake Planner + RAG 미사용으로 테스트:

```text
청구 항목명: 도수치료
청구금액: 150000
수량: 1
급여/비급여 구분: 3대비급여
방문 형태: 통원
```

기대:

- 화면 진입 시 임베딩 오류가 먼저 뜨지 않아야 한다.
- 계산 버튼 클릭 후 지급예상액 계산 결과가 표시되어야 한다.
- 비급여 DB 매칭 실패 또는 다중 후보가 있으면 계산 확정처럼 보이지 말고 검토/선택 필요가 표시되어야 한다.

## 8. 완료 보고서

수정 완료 후 다음 문서를 작성한다.

```text
docs/100_CLAIM_CALCULATION_FIX_IMPL_REPORT.md
```

포함할 내용:

- 원인 분석
- 수정 파일 목록
- 회귀 복구 내역
- 보험금 계산 안정화 내역
- 실행한 테스트와 결과
- 실행하지 않은 GPU/LLM/장시간 테스트
- 남은 위험
- 사용자가 앱을 실행하는 정확한 절차

## 9. 수용 기준

다음 조건이 모두 만족되어야 한다.

- `보험금 계산` 모드 진입만으로 임베딩 모델 로드 실패가 발생하지 않는다.
- wrapper로 실행하면 `/srv/ai-ops/models/embedding/bge-m3`를 사용한다.
- OCR v1/v2 index mode와 pair mapping 연동이 보존된다.
- 관리자 OCR Pair Mapping 진단이 보존된다.
- 기존 삭제된 테스트가 복구된다.
- 보험금 계산 신규 테스트가 통과한다.
- Streamlit 테스트가 통과한다.
- 런타임 산출물과 대용량 파일은 Git에 포함되지 않는다.
- 결과는 “지급예상액”으로만 표시된다.
