# Codex 명세 #54 — OCR 문서 검색 품질 평가 QA 시트 + 자동화 테스트

## 1. 목적

OCR 처리된 두 문서(실무가이드, 상담사례집)를 대상으로 검색 품질을 측정한다. 기존 `eval/smoke_qa.jsonl`은 심평원·약관 위주라 OCR 문서 검증이 없다. 이번 명세에서는:

1. OCR 문서 전용 평가 파일 `eval/ocr_qa.jsonl` 을 작성한다 (≥40건).
2. `scripts/eval.py` 에 `--ocr` 플래그와 새 평가 지표를 추가한다.
3. 평가를 실행하고 결과를 `docs/54_EVAL_QA_REPORT.md` 에 기록한다.

---

## 2. 대상 문서 및 doc_short

| 문서명 | doc_short | 특성 |
|---|---|---|
| Claim 실무종합가이드 | `실무가이드` | 수술분류표(수술종수), 장해분류표(지급률), 판정기준 텍스트 |
| 소비자 상담 주요 사례집 | `상담사례집` | 보험 분쟁 상담사례, 약관 해설 |

---

## 3. 평가 문항 구조 (`eval/ocr_qa.jsonl`)

### 3-1. 기존 필드 (유지)

```jsonc
{
  "question": "질문 텍스트",
  "expected_pages": [64],          // 답이 위치한 문서 페이지 번호 (label 기준)
  "expected_codes": [],            // 코드 포함 여부 검증용 (해당 없으면 [])
  "type": "surgery_grade",         // 아래 3-2 참조
  "doc_sources": ["실무가이드"]    // 검색 필터용 doc_short
}
```

### 3-2. 신규 type 및 추가 필드

| type | 설명 | 추가 필드 |
|---|---|---|
| `surgery_grade` | 수술 1-3종/1-5종/신1-5종 수술종수 질문 | `expected_grades: {"1-3종":"1","1-5종":"2","신1-5종":"2"}` |
| `surgery_description` | 수술해설 텍스트 질문 | `expected_keywords: ["키워드1","키워드2"]` |
| `disability_rate` | 장해 지급률 질문 | `expected_rate: "60%"` |
| `disability_criteria` | 장해판정기준 텍스트 질문 | `expected_keywords: [...]` |
| `consultation` | 상담사례집 내용 질문 | `expected_keywords: [...]` |

---

## 4. 요구 평가 문항 목록

Codex는 아래 문항을 모두 포함하여 `eval/ocr_qa.jsonl`을 작성해야 한다.  
`expected_pages`는 **문서 page_label** 기준이다 (OCR 추출 파일 `p###` 번호가 아님).

### 4-1. 수술종수 (surgery_grade) — 실무가이드

| # | 질문 | expected_pages | expected_grades |
|---|---|---|---|
| 1 | 체외금속고정술(창외고정술)의 1-3종·1-5종·신1-5종 수술종수는? | [64] | `{"1-3종":"1","1-5종":"2","신1-5종":"2"}` |
| 2 | 수족골 적출술의 1-3종·1-5종·신1-5종 수술종수는? | [64] | `{"1-3종":"1","1-5종":"2","신1-5종":"2"}` |
| 3 | 주상골 적출술(골편적출술)의 수술종수는? | [64] | `{"1-3종":"1","1-5종":"2","신1-5종":"2"}` |
| 4 | 제허니아 근본수술의 1-3종·1-5종·신1-5종 수술종수는? | [107] | `{"1-3종":"1","1-5종":"1","신1-5종":"1"}` |
| 5 | 제대허니아수술의 수술종수는? | [107] | `{"1-3종":"1","1-5종":"1","신1-5종":"1"}` |
| 6 | 결장경하 종양수술의 수술종수는? | [167] | `{"1-3종":"1","1-5종":"2","신1-5종":"1"}` |
| 7 | 결장경하 폴립절제술의 수술종수는? | [167] | `{"1-3종":"1","1-5종":"2","신1-5종":"1"}` |
| 8 | 결장경하 점막절제술의 수술종수는? | [167] | `{"1-3종":"1","1-5종":"2","신1-5종":"1"}` |
| 9 | 충수절제술(맹장 수술)의 1-3종·1-5종·신1-5종은? | [109] | `{"1-3종":"1","1-5종":"2","신1-5종":"2"}` |
| 10 | 전신성 복막염 수술의 수술종수는? | [108] | Codex가 OCR 테이블에서 확인 후 작성 |
| 11 | 가관절수술(사지골 사지관절)의 수술종수는? | [64] | Codex가 OCR 테이블에서 확인 후 작성 |
| 12 | 직시하심장내수술의 수술종수는? | [7] | Codex가 OCR 테이블에서 확인 후 작성 |

> **주의**: #10~#12는 Codex가 해당 페이지 OCR 테이블 파일(`data/extracted/실무가이드/tables/`)을 직접 읽어 정확한 `expected_grades`를 채워야 한다. 추정 작성 금지.

### 4-2. 수술해설 (surgery_description) — 실무가이드

| # | 질문 | expected_pages | expected_keywords |
|---|---|---|---|
| 13 | 체외금속고정술은 어떤 방법의 수술인가? | [64] | ["피부 절개", "금속물", "고정"] |
| 14 | 주상골 적출술은 어떤 수술인가? | [64] | ["손목뼈", "골절", "골편"] |
| 15 | 제허니아 근본수술의 수술 방법을 설명하라. | [107] | ["복벽", "근막", "복막"] |
| 16 | 결장경하 종양수술은 어떤 도구를 사용하는가? | [167] | ["결장경"] |

### 4-3. 장해 지급률 (disability_rate) — 실무가이드

| # | 질문 | expected_pages | expected_rate |
|---|---|---|---|
| 17 | 두 눈이 멀었을 때 장해 지급률은? | [236] | "100" |
| 18 | 한 눈이 멀었을 때 장해 지급률은? | [236] | "50" |
| 19 | 두 귀의 청력을 완전히 잃었을 때 장해 지급률은? | [242] | "80" |
| 20 | 한 귀의 청력을 완전히 잃었을 때 장해 지급률은? | [242] | "25" |
| 21 | 코의 기능을 완전히 잃었을 때 장해 지급률은? | [245] | "15" |
| 22 | 척추에 심한 운동장해가 남은 경우 지급률은? | [251] | "40" |
| 23 | 척추에 뚜렷한 운동장해가 남은 경우 지급률은? | [251] | "30" |
| 24 | 두 팔의 손목 이상을 잃었을 때 장해 지급률은? | [255] | "100" |
| 25 | 한 팔의 손목 이상을 잃었을 때 장해 지급률은? | [255] | "60" |
| 26 | 한 팔의 3대관절 중 1관절의 기능을 완전히 잃었을 때 지급률은? | [255] | "30" |
| 27 | 두 다리의 발목 이상을 잃었을 때 장해 지급률은? | [257] | "100" |
| 28 | 한 손의 5개 손가락을 모두 잃었을 때 지급률은? | [264] | "55" |
| 29 | 한 손의 첫째 손가락을 잃었을 때 지급률은? | [264] | "15" |
| 30 | 씹어먹는 기능과 말하는 기능 모두에 심한 장해가 남은 경우 지급률은? | [247] | "100" |

### 4-4. 장해판정기준 (disability_criteria) — 실무가이드

| # | 질문 | expected_pages | expected_keywords |
|---|---|---|---|
| 31 | 장해에서 '영구적'이라 함은 어떤 상태를 의미하는가? | [232] | ["치유", "회복", "영구"] |
| 32 | 장해 판정 시 금속내고정물이 제거되지 않은 경우 언제 장해를 판정하는가? | [255] | ["제거", "의학적 소견"] |
| 33 | 팔의 3대관절은 무엇인가? | [255] | ["어깨관절", "팔꿈치관절", "손목관절"] |
| 34 | 근력등급 G0(Zero)란 어떤 상태인가? | [262] | ["운동기능", "수축"] |

### 4-5. 상담사례집 (consultation)

| # | 질문 | expected_pages | expected_keywords |
|---|---|---|---|
| 35 | 계약 전 알릴 의무를 위반한 경우 어떤 불이익이 있는가? | [65] | Codex가 OCR 내용 기반으로 작성 |
| 36 | 지정1인 한정운전 특약 가입 상태에서 지정 운전자가 다른 자동차를 운전 중 사고가 난 경우 보험금을 받을 수 있는가? | [189] | ["지급하지 않", "다른 자동차 운전담보"] |
| 37 | 2세대 실손의료보험에서 2016년 1월에 변경된 내용은 무엇인가? | [101] | ["자동차보험", "산재보험", "40%", "80%"] |
| 38 | 수술의 정의에서 '자택 등에서 치료가 곤란한 경우'의 의미는? | [273] | ["병원", "의원", "의사"] |

### 4-6. 교차 문서 (cross_doc) — 선택

| # | 질문 | expected_pages | doc_sources | note |
|---|---|---|---|---|
| 39 | 제허니아 근본수술의 수술해설과 1-3종 수술종수를 함께 알려달라. | [107] | ["실무가이드"] | 수술해설+수술종수 통합 질문 |
| 40 | 한 팔의 손목 이상을 잃었을 때 장해 지급률은 몇 %이고 판정기준은 무엇인가? | [255] | ["실무가이드"] | 지급률+판정기준 통합 질문 |

---

## 5. `scripts/eval.py` 수정 사항

### 5-1. `--ocr` 플래그 추가

```python
parser.add_argument("--ocr", action="store_true", help="OCR 문서 평가 문항을 사용합니다.")
```

문항 경로: `eval/ocr_qa.jsonl`

### 5-2. 신규 지표 함수 추가

```python
def answer_mentions_expected_grades(answer: str, expected_grades: dict) -> tuple[int, int]:
    """
    답변에서 수술종수 값이 올바르게 언급됐는지 확인한다.
    Returns: (correct_count, total_count)
    """
    correct = 0
    for col, value in expected_grades.items():
        # "1-3종: 1", "1-3종=1", "1-3종 : 1" 등 다양한 포맷 허용
        pattern = rf"{re.escape(col)}\s*[:=]\s*{re.escape(value)}"
        if re.search(pattern, answer):
            correct += 1
        elif value in answer and col in answer:
            correct += 1  # 값과 컬럼명이 모두 있으면 부분 인정
    return correct, len(expected_grades)


def answer_mentions_expected_rate(answer: str, expected_rate: str) -> bool:
    """답변에 기대 지급률(숫자+%)이 포함됐는지 확인한다."""
    return expected_rate in answer or (expected_rate.rstrip('%') + '%') in answer


def answer_mentions_expected_keywords(answer: str, expected_keywords: list[str]) -> tuple[int, int]:
    """expected_keywords 중 답변에 포함된 비율을 반환한다."""
    if not expected_keywords:
        return 1, 1
    matched = sum(1 for kw in expected_keywords if kw in answer)
    return matched, len(expected_keywords)
```

### 5-3. `--ocr` 실행 시 새 지표 집계

```python
grade_correct_total = 0
grade_total = 0
rate_hits = 0
rate_evaluated = 0
keyword_correct = 0
keyword_total = 0
```

각 문항 타입별 처리:
- `surgery_grade`: `answer_mentions_expected_grades()` → grade_correct_total, grade_total 누적
- `disability_rate`: `answer_mentions_expected_rate()` → rate_hits, rate_evaluated 누적
- `surgery_description`, `disability_criteria`, `consultation`: `answer_mentions_expected_keywords()` → keyword 누적

### 5-4. 출력 지표 추가

```
retrieval recall@8: 0.xxx
출처 페이지 정확도: 0.xxx
수술종수 정확도 (grade_accuracy): 0.xxx   # surgery_grade 문항 전용
장해 지급률 정확도 (rate_accuracy): 0.xxx  # disability_rate 문항 전용
키워드 포함율 (keyword_coverage): 0.xxx   # description/criteria/consultation 문항 전용
```

### 5-5. 성공 기준

```python
# --ocr 모드 종료 조건
if recall < 0.70:
    raise SystemExit(1)
if grade_total > 0 and grade_correct_total / grade_total < 0.60:
    raise SystemExit(1)
if rate_evaluated > 0 and rate_hits / rate_evaluated < 0.70:
    raise SystemExit(1)
```

---

## 6. 실행 명세

```bash
# 1. OCR 평가 실행
python scripts/eval.py --ocr

# 2. 기존 smoke QA도 회귀 확인
python scripts/eval.py
python scripts/eval.py --v2
```

> **전제**: Ollama 서버(`OLLAMA_MODEL`) + ChromaDB + BM25 인덱스 모두 로컬에서 구동 중이어야 한다.  
> Ollama가 없을 경우: 회귀 테스트(`pytest -q`)만 실행하고 LLM 평가는 skip하여 결과 보고에 명시한다.

---

## 7. 대상 파일

### 신규 생성
- `eval/ocr_qa.jsonl` — OCR 문서 전용 평가 문항 (≥40건)

### 수정
- `scripts/eval.py` — `--ocr` 플래그, 신규 지표 함수, 집계 로직, 출력

### 수정 금지
- `eval/smoke_qa.jsonl`, `eval/smoke_qa_v2.jsonl` — 기존 문항 변경 금지
- `src/` 전체 — 평가 스크립트 외 프로덕션 코드 수정 금지

---

## 8. 검증 순서

1. **파일 확인**: `eval/ocr_qa.jsonl` 존재 및 JSON 포맷 유효성 (`jq '.' eval/ocr_qa.jsonl`)
2. **문항 수 확인**: `wc -l eval/ocr_qa.jsonl` → ≥40
3. **type 분포 확인**: surgery_grade ≥ 10, disability_rate ≥ 10, consultation ≥ 4
4. **회귀 테스트**: `pytest -q` → 0 failures
5. **eval 실행**: `python scripts/eval.py --ocr` → 지표 출력
6. **기존 smoke 회귀**: `python scripts/eval.py` → 기존 통과 기준 유지

---

## 9. 보고서 (`docs/54_EVAL_QA_REPORT.md`) 포함 내용

1. 평가 문항 분포 (type별 건수)
2. `python scripts/eval.py --ocr` 전체 출력 (문항별 OK/MISS + 최종 지표)
3. `python scripts/eval.py` 기존 smoke 결과 (회귀 확인)
4. MISS 문항 분석: 검색 실패 원인 (청크 누락 / 임베딩 미스매치 / 답변 생성 오류)
5. 개선 권장사항 (있을 경우)
6. 잔여 블로커 ("None" 또는 구체적 내용)

---

## 10. 중단 조건 (Stop Rules)

- `pytest -q`에서 기존 테스트 실패 → 즉시 중단, 보고
- `ocr_qa.jsonl`의 `expected_grades`가 OCR 실제 데이터와 다를 경우 → 데이터 파일을 직접 읽어 수정 후 재시작
- Ollama 연결 불가 → LLM 평가 skip, retrieval-only 결과만 보고 (종료 오류 아님)
- `eval/smoke_qa.jsonl`이 수정됨 → 즉시 복원 후 보고
