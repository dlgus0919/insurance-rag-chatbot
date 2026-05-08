# OCR 전처리 파이프라인 구현 보고서

## 작업 범위
- 명세: `docs/34_CODEX_SPEC_OCR_PIPELINE.md`
- 구현: M22 스캔 PDF OCR 전처리 파이프라인
- 대상: D6 `Claim 실무종합가이드.pdf`, D7 `소비자 상담 주요 사례집.pdf`
- 산출물: `data/extracted/<doc_short>/` 구조화 OCR 결과, `--include-ocr` 청킹 연결

## 구현 내역
- `src/parser/pdf_extractor.py`: PDF 임베딩 JPEG 직접 추출
- `src/parser/ocr_engine.py`: PP-Structure 실행, EasyOCR 폴백, 표 HTML/JSON 변환
- `src/parser/ocr_postprocess.py`: 한국어 OCR 후처리
- `scripts/ocr_extract.py`: OCR 추출 오케스트레이터
- `src/parser/ocr_chunker.py`: 추출물 기반 RAG 청크 생성
- `scripts/ingest.py`: `--include-ocr`일 때 OCR 추출물 청킹 경로 연결
- `requirements-ocr.txt`: `paddlepaddle`, `paddleocr`, `beautifulsoup4`, `lxml` 추가

## D6 60~70p 샘플 추출 결과
실행:

```bash
python scripts/ocr_extract.py --doc 실무가이드 --pages 60-70 --fallback-threshold 0.5
```

결과:
- 처리 페이지: 11p
- 엔진: PP-Structure 11/11, EasyOCR 폴백 0/11
- 블록: text 13, table 10, figure 6
- p066: table 2개, text 1개 감지

PP-Structure 표 셀 구조 판정:
- p066 `p066_t00.json`: headers 5개, rows 15개, `cell_bbox` 86개
- p066 `p066_t01.json`: headers 5개, rows 1개, `cell_bbox` 30개
- 결론: 표 영역과 셀 bbox는 감지했지만, 한글 헤더/셀 텍스트는 올바르게 인식하지 못했다.
- 원인: PaddleOCR 2.10.0의 PP-Structure layout 모델이 `lang="korean"`을 지원하지 않아 내부적으로 `ch` 모델로 폴백했다.
- 예: 기대 헤더 `수술종수 / 수술명 / 수술해설` 대신 `['舍', 'col_2', 'col_3', 'col_4', 'col_5']`로 추출됨.

## Content Type 통계
추출 블록 기준:

| 문서 | 처리 페이지 | text | table | figure |
|---|---:|---:|---:|---:|
| D6 실무가이드 | 11 | 13 (44.8%) | 10 (34.5%) | 6 (20.7%) |
| D7 상담사례집 | 5 | 15 (88.2%) | 0 (0.0%) | 2 (11.8%) |
| 합계 | 16 | 28 (60.9%) | 10 (21.7%) | 8 (17.4%) |

RAG 청크 기준:

| content_type | 청크 수 | 비율 |
|---|---:|---:|
| text | 28 | 73.7% |
| table | 10 | 26.3% |
| figure | 0 | 0.0% |

figure는 이번 단계에서 빈 캡션 파일만 생성하므로 검색 청크로 만들지 않았다. 캡션 생성은 후속 Vision 명세 범위다.

## 엔진/폴백 비율
처리 페이지 기준:

| 엔진 | 페이지 수 | 비율 |
|---|---:|---:|
| PP-Structure | 16 | 100.0% |
| EasyOCR fallback | 0 | 0.0% |

주의: PP-Structure 자체는 `lang="korean"` 초기화를 거부했고, 구현에서는 `korean -> ch` 순서로 초기화 폴백한다. 위 비율의 PP-Structure는 `ch` layout/table 모델 기반이다.

## 한국어 후처리 예시
| 구분 | 텍스트 |
|---|---|
| 전 | `반월판 연골올 제거해내논 수술올 말하다` |
| 후 | `반월판 연골을 제거해내는 수술을 말하다` |
| 전 | `피보험자 서명틀 대필` |
| 후 | `피보험자 서명을 대필` |

## 통합 검증
실행:

```bash
python scripts/ocr_extract.py --doc 실무가이드 --pages 60-70 --fallback-threshold 0.5
python scripts/ocr_extract.py --doc 상담사례집 --pages 0-4 --fallback-threshold 0.5
python scripts/ingest.py --include-ocr --stage chunks
pytest -q
```

결과:
- OCR 청크 생성: D6 23개, D7 15개
- `python scripts/ingest.py --include-ocr --stage chunks`: 통과
- `pytest -q`: 157 passed, 5 warnings

## 보안 및 GitHub 반영
- `data/extracted/` OCR 추출물은 `.gitignore` 정책에 따라 GitHub에 커밋하지 않는다.
- `data/processed/chunks.jsonl`은 검증 후 원복했다.
- 최종 응답 기준, 본 보고서 포함 구현 커밋을 `origin/master`로 푸시 완료.
