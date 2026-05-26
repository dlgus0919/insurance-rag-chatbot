# SPA 보험금 계산 통합 보강 보고서

작성일: 2026-05-26

---

## 1. 배경

FastAPI + SPA 전환 작업을 검토한 결과, 기존 eundeo 프론트엔드 기반 화면에는 최신 메인 프로젝트의 `src/claim_calculation` 보험금 계산 파이프라인을 직접 사용하는 화면과 API가 없었다. Streamlit을 대체하려면 일반 RAG 질의뿐 아니라 보상금 계산 기능도 SPA에서 실행 가능해야 하므로 보강했다.

---

## 2. 변경 사항

- `src/api/routes/claim.py` 추가
  - `POST /api/claim/calculate` 엔드포인트를 추가했다.
  - 최신 `run_claim_calculation()` 파이프라인을 호출한다.
  - RAG/GraphDB 초기화 실패 시에도 구조화 계산은 수행하고 warning을 반환한다.
  - 계산 이벤트를 `CLAIM_CALCULATION` 감사 로그로 남긴다.
- `src/api/schemas/claim.py` 추가
  - 청구 항목, 청구 상황, 계산 결과 응답 스키마를 정의했다.
- `src/api/main.py` 수정
  - claim router를 FastAPI 앱에 등록했다.
- `frontend/html/chat.html`, `frontend/js/pages/chat.js`, `frontend/css/chat.css` 수정
  - `보험금 계산` 탭과 입력 패널을 추가했다.
  - 청구 항목명, 코드, 금액, 수량, 진단코드, 보장 주제, 방문 구분, 분류 힌트, 상황 메모를 입력할 수 있게 했다.
  - 계산 결과를 총 청구금액, 예상 공제금액, 예상 지급금액, 검토 사유, 선택 후보, 적용 근거로 분리 렌더링한다.
- `frontend/js/config.js` 수정
  - `CLAIM_CALCULATE` API 경로를 추가했다.
- `tests/test_api_claim_calculation.py` 추가
  - 계산 성공 케이스와 잘못된 금액 입력 방어를 검증한다.
- `docs/127_DGX_SPARK_TEAM_PULL_AND_SPA_RUN_GUIDE.md` 수정
  - 팀원 실행 가이드에 보험금 계산 탭 테스트 절차를 추가했다.

---

## 3. 검증

DGX Spark SSH가 일시적으로 응답하지 않는 동안 로컬 작업트리에서 다음 검증을 먼저 수행했다.

```bash
PYTHONPYCACHEPREFIX=/tmp/insurance_pycache python3 -m py_compile src/api/routes/claim.py src/api/schemas/claim.py src/api/main.py
```

결과: 통과

```bash
node --check frontend/js/pages/chat.js
```

결과: 통과

---

## 4. 원격 DGX Spark 검증 결과

SSH 연결 복구 후 원격 메인 repo(`/srv/shared/projects/insurance-rag-chatbot`)에서 다음 검증을 수행했다.

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_api_claim_calculation.py tests/test_api_chat_stream.py tests/test_api_auth_system.py -q
PYTHONPATH=. .venv/bin/pytest -q
node --check frontend/js/pages/chat.js
cd frontend && npm run build
```

결과:

```text
8 passed, 1 warning
408 passed, 3 warnings
node --check 통과
frontend/dist/app.min.js 번들 생성 완료
```

GraphDB 연동 상태도 함께 확인했다.

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
```

결과:

```text
Detailed Integrity Check: PASS
Evaluation Summary: 5/5 cases passed.
```
