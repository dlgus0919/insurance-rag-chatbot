# Codex Spec #58 — LLM 답변 품질 개선: A(프롬프트) + B(구조화 행 주입) 동시 구현

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **우선순위:** 🔴 높음  
> **예상 소요:** 3~4시간

---

## 1. 목표

현재 LLM 평가 지표를 아래 기준치까지 끌어올린다.

| 지표 | 현재 | 목표 |
|---|---|---|
| grade_accuracy | 0.353 | ≥ 0.60 |
| rate_accuracy | 0.357 | ≥ 0.70 |
| retrieval recall@8 | 1.000 | ≥ 1.000 (유지) |

두 방안을 **동시에** 구현한다.

- **방안 A**: `src/llm/prompt.py` — SYSTEM_PROMPT에 OCR 표 추출 규칙 추가
- **방안 B**: `src/rag/pipeline.py` — 수술종수·장해 지급률 구조화 행을 LLM 프롬프트에 직접 주입

**C 호환 설계 원칙**: 방안 C(별도 DataFrame 저장 + 직접 조회)가 이후 명세에서 추가될 때, 이번 구현을 재작성 없이 확장할 수 있어야 한다. 이를 위해 B의 구조화 데이터 생성 로직을 `_build_structured_context()` 단일 함수로 캡슐화하며, 해당 함수의 시그니처에 C를 위한 `table_store` 파라미터 자리를 예약한다.

---

## 2. 대상 파일

| 파일 | 변경 유형 |
|---|---|
| `src/llm/prompt.py` | 수정 — SYSTEM_PROMPT 확장 |
| `src/rag/pipeline.py` | 수정 — 함수 2개 추가, `answer()` 수정 |
| `tests/test_pipeline.py` | 수정 — 신규 테스트 ≥ 5개 추가 |
| `docs/58_LLM_AB_IMPL_REPORT.md` | 신규 생성 |

변경하지 않을 파일:
- `src/parser/` 전체
- `scripts/ingest.py`, `scripts/run_full_ocr.py`
- `eval/ocr_qa.jsonl`, `eval/smoke_qa.jsonl`, `eval/smoke_qa_v2.jsonl`

---

## 3. 방안 A — SYSTEM_PROMPT 수정 (`src/llm/prompt.py`)

### 3-1. 추가 규칙 (`## 핵심 규칙` 블록 끝에 삽입)

기존 규칙 6개 뒤에 아래 내용을 추가한다.

```
7. OCR로 추출된 표는 '컬럼1 | 컬럼2 | 값' 형식의 파이프(|) 구분 텍스트로 제공됩니다.
   - 수술종수 표는 '수술명 | 수술해설 | 1-3종 | 1-5종 | 신1-5종' 구조입니다.
     질문한 수술명과 같은 행에서 해당 종(1-3종/1-5종/신1-5종) 컬럼의 숫자를 직접 인용하세요.
   - 장해 지급률 표는 '장해의 분류 | 지급률' 구조입니다.
     질문한 신체 부위·장해 상태와 일치하는 행의 지급률(%) 숫자를 직접 인용하세요.
   - 답변에 수치가 포함될 때는 반드시 해당 수치를 명시하세요. "확인되지 않습니다"는 표에서
     해당 행을 찾을 수 없을 때만 사용하세요.
```

### 3-2. 예시 추가 (`## 예시` 블록 끝에 추가)

기존 2개 예시 뒤에 아래 2개를 추가한다.

```
질문: 충수절제술(맹장 수술)의 1-5종 수술종수는?
답변: 충수절제술의 1-5종 수술종수는 2종입니다.
[출처: 실무가이드, 수술분류표, p.109]

질문: 한 팔의 손목 이상을 잃었을 때 장해 지급률은?
답변: 한 팔의 손목 이상을 잃었을 때 장해 지급률은 60%입니다.
[출처: 실무가이드, 장해분류표, p.255]
```

### 3-3. 주의사항

- 기존 규칙 1~6과 예시 2개는 **수정하지 않는다**.
- 프롬프트 총 길이가 과도하게 늘지 않도록 규칙 7을 간결하게 유지한다 (현재 초안 기준 약 150 토큰).

---

## 4. 방안 B — 구조화 행 주입 (`src/rag/pipeline.py`)

### 4-1. 신규 함수: `_extract_disability_region_from_query()`

```python
_DISABILITY_KEYWORDS = [
    "두 눈", "한 눈", "두 귀", "한 귀", "코", "척추",
    "두 팔", "한 팔", "두 다리", "한 다리", "두 손", "한 손",
    "손가락", "발가락", "씹어먹는", "말하는 기능",
]

_DISABILITY_QUERY_PATTERN = re.compile(
    r"(.{2,15}?)\s*(?:을|를)\s*(?:완전히\s*)?(?:잃었을 때|상실)",
    re.UNICODE,
)
_DISABILITY_DESC_PATTERN = re.compile(
    r"(.{2,20}?)\s*(?:장해|운동장해|기능장해)\s*(?:가|이)\s*남은",
    re.UNICODE,
)

def _extract_disability_region_from_query(question: str) -> str | None:
    """장해 지급률 질의에서 핵심 신체 부위·상태 문자열을 추출한다.

    인식하는 패턴:
      - "두 눈이 멀었을 때 장해 지급률은?"
      - "한 팔의 손목 이상을 잃었을 때 지급률은?"
      - "척추에 심한 운동장해가 남은 경우 지급률은?"
      - "씹어먹는 기능과 말하는 기능 모두에 심한 장해가 남은 경우"

    Returns:
        추출된 부위·상태 문자열, 또는 None (해당 패턴 없음).
    """
    # 1차: 키워드 사전 직접 매칭 (가장 안정적)
    for kw in _DISABILITY_KEYWORDS:
        if kw in question:
            return kw
    # 2차: 정규식 패턴
    for pattern in (_DISABILITY_QUERY_PATTERN, _DISABILITY_DESC_PATTERN):
        m = pattern.search(question)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) >= 2:
                return candidate
    return None
```

### 4-2. 신규 함수: `_build_structured_context()`

이 함수가 C 호환의 핵심이다. 현재는 B 로직(chunks에서 조회)만 구현하지만, 시그니처에 `table_store=None`을 예약해 C 추가 시 함수 내부만 확장하면 된다.

```python
def _build_structured_context(
    question: str,
    chunks: list,
    table_store=None,  # 방안 C 예약 파라미터: Parquet/SQLite 조회 객체
) -> str | None:
    """수술종수 또는 장해 지급률 쿼리에서 매칭 행을 구조화 블록으로 반환한다.

    우선순위 (C 추가 시 자동 적용):
      1. table_store 조회 성공 시 → table_store 결과 반환 (C 전용)
      2. chunks의 table_json 매칭 → B 결과 반환 (현재)
      3. 매칭 없음 → None (no-op)

    Args:
        question: 사용자 질문.
        chunks: retrieve_hits()가 반환한 Chunk 목록.
        table_store: (미래) Parquet/SQLite 기반 조회 객체. 현재는 항상 None.

    Returns:
        "[구조화 데이터]\\n..." 형식의 문자열, 또는 None.
    """
    import json as _json

    # ── (미래) 방안 C: table_store 우선 조회 ──────────────────────────
    # if table_store is not None:
    #     result = table_store.lookup(question)
    #     if result:
    #         return result
    # ──────────────────────────────────────────────────────────────────

    surgery_name = _extract_surgery_name_from_query(question)
    disability_region = _extract_disability_region_from_query(question)

    if not surgery_name and not disability_region:
        return None

    for chunk in chunks:
        raw = chunk.metadata.get("table_json", "{}")
        if not raw or raw == "{}":
            continue
        try:
            tj = _json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if not isinstance(tj, dict):
            continue

        headers = tj.get("headers", [])
        rows = tj.get("rows", [])
        page = chunk.metadata.get("page_start", "?")
        doc = chunk.metadata.get("doc_short", "")

        # 수술종수 표 매칭
        if surgery_name and "수술명" in headers:
            for row in rows:
                cell = str(row.get("수술명", "")).strip()
                if surgery_name in cell or cell in surgery_name:
                    parts = [f"수술명: {cell}"]
                    for col in ["1-3종", "1-5종", "신1-5종"]:
                        if col in row:
                            parts.append(f"{col}: {row[col]}")
                    block = " | ".join(parts)
                    return f"[구조화 데이터 — 검색 결과 기반]\n{block}\n출처: {doc} p.{page}"

        # 장해 지급률 표 매칭
        if disability_region and "지급률" in headers:
            for row in rows:
                cell = str(row.get("장해의 분류", "")).strip()
                if disability_region in cell:
                    rate = row.get("지급률", "")
                    return (
                        f"[구조화 데이터 — 검색 결과 기반]\n"
                        f"장해 분류: {cell[:80]}\n"
                        f"지급률: {rate}%\n"
                        f"출처: {doc} p.{page}"
                    )

    return None
```

### 4-3. `answer()` 수정

`chunks = [...]` 직후, `prompt = build_user_prompt(...)` 직전에 삽입한다.

```python
chunks = [_hit_to_chunk(hit) for hit in fused_hits]

# 방안 B: 수술종수·장해 지급률 구조화 행 주입
structured_ctx = _build_structured_context(question, chunks)
prompt = build_user_prompt(question, chunks)
if structured_ctx:
    prompt = f"{structured_ctx}\n\n{prompt}"

llm_started = time.perf_counter()
answer_text = self.llm.generate(prompt, system=SYSTEM_PROMPT, temperature=temperature)
```

**주의**: 기존 코드의 `answer` 변수명이 메서드명(`answer`)과 충돌하므로 내부 변수명이 이미 `answer`인지 확인 후 필요 시 `answer_text`로 리팩토링한다. 현재 코드를 읽고 실제 변수명을 확인한 뒤 그대로 따를 것.

---

## 5. 테스트 (`tests/test_pipeline.py`)

최소 5개 테스트를 추가한다.

### Test 1 — 장해 부위 추출: 키워드 매칭

```python
def test_extract_disability_region_keyword_match():
    assert _extract_disability_region_from_query("두 눈이 멀었을 때 장해 지급률은?") == "두 눈"
    assert _extract_disability_region_from_query("한 팔의 손목 이상을 잃었을 때 지급률은?") == "한 팔"
    assert _extract_disability_region_from_query("두 귀의 청력을 완전히 잃었을 때") == "두 귀"
```

### Test 2 — 장해 부위 추출: 비해당 쿼리 → None

```python
def test_extract_disability_region_non_disability():
    assert _extract_disability_region_from_query("충수절제술의 수술종수는?") is None
    assert _extract_disability_region_from_query("계약 전 알릴 의무 위반 시 불이익은?") is None
```

### Test 3 — 구조화 컨텍스트: 수술종수 표 매칭

```python
def test_build_structured_context_surgery_grade(make_chunk):
    chunk = make_chunk(table_json=json.dumps({
        "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
        "rows": [{"수술명": "충수절제술(맹장 수술)", "수술해설": "...", "1-3종": "1", "1-5종": "2", "신1-5종": "2"}]
    }), doc_short="실무가이드", page_start=109)
    result = _build_structured_context("충수절제술의 1-5종 수술종수는?", [chunk])
    assert result is not None
    assert "1-5종: 2" in result
    assert "충수절제술" in result
```

### Test 4 — 구조화 컨텍스트: 장해 지급률 표 매칭

```python
def test_build_structured_context_disability_rate(make_chunk):
    chunk = make_chunk(table_json=json.dumps({
        "headers": ["장해의 분류", "지급률"],
        "rows": [{"장해의 분류": "1) 한 팔의 손목 이상을 잃었을 때", "지급률": "60"}]
    }), doc_short="실무가이드", page_start=255)
    result = _build_structured_context("한 팔의 손목 이상을 잃었을 때 지급률은?", [chunk])
    assert result is not None
    assert "60%" in result
```

### Test 5 — 구조화 컨텍스트: 매칭 없음 → None

```python
def test_build_structured_context_no_match(make_chunk):
    chunk = make_chunk(table_json="{}", doc_short="실무가이드", page_start=1)
    result = _build_structured_context("충수절제술의 수술종수는?", [chunk])
    assert result is None

def test_build_structured_context_non_structured_query(make_chunk):
    chunk = make_chunk(table_json=json.dumps({
        "headers": ["수술명", "1-3종"], "rows": []
    }), doc_short="실무가이드", page_start=1)
    result = _build_structured_context("계약 전 알릴 의무란?", [chunk])
    assert result is None
```

> `make_chunk`는 테스트용 fixture로, `Chunk(id="test", text="", metadata={...})` 를 생성하는 헬퍼다. 기존 test_pipeline.py에 유사 패턴이 있으면 그것을 재사용한다.

---

## 6. 검증 명령어

```bash
# 1. 신규 테스트
pytest tests/test_pipeline.py -v -k "disability or structured_context"

# 2. 전체 회귀
pytest -q

# 3. OCR eval (LLM 포함 — Ollama 실행 중이어야 함)
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
python scripts/eval.py --ocr 2>&1 | tee logs/eval_ocr_ab_$(date +%Y%m%d_%H%M%S).log

# 4. 기존 smoke 회귀
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
python scripts/eval.py 2>&1 | tee logs/eval_smoke_ab_$(date +%Y%m%d_%H%M%S).log

python scripts/eval.py --v2 2>&1 | tee logs/eval_smoke_v2_ab_$(date +%Y%m%d_%H%M%S).log
```

---

## 7. 성공 기준

- `pytest -q` → 0 failures (≥ 234 tests 예상)
- `python scripts/eval.py --ocr`: grade_accuracy ≥ 0.60, rate_accuracy ≥ 0.70
- `python scripts/eval.py` 및 `--v2`: 기존 recall/page_accuracy 수치 하락 없음
- `_build_structured_context()`의 `table_store=None` 파라미터가 함수 시그니처에 명시되어 있을 것

---

## 8. 중단 조건

- `pytest -q` 기존 테스트 실패 → 즉시 중단, 보고
- `python scripts/eval.py` 또는 `--v2`의 recall이 이전 대비 0.05 이상 하락 → SYSTEM_PROMPT 변경 롤백 후 보고
- `_build_structured_context()`에서 잘못된 행이 주입되어 eval에서 오히려 오답 확신 사례가 증가하면 → injection 비활성화(`structured_ctx = None`으로 고정) 후 보고

---

## 9. 출력 요구사항

`docs/58_LLM_AB_IMPL_REPORT.md`에 다음을 포함한다:

1. 수정 함수·파일 목록과 한 줄 설명
2. `pytest -q` 결과
3. `python scripts/eval.py --ocr` 전체 출력 (grade_accuracy, rate_accuracy, recall@8)
4. `python scripts/eval.py` / `--v2` smoke 결과 (recall, page_accuracy)
5. 구조화 컨텍스트 주입 사례 샘플 2건 (실제 주입된 블록 텍스트)
6. `_build_structured_context()` 시그니처 발췌 (C 예약 파라미터 확인)
7. 잔여 블로커 ("None" 또는 구체 내용)

커밋 메시지: `Improve LLM answer quality: prompt rules + structured row injection`  
푸시: `origin/master`
