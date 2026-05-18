# Codex Spec #57 — 스테일 파일 정리 + LLM 답변 품질 개선 방안 검토

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **성격:** 정리 + 기술 검토 (이번 명세에서 구현은 없음)  
> **우선순위:** 🔴 높음

---

## 1. 배경

`eval/ocr_qa.jsonl` 40건 LLM 평가 결과(2026-05-13):

| 지표 | 결과 | 기준 | 상태 |
|---|---|---|---|
| retrieval recall@8 | 1.000 | ≥ 0.70 | ✅ (spec #56으로 달성) |
| grade_accuracy | 0.353 | ≥ 0.60 | ❌ |
| rate_accuracy | 0.357 | ≥ 0.70 | ❌ |
| keyword_coverage | 0.545 | — | 참고 |

**핵심 진단:**

- `disability_rate` 14개 항목은 모두 retrieval=OK임에도 rate_accuracy=0.357. 순수 LLM 추출 실패.
- `surgery_grade` 항목 중 page=OK인 케이스에서도 grade=0/3 발생 (ocr_003, ocr_010).
- 현재 `SYSTEM_PROMPT`에 OCR 파이프 구분 표에서 특정 행 값을 추출하는 지시가 없다.

다음 명세(#58 이후)에서 구현에 착수하기 전, 이번 명세에서 **Codex가 코드베이스를 직접 읽고 세 가지 개선 방안의 기술적 타당성을 평가**한다.

---

## 2. Task 1 — 스테일 파일 정리

spec #55 실행 결과 manifest 미등록 stale 파일 13개가 발견됐다. `p255_b02.txt`는 이미 삭제됐으며, 아래 12개가 남아 있다.

```
data/extracted/실무가이드/text/p064_b01.txt
data/extracted/실무가이드/text/p071_b01.txt
data/extracted/실무가이드/text/p071_b02.txt
data/extracted/실무가이드/text/p074_b02.txt
data/extracted/실무가이드/text/p081_b01.txt
data/extracted/실무가이드/text/p081_b02.txt
data/extracted/실무가이드/text/p151_b01.txt
data/extracted/실무가이드/text/p151_b02.txt
data/extracted/실무가이드/text/p255_b01.txt
data/extracted/실무가이드/text/p255_b03.txt
data/extracted/실무가이드/text/p279_b01.txt
data/extracted/실무가이드/text/p279_b02.txt
```

### 실행 절차

1. `python scripts/verify_p255_word_order.py` 재실행해 stale 목록을 최신 상태로 확인한다.
2. 위 12개 파일을 삭제한다.
3. `python scripts/verify_p255_word_order.py` 재실행 → Stale files: 0 확인.
4. `pytest -q` → 0 failures 확인.

### 제약

- `data/extracted/실무가이드/manifest.json` 수정 금지.
- `data/extracted/상담사례집/` 내 파일은 건드리지 않는다 (이번 범위 외).
- 파일 삭제 전 각 파일 첫 줄(preview)을 보고서에 기록한다.

---

## 3. Task 2 — LLM 답변 품질 개선 방안 기술 검토

구현 전에 아래 파일들을 읽고 세 가지 방안의 기술적 효용과 위험을 평가한다. **이번 명세에서 코드 수정은 없다.**

### 읽어야 할 파일

```
src/llm/prompt.py                  # SYSTEM_PROMPT, build_user_prompt
src/rag/pipeline.py                # answer(), retrieve_hits(), _boost_surgery_name_table_rows()
src/parser/ocr_chunker.py          # table_json 메타데이터 저장 방식
scripts/ingest.py                  # ingest 파이프라인 전체 흐름
eval/ocr_qa.jsonl                  # 평가 문항 구조 (type별 분포 파악용)
```

---

### 방안 A — 시스템 프롬프트 개선

**개요:**  
`src/llm/prompt.py`의 `SYSTEM_PROMPT`에 OCR 표 파싱 지시와 수술종수·장해 지급률 추출용 few-shot 예시를 추가한다. 코드 변경 없이 프롬프트 문자열만 수정한다.

**추가할 내용 (초안):**

```
## OCR 표 읽는 방법
표는 '수술명 | 수술해설 | 1-3종 | 1-5종 | 신1-5종' 또는
'장해 분류 | 지급률' 형식의 파이프(|) 구분 텍스트로 제공됩니다.

- 수술종수를 묻는 질문: 해당 수술명 행에서 묻는 종(1-3종/1-5종/신1-5종)의 숫자를 직접 인용하세요.
- 장해 지급률을 묻는 질문: 해당 신체 부위 행에서 지급률(%)을 직접 인용하세요.
- 값이 여러 셀에 걸쳐 있으면 같은 행의 가장 가까운 숫자 값을 사용하세요.

예시)
질문: 충수절제술의 1-5종 수술종수는?
컨텍스트: 충수절제술 | 맹장과 충수를 절제하는 수술 | 1 | 2 | 2
답변: 충수절제술의 1-5종 수술종수는 2종입니다.

질문: 한 팔의 손목 이상을 잃었을 때 장해 지급률은?
컨텍스트: 한 팔의 손목 이상을 잃었을 때 | 60%
답변: 한 팔의 손목 이상을 잃었을 때 장해 지급률은 60%입니다.
```

**Codex 검토 요청:**
- 현재 SYSTEM_PROMPT 구조에서 이 내용을 추가할 최적 위치는 어디인가?
- 기존 코드(예시, 핵심 규칙) 중 수정하거나 병합해야 할 항목이 있는가?
- 이 변경이 기존 약관/코드 질의 테스트(`eval/smoke_qa.jsonl`, `eval/smoke_qa_v2.jsonl`)에 부정적 영향을 줄 가능성이 있는가?
- `tests/test_pipeline.py` 또는 `tests/test_eval.py` 중 이 변경으로 깨질 수 있는 테스트가 있는가?

---

### 방안 B — 매칭 행 직접 주입 (Structured Row Injection)

**개요:**  
`src/rag/pipeline.py`의 `answer()` 단계에서, 수술명 또는 장해 부위가 추출된 경우 해당 청크의 `table_json`에서 매칭 행을 찾아 `key: value` 형식의 별도 블록을 LLM 프롬프트 상단에 삽입한다.

예시 삽입 블록:
```
[구조화 데이터]
수술명: 충수절제술(맹장 수술)
1-3종: 1 | 1-5종: 2 | 신1-5종: 2
```

**Codex 검토 요청:**
- `pipeline.py`의 `answer()` 함수와 `prompt.py`의 `build_user_prompt()` 중 어느 쪽에 삽입 로직을 두는 것이 더 적절한가? 이유를 설명하라.
- 수술명 쿼리(`_extract_surgery_name_from_query`)는 이미 구현됐다. 장해 지급률 쿼리(`"X를 잃었을 때"`, `"X장해가 남은 경우"` 등)에서 신체 부위명을 추출하는 패턴을 어떻게 설계할 것인가?
- `table_json`이 없는 텍스트 청크가 상위에 오는 경우(fallback)를 어떻게 처리할 것인가?
- 이 방안이 A(프롬프트만 수정)보다 복잡도 대비 추가 효과가 있다고 판단하는가?

---

### 방안 C — 별도 DataFrame 저장 + 직접 조회

**개요:**  
`scripts/ingest.py` 실행 시 OCR 표 청크의 `table_json`을 파싱해 수술종수 표와 장해분류표를 **별도 Parquet 또는 SQLite 파일**로 저장한다. 이후 쿼리 단계에서 벡터 검색 없이 수술명/신체 부위명으로 직접 row를 lookup하고, 그 결과를 LLM 컨텍스트에 삽입한다.

예시 저장 구조:
```
data/index/surgery_grades.parquet     # 수술명, 1-3종, 1-5종, 신1-5종, page
data/index/disability_rates.parquet   # 신체부위, 장해유형, 지급률(%), page
```

예시 조회:
```python
df = pd.read_parquet("data/index/surgery_grades.parquet")
row = df[df["수술명"].str.contains("충수절제술")].iloc[0]
# → {"수술명": "충수절제술", "1-3종": "1", "1-5종": "2", "신1-5종": "2", "page": 109}
```

**Codex 검토 요청:**
- 현재 `table_json`에 저장된 데이터만으로 수술종수 표와 장해분류표를 분리해 Parquet로 저장하는 것이 가능한가? 두 표를 구분할 수 있는 기준(컬럼 구조, doc_short 등)이 있는가?
- `scripts/ingest.py`의 어느 단계에 Parquet 저장 로직을 추가하는 것이 적절한가?
- 장해분류표는 신체 부위명과 장해 유형이 다단 구조(예: 두 눈 / 시력 / 완전 실명)로 되어 있을 수 있다. 이를 flat row로 정규화하는 데 어느 정도의 전처리 비용이 필요한가?
- A·B와 조합 시(A+C 또는 A+B+C) 중복·충돌 가능성이 있는가?
- 과제 2(보험금 자동 계산) 연계 관점에서 이 파일이 어떤 가치를 갖는가?

---

## 4. 보고서 요구사항

`docs/57_LLM_QUALITY_REVIEW_REPORT.md`에 다음을 포함한다.

**섹션 1 — 스테일 파일 정리 결과**
- 삭제 전 파일별 preview 목록
- 삭제 완료 확인 (`verify_p255_word_order.py` 출력)
- `pytest -q` 결과

**섹션 2 — 방안 A 검토**
- 현재 SYSTEM_PROMPT 분석 요약 (강점/약점)
- 추가 위치 추천 및 이유
- 기존 테스트 영향 분석
- 예상 구현 소요 시간 및 난이도 (상/중/하)

**섹션 3 — 방안 B 검토**
- `answer()` vs `build_user_prompt()` 삽입 위치 판단 및 이유
- 장해 부위 추출 패턴 설계안 (간단한 regex 또는 키워드 목록 초안)
- table_json 없는 경우 fallback 처리 방안
- 예상 구현 소요 시간 및 난이도
- A 대비 추가 효과 여부 판단

**섹션 4 — 방안 C 검토**
- 수술종수/장해분류표 식별 가능 여부 및 기준
- ingest.py 삽입 위치 추천
- 장해분류표 정규화 난이도 평가
- 예상 구현 소요 시간 및 난이도
- 과제 2 연계 활용 가능성

**섹션 5 — 종합 권장안**
- 세 방안의 효용/비용 비교표
- Codex 관점 권장 구현 순서 (구체적인 이유 포함)
- 구현 시 예상되는 주요 위험 요소

---

## 5. 중단 조건

- `pytest -q` 실패 → 즉시 중단, 보고
- stale 파일 삭제 중 manifest 등록 파일 삭제 위험 감지 → 즉시 중단, 보고

---

## 6. 커밋

커밋 메시지: `Remove stale OCR files and add LLM quality improvement review`  
푸시: `origin/master`
