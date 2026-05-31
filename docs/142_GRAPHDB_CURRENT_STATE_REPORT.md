# 142. GraphDB 현재 구축 상태 검토 보고서

작성일: 2026-05-28
대상 프로젝트: `insurance-rag-chatbot`

## 1. 보고 목적

이 문서는 현재 프로젝트의 GraphDB가:

1. 코드상 어떤 구조로 설계/구현되어 있는지
2. 실제 운영 SQLite 산출물이 어떤 상태인지
3. 현재 챗봇/보험금 계산 런타임에서 어떻게 쓰이는지

를 **현재 시점 기준**으로 이해하기 쉽게 정리한 현황 보고서다.

이 보고서의 “현재”는 **DGX Spark 공유 프로젝트 운영 경로**를 기준으로 한다.

```text
/srv/shared/projects/insurance-rag-chatbot/data/index/graph/insurance_graph.sqlite
```

## 2. 한 줄 결론

현재 GraphDB는 더 이상 단순한 `수술/수가/별표` 그래프가 아니다.
기존 구조 위에 **약관 조항, 사례집 사례, 진단코드, 합병증 판단 개념, 증빙 요구, 검토 조치**를 포함하는 **문서 기반 보상 판단 그래프**가 실제 SQLite에 반영된 상태다.

즉 지금은:

- 코드만 확장된 상태가 아니라
- 실제 운영 GraphDB도 재빌드 완료 상태이며
- review path가 런타임에서 실제 생성된다

로 보는 것이 맞다.

---

## 3. GraphDB의 목적

현재 GraphDB는 두 층으로 이해하면 된다.

### 3.1 기존 핵심 층: 수술/수가/별표 구조화 그래프

이 층은 아래 연결을 담당한다.

- 수술명
- 수술 종수(1-3종, 1-5종, 신1-5종)
- 수술 카테고리
- HIRA 수가코드
- 자사 SOL 건강보험 [별표7] 지급비율 후보
- 비급여 표준코드

즉, **수술 중심 보험 지식 그래프**다.

### 3.2 확장 층: 문서 기반 보상 판단 그래프

이 층은 아래를 담당한다.

- 약관 조항
- 사례집 사례
- 판단 조건
- 판단 결과 개념
- 증빙 요구
- 문서에 직접 등장한 진단코드
- 합병증/후유증/부작용 같은 판단 개념
- 세대/입원통원/의료기관 맥락
- review action

즉, 의학 일반지식 그래프가 아니라 **문서 기반 검토 경로 그래프**다.

---

## 4. 코드상 현재 스키마

기준 파일:

- [src/graph/schema.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/schema.py)

### 4.1 NodeType

기존 중심 노드:

- `Document`
- `DocumentSection`
- `Table`
- `TableRow`
- `SurgeryProcedure`
- `SurgeryGrade`
- `SurgeryCategory`
- `MedicalFeeCode`
- `PolicyProduct`
- `PolicyAppendix`
- `PolicyBenefitRule`
- `CoverageItem`
- `NonpayStandardCode`

확장된 판단 그래프 노드:

- `PolicyClause`
- `CaseExample`
- `ClaimCondition`
- `DecisionConcept`
- `EvidenceRequirement`
- `DiagnosisCode`
- `ComplicationConcept`
- `PolicyGeneration`
- `VisitContext`
- `FacilityContext`
- `ReviewAction`

### 4.2 EdgeType

기존 중심 엣지:

- `HAS_GRADE`
- `HAS_CATEGORY`
- `HAS_MEDICAL_FEE_CODE`
- `DEFINED_IN_APPENDIX`
- `POLICY_COVERS_PROCEDURE`
- `PAYS_BY_RATIO`
- `SAME_CATEGORY_AS`
- `APPEARS_IN`

확장된 판단 그래프 엣지:

- `HAS_TOPIC`
- `APPLIES_WHEN`
- `HAS_DECISION`
- `REQUIRES_EVIDENCE`
- `RELATES_TO_DIAGNOSIS`
- `RELATES_TO_COMPLICATION`
- `APPLIES_TO_GENERATION`
- `APPLIES_TO_VISIT`
- `APPLIES_TO_FACILITY`
- `HAS_REVIEW_ACTION`
- `SIMILAR_CASE_FOR`

### 4.3 명시적으로 하지 않는 것

현재 구조는 아래를 전역 지식으로 만들지 않는다.

- 질병 -> 합병증 의학 인과
- 질병 -> 시술 적응증 일반지식
- 임상 상식 기반 causal edge

즉 `CAUSES`, `LEADS_TO`, `TREATED_BY`, `COMPLICATES_TO` 같은 의학 인과 그래프는 없다.

---

## 5. 저장 방식

기준 파일:

- [src/graph/store.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/store.py)

GraphDB는 SQLite 기반 property graph다.

핵심 테이블:

- `graph_nodes`
- `graph_aliases`
- `graph_edges`
- `graph_evidence`
- `graph_node_evidence`
- `graph_edge_evidence`
- `graph_build_manifest`

런타임 조회는 `readonly=True`로 SQLite `mode=ro` 연결을 사용한다.
즉 **빌드 시에만 쓰기, 서비스 시에는 읽기 전용**이다.

---

## 6. 빌드 파이프라인

기준 파일:

- [scripts/build_graph_index.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/scripts/build_graph_index.py)
- [src/graph/build.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/build.py)

기본 빌드 명령:

```bash
python scripts/build_graph_index.py
```

현재 빌드 순서:

1. `SurgeryGradeExtractor`
2. `PolicyAppendixExtractor`
3. `HiraCodeExtractor`
4. `NonpayStandardExtractor`
5. `SilsonCoverageExtractor`
6. `PolicyReviewExtractor`
7. `_build_cross_references()`
8. manifest 저장

즉 구조는:

- 먼저 기존 수술/수가/별표 그래프를 만들고
- 그 위에 문서 기반 판단 그래프를 추가하는 방식

이다.

---

## 7. Extractor별 역할

기준 파일:

- [src/graph/extractors.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/extractors.py)

### 7.1 `SurgeryGradeExtractor`

생성:

- `SurgeryProcedure`
- `SurgeryGrade`
- `SurgeryCategory`
- `HAS_GRADE`
- `HAS_CATEGORY`

### 7.2 `PolicyAppendixExtractor`

생성:

- `PolicyProduct`
- `PolicyAppendix`
- `PolicyBenefitRule`
- `DEFINED_IN_APPENDIX`
- `PAYS_BY_RATIO`

### 7.3 `HiraCodeExtractor`

생성:

- `MedicalFeeCode`
- `APPEARS_IN`

### 7.4 `NonpayStandardExtractor`

생성:

- `NonpayStandardCode`
- alias

이 노드가 지금도 GraphDB 전체 규모의 대부분을 차지한다.

### 7.5 `SilsonCoverageExtractor`

생성:

- `CoverageItem`
- `HAS_CATEGORY` 기반 hierarchy

현재는 `실손 -> 3대비급여 / 상급병실료 차액 / 건강보험 미적용 특례 / 합병증 치료 / 미용 목적 치료`까지 포함한다.

### 7.6 `PolicyReviewExtractor`

이번 확장의 핵심이다.

생성:

- `PolicyClause`
- `CaseExample`
- `ClaimCondition`
- `DecisionConcept`
- `EvidenceRequirement`
- `DiagnosisCode`
- `ComplicationConcept`
- `PolicyGeneration`
- `VisitContext`
- `FacilityContext`
- `ReviewAction`

그리고 아래 연결을 만든다.

- 조항 -> 주제
- 조항 -> 조건
- 조항 -> 판단 결과
- 조항 -> 증빙 요구
- 조항 -> 합병증 개념
- 조항 -> 진단코드
- 사례 -> 주제 / 조건 / 판단 결과

중요한 제약:

- `합병증`은 질병별 ontology가 아니라 판단 개념
- `DiagnosisCode`는 문서에 직접 등장한 코드만
- 외부 KCD/SNOMED/의학 ontology는 도입하지 않음

---

## 8. Cross-reference 생성 로직

기준 파일:

- [src/graph/build.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/build.py)

핵심 연결:

### 8.1 `PolicyBenefitRule -> SurgeryProcedure`

엣지:

- `POLICY_COVERS_PROCEDURE`

의미:

- 약관 [별표7] 조항과 특정 수술의 연결

### 8.2 `SurgeryProcedure -> MedicalFeeCode`

엣지:

- `HAS_MEDICAL_FEE_CODE`

의미:

- 실무가이드 수술명과 HIRA 수가코드 연결

### 8.3 `SurgeryCategory <-> SurgeryCategory`

엣지:

- `SAME_CATEGORY_AS`

의미:

- 문서 간 카테고리 이름의 느슨한 연결

---

## 9. Query Planner / Retriever 현재 구조

기준 파일:

- [src/graph/query_planner.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/query_planner.py)
- [src/graph/retriever.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/graph/retriever.py)

Planner는 현재 아래를 읽는다.

- 수술명
- 등급체계 / 등급값
- 카테고리
- 상품명 / 별표 / HIRA code
- 진단코드
- coverage topic
- condition
- complication asserted
- evidence tag
- policy generation
- visit type
- facility type

Retriever 결과는 두 층으로 나뉜다.

### 9.1 기존 fact 층

- `facts`
- `source_chunk_ids`
- `warnings`

### 9.2 새 review path 층

- `session_assertions`
- `review_paths`
- `required_evidence`
- `review_actions`

즉 현재 구조는 **fact retrieval + review path retrieval 혼합형**이다.

---

## 10. 현재 런타임 사용 위치

### 10.1 일반 RAG 답변

기준:

- [src/rag/pipeline.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/rag/pipeline.py)

동작:

- `GraphRetriever.retrieve(question)`
- `build_graph_context(graph_result)`
- review path + 기존 구조화 사실을 prompt context 앞단에 삽입

### 10.2 API 응답 직렬화

기준:

- [src/api/rag_service.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/api/rag_service.py)

동작:

- `facts`, `session_assertions`, `graph_review_paths`, `required_evidence`, `review_actions`를 payload로 직렬화

### 10.3 보험금 계산 파이프라인

기준:

- [src/claim_calculation/pipeline.py](/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/claim_calculation/pipeline.py)

동작:

- claim context와 item name으로 Graph query 생성
- `graph_result.review_paths`가 있으면 `review_required` 판단 강화
- 합병증/후유증/부작용이면 review path를 강제로 참고
- 직접 연결된 exclusion 성격 경로가 있으면 보수적으로 `payable = 0`, `deductible = claimed`

즉 GraphDB는 현재 **RAG 답변 보조층 + 보험금 계산 검토 보조층** 둘 다로 연결돼 있다.

---

## 11. 실제 운영 SQLite 산출물 상태

실제 파일:

- `/srv/shared/projects/insurance-rag-chatbot/data/index/graph/insurance_graph.sqlite`

manifest:

- `build_date = 2026-05-28T16:06:03.445372`
- `source_mode = v1_v2_combined`
- `chunks_path = data/processed/chunks_v1_v2_combined.jsonl`
- `standard_code_db = data/index/relational/standard_codes.sqlite`

### 11.1 실제 테이블 건수

- `graph_nodes`: `545,136`
- `graph_edges`: `35,835`
- `graph_evidence`: `27,015`
- `graph_aliases`: `528,090`

### 11.2 실제 node type 분포 핵심

- `NonpayStandardCode`: `527,679`
- `MedicalFeeCode`: `9,020`
- `PolicyClause`: `3,995`
- `SurgeryProcedure`: `2,369`
- `CaseExample`: `1,138`
- `DiagnosisCode`: `695`
- `SurgeryCategory`: `87`
- `PolicyBenefitRule`: `69`
- `SurgeryGrade`: `20`
- `CoverageItem`: `15`
- `ClaimCondition`: `13`
- `ReviewAction`: `7`
- `ComplicationConcept`: `6`
- `DecisionConcept`: `6`
- `FacilityContext`: `5`
- `EvidenceRequirement`: `4`
- `PolicyGeneration`: `3`
- `VisitContext`: `2`

추가 검증:

- `PolicyClause.properties.rule_types` 적재 건수: `3,995 / 3,995`
- `PolicyClause.properties.rule_summary`는 rule type, decision polarity, 원문 excerpt를 함께 보존한다.

### 11.3 실제 edge type 분포 핵심

- `APPEARS_IN`: `9,021`
- `HAS_GRADE`: `5,373`
- `APPLIES_TO_GENERATION`: `5,185`
- `HAS_CATEGORY`: `4,813`
- `RELATES_TO_DIAGNOSIS`: `1,881`
- `APPLIES_WHEN`: `1,924`
- `HAS_REVIEW_ACTION`: `1,589`
- `APPLIES_TO_FACILITY`: `1,552`
- `HAS_DECISION`: `1,088`
- `APPLIES_TO_VISIT`: `748`
- `HAS_MEDICAL_FEE_CODE`: `709`
- `HAS_TOPIC`: `672`
- `POLICY_COVERS_PROCEDURE`: `432`
- `SIMILAR_CASE_FOR`: `264`
- `RELATES_TO_COMPLICATION`: `178`
- `REQUIRES_EVIDENCE`: `178`

### 11.4 핵심 해석

중요한 점:

- 새 판단 그래프 노드가 **실제로 존재한다**
- review path용 edge도 **실제로 존재한다**
- 현재 운영 GraphDB는 **기존 수술 그래프 + 문서 판단 그래프 결합 상태**다

---

## 12. 현재 GraphDB가 실제로 잘 하는 것

### 12.1 기존 강점

- 수술 종수 조회
- 동일 종수 수술 peer 탐색
- 카테고리별 수술 목록화
- 실무가이드 수술명 ↔ 심평원 수가코드 연결
- [별표7] 지급비율 후보 연결
- 비급여 표준코드 lookup

### 12.2 새로 가능해진 것

- 합병증/후유증/부작용 관련 clause 기반 review path
- 문서에 직접 등장한 진단코드의 clause/case 연결
- 증빙 요구사항 노출
- review action 노출
- 보험금 계산 시 review-required 강화

즉 GraphDB는 현재 **수술 lookup 엔진**을 넘어서 **문서 근거 검토 경로 엔진** 역할까지 수행한다.

---

## 13. 현재 한계

현재 운영 GraphDB의 한계는 “아직 없다”가 아니라 **정밀도 문제** 쪽이다.

### 13.1 구조적 한계

- `PolicyReviewExtractor`는 chunk heuristic 기반이다
- 따라서 clause granularity가 거칠 수 있다
- topic / condition / decision 매칭이 과포함될 수 있다

### 13.2 의미적 한계

- 외부 의학 ontology를 도입하지 않았기 때문에
- 질병 -> 합병증 일반 인과는 전역 지식으로 추론하지 않는다
- review path는 “의학 인과 설명”이 아니라 “문서 기반 검토 경로”다

### 13.3 런타임 품질 한계

- 일부 `complication_review` summary는 exclusion 쪽으로 다소 강하게 해석될 수 있다
- 즉 review path는 생성되지만, **경로 relevance ranking**은 다음 개선 과제다

---

## 14. 지금 시점의 정확한 해석

현재 GraphDB는 이렇게 이해하면 된다.

### 14.1 이미 실제로 구축되어 있는 것

- 수술, 종수, 카테고리
- HIRA 수가코드
- 비급여 표준코드
- SOL [별표7] 지급비율 후보
- 약관 조항 그래프
- 사례집 사례 그래프
- 합병증 판단 개념 노드
- 진단코드 기반 review path 연결
- 세대/입원통원/의료기관/증빙/검토조치 그래프

### 14.2 아직 고도화가 필요한 것

- clause relevance ranking
- 합병증 review path의 문맥 정밀도
- topic / condition 과포함 억제
- 운영 기준 DB와 로컬 개발용 DB의 시점 동기화

---

## 15. 현재 상태에서 필요한 다음 작업

### 15.1 retrieval / ranking 정밀화

우선순위:

1. `complication_review` summary가 과하게 exclusion으로 기우는지 점검
2. clause relevance ranking 보강
3. topic / condition 매칭의 과포함 감소

### 15.2 review path 평가셋 보강

필요 항목:

1. 합병증 주장 + 미용 목적
2. 진단코드 explicit clause
3. 상급병실료 차액
4. 건강보험 미적용 특례
5. 사례집 + 약관 joint review path

### 15.3 운영 기준 동기화 관리

현재 보고서는 DGX 운영 SQLite 기준이다.
로컬 작업 디렉터리의 `data/index/graph`와 운영 SQLite의 시점 차이는 별도로 관리해야 한다.

---

## 16. 결론

현재 GraphDB 현황을 한 문장으로 요약하면 이렇다.

**현재 운영 SQLite는 기존 수술/수가/별표 중심 GraphDB 위에, 문서 기반 보상 판단 GraphDB가 실제로 반영된 상태다.**

조금 더 풀면:

- **이미 구축되어 있는 것**: 수술, 종수, 카테고리, HIRA 수가코드, 비급여 표준코드, SOL [별표7] 지급비율 후보, 약관 조항, 사례집 사례, 합병증 개념, 진단코드 기반 검토 경로, 증빙/검토조치 그래프
- **현재 남은 과제**: review path relevance와 문서 매칭 정밀도 개선

따라서 지금 GraphDB를 이해할 때는 아래처럼 봐야 한다.

1. **현재 코드 구조**는 확장형 문서 판단 그래프까지 구현됨
2. **현재 운영 SQLite 산출물**도 새 판단 노드와 review path용 edge를 포함함
3. **다음 실질 단계**는 재빌드가 아니라 retrieval/review 품질을 정밀화하는 것
