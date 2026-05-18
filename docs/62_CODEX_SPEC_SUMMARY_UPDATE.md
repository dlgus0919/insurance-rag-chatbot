# Codex Spec #62 — PROJECT_SUMMARY.md 갱신 (#59–#60 반영)

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **성격:** 문서 작업 (코드 수정 없음)  
> **우선순위:** 🟢 낮음

---

## 1. 배경

`docs/PROJECT_SUMMARY.md`는 spec #59 Codex 작업 시 #58까지만 반영됐다.  
이후 완료된 두 명세가 누락됐다:

- **spec #59** — PROJECT_SUMMARY 갱신 + Streamlit OCR QA 시나리오 문서 작성
- **spec #60** — Parquet 테이블 인덱스 구축 + TableStore + pipeline C hook 연결

---

## 2. 수정 대상 파일

`docs/PROJECT_SUMMARY.md`

---

## 3. 수정 내용

### 3-1. 섹션 3 (OCR 파이프라인 진화 이력) — Phase 6 하단에 추가

기존 Phase 6 블록 하단, Phase 7 시작 전에 아래 내용을 삽입한다.

```markdown
### Phase 7 — 인덱스 고도화 + 문서화 (명세 #59–60)

**문서화** (명세 #59)
- `docs/PROJECT_SUMMARY.md` 갱신 (#54–#58 반영)
- `docs/59_STREAMLIT_OCR_QA_SCENARIO.md` 신규 작성: 실무가이드·상담사례집 기반 수동 QA 시나리오 14건 (S01~S14)

**Parquet 테이블 인덱스** (명세 #60)
- `scripts/build_table_index.py` 신규 작성: OCR 표 JSON → Parquet 변환
- 생성물:
  - `data/index/surgery_grades.parquet` — 수술종수표 **2,408행** (p33~p175, 192개 파일)
  - `data/index/disability_rates.parquet` — 장해분류표 **100행** (신체부위별 13개 파일)
- `src/rag/table_store.py` 신규: `TableStore` 직접 조회 인터페이스 (`lookup_surgery_grade`, `lookup_disability_rate`)
- `src/rag/pipeline.py`: C hook 활성화 — Parquet 조회 성공 시 `[구조화 데이터 — 직접 조회 (C)]` 블록 우선 주입, 실패 시 B(table_json) fallback
- pytest: **240 passed** (신규 테스트 5건 추가)

**핵심 조회 검증 완료:**

| 질의 | 결과 | 출처 |
|---|---|---|
| 충수절제술 1-5종 | 2종 | 실무가이드 p.109 |
| 두 눈이 멀었을 때 지급률 | 100% | 실무가이드 p.236 |
| 한 팔 손목 이상 지급률 | 60% | 실무가이드 p.255 |
| 두 귀 청력 상실 지급률 | 80% | 실무가이드 p.242 |
```

### 3-2. 섹션 4 (현재 데이터 상태) — 파일 구조 추가

기존 표 하단 `Vision/Numeric 처리` 표 다음에 아래를 삽입한다.

```markdown
**Parquet 인덱스 (`data/index/`)**

| 파일 | 행 수 | 내용 |
|---|---|---|
| `surgery_grades.parquet` | 2,408 | 수술종수표 전체 (p33~p175, 신체부위별 라벨 포함) |
| `disability_rates.parquet` | 100 | 장해분류표 전체 (신체부위 15종, 지급률 정규화 완료) |
```

### 3-3. 섹션 5 (파일 구조) — 신규 경로 추가

기존 파일 트리에 아래 항목을 추가한다.

```
├── data/
│   ├── extracted/       (기존)
│   ├── index/
│   │   ├── surgery_grades.parquet   # 수술종수표 Parquet
│   │   └── disability_rates.parquet # 장해분류표 Parquet
│   └── processed/       (기존)
├── src/
│   ├── parser/          (기존)
│   ├── rag/
│   │   ├── pipeline.py              # (기존, C hook 연결 완료)
│   │   └── table_store.py           # 신규: Parquet 직접 조회
```

### 3-4. 섹션 6 (실행 명령어) — 인덱스 빌드 명령 추가

기존 명령어 목록 하단에 추가:

```bash
# Parquet 테이블 인덱스 재생성 (OCR 데이터 변경 시)
python scripts/build_table_index.py
```

### 3-5. 섹션 7 (잔여 과제) — 항목 업데이트

기존 표를 아래로 교체:

| 항목 | 우선순위 | 상태 | 비고 |
|---|---|---|---|
| A+B+C LLM eval 결과 확인 (grade/rate 측정) | 🔴 높음 | 진행 중 | `logs/eval_ocr_abc_*.log` |
| smoke_v2 recall 개선 (약관 청크 재분할) | 🟡 중간 | 명세 작성 완료 (#61) | eval 완료 후 착수 |
| Streamlit 챗봇 수동 QA | 🟡 중간 | 시나리오 준비 완료 | `docs/59_STREAMLIT_OCR_QA_SCENARIO.md` 기준 |
| Task 2 (보험금 자동 계산) 기획 | 🟡 중간 | 미착수 | Parquet 데이터 활용 |
| unresolved 셀 133개 수동 검토 | 🟢 낮음 | 미착수 | 원본 이미지와 대조 필요 |
| 영구 실패 3페이지 (NO_TEXT) | 🟢 낮음 | 미착수 | 빈 페이지로 추정 |

---

## 4. 제약

- 섹션 1(프로젝트 개요), 섹션 2(기술 스택), Phase 1~6 내용은 수정하지 않는다.
- 코드 파일 수정 없음.

---

## 5. 검증

```bash
grep -n "Phase 7\|2408\|240 passed\|surgery_grades" docs/PROJECT_SUMMARY.md
```

위 키워드가 모두 검색되면 완료.

---

## 6. 커밋

커밋 메시지: `Update PROJECT_SUMMARY with spec #59-#60 (Parquet index, QA scenario)`  
푸시: `origin/master`
