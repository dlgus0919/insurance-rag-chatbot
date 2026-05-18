# Codex Spec #59 — PROJECT_SUMMARY 갱신 + Streamlit OCR QA 시나리오 작성

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **성격:** 문서 작업 (코드 수정 없음)  
> **우선순위:** 🟡 중간

---

## 1. 배경

- `docs/PROJECT_SUMMARY.md`는 2026-05-12 기준 명세 #53까지만 반영되어 있다. 이후 #54~#58이 완료됐으나 문서에 누락되어 있다.
- Streamlit 챗봇의 수동 QA 가이드(`docs/11_TEST_SCENARIO_GUIDE.md`)는 심평원·약관 문서 중심으로 작성됐다. 실무가이드·상담사례집 OCR 인덱스와 A+B 구조화 컨텍스트 주입 기능을 검증하는 시나리오가 없다.

---

## 2. Task 1 — PROJECT_SUMMARY.md 갱신

**대상 파일:** `docs/PROJECT_SUMMARY.md`

### 2-1. 섹션 3 (OCR 파이프라인 진화 이력) 추가

기존 "Phase 5 — 워크플로우 확정 (명세 #53)" 하단에 아래 내용을 추가하라.

```markdown
### Phase 6 — RAG 파이프라인 + LLM 품질 개선 (명세 #54–58)

**RAG 인덱스 구축 및 eval 자동화** (명세 #54)
- `scripts/ingest.py --include-ocr --stage all` 로 ChromaDB + BM25 인덱스 최초 구축
- 40건 OCR QA(`eval/ocr_qa.jsonl`) 자동 평가 파이프라인 완성
- 최초 baseline eval 결과: retrieval recall@8=0.975, grade_accuracy=0.353, rate_accuracy=0.357

**스테일 파일 정리** (명세 #55, #57)
- `data/extracted/실무가이드/text/` 내 manifest 미등록 stale 파일 13개 전체 삭제 완료
- `scripts/verify_p255_word_order.py` — Stale files: 0 확인

**수술명 행 부스팅** (명세 #56)
- `_extract_surgery_name_from_query()` + `_boost_surgery_name_table_rows()` 추가
- RRF 풀을 `final_top_k * 3`으로 확장, reranker 전 수술명 행 재정렬
- 결과: retrieval **recall@8 = 1.000** (ocr_011 MISS → HIT)

**LLM 품질 개선 A+B** (명세 #57 검토, #58 구현)
- **A — 시스템 프롬프트 개선:** SYSTEM_PROMPT 핵심 규칙 7 추가 + 수술종수·장해 지급률 few-shot 예시 2건
- **B — 구조화 행 주입:** `_extract_disability_region_from_query()` + `_build_structured_context()` 구현
  - 수술명 또는 장해 부위가 감지되면 `[구조화 데이터 — 검색 결과 기반]` 블록을 LLM 프롬프트 앞에 삽입
  - C 방안 호환 예약 파라미터 `table_store=None` 포함
- pytest: 235 passed (신규 테스트 6건 추가)
- LLM eval(grade_accuracy, rate_accuracy)은 Ollama 연결 환경에서 별도 수행 필요
```

### 2-2. 섹션 4 (현재 데이터 상태) 수정

**파일 구조** 표의 `tests/` 행을 아래와 같이 수정:

```
| tests/                         # pytest 테스트 (235개, 전원 통과)
```

### 2-3. 섹션 5 (파일 구조) 추가

`src/rag/` 및 `src/llm/` 항목을 추가하라:

```
├── src/
│   ├── parser/
│   │   └── (기존과 동일)
│   ├── rag/
│   │   └── pipeline.py           # retrieve_hits, answer, 수술명/장해 구조화 컨텍스트
│   └── llm/
│       └── prompt.py             # SYSTEM_PROMPT, build_user_prompt
├── eval/
│   ├── ocr_qa.jsonl              # OCR 문서 40건 자동 평가 세트
│   ├── smoke_qa.jsonl            # 약관·심평원 스모크 평가 (15건)
│   └── smoke_qa_v2.jsonl        # 스모크 v2
```

### 2-4. 섹션 6 (실행 명령어) 추가

기존 명령어 목록 하단에 아래를 추가:

```bash
# OCR 자동 eval (LLM 포함, Ollama 실행 필요)
python scripts/eval.py --ocr

# retrieval-only eval (Ollama 불필요)
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py --ocr
```

### 2-5. 섹션 7 (잔여 과제) 전면 교체

기존 표를 아래로 교체:

| 항목 | 우선순위 | 상태 | 비고 |
|---|---|---|---|
| LLM eval 재실행 (grade/rate 측정) | 🔴 높음 | 대기 | Ollama 서버 연결 후 `python scripts/eval.py --ocr` |
| Streamlit 챗봇 수동 QA | 🔴 높음 | 대기 | `docs/59_STREAMLIT_OCR_QA_SCENARIO.md` 기준 |
| Approach C — 별도 DataFrame 저장 | 🟡 중간 | 설계 완료, 구현 미착수 | eval 결과 확인 후 결정 |
| unresolved 셀 133개 수동 검토 | 🟢 낮음 | 미착수 | 원본 이미지와 대조 필요 |
| 영구 실패 3페이지 (NO_TEXT) | 🟢 낮음 | 미착수 | 빈 페이지로 추정 |

---

## 3. Task 2 — Streamlit OCR QA 시나리오 문서 작성

**생성할 파일:** `docs/59_STREAMLIT_OCR_QA_SCENARIO.md`

이 문서는 실무가이드·상담사례집 기반 OCR 인덱스를 대상으로 Streamlit 챗봇을 수동 테스트하기 위한 가이드다. A+B 구조화 컨텍스트 주입이 정답 추출에 실제로 기여하는지 수동으로 확인하는 것이 목적이다.

### 3-1. 문서 헤더 및 테스트 원칙

파일 앞부분에 다음 내용을 포함:

```markdown
# Streamlit OCR QA 시나리오 — 실무가이드·상담사례집

> 작성일: 2026-05-13  
> 대상 인덱스: 실무가이드 (330p), 상담사례집 (351p)  
> 연관 기능: Approach A (SYSTEM_PROMPT), Approach B (구조화 행 주입)  
> 실행 환경: Ollama 실행 + `streamlit run src/ui/streamlit_app.py`

## 테스트 환경 설정

1. `ollama serve` 또는 Ollama 앱 실행
2. `streamlit run src/ui/streamlit_app.py`
3. http://localhost:8501 접속
4. 사이드바: Top-K=8, 온도=0.2 설정
5. 각 테스트마다 "대화 초기화" 클릭 후 시작

## 판정 기준

| 기호 | 의미 |
|------|------|
| ✅ 정답 | 정확한 수치·키워드 포함 |
| ⚠️ 부분 | 핵심 일부만 포함 (허용 조건 명시) |
| ❌ 오답 | 틀리거나 없음 |

## A+B 주입 확인 방법

`answer()` 로그 또는 Streamlit 출처 박스에서 `[구조화 데이터 — 검색 결과 기반]` 블록이 출력되는지 확인한다. 이 블록이 있으면 B 주입이 활성화된 것이다.
```

### 3-2. 시나리오 목록

아래 시나리오를 문서에 포함하라. 각 시나리오는 ID·질문·필수 포함 요소·판정 기준·B 주입 확인 여부 항목으로 구성한다.

---

**S01 — 수술종수: 충수절제술 1-5종 (기본 수치 조회)**

- 질문: `충수절제술의 1-5종 수술종수는 몇 종인가요?`
- 필수 포함: `2종` (또는 "2")
- 출처: 실무가이드 p.109 또는 p.110 근처
- B 주입 기대: `[구조화 데이터]` 블록에 `1-5종: 2` 포함
- 판정: 숫자 "2" 포함 시 ✅, 숫자 없이 설명만 시 ⚠️

**S02 — 수술종수: 충수절제술 1-3종 (종류 구분)**

- 질문: `충수절제술의 1-3종 수술종수는?`
- 필수 포함: `1종` (또는 "1")
- B 주입 기대: `1-3종: 1`
- 판정: 숫자 "1" 포함 시 ✅

**S03 — 수술종수: 신1-5종 확인**

- 질문: `충수절제술의 신1-5종 수술종수는 몇 종인가요?`
- 필수 포함: `2종` (또는 "2")
- 판정: 숫자 "2" 포함 시 ✅

**S04 — 수술종수: 다른 수술명 (회귀 방지)**

- 질문: `사지 관절에 가관절이 생겼을 때 수술종수는?`
- 필수 포함: 수술종수 수치 또는 해당 행 내용
- 출처: 실무가이드 p.64 근처 (ocr_011 기준)
- 판정: 수치 포함 시 ✅, 출처 페이지만 맞으면 ⚠️

**S05 — 장해 지급률: 한 팔의 손목 이상을 잃었을 때**

- 질문: `한 팔의 손목 이상을 잃었을 때 장해 지급률은 몇 퍼센트인가요?`
- 필수 포함: `60%`
- 출처: 실무가이드 p.255 또는 p.256 근처
- B 주입 기대: `[구조화 데이터]` 블록에 `지급률: 60%` 포함
- 판정: "60%" 포함 시 ✅

**S06 — 장해 지급률: 두 눈이 멀었을 때**

- 질문: `두 눈이 모두 멀었을 때 장해 지급률은?`
- 필수 포함: `100%`
- 출처: 실무가이드 p.235 또는 p.236 근처
- 판정: "100%" 포함 시 ✅

**S07 — 장해 지급률: 두 귀 청력 완전 상실**

- 질문: `두 귀의 청력을 완전히 잃었을 때 지급률은?`
- 필수 포함: `80%`
- 출처: 실무가이드 p.241 또는 p.242 근처
- 판정: "80%" 포함 시 ✅

**S08 — 장해 지급률: 척추 심한 운동장해**

- 질문: `척추에 심한 운동장해를 남긴 때의 장해 지급률은?`
- 필수 포함: `40%`
- 출처: 실무가이드 p.250 또는 p.251 근처
- 판정: "40%" 포함 시 ✅

**S09 — 장해 판단 기준 (서술형)**

- 질문: `골절부에 금속내고정물을 사용한 경우 기능장해 판정은 어떻게 하나요?`
- 필수 포함: 금속내고정물 관련 판정 기준 (제거 후 판정 등)
- 출처: 실무가이드 p.254–256 범위
- 판정: 관련 기준 언급 시 ✅, 단순 "확인되지 않습니다" 시 ❌

**S10 — 상담사례: 사례 조회 (텍스트 검색)**

- 질문: `보험 가입 후 1년 이내 암 진단을 받은 경우 보험금 지급이 거절될 수 있나요?`
- 필수 포함: 면책기간 또는 감액지급 관련 내용
- 출처: 상담사례집 내 해당 사례 페이지
- 판정: 면책 또는 감액 조건 포함 시 ✅

**S11 — 상담사례: 교통사고 후유장해 분쟁**

- 질문: `교통사고 후 후유장해 등급이 낮게 판정됐을 때 이의 제기 방법은?`
- 필수 포함: 이의 신청 또는 재심사 관련 내용
- 출처: 상담사례집 내 관련 사례
- 판정: 관련 절차 언급 시 ✅

**S12 — 없는 수술명 (경계 케이스)**

- 질문: `우주유영수술의 수술종수는?`
- 기대 동작: "확인되지 않습니다" 또는 "해당 수술명을 찾을 수 없습니다" 유사 표현
- 오답 기준: 엉뚱한 수치 반환 시 ❌
- 판정: 모르는 것을 명확히 답하면 ✅

**S13 — 수술 설명 조회 (종수 외 정보)**

- 질문: `충수절제술은 어떤 수술인가요?`
- 필수 포함: 충수 또는 맹장 절제 관련 설명
- B 주입 기대: 이 질문은 수술종수 질의가 아니므로 `[구조화 데이터]` 블록이 없거나 최소화됨
- 판정: 수술 개요 설명 포함 시 ✅

**S14 — 출처 검증: 실무가이드 페이지 인용**

- 질문: `충수절제술의 1-5종 수술종수는 몇 종인가요?` (S01과 동일)
- 추가 확인: Streamlit 출처 박스에 실무가이드 페이지 번호가 표시되는가
- 판정: 페이지 번호(예: p.109)가 출처로 표시되면 ✅

---

### 3-3. 평가 기록 시트

문서 하단에 아래 표를 포함:

```markdown
## 평가 기록 시트

| ID | 질문 요약 | 유형 | 기대 값 | B주입 | 판정 | 비고 |
|----|---------|------|---------|-------|------|------|
| S01 | 충수절제술 1-5종 | surgery_grade | 2종 | 예 | | |
| S02 | 충수절제술 1-3종 | surgery_grade | 1종 | 예 | | |
| S03 | 충수절제술 신1-5종 | surgery_grade | 2종 | 예 | | |
| S04 | 사지관절 가관절 수술종수 | surgery_grade | 수치 | 예 | | |
| S05 | 한 팔 손목 이상 지급률 | disability_rate | 60% | 예 | | |
| S06 | 두 눈 실명 지급률 | disability_rate | 100% | 예 | | |
| S07 | 두 귀 청력 상실 지급률 | disability_rate | 80% | 예 | | |
| S08 | 척추 운동장해 지급률 | disability_rate | 40% | 예 | | |
| S09 | 금속내고정물 판정 기준 | disability_criteria | 기준 설명 | 아니오 | | |
| S10 | 암보험 1년 이내 면책 | consultation | 면책/감액 | 아니오 | | |
| S11 | 교통사고 후유장해 이의 | consultation | 절차 설명 | 아니오 | | |
| S12 | 없는 수술명 | edge | 모름 명시 | 아니오 | | |
| S13 | 충수절제술 설명 | surgery_description | 개요 설명 | 부분 | | |
| S14 | 출처 페이지 표시 확인 | UX | 페이지 번호 | 예 | | |

**합계:** ✅ _/14 · ⚠️ _/14 · ❌ _/14

## 합격 기준

| 유형 | 기준 |
|------|------|
| surgery_grade (S01~S04) | 4건 중 3건 이상 ✅ |
| disability_rate (S05~S08) | 4건 중 3건 이상 ✅ |
| disability_criteria·consultation (S09~S11) | 3건 중 2건 이상 ✅ 또는 ⚠️ |
| edge (S12) | ❌ 없을 것 (최소 ⚠️) |
| UX (S14) | 출처 페이지 표시 확인 |
```

---

## 4. 제약 사항

- `docs/PROJECT_SUMMARY.md` 이외 소스 코드 수정 금지.
- 새 파일(`docs/59_STREAMLIT_OCR_QA_SCENARIO.md`)은 신규 생성. 기존 `docs/11_TEST_SCENARIO_GUIDE.md`는 수정하지 않는다.
- `docs/PROJECT_SUMMARY.md` 내 기존 섹션(1, 2, Phase 1~5)은 원문 유지. 추가·수정된 부분만 변경한다.

---

## 5. 검증

```bash
# PROJECT_SUMMARY.md 변경 확인
grep -n "Phase 6" docs/PROJECT_SUMMARY.md
grep -n "235 passed" docs/PROJECT_SUMMARY.md

# 신규 파일 존재 확인
ls docs/59_STREAMLIT_OCR_QA_SCENARIO.md

# 기존 테스트 회귀 없음 확인
pytest -q
```

---

## 6. 커밋

커밋 메시지: `Update PROJECT_SUMMARY and add Streamlit OCR QA scenario (spec #59)`  
푸시: `origin/master`
