# 147. GraphDB Stage 2 Policy Rule Layer Report

작성일: 2026-05-28
대상 단계: `145_GRAPHDB_ONTOLOGY_IMPROVEMENT_STAGE_PLAN.md`의 Stage 2

## 1. 작업 목적

Stage 2의 목적은 약관 조항을 단순 `PolicyClause`로만 보관하지 않고, 보상 실무에서 바로 쓰는 rule layer로 분해하는 것이다.

다만 이번 단계에서는 SQLite schema와 기존 rebuild 파이프라인을 안정적으로 유지하기 위해 새 node type을 추가하지 않았다. 대신 `PolicyClause.properties`에 rule layer 정보를 추가했다.

## 2. 구현 방식

수정 파일:

- `src/graph/extractors.py`
- `tests/test_graph_policy_clause_extractor.py`

추가한 `PolicyClause.properties` 필드:

- `rule_types`
- `rule_summary`

지원하는 rule type:

- `CoverageTriggerRule`
- `ExclusionRule`
- `LimitRule`
- `DeductibleRule`
- `EvidenceGateRule`
- `PrecedenceRule`

설계 판단:

- exclusion 조항은 coverage trigger보다 우선한다.
- 한 조항에 한도, 공제, 증빙 요건이 같이 있으면 복수 rule type을 허용한다.
- 원문에 근거가 없는 rule type은 생성하지 않는다.
- 새 node type 승격은 rule별 독립 편집/승인 workflow가 필요해질 때 검토한다.

## 3. 개선 내용

### 3.1 Clause type 우선순위 정리

`_classify_clause_type()`에서 면책/보상제외를 최우선으로 분류하고, 그 다음 한도, 공제, 증빙, 정의, 검토, 보장 순으로 분류하도록 정리했다.

의도:

- 면책 조항이 `보험금`, `지급` 같은 단어 때문에 coverage로 보이는 것을 줄인다.
- 도수치료처럼 한도와 공제, 증빙이 함께 등장하는 조항도 대표 clause type은 일관되게 선택한다.

### 3.2 Rule types 다중 분류

`_classify_rule_types()`를 추가했다.

예시:

- `보상하지 않는다` -> `ExclusionRule`
- `연간 50회`, `회당` -> `LimitRule`
- `공제금액`, `자기부담` -> `DeductibleRule`
- `세부내역서`, `진단서`, `제출` -> `EvidenceGateRule`
- `다만`, `한하여`, `우선` -> `PrecedenceRule`

### 3.3 Rule summary 생성

`_build_rule_summary()`를 추가해 rule type, polarity, 짧은 원문 excerpt를 함께 저장한다.

이 필드는 향후 UI, 평가, audit report에서 조항의 실무적 성격을 빠르게 표시하는 데 사용한다.

## 4. 검증 결과

실행 명령:

```bash
python -m py_compile src/graph/extractors.py
python -m pytest tests/test_graph_policy_clause_extractor.py -q
```

결과:

```text
2 passed in 0.54s
```

검증한 사항:

- 면책/증빙 조항에 `ExclusionRule`, `EvidenceGateRule`이 들어간다.
- 한도/공제/증빙 조항에 `LimitRule`, `DeductibleRule`, `EvidenceGateRule`이 함께 들어간다.
- 지급사유 조항은 `CoverageTriggerRule`로 분류된다.

## 5. 남은 작업

다음 단계는 Stage 3 `Evidence Completeness and Human Task Routing`이다.

확인할 내용:

- `required_evidence`와 실제 입력/첨부 증빙 태그의 차이를 구조화한다.
- 사람 심사 필요 조건을 보험금 계산 결과에 명확히 전달한다.
- 자동 계산 가능, 예상 계산, 자동 계산 보류를 구분한다.
