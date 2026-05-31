# 146. GraphDB Stage 1 Review Path Precision Report

작성일: 2026-05-28
대상 단계: `145_GRAPHDB_ONTOLOGY_IMPROVEMENT_STAGE_PLAN.md`의 Stage 1

## 1. 작업 목적

Stage 1의 목적은 GraphRAG review path가 보상 담당자에게 과잉 확정된 판단으로 보이지 않도록 정밀도를 높이는 것이다.

특히 다음 결점을 우선 수정했다.

- `염증` 단독 표현이 합병증 주장으로 과잉 해석될 수 있음
- `합병증 특약` 질의에서 topic이 맞지 않는 `실손` 면책 조항이 확정 면책처럼 승격될 수 있음
- review path에 너무 많은 그래프 조항이 그대로 노출될 수 있음

## 2. 변경 내용

### 2.1 Planner 합병증 신호 정밀화

수정 파일:

- `src/graph/query_planner.py`

변경 내용:

- `합병증`, `부작용`, `후유증`은 명시적 합병증 주장으로 유지했다.
- `염증`은 `수술 후`, `시술 후`, `처치 후` 같은 사후 치료 맥락과 함께 있을 때만 합병증 review path를 만들도록 조정했다.
- 단순 염증 청구 질의는 일반 실손/조건 검토로 남기고 의학 인과를 만들지 않는다.

### 2.2 Review path scoring/ranking 추가

수정 파일:

- `src/graph/retriever.py`

변경 내용:

- review path 조항에 source priority, edge confidence, decision polarity, condition/topic 직접 일치 여부를 반영한 ranking을 추가했다.
- path당 graph step 노출을 최대 8개로 제한했다.
- `APPLIES_WHEN`, `HAS_TOPIC`, `RELATES_TO_COMPLICATION` 조항을 입력 조건과 직접 맞는 순서로 정렬한다.

### 2.3 확정 면책 승격 조건 강화

수정 파일:

- `src/graph/retriever.py`

변경 내용:

- `RELATES_TO_COMPLICATION`만 있다고 곧바로 확정 면책으로 보지 않는다.
- 조항에 연결된 `ClaimCondition` 또는 `CoverageItem`이 현재 질문의 condition/topic과 맞지 않으면 `candidate`로 남긴다.
- 입력 조건과 직접 맞는 면책/제외 조항만 `confirmed`로 승격한다.

## 3. 추가 테스트

수정 파일:

- `tests/test_graph_review_path_planner.py`
- `tests/test_graph_review_path_retriever.py`

추가/보강한 케이스:

- `눈 염증으로 실손 청구가 가능한가요?`
  - 합병증 review path를 만들지 않아야 한다.
- `미용 목적 수술 후 염증이 생겼는데 합병증 치료비를 받을 수 있나요?`
  - 합병증 review path를 유지해야 한다.
- `당뇨 진단 후 합병증 특약 보상이 되나요?`
  - `실손` 면책 조항이 `특약` 질의의 확정 면책으로 승격되면 안 된다.

## 4. 검증 결과

실행 명령:

```bash
python -m py_compile src/graph/query_planner.py src/graph/retriever.py
python -m pytest tests/test_graph_review_path_planner.py tests/test_graph_review_path_retriever.py -q
```

결과:

```text
6 passed in 7.71s
```

## 5. 남은 작업

Stage 1은 관련 회귀 테스트 기준으로 통과했다. 다음 단계는 Stage 2 `Policy Rule Ontology Layer` 구현이다.

다음 작업에서 확인해야 할 점:

- `PolicyClause.clause_type`과 `decision_polarity`의 과잉 중복 분류 감소
- `CoverageTriggerRule`, `ExclusionRule`, `LimitRule`, `DeductibleRule`, `EvidenceGateRule`, `PrecedenceRule`을 새 node type으로 늘릴지, 우선 properties 기반 rule summary로 유지할지 결정
- GraphDB rebuild 후 rule 분류 샘플이 실제 SQLite에 기대한 형태로 들어가는지 검증
