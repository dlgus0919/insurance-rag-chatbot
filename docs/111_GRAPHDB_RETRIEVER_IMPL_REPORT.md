# 111. GraphDB Retriever Integration Report

## 1. 개요
본 보고서는 `docs/110_GRAPHDB_REVIEW_AND_NEXT_INTEGRATION_SPEC.md` 명세에 따른 SQLite GraphDB의 RAG 통합, Query Planner 및 Retriever 계층 구현, 그리고 평가 결과에 대해 다룬다.
우리는 구조화된 사실(graph facts)의 신뢰도 수준(`confirmed`, `candidate`, `missing`)을 구분하고, 안전한 Read-Only 모드 연결과 테스트 데이터셋 검증을 통해 보험 분석의 정확도 및 안정성을 동시에 확보하였다.

## 2. 변경 내용 및 구현 세부사항

### 2.1 GraphStore Read-Only 모드 도입 및 트랜잭션 관리
- **읽기 전용 연결 구현**: `GraphStore(db_path, readonly=True)` 또는 `open_readonly` 메소드를 통해 SQLite 데이터베이스를 `file:...?mode=ro`로 연결하고 쓰기 권한이 요구되는 schema 생성이나 쓰기 쿼리를 전면 차단하였다.
- **안전한 트랜잭션 컨텍스트**: `with store.transaction():` 컨텍스트 매니저를 도입하여 예외 발생 시 안전하게 롤백되도록 강화하였다.

### 2.2 Query Planner & Retriever 보강
- **불용어(Stopwords) 필터링**: Query Planner에서 `"차이점과 각각 해당하는 수술종류"`와 같은 무의미한 텍스트가 수술명(`procedure_name`)으로 오추출되는 문제를 해결하기 위해 불용어 차단 규칙(`stopwords = ["차이점", "공통점", "수술종류", ...]`)을 구현하였다.
- **`policy_appendix_payment_lookup` 처리**: 질문에 약관(예: `별표7`) 및 항목 번호(예: `18`, `19`)가 포함되어 있을 때 `PolicyBenefitRule` 테이블을 정밀 조회하여 `DEFINED_IN_APPENDIX` 관계(확정 등급 `confirmed`) 팩트를 반환하도록 Retriever 로직을 추가했다.
- **수술명 노드 부재 시 Missing 팩트 반환**: 해당 수술이 DB에 존재하지 않는 경우 `EXISTS` 관계를 `status="missing"`으로 명확히 반환하여 LLM 환각 현상을 방지하도록 정렬하였다.

### 2.3 RAG 및 Streamlit UI 통합
- **Streamlit 화면 진단**: 관리자 진단 탭 내 **GraphDB 진단** 도구를 통해 DB 크기, 노드/엣지 개수, 그리고 각 빌드 명세 메타데이터를 표시한다.
- **구조화 근거 노출**: 일반 유저 단에서도 `confirmed` 사실과 `candidate` 사실을 시각적으로 명확히 분리하여 표시하고, `candidate`일 경우 "검토 후보용 정보"로 제한하여 전달하도록 렌더링을 고도화했다.
- **Chat Store 직렬화**: GraphDB 검색 사실을 JSON 스키마로 직렬화하여 기존 대화 히스토리 로딩 시에도 그래프 참조 이력이 유지되도록 구현했다.

## 3. 검증 결과 및 통과 상태

모든 검증은 LLM 의존성 없이 로컬 환경에서 엄격하게 수행되었다.

### 3.1 Unit Test 통과 (`pytest -q`)
Streamlit의 `MockPipeline` 및 RAG Mocking 테스트 케이스 등 총 325개의 테스트가 성공적으로 동작함을 확인하였다.
```bash
pytest -q
# 325 passed, 3 warnings in 2.91s
```

### 3.2 Graph DB 무결성 및 인덱스 정합성 검사 (`check_graph_index.py`)
```bash
PYTHONPATH=. python scripts/check_graph_index.py
# Q1/Q2 hard query fixture coverage PASS
# Detailed Rule, Grade, Payment Ratio & Evidence Verification PASS
# Detailed Integrity Check: PASS
```

### 3.3 자동화 평가 데이터셋 검증 (`eval_graph_qa.py`)
`eval/graph_qa.jsonl`에 규정된 5가지 시나리오(질의, 인텐트, 엔티티, 기대 팩트 상태 및 관계)에 대한 평가를 통과했다.
```bash
PYTHONPATH=. python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
# Evaluation Summary: 5/5 cases passed.
```

## 4. 남은 위험 요소 및 관리 전략
- **`candidate` 관계 승격 금지**: 수술명과 약관 조항의 엣지는 confidence 0.8 이하의 category/keyword 매칭 결과이므로, 보험금 지급 예측 시 이를 확정 지급 조항으로 계산 파이프라인에서 단정하지 않고 `review_required=True` 플래그를 결합하여 사용자 검토를 강제한다.
- **대형 DB 로딩 지연**: 53만 개 이상의 비급여 표준 노드로 인해 SQLite 쿼리가 빈번해질 시 병목이 발생하지 않도록, `readonly=True` 모드에서는 SQLite `PRAGMA query_only = ON;` 등 캐싱 및 질의 최적화 설정을 유지한다.
- **Staging 방지**: Git 작업 트리를 정돈하여 불용 리소스 포크 파일(`._*`)이나 PoC용 임시 오염물질이 staging되지 않도록 `.gitignore` 규칙을 지켰다.
