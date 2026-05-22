# 구현 보고서: GraphDB 구축 품질 고도화 및 품질 검증 강화

이 보고서는 SQLite 기반 Property GraphDB 구축 인프라의 품질을 개선하기 위해 진행된 6가지 핵심 후속 조치(일반어 부분 매칭 금지, SOL [별표7] 파서 항목 경계 복원, 회귀 테스트 구축, 에비던스 연계 구조 고도화, 검증기 정밀성 개선, DB 트랜잭션 옵션 세분화)에 대한 상세 구현 내역 및 검증 결과를 정리한 문서입니다.

---

## 1. 개요 및 배경

이전 단계에서 SQLite 기반의 대량 데이터 삽입 성능을 최적화(WAL 모드, executemany 벌크 적용 등)하여 인덱스 빌드 속도를 13초 내외로 단축하는 데 성공하였습니다.

그러나 RAG 답변 생성 시 고품질의 약관-수술 매핑 관계를 쿼리하기 위해서는 다음의 **추론 품질 이슈**를 해결해야 했습니다.
1. `"수술"`, `"관혈수술"` 등 지극히 일반적인 단어가 키워드 부분 매칭(Keyword Partial Match)에 포함되면서 불필요한 노이즈 엣지가 과도하게 생성되는 문제.
2. PDF 파싱 과정에서 등급 숫자(예: 18번 행의 `4`)가 개행과 함께 수술명 중간에 끼어들어가면서(`개흉술(開胸術,\n4\nThoracotomy)`), 공백 병합 후 18번 행과 19번 행이 하나로 합쳐져 버리는 파싱 누락 문제.
3. 관계 엣지(`POLICY_COVERS_PROCEDURE`) 생성 시 약관 구절과 매핑되는 에비던스(Evidence)의 소스 및 매핑 정보가 엣지 테이블에 누락되어 답변 출처를 증명하지 못하는 문제.
4. 검증 스크립트(`check_graph_index.py`)가 단순 엣지 존재 여부만 체크하여 파싱된 세부 데이터(룰 번호, 등급, 지급비율)의 정합성을 모니터링하지 못하는 문제.
5. 빌드 전용의 비동기 커밋 옵션(`synchronous = OFF`)이 일반 RAG 서빙/쿼리 런타임 환경에서도 전역적으로 적용되어 시스템 비정상 종료 시 데이터베이스 훼손 위험을 가질 수 있는 안전성 문제.

---

## 2. 변경 내용 및 구현 파일

### 2.1. 주요 수정 파일 및 요약

- **[store.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/store.py)**
  - `GraphStore.__init__`에 `build_mode: bool = False` 인자를 추가하여 런타임과 빌드타임 설정을 분리하였습니다.
  - 빌드 전용(`build_mode=True`)인 경우 대량 트랜잭션 처리 속도를 극대화하도록 `PRAGMA synchronous = OFF;` 및 `PRAGMA journal_mode = WAL;`를 지정합니다.
  - 일반 서빙/쿼리용(`build_mode=False`)인 경우 디스크 플러시 정합성을 보장하여 데이터가 훼손되지 않도록 안전한 `PRAGMA synchronous = NORMAL;` 및 `PRAGMA journal_mode = WAL;`로 실행되도록 개선하였습니다.

- **[extractors.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/extractors.py)**
  - `PolicyAppendixExtractor` 내에서 자사_SOL건강 약관 [별표7] 수술분류표 청크 텍스트를 공백으로 병합하기 전, **항목 번호(예: `\n18. `) 기준으로 split 전처리**를 진행합니다.
  - 각 파트 내부에서 개행으로 분리되어 존재하는 고립된 등급 숫자(`\n[1-5N]\n` 또는 줄 끝의 문자)를 정규식(`grade_lonely_pattern`)으로 탐지하여, 해당 항목의 맨 끝부분으로 이동시켜 등급 인식이 실패하거나 다음 행과 합쳐지는 현상을 원천적으로 차단했습니다.

- **[build.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/build.py)**
  - 빌드 시 `GraphStore(output_db_path, build_mode=True)`를 명시적으로 전달하도록 수정하였습니다.
  - `_build_cross_references` 함수 내에 `STOP_KEYWORDS` 리스트(`"수술"`, `"수술분류표"`, `"관혈수술"`, `"비관혈수술"`, `"관혈"`, `"비관혈"`, `"기타"`, `"이외"`, `"이외의"`)를 도입하여 일반어가 부분 매칭 키워드로 지정되지 않도록 필터링을 구축했습니다.
  - 룰 노드를 로딩할 때 `graph_node_evidence`와 `LEFT JOIN`을 걸어 룰에 대응하는 에비던스 ID를 추출한 뒤, `POLICY_COVERS_PROCEDURE` 엣지를 생성할 때 `source_evidence_id` 컬럼으로 주입하고, `store.link_edge_evidence(edge_id, evidence_id, role="source")`를 명시적으로 호출해 `graph_edge_evidence`에도 단단히 매핑하여 추적성(Traceability)을 보장했습니다.

- **[test_graph_extractors.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/tests/test_graph_extractors.py)**
  - 18번 행과 19번 행 사이에 고립된 등급 `4`가 끼어들어가 있던 실제 청크의 OCR 인식 형태를 시뮬레이션하는 **`test_policy_appendix_extractor_regression_18_19` 회귀 테스트**를 구축하였습니다.

- **[check_graph_index.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/scripts/check_graph_index.py)**
  - 단순 엣지 카운트를 넘어 `POLICY_COVERS_PROCEDURE` 타입의 엣지를 직접 파싱 및 순회하여, 약관 룰 노드에 저장된 정합성(룰 번호가 숫자/하이픈 포맷인지, 등급이 1-5 또는 N인지, 지급비율이 0%~100% 구간 내에 존재하는지)을 정밀 검사합니다.
  - 해당 엣지들에 유효한 `source_evidence_id`가 지정되어 있으며 실제로 `graph_evidence`에 기록되었는지, 그리고 `graph_edge_evidence` 조인 테이블에 맵핑 레코드가 존재하는지 정밀히 검증하도록 로직을 강화했습니다. 정합성 검증 실패 시 Exit Code 1을 반환하며 빌드 경고를 울립니다.

---

## 3. 검증 결과 및 통계

### 3.1. 단위 테스트 결과
로컬 및 원격 개발 서버(`ai-hang@100.88.5.57`)에서 전체 단위 테스트 및 그래프 단위 테스트를 수행하여 전원 성공을 확인했습니다.
```bash
$ pytest tests/test_graph_*.py -v
======================================== 6 passed in 0.21s =========================================
```
(18번 행과 19번 행의 오파싱 방지 회귀 테스트가 성공적으로 동작함을 확인하였습니다.)

### 3.2. Graph DB 재빌드 성능 및 로그
배치 트랜잭션, `executemany` 삽입, 빌드용 SQLite PRAGMA 설정으로 인해 52만 7천 건의 표준 코드 및 관계 데이터 생성이 **15초 이내**에 에러 없이 완료되었습니다.
```text
[INFO] Starting GraphDB build...
[INFO] Extracting surgery grades from /srv/shared/projects/insurance-rag-chatbot/data/index/surgery_grades.parquet
[INFO] Extracting policy appendix rules from data/processed/chunks_v1_v2_combined.jsonl
[INFO] Extracting HIRA codes from data/processed/chunks_v1_v2_combined.jsonl
[INFO] Extracting non-pay standard codes from data/index/relational/standard_codes.sqlite
[INFO] Ingested 10000 non-pay standard codes...
...
[INFO] Ingested 527679 non-pay standard codes (Final batch).
[INFO] Building cross-reference edges...
[INFO] GraphDB build finished successfully.
```

### 3.3. check_graph_index.py 최종 정합성 검증 결과
수정이 완료된 DB를 정밀 분석한 결과, 노이즈 엣지가 차단되었으며, 18.행과 19.행이 무사히 복원되어 `PolicyBenefitRule` 노드가 기존 53개에서 **69개**로 정상 증가하였습니다. 또한, 432개의 매핑 엣지 전체가 세부 정합성 및 에비던스 연계 룰을 완벽하게 만족(`PASS`)하였습니다.

```text
=== Graph DB Inspection: insurance_graph.sqlite ===

--- Manifest Info ---
  build_date: 2026-05-22T15:15:03.051146
  source_mode: v1_v2_combined
  chunks_path: data/processed/chunks_v1_v2_combined.jsonl
  standard_code_db: data/index/relational/standard_codes.sqlite
  node_count: 539247
  edge_count: 21787
  evidence_count: 21882
  alias_count: 528090

--- Summary Statistics ---
  Nodes: 539247
  Edges: 21787
  Evidence: 21882
  Aliases: 528090

--- Node Types ---
  Document: 1
  MedicalFeeCode: 9020
  NonpayStandardCode: 527679
  PolicyAppendix: 1
  PolicyBenefitRule: 69
  PolicyProduct: 1
  SurgeryCategory: 87
  SurgeryGrade: 20
  SurgeryProcedure: 2369

--- Edge Types ---
  APPEARS_IN: 9021
  DEFINED_IN_APPENDIX: 69
  HAS_CATEGORY: 4800
  HAS_GRADE: 5373
  HAS_MEDICAL_FEE_CODE: 1933
  PAYS_BY_RATIO: 70
  POLICY_COVERS_PROCEDURE: 432
  SAME_CATEGORY_AS: 89

--- Low Confidence Entities (confidence < 0.8) ---
  Low Confidence Nodes: 0
  Low Confidence Edges: 0

--- Hard Query Fixture Coverage ---
  Q1 Target Node (기관지 식도루 폐쇄술): PASS
    - Has Grade: 신1-5종 4종
    - Same Grade Peer Procedures: 268 found
    - PolicyBenefitRule covers this procedure: Yes (1 edges)
  Q1 Overall Coverage: PASS
  Q2 Target Category (소화기계): PASS
    - Digestive Grade 5 Procedures: 2 found
      * 간장 이식수술
      * 췌장 이식수술
    - Medical Fee Code links count: 1933
    - Policy Appendix payment ratio links count: 70
  Q2 Overall Coverage: PASS

--- Detailed Rule, Grade, Payment Ratio & Evidence Verification ---
  Total POLICY_COVERS_PROCEDURE edges: 432
  Validation Summary:
    - Invalid Rule Props (rule_no/grade/ratio): 0
    - Missing/Invalid source_evidence_id: 0
    - Missing graph_edge_evidence mapping: 0
  Detailed Integrity Check: PASS
```

---

## 4. 결론 및 향후 계획

본 후속 개선 조치를 통해 약관-수술 간 매핑 정확도와 추적성(Traceability)이 비약적으로 강화되었습니다.
- 무의미한 일반어 기반 노이즈 엣지를 완벽하게 걸러내어 정제된 매핑 구조를 확보했습니다.
- [별표7] 수술분류표의 파싱 누락(18번-19번) 문제를 해결하여 총 69개의 온전한 룰 노드를 정합성 있게 구축하였습니다.
- 엣지 생성 시 연관 에비던스를 함께 기록하여, RAG 모델이 특정 수술의 보장 한도나 지급 비율을 답변할 때 법적 근거가 되는 약관의 출처를 정확히 추적 및 표시할 수 있게 되었습니다.
- RAG 서빙 환경의 데이터 안정성을 위해 DB Pragma 설정을 이원화하였습니다.
- 이로써, 고품질 약관-수술 DB 생성을 완료하였으며, 하이브리드 RAG 파이프라인의 다음 단계인 그래프 탐색(Graph Retrieval) 최적화를 안정적으로 진행할 수 있습니다.
