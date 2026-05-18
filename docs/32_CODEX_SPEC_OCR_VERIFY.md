# Codex 명세 — OCR 검증 스크립트 구현

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)

---

## 배경

D6 (실무가이드, 330p)와 D7 (상담사례집, 351p)은 완전 이미지 스캔 PDF다.  
PyMuPDF 네이티브 추출 결과 텍스트 레이어가 **0자**이므로 OCR 없이는 인덱싱이 불가능하다.

이번 명세의 목표는 **두 가지 OCR 엔진을 실제 문서에 적용해 품질을 정량·정성으로 검증**하는 것이다.  
전체 파이프라인 통합은 이 검증 결과를 기반으로 **다음 명세(33번)** 에서 진행한다.

### 문서 현황

| 문서 | 파일명 | 페이지 | 1p 해상도 @150dpi | 파일 크기 |
|------|--------|--------|-----------------|----------|
| D6 실무가이드 | `Claim 실무종합가이드.pdf` | 330p | 1241×1754px (A4급) | 233MB |
| D7 상담사례집 | `소비자 상담 주요 사례집.pdf` | 351p | 877×1241px (A5급) | 146MB |

> **배포 정책:** D6는 `cloud_safe=False`이므로 OCR 완료 후에도 클라우드 인덱스에 포함하지 않는다.  
> D7은 `cloud_safe=True`이므로 품질 검증 통과 시 다음 통합 단계에서 클라우드 배포한다.

---

## OCR 엔진 비교 대상

### 엔진 A — pytesseract (Tesseract 5.x)

- 한국어 지원: tessdata kor 언어팩 사용
- 의존성: `pip install pytesseract pdf2image Pillow` + 시스템 tesseract 바이너리
- Mac: `brew install tesseract tesseract-lang`
- Linux: `apt-get install -y tesseract-ocr tesseract-ocr-kor poppler-utils`
- 특징: 빠르지만 복잡한 레이아웃에서 품질 저하 가능

### 엔진 B — EasyOCR

- 한국어 지원: 내장 (`lang_list=['ko']`)
- 의존성: `pip install easyocr` (모델 자동 다운로드 ~500MB)
- 특징: 시스템 의존성 없음, 복잡 레이아웃에서 tesseract보다 양호

---

## 구현 태스크

### M-ocr-1 — `scripts/ocr_verify.py` 작성

검증 스크립트를 새로 작성한다. 기존 파일을 수정하지 않는다.

#### 1-A. 실행 방법

```bash
# 두 엔진 모두 실행 (기본값)
python scripts/ocr_verify.py

# 특정 엔진만 실행
python scripts/ocr_verify.py --engine tesseract
python scripts/ocr_verify.py --engine easyocr

# 샘플 페이지 수 조정 (기본값 10)
python scripts/ocr_verify.py --pages 5
```

#### 1-B. 샘플 페이지 선택 방법

앞 10페이지가 아니라 **전체 구간에서 균등 분산** 방식으로 선택한다.  
문서 전반부·중반부·후반부의 품질 편차를 고르게 측정하기 위함이다.

```python
def sample_page_indices(total_pages: int, n: int = 10) -> list[int]:
    """총 페이지에서 n개를 균등 간격으로 선택한다 (0-indexed)."""
    if total_pages <= n:
        return list(range(total_pages))
    step = total_pages / n
    return [int(i * step) for i in range(n)]
```

예: 330p에서 10개 → [0, 33, 66, 99, 132, 165, 198, 231, 264, 297]

#### 1-C. 이미지 변환

**DPI 200**을 기본으로 사용한다. D7 해상도가 낮아 150dpi보다 200dpi에서 인식률이 향상된다.

```python
import fitz  # pymupdf

def page_to_image(pdf_path: str, page_no: int, dpi: int = 200):
    """PDF 페이지를 PIL Image로 변환한다."""
    doc = fitz.open(pdf_path)
    page = doc[page_no]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)  # 그레이스케일로 OCR 성능 향상
    doc.close()
    # PIL Image로 변환
    from PIL import Image
    import io
    img_bytes = pix.tobytes("png")
    return Image.open(io.BytesIO(img_bytes))
```

그레이스케일로 변환하면 컬러 잡음이 제거돼 OCR 인식률이 향상된다.

#### 1-D. 각 엔진 OCR 함수

```python
def ocr_tesseract(image) -> str:
    import pytesseract
    config = '--oem 3 --psm 3 -l kor+eng'
    return pytesseract.image_to_string(image, config=config)

def ocr_easyocr(image, reader) -> str:
    import numpy as np
    result = reader.readtext(np.array(image), detail=0, paragraph=True)
    return '\n'.join(result)
```

EasyOCR reader는 초기화 비용이 크므로 반드시 **문서 루프 바깥에서 한 번만 생성**한다:
```python
import easyocr
reader = easyocr.Reader(['ko', 'en'], gpu=False)
```

#### 1-E. 품질 지표 계산

```python
import re

KOREAN_RE = re.compile(r'[가-힣]')
NOISE_RE = re.compile(r'[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ.,·\-()]')

def quality_metrics(text: str) -> dict:
    """OCR 텍스트의 품질 지표를 계산한다."""
    total = len(text)
    if total == 0:
        return {"chars": 0, "korean_ratio": 0.0, "noise_ratio": 1.0, "grade": "FAIL"}
    korean = len(KOREAN_RE.findall(text))
    noise = len(NOISE_RE.findall(text))
    k_ratio = korean / total
    n_ratio = noise / total

    # 등급 판정 기준
    if k_ratio >= 0.35 and n_ratio <= 0.10 and total >= 200:
        grade = "PASS"
    elif k_ratio >= 0.20 and total >= 100:
        grade = "MARGINAL"
    else:
        grade = "FAIL"

    return {
        "chars": total,
        "korean_ratio": round(k_ratio, 3),
        "noise_ratio": round(n_ratio, 3),
        "grade": grade,
    }
```

**등급 기준:**
- `PASS`: 한글 비율 ≥ 35%, 노이즈 비율 ≤ 10%, 페이지당 ≥ 200자 — RAG 활용 가능
- `MARGINAL`: 한글 비율 ≥ 20%, 페이지당 ≥ 100자 — 조건부 활용 가능
- `FAIL`: 그 외 — RAG 활용 불가

#### 1-F. 출력 구조

```
reports/ocr_sample/
├── 실무가이드_tesseract_p000.txt    # 각 페이지 전체 텍스트
├── 실무가이드_tesseract_p033.txt
├── ...
├── 실무가이드_easyocr_p000.txt
├── ...
├── 상담사례집_tesseract_p000.txt
├── ...
├── 상담사례집_easyocr_p000.txt
├── ...
└── summary.txt                      # 종합 품질 리포트
```

`summary.txt` 형식:
```
=== OCR 검증 요약 ===
실행일: 2026-05-08
DPI: 200
샘플 페이지: 10개 (균등 분산)

--- 실무가이드 (D6, 330p) ---
[tesseract] 평균 chars: 412, 한글비율: 0.421, 노이즈: 0.043, PASS: 9/10
[easyocr  ] 평균 chars: 487, 한글비율: 0.503, 노이즈: 0.021, PASS: 10/10

--- 상담사례집 (D7, 351p) ---
[tesseract] 평균 chars: 198, 한글비율: 0.312, 노이즈: 0.089, PASS: 6/10
[easyocr  ] 평균 chars: 274, 한글비율: 0.448, 노이즈: 0.034, PASS: 9/10

=== 권장 엔진 ===
D6 실무가이드: easyocr (PASS 10/10)
D7 상담사례집: easyocr (PASS 9/10)
```

#### 1-G. 스크립트 전체 흐름

```python
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=['tesseract', 'easyocr', 'all'], default='all')
    parser.add_argument('--pages', type=int, default=10)
    parser.add_argument('--dpi', type=int, default=200)
    args = parser.parse_args()

    engines = ['tesseract', 'easyocr'] if args.engine == 'all' else [args.engine]

    # requires_ocr=True 소스만 대상
    from src import config
    targets = [s for s in config.PDF_SOURCES if s.requires_ocr and s.path.exists()]

    # EasyOCR reader 사전 초기화 (한 번만)
    reader = None
    if 'easyocr' in engines:
        import easyocr
        print("[ocr_verify] EasyOCR 초기화 중 (최초 실행 시 모델 다운로드 수분 소요)...")
        reader = easyocr.Reader(['ko', 'en'], gpu=False)

    output_dir = Path('reports/ocr_sample')
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results = {}  # {doc_short: {engine: [metrics_per_page]}}

    for source in targets:
        indices = sample_page_indices(total_pages, args.pages)
        all_results[source.doc_short] = {}

        for engine in engines:
            metrics_list = []
            for page_no in indices:
                img = page_to_image(str(source.path), page_no, args.dpi)
                text = ocr_tesseract(img) if engine == 'tesseract' else ocr_easyocr(img, reader)
                metrics = quality_metrics(text)
                metrics_list.append(metrics)

                out_file = output_dir / f"{source.doc_short}_{engine}_p{page_no:03d}.txt"
                out_file.write_text(text, encoding='utf-8')
                print(f"  [{engine}] p{page_no:03d}: chars={metrics['chars']}, "
                      f"kor={metrics['korean_ratio']:.2f}, grade={metrics['grade']}")

            all_results[source.doc_short][engine] = metrics_list

    write_summary(output_dir / 'summary.txt', all_results)
    print(f"\n[ocr_verify] 완료. 결과: {output_dir}/")
```

---

### M-ocr-2 — 의존성 추가 (`requirements.txt` 또는 `pyproject.toml`)

기존 의존성 파일에 OCR 관련 패키지를 **선택적 그룹**으로 추가한다.  
기존 `pip install -r requirements.txt` 동작에 영향을 주지 않는다.

```
# requirements-ocr.txt (새 파일로 분리)
pytesseract>=0.3.10
easyocr>=1.7.1
pdf2image>=1.17.0
Pillow>=10.0.0
```

> 시스템 의존성 안내를 `requirements-ocr.txt` 상단 주석으로 명시한다:
> ```
> # 시스템 패키지 필요:
> # Mac:   brew install tesseract tesseract-lang poppler
> # Linux: apt-get install -y tesseract-ocr tesseract-ocr-kor poppler-utils
> ```

---

### M-ocr-3 — 테스트 추가 (`tests/test_ocr_verify.py`)

핵심 유틸 함수에 대한 단위 테스트만 작성한다. 실제 OCR 엔진 호출은 느리므로 skip 처리한다.

```python
# tests/test_ocr_verify.py
import pytest
from scripts.ocr_verify import sample_page_indices, quality_metrics

def test_sample_page_indices_even_distribution():
    indices = sample_page_indices(330, 10)
    assert len(indices) == 10
    assert indices[0] == 0
    assert all(0 <= i < 330 for i in indices)
    # 균등 간격 확인
    gaps = [indices[i+1] - indices[i] for i in range(len(indices)-1)]
    assert max(gaps) - min(gaps) <= 1

def test_sample_page_indices_small_doc():
    assert sample_page_indices(5, 10) == [0, 1, 2, 3, 4]

def test_quality_metrics_pass():
    text = "안녕하세요. 이 문서는 보험 약관에 관한 내용입니다. 보상 기준과 지급 조건을 설명합니다." * 5
    m = quality_metrics(text)
    assert m["grade"] == "PASS"
    assert m["korean_ratio"] > 0.35

def test_quality_metrics_empty():
    m = quality_metrics("")
    assert m["grade"] == "FAIL"
    assert m["chars"] == 0
```

---

## 검증 체크리스트

Codex는 구현 완료 후 아래 항목을 직접 수행하고 리포트에 기재할 것.

- [ ] `pip install pytesseract pdf2image Pillow easyocr` 설치 성공 확인
- [ ] 시스템 tesseract 설치 및 한국어 언어팩 확인: `tesseract --list-langs | grep kor`
- [ ] `python scripts/ocr_verify.py --pages 5` 실행 성공 (시간 단축 목적)
- [ ] `reports/ocr_sample/summary.txt` 생성 확인
- [ ] D6/D7 각 엔진별 샘플 텍스트 파일 생성 확인 (`*.txt`)
- [ ] `pytest tests/test_ocr_verify.py -q` 전체 통과
- [ ] `pytest -q --ignore=tests/test_vector_store.py` 전체 통과 (기존 테스트 영향 없음)
- [ ] `summary.txt`의 등급 결과를 리포트에 그대로 붙여 넣을 것

---

## 다음 단계 예고 (이번 구현 범위 밖)

검증 결과에서 PASS 엔진이 확인되면 **명세 33번**에서 아래를 구현한다.

1. `src/parser/ocr_parser.py` — 선정 엔진 기반 `parse_pdf_ocr(source) → list[tuple[int, str]]`
2. `scripts/ingest.py` `--include-ocr` 경로에서 OCR 파서 호출
3. 청크 메타데이터 `source_method="ocr"` 설정 (필드는 이미 `EXTENDED_META_FIELDS`에 존재)
4. D7 (`cloud_safe=True`) 전체 인덱싱 후 클라우드 배포 (commit + push)
5. D6 (`cloud_safe=False`)는 로컬 전용 인덱스 생성

---

## 구현 우선순위

1. **M-ocr-1** (필수): `scripts/ocr_verify.py` 작성 및 실행
2. **M-ocr-2** (필수): `requirements-ocr.txt` 작성
3. **M-ocr-3** (필수): 단위 테스트 작성

구현 완료 후 `docs/33_OCR_VERIFY_REPORT.md`에:
- `summary.txt` 전문
- 각 엔진별 대표 샘플 텍스트 1개(D6, D7 각각)
- 권장 엔진 의견

을 포함한 결과 리포트를 작성할 것.
