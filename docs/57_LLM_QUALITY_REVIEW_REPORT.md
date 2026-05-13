# 57 LLM Quality Review Report

작성일: 2026-05-13  
대상 명세: `docs/57_CODEX_SPEC_LLM_QUALITY_REVIEW.md`

## 1. Stale 파일 정리 결과

### 1-1. 삭제 전 파일별 first-line preview

| 파일 | first line preview |
|---|---|
| `data/extracted/실무가이드/text/p064_b01.txt` | `수술분류표` |
| `data/extracted/실무가이드/text/p071_b01.txt` | `족근관 Synd) (Tarsal Tunnel 발목내측부의 족근관의 내용물 증가로 후경골신경이 눌려서 여러 증상을 나타내는 것을` |
| `data/extracted/실무가이드/text/p071_b02.txt` | `78 claim실무 종합가이드` |
| `data/extracted/실무가이드/text/p074_b02.txt` | `근본수술(654)` |
| `data/extracted/실무가이드/text/p081_b01.txt` | `19.폐장() 이식수술[수용자(품입후)에 한함]` |
| `data/extracted/실무가이드/text/p081_b02.txt` | `88 claim실무 종합가이드` |
| `data/extracted/실무가이드/text/p151_b01.txt` | `77. 관혈적 안와내(←) 이물제거수술(베다)` |
| `data/extracted/실무가이드/text/p151_b02.txt` | `claim실무 종합가이드` |
| `data/extracted/실무가이드/text/p255_b01.txt` | `9) 기형을 "뼈에 때" 라 또는 남긴 함은 상완골 남아 요골과 척골에 변형이 정상에 된 각 비해 부정유합 변형` |
| `data/extracted/실무가이드/text/p255_b03.txt` | `Claim실무 종합가이드` |
| `data/extracted/실무가이드/text/p279_b01.txt` | `III. 표준약관 따른 장해관련 변경에 변경내용` |
| `data/extracted/실무가이드/text/p279_b02.txt` | `286 claim실무 종합가이도` |

### 1-2. verify 재실행 결과

실행:

```bash
python scripts/verify_p255_word_order.py
```

핵심 결과:

```text
Stale text files (not in manifest):
  (none)

Summary:
  Registered blocks checked: 5
  PASS: 1 | WARN: 4 | FAIL: 0
  Stale files: 0
  Overall: PASS
```

### 1-3. pytest 결과

실행:

```bash
pytest -q
```

결과:

```text
229 passed, 5 warnings in 4.79s
```

---

## 2. Approach A 검토 (Prompt 개선)

검토 파일:
- `src/llm/prompt.py`
- `src/rag/pipeline.py`
- `eval/ocr_qa.jsonl`

### 2-1. 현재 SYSTEM_PROMPT 분석 (강점/약점)

- 강점:
  - 코드/약관 보상판정 질의에 대한 규칙이 구체적이다.
  - 출처 형식 강제가 명확하다.
- 약점:
  - OCR 표 파이프 텍스트에서 특정 행/열 값을 추출하는 명시 규칙이 없다.
  - 수술종수(3개 컬럼), 장해 지급률(행-값 매핑) 같은 구조적 추출 패턴이 프롬프트에 없다.
  - 결과적으로 retrieval=OK인데 answer extraction 실패가 잦다.

### 2-2. 추가 위치 추천

- 최적 위치: `SYSTEM_PROMPT`의 `## 핵심 규칙` 아래에 `## OCR 표 추출 규칙` 섹션 추가.
- 이유:
  - 현 prompt 구조가 규칙 중심이므로 동일 계층에 넣는 것이 충돌이 적다.
  - 예시는 기존 `## 예시` 섹션 하단에 2~3개 추가하면 컨벤션 유지 가능.

### 2-3. 기존 코드/테스트 영향

- 코드 영향: `src/llm/prompt.py` 문자열 변경만으로 충분.
- 테스트 영향:
  - `tests/test_pipeline.py`는 `SYSTEM_PROMPT` 본문 문자열을 직접 assert하지 않는다.
  - `build_user_prompt`, `append_retrieved_source_citations` 테스트와 직접 충돌 가능성은 낮다.
  - `scripts/eval.py` 스모크 결과가 모델 응답 분포에 따라 달라질 수 있어 회귀 재측정은 필요.

### 2-4. 난이도/소요

- 난이도: 하
- 예상 소요: 0.5~1시간 (문구 튜닝 + eval 재실행 포함)

---

## 3. Approach B 검토 (Structured Row Injection)

검토 파일:
- `src/rag/pipeline.py`
- `src/llm/prompt.py`
- `src/parser/ocr_chunker.py`

### 3-1. 삽입 위치 판단 (`answer()` vs `build_user_prompt()`)

- 권장 위치: `src/rag/pipeline.py`의 `answer()`에서 `build_user_prompt()` 호출 직전.
- 이유:
  - row injection은 검색 결과(`chunks`)와 질의 타입(수술/장해) 판단이 모두 필요한 로직이다.
  - `build_user_prompt()`는 범용 포맷터 역할을 유지하는 편이 응집도가 높다.
  - `answer()`에서 `[구조화 데이터]` 블록을 prepend한 뒤 기존 `build_user_prompt()`를 그대로 재사용할 수 있다.

### 3-2. 장해 부위 추출 패턴 설계안

- 1차 regex:
  - `r"(.+?)\\s*(?:을|를)\\s*(?:잃었을 때|남은 경우)"`
  - `r"(.+?)\\s*장해\\s*(?:지급률|판정)"`
- 2차 키워드 사전:
  - `두 눈`, `한 눈`, `두 귀`, `한 귀`, `코`, `척추`, `한 팔`, `두 팔`, `한 손`, `두 다리`, `발목`, `손목`, `손가락`, `말하는 기능`, `씹어먹는 기능`
- 정규화:
  - 공백 정리, 괄호 제거, 조사 제거 후 부분 매칭.

### 3-3. table_json 없는 경우 fallback

- 처리 원칙:
  - top-k를 순회하며 `metadata["table_json"]`가 유효한 첫 청크를 사용.
  - 모두 없으면 injection을 생략하고 기존 prompt만 사용(no-op).
  - injection 실패는 예외를 내지 않고 로그/디버그 플래그로만 기록.

### 3-4. 복잡도/효과

- 난이도: 중
- 예상 소요: 1.5~3시간 (패턴/파서 + 테스트 + eval)
- A 대비 추가효과:
  - 있음. LLM에게 구조화된 정답 후보를 직접 주므로 수치 추출 실패를 크게 줄일 가능성이 높다.
  - 특히 `grade_accuracy`, `rate_accuracy` 개선에 직접적이다.

---

## 4. Approach C 검토 (별도 DataFrame 저장 + 직접 조회)

검토 파일:
- `src/parser/ocr_chunker.py`
- `scripts/ingest.py`
- `eval/ocr_qa.jsonl`

### 4-1. table 분리 저장 가능 여부/기준

- 가능 여부: 가능.
- 기준:
  - `doc_short == "실무가이드"` + `content_type == "table"` + `table_json != "{}"` 필수.
  - 수술종수표 식별: headers가 `["수술명", ..., "1-3종", "1-5종", "신1-5종"]` 패턴 포함.
  - 장해분류표 식별: headers에 `장해`/`지급률` 계열 컬럼 존재.

### 4-2. ingest.py 삽입 위치

- 권장 위치:
  - `build_chunks()` 완료 후 `all_chunks`가 메모리에 있는 시점에서 파생 인덱스 생성.
  - 저장 경로 예: `data/index/ocr_tables/` 하위 parquet/sqlite.
- 이유:
  - OCR chunk 파싱을 다시 돌리지 않아도 되고, 인제스트 파이프 한 번으로 동기화 가능.

### 4-3. 장해분류표 정규화 난이도

- 난이도: 중~상.
- 이유:
  - 장해문구가 multi-line/복합조건/번호 체계를 포함하며 단순 split으로 손실 가능.
  - "신체부위", "장해유형", "지급률"로 flatten하려면 규칙기반 전처리 추가가 필요.

### 4-4. A/B와의 조합 충돌

- 충돌 가능성:
  - A와는 거의 없음(프롬프트 계층).
  - B와는 중복 가능성 있음(둘 다 구조화 데이터 주입). 우선순위 규칙 필요:
    - C 조회 성공 시 C값 우선, 실패 시 B(table_json) fallback.

### 4-5. 과제 2(보험금 자동 계산) 연계 가치

- 매우 큼.
- 이유:
  - 지급률/종수 값이 정규화 테이블로 있으면 계산 로직에서 LLM 의존도를 줄이고 deterministic 계산 가능.
  - 향후 검증/감사 로그에도 유리.

---

## 5. 종합 권장안

### 5-1. 효용/비용 비교표

| 접근 | 기대 효과 | 구현 비용 | 리스크 | 권장도 |
|---|---:|---:|---:|---:|
| A Prompt 개선 | 중 | 하 | 모델 편차 | 높음 |
| B Row Injection | 높음 | 중 | 패턴 설계 미스 | 매우 높음 |
| C 별도 테이블 인덱스 | 매우 높음(중장기) | 중~상 | 정규화 복잡도 | 중장기 높음 |

### 5-2. 권장 구현 순서

1. **A 먼저**: 빠른 개선 + 기존 구조 영향 최소.
2. **B 다음**: 정확도 병목(grade/rate)을 직접 해결할 실효성 큼.
3. **C 마지막**: 과제 2 연계를 위한 인프라화 단계로 확장.

### 5-3. 주요 위험 요소

- A: 프롬프트 길이 증가로 일부 일반 질의 답변이 장황해질 수 있음.
- B: 잘못된 행 추출 시 오답을 오히려 확신 있게 출력할 위험.
- C: 장해분류표 정규화 규칙 불안정 시 유지보수 비용 급증.

---

## 결론

- Task 1은 `Stale files: 0`, `pytest 229 passed`로 완료.
- LLM 품질 개선은 **A → B → C** 순서가 비용 대비 효과가 가장 좋다.
- 단기 KPI(`grade_accuracy`, `rate_accuracy`) 관점에서는 B가 핵심 레버리지다.
