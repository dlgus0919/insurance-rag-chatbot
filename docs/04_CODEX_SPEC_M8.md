# Codex 개발자 명세서 — M8: 인용 형식 강화 & Eval 개선

> **이 문서는 Codex 에이전트(개발자)가 받아 구현하는 명세입니다.**
> 기획·검토는 별도 에이전트가 담당하며, 본 명세를 임의로 변경하지 마세요.
> 결정 변경이 필요한 사안이 발생하면 변경 사유와 옵션을 PR 설명에 명시하고 검토자에게 알리세요.

---

## 0. Codex에게 전달할 프롬프트 (이 섹션을 그대로 Codex에 붙여넣으세요)

```
당신은 시니어 Python 개발자입니다. M6·M7까지 완료된 "보험 문서 RAG 챗봇" 프로젝트에서
Eval 결과(recall=1.000, page_accuracy=0.571)를 분석하여 두 가지 개선을 구현합니다.

배경:
- Retrieval recall@8은 1.000으로 완벽하나 출처 페이지 정확도가 0.571로 목표(0.6) 미달.
- 원인 1: gemma3:4b 모델이 "[출처: ..., p.페이지]" 형식을 일관되게 출력하지 않음.
- 원인 2: 약관 청크의 page 범위 형식("p.36-38")이 정답인데 eval이 "p.38"만 정답으로 인정.

원칙:
1. 기존 M1-M7 코드의 동작을 깨뜨리지 마세요. pytest 19개 전부 통과해야 합니다.
2. 이번 마일스톤은 단일 커밋으로 완료합니다.
3. 변경 파일은 명세에 명시된 4개로 제한합니다.
4. M8 완료 후 Streamlit UI 테스트 가이드라인을 별도 마크다운 파일로 작성하세요. (명세 5장 참조)

먼저 명세 전체(docs/04_CODEX_SPEC_M8.md)와 Eval 결과(위 터미널 출력)를 읽고,
명세 4장 "완료 기준"을 자가 검증한 뒤 결과를 보고하세요.
```

---

## 1. 배경 및 범위

### 현황
```
retrieval recall@8 : 1.000  ✅
출처 페이지 정확도  : 0.571  ⚠️ (목표 ≥ 0.60)
skipped            : 1건 (가이드북 미인덱싱, 정상)
```

page=MISS 6건 분류:
- **그룹A (4건)** — 01, 02, 08, 12: LLM이 `[출처: ..., p.XXX]` 형식 자체를 생략하거나 다른 형식으로 씀
- **그룹B (2건)** — 11, 15: 약관 청크가 멀티 페이지(p.36-38)인데 eval이 `p.38` 문자열만 체크

### 이번 변경 범위 (M8)

| 파일 | 변경 내용 |
|---|---|
| `src/llm/prompt.py` | SYSTEM_PROMPT 인용 규칙 강화 |
| `scripts/eval.py` | `answer_mentions_expected_page()` 범위 형식 허용 |
| `.env.example` | OLLAMA_MODEL 주석 및 gemma3 대안 안내 추가 |
| `docs/05_STREAMLIT_TEST_GUIDE.md` | Streamlit UI 테스트 가이드라인 (신규) |

**변경하지 않는 파일:** chunker, config, ingest, retrieval/*, pipeline, UI

---

## 2. 변경 명세

### 2.1 `src/llm/prompt.py` — SYSTEM_PROMPT 강화

**변경 목적:** gemma3:4b 계열 모델이 `[출처: ..., p.페이지]` 형식을 더 일관되게 따르도록 규칙 4를 구체화하고 형식 예시를 추가한다.

**3B 모델 친화 원칙 유지:** 시스템 프롬프트 전체 길이는 현재(6줄)보다 길어지지 않도록 한다. 불필요한 설명 제거 후 규칙 4만 구체화한다.

현재:
```python
SYSTEM_PROMPT = """당신은 보험사 직원의 질문에 답하는 어시스턴트입니다. 참고 문서에는 건강보험 고시(심평원), 실손의료보험 약관, 보상가이드북 등이 포함될 수 있습니다.
규칙:
1. 반드시 제공된 참고 문맥(컨텍스트) 안의 정보만 사용해 답하세요.
2. 컨텍스트에 답이 없거나 모호하면 "제공된 문서에서 확인되지 않습니다."라고 답하세요.
3. 추측하거나 외부 지식을 사용하지 마세요.
4. 답변 마지막에 사용한 출처를 [출처: 문서명, 조문/절, p.페이지] 형식으로 나열하세요.
5. 한국어로 간결하고 정확하게 답하세요."""
```

변경 후:
```python
SYSTEM_PROMPT = """당신은 보험사 직원의 질문에 답하는 어시스턴트입니다. 참고 문서에는 건강보험 고시(심평원), 실손의료보험 약관, 보상가이드북 등이 포함될 수 있습니다.
규칙:
1. 반드시 제공된 참고 문맥(컨텍스트) 안의 정보만 사용해 답하세요.
2. 컨텍스트에 답이 없거나 모호하면 "제공된 문서에서 확인되지 않습니다."라고 답하세요.
3. 추측하거나 외부 지식을 사용하지 마세요.
4. 답변 마지막에 반드시 아래 형식으로 출처를 기재하세요. 생략하지 마세요.
   형식: [출처: 문서명, 조문/절, p.페이지]
   예시: [출처: 심평원, 제1절 진찰료, p.101]
5. 한국어로 간결하고 정확하게 답하세요."""
```

> **Codex 판단 기준:** 위 diff는 기준이며, 실제로 gemma3:4b가 잘 따르는 표현으로 미세 조정해도 됩니다. 단, 규칙 수(5개)와 전체 길이는 현재와 동등 수준을 유지해야 합니다.

### 2.2 `scripts/eval.py` — `answer_mentions_expected_page()` 개선

**변경 목적:** 약관 청크처럼 멀티 페이지 범위(`p.36-38`)가 컨텍스트 레이블로 전달될 때, LLM이 범위 형식으로 인용해도 정답으로 인정한다.

현재:
```python
def answer_mentions_expected_page(answer: str, expected_pages: list[int]) -> bool:
    """답변 텍스트에 정답 페이지 번호가 언급됐는지 확인한다."""
    return any(f"p.{page}" in answer or f"p. {page}" in answer for page in expected_pages)
```

변경 후:
```python
def answer_mentions_expected_page(answer: str, expected_pages: list[int]) -> bool:
    """
    답변 텍스트에 정답 페이지 번호가 언급됐는지 확인한다.

    단일 페이지 형식("p.38")과 범위 형식("p.36-38") 모두 정답으로 인정한다.
    범위 형식의 경우, expected_pages 중 하나가 범위 안에 포함되면 정답으로 처리한다.
    """
    import re

    # 1) 단일 페이지 형식 체크: "p.38", "p. 38"
    for page in expected_pages:
        if f"p.{page}" in answer or f"p. {page}" in answer:
            return True

    # 2) 범위 형식 체크: "p.36-38" → 36~38 사이에 expected_page가 있는지
    for match in re.finditer(r"p\.(\d+)-(\d+)", answer):
        range_start, range_end = int(match.group(1)), int(match.group(2))
        if any(range_start <= page <= range_end for page in expected_pages):
            return True

    return False
```

### 2.3 `.env.example` — 모델 안내 추가

현재:
```
OLLAMA_MODEL=qwen2.5:3b-instruct
```

변경 후:
```
# LLM 모델 설정 (Ollama에 설치된 모델 이름으로 변경하세요)
# 기본값: qwen2.5:3b-instruct (ollama pull qwen2.5:3b-instruct)
# 대안: gemma3:4b (이미 설치된 경우), gemma3:1b (경량)
OLLAMA_MODEL=qwen2.5:3b-instruct
```

### 2.4 `docs/05_STREAMLIT_TEST_GUIDE.md` — 신규 작성

명세 5장에서 별도 정의.

---

## 3. 테스트

### 3.1 기존 테스트 유지

```bash
pytest tests/ -q   # 기존 19개 전부 통과해야 함
```

### 3.2 `answer_mentions_expected_page` 단위 테스트 추가

`tests/test_eval.py`에 다음 케이스를 추가한다:

```python
def test_answer_mentions_page_range_format() -> None:
    """범위 형식(p.36-38)도 expected_page가 범위 안에 있으면 정답으로 인정한다."""
    from scripts.eval import answer_mentions_expected_page

    # 범위 형식 — 정답
    assert answer_mentions_expected_page("[출처: 약관, 제4조, p.36-38]", [38]) is True
    assert answer_mentions_expected_page("[출처: 약관, p.78-84]", [80]) is True
    assert answer_mentions_expected_page("[출처: 약관, p.78-84]", [82]) is True

    # 범위 밖 — 오답
    assert answer_mentions_expected_page("[출처: 약관, p.36-38]", [40]) is False

    # 기존 단일 형식도 그대로 동작
    assert answer_mentions_expected_page("[출처: 심평원, p.101]", [101]) is True
    assert answer_mentions_expected_page("[출처: 심평원, p.101]", [100]) is False
```

### 3.3 page accuracy 재측정

```bash
OLLAMA_MODEL=gemma3:4b python scripts/eval.py
```

**통과 조건:** `출처 페이지 정확도 ≥ 0.600`

> 단, 모델·컨텍스트 길이에 따라 비결정적 변동이 있으므로 2~3회 실행 평균으로 판단. 한 번 실행에서 0.571이 나와도 다른 실행에서 0.643이 나오면 개선으로 인정한다.

---

## 4. 마일스톤 완료 기준

| 항목 | 기준 |
|---|---|
| 기존 테스트 | `pytest tests/ -q` — 19개 이상 통과 |
| 신규 테스트 | `test_answer_mentions_page_range_format` 포함 전부 통과 |
| page accuracy | `python scripts/eval.py` — 0.600 이상 (또는 유의미한 개선) |
| 테스트 가이드 | `docs/05_STREAMLIT_TEST_GUIDE.md` 파일 존재 및 명세 5장 기준 충족 |

---

## 5. Streamlit 테스트 가이드라인 명세 (`docs/05_STREAMLIT_TEST_GUIDE.md`)

Codex는 M8 구현 완료 직후 이 가이드라인 파일을 작성한다. 파일은 **범준님(기획자)이 직접 Streamlit을 처음 열고 단계별로 테스트**할 수 있도록 쓰여야 한다. 기술적 배경 없이도 따라할 수 있게 평이하게 작성한다.

### 5.1 파일 구성 요구사항

**섹션 1 — 실행 방법**
- Ollama 앱 실행 확인 방법
- `.env` 파일에 `OLLAMA_MODEL=gemma3:4b` 설정 확인
- 터미널에서 `streamlit run src/ui/streamlit_app.py` 실행
- 브라우저 자동 열림 또는 `http://localhost:8501` 접속

**섹션 2 — 기본 UI 확인 (스크린샷 없이 텍스트로 설명)**
- 사이드바 구성 요소: 모델명 표시, Top-K 슬라이더, 온도 슬라이더, 대화 초기화 버튼
- 채팅 입력창 위치
- 첫 질문 시 인덱스 로딩 대기 시간 안내 (최초 1회 30초 내외)

**섹션 3 — 단계별 테스트 시나리오 (반드시 아래 5개 포함)**

시나리오는 기획자가 검증 가능한 예상 답변 요소와 함께 제공한다:

| # | 질문 | 테스트 목적 | 확인 포인트 |
|---|---|---|---|
| T1 | `AA157은 어떤 기관의 초진 진찰료이며 점수는 얼마인가요?` | 심평원 코드 조회 | 상급종합병원, 점수, p.101 인용 |
| T2 | `N39.3 진단이 실손의료비 약관에서 보상가능한지 알려줘.` | 약관 진단코드 조회 | "요실금", "보상하지 않습니다", 약관 출처 |
| T3 | `식도조루술의 코드를 알려줘.` | 심평원 수술코드 조회 | Q2333, p.531 인용 |
| T4 | `실손의료보험 약관에서 3대비급여에 해당하는 항목은 무엇인가요?` | 약관 의미 검색 | 도수치료, 비급여 주사료, MRI/MRA |
| T5 | `요양기관 종별가산율에서 상급종합병원은 몇 퍼센트를 가산하나요?` | 심평원 의미 검색 | 퍼센트 수치, 심평원 출처 |

**섹션 4 — 출처 expander 확인 방법**
- 답변 아래 "출처 보기" 클릭 시 청크 원문 확인 방법
- 문서명(심평원/약관)이 표시되는 위치 안내

**섹션 5 — 이상 증상 대처 방법**
- "Ollama 서버에 연결할 수 없습니다" → Ollama 앱 실행 또는 `ollama serve` 실행
- 응답이 너무 느림 → 사이드바 온도 낮추기(0.1), Top-K 줄이기(4)
- 출처가 없거나 "확인되지 않습니다" → 질문을 더 구체적으로 재시도
- 인덱스 오류 → `python scripts/ingest.py --stage index` 재실행

**섹션 6 — 멀티 문서 구분 확인**
- T1과 T2 답변을 비교: T1은 "심평원" 출처, T2는 "약관" 출처가 명시되어야 함
- 출처 expander에서 `doc_short` 또는 `doc_name` 필드로 구분 확인 방법 설명

### 5.2 문체 가이드
- 독자: 보험사 실무 담당자 (비개발자)
- 명령어는 코드 블록으로 표시
- 각 확인 포인트는 "~이 보이면 정상입니다" 형식으로 마무리
- 오류 대처는 원인·해결 순서로 간결하게

---

## 6. PR 보고서 양식

```
## M8 완료 보고
- 변경 파일: src/llm/prompt.py, scripts/eval.py, .env.example, docs/05_STREAMLIT_TEST_GUIDE.md
- 자가 검증 결과:
  - [pytest]: X개 통과 (기존 19개 + 신규 X개)
  - [page accuracy 1차]: X.XXX
  - [page accuracy 2차]: X.XXX (비결정적 변동 확인용)
  - [테스트 가이드]: docs/05_STREAMLIT_TEST_GUIDE.md 작성 완료
- SYSTEM_PROMPT 변경 내용 요약: ...
- answer_mentions_expected_page 로직 변경 요약: ...
- 검토자 확인 필요 항목: ...
```
