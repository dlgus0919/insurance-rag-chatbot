# 230. Semi-Adaptive-K 보류 메모 및 Clause Detail Lookup 개선 방향

## 목적

- `semi-adaptive-k`는 다음 실험 후보로 보류한다.
- `clause_detail_lookup` 실패는 자동 Top-K/temperature 문제가 아니라 조항·표 세부 추출 문제로 분리한다.
- 개선은 "하드코딩 지식 로직 금지" 원칙을 지키는 방식으로 설계한다.

## Semi-Adaptive-K 보류 메모

기존 `threshold_auto`는 reranker 점수 급락을 보고 최종 Top-K를 줄일 수 있었다. 전체 평가에서는 일부 케이스에서 필요한 근거가 잘려 `rule_auto`보다 낮은 결과가 나왔다.

`semi-adaptive-k`는 이 실패를 줄이기 위한 다음 실험 후보이다.

- profile별 기본 Top-K를 하한으로 둔다.
- 검색은 profile별 최대 Top-K까지 넓게 수행한다.
- reranker 점수 급락이 기본 Top-K보다 늦게 나타나는 경우에만 최종 Top-K를 늘린다.
- 최종 Top-K는 절대 profile별 기본값보다 작아지지 않는다.

예상 형태:

```text
retrieval_top_k = profile.max_k
final_k = max(profile.base_k, late_drop_cutoff)
final_k <= profile.max_k
```

현재 보류 이유:

- `rule_auto`가 전체 평가에서 최선이었다.
- `threshold_auto`가 일부 문항에서 필요한 근거를 줄인 전례가 있다.
- semi-adaptive-k는 근거를 늘리는 전략이므로 기존 실패 위험은 줄지만, 불필요한 청크 유입으로 답변 초점이 흐려질 수 있다.
- 따라서 구현 전 `observe` 또는 평가 전용 전략으로 먼저 검증해야 한다.

## Clause Detail Lookup 실패 요약

전체 평가에서 `clause_detail_lookup` 2건은 모든 전략에서 실패했다.

- `policy_xlsx_018`
  - 질문: 급여(상해·질병) 입원치료의 자기부담금(공제) 비율
  - 기대: 본인부담금의 80% 보상, 자기부담률 20%, 제3조
- `policy_xlsx_019`
  - 질문: 급여 통원치료의 자기부담금 산정 방식
  - 기대: 통원 1회당, 병원급별 공제금액, 2만원, 20%, 제3조 `<표1>`

진단:

- 관련 후보 청크가 전혀 없었던 것은 아니다.
- `약관` p.31-36 등 제3조 주변 청크가 검색 결과에 포함됐다.
- 현재 deterministic clause detail 답변기는 조항/표의 행 단위 값을 읽지 못하고, "자기부담금이 있다"는 일반 설명으로 요약했다.
- 긴 페이지 범위, 표형 OCR 텍스트, 목차성/광범위 청크가 섞이면서 필요한 숫자와 조건이 최종 답변에 안정적으로 반영되지 않았다.

## 하드코딩 금지 원칙

금지해야 할 방식:

- 질문 문자열에 `입원`, `통원`, `자기부담금`이 있으면 코드에서 직접 `80%`, `20%`, `2만원`을 반환하는 방식
- 평가 케이스 ID 또는 특정 질문 문장에 맞춘 분기
- 특정 상품 지식 값을 Python 상수로 박는 방식
- 약관 개정 시 코드 수정이 필요한 방식

허용되는 방식:

- 원문 약관, OCR 보정본, table metadata, section metadata에서 값을 읽어오는 방식
- 조항 번호, 표 제목, 행/열, 문서/페이지를 근거로 구조화 인덱스를 만드는 방식
- query-to-row matching 규칙은 일반화하되, 값은 데이터에서 추출하는 방식
- 추출된 행과 숫자를 출처와 함께 답변하는 방식
- alias/용어 정규화는 온톨로지 승인 workflow를 통해 관리하는 방식

## 개선 제안

### 1. 조항·표 구조화 인덱스 보강

현재 chunk 단위 검색만으로는 표 안의 행/열 관계가 약하다. `clause_detail_lookup`용 보조 인덱스를 만든다.

구조 예시:

```json
{
  "doc_short": "약관",
  "section_id": "article_3",
  "section_title": "제3조(보장종목별 보상내용)",
  "table_id": "article_3_table_1",
  "table_title": "<표1>",
  "row_text": "...",
  "normalized_terms": ["급여", "통원", "자기부담금"],
  "numbers": ["1회", "20%", "2만원"],
  "page_start": 31,
  "page_end": 36,
  "chunk_id": "..."
}
```

중요한 점은 `numbers`가 코드에 쓰인 지식값이 아니라 원문에서 추출된 값이어야 한다는 것이다.

### 2. Query-to-Row 매칭

질문에서 다음 요소를 일반적으로 추출한다.

- 급여/비급여
- 입원/통원/처방조제
- 상해/질병
- 자기부담금/공제금액/보상비율
- 조항 번호 또는 표 번호

이 요소를 구조화 row의 `normalized_terms`, `section_title`, `table_title`, `row_text`와 매칭한다. 매칭 점수는 일반 규칙으로 계산하고, 특정 정답값은 코드에 넣지 않는다.

### 3. Evidence-First 답변 생성

`clause_detail_lookup`에서는 LLM 자유 생성을 먼저 쓰지 말고, 선택된 row evidence를 먼저 구성한다.

권장 출력 구조:

```text
제공된 약관 근거 기준으로 답변드립니다.

- 기준 조항: 제3조(보장종목별 보상내용) <표1>
- 적용 구분: 급여 / 통원
- 자기부담금 산정: 원문 row에서 추출한 내용
- 확인된 수치: 원문에서 추출한 숫자 목록

[출처: 약관 p.xx-yy]
```

LLM은 이 구조화 evidence를 자연어로 다듬는 역할만 수행한다. 값 자체는 구조화 evidence에서 온다.

### 4. Numeric Coverage 검증

답변 생성 후 다음을 검증한다.

- 선택된 evidence row의 숫자가 답변에 포함됐는가
- 질문의 핵심 구분어가 답변에 포함됐는가
- 출처 조항/표가 포함됐는가

검증 실패 시:

- 바로 일반 답변을 내지 않는다.
- 더 넓은 row 후보를 재검색하거나, "근거는 찾았으나 수치 추출이 불안정하다"는 경고를 붙인다.

### 5. 평가 추가

현재 실패한 두 케이스를 최소 회귀 테스트로 고정한다.

- `policy_xlsx_018`: `80%`, `20%`, `입원`, `제3조`
- `policy_xlsx_019`: `1회`, `20%`, `2만원`, `통원`, `제3조`, `<표1>`

이 테스트도 정답값을 코드에 넣는 것이 아니라, 평가 fixture에 기대값으로 두고 시스템이 원문 데이터에서 값을 추출하는지 확인하는 방식이다.

## 권장 구현 순서

1. `clause_detail_lookup` 실패 케이스의 검색 후보와 원문 row를 재현한다.
2. 약관 chunk metadata에 table/section 정보가 충분한지 점검한다.
3. 부족하면 ingestion 또는 post-processing 단계에서 조항·표 row manifest를 생성한다.
4. `clause_detail_lookup` 경로에서 row manifest를 우선 조회한다.
5. row evidence 기반 deterministic answer builder를 추가한다.
6. 숫자/조항 coverage 검증을 추가한다.
7. 두 실패 케이스와 기존 전체 평가셋으로 회귀 검증한다.

## 정책 판단

`clause_detail_lookup` 개선의 핵심은 Top-K를 더 늘리는 것이 아니다. Top-K를 늘리는 것은 후보 누락 완화에는 도움이 될 수 있지만, 표 안의 행/열 값을 읽는 문제를 해결하지 못한다.

따라서 다음 작업은 `semi-adaptive-k`가 아니라 `clause_detail_lookup` 전용 구조화 evidence layer를 만드는 것이 우선이다.

