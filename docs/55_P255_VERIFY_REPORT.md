# 55 P255 Verify & Cleanup Report

작성일: 2026-05-13  
대상 명세: `docs/55_CODEX_SPEC_P255_VERIFY_CLEANUP.md`

## 1) verify 스크립트 실행 결과

실행 명령:

```bash
python scripts/verify_p255_word_order.py
```

출력:

```text
=== p255 Word Order Verification ===
Checking page_no=254 (page_label=255):
  [WARN] text/p254_b00.txt — no known pattern hit; preview="제2장 장해분류표 해설"
  [WARN] text/p254_b01.txt — no known pattern hit; preview="장해분류표"
  [WARN] text/p254_b02.txt — no known pattern hit; preview="<장해판정기준> 1) 골절부에 금속내고정물 등을 사용하였기 때문에 그것이 기능장해의 원..."
  [WARN] text/p254_b03.txt — no known pattern hit; preview="제2장 장해분류표 해설 261"
Checking page_no=255 (page_label=256):
  [PASS] text/p255_b00.txt — GOOD ORDER CONFIRMED: 원칙적으로 각각

Stale text files (not in manifest):
  [STALE] text/p064_b01.txt — preview="수술분류표 71 수술분류표 해설 제1장"
  [STALE] text/p071_b01.txt — preview="족근관 Synd) (Tarsal Tunnel 발목내측부의 족근관의 내용물 증가로 후경골..."
  [STALE] text/p071_b02.txt — preview="78 claim실무 종합가이드"
  [STALE] text/p074_b02.txt — preview="근본수술(654) 만성부비|강염(ticket)| 15."
  [STALE] text/p081_b01.txt — preview="19.폐장() 이식수술[수용자(품입후)에 한함]"
  [STALE] text/p081_b02.txt — preview="88 claim실무 종합가이드"
  [STALE] text/p151_b01.txt — preview="77. 관혈적 안와내(←) 이물제거수술(베다)"
  [STALE] text/p151_b02.txt — preview="claim실무 종합가이드"
  [STALE] text/p255_b01.txt — preview="9) 기형을 "뼈에 때" 라 또는 남긴 함은 상완골 남아 요골과 척골에 변형이 정상에 ..."
  [STALE] text/p255_b02.txt — preview="1) 1상지(팔과 손가락)의 후유장해 지급률은 각각 원칙적으로 합산하되, 60% 한도로..." BAD ORDER DETECTED
  [STALE] text/p255_b03.txt — preview="Claim실무 종합가이드"
  [STALE] text/p279_b01.txt — preview="III. 표준약관 따른 장해관련 변경에 변경내용"
  [STALE] text/p279_b02.txt — preview="286 claim실무 종합가이도"

Summary:
  Registered blocks checked: 5
  PASS: 1 | WARN: 4 | FAIL: 0
  Stale files: 13
  Overall: PASS
```

## 2) 삭제 대상 파일 내용 (삭제 전 전문)

대상 파일: `data/extracted/실무가이드/text/p255_b02.txt`

```text
1) 1상지(팔과 손가락)의 후유장해 지급률은 각각 원칙적으로 합산하되, 60% 한도로 한다.
지급률은 2) 한 팔의 3대 관절중 1관절에 기능장해가 다른 생기고 1관절에 기능장해가 발생한 경우 지급률은 용하여 합산한다.
```

## 3) 삭제 완료 확인

실행:

```bash
rm data/extracted/실무가이드/text/p255_b02.txt
ls data/extracted/실무가이드/text/p255_b02.txt 2>/dev/null && echo "삭제 필요" || echo "이미 없음"
```

결과:

```text
이미 없음
```

## 4) pytest 결과

실행:

```bash
pytest -q
```

결과:

```text
225 passed, 5 warnings in 11.19s
```

## 5) 재처리 실행 여부

- 실행 여부: 미실행
- 이유: verify 결과가 `FAIL`이 아니라 `Overall: PASS`였음 (registered 파일 내 bad pattern 미검출).

## 6) 최종 판정

`PASS`
