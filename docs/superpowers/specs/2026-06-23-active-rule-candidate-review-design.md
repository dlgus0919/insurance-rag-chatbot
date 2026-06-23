# Active Rule Candidate Review Design

## 목적

DGX 실행기에 `액티브 룰 신규 후보` 선택지를 추가해, 신한EZ 약관 문서에서 자동 추출된 보험금 계산 rule 후보를 실무자가 수정, 승인, 거절할 수 있게 한다.

이 기능은 000번 규칙을 따른다.

- 계산 지식은 코드 상수가 아니라 rule candidate, approved manifest, source evidence로 관리한다.
- 새 계산 rule은 반드시 후보 상태에서 시작한다.
- 지급, 공제, 한도, 세대별 계산값은 자동 승인하지 않는다.
- 승인된 후보만 active rule manifest에 병합한다.
- 병합 전 전체 manifest를 `ClaimRuleRegistry`로 검증한다.

## 범위

1차 범위는 신한EZ 약관 문서 전체다.

후보 폭증, source 식별 실패, 또는 문서 범위 판정이 불안정하면 fallback으로 기존 active rule의 `source_chunk_id`, `additional_source_refs`, 주변 약관 chunk/table row만 재스캔한다.

포함:

- 약관 chunk와 table/row evidence에서 계산 rule 후보 추출
- 후보 목록 표시
- 후보 상세 표시
- 후보 값 수정
- 승인, 거절
- 승인 후보 active manifest 병합
- 승인 rule과 source evidence, ontology concept, GraphDB evidence node 연결
- 실행기 창 크기 최적화

제외:

- LLM이 계산 rule을 확정 생성하는 기능
- source evidence 없는 후보 자동 승인
- GraphDB 또는 ontology가 계산 rule 값을 직접 소유하는 구조
- 승인 없이 GraphDB 또는 ontology를 자동 rebuild/apply하는 구조
- 보험금 계산 결과 자체의 UI 개편

## 실행기 UX

메인 실행기 선택지 순서는 다음과 같다.

1. 온톨로지 승인 검토
2. 액티브 룰 신규 후보
3. 액티브 룰 검토
4. 모델 기동
5. 현재 실행 중 모델 유지

`모델 기동`을 선택하면 별도 모델 선택 창을 연다.

두 번째 창에는 현재 DGX에서 사용할 수 있는 모델만 표시한다.

- 이미 실행 중인 모델은 “현재 실행 중”으로 표시한다.
- 로컬 모델 파일이 부족하거나 기동 불가로 판정된 모델은 표시하지 않는다.
- TensorRT-LLM `gpt-oss-120b`처럼 편입 불가로 결론 난 모델은 기본 목록에서 제외한다.
- 모델 기동 목록은 실행기 내부에 길게 펼치지 않고, 별도 list 창에서 선택한다.

`액티브 룰 신규 후보`를 선택하면 rule candidate GUI가 열린다.

GUI는 온톨로지 승인 검토와 같은 흐름을 따른다.

- 후보 목록
- 후보 상세
- 수정
- 승인
- 거절
- 승인 후보 반영

## 후보 데이터

후보 저장소:

```text
data/rules/review/candidates.jsonl
data/rules/review/review_log.jsonl
data/rules/rule_links.active.json
```

후보 필드:

- `candidate_id`
- `status`: `pending`, `approved`, `rejected`, `applied`
- `rule_type`: `deductible`, `prescription`, `special`
- `proposed_rule`: active manifest에 병합 가능한 rule row 형태
- `proposed_links`: source evidence, ontology concept, GraphDB 연결 후보
- `source_refs`: 문서명, 페이지, 조항, chunk_id, row_id
- `evidence_text`: 원문 근거 발췌
- `extraction_reason`: 후보로 추출한 이유
- `risk_flags`: 중복, source 부족, 숫자 충돌, schema 미충족 등
- `created_at`
- `reviewed_at`
- `reviewer`
- `review_note`

후보는 active manifest와 같은 row 형태를 내부에 포함한다. 별도 변환 계층을 크게 만들지 않고, 검증은 기존 `ClaimRuleRegistry`를 재사용한다.

`proposed_links`는 계산값을 소유하지 않는다. 계산값은 `proposed_rule`과 active rule manifest에만 둔다.

## 후보 추출

추출기는 `scripts/extract_claim_rule_candidates.py`로 둔다.

입력:

- 보정본 OCR 포함 약관 chunk
- clause detail row/table evidence
- 기존 active rule source refs

기본 추출 조건:

- 문맥에 계산 rule 신호가 있어야 한다.
- 예: 공제, 본인부담, 한도, 연간, 통원, 입원, 처방, 급여, 비급여, 세대
- 숫자 값과 적용 범위가 같은 근거 안에서 확인되어야 한다.
- 세대, 급여/비급여, 입원/통원/처방, 한도/공제율/공제금 중 일부가 구조화되어야 한다.

후보화하지 않는 경우:

- 숫자만 있고 적용 범위가 없는 경우
- 문서 근거 없이 기존 코드값만 있는 경우
- LLM 출력만 있는 경우
- 면책/지급 판단 문장인데 계산 rule schema로 구조화되지 않는 경우

## Rule, Ontology, GraphDB 연결

승인된 rule은 source evidence와 ontology/GraphDB 연결을 반드시 가진다.

역할 분리:

- `ClaimRuleRegistry`: 계산값의 유일한 실행 원천
- active rule manifest: 승인된 계산 rule 저장소
- rule link manifest: rule과 source/ontology/GraphDB 연결 저장소
- ontology: rule이 속한 보험 업무 개념
- GraphDB: rule, source chunk/table row, ontology concept 사이의 탐색 edge

금지:

- ontology concept metadata에 공제율, 한도, 지급률 같은 계산값을 저장하지 않는다.
- GraphDB node 값을 계산 원천으로 사용하지 않는다.
- GraphDB 또는 ontology 연결만 있고 active rule manifest에 없는 rule은 계산에 쓰지 않는다.

rule link 예시:

```json
{
  "rule_id": "deductible.5th.benefit.outpatient",
  "source_refs": ["약관_ch_002331"],
  "ontology_refs": ["cov.indemnity_medical", "cond.outpatient"],
  "graph_refs": ["source_chunk:약관_ch_002331"],
  "link_status": "active"
}
```

후보 승인 시 `proposed_rule`과 `proposed_links`를 함께 검토한다. `--apply`는 active rule manifest와 rule link manifest를 함께 갱신한다.

GraphDB 반영은 명시적 rebuild 단계에서 수행한다. rebuild는 rule link manifest를 읽어 다음 edge를 만든다.

- rule -> source chunk/table row
- rule -> ontology concept
- ontology concept -> source evidence

## 후보 검토와 반영

검토 CLI는 `scripts/claim_rule_candidate_review.py`로 둔다.

최소 명령:

- `--pending-count`
- `--summary`
- `--list-json`
- `--show <candidate_id>`
- `--decide <candidate_id> --decision approve|reject --reason ...`
- `--edit <candidate_id> --field ... --value ... --note ...`
- `--apply`
- `--dry-run`

`--apply`는 approved 후보만 active manifest에 병합한다.

병합 규칙:

- 같은 `rule_id`가 이미 active에 있으면 기본은 충돌로 막는다.
- 기존 active rule을 갱신하려면 `액티브 룰 검토` 기능을 사용한다.
- 신규 후보 병합 후 전체 manifest를 `ClaimRuleRegistry.from_file()`로 검증한다.
- rule link manifest도 함께 검증한다.
- approved 후보에 `proposed_links`가 없으면 apply를 막는다.
- 검증 실패 시 active manifest를 쓰지 않는다.
- 성공 시 backup과 audit log를 남긴다.

## 창 크기 최적화

대상:

- 메인 실행기
- 온톨로지 승인 검토 GUI
- 액티브 룰 검토 GUI
- 신규 액티브 룰 후보 GUI

규칙:

- list 창은 row 수 기반으로 높이를 계산한다.
- detail 창은 텍스트 줄 수 기반으로 높이를 계산한다.
- 최소 높이와 최대 높이를 둔다.
- 과도한 창 폭 대신 줄바꿈 가능한 상세 텍스트를 사용한다.
- live `/srv/ai-ops/bin` 파일과 repo `ops/bin` 파일을 모두 확인한다.

## 오류 처리

- 후보 0건: 실패가 아니라 “추출 후보 없음”으로 표시한다.
- source evidence 누락: 승인 불가 상태로 표시한다.
- schema 검증 실패: 후보 상세에 오류를 표시하고 active 병합을 막는다.
- 같은 `rule_id` 충돌: 신규 후보 적용을 막고 active rule 수정 흐름으로 안내한다.
- dry-run: active manifest, audit log, backup을 쓰지 않는다.

## 테스트

최소 테스트:

- 후보 JSONL load/list/show
- 후보 edit 후 schema 검증
- 승인 후보 apply 시 active manifest 병합
- 승인 후보 apply 시 rule link manifest 병합
- 중복 `rule_id` 적용 차단
- source evidence 없는 후보 승인/적용 차단
- `proposed_links` 없는 후보 적용 차단
- 실행기 `--choices`에 신규 선택지 표시
- `모델 기동` 선택 시 별도 모델 목록 표시
- wrapper `bash -n`
- GUI `--dry-run`

실샘플 검증:

- 신한EZ 약관 전체 스캔 dry-run
- 후보 수, risk flag 분포, 대표 후보 5건 확인
- active manifest가 dry-run에서 변경되지 않았는지 확인
- rule link manifest가 dry-run에서 변경되지 않았는지 확인

## 실무 흐름 평가

이 설계는 실무자가 계산 rule 후보를 직접 코드 수정 없이 검토할 수 있게 한다.

자동 추출은 후보 생성까지만 담당한다. 후보 값은 source evidence와 함께 표시되고, 실무자 승인 전에는 운영 계산에 반영되지 않는다.

기존 active rule 값 수정은 `액티브 룰 검토`로 분리한다. 신규 rule 추가는 `액티브 룰 신규 후보`로 분리해, 새 지식 추가와 기존 지식 수정을 혼동하지 않게 한다.

GraphDB와 ontology는 rule 값을 확정하는 계층이 아니다. 실무자는 rule 값과 근거 연결을 함께 승인하고, 계산기는 active rule manifest만 실행 원천으로 사용한다.

## 확장 지점

추후 확장 가능한 항목:

- 약관 신규 편입 시 자동 후보 생성 batch 연결
- 후보 추출 LLM enrichment 추가
- rule link manifest 기반 GraphDB rebuild 검증 리포트
- ontology concept 누락 시 별도 ontology candidate 자동 생성

단, LLM enrichment를 추가하더라도 LLM 출력은 후보 설명과 risk 보조 정보로만 사용한다. 계산값 확정과 active 반영은 source evidence와 실무자 승인에 따른다.
