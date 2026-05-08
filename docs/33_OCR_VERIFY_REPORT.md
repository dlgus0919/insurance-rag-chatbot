# OCR 검증 도구 구현 보고서

## 작업 범위
- 명세: `docs/32_CODEX_SPEC_OCR_VERIFY.md`
- 범위: D6 `Claim 실무종합가이드.pdf`, D7 `소비자 상담 주요 사례집.pdf`의 OCR 샘플 품질 검증
- 제외: OCR 결과의 RAG 인덱싱, OCR 본격 파이프라인, GraphDB 연동, 약관 비교

## 구현 내역
- `scripts/ocr_verify.py` 추가
  - `requires_ocr=True` 원본 PDF만 대상으로 샘플 페이지를 균등 선택한다.
  - Tesseract와 EasyOCR 엔진을 선택 실행할 수 있다.
  - 페이지별 OCR 텍스트는 `reports/ocr_sample/`에 저장하고, 요약은 `summary.txt`로 생성한다.
  - 엔진 미설치/언어팩 누락 시 전체 실행을 중단하지 않고 요약에 오류를 남긴다.
- `requirements-ocr.txt` 추가
  - OCR 검증용 선택 의존성을 운영 앱 의존성과 분리했다.
- `tests/test_ocr_verify.py` 추가
  - 샘플 페이지 선택, 품질 지표, 엔진 오류 요약 기록을 검증한다.
- `.gitignore` 업데이트
  - OCR 산출물 `reports/ocr_sample/`은 GitHub에 올라가지 않도록 제외했다.

## 실행 결과
실행 명령:

```bash
python scripts/ocr_verify.py --pages 5 --dpi 150
```

요약:

```text
=== OCR 검증 요약 ===
실행일: 2026-05-08 09:52:52
DPI: 150
샘플 페이지: 5개 (균등 분산)

--- 실무가이드 (D6) (330p) ---
[tesseract] 평균 chars: 0.0, 한글비율: 0.0, 노이즈: 0.0, PASS: 0/0, MARGINAL: 0/0, FAIL: 0/0, 소요: 0초
  ERROR: RuntimeError: tesseract 바이너리가 PATH에 없습니다. requirements-ocr.txt의 시스템 패키지 안내를 확인하세요.
[easyocr  ] 평균 chars: 875.6, 한글비율: 0.599, 노이즈: 0.007, PASS: 4/5, MARGINAL: 0/5, FAIL: 1/5, 소요: 21.9초

--- 상담사례집 (D7) (351p) ---
[tesseract] 평균 chars: 0.0, 한글비율: 0.0, 노이즈: 0.0, PASS: 0/0, MARGINAL: 0/0, FAIL: 0/0, 소요: 0초
  ERROR: RuntimeError: tesseract 바이너리가 PATH에 없습니다. requirements-ocr.txt의 시스템 패키지 안내를 확인하세요.
[easyocr  ] 평균 chars: 625.8, 한글비율: 0.638, 노이즈: 0.006, PASS: 4/5, MARGINAL: 1/5, FAIL: 0/5, 소요: 11.3초

=== 권장 엔진 ===
실무가이드 (D6): easyocr (PASS 4/5, MARGINAL 0/5)
상담사례집 (D7): easyocr (PASS 4/5, MARGINAL 1/5)
```

대표 샘플 텍스트(짧은 품질 확인용 발췌):
- D6: `수술분류표 해설`, `반월판연골 봉합술`, `골연장술`
- D7: `자필서명 위반`, `사망담보 있는 피보험자 서명`, `검토 의견`

전체 OCR 텍스트 파일은 보안상 GitHub에 커밋하지 않고 로컬 `reports/ocr_sample/`에만 생성했다.

## 엔진 판단
- 현재 로컬 환경에서는 Tesseract 바이너리 설치가 완료되지 않아 품질 비교 수치를 만들 수 없었다.
- EasyOCR은 최초 모델 다운로드 후 D6/D7 모두 본문 페이지 기준 PASS 비율이 높아, 다음 단계의 OCR 파이프라인 후보 엔진으로 우선 권장한다.
- Tesseract를 재검증하려면 시스템 패키지 설치 후 `tesseract --list-langs`에서 `kor`가 표시되어야 한다.

## 검증
- `pytest -q tests/test_ocr_verify.py`: 통과
- `python scripts/ocr_verify.py --engine tesseract --pages 1 --dpi 150 --output-dir /tmp/ocr_tesseract_check`: 오류 요약 처리 확인
- `python scripts/ocr_verify.py --pages 5 --dpi 150`: EasyOCR 샘플 5쪽 검증 및 `reports/ocr_sample/summary.txt` 생성 확인

## GitHub 반영
- 구현 완료 후 본 리포트 포함 커밋을 `origin/master`로 푸시했다.
