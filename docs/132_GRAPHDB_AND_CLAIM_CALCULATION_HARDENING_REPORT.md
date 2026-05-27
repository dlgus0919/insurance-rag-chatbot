# 132. GraphDB 교차참조 및 보험금 계산 기능 보강 보고

작성일: 2026-05-26

## 목적

GraphDB 구조화 근거에서 수가코드가 `N/A`로 표시되는 누락 계열 문제를 줄이고, 보험금 계산 화면에서 4세대/5세대 실손 기준과 복수 청구 항목을 한 번의 청구 건으로 계산할 수 있도록 보강했다.

## 핵심 변경

### GraphDB

- `SurgeryProcedure -> MedicalFeeCode` 연결 시 수술명과 HIRA 수가명칭의 완전 일치만 보던 구조를 보수적 의미 변형 기반 매칭으로 확장했다.
- 예: `췌장 이식수술 -> 췌이식술`, `간장 이식수술 -> 간이식술` 변형을 생성해 HIRA 수가코드와 연결한다.
- 전체 `graph_aliases`를 수술 alias처럼 사용하던 문제를 수정해, 수술 프로시저 노드의 alias만 수가코드 교차참조에 사용하도록 제한했다.
- HIRA 수가코드 노드의 원문 evidence를 `HAS_MEDICAL_FEE_CODE` edge에도 연결해, UI에서 근거 없는 confirmed 사실이 생기지 않게 했다.
- `check_graph_index.py`에 췌장이식술 `Q8061`, `Q8062` 및 edge evidence 검증을 추가했다.

### 보험금 계산

- 청구 context에 `policy_generation`을 추가했다.
- SPA 보험금 계산 패널 상단에 `4세대 실손`, `5세대 실손` 라디오 버튼을 추가했다.
- 청구 항목 행을 동적으로 추가/삭제할 수 있도록 UI를 수정했다.
- API 요청/응답에 복수 line item과 `line_results`를 포함하도록 확장했다.
- 기본 계산 경로는 항목별 결정론 계산으로 전환했다.
  - 4세대: 급여 20%, 비급여/3대비급여 30% 공제 기준.
  - 5세대: 지정 PDF `별첨3 [별표15] 표준약관` 기준으로 급여 20%, 중증 비급여 30%, 비중증 비급여 50% 공제 기준.
  - 통원은 약관 표의 최소공제금액을 함께 적용한다.
- 항목 구분이 불명확하면 임의 확정하지 않고 `requires_review`와 검토 사유를 남긴다.

## 근거 확인

- 지정 5세대 PDF에서 기본형 급여는 입원 본인부담금 80% 보상, 통원은 1만원/2만원과 보장대상의료비 20% 중 큰 금액 공제 구조를 확인했다.
- 지정 5세대 PDF의 특별약관1(중증 비급여)에서 입원 비급여 의료비 70% 보상 및 통원 3만원과 30% 중 큰 금액 공제를 확인했다.
- 지정 5세대 PDF의 특별약관2(비중증 비급여)에서 입원 비급여 의료비 50% 보상 및 통원 5만원과 50% 중 큰 금액 공제를 확인했다.
- 웹 조사에서는 금융위원회 5세대 실손 출시 자료와 손해보험협회 4세대 실손 안내를 대조했다. 실손 청구는 실제로 진료비 영수증 및 진료비 세부내역서처럼 여러 항목 단위 서류를 기반으로 처리된다는 점을 청구 안내 자료로 확인했다.

## 검증

원격 DGX 프로젝트(`/srv/shared/projects/insurance-rag-chatbot`)에서 실행했다.

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_graph_build_cross_refs.py tests/test_graph_retriever.py -q
# 4 passed

python scripts/build_graph_index.py --rebuild
# GraphDB build finished successfully.

PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
# Q1 Overall Coverage: PASS
# Q2 Overall Coverage: PASS
# Detailed Integrity Check: PASS

PYTHONPATH=. .venv/bin/pytest tests/test_claim_calculation_pipeline.py tests/test_api_claim_calculation.py -q
# 13 passed

node --check frontend/js/pages/chat.js
cd frontend && npm run build
# dist/app.min.js 생성 성공

PYTHONPATH=. .venv/bin/pytest -q
# 414 passed, 3 warnings
```

## 남은 주의점

- 5세대 실손 비급여는 산정특례/중증 여부에 따라 특약1/특약2 적용이 달라진다. UI는 `중증비급여`, `비중증비급여` 힌트를 제공하지만, 실제 지급 심사에서는 진료비 세부내역서 및 진단/산정특례 정보를 확인해야 한다.
- GraphDB 수가코드 교차참조는 보수적 의미 변형과 exact base matching을 사용한다. 광범위한 임의 substring 매칭은 오연결 위험 때문에 의도적으로 배제했다.
