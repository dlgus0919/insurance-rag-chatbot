# Codex Spec #64 — grade_accuracy 근본 원인 수정

> **작성일:** 2026-05-13
> **작성자:** Claude (검토자)
> **구현 담당:** Codex
> **성격:** 버그 수정 + 프롬프트 개선 + eval 환경 정비
> **우선순위:** 🔴 높음 — spec #63 구현 완료 후 eval 재실행 전에 반드시 선행

---

## 0. 진단 요청 및 배경

eval 로그 3개(baseline / A+B / A+B+C)를 교차 분석한 결과, **grade_accuracy 하락의 실제 원인이 기존 가설과 다름**이 확인됐다. Codex는 본 명세 구현 전에 아래 진단 내용을 직접 재확인하고, 진단과 다른 동작이 발견되면 보고서에 기재할 것.

### 0-1. 오해했던 가설과 실제 원인

| 가설 (틀림) | 실제 원인 (맞음) |
|---|---|
| B가 잘못된 수술명 행을 주입함 | B는 [06][07][11] 모두 **정확한 데이터를 주입** 중 |
| retrieval 개선이 grade에 도움됨 | retrieval MISS→OK로 바꿔도 grade 0/3 그대로 |

### 0-2. 재현 명령어 (진단 확인용)

아래를 실행해 B 주입 시뮬레이션을 확인한다.

```python
# B 주입 시뮬레이션: 각 질문에서 실제로 어떤 데이터가 LLM에 주입되는지 출력
import json, re, sys
sys.path.insert(0, '.')
from src.rag.pipeline import _extract_surgery_name_from_query, _build_structured_context
from src.parser.chunker import Chunk

chunks_path = 'data/processed/chunks.jsonl'
chunks = []
with open(chunks_path) as f:
    for line in f:
        c = json.loads(line)
        meta = c.get('metadata', {})
        if meta.get('doc_short') == '실무가이드':
            chunks.append(Chunk(id='', text=c['text'], metadata=meta))

test_questions = [
    ("체외금속고정술(창외고정술)의 1-3종·1-5종·신1-5종 수술종수는?",   {"1-3종":"1","1-5종":"2","신1-5종":"2"}),
    ("결장경하 종양수술의 수술종수는?",                              {"1-3종":"1","1-5종":"2","신1-5종":"1"}),
    ("사지골 사지관절 가관절수술의 수술종수는?",                       {"1-3종":"1","1-5종":"2","신1-5종":"2"}),
    ("제대허니아수술의 수술종수는?",                                  {"1-3종":"1","1-5종":"1","신1-5종":"1"}),
]
for q, expected in test_questions:
    sname = _extract_surgery_name_from_query(q)
    ctx   = _build_structured_context(q, chunks)   # table_store 없이 B만
    print(f"Q: {q}")
    print(f"  surgery_name 추출: {sname!r}")
    print(f"  B 주입 컨텍스트:\n{ctx}")
    print()
```

**확인 항목:**
1. "결장경하 종양수술의 수술종수는?" — B가 `1-3종:1|1-5종:2|신1-5종:1`을 주입하지만 LLM은 한 숫자만 반환함을 확인
2. "체외금속고정술(창외고정술)의 1-3종·..." — surgery_name 추출이 None이거나 필터에서 걸림을 확인

### 0-3. 원인별 영향 범위

| 원인 | 영향 항목 | grade 손실 |
|---|---|---|
| **A** LLM이 "수술종수는?" 질문에 한 값만 반환 | [05][06][07][08][10][11] | −6×3 = **−18점** |
| **B** `_extract_surgery_name_from_query()` 버그 (`endswith("술")` 실패) | [01] B/C 미활성화 | −2점 추정 |
| **C** C Parquet 구 테이블 오작동 | [12] | −1점 (spec #63 수정 완료) |
| **D** SYSTEM_PROMPT few-shot 오염 | rate [25] 인위 상승 | 측정 오염 |
| **E** eval LLM 비결정성 | keyword 노이즈 | 측정 불신뢰 |

---

## 1. Task 1 — SYSTEM_PROMPT rule 7 수정 (원인 A 해결)

### 1-1. 문제

`src/llm/prompt.py` rule 7의 현재 표현:

```
질문한 수술명과 같은 행에서 해당 종(1-3종/1-5종/신1-5종) 컬럼의 숫자를 직접 인용하세요.
```

"해당 종 컬럼"이 모호하다. "수술종수는?"처럼 특정 컬럼을 지정하지 않는 질문에서 LLM은 가장 대표적인 값 하나만 반환한다. eval 채점 함수 `answer_mentions_expected_grades()`는 각 컬럼값이 컬럼명과 함께 언급돼야 점수를 부여하므로 전부 0점 처리된다.

**패턴 확인:** 컬럼을 명시한 질문([04] "1-3종·1-5종·신1-5종 수술종수는?")은 grade=3/3, 미명시([05][06][07] "수술종수는?")는 grade=0/3.

### 1-2. 수정 대상

`src/llm/prompt.py` — `SYSTEM_PROMPT`의 rule 7 수술종수 부분

### 1-3. 수정 내용

```python
# 수정 전
"   - 수술종수 표는 '수술명 | 수술해설 | 1-3종 | 1-5종 | 신1-5종' 구조입니다.\n"
"     질문한 수술명과 같은 행에서 해당 종(1-3종/1-5종/신1-5종) 컬럼의 숫자를 직접 인용하세요.\n"

# 수정 후
"   - 수술종수 표는 '수술명 | 수술해설 | 1-3종 | 1-5종 | 신1-5종' 구조입니다.\n"
"     질문한 수술명과 같은 행에서 1-3종, 1-5종, 신1-5종 **세 값을 모두** 인용하세요.\n"
"     질문이 특정 종만 묻더라도 세 컬럼 값을 모두 답변에 포함하세요.\n"
```

> **이유:** 상담사는 한 컬럼만 알면 되는 경우에도, 보험 실무에서는 세 종수 모두 확인하는 것이 표준이다. 세 값을 모두 출력하도록 지시하면 특정 컬럼을 묻는 질문에도 손실 없이 채점된다.

### 1-4. few-shot 예시 교체 (eval 오염 제거)

현재 SYSTEM_PROMPT에 eval 항목 [25]와 동일한 질문이 포함돼 있다.

```python
# 수정 전 (eval [25]와 동일 — 오염)
"질문: 한 팔의 손목 이상을 잃었을 때 장해 지급률은?\n"
"답변: 한 팔의 손목 이상을 잃었을 때 장해 지급률은 60%입니다.\n"
"[출처: 실무가이드, 장해분류표, p.255]"

# 수정 후 (eval에 없는 질의로 교체)
"질문: 두 다리의 발목 이상을 잃었을 때 장해 지급률은?\n"
"답변: 두 다리의 발목 이상을 잃었을 때 장해 지급률은 100%입니다.\n"
"[출처: 실무가이드, 장해분류표, p.257]"
```

```python
# 수정 전 (eval [09]와 유사)
"질문: 충수절제술(맹장 수술)의 1-5종 수술종수는?\n"
"답변: 충수절제술의 1-5종 수술종수는 2종입니다.\n"
"[출처: 실무가이드, 수술분류표, p.109]"

# 수정 후 (세 컬럼 모두 명시하는 형태로 교체)
"질문: 전신성 복막염 수술의 1-3종·1-5종·신1-5종 수술종수는?\n"
"답변: 전신성 복막염 수술의 수술종수는 1-3종 2종, 1-5종 3종, 신1-5종 2종입니다.\n"
"[출처: 실무가이드, 수술종수표, p.108]"
```

> **주의:** 교체 예시 답변의 숫자는 실제 Parquet 또는 표 데이터와 일치해야 한다. `전신성 복막염 수술` expected_grades = {"1-3종":"2","1-5종":"3","신1-5종":"2"} (eval [10] 기준).  
> `두 다리의 발목 이상을 잃었을 때` expected_rate = "100" (eval [27] 기준).

---

## 2. Task 2 — `_extract_surgery_name_from_query()` 버그 수정 (원인 B 해결)

### 2-1. 문제

`src/rag/pipeline.py` 172-174번째 줄:

```python
candidate = match.group(1).strip()
if "수술" in candidate or candidate.endswith("술"):
    return candidate
```

"체외금속고정술(창외고정술)"은 `endswith("술")`에 실패한다 — 문자열이 `)`로 끝나기 때문이다. 또한 `"수술" in candidate`도 False다("체외금속고정술"에 연속된 "수술" 두 글자가 없음).

결과적으로 [01] "체외금속고정술(창외고정술)의 1-3종·1-5종·신1-5종 수술종수는?"에서 `surgery_name=None`이 돼 B와 C 모두 미활성화된다.

**재현 확인:**
```bash
python3 -c "
from src.rag.pipeline import _extract_surgery_name_from_query
tests = [
    '체외금속고정술(창외고정술)의 1-3종·1-5종·신1-5종 수술종수는?',
    '충수절제술(맹장 수술)의 1-3종·1-5종·신1-5종은?',
]
for q in tests:
    print(repr(q[:30]), '->', _extract_surgery_name_from_query(q))
"
```

### 2-2. 수정 내용

```python
# 수정 전
if "수술" in candidate or candidate.endswith("술"):
    return candidate

# 수정 후
# "술"이 문자열 어디에든 포함되면 수술명으로 판정
# (체외금속고정술, 절제술, 성형술 등 모두 포괄)
if "술" in candidate:
    return candidate
```

> **오탐 위험:** "술"이 포함된 비수술 단어(예: "결술", "술어")가 오탐될 수 있으나, 이 함수는 이미 `_SURGERY_QUERY_PATTERN` 또는 `_SURGERY_DESC_PATTERN` 매칭을 통과한 후보에만 적용된다. 해당 패턴이 수술 관련 문맥을 보장하므로 오탐 가능성은 낮다.

### 2-3. `_SURGERY_QUERY_PATTERN` 보강 (선택 사항)

"충수절제술(맹장 수술)의 1-3종·1-5종·신1-5종은?"은 현재 패턴의 종료 키워드(`수술종수|수술해설|…`) 없이 "은?"으로 끝나 매칭이 안 된다. 패턴에 종료 키워드 없는 "X의 1-3종·1-5종·신1-5종" 형식을 추가한다.

```python
_SURGERY_GRADE_COLUMN_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9 ·∙/()_-]{3,})\s*의\s*(?:1-3종|1-5종|신1-5종)",
    re.UNICODE,
)
```

`_extract_surgery_name_from_query()` 함수 내에서 기존 두 패턴 순회 후 이 패턴을 추가로 시도한다.

---

## 3. Task 3 — eval temperature=0 고정 (원인 E 해결)

### 3-1. 문제

[37] consultation 항목이 동일한 retrieval 결과에서 A+B=4/4, A+B+C=2/4로 달라졌다. Ollama 기본 temperature(0.8)에 의한 LLM 비결정성이 원인이다. keyword_coverage가 실행마다 달라져 개선/회귀 판단을 신뢰할 수 없다.

### 3-2. 수정 대상

Ollama API 호출 위치. 아래 명령으로 확인한다.

```bash
grep -rn "temperature\|ollama\|generate\|chat" src/llm/ | head -30
```

### 3-3. 수정 내용

eval.py 실행 시 Ollama 호출에 `temperature=0`을 적용한다. 두 가지 방법 중 코드베이스 구조에 맞는 것을 선택한다.

**방법 1 (권장) — LLM 호출 레이어에 파라미터 추가:**

```python
# src/llm/client.py 또는 동등 위치
def call_ollama(prompt: str, temperature: float = 0.7) -> str:
    response = ollama.generate(
        model=MODEL,
        prompt=prompt,
        options={"temperature": temperature},
    )
    return response["response"]
```

eval.py에서 `pipeline` 또는 LLM 클라이언트를 초기화할 때 `temperature=0`을 전달한다.

**방법 2 — 환경변수:**

```bash
# eval 실행 시
OLLAMA_TEMPERATURE=0 python scripts/eval.py --ocr
```

LLM 클라이언트에서 `float(os.environ.get("OLLAMA_TEMPERATURE", "0.7"))`로 읽도록 수정한다.

> eval 환경에서만 temperature=0을 적용하고, 실제 Streamlit 챗봇에서는 기본값을 유지한다.

---

## 4. 검증

### 4-1. 단위 확인 (구현 직후)

```bash
# Task 2 버그 수정 확인
python3 -c "
from src.rag.pipeline import _extract_surgery_name_from_query
cases = [
    ('체외금속고정술(창외고정술)의 1-3종·1-5종·신1-5종 수술종수는?', '체외금속고정술(창외고정술)'),
    ('충수절제술(맹장 수술)의 1-3종·1-5종·신1-5종은?', '충수절제술(맹장 수술)'),
    ('결장경하 종양수술의 수술종수는?', '결장경하 종양수술'),
]
for q, expected in cases:
    result = _extract_surgery_name_from_query(q)
    status = 'OK' if result and expected.split('(')[0] in result else 'FAIL'
    print(f'{status}: {result!r}  (expected contains {expected.split(\"(\")[0]!r})')
"
```

```bash
# Task 1 few-shot 교체 확인
grep -n "한 팔의 손목\|충수절제술" src/llm/prompt.py
# 출력이 없거나 교체된 질문이 출력돼야 함
```

### 4-2. eval 재실행

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 OLLAMA_TEMPERATURE=0 \
  python scripts/eval.py --ocr
```

**기대 결과:**

| 지표 | 이전 A+B+C | 목표 |
|---|---|---|
| grade_accuracy | 0.265 | **≥ 0.450** |
| rate_accuracy | 0.429 | **≥ 0.550** (spec #63 효과 포함) |
| keyword_coverage | 0.485 | ≥ 0.500 (temperature=0으로 안정화) |
| retrieval recall@8 | 1.000 | 1.000 유지 |

> grade_accuracy 세부 기대: [05][06][08][11] 각 0→3/3 전환 시 +12점, [01] B/C 활성화 시 추가 +2점. 34점 분모 기준 최대 +0.412 상승 가능.
> [03][07][10]은 OCR 품질 한계로 이번 수정으로도 개선 불확실.

### 4-3. pytest

```bash
pytest -q
```

전원 통과 확인.

### 4-4. smoke v1 회귀 없음

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py
```

recall@8: 1.000 유지 확인.

---

## 5. 보고서 요구사항

`docs/64_GRADE_ACCURACY_FIX_REPORT.md`에 다음을 포함한다.

1. **진단 재확인:** B 주입 시뮬레이션 결과 — 각 항목에서 실제 주입된 데이터와 LLM 출력 비교
2. **Task 1 적용 후 grade 항목별 변화표:** 항목·기대값·LLM 답변·채점 결과(수정 전/후)
3. **Task 2 수술명 추출 전/후 비교:** [01][09] 추출 성공 여부
4. **eval 결과 비교표:** 지표 4종의 수정 전후 수치
5. **미개선 항목 분석:** 수정 후에도 grade=0/3인 항목의 실패 이유 (OCR 품질 vs LLM 파싱 vs 기타)
6. pytest 결과

---

## 6. 중단 조건

- retrieval recall@8 < 1.000 → 즉시 롤백 후 보고
- pytest 실패 → 즉시 중단
- grade_accuracy가 수정 후에도 A+B+C 대비 하락 → 원인 재분석 후 보고

---

## 7. 커밋

커밋 메시지: `Fix grade accuracy: clarify rule-7, fix surgery name extraction, eval temperature (spec #64)`
푸시: `origin/master`
