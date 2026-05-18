# Codex Spec #56 — 수술명 행 단위 정확 검색 (Surgery Name Row Boost)

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **우선순위:** 🔴 높음  
> **예상 소요:** 1~2시간

---

## 1. 목표

eval #54에서 recall MISS가 발생한 `ocr_011`(사지골 사지관절 가관절수술, 기대 페이지 p64, 실제 반환 p188/p63/p25) 유형의 검색 실패를 해소한다.

**핵심 개선**: RRF 융합 이후, 수술명 쿼리를 감지하면 `table_json` 메타데이터에서 해당 수술명이 `"수술명"` 컬럼에 직접 포함된 청크를 최상위로 끌어올리는 `_boost_surgery_name_table_rows()` 함수를 `src/rag/pipeline.py`에 추가한다.

---

## 2. 배경

### 현재 검색 흐름의 문제

`ocr_chunker.py`는 OCR 표 블록을 **페이지 단위 단일 청크**로 인덱싱한다 (한 표 = 하나의 청크). p63과 p64에 모두 `사지골 사지관절` 계열 키워드를 포함하는 표가 존재하기 때문에, BM25/dense 점수에서 p63 청크가 p64를 앞선다.

기존 `_prefer_exact_text_hits()`는 청크 텍스트 전체에서 단어 존재 여부만 확인하므로, 두 청크 모두 해당 키워드를 포함하면 순서를 바꾸지 못한다.

### 해결 방향

각 청크의 `table_json` 메타데이터에는 다음 구조가 저장되어 있다:

```json
{
  "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
  "rows": [
    {"수술명": "사지골 사지관절 가관절수술", "수술해설": "...", "1-3종": "1", ...},
    ...
  ]
}
```

수술명이 `rows[i]["수술명"]`에 **부분 일치**하는 청크가 반드시 정답 청크이므로, 이 청크를 RRF 결과 최상위로 올리면 recall이 개선된다.

---

## 3. 대상 파일

| 파일 | 변경 유형 |
|---|---|
| `src/rag/pipeline.py` | **수정** — 함수 2개 추가, `retrieve_hits()` 내 호출 추가 |
| `tests/test_pipeline.py` | **수정** — 새 함수 테스트 3개 이상 추가 |
| `docs/56_SURGERY_NAME_BOOST_REPORT.md` | **신규 생성** — 구현 보고서 |

변경하지 않을 파일:

- `src/parser/ocr_chunker.py`
- `src/retrieval/` 전체
- `eval/ocr_qa.jsonl`
- `scripts/` 전체

---

## 4. 상세 요구사항

### 4-1. `_extract_surgery_name_from_query()` — 쿼리에서 수술명 추출

```python
_SURGERY_QUERY_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9 ·∙/()_-]{3,?}?)\s*(?:수술)?\s*의\s*(?:수술종수|수술해설|수술방법|수술 방법|분류)",
    re.UNICODE,
)
_SURGERY_DESC_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9 ·∙/()_-]{3,?}?)\s*(?:수술은|수술이란)\s*(?:어떤|무엇)",
    re.UNICODE,
)

def _extract_surgery_name_from_query(question: str) -> str | None:
    """수술명 관련 질의에서 핵심 수술명 문자열을 추출한다.

    인식하는 패턴:
      - "체외금속고정술의 수술종수는?"
      - "제허니아 근본수술의 1-3종·1-5종·신1-5종 수술종수는?"
      - "사지골 사지관절 가관절수술의 수술종수는?"
      - "결장경하 종양수술은 어떤 도구를 사용하는가?"

    Returns:
        정규화된 수술명 문자열, 또는 None (해당 패턴 없음).
    """
    for pattern in (_SURGERY_QUERY_PATTERN, _SURGERY_DESC_PATTERN):
        m = pattern.search(question)
        if m:
            return m.group(1).strip()
    return None
```

**설계 원칙**:
- 패턴이 일치하지 않으면 `None` 반환 → 부스팅 비활성화 (기존 동작 유지)
- 추출한 수술명은 그대로 사용 (추가 정규화 없음, 공백/괄호 포함)

### 4-2. `_boost_surgery_name_table_rows()` — 수술명 행 단위 부스팅

```python
def _boost_surgery_name_table_rows(hits: list[Hit], surgery_name: str) -> list[Hit]:
    """수술명이 table_json의 '수술명' 컬럼 행에 포함된 청크를 최상위로 올린다.

    Args:
        hits: RRF 융합 이후 정렬된 Hit 목록 (이미 top_k 이하).
        surgery_name: _extract_surgery_name_from_query()가 추출한 수술명 문자열.

    Returns:
        정렬이 바뀐 Hit 목록. 수술명 행이 있는 청크가 앞쪽, 나머지는 기존 순서 유지.
    """
    import json as _json

    def _has_surgery_row(hit: Hit) -> bool:
        raw = hit.metadata.get("table_json", "{}")
        if not raw or raw == "{}":
            return False
        try:
            tj = _json.loads(raw)
        except Exception:
            return False
        rows = tj.get("rows", [])
        for row in rows:
            cell = row.get("수술명", "")
            if surgery_name in cell or cell in surgery_name:
                return True
        return False

    matched = [h for h in hits if _has_surgery_row(h)]
    unmatched = [h for h in hits if not _has_surgery_row(h)]
    return matched + unmatched
```

**설계 원칙**:
- `surgery_name in cell` (추출명이 셀에 포함) OR `cell in surgery_name` (셀이 추출명에 포함): 양방향 부분 일치로 약어·괄호 포함 표현 대응
- `table_json`이 없거나 파싱 실패하면 조용히 `False` 반환
- 매칭 청크가 없어도 기존 순서를 그대로 반환 (no-op fallback)
- 성능: top_k(최대 16~24개) 반복이므로 O(n) 이내

### 4-3. `retrieve_hits()` 내 호출 위치

`_prefer_exact_text_hits()` 호출 바로 뒤, reranker 호출 전에 삽입한다. 코드 위치:

```python
# 기존 (pipeline.py line 237–238)
else:
    fused_hits = _prefer_exact_text_hits(fused_hits, named_code_terms)

# 수정 후
else:
    fused_hits = _prefer_exact_text_hits(fused_hits, named_code_terms)

surgery_name = _extract_surgery_name_from_query(question)
if surgery_name:
    fused_hits = _boost_surgery_name_table_rows(fused_hits, surgery_name)
```

**주의**: `code_hits` 경로 (if 분기)에서도 surgery name boost는 동일하게 적용한다. 수술명 쿼리는 코드 쿼리와 동시에 발생할 가능성이 낮지만, 혹시 있을 경우도 대응되도록 if/else 바깥에 위치시킨다.

최종 삽입 위치 (전체 흐름):

```python
# RRF 융합 후
fused_hits = rrf_fuse(...)
debug_rrf = list(fused_hits)

if code_hits:
    # code 우선 정렬
    ...
    fused_hits = ordered[:rrf_top_k]
else:
    fused_hits = _prefer_exact_text_hits(fused_hits, named_code_terms)

# ← 여기에 삽입 (code_hits 분기 이후, 공통 적용)
surgery_name = _extract_surgery_name_from_query(question)
if surgery_name:
    fused_hits = _boost_surgery_name_table_rows(fused_hits, surgery_name)

if self.reranker is not None:
    final_hits = self.reranker.rerank(question, fused_hits, top_k=final_top_k)
else:
    final_hits = fused_hits[:final_top_k]
```

---

## 5. 테스트 요구사항 (`tests/test_pipeline.py`)

최소 3개 테스트를 추가한다.

### Test 1 — 수술명 추출 패턴 정상 작동

```python
def test_extract_surgery_name_from_query_surgery_grade():
    assert _extract_surgery_name_from_query("사지골 사지관절 가관절수술의 수술종수는?") == "사지골 사지관절 가관절수술"
    assert _extract_surgery_name_from_query("체외금속고정술의 수술종수는?") == "체외금속고정술"
    assert _extract_surgery_name_from_query("제허니아 근본수술의 1-3종·1-5종·신1-5종 수술종수는?") is not None
```

### Test 2 — 비수술명 쿼리에서 None 반환

```python
def test_extract_surgery_name_from_query_non_surgery():
    assert _extract_surgery_name_from_query("두 눈이 멀었을 때 장해 지급률은?") is None
    assert _extract_surgery_name_from_query("계약 전 알릴 의무를 위반한 경우") is None
    assert _extract_surgery_name_from_query("척추에 심한 운동장해가 남은 경우 지급률은?") is None
```

### Test 3 — 수술명 행 부스팅: 매칭 청크가 앞으로

```python
def test_boost_surgery_name_table_rows_matched_first():
    matched_hit = Hit(
        id="p64",
        score=0.7,
        document="사지골 사지관절 | 수술해설 | 1 | 2 | 2",
        metadata={
            "doc_short": "실무가이드",
            "page_start": 64,
            "table_json": json.dumps({
                "headers": ["수술명", "수술해설", "1-3종", "1-5종", "신1-5종"],
                "rows": [{"수술명": "사지골 사지관절 가관절수술", "수술해설": "...", "1-3종": "1", "1-5종": "2", "신1-5종": "2"}]
            }, ensure_ascii=False)
        }
    )
    unmatched_hit = Hit(
        id="p63",
        score=0.9,  # RRF 점수가 높아도
        document="사지골 관련 다른 표",
        metadata={"doc_short": "실무가이드", "page_start": 63, "table_json": "{}"}
    )
    result = _boost_surgery_name_table_rows(
        [unmatched_hit, matched_hit],  # 원래 순서: p63 > p64
        surgery_name="사지골 사지관절 가관절수술"
    )
    assert result[0].id == "p64"  # 매칭 청크가 앞으로
    assert result[1].id == "p63"
```

### Test 4 — 수술명 없는 쿼리: 기존 순서 유지

```python
def test_boost_surgery_name_table_rows_no_match_preserves_order():
    hits = [
        Hit(id="a", score=0.9, document="text", metadata={"table_json": "{}"}),
        Hit(id="b", score=0.8, document="text", metadata={"table_json": "{}"}),
    ]
    result = _boost_surgery_name_table_rows(hits, surgery_name="없는수술명")
    assert [h.id for h in result] == ["a", "b"]  # 순서 불변
```

---

## 6. 검증 명령어

```bash
# 1. 신규 테스트만 실행
pytest tests/test_pipeline.py -v -k "surgery_name or boost_surgery"

# 2. 전체 회귀
pytest -q

# 3. retrieval-only eval (LLM 없이 recall 확인)
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_HOST=http://localhost:9 \
python scripts/eval.py --ocr

# 기대: recall@8 ≥ 0.975 (기존 유지), ocr_011 MISS 해소 시 1.000
```

---

## 7. 성공 기준

- `pytest -q` → 0 failures
- `_extract_surgery_name_from_query("사지골 사지관절 가관절수술의 수술종수는?")` == `"사지골 사지관절 가관절수술"`
- `_boost_surgery_name_table_rows()` 적용 후 `사지골 사지관절 가관절수술` 쿼리에서 p64 청크가 p63보다 앞순위
- `python scripts/eval.py --ocr` retrieval recall@8 ≥ 0.975 (하락 없음)
- ocr_011 MISS 해소 시 recall = 1.000 (best case)

---

## 8. 중단 조건

- `pytest -q` 기존 테스트 실패 → 즉시 중단 후 보고
- `_boost_surgery_name_table_rows()` 적용 후 recall이 0.975 미만으로 떨어지는 경우 → 함수 비활성화(조건문 주석처리) 후 원인 분석 보고
- `table_json` 파싱에서 예외가 suppress되지 않고 eval 실행 중 traceback 발생 → 즉시 보고

---

## 9. 출력 요구사항

`docs/56_SURGERY_NAME_BOOST_REPORT.md`에 다음을 포함한다:

1. 추가/수정한 함수 목록과 한 줄 설명
2. `pytest tests/test_pipeline.py -v -k "surgery"` 출력
3. `pytest -q` 전체 결과
4. `python scripts/eval.py --ocr` retrieval recall@8 결과
5. ocr_011 MISS 해소 여부 (MISS → HIT 전환 확인)
6. 잔여 블로커 ("None" 또는 구체 내용)

커밋 메시지: `Add surgery name row-level boost to retrieval pipeline`  
푸시: `origin/master`
