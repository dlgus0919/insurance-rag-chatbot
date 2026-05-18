# Codex 명세 — M22 스캔 PDF OCR 전처리 파이프라인 구현

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)  
로드맵 참조: `docs/20_INTEGRATION_ROADMAP.md` Phase C M22–M23

---

## 배경 및 분석

### 문서 물리 구조 확인

| 문서 | 페이지 | 내장 이미지 해상도 | 색공간 | 포맷 | 유효 DPI |
|------|--------|-----------------|--------|------|---------|
| D6 실무가이드 | 330p | 2360×3316 px | 그레이스케일 | JPEG | ~279 dpi |
| D7 상담사례집 | 351p | 1720×2457 px | 그레이스케일 | JPEG | ~294 dpi |

두 문서 모두 **PDF 페이지 = 단일 JPEG 이미지**이다. 텍스트 레이어 0자.  
PyMuPDF `doc.extract_image(xref)`로 원본 JPEG를 바로 추출하면 re-render 손실 없이 최고 화질을 얻을 수 있다.

### D6 콘텐츠 유형 분석

D6 (Claim 실무종합가이드)는 단순 텍스트 문서가 아니다. 로드맵이 예고한 복합 콘텐츠가 실제로 존재한다:

| 콘텐츠 유형 | 예시 | OCR 난이도 |
|------------|------|-----------|
| 본문 설명 텍스트 | 수술 해설 단락 | 보통 |
| 수술/장해 분류표 | 수술종수 × 수술명 × 수술해설 3열 표 | **어려움** |
| 수술 색인 표 | 수술명+페이지 번호 다단 인덱스 | **어려움** |
| 해부학적 도식 | 신체 부위 도식 + 한글/한자 레이블 | **매우 어려움** |
| 한자 병기 | "骨端 骨端板(골단판)" 형식 | 보통 (한자 모델 필요) |
| 반복 머리글/바닥글 | "제○장 수술분류표 해설 N" | 노이즈 제거 필요 |

EasyOCR은 "모든 텍스트를 읽기 순서대로 나열"하는 방식이라 표 구조가 붕괴됐다.  
**PP-Structure는 레이아웃 인식 → 영역 분류 → 영역별 처리** 순서로 표 셀 구조를 보존한다.

---

## OCR 방법론 결정

### 비교 검토

| 항목 | EasyOCR | PaddleOCR + PP-Structure | CLOVA OCR | GPT-4o Vision |
|------|---------|--------------------------|-----------|--------------|
| 레이아웃 분석 | ❌ (없음) | ✅ (title/text/table/figure) | ✅ | ✅ |
| 표 구조 보존 | ❌ 붕괴 | ✅ HTML 셀 추출 | ✅ | ✅ |
| 한국어 품질 | 양호 | 양호 | 최우수 | 최우수 |
| 한자 병기 | 가능(ko+ch) | ✅ 기본 지원 | ✅ | ✅ |
| 로컬 실행 | ✅ 무료 | ✅ 무료 | ❌ API (월 1만건 무료) | ❌ API (유료) |
| 설치 크기 | ~500MB | ~1.5GB | 없음 | 없음 |
| 이번 범위 | 검증 완료 | **1차 채택** | 2차 폴백 | 3차 선택 |

### 최종 결정: PaddleOCR + PP-Structure (1차) + EasyOCR 폴백 (2차)

**1차 (PP-Structure):**  
- 레이아웃 분석 → text/table/figure 영역 분리  
- 표 영역: 셀 구조를 HTML로 추출 → JSON + 직렬화 텍스트로 이중 저장  
- 본문/제목 영역: PP-OCR 한국어 모델로 텍스트 인식 (한자 병기 포함)  
- 이미지/도식 영역: PNG 추출 + 캡션 플레이스홀더  

**2차 폴백 (EasyOCR):**  
- PP-Structure 신뢰도가 임계값 미만인 페이지에 적용  
- 또는 텍스트 단락만 있는 단순 페이지

**3차 선택 (GPT-4o Vision) — 이번 구현 범위 외:**  
- 해부학 도식 캡션 자동 생성 (별도 명세 35번)

---

## 구현 태스크

### M-ocr-pipe-1 — 의존성 추가

`requirements-ocr.txt`에 PP-Structure 관련 패키지를 추가한다.

```text
# requirements-ocr.txt에 추가
paddlepaddle>=2.6.0
paddleocr>=2.8.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
```

> 설치 확인:
> ```bash
> pip install paddlepaddle paddleocr beautifulsoup4 lxml --break-system-packages
> python -c "from paddleocr import PPStructure; print('OK')"
> ```

---

### M-ocr-pipe-2 — `src/parser/pdf_extractor.py` 신설

PDF에서 임베딩된 JPEG를 직접 추출하는 유틸리티 모듈이다.  
기존 `src/parser/pdf_parser.py`를 수정하지 않고 별도 파일로 분리한다.

```python
"""PDF 임베딩 이미지 직접 추출 유틸리티."""
from __future__ import annotations

from pathlib import Path
import io
from PIL import Image
import fitz  # pymupdf


def extract_page_image(pdf_path: str | Path, page_no: int) -> Image.Image:
    """
    PDF 페이지에서 임베딩된 이미지를 직접 추출한다.
    re-render 없이 원본 JPEG 품질을 유지한다.
    이미지가 없는 페이지는 300dpi로 fallback 렌더링한다.
    """
    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_no]
        images = page.get_images(full=True)
        if images:
            xref = images[0][0]
            raw = doc.extract_image(xref)
            img = Image.open(io.BytesIO(raw["image"]))
            img.load()
            # 그레이스케일 보장 (OCR 성능 향상)
            if img.mode not in ("L", "RGB"):
                img = img.convert("L")
            return img
        # 이미지 없는 페이지: 300dpi 렌더링 fallback
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        return Image.open(io.BytesIO(pix.tobytes("png")))


def get_page_count(pdf_path: str | Path) -> int:
    with fitz.open(str(pdf_path)) as doc:
        return doc.page_count
```

---

### M-ocr-pipe-3 — `src/parser/ocr_engine.py` 신설

PP-Structure 엔진과 EasyOCR 폴백을 추상화한다.

#### 3-A. PPStructure 레이아웃 결과 데이터 클래스

```python
from dataclasses import dataclass, field

@dataclass
class LayoutBlock:
    """PP-Structure 레이아웃 블록 하나."""
    block_type: str       # "title" | "text" | "table" | "figure"
    bbox: list[int]       # [x1, y1, x2, y2]
    text: str             # 텍스트 또는 직렬화된 표 텍스트
    html: str | None = None      # 표인 경우 HTML 문자열
    confidence: float = 1.0
    raw: dict = field(default_factory=dict)   # PPStructure 원본 결과
```

#### 3-B. PP-Structure 호출

```python
def run_ppstructure(image: "Image.Image") -> list[LayoutBlock]:
    """
    PP-Structure로 레이아웃 분석 + 표/텍스트 OCR을 실행한다.
    반환: 감지된 LayoutBlock 목록 (bbox 기준 위에서 아래 순)
    """
    import numpy as np
    from paddleocr import PPStructure

    # PPStructure는 모듈 수준에서 초기화 비용이 크므로 캐싱
    engine = _get_ppstructure_engine()
    result = engine(np.array(image))
    blocks = []
    for region in result:
        btype = region.get("type", "text").lower()
        bbox = region.get("bbox", [0, 0, 0, 0])
        res = region.get("res", {})

        if btype == "table":
            html = res.get("html", "")
            text = _table_html_to_text(html)
            conf = float(res.get("score", 1.0)) if isinstance(res, dict) else 1.0
            blocks.append(LayoutBlock("table", bbox, text, html=html, confidence=conf))
        elif btype == "figure":
            blocks.append(LayoutBlock("figure", bbox, "", confidence=1.0))
        else:
            # title, text, header, footer 등
            if isinstance(res, list):
                # PP-OCR 결과: [(bbox, (text, confidence)), ...]
                texts = [item[1][0] for item in res if item[1][1] > 0.5]
                conf = float(sum(item[1][1] for item in res) / len(res)) if res else 0.0
                text = " ".join(texts)
            else:
                text = str(res)
                conf = 1.0
            blocks.append(LayoutBlock(btype, bbox, text, confidence=conf))

    # y축 기준 정렬 (위→아래 읽기 순서)
    blocks.sort(key=lambda b: b.bbox[1])
    return blocks
```

#### 3-C. 표 HTML → 텍스트 직렬화

```python
def _table_html_to_text(html: str) -> str:
    """HTML 표를 '헤더1 | 헤더2 | ...\n값1 | 값2 | ...' 형식으로 직렬화한다."""
    from bs4 import BeautifulSoup
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
        rows.append(" | ".join(cells))
    return "\n".join(rows)
```

#### 3-D. 표 JSON 구조화

```python
def _table_html_to_json(html: str) -> dict:
    """HTML 표를 헤더+행 JSON으로 변환한다."""
    from bs4 import BeautifulSoup
    import json
    if not html:
        return {}
    soup = BeautifulSoup(html, "lxml")
    all_rows = soup.find_all("tr")
    if not all_rows:
        return {}
    headers = [th.get_text(strip=True) for th in all_rows[0].find_all(["th", "td"])]
    rows = []
    for tr in all_rows[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
        if headers:
            rows.append(dict(zip(headers, cells)))
        else:
            rows.append(cells)
    return {"headers": headers, "rows": rows}
```

#### 3-E. PP-Structure 엔진 싱글턴 초기화

```python
_ppstructure_instance = None

def _get_ppstructure_engine():
    global _ppstructure_instance
    if _ppstructure_instance is None:
        from paddleocr import PPStructure
        _ppstructure_instance = PPStructure(
            table=True,
            ocr=True,
            lang="korean",   # 한국어 + 한자 병기 지원
            show_log=False,
            image_orientation=False,
        )
    return _ppstructure_instance
```

#### 3-F. EasyOCR 폴백

```python
def run_easyocr_fallback(image: "Image.Image") -> list[LayoutBlock]:
    """PPStructure 신뢰도가 낮을 때 EasyOCR로 폴백한다."""
    import numpy as np
    import easyocr
    reader = _get_easyocr_reader()
    result = reader.readtext(np.array(image), detail=1, paragraph=False)
    blocks = []
    for bbox_pts, text, conf in result:
        # EasyOCR bbox는 4점 형식 → [x1, y1, x2, y2]
        xs = [p[0] for p in bbox_pts]
        ys = [p[1] for p in bbox_pts]
        bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
        blocks.append(LayoutBlock("text", bbox, text, confidence=float(conf)))
    blocks.sort(key=lambda b: b.bbox[1])
    return blocks

_easyocr_reader = None
def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        _easyocr_reader = easyocr.Reader(["ko", "en"], gpu=False)
    return _easyocr_reader
```

---

### M-ocr-pipe-4 — `src/parser/ocr_postprocess.py` 신설

Korean 특화 텍스트 정규화. EasyOCR 검증에서 발견된 일관 오류 패턴을 보정한다.  
PP-Structure 출력에도 동일 정규화를 적용한다.

```python
"""OCR 한국어 텍스트 후처리 정규화."""
import re

# 받침 오류 패턴: (잘못된 패턴, 올바른 표현)
_SUFFIX_FIXES = [
    # 목적격 조사 오류
    (r"(?<=[가-힣])올\b", "을"),
    (r"(?<=[가-힣])틀\b", "를"),
    (r"(?<=[가-힣])롤\b", "를"),
    # 서술형 어미 오류
    (r"덥니다", "됩니다"),
    (r"됩니닥", "됩니다"),
    # 동사 어간 오류
    (r"엎올", "었을"),
    (r"잃엎", "잃었"),
    (r"없엎", "없었"),
    # 수술 용어 빈출 오류
    (r"수술올\b", "수술을"),
    (r"제거해내논", "제거해내는"),
]

# 반복 머리글/바닥글 제거 패턴 (D6 패턴)
_NOISE_PATTERNS = [
    re.compile(r"제\d+장\s+\S+분류표\s+해설\s+\d+\s*$", re.MULTILINE),
    re.compile(r"^[\s\d]+$", re.MULTILINE),          # 숫자만 있는 줄
    re.compile(r"^\s*[\{\}\[\]]\s*$", re.MULTILINE),  # 중괄호만 있는 줄
]

def normalize_ocr_text(text: str) -> str:
    """OCR 출력 텍스트를 정규화한다."""
    # 1. 받침 오류 보정
    for pattern, replacement in _SUFFIX_FIXES:
        text = re.sub(pattern, replacement, text)
    # 2. 반복 노이즈 줄 제거
    for noise_pat in _NOISE_PATTERNS:
        text = noise_pat.sub("", text)
    # 3. 다중 공백 정리
    text = re.sub(r"[ \t]{2,}", " ", text)
    # 4. 3줄 이상 연속 빈 줄 → 1줄
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

> **주의:** `_SUFFIX_FIXES` 패턴은 검증 단계의 실제 오류에서 도출됐다.  
> PP-Structure 출력 결과를 확인한 후 오류 패턴이 다르면 보완 필요.

---

### M-ocr-pipe-5 — `scripts/ocr_extract.py` 신설

전체 전처리 파이프라인 오케스트레이터. 원본 PDF → 구조화된 추출물 저장.

#### 5-A. 출력 디렉토리 구조

```
data/extracted/
└── 실무가이드/
│   ├── manifest.json           # 페이지별 블록 목록, 콘텐츠 유형 통계
│   ├── text/
│   │   ├── p000_b00.txt
│   │   └── ...
│   ├── tables/
│   │   ├── p066_t00.html       # PP-Structure 원본 HTML
│   │   ├── p066_t00.json       # 헤더+행 JSON
│   │   ├── p066_t00_text.txt   # BM25/임베딩용 직렬화 텍스트
│   │   └── ...
│   └── images/
│       ├── p010_f00.jpg        # 원본 도식 이미지
│       ├── p010_f00_caption.txt # 캡션 (현재: 빈 파일, 추후 Vision LLM으로 채움)
│       └── ...
└── 상담사례집/
    └── (동일 구조)
```

#### 5-B. 실행 명령

```bash
# 전체 실행 (기본 10 workers)
python scripts/ocr_extract.py

# 특정 문서만
python scripts/ocr_extract.py --doc 실무가이드

# 페이지 범위 지정 (디버그용)
python scripts/ocr_extract.py --doc 실무가이드 --pages 60-70

# 폴백 엔진 지정
python scripts/ocr_extract.py --fallback-engine easyocr --fallback-threshold 0.5
```

#### 5-C. 페이지 처리 흐름

```python
def process_page(
    pdf_path: Path,
    page_no: int,
    out_dir: Path,
    fallback_threshold: float = 0.5,
) -> dict:
    """단일 페이지를 처리하고 결과 메타를 반환한다."""
    from src.parser.pdf_extractor import extract_page_image
    from src.parser.ocr_engine import run_ppstructure, run_easyocr_fallback
    from src.parser.ocr_postprocess import normalize_ocr_text

    image = extract_page_image(pdf_path, page_no)
    blocks = run_ppstructure(image)

    # 신뢰도 평균이 낮으면 EasyOCR 폴백
    text_blocks = [b for b in blocks if b.block_type in ("text", "title")]
    avg_conf = sum(b.confidence for b in text_blocks) / len(text_blocks) if text_blocks else 0.0
    engine_used = "ppstructure"
    if avg_conf < fallback_threshold or not blocks:
        blocks = run_easyocr_fallback(image)
        engine_used = "easyocr"

    page_meta = {"page_no": page_no, "engine": engine_used, "blocks": []}

    text_i = table_i = fig_i = 0
    for block in blocks:
        text = normalize_ocr_text(block.text)

        if block.block_type == "table" and block.html:
            # 표 저장: HTML + JSON + 텍스트
            prefix = f"p{page_no:03d}_t{table_i:02d}"
            (out_dir / "tables" / f"{prefix}.html").write_text(block.html, encoding="utf-8")
            table_json = _table_html_to_json(block.html)
            (out_dir / "tables" / f"{prefix}.json").write_text(
                json.dumps(table_json, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (out_dir / "tables" / f"{prefix}_text.txt").write_text(text, encoding="utf-8")
            page_meta["blocks"].append({
                "type": "table", "file": f"tables/{prefix}_text.txt",
                "bbox": block.bbox, "confidence": block.confidence
            })
            table_i += 1

        elif block.block_type == "figure":
            # 도식: 원본 이미지 크롭 저장 + 빈 캡션 파일
            prefix = f"p{page_no:03d}_f{fig_i:02d}"
            cropped = image.crop(block.bbox)
            cropped.save(str(out_dir / "images" / f"{prefix}.jpg"), "JPEG", quality=90)
            (out_dir / "images" / f"{prefix}_caption.txt").write_text("", encoding="utf-8")
            page_meta["blocks"].append({
                "type": "figure", "file": f"images/{prefix}.jpg",
                "bbox": block.bbox
            })
            fig_i += 1

        else:
            # 텍스트/제목 블록
            if not text:
                continue
            prefix = f"p{page_no:03d}_b{text_i:02d}"
            (out_dir / "text" / f"{prefix}.txt").write_text(text, encoding="utf-8")
            page_meta["blocks"].append({
                "type": block.block_type, "file": f"text/{prefix}.txt",
                "bbox": block.bbox, "confidence": block.confidence,
                "chars": len(text)
            })
            text_i += 1

    return page_meta
```

#### 5-D. manifest.json 구조

```json
{
  "doc_short": "실무가이드",
  "total_pages": 330,
  "processed_pages": 330,
  "engine_stats": {
    "ppstructure": 280,
    "easyocr": 50
  },
  "content_type_stats": {
    "text": 1420,
    "table": 210,
    "figure": 88
  },
  "pages": [
    {
      "page_no": 0,
      "engine": "ppstructure",
      "blocks": [
        {"type": "text", "file": "text/p000_b00.txt", "bbox": [...], "confidence": 0.94, "chars": 82}
      ]
    },
    ...
  ]
}
```

---

### M-ocr-pipe-6 — `src/parser/ocr_chunker.py` 신설

추출물 디렉토리(`data/extracted/<doc_short>/`)를 읽어 RAG 청크를 생성한다.  
기존 `chunk_pages()`와 동일한 `Chunk` 객체를 반환해 `build_chunks()` 흐름에 그대로 투입한다.

```python
def chunk_from_extracted(
    doc_short: str,
    extracted_dir: Path,
    doc_source: "PdfSource",
    id_offset: int = 0,
) -> list[Chunk]:
    """
    ocr_extract.py가 생성한 data/extracted/<doc_short>/manifest.json을 읽어
    Chunk 목록을 생성한다.
    """
    manifest_path = extracted_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = []
    chunk_idx = id_offset

    for page_info in manifest["pages"]:
        page_no = page_info["page_no"]
        engine = page_info["engine"]

        for block_info in page_info["blocks"]:
            btype = block_info["type"]
            fpath = extracted_dir / block_info["file"]
            if not fpath.exists():
                continue

            if btype == "table":
                # 텍스트 직렬화로 검색, JSON으로 렌더링
                text = fpath.read_text(encoding="utf-8").strip()
                json_path = fpath.with_suffix("").parent / (fpath.stem.replace("_text", "") + ".json")
                table_json_str = json_path.read_text(encoding="utf-8") if json_path.exists() else "{}"
                metadata = _base_meta(doc_source, page_no, engine, "table", block_info)
                metadata["table_json"] = table_json_str
                chunks.append(Chunk(
                    id=f"{doc_short}_ch_{chunk_idx:06d}",
                    text=text,
                    metadata=metadata,
                ))
                chunk_idx += 1

            elif btype == "figure":
                # 캡션 파일만 읽음 (빈 캡션은 청크 미생성)
                cap_path = fpath.with_suffix("") + "_caption.txt"
                caption = cap_path.read_text(encoding="utf-8").strip() if cap_path.exists() else ""
                if not caption:
                    continue  # 캡션 없으면 검색 불가, 스킵
                metadata = _base_meta(doc_source, page_no, engine, "image", block_info)
                metadata["image_path"] = str(fpath.relative_to(extracted_dir.parent.parent))
                chunks.append(Chunk(
                    id=f"{doc_short}_ch_{chunk_idx:06d}",
                    text=caption,
                    metadata=metadata,
                ))
                chunk_idx += 1

            else:
                # 텍스트/제목 블록
                text = fpath.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                for piece in _split_text(text, target_chars=800, overlap_chars=100):
                    metadata = _base_meta(doc_source, page_no, engine, "text", block_info)
                    chunks.append(Chunk(
                        id=f"{doc_short}_ch_{chunk_idx:06d}",
                        text=piece,
                        metadata=metadata,
                    ))
                    chunk_idx += 1

    return chunks


def _base_meta(doc_source, page_no, engine, content_type, block_info) -> dict:
    from src.parser.chunker import EXTENDED_META_DEFAULTS, _extract_codes
    meta = {
        **EXTENDED_META_DEFAULTS,
        "doc_short": doc_source.doc_short,
        "doc_name": doc_source.doc_name,
        "doc_type": doc_source.doc_type,
        "pdf_filename": doc_source.path.name,
        "page_start": page_no,
        "page_end": page_no,
        "content_type": content_type,         # "text" | "table" | "image"
        "source_method": f"ocr_{engine}",     # "ocr_ppstructure" | "ocr_easyocr"
        "confidence": block_info.get("confidence", 1.0),
        "bbox": block_info.get("bbox"),
        "volume": None, "part": None, "chapter": None, "section": None,
        "codes": [],
        "is_code_table": False,
        "char_count": block_info.get("chars", 0),
    }
    for field in ["insurance_company","is_own_company","product_name","product_type","effective_date","version"]:
        val = getattr(doc_source, field, None)
        if val is not None:
            meta[field] = val
    return meta
```

---

### M-ocr-pipe-7 — `scripts/ingest.py` OCR 경로 연결

`build_chunks()` 함수에 OCR 문서 처리 경로를 추가한다. 기존 네이티브 경로는 변경하지 않는다.

```python
# scripts/ingest.py build_chunks() 내부 수정

from src.parser.ocr_chunker import chunk_from_extracted
from pathlib import Path

EXTRACTED_BASE = ROOT / "data" / "extracted"

for source in selected_sources:
    if not source.path.exists():
        print(f"[M6] 파일 없음, 건너뜀: {source.path.name}")
        continue

    if source.requires_ocr:
        # OCR 문서: 추출물 디렉토리에서 청크 생성
        extracted_dir = EXTRACTED_BASE / source.doc_short
        if not (extracted_dir / "manifest.json").exists():
            print(f"[M6] OCR 추출물 없음, 건너뜀: {source.doc_short}")
            print(f"     먼저 python scripts/ocr_extract.py --doc {source.doc_short} 실행")
            continue
        print(f"[M6] OCR 청크 생성: {source.doc_short}")
        chunks = chunk_from_extracted(source.doc_short, extracted_dir, source, id_offset)
    else:
        # 기존 네이티브 파싱 경로
        pages = parse_pdf(source.path)
        chunks = chunk_pages(pages, ..., doc_source=source, id_offset=id_offset)

    all_chunks.extend(chunks)
    ...
```

---

## 검증 체크리스트

### M-ocr-pipe-1~4 단계 검증

- [ ] `pip install paddlepaddle paddleocr beautifulsoup4 lxml` 성공
- [ ] `python -c "from paddleocr import PPStructure; e = PPStructure(table=True, ocr=True, lang='korean', show_log=False); print('OK')"` 성공
- [ ] `src/parser/pdf_extractor.py` — 페이지당 원본 JPEG 추출 확인 (이미지 크기 D6: ~2360×3316)
- [ ] `src/parser/ocr_engine.py` — D6 p066 (수술분류표 페이지)에서 LayoutBlock 목록에 `block_type="table"` 포함 확인
- [ ] `src/parser/ocr_postprocess.py` — `normalize_ocr_text("수술올 말하다")` → `"수술을 말하다"` 확인

### M-ocr-pipe-5 ocr_extract.py 실행 검증

```bash
# 먼저 소량 테스트 (60~70 페이지: 수술분류표 포함 구간)
python scripts/ocr_extract.py --doc 실무가이드 --pages 60-70
```

확인 사항:
- [ ] `data/extracted/실무가이드/tables/p066_t00.json` 생성 확인
- [ ] `p066_t00.json`의 `headers` 필드가 `["수술종수", "수술명", "수술해설"]` 포함 확인
- [ ] `data/extracted/실무가이드/text/` 디렉토리에 텍스트 파일 생성
- [ ] `data/extracted/실무가이드/images/` 디렉토리에 도식 이미지 PNG 생성
- [ ] `manifest.json`에 해당 페이지들 기록 확인

```bash
# D7 전체 실행
python scripts/ocr_extract.py --doc 상담사례집
```
- [ ] `data/extracted/상담사례집/manifest.json` 통계 확인 (351페이지)

### M-ocr-pipe-6 청킹 검증

```bash
python -c "
from pathlib import Path
from src.parser.ocr_chunker import chunk_from_extracted
from src.config import PDF_SOURCES
d6 = next(s for s in PDF_SOURCES if s.doc_short == '실무가이드')
chunks = chunk_from_extracted('실무가이드', Path('data/extracted/실무가이드'), d6)
table_chunks = [c for c in chunks if c.metadata.get('content_type') == 'table']
print(f'전체: {len(chunks)}, 표 청크: {len(table_chunks)}')
print('표 청크 샘플:', table_chunks[0].text[:100] if table_chunks else '없음')
"
```

- [ ] 표 청크에 `content_type="table"`, `source_method="ocr_ppstructure"` 확인
- [ ] 표 청크 `metadata["table_json"]`에 `headers` 필드 존재 확인

### M-ocr-pipe-7 전체 파이프라인 통합 검증

```bash
# OCR 추출물 존재 전제로 인덱싱 실행
python scripts/ingest.py --include-ocr --stage chunks
python -c "
import json
from pathlib import Path
counts = {}
for line in Path('data/processed/chunks.jsonl').open():
    d = json.loads(line)
    key = f\"{d['metadata']['doc_short']}:{d['metadata'].get('content_type','text')}\"
    counts[key] = counts.get(key, 0) + 1
for k, v in sorted(counts.items()):
    print(f'{k}: {v}')
"
```

- [ ] `실무가이드:text`, `실무가이드:table` 청크 확인
- [ ] `pytest -q --ignore=tests/test_vector_store.py` 전체 통과
- [ ] `python scripts/check_raw_assets.py` 통과

### .gitignore 추가

- [ ] `data/extracted/` 추가 (원본 OCR 추출물은 대용량이므로 Git 미추적)

---

## 구현 우선순위

| 순서 | 태스크 | 필수 여부 |
|------|--------|---------|
| 1 | M-ocr-pipe-1 — 의존성 추가 | 필수 |
| 2 | M-ocr-pipe-2 — pdf_extractor.py | 필수 |
| 3 | M-ocr-pipe-3 — ocr_engine.py | 필수 |
| 4 | M-ocr-pipe-4 — ocr_postprocess.py | 필수 |
| 5 | M-ocr-pipe-5 — ocr_extract.py (60~70p 테스트 먼저) | 필수 |
| 6 | M-ocr-pipe-6 — ocr_chunker.py | 필수 |
| 7 | M-ocr-pipe-7 — ingest.py 연결 | 필수 |
| 8 | D6 전체 실행 (`ocr_extract.py --doc 실무가이드`) | 권장 |
| 9 | D7 전체 실행 (`ocr_extract.py --doc 상담사례집`) | 권장 |

**D6 전체 실행 소요 시간 예상:**  
PP-Structure 초기화 ~30초 + 330페이지 × 5~15초/페이지 = 약 30~90분.  
`--pages` 범위 옵션으로 배치 실행 권장.

**다음 명세 (35번, 이번 범위 외):**  
- GPT-4o Vision으로 `images/*_caption.txt` 채우기
- D6 해부학 도식 캡션 생성 → 이미지 청크 검색 가능화

구현 완료 후 `docs/35_OCR_PIPELINE_REPORT.md`에 결과를 작성할 것.  
리포트 필수 포함 항목:  
1. D6 60~70p 테스트 표 청크 샘플 (헤더+행 JSON)
2. D6/D7 전체 콘텐츠 유형별 청크 수 통계
3. PP-Structure vs EasyOCR 폴백 비율
4. 후처리 전/후 텍스트 품질 비교 샘플
