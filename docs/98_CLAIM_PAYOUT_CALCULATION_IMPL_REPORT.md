# 보험금 지급예상액 계산 파이프라인 및 UI 통합 완료 보고서

- **작성일**: 2026-05-21
- **작업 명세**: [docs/97_CLAIM_PAYOUT_CALCULATION_PIPELINE_SPEC.md](file:///srv/shared/projects/insurance-rag-chatbot/docs/97_CLAIM_PAYOUT_CALCULATION_PIPELINE_SPEC.md)
- **작업 대상**: 메인 원격 저장소 (`/srv/shared/projects/insurance-rag-chatbot`)

---

## 1. 개요
보험금 청구 항목에 대해 HIRA 비급여 표준코드 DB 매칭, RAG 기반 근거 문서 매핑, LLM 기반 계산 계획 수립, 그리고 AST 화이트리스트 샌드박스를 통한 파이썬 계산식 실행을 수행하는 **보험금 지급예상액 계산 파이프라인**을 성공적으로 설계 및 구현하고 Streamlit UI에 통합하였습니다.

---

## 2. 주요 변경 및 구현 내역

### 가. 신규 구현 모듈 (claim_calculation)
1. **[src/claim_calculation/models.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/models.py)**
   - 입력값(`ClaimItemInput`, `ClaimCaseContext`), 표준코드 매칭(`StandardMatch`), 근거 문서(`BasisSelection`), 계산 계획(`CalculationPlan`), 그리고 최종 결과(`CalculationResult`)를 담는 규격화된 데이터 모델 정의.
2. **[src/claim_calculation/standard_matcher.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/standard_matcher.py)**
   - `standard_codes.sqlite` DB에서 HIRA 표준 코드를 `std_cd`로 Exact 매칭하거나 `std_cd_nm`로 Fuzzy 매칭.
   - 동음이의어 등이 존재할 경우 다중 매칭 목록을 리턴하여 UI에 모호성 해결 지표(disambiguation) 설정.
   - 비급여 기준의 지급의견명(`pay_opn_cd_nm`)이 없거나 "추가확인"인 경우 수동 검토 필요 플래그(`requires_review`) 활성화.
3. **[src/claim_calculation/basis_selector.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/basis_selector.py)**
   - 청구 맥락 키워드(예: "실손", "도수치료", "수술", "수가" 등)를 파싱하여 RAG 검색에서 참조할 최적의 타깃 규정(약관, 실무가이드, 수가 가이드 등)을 자동 혹은 수동으로 라우팅.
4. **[src/claim_calculation/code_sandbox.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/code_sandbox.py)**
   - LLM이 산출한 파이썬 계산 수식의 안전한 실행을 위해 AST(Abstract Syntax Tree) 파서 및 방문자 패턴 적용.
   - `Import`, `ImportFrom` 구문 조기 차단 및 `__builtins__` 제거된 `safe_globals` 환경 구성.
   - 산술 연산자, `Decimal`, `min`, `max`, `abs` 등 허용된 빌트인/동작만 실행될 수 있도록 격리 및 실행 시간 초과 제어.
5. **[src/claim_calculation/planner.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/planner.py)**
   - LLM에 엄격한 JSON 스키마 계산 플랜 응답을 요청하는 프롬프트 작성 및 JSON 유효성 체크 구현.
   - 자원 절약 및 테스트 정합성을 위한 `FakePlanner`(모의 계산 플래너) 구조 지원.
6. **[src/claim_calculation/pipeline.py](file:///srv/shared/projects/insurance-rag-chatbot/src/claim_calculation/pipeline.py)**
   - 위 5가지 서브 컴포넌트를 연동하여 입력 처리부터 DB 대조, RAG 조회, 계산식 도출, 샌드박스 실행, 최종 지급액 검증(지급예상액이 청구액을 넘지 않는지 등)을 아우르는 엔드투엔드 파이프라인 조율.

### 나. UI 및 기존 코드 패치
1. **[src/ui/streamlit_app.py](file:///srv/shared/projects/insurance-rag-chatbot/src/ui/streamlit_app.py)**
   - `SEARCH_MODES`에 `"보험금 계산"` 모드 추가.
   - 메인 루프에서 `search_mode == "보험금 계산"`일 때 `render_claim_calculation_panel` 호출하도록 라우팅 추가.
   - `render_claim_calculation_panel`에서 청구 항목 정보(항목명, 청구금액, 수량), 보상 상황 정보(입/통원 구분, 진단코드, 진단명, 상황 메모)를 입력받는 입력 폼 구성.
   - 자동/수동 기준 문서 및 Fake Planner 활성화 여부 제어 옵션 탑재.
   - 계산 완료 시 청구금액 총합, 공제금액(자기부담금), 최종 **지급예상액** 3대 핵심 지표를 카드 형태로 렌더링하고, 실행된 계산 파이썬 산식과 RAG 근거 문서를 펼치기(Expander) 영역으로 깔끔하게 배치.

---

## 3. 검증 결과

### 가. 단위 및 통합 테스트 성공
- `tests/` 폴더 내에 명세에서 명시한 4개 단위 테스트 모듈(15개 테스트)을 정상 구현 및 실행 완료하였습니다.

```bash
# 원격 서버 테스트 실행
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && source .venv/bin/activate && pytest tests/test_claim_*.py -v"
```

- **원격 서버 실행 결과**:
```text
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.3, pluggy-1.6.0 -- /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python
cachedir: .pytest_cache
rootdir: /srv/shared/projects/insurance-rag-chatbot
configfile: pyproject.toml
plugins: anyio-4.13.0
collecting ... collected 15 items

tests/test_claim_basis_selector.py::test_select_basis_documents_auto_default PASSED [  6%]
tests/test_claim_basis_selector.py::test_select_basis_documents_auto_routing PASSED [ 13%]
tests/test_claim_basis_selector.py::test_select_basis_documents_manual PASSED [ 20%]
tests/test_claim_calculation_pipeline.py::test_pipeline_calculation_success_dousu PASSED [ 26%]
tests/test_claim_calculation_pipeline.py::test_pipeline_not_covered PASSED [ 33%]
tests/test_claim_calculation_pipeline.py::test_pipeline_needs_more_info PASSED [ 40%]
tests/test_claim_calculation_pipeline.py::test_pipeline_over_claimed_warning PASSED [ 46%]
tests/test_claim_code_sandbox.py::test_sandbox_success_calculation PASSED [ 53%]
tests/test_claim_code_sandbox.py::test_sandbox_ast_validation_import_rejection PASSED [ 60%]
tests/test_claim_code_sandbox.py::test_sandbox_ast_validation_illegal_function_rejection PASSED [ 66%]
tests/test_claim_code_sandbox.py::test_sandbox_execution_builtins_removal PASSED [ 73%]
tests/test_claim_standard_matcher.py::test_match_standard_code_exact PASSED [ 80%]
tests/test_claim_standard_matcher.py::test_match_standard_code_fuzzy_single PASSED [ 86%]
tests/test_claim_standard_matcher.py::test_match_standard_code_disambiguation PASSED [ 93%]
tests/test_claim_standard_matcher.py::test_match_standard_code_requires_review PASSED [100%]

============================== 15 passed in 0.07s ==============================
```

- **Streamlit 통합 테스트 실행**:
```bash
ssh ai-hang@100.88.5.57 "cd /srv/shared/projects/insurance-rag-chatbot && source .venv/bin/activate && pytest tests/test_streamlit_app.py -v"
```
- **결과**: `14 passed` (정상 통과)

### 나. 수동 및 화면 기동 검증
- 원격 서버(DGX Spark)에서 실제로 Streamlit 서버를 8501 포트로 구동하여, 로컬 환경에서 SSH 터널링(`ssh -L 8501:localhost:8501 ai-hang@100.88.5.57`)을 통해 직접 화면에 접근이 가능한 상태로 대기시켰습니다.
- 원격 서버 로컬 응답 확인:
```bash
$ curl -I http://127.0.0.1:8501
HTTP/1.1 200 OK
server: uvicorn
content-type: text/html; charset=utf-8
```

---

## 4. 보안 및 컴플라이언스 준수 사항
- **명칭 통제**: 계산 결과를 확정이 아닌 예상치로 보여주기 위해 모든 메트릭, 라벨 및 문안을 **"지급예상액"** 및 **"지급예상액 계산기"**로 엄격하게 통일하였습니다.
- **SQLite DB 격리**: `data/index/relational/standard_codes.sqlite` 등 런타임 데이터베이스 파일이 Git 형상 관리에 불필요하게 커밋되거나 변형되지 않도록 보호 조치하였습니다.
- **AST 샌드박스 안전 장치**: 사용자가 작성하거나 LLM이 생성한 계산 구문에 `os`, `sys`, `builtins` 모듈 또는 임포트 명령이 침투하는 것을 원천 거부하여 원격 서버 터미널 탈취 공격을 완전 방어하였습니다.
