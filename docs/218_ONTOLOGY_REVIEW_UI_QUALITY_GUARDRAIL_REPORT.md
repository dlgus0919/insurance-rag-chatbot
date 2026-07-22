# 218. Ontology Review UI Quality Guardrail Report

작성일: 2026-06-11

## Summary

실무자 승인 UI와 온톨로지 적용 품질 검증을 함께 보강했다.

이번 변경은 다음 문제를 해결한다.

- 실무자가 후보를 볼 때 승인/보류/거절 판단 기준이 부족했다.
- 후보 상세 창의 긴 텍스트가 줄바꿈 없이 표시되어 Zenity 창이 과도하게 커질 수 있었다.
- `candidate_aliases` 중 문장 조각과 다중 concept 소유 표현이 active manifest에 들어갈 수 있었다.
- DGX Zenity UI 외에 Mac 로컬에서 후보를 UI로 검토할 방법이 없었다.

## Implemented

### 1. 실무자 판단 기준 표시

수정:

- `src/ontology/candidate_display.py`
- `scripts/ontology_review.py`

후보 상세 표시에는 다음 정보가 추가된다.

- 후보 ID
- 대상 concept ID
- 승인/보류/거절 판단 기준
- 원문 근거와 후보 개념 연결이 어긋났을 때의 판단 가이드
- 품질 경고
- 후보 alias 목록

판단 기준 요약:

- 승인: 후보 표현이 후보 개념과 같은 보험 업무 개념을 가리키고, 원문 근거의 사용 맥락도 맞으며, 다른 개념으로 해석될 가능성이 낮을 때
- 보류: 표현은 유용하지만 근거 연결, concept 소유권, 문장 조각 여부, 추가 근거 확인이 필요할 때
- 거절: 표현이 너무 넓거나, 지급/면책/감액/계산 판단으로 이어지거나, 후보 개념과 연결이 잘못됐거나, 문장 조각일 때

### 2. 품질 경고 생성

추가:

- `src/ontology/candidate_quality.py`

감지 항목:

- `sentence_fragment_alias`: 후보 alias가 개념명이 아니라 원문 문장 조각에 가까운 경우
- `candidate_alias_multi_owner`: 같은 후보 alias가 여러 concept 후보에 동시에 연결된 경우

실무자 UI에서는 이 정보를 품질 경고로 보여준다.

예:

```text
[주의] '질병의 치료 목적에 해당되어' 표현은 개념명보다 원문 문장 조각에 가깝습니다.
[주의] '질병의 치료 목적에 해당되어' 표현이 여러 후보 concept에 동시에 연결되어 있습니다.
```

### 3. 창 크기와 줄바꿈 조정

수정:

- `src/ontology/candidate_display.py`
- `scripts/ontology_review.py`
- `ops/bin/insurance-rag-ontology-review-gui`

변경:

- `format_candidate_for_practitioner(..., wrap_width=82)` 기본 줄바꿈 추가
- CLI `--show`에 `--wrap-width` 옵션 추가
- DGX Zenity GUI는 `--wrap-width 72`를 사용
- Zenity 후보 검토 창은 `width=760`, `height=560`으로 조정

### 4. Mac 로컬 브라우저 UI 추가

추가:

- `scripts/ontology_review_local_ui.py`

실행 예:

```bash
python scripts/ontology_review_local_ui.py
```

기본 URL:

```text
http://127.0.0.1:8765/?status=pending
```

특징:

- 외부 패키지 없이 Python 표준 라이브러리만 사용
- 로컬 브라우저에서 후보 목록/상세/품질 경고 확인
- pending 후보에 대해 승인/보류/거절 가능
- 기존 `OntologyReviewStore`를 사용하므로 `review_log.jsonl` 감사 로그 형식이 동일함
- 운영 반영은 별도 `scripts/ontology_review.py --apply --rebuild-graph` 명령으로 분리

### 5. 적용 단계 품질 차단

수정:

- `src/ontology/manifest_merge.py`
- `scripts/check_ontology_sync.py`

`candidate_aliases`가 다음 조건에 걸리면 active manifest 적용을 차단한다.

- 문장 조각형 alias
- 여러 concept에 동시에 소유된 candidate alias

### 6. 기존 적용분 보수 정리 옵션

수정:

- `src/ontology/candidate_quality.py`
- `scripts/ontology_review.py`

추가 옵션:

```bash
.venv/bin/python scripts/ontology_review.py --sanitize-candidate-aliases
```

동작:

- 문장 조각형 candidate alias 제거
- 다중 concept 소유 candidate alias 제거
- 제거 내역을 candidate properties의 `quality_repair`에 기록

정책은 보수적으로 잡았다. 소유권이 애매한 alias는 자동으로 특정 concept에 남기지 않고 모두 제거한다. 필요한 표현은 이후 새 후보로 단일 concept에 다시 승인해야 한다.

## DGX Runtime Repair

백업:

```text
/tmp/ontology-quality-repair-20260611-132059
```

실행:

```bash
.venv/bin/python scripts/ontology_review.py --sanitize-candidate-aliases
.venv/bin/python scripts/ontology_review.py --apply --rebuild-graph
.venv/bin/python scripts/check_ontology_sync.py --manifest data/ontology/concepts.active.json
```

결과:

```text
changed_count=19
[OK] Ontology sync check passed
concepts=49 aliases=109 candidate_aliases=34 retrieval_rules=20
```

기존 active manifest는 `candidate_aliases=58`였고, 정리 후 `candidate_aliases=34`가 되었다.

중복 candidate alias 재검사:

```text
duplicate_candidate_alias_terms=0
```

GraphDB rebuild 결과:

```text
graph_nodes=545223
graph_edges=46241
graph_aliases=528204
graph_evidence=27015
```

앱 상태:

```text
api_health=ok
api_models=ok
graph_db=ok
curl /api/health: {"status":"ok"}
```

## Verification

로컬:

```bash
python -m py_compile \
  src/ontology/candidate_quality.py \
  src/ontology/candidate_display.py \
  src/ontology/manifest_merge.py \
  scripts/check_ontology_sync.py \
  scripts/ontology_review.py \
  scripts/ontology_review_local_ui.py

python -m pytest \
  tests/test_ontology_candidate_quality.py \
  tests/test_extract_ontology_candidates_cli.py \
  tests/test_ontology_policy.py \
  tests/test_ontology_candidate_extractor.py \
  tests/test_ontology_candidate_display.py \
  tests/test_ontology_candidate_reviewer.py \
  tests/test_ontology_review_store.py \
  tests/test_ontology_manifest_merge.py \
  tests/test_ontology_registry.py \
  -q
```

결과:

```text
37 passed
```

DGX:

```bash
.venv/bin/python -m pytest \
  tests/test_ontology_candidate_quality.py \
  tests/test_extract_ontology_candidates_cli.py \
  tests/test_ontology_policy.py \
  tests/test_ontology_candidate_extractor.py \
  tests/test_ontology_candidate_display.py \
  tests/test_ontology_candidate_reviewer.py \
  tests/test_ontology_review_store.py \
  tests/test_ontology_manifest_merge.py \
  tests/test_ontology_registry.py \
  -q
```

결과:

```text
37 passed
```

Mac 로컬 UI smoke:

```bash
python scripts/ontology_review_local_ui.py --no-open --port 8766
curl -s -o /tmp/ontology_local_ui.html -w '%{http_code}\n' 'http://127.0.0.1:8766/?status=pending'
```

결과:

```text
200
```

## Remaining Work

- base manifest의 기존 alias 충돌은 아직 warning이다.
- 제거된 alias 중 실제로 유용한 표현은 새 후보로 단일 concept에 다시 승인해야 한다.
- 실무자 UI에서 보류 사유를 structured reason으로 선택하게 하는 기능은 후속 개선 대상이다.
