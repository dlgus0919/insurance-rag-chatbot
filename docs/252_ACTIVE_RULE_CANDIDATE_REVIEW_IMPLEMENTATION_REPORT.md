# Active Rule Candidate Review Implementation Report

## 요약

DGX 메인 저장소에 액티브 룰 신규 후보 생성/검토/적용 흐름을 구현했다.

- 문서 기반 deterministic 추출기로 계산 룰 후보를 생성한다.
- 실무자는 DGX 실행기에서 `액티브 룰 신규 후보`를 열어 후보를 수정, 승인, 거절할 수 있다.
- 승인 후보만 active rule manifest와 rule link manifest에 병합된다.
- GraphDB는 승인 rule의 source/ontology 연결만 저장하며, 계산값 실행 원천은 계속 active rule manifest다.

## 구현 범위

### 후보 생성

`scripts/extract_claim_rule_candidates.py`는 약관 chunk에서 공제율, 한도, 본인부담, 세대, 통원/입원/처방 등 rule 신호가 같이 나타나는 문맥만 후보화한다.

생성 후보는 `data/rules/review/candidates.jsonl`에 저장된다. 이 파일은 실무 검토용 runtime 데이터이며 Git 커밋 대상이 아니다.

### 후보 검토

`scripts/claim_rule_candidate_review.py`는 다음 기능을 제공한다.

- `--pending-count`
- `--summary`
- `--list-json`
- `--show`
- `--decide`
- `--edit`
- `--apply`
- `--gui`
- `--dry-run`

GUI에서는 후보 목록, 상세 근거, 제안 값, source/ontology 연결을 확인하고 승인/수정/거절/적용을 수행할 수 있다.

### 액티브 룰 수정

`scripts/claim_rule_review.py`는 이미 승인된 active rule의 값만 수정한다. 수정 시 reviewer와 사유가 필요하며, 저장 전 `ClaimRuleRegistry` 검증을 수행한다.

신규 rule 추가와 기존 rule 수정 흐름을 분리해 실무자가 작업 목적을 혼동하지 않도록 했다.

### 실행기 UX

`ops/bin/insurance-rag-desktop-launcher`의 첫 선택지는 다음 순서로 정리했다.

1. 온톨로지 승인 검토
2. 액티브 룰 신규 후보
3. 액티브 룰 검토
4. 모델 기동 선택
5. 현재 실행 중 모델 유지

`모델 기동 선택`을 누른 경우에만 별도 모델 목록을 띄운다. 첫 실행기 창에 모델 후보가 길게 펼쳐지지 않도록 했다.

온톨로지 후보가 있더라도 실행기 시작 시 온톨로지 검토 GUI를 자동으로 선행 실행하지 않는다. 실무자가 첫 선택창에서 명시적으로 `온톨로지 승인 검토`를 선택한 경우에만 해당 GUI가 열린다.

### GraphDB 연결

`scripts/build_graph_index.py`에 `--rule-links` 옵션을 추가했다.

GraphDB rebuild 시 `data/rules/rule_links.active.json`이 있으면 active link만 읽어 다음 연결을 만든다.

- rule -> source chunk
- rule -> ontology concept
- ontology concept -> source chunk

GraphDB에는 공제율, 한도, 지급률 같은 계산값을 실행 원천으로 저장하지 않는다. 계산에는 계속 `data/rules/claim_deductible_rules.active.json`만 사용한다.

## 000번 규칙 점검

- 계산 지식은 코드 상수가 아니라 후보 JSONL, active manifest, source evidence를 통해 관리한다.
- 신규 계산 rule은 후보 상태에서 시작하고, 실무자 승인 전에는 active 계산에 반영되지 않는다.
- 승인 후보 적용 전 전체 active manifest를 `ClaimRuleRegistry`로 검증한다.
- ontology/GraphDB는 계산값 소유 계층이 아니라 traceability 계층으로만 사용한다.
- LLM 출력이나 외부 API 없이 deterministic 추출과 실무자 승인을 우선한다.

## DGX 검증 결과

실행 명령:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_claim_rule_candidates.py \
  tests/test_extract_claim_rule_candidates.py \
  tests/test_claim_rule_candidate_review.py \
  tests/test_claim_rule_review.py \
  tests/test_claim_rule_registry.py \
  tests/test_deductible_rules.py \
  tests/test_desktop_launcher_choices.py \
  tests/test_graph_rule_links.py \
  tests/test_graph_policy_rule_nodes.py -q
```

결과:

```text
50 passed in 0.70s
```

추가 확인:

```bash
bash -n ops/bin/insurance-rag-desktop-launcher
bash -n ops/bin/insurance-rag-rule-candidate-review-gui
bash -n ops/bin/insurance-rag-rule-review-gui
bash -n ops/bin/insurance-rag-ontology-review-gui
```

결과: syntax error 없음.

live DGX 실행기 동기화:

```bash
install -m 0755 ops/bin/insurance-rag-desktop-launcher /srv/ai-ops/bin/insurance-rag-desktop-launcher
install -m 0755 ops/bin/insurance-rag-rule-candidate-review-gui /srv/ai-ops/bin/insurance-rag-rule-candidate-review-gui
/srv/ai-ops/bin/insurance-rag-desktop-launcher --choices
```

결과:

```text
ontology|review|0
rules|candidate|24
rules|review|active
model|select|available
current|sglang|gpt-oss-20b
```

실제 DGX 후보 생성:

```bash
.venv/bin/python scripts/extract_claim_rule_candidates.py --limit 100 --replace-existing
.venv/bin/python scripts/claim_rule_candidate_review.py --summary
```

결과:

```json
{
  "pending": 24,
  "approved": 0,
  "rejected": 0,
  "applied": 0,
  "total": 24
}
```

## 남은 운영 작업

실무자가 DGX 실행기에서 `액티브 룰 신규 후보`를 열어 후보를 검토한다.

승인 후 GUI 또는 CLI의 apply를 수행하면 active rule manifest와 rule link manifest가 갱신된다.

그 다음 별도 명시 작업으로 GraphDB rebuild를 실행하면 승인 rule과 source/ontology 연결이 GraphDB에 반영된다.

## 남은 위험

- 현재 후보 추출기는 보수적인 정규식 기반이다. 후보 품질은 실무자 검토와 risk flag 확대를 통해 점진 개선해야 한다.
- rule link manifest가 없는 기존 active rule은 GraphDB 연결이 생기지 않는다. 기존 active rule에 대한 source/ontology link backfill은 후속 작업으로 분리하는 것이 안전하다.
- GUI는 Zenity 기반이므로 DGX desktop 세션에서만 직접 사용할 수 있다.
