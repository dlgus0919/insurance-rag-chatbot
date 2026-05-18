# Codex Spec #55 — p255 단어 순서 검증 및 스테일 파일 정리

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **우선순위:** 🟡 중간  
> **예상 소요:** 30분 이내

---

## 1. 목표

spec #51(`f1b39ce`) 적용 이후 `data/extracted/실무가이드/` 안에 두 가지 잔여 문제가 남아 있다.

1. **p255 검증 미완료**: spec #51 보고서에서 `p255 True Hybrid: "원칙적으로 각각" 정상` 으로 표시되었으나, 같은 페이지(page_label=255, page_no=254)의 텍스트 블록 전체가 실제 올바른 단어 순서로 저장되어 있는지 자동 검증한 적이 없다.
2. **스테일 파일 잔존**: 이전 OCR 실행에서 생성된 `text/p255_b02.txt`가 현재 manifest에 등록되지 않은 채로 디스크에 남아 있다. 이 파일은 `"각각 원칙적으로 합산하되"` 라는 **잘못된 단어 순서**를 담고 있어 향후 수동 검토 시 혼란을 일으킬 수 있다.

---

## 2. 배경

| 항목 | 내용 |
|---|---|
| 수정 커밋 | `f1b39ce` (Fix OCR field order, 2026-05-11 KST 17:23) |
| p254 파일 mtime | 2026-05-11 UTC 12:34 = **KST 21:34** (커밋보다 4시간 이후) |
| 판단 | p254 블록(page_label=255)은 spec #51 적용 이후 재기록된 파일 |
| 문제 파일 | `text/p255_b02.txt` — manifest에 없음, 구형 단어 순서 오류 포함 |

현재 manifest 기준으로 page_no=254(page_label=255)는 다음 5개 블록을 가진다:

```
text/p254_b00.txt  text/p254_b01.txt  text/p254_b02.txt  text/p254_b03.txt
tables/p254_t00.txt
```

page_no=255(page_label=256)는 `text/p255_b00.txt` 1개 블록만 가진다.

---

## 3. 대상 파일

| 파일 | 변경 유형 |
|---|---|
| `scripts/verify_p255_word_order.py` | **신규 생성** — 검증 스크립트 |
| `data/extracted/실무가이드/text/p255_b02.txt` | **삭제** — manifest 미등록 스테일 파일 |
| `docs/55_P255_VERIFY_REPORT.md` | **신규 생성** — 검증 보고서 |

변경하지 않을 파일:

- `src/` 전체
- `data/extracted/실무가이드/manifest.json`
- `scripts/run_full_ocr.py`, `scripts/ingest.py`
- `eval/` 전체

---

## 4. 상세 요구사항

### 4-1. 검증 스크립트 (`scripts/verify_p255_word_order.py`)

다음 검사를 순서대로 실행한다.

```python
"""p255(page_label=255) 단어 순서 검증 스크립트.

검사 항목:
  1. manifest 기준 p254 블록 파일 목록 확인
  2. 각 텍스트 블록에서 단어 순서 오류 패턴 탐지
  3. 스테일 파일(manifest 미등록) 목록 출력
  4. 결과 요약 출력 (PASS / WARN / FAIL)
"""
```

**단어 순서 오류 패턴 탐지 방법:**

spec #51이 고쳤던 버그는 `_fields_to_lines()` 내부에서 Y-그룹 안의 단어를 center_X로 재정렬하여 순서가 뒤집히는 것이었다. 결과물 텍스트에서 이 버그의 흔적은 주로 두 단어가 의미적으로 뒤집혀 등장할 때 나타난다.

스크립트에서는 다음 known-bad 패턴을 직접 탐지한다:

```python
KNOWN_BAD_PATTERNS = [
    "각각 원칙적으로",   # 정상: "원칙적으로 각각"
    "생기고 다른",       # 정상: "다른 생기고" → 실제 문장 확인 필요
]

KNOWN_GOOD_PATTERNS = [
    "원칙적으로 각각",
]
```

탐지 결과:
- `KNOWN_BAD_PATTERNS` 중 하나라도 발견 → `FAIL`
- `KNOWN_GOOD_PATTERNS` 모두 확인 + bad 없음 → `PASS`
- 패턴 불일치(해당 텍스트 없음) → `WARN` (해당 페이지에 해당 문장 없을 수 있음)

**스테일 파일 탐지 방법:**

```python
# manifest에 등록된 file 경로 집합 수집
registered = {block["file"] for page in manifest["pages"] for block in page["blocks"]}

# data/extracted/실무가이드/text/ 디렉토리 실제 파일 목록과 비교
stale = [f for f in text_dir.glob("*.txt") if f"text/{f.name}" not in registered]
```

**출력 형식:**

```
=== p255 Word Order Verification ===
Checking page_no=254 (page_label=255):
  [OK] text/p254_b00.txt — 제2장 장해분류표 해설 (12 chars)
  [OK] text/p254_b01.txt — 장해분류표 (6 chars)
  [PASS] text/p254_b02.txt — "원칙적으로 각각" 패턴: GOOD ORDER CONFIRMED
  [OK] text/p254_b03.txt — 제2장 장해분류표 해설 261 (18 chars)

Checking page_no=255 (page_label=256):
  [PASS] text/p255_b00.txt — "원칙적으로 각각" 패턴: GOOD ORDER CONFIRMED

Stale files (not in manifest):
  [STALE] text/p255_b02.txt — "각각 원칙적으로" BAD ORDER DETECTED

Summary:
  Registered blocks checked: 5
  PASS: 2 | WARN: 2 | FAIL: 0
  Stale files: 1
  Overall: PASS (no bad patterns in registered files)
```

### 4-2. 스테일 파일 삭제

```bash
rm data/extracted/실무가이드/text/p255_b02.txt
```

삭제 전 파일 내용을 보고서에 기록한다.

### 4-3. 재처리 조건

검증 결과 `FAIL`(registered 파일에서 bad pattern 발견)인 경우에만:

```bash
python scripts/run_full_ocr.py --doc 실무가이드 --pages 255,256 --force --yes
python scripts/ingest.py --include-ocr --stage all
```

현재 분석으로는 FAIL이 아닐 것으로 예상되므로, Codex는 스크립트 실행 결과만 보고서에 기록하고 재처리는 생략한다.

---

## 5. 검증 명령어

```bash
# 1. 검증 스크립트 실행
python scripts/verify_p255_word_order.py

# 2. 스테일 파일 삭제 확인
ls data/extracted/실무가이드/text/p255_b02.txt 2>/dev/null && echo "삭제 필요" || echo "이미 없음"

# 3. pytest 회귀 확인
pytest -q
```

---

## 6. 중단 조건

- `FAIL` 결과(registered 파일에 bad pattern 존재) → 즉시 보고, 재처리 명령 실행 전 Claude에 확인 요청
- `pytest -q` 실패 → 원인 파악 후 보고

---

## 7. 출력 요구사항

`docs/55_P255_VERIFY_REPORT.md` 에 다음을 포함한다:

1. `python scripts/verify_p255_word_order.py` 전체 출력
2. 스테일 파일 삭제 전 내용 전문
3. 삭제 완료 확인
4. `pytest -q` 결과
5. 재처리 실행 여부 및 이유
6. 종합 판정: `PASS` / `WARN` / `FAIL`

커밋 메시지: `Verify p255 word order and remove stale OCR files`  
푸시: `origin/master`
