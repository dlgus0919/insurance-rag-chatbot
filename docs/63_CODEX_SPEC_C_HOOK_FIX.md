# Codex Spec #63 — C Hook 정확도 개선 (Interrupt Spec)

> **작성일:** 2026-05-13
> **작성자:** Claude (검토자)
> **구현 담당:** Codex
> **성격:** 버그 수정 + 로직 보강
> **우선순위:** 🔴 높음 — 명세 #61 작업을 일시 중단하고 본 명세를 먼저 완료할 것

---

## 0. 배경

`eval_ocr_abc_20260513_131447.log` 분석 결과, A+B+C 파이프라인에서 세 가지 문제가 확인됐다.

| 지표 | A+B | A+B+C | 목표 |
|---|---|---|---|
| grade_accuracy | 0.294 | 0.265 | ≥ 0.60 |
| rate_accuracy | 0.429 | 0.429 | ≥ 0.70 |
| keyword_coverage | 0.545 | 0.485 | ≥ 0.70 |

rate_accuracy가 A+B와 동일하다는 것은 C의 장해 조회가 전혀 작동하지 않음을 의미한다. grade에서는 [12]번 항목이 C 때문에 오히려 회귀했다.

---

## 1. Task 1 — 구(舊) 수술분류표 질의에서 C 주입 차단

### 1-1. 문제

`src/rag/pipeline.py` 21번째 줄 `_SURGERY_QUERY_PATTERN`에 "수술종류"가 포함되어 있어, `ocr_012` ("직시하심장내수술의 수술종류 분류(종)는?") 같은 **구 수술분류표 질의**도 C가 활성화된다.

`surgery_grades.parquet`은 신(新) 수술종수표(1-3종/1-5종/신1-5종 컬럼) 데이터만 보유한다. 구 수술분류표(단일 '수술종류 분류(종)' 컬럼)는 포함되지 않는다. 따라서 구 형식 질의에 C가 활성화되면 잘못된 종수 데이터를 주입해 grade가 하락한다.

**[12] 실제 회귀:**
- 질의: "직시하심장내수술의 수술종류 분류(종)는?" (expected: 3종, expected_pages=[7])
- A+B 결과: grade=1/1 (정답)
- A+B+C 결과: grade=0/1 (C 잘못된 주입으로 오답)

### 1-2. 수정 대상

`src/rag/pipeline.py` — `_build_structured_context()` 함수 내 `surgery_name` 결정 직후

### 1-3. 수정 내용

`_build_structured_context()` 함수에서 `surgery_name`을 추출한 뒤, 구 수술분류표 질의임이 확인되면 C 주입을 스킵한다.

```python
# 기존 코드 (수정 전)
surgery_name = _extract_surgery_name_from_query(question)
disability_region = _extract_disability_region_from_query(question)

if table_store is not None:
    try:
        if table_store.is_available():
            if surgery_name:
                result = table_store.lookup_surgery_grade(surgery_name)
                ...
```

```python
# 수정 후 — surgery_name 결정 직후, table_store 진입 전에 가드 추가
surgery_name = _extract_surgery_name_from_query(question)
disability_region = _extract_disability_region_from_query(question)

# 구(舊) 수술분류표 질의는 Parquet에 없으므로 C 주입 스킵
_OLD_TABLE_MARKERS = ("수술종류 분류", "종류 분류(종)", "수술분류표")
if surgery_name and any(marker in question for marker in _OLD_TABLE_MARKERS):
    surgery_name = None

if table_store is not None:
    ...
```

> **주의:** `_OLD_TABLE_MARKERS`는 함수 내 지역 상수 또는 모듈 상수 중 팀이 선호하는 방식으로 정의한다. `_build_structured_context` 함수 바깥에 모듈 레벨 상수로 두는 것을 권장한다.

---

## 2. Task 2 — 장해 지급률 추출 정밀도 개선

### 2-1. 문제

`_extract_disability_region_from_query()`는 현재 신체 부위 **키워드**("두 눈", "한 귀" 등)만 반환한다. `lookup_disability_rate()`는 `장해분류` 컬럼을 대상으로 부분 일치 검색 후 **첫 번째 행**을 반환한다.

결과적으로 동일 신체 부위에 여러 장해 조건이 있을 때 엉뚱한 행이 반환된다.

**실패 사례:**
- "두 눈이 멀었을 때 장해 지급률은?" → 추출: "두 눈" → 첫 번째 "두 눈" 포함 행이 "두 눈의 시력이 0.02 이하" 등으로 반환 → 지급률 불일치 → rate=MISS
- "한 팔의 3대관절 중 1관절의 기능을 완전히 잃었을 때 지급률은?" → 추출: "한 팔" → 첫 번째 "한 팔" 포함 행 = "한 팔의 손목 이상을 잃었을 때"(60%) → expected는 30% → rate=MISS

**성공 사례 비교:**
- "한 눈이 멀었을 때 장해 지급률은?" → "한 눈" → 첫 번째 "한눈" 행이 "한 눈이 멀었을 때" → rate=OK (우연히 첫 행과 일치)

rate_accuracy 0.429는 A+B와 동일하다: C의 장해 조회가 사실상 무효화 상태다.

### 2-2. 수정 대상

`src/rag/pipeline.py`

- `_DISABILITY_RATE_QUESTION_PATTERN` 신규 정규식 추가
- `_extract_disability_region_from_query()` 로직 개선

### 2-3. 수정 내용

#### Step A — 모듈 상수 추가

기존 `_DISABILITY_DESC_PATTERN` 아래에 아래 패턴을 추가한다.

```python
# 장해 지급률 질의 전체 조건구 추출 ("X 지급률은?" 형식)
_DISABILITY_RATE_QUESTION_PATTERN = re.compile(
    r"^(.{4,60}?)\s*(?:장해\s*)?지급률",
    re.UNICODE,
)
```

#### Step B — `_extract_disability_region_from_query()` 함수 수정

전체 조건구 추출을 **최우선**으로 시도한다. 기존 키워드/패턴 매칭은 fallback으로 유지한다.

```python
def _extract_disability_region_from_query(question: str) -> str | None:
    """장해 지급률 질의에서 핵심 신체 부위·상태 문자열을 추출한다."""

    # 1순위: "X 지급률은?" 형식에서 전체 조건구 추출 (정밀 매칭용)
    match = _DISABILITY_RATE_QUESTION_PATTERN.search(question)
    if match:
        phrase = match.group(1).strip().rstrip("경우 ")
        if len(phrase) >= 4:
            return phrase

    # 2순위: 기존 신체 부위 키워드 직접 매칭 (비 지급률 질의 대응)
    for keyword in _DISABILITY_KEYWORDS:
        if keyword in question:
            return keyword

    # 3순위: 기존 정규식 패턴
    for pattern in (_DISABILITY_QUERY_PATTERN, _DISABILITY_DESC_PATTERN):
        match = pattern.search(question)
        if not match:
            continue
        candidate = match.group(1).strip()
        if len(candidate) >= 2:
            return candidate

    return None
```

> **설명:** 1순위 패턴은 "두 눈이 멀었을 때 장해 지급률은?"에서 "두 눈이 멀었을 때"를, "한 팔의 3대관절 중 1관절의 기능을 완전히 잃었을 때 지급률은?"에서 "한 팔의 3대관절 중 1관절의 기능을 완전히 잃었을 때"를 추출한다. 이 긴 문자열을 `lookup_disability_rate()`에 전달하면 Parquet 부분 일치 검색의 정밀도가 대폭 향상된다.

---

## 3. Task 3 — grade_accuracy 디버그 로깅 추가

### 3-1. 문제

grade_accuracy가 A+B (0.294) → A+B+C (0.265)로 하락했다. C가 활성화될 때 LLM이 C 블록의 값을 무시하는 경우가 있는 것으로 추정된다.

**관찰:**
- 질의에 "1-3종·1-5종·신1-5종"을 명시하면 grade=3/3 성공 ([04], [09])
- "수술종수는?" 단문 질의는 grade=0/3 또는 1/3

### 3-2. 수정 대상

`scripts/eval.py` — OCR eval 루프 내 surgery_grade 처리 부분

### 3-3. 수정 내용

OCR eval 실행 시 surgery_grade 항목에 대해 **C 활성화 여부**와 **C 주입 내용**을 로그에 출력한다.

`eval.py`의 surgery_grade 항목 처리 블록에서 `_build_structured_context()` 또는 동등한 함수 호출 직후(혹은 pipeline이 반환한 answer 직전)에 아래를 출력한다.

```python
# eval.py 내 surgery_grade 항목 처리 시 추가
if item_type == "surgery_grade":
    # C 블록이 answer에 포함됐는지 확인
    c_block_present = "[구조화 데이터 — 직접 조회 (C)]" in answer
    print(f"  [C_DEBUG] C블록 존재: {c_block_present}")
```

> 로그 예시:
> ```
> [04] surgery_grade recall=OK page=OK code=OK [C_DEBUG] C블록 존재: True top_pages=['107', '26', '173'] grade=3/3
> [05] surgery_grade recall=OK page=OK code=OK [C_DEBUG] C블록 존재: False top_pages=['107', '26', '12'] grade=0/3
> ```

> **참고:** `answer`는 LLM 최종 답변 텍스트다. C 블록이 컨텍스트에 주입됐지만 LLM 답변에 해당 형식이 없다면, C 주입 자체는 성공했으나 LLM이 무시한 것이다. C 블록이 아예 없다면 `lookup_surgery_grade()`가 실패한 것이다.

> **구현 참고:** `eval.py`가 LLM 답변 텍스트에 직접 접근하지 않는 구조라면, `pipeline.py`의 `RagAnswer.answer` 필드 또는 `debug` 정보를 활용한다. 구조에 따라 가장 자연스러운 방법으로 구현한다.

---

## 4. 검증

### 4-1. eval 재실행

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py --ocr
```

**기대 결과:**

| 지표 | 이전 (A+B+C) | 목표 |
|---|---|---|
| retrieval recall@8 | 1.000 | 1.000 유지 |
| grade_accuracy | 0.265 | ≥ 0.294 (A+B 대비 회귀 없음) |
| rate_accuracy | 0.429 | ≥ 0.600 (장해 추출 개선 효과) |
| keyword_coverage | 0.485 | ≥ 0.485 유지 |

> grade_accuracy 목표: [12] 회귀 복원(+1/1)으로 최소 A+B 수준 회복. C 디버그 로그로 활성화 패턴 확인 후 추가 개선 여부를 다음 명세에서 결정한다.

> rate_accuracy 목표: 장해 추출 정밀도 개선으로 기존 MISS 8건 중 절반 이상 전환 기대. 0.600 달성 여부 확인 필수.

### 4-2. 단위 테스트

```bash
pytest -q
```

전원 통과 확인 (`240 passed` 이상).

### 4-3. 회귀 확인

```bash
# smoke v1 회귀 없음
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py
```

smoke v1 recall@8: 1.000 유지 확인.

---

## 5. 보고서 요구사항

`docs/63_C_HOOK_FIX_REPORT.md`에 다음을 포함한다.

1. Task 1 (`_OLD_TABLE_MARKERS` 가드) 적용 후 [12] grade 결과 변화
2. Task 2 (장해 추출 정밀도 개선) 적용 후, 각 MISS 항목별 추출된 문자열 및 rate 결과 변화
3. Task 3 C 디버그 로그: surgery_grade 항목별 C블록 존재 여부 표
4. 수정 전후 지표 비교표 (grade_accuracy, rate_accuracy, keyword_coverage)
5. pytest 결과

---

## 6. 중단 조건

- retrieval recall@8 < 1.000 → 즉시 롤백 후 보고
- smoke v1 recall@8 < 1.000 → 즉시 롤백 후 보고
- pytest 실패 → 즉시 중단

---

## 7. 명세 #61 재개

본 명세 완료 및 eval 결과 보고 후, **명세 #61 (smoke_v2 recall fix)을 재개**한다.
명세 #62 (PROJECT_SUMMARY 갱신)는 명세 #63 완료 후 순차 진행한다.

---

## 8. 커밋

커밋 메시지: `Fix C hook: guard old surgery table, improve disability phrase extraction (spec #63)`
푸시: `origin/master`
