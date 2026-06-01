# 151. GraphDB 빌드 파이프라인 결점 보고서

작성일: 2026-05-28  
대상 DB: `/srv/shared/projects/insurance-rag-chatbot/data/index/graph/insurance_graph.sqlite`  
빌드일: `2026-05-28T16:06:03.445372`  
작성 경위: 142번 문서 검증 과정에서 실제 DB를 직접 조회하여 발견된 결점을 종합 정리

---

## 1. 개요

이 문서는 현재 운영 GraphDB의 빌드 파이프라인에서 확인된 **구조적 결점 7가지**를 분류·기록한다.  
각 결점은 발견 경위, 실제 증거, 영향 범위, 권장 조치로 구성된다.  
코드 수정은 이 문서의 범위가 아니며, 다음 개선 사이클에서 우선순위를 부여하기 위한 참고 문서다.

---

## 2. 결점 목록

| # | 결점 | 심각도 | 영향 범위 |
|---|------|--------|-----------|
| D-01 | CoverageItem 속성(properties) 전체 비어 있음 | 🔴 High | 보험금 계산 파이프라인 |
| D-02 | PolicyClause rule_types 48.2%가 미분류 기본값 | 🟠 Medium | review path 정밀도 |
| D-03 | PolicyClause canonical_name 대규모 중복 | 🟠 Medium | retrieval 정밀도 |
| D-04 | CaseExample canonical_name 품질 저하 | 🟠 Medium | 사례 검색 정밀도 |
| D-05 | 고아 노드(엣지 없는 판단 그래프 노드) 존재 | 🟡 Low | review path 조회 |
| D-06 | POLICY_COVERS_PROCEDURE 전체가 낮은 신뢰도(0.8) | 🟡 Low | 수술 보장 연결 신뢰도 |
| D-07 | ClaimCondition 13개 전체 evidence 링크 없음 | 🟡 Low | 조건 근거 추적 불가 |

---

## 3. 결점 상세

### D-01 CoverageItem 속성(properties) 전체 비어 있음

**심각도**: 🔴 High

**발견 경위**:  
142번 문서 업데이트 중 CoverageItem 트리를 실제 DB와 대조하는 과정에서 발견.

**실제 증거**:

```text
3대비급여: {}
건강보험 미적용 특례: {}
급여: {}
도수치료: {}
미용 목적 치료: {}
비급여: {}
비중증 비급여: {}
상급병실료 차액: {}
실손: {}
자기공명영상진단(MRI/MRA): {}
주사료: {}
중증 비급여: {}
증식치료: {}
체외충격파치료: {}
합병증 치료: {}
```

전체 15개 CoverageItem 노드의 `properties`가 모두 빈 딕셔너리다.

**원인**:  
`SilsonCoverageExtractor.extract()`에서 노드 생성 시 `properties` 인자를 전달하지 않는다. 현재는 보장 계층 이름만 노드로 만들고, 실제 약관에서 추출해야 할 속성(보상 비율, 연간 한도, 자기부담 비율, 세대 적용 범위 등)을 추출·저장하는 로직이 없다.

**영향**:
- 5세대 실손 보험금 계산 시 GraphDB에서 한도·비율을 참조할 수 없다.
- 현재 보험금 계산 파이프라인은 CoverageItem의 `properties`를 직접 조회하지 않기 때문에 런타임 오류는 없으나, `GraphDB → 계산 직접 연동`을 구현하면 즉시 문제가 된다.

**권장 조치**:  
`SilsonCoverageExtractor`에서 각 항목별 보상 비율, 한도, 자기부담 비율을 약관 문서 청크에서 추출해 `properties`에 저장하는 로직을 추가한다.

---

### D-02 PolicyClause rule_types 48.2%가 미분류 기본값

**심각도**: 🟠 Medium

**발견 경위**:  
142번 문서 검증 중 rule_types 전체 분포를 집계하는 쿼리를 실행하여 발견.

**실제 증거**:

| rule_type | 건수 |
|-----------|------|
| CoverageTriggerRule | 1,193 |
| PrecedenceRule | 1,139 |
| LimitRule | 365 |
| ExclusionRule | 306 |
| EvidenceGateRule | 261 |
| DeductibleRule | 152 |
| **`PolicyClause` (미분류 기본값)** | **1,924 (48.2%)** |

**원인**:  
`_classify_rule_types()`는 키워드 매칭 방식이다. 해당 조항에 아래 토큰이 하나도 없으면 `["PolicyClause"]`(기본값)를 반환한다.

```text
면책, 보상하지, 지급하지 않는, 보상 제외  (ExclusionRule)
보장, 지급사유, 보험금, 보상 가능, 지급한다, 보상한다  (CoverageTriggerRule)
한도, 최대, 횟수, 연간, 회당  (LimitRule)
공제, 자기부담, 본인 부담, 부담한 의료비  (DeductibleRule)
세부내역서, 진단서, 영수증, 확인서, 제출, 첨부, 증빙  (EvidenceGateRule)
우선, 다만, 제외하고, 불구하고, 한하여, 경우에 한하여  (PrecedenceRule)
```

미분류 노드의 대부분은 수술분류표 해설, 표/수가 행, 목차성 청크 등 실질적 판단 의미가 없는 청크에서 추출된 것으로 보인다.

**영향**:
- review path에서 rule_type 기반 필터링 또는 우선순위를 적용할 때 48.2%의 조항이 역할 분류 없이 참조된다.
- ExclusionRule·LimitRule 등을 기준으로 면책/한도 판단을 강화하려 해도 절반의 조항이 활용되지 못한다.

**권장 조치**:
1. 미분류 노드 중 실질 판단 의미 없는 청크(수가 표 행, 목차, 표지 등)를 `PolicyReviewExtractor`에서 사전 필터링한다.
2. 키워드 분류 토큰 목록을 확장하거나, LLM 기반 rule type 분류 후처리를 도입한다.

---

### D-03 PolicyClause canonical_name 대규모 중복

**심각도**: 🟠 Medium

**발견 경위**:  
빌드 파이프라인 감사 중 canonical_name 중복 집계를 실행하여 발견.

**실제 증거**:

| canonical_name | 중복 건수 |
|----------------|-----------|
| `제1장 수술분류표 해설` | 204개 |
| `제1조(보험금의 지급사유)` | 162개 |
| `제2부 제9장 처치 및 수술료 등` | 117개 |
| `제2장 장해분류표 해설` | 92개 |
| `제2조(보험금 지급에 관한 세부규정)` | 87개 |

**원인**:  
`PolicyReviewExtractor._derive_clause_title()`는 메타데이터의 `section`, `chapter`, `part` 필드를 우선 사용해 canonical_name을 만든다. 동일 섹션에 해당하는 청크가 여러 개이면 모두 같은 canonical_name을 가진 별개의 노드로 생성된다.

```python
def _derive_clause_title(self, text, meta):
    for key in ("section", "chapter", "part"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value  # 같은 섹션명 → 모두 동일 canonical_name
```

**영향**:
- `제1장 수술분류표 해설` 조항을 조회하면 204개의 개별 노드가 반환된다.
- 동일 섹션의 여러 청크가 각각 다른 edge를 가지므로 retriever가 중복 결과를 반환할 수 있다.
- review path의 relevance ranking에서 동일 이름 노드가 과다 노출된다.

**권장 조치**:
1. `_extract_clause_id()`에 chunk_id를 suffix로 붙여 `canonical_name`을 고유하게 만든다.
2. 또는 동일 canonical_name을 하나의 노드로 merge하고 evidence를 모두 연결하는 upsert 전략을 적용한다.

---

### D-04 CaseExample canonical_name 품질 저하

**심각도**: 🟠 Medium

**발견 경위**:  
빌드 파이프라인 감사 중 CaseExample 노드 샘플을 조회하여 발견.

**실제 증거**:

```text
'손해보험'
'일러두기'
'CONTENTS'
'CONTENTS'
'손해보험 소비자 상담 주요 사례집'
'CONTENTS'
'1. 상담신청 내용'
'고로 인하여 남을 죽게 하거나 다치게 한 경우와 남의 재물을 없애거나...'
```

**원인**:  
`PolicyReviewExtractor`에서 사례집 청크를 `CaseExample` 노드로 분류하는 조건이 너무 느슨하다. 사례집 문서의 목차, 표지, 일러두기 페이지의 청크도 `CaseExample`로 추출되고 있다. `_extract_case_no()`가 `사례N`, `QN` 패턴을 찾지 못하면 chunk_id를 그대로 반환하지만, canonical_name은 메타데이터의 첫 번째 필드를 그대로 사용한다.

**영향**:
- 1,138개 CaseExample 중 상당수가 실제 상담 사례가 아닌 목차·표지 청크다.
- 사례 검색 쿼리에서 노이즈가 발생하고, `SIMILAR_CASE_FOR` 엣지도 일부 오연결된다.

**권장 조치**:
1. `CaseExample` 분류 조건에 `사례N`, `Q&A`, `상담 내용` 등 명시적 패턴 필터를 추가한다.
2. 목차·표지 청크를 나타내는 메타데이터 신호(예: `page < 5`, `section == 'CONTENTS'`)가 있으면 추출 대상에서 제외한다.

---

### D-05 고아 노드(엣지 없는 판단 그래프 노드) 존재

**심각도**: 🟡 Low

**발견 경위**:  
빌드 파이프라인 감사 중 엣지가 없는 노드를 조회하여 발견.

**실제 증거**:

| 노드 타입 | canonical_name |
|-----------|----------------|
| `CoverageItem` | `급여` |
| `ComplicationConcept` | `미용 목적 시술 후 합병증` |
| `ClaimCondition` | `건강보험 미적용` |
| `ClaimCondition` | `추가 치료` |
| `DecisionConcept` | `자동 계산 보류` |
| `PolicyGeneration` | `5세대` |
| `ReviewAction` | `인간 심사 필요` |

**원인**:  
각 노드는 생성되었으나, 대응하는 `PolicyClause`나 `CaseExample`와의 엣지 연결이 누락되어 있다.  
`PolicyGeneration: 5세대`는 `APPLIES_TO_GENERATION` 엣지가 전혀 없다는 의미로, 5세대 실손 약관 조항이 세대 컨텍스트와 연결되지 않은 상태다.

**영향**:
- 고아 노드는 어떤 review path에서도 도달하지 못한다.
- `PolicyGeneration: 5세대`가 고아인 경우, 5세대 특화 조항 검색이 작동하지 않을 수 있다.

**권장 조치**:
1. 빌드 완료 후 무결성 검사에 "고아 노드 검출" 항목을 추가한다.
2. `PolicyGeneration: 5세대` 고아 원인을 구체적으로 추적해 `APPLIES_TO_GENERATION` 엣지 연결 로직을 점검한다.

---

### D-06 POLICY_COVERS_PROCEDURE 전체가 낮은 신뢰도(0.8)

**심각도**: 🟡 Low

**발견 경위**:  
빌드 파이프라인 감사 중 POLICY_COVERS_PROCEDURE 신뢰도 분포를 집계하여 발견.

**실제 증거**:

```text
POLICY_COVERS_PROCEDURE: 432건 전체 confidence = 0.8
confidence = 1.0: 0건
```

**원인**:  
`build.py`의 cross-reference 로직에서 exact/alias 매칭이 성공하면 `confidence=1.0`으로 엣지를 생성하고 `continue`로 즉시 다음 rule로 넘어간다. 그러나 실제 432건은 모두 partial keyword match(1.2 분기)에서 생성되었고, exact/alias match(1.1 분기)에서 생성된 엣지가 하나도 없다는 것을 의미한다.

이는 `PolicyBenefitRule`의 normalized_name이 `SurgeryProcedure`의 normalized_name 또는 alias와 정확히 일치하는 경우가 없다는 뜻이다. 즉 [별표7] 조항명과 수술명 간의 정규화 일치 정밀도에 문제가 있다.

**영향**:
- 보장 연결 432건 전체가 `partial_keyword`로만 연결되어 있어 오연결 가능성이 있다.
- confidence 임계값 기반 필터링을 적용하면 수술 보장 연결이 전부 제거된다.

**권장 조치**:
1. `PolicyBenefitRule`과 `SurgeryProcedure`의 normalized_name 정규화 함수가 일관적으로 적용되는지 점검한다.
2. alias 매칭 범위를 점검하고, [별표7] 수술명과 실무가이드 수술명 간의 표기 차이를 수동으로 확인한다.

---

### D-07 ClaimCondition 13개 전체 evidence 링크 없음

**심각도**: 🟡 Low

**발견 경위**:  
빌드 파이프라인 감사 중 판단 그래프 노드의 evidence 링크 현황을 집계하여 발견.

**실제 증거**:

```text
ClaimCondition: 전체 13개 중 evidence 없음 13개 (100%)
PolicyClause: 전체 3995개 중 evidence 없음 0개
CaseExample: 전체 1138개 중 evidence 없음 0개
```

**원인**:  
`PolicyReviewExtractor`에서 `ClaimCondition` 노드를 생성할 때 `graph_node_evidence` 테이블에 evidence를 링크하는 `store.link_node_evidence()` 호출이 누락된 것으로 추정된다. `PolicyClause`와 `CaseExample`는 0개로 evidence 링크가 정상이다.

**영향**:
- `ClaimCondition` 노드에서 원문 근거(청크)를 역추적할 수 없다.
- audit view에서 조건의 출처를 확인할 수 없다.

**권장 조치**:  
`PolicyReviewExtractor`에서 `ClaimCondition` 노드 생성 직후 `store.link_node_evidence()`를 호출하도록 추가한다.

---

## 4. 빌드 운영 절차 상의 결점

### P-01 DGX 코드 동기화 미검증 (Stage 5에서 실제 발생)

**발견 경위**: Stage 5 리빌드 게이트(150번 문서)에서 실제로 발생한 장애.

**경위**:  
Stage 5 첫 DGX 리빌드 후 `PolicyClause`, `CaseExample`, `ReviewAction` 등 새 판단 노드가 SQLite에 존재하지 않아 `eval_graph_review_paths.py` 결과가 `3/5 PASS`로 실패했다. 원인은 DGX의 `src/graph/build.py`가 로컬 최신 코드보다 뒤처져 `PolicyReviewExtractor` 호출 코드가 빠져 있었기 때문이다.

**권장 조치**:  
리빌드 전 코드 동기화를 자동 검증하는 단계를 빌드 스크립트에 추가한다. 예: `git diff HEAD~1 src/graph/build.py` 출력을 로그로 남기거나, checksum 비교를 수행한다.

---

## 5. 결점 우선순위 및 다음 단계

### 즉시 대응 (다음 개선 사이클 포함)

1. **D-01**: CoverageItem 속성 보강 — 보험금 계산 파이프라인의 GraphDB 직접 연동을 막는 유일한 구조적 공백이다.
2. **D-02**: rule_types 미분류 비율 감소 — review path 정밀도와 직결된다.
3. **D-05**: `PolicyGeneration: 5세대` 고아 원인 추적 — 5세대 실손 약관 조항 검색 오동작 가능성.

### 중기 대응

4. **D-03**: PolicyClause canonical_name 중복 해소 — retrieval 노이즈 제거.
5. **D-04**: CaseExample 품질 필터링 — 목차/표지 청크 제거.
6. **D-06**: POLICY_COVERS_PROCEDURE 신뢰도 0으로 확인 — [별표7] ↔ 수술명 정규화 정밀도 점검.

### 빌드 운영 절차

7. **D-07 + P-01**: 빌드 무결성 검사에 "고아 노드", "evidence 없는 ClaimCondition", "코드 동기화 상태" 항목 추가.

---

## 6. 참고 문서

- [142. GraphDB 현재 구축 상태 검토 보고서](142_GRAPHDB_CURRENT_STATE_REPORT.md)
- [145. GraphDB Ontology Improvement Stage Plan](145_GRAPHDB_ONTOLOGY_IMPROVEMENT_STAGE_PLAN.md)
- [150. Stage 5 Evaluation Rebuild Gate Report](150_GRAPHDB_STAGE5_EVALUATION_REBUILD_GATE_REPORT.md)
