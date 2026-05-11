# 49 전체 OCR 스모크 재실행 보고서

## 실행 일시

- 2026-05-11

## 실행 범위

명세 smoke 기준 2페이지와 고정 seed `20260511`로 추출한 랜덤 8페이지를 합쳐 총 10페이지를 실행했다.

- 실무가이드: `64,65,74,151,255,279`
- 상담사례집: `65,189,211,273`

## 실행 명령 및 결과

### 실무가이드

```bash
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64,65,74,151,255,279 --yes
```

결과:

```text
SUCCESS: 6/6 | SKIPPED: 0/6 | FAILED: 0/6 | 소요: 4m 5s
```

페이지별 결과:

- p064: `SUCCESS` 3블록
- p065: `SUCCESS` 2블록
- p074: `SUCCESS` 4블록
- p151: `SUCCESS` 5블록
- p255: `SUCCESS` 4블록
- p279: `SUCCESS` 4블록

### 상담사례집

```bash
python scripts/run_full_ocr.py --doc 상담사례집 --pages 65,189,211,273 --yes
```

초회 실행에서 p065가 `Connection reset by peer`로 실패했고, 나머지 3페이지는 성공했다.

```text
SUCCESS: 3/4 | SKIPPED: 0/4 | FAILED: 1/4 | 소요: 2m 11s
```

p065만 재시도했다.

```bash
python scripts/run_full_ocr.py --doc 상담사례집 --pages 65 --yes
```

재시도 결과:

```text
SUCCESS: 1/1 | SKIPPED: 0/1 | FAILED: 0/1 | 소요: 42.0초
```

최종적으로 10페이지 모두 `engine="true_hybrid"`로 저장됐다.

## manifest 확인

- 실무가이드 p064: `true_hybrid`, 3블록 (`text`, `table`, `text`)
- 실무가이드 p065: `true_hybrid`, 2블록 (`text`, `table`)
- 실무가이드 p074: `true_hybrid`, 4블록 (`text`, `text`, `text`, `table`)
- 실무가이드 p151: `true_hybrid`, 5블록 (`text`, `text`, `table`, `table`, `text`)
- 실무가이드 p255: `true_hybrid`, 4블록 (`text`, `text`, `text`, `text`)
- 실무가이드 p279: `true_hybrid`, 4블록 (`text`, `text`, `table`, `text`)
- 상담사례집 p065: `true_hybrid`, 3블록 (`text`, `text`, `text`)
- 상담사례집 p189: `true_hybrid`, 9블록 (`text`, `text`, `table`, `text`, `text`, `text`, `text`, `text`, `table`)
- 상담사례집 p211: `true_hybrid`, 9블록 (`text` 9개)
- 상담사례집 p273: `true_hybrid`, 7블록 (`text` 7개)

## HTML 대조 산출물

원본 PDF 페이지 이미지와 `data/extracted` OCR 결과를 함께 볼 수 있는 HTML을 생성했다.

```text
reports/full_ocr_smoke_compare.html
```

검증:

- 파일 크기: `1,476,150 bytes`
- 포함 페이지 섹션: `10`
- `실무가이드 p064`, `상담사례집 p273` 포함 확인

## Chunker 연동 확인

스모크 대상 페이지를 포함하는 `data/extracted`를 `chunk_from_extracted()`로 읽어 확인했다.

```text
실무가이드: source_method 샘플 ['ocr_true_hybrid']
상담사례집: source_method 샘플 ['ocr_true_hybrid']
```

## Git 처리

- `data/extracted/` OCR 결과와 `reports/full_ocr_smoke_compare.html`은 검토용 로컬 산출물이므로 커밋하지 않는다.
- 본 실행 보고서만 커밋한다.

## 잔여 블로커

None
