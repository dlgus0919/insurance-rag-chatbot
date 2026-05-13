# 64_GRADE_ACCURACY_FIX 구현 보고서

작성일: 2026-05-13  
대상 명세: `docs/64_CODEX_SPEC_GRADE_ACCURACY_FIX.md`

## 1) 변경 파일

- `src/llm/prompt.py`
- `src/rag/pipeline.py`
- `scripts/eval.py`
- `tests/test_pipeline.py`

## 2) Task 1 — SYSTEM_PROMPT 수정

### 적용 내용
- rule 7 수술종수 지시를 모호한 "해당 종 컬럼"에서, **1-3종/1-5종/신1-5종 3개 컬럼 모두 출력**으로 변경.
- 질문이 특정 종만 묻는 경우에도 3개 값을 모두 포함하도록 명시.
- few-shot 예시 교체:
  - 삭제: `충수절제술(맹장 수술)` 예시, `한 팔의 손목 이상...60%` 예시
  - 추가: `전신성 복막염 수술`(2/3/2), `두 다리의 발목 이상...100%`

### 확인 결과
- `grep -n "한 팔의 손목\\|충수절제술" src/llm/prompt.py` 결과: 미검출(교체 완료)

## 3) Task 2 — 수술명 추출 버그 수정 + 패턴 보강

### 적용 내용
1. `_extract_surgery_name_from_query()` 판정 조건 완화
   - 기존: `"수술" in candidate or candidate.endswith("술")`
   - 변경: `"술" in candidate`
2. `_SURGERY_GRADE_COLUMN_PATTERN` 추가
   - `"X의 1-3종/1-5종/신1-5종"` 패턴에서도 수술명 추출
3. 괄호/기호/별칭 표기 정규화 매칭 추가
   - `_normalize_surgery_match_text()` 도입
   - `_build_structured_context()` / `_boost_surgery_name_table_rows()` 수술명 비교를 정규화 기반으로 변경
   - 예: `체외금속고정술(창외고정술)` ↔ `체외금속고정술 (= 창외고정술)` 매칭

### 단위 확인 출력
- `체외금속고정술(창외고정술)의 1-3종·1-5종·신1-5종 수술종수는?` → 추출 성공
- `충수절제술(맹장 수술)의 1-3종·1-5종·신1-5종은?` → 추출 성공
- `결장경하 종양수술의 수술종수는?` → 추출 성공

## 4) 진단 재확인(B 주입 시뮬레이션)

아래 4개 질의에서 `_build_structured_context(question, chunks)` 결과를 재확인함:

1. 체외금속고정술(창외고정술)
2. 결장경하 종양수술
3. 사지골 사지관절 가관절수술
4. 제대허니아수술

재확인 결과, 4개 모두 B 구조화 컨텍스트가 생성되며 수술종수 3개 컬럼 값이 포함됨.

예시 (`체외금속고정술(창외고정술)`):

```text
[구조화 데이터 — 검색 결과 기반]
수술명: 체외금속고정술 (= 창외고정술) | 1-3종: 1 | 1-5종: 2 | 신1-5종: 2
출처: 실무가이드 p.64
```

## 5) Task 3 — eval temperature 고정

### 적용 내용
- `scripts/eval.py`에서 `OLLAMA_TEMPERATURE` 환경변수를 읽도록 추가.
- 기본값은 `0`으로 설정(`float(os.getenv("OLLAMA_TEMPERATURE", "0"))`).
- `llm.generate(... temperature=eval_temperature ...)`로 전달.
- 이 변경은 eval 스크립트에만 적용되며 Streamlit 런타임 기본값은 유지됨.

## 6) 테스트 결과

- `pytest tests/test_pipeline.py -v` → **31 passed**
- `pytest -q` → **243 passed**

## 7) eval 실행 상태

사용자 요청에 따라 장시간 eval은 중단함.

- 중단된 실행:
  - `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false OLLAMA_TEMPERATURE=0 python scripts/eval.py --ocr`
- 중단 조치:
  - `pkill -f "python scripts/eval.py"`

현재 보고서에는 구현/단위/회귀(pytest)만 반영했고, 최종 지표(grade_accuracy/rate_accuracy/keyword_coverage)는 사용자 직접 실행 후 채워야 함.

## 8) 사용자 직접 실행 권장 명령어

```bash
cd "/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇"

# OCR eval (deterministic)
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
OLLAMA_TEMPERATURE=0 python scripts/eval.py --ocr

# smoke v1 회귀
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
python scripts/eval.py
```

