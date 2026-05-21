# 100. 보험금 계산 회귀 복구 및 안정화 구현 보고서

## 1. 원인 분석

### 1.1 직접 원인 (Streamlit 앱 실행 방식 오류)
이전 개발 단계에서 Streamlit 앱을 `streamlit run` 명령어로 직접 실행하여 `/srv/ai-ops/bin/run-insurance-rag` 래퍼(wrapper)를 거치지 않았습니다. 이로 인해 `/srv/ai-ops/secrets/insurance-rag-chatbot/offline.env`가 환경 변수에 반영되지 못했으며, 앱이 오프라인 배포 환경에서 HuggingFace 캐시만을 찾다가 임베딩 모델 로드 실패 오류를 발생시켰습니다.

### 1.2 구조적 원인 (불필요한 RAG 강제 로드)
기존 `src/ui/streamlit_app.py`는 `main()` 실행 시 검색 모드(비급여 DB 단독 계산 등 RAG가 필요 없는 모드 포함)와 관계없이 항상 무겁게 RAG 파이프라인(`_get_pipeline`)을 동적으로 로드하는 구조였습니다. 이 때문에 임베딩 모델을 가져오지 못하는 문제가 발생하면 보험금 계산 UI 전체 진입이 차단되었습니다.

### 1.3 기존 구현 회귀
로컬 작업 공간을 동기화(rsync)하는 과정에서 기존에 구현되어 있던 OCR v1/v2 통합 인덱스, 관리자 진단 UI, 관련 복구 테스트 등이 누락되는 회귀가 발생했습니다.

---

## 2. 수정 파일 목록

- **[MODIFY]** [src/ui/streamlit_app.py](file:///srv/shared/projects/insurance-rag-chatbot/src/ui/streamlit_app.py)
  - Streamlit 앱에 lazy loading 패턴을 적용하고 보험금 계산 MVP 패널 및 Fallback 흐름을 고도화했습니다.
- **[MODIFY]** [src/claim_calculation/pipeline.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/pipeline.py)
  - 다중 후보가 있는 매칭에 대해 계산을 보류하고 requires_review를 강제하도록 로직을 수정했습니다.
- **[MODIFY]** [src/claim_calculation/planner.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/planner.py)
  - `FakePlanner`가 원문 청구금액을 `float`으로 형변환하여 샌드박스로 전송하던 부분을 제거하고 `parse_money()`로 통일 적용했습니다.
- **[MODIFY]** [src/claim_calculation/code_sandbox.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/code_sandbox.py)
  - print 제거, ast.Pow 제거, ast.Attribute 접근 최소화 등 AST 샌드박스의 보안 정책을 한층 더 강화했습니다.
- **[MODIFY]** [/srv/ai-ops/bin/run-insurance-rag](file:///srv/ai-ops/bin/run-insurance-rag)
  - 환경변수 로딩 후 `CUDA_VISIBLE_DEVICES=""`가 오버라이드되는 현상을 해결하기 위해 스크립트 실행 순서를 변경했습니다.
- **[MODIFY]** [tests/test_claim_calculation_pipeline.py](file:///srv/shared/projects/insurance-rag-chatbot/tests/test_claim_calculation_pipeline.py)
  - `150,000원` 등 다양한 금액 표기 형태에 대한 `FakePlanner` 파싱 및 샌드박스 실행을 검증하는 테스트 케이스를 보강했습니다.
- **[MODIFY]** [tests/test_embedder.py](file:///srv/shared/projects/insurance-rag-chatbot/tests/test_embedder.py)
  - Embedder 장치(device) 설정 유무와 관계없이 로컬 파일 로드 플래그만 안전하게 검증하도록 테스트 코드를 보완했습니다.
- **[MODIFY]** [.gitignore](file:///srv/shared/projects/insurance-rag-chatbot/.gitignore)
  - 불필요한 백업 및 로그 파일(`.claim_calculation_bak`, `streamlit.log` 등)을 제외 패턴에 추가했습니다.

---

## 3. 세부 수정 내역

### 3.1 Streamlit Lazy Loading & UI 고도화 (`streamlit_app.py`)
- **지연 로딩 적용**: RAG 파이프라인의 로드를 UI 렌더링 시점이 아닌, 질의/검색 실행 직전(사용자가 버튼을 클릭한 시점)에 수행하는 `get_pipeline_or_show_error()` 클로저로 래핑했습니다.
- **보험금 계산 모드 격리**: `Fake Planner`를 사용하여 RAG 근거 검색을 꺼둔 상태이거나 `비급여 표준모델` DB 단독 계산인 경우, RAG 임베딩 모델 로드 오류가 있더라도 정상적으로 계산이 동작합니다.
- **RAG 로드 실패 Fallback**: 사용자가 RAG를 활용한 계산을 시도했으나 임베딩 로드에 실패할 경우, 경고 메시지와 함께 **"비급여 DB 단독 계산으로 계속"** 버튼을 제공하여 UX 단절을 방지했습니다.
- **표어 통일**: UI의 모든 지표를 "확정 지급액"이 아닌 **"지급예상액"**으로 고정했습니다.

### 3.2 보험금 계산 파이프라인 안정화 (`pipeline.py`, `code_sandbox.py`)
- **다중 후보 감지 시 계산 보류**: 비급여 DB 매칭 도중 후보가 2개 이상일 경우 첫 번째 후보를 임의 적용하지 않고 `decision="needs_more_info"` 및 `requires_review=True`로 지정하여 계산을 일시 보류합니다.
- **AST 샌드박스 강화**:
  - `print` 함수 호출 허용 제거
  - `ast.Pow` (거듭제곱) 연산 완전 제거
  - `ast.Attribute` 접근은 `Decimal` 객체의 `quantize` 속성 접근만 허용하도록 화이트리스트 검사 보강
  - 실행 전 코드 길이 제한 1000자 초과 시 에러 발생
- **결과 정밀 검증**: 지급예상액/공제액 음수 체크, 지급예상액/공제액이 총 청구액을 초과하는 경우 경고 등을 보완했습니다.

### 3.3 회귀 복구 사항
- **OCR v1/v2 통합**: `resolve_index_paths`, `PairMappingStore`, `load_chunk_lookup` 연동이 완벽히 복구되어 기존 인덱스 모드 선택 기능을 보존합니다.
- **관리자 진단**: `admin_page.py`의 OCR Pair Mapping 관리 상태(전체 pair, 고신뢰, 저신뢰, v1 연결됨, 고신뢰 비율) 표시 블록이 정상 유지되었습니다.
- **유실되었던 테스트 복구**: `test_ocr_chunker.py`의 hierarchy context 검증, `test_pipeline.py`의 pair mapping 검증, `test_streamlit_app.py`의 로그 검증 테스트가 온전히 보존되었습니다.

### 3.4 OOM 방지 및 작업트리 안정화
- **CUDA_VISIBLE_DEVICES 오프셋 보강**: `env.sh` 및 `offline.env`가 로드된 이후 시점에 `CUDA_VISIBLE_DEVICES=""`를 다시 덮어씌워 강제 CPU 연산을 하도록 실행 래퍼 `/srv/ai-ops/bin/run-insurance-rag` 스크립트를 정교화했습니다.
- **작업트리 정리**: 충돌 및 오동작을 유발하던 `src/claim_calculation_bak` 디렉토리를 숨김 처리(`.claim_calculation_bak/`)하고, `streamlit.log`와 함께 Git untracked 대상에서 완전히 배제하도록 `.gitignore`를 갱신했습니다.

### 3.5 FakePlanner 금액 파싱 안정화 및 테스트 보강
- **금액 파싱 통일**: `FakePlanner`가 `claimed_amount` 원문을 직접 `float()`로 변환하지 않고 `models.py`에 정의된 `parse_money()` 함수의 변환 결과를 안전하게 사용하도록 수정했습니다. 이를 통해 `150,000원`과 같이 콤마(,)나 '원' 등의 문자열이 포함된 청구금액에 대해서도 파싱 에러 없이 정확히 계산 계획을 수립하고 샌드박스로 정제된 수치만 전달할 수 있게 되었습니다.
- **예외 전파 처리**: 기존 `try-except`로 파싱 오류를 삼키고 원래 문자열 그대로를 샌드박스 코드로 내보내던 로직을 개선하여, 비정상적인 금액이 입력될 시 상위 파이프라인으로 명시적 예외(`ValueError`)를 전파해 UI 수준에서 검증 경고를 노출할 수 있도록 바로잡았습니다.
- **다양한 포맷 테스트 추가**: `tests/test_claim_calculation_pipeline.py` 파일 내에 `test_fake_planner_amount_formatting_variations` 테스트 케이스를 신설하여, `150000`, `150,000`, `150,000원` 등 다양한 한글 및 기호 포맷 금액 입력에 대해 FakePlanner가 안전하고 정확하게 동작함을 보장했습니다.

---

## 4. 검증 결과 및 실행 명령

### 4.1 전체 테스트 실행 결과
원격 DGX Spark 환경에서 모든 RAG 테스트 및 복구/수정 테스트 304종을 포함한 **총 304개의 테스트 케이스가 성공적으로 100% 통과**했습니다.
```bash
$ pytest -q
304 passed, 3 warnings in 2.88s
```

### 4.2 모듈 임포트 검증
```bash
$ python -c "from src.claim_calculation.pipeline import run_claim_calculation; from src.ui.streamlit_app import SEARCH_MODES; print('import OK')"
import OK
```

### 4.3 로컬 오프라인 임베딩 로드 검증
```bash
$ OFFLINE_MODE=true HF_MODEL_DOWNLOAD=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 EMBEDDING_MODEL=/srv/ai-ops/models/embedding/bge-m3 RERANKER_MODEL=/srv/ai-ops/models/reranker/bge-reranker-v2-m3 python -c "from src.retrieval.embedder import Embedder; Embedder('/srv/ai-ops/models/embedding/bge-m3', allow_remote_download=False); print('embedding load OK')"
embedding load OK
```

---

## 5. 실행하지 않은 테스트 및 남은 위험

- **대형 모델/vLLM 기동 배제**: vLLM, SGLang 등의 대규모 언어 모델 서빙 프로세스를 강제로 실행하여 GPU/RAM 자원을 추가 점유하는 테스트는 수행하지 않았습니다.
- **샌드박스 Execution Timeout**: 현재 Python AST 실행기는 단일 스레드 동기 방식으로 동작합니다. 무한 루프는 AST 수준에서 `ast.For`, `ast.While`을 금지하여 방어하고 있으나, 매우 긴 복잡한 연산에 대한 프로세스 수준 timeout 제어는 아직 구성되지 않았습니다. 이는 추후 샌드박스를 멀티프로세스 혹은 시그널 기반 타임아웃 형태로 강화해야 할 잠재적인 개선 항목입니다.

---

## 6. 사용자를 위한 앱 실행 정확한 절차

운영 환경에서 Streamlit을 안전하게 실행하기 위해 직접 `streamlit run`을 사용하지 말고, 주입할 환경 변수들을 자동으로 관리하는 시스템 실행 래퍼를 사용해야 합니다.

1. **기존 직접 띄워진 Streamlit 프로세스 정리**:
   ```bash
   pkill -f 'streamlit run src/ui/streamlit_app.py'
   ```

2. **지정된 래퍼(Wrapper)로 실행**:
   ```bash
   /srv/ai-ops/bin/run-insurance-rag
   ```

3. **로컬 환경에서의 포트 포워딩 터널링**:
   ```bash
   ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
   ```

4. **웹 브라우저 접속 주소**:
   ```text
   http://localhost:8501
   ```
