# Codex 명세 #49 — 전체 스캔본 True Hybrid OCR 실행 및 RAG 인덱싱

## 1) Goal

두 스캔본 문서(실무가이드 330페이지, 상담사례집 351페이지)의 **모든 페이지**에
True Hybrid OCR(CLOVA + PP-Structure)을 적용하고, 결과를 RAG 파이프라인이 읽을 수 있는
`data/extracted/{doc}/` 포맷으로 저장한다. 이후 `ingest.py --include-ocr`로
ChromaDB·BM25 인덱스를 재빌드한다.

---

## 2) Background

### 현재 상태

| 문서 | 전체 페이지 | 현재 추출 완료 | 사용 엔진 | cloud_safe |
|---|---|---|---|---|
| 실무가이드 | 330 | 11 (60–70) | ppstructure | False |
| 상담사례집 | 351 | 5 (0–4) | ppstructure | True |

`data/extracted/{doc}/manifest.json`에 기존 PaddleOCR 결과만 있고,
True Hybrid(CLOVA) 결과는 `reports/ocr_compare/{doc}/p{NNN}_true_hybrid.json`에만 존재한다.
`ingest.py`는 `data/extracted/` 포맷만 인식하므로 현재 두 문서는 RAG 검색 대상에서 제외된 상태다.

### `ocr_chunker.py`가 기대하는 `data/extracted/{doc}/` 포맷

```
data/extracted/{doc}/
├── manifest.json          # 페이지 목록 + 블록 메타
├── text/
│   ├── p{NNN}_b{II}.txt   # 텍스트 블록 내용
│   └── ...
├── tables/
│   ├── p{NNN}_t{II}.txt   # 표 텍스트(header | row 형식)
│   ├── p{NNN}_t{II}.json  # 표 table_json {"headers":[], "rows":[]}
│   └── ...
└── images/                # 기존 PaddleOCR figure 이미지 (유지, 건드리지 않음)
```

`manifest.json` 페이지 항목 예시:
```json
{
  "page_no": 64,
  "page_label": 65,
  "engine": "true_hybrid",
  "fallback_reason": null,
  "blocks": [
    {"type": "text", "file": "text/p064_b00.txt", "bbox": [...], "confidence": 1.0, "chars": 120},
    {"type": "table", "file": "tables/p064_t00.txt", "bbox": [...], "confidence": 1.0,
     "vision_cleaned": true, "numeric_refined": true}
  ]
}
```

---

## 3) Target Files

### 신규 생성
- `scripts/run_full_ocr.py` — 전체 페이지 True Hybrid OCR 실행 + `data/extracted/` 저장
- `tests/test_run_full_ocr.py` — 단위 테스트

### 수정 허용
- `data/extracted/실무가이드/manifest.json` — True Hybrid 결과로 전체 갱신
- `data/extracted/상담사례집/manifest.json` — True Hybrid 결과로 전체 갱신
- `data/extracted/실무가이드/text/`, `tables/` — 신규 파일 추가
- `data/extracted/상담사례집/text/`, `tables/` — 신규 파일 추가

### 수정 금지
- `src/parser/ocr_chunker.py`
- `src/parser/ocr_engine.py`
- `src/parser/clova_ocr.py`
- `src/parser/table_vision_cleaner.py`
- `src/parser/numeric_cell_refiner.py`
- `src/config.py`
- `scripts/ingest.py`
- `scripts/run_true_hybrid_local.py`
- `scripts/run_clova_local.py`

---

## 4) Detailed Requirements

### 4-1. `scripts/run_full_ocr.py` 인터페이스

```
python scripts/run_full_ocr.py \
    --doc 실무가이드          # 또는 상담사례집, 또는 all (두 문서 순차 처리)
    [--pages 60-70]          # 지정 시 해당 범위만 처리 (기본: 전체)
    [--vision-clean]         # 표 정제 활성화 (기본: False)
    [--force]                # 이미 성공한 페이지도 재처리
    [--timeout 90]           # 페이지당 CLOVA API 타임아웃 (초, 기본 90)
    [--output-dir PATH]      # 기본: data/extracted/
```

처리 대상 문서는 `config.PDF_SOURCES`에서 `requires_ocr=True`인 것만 선택한다.
`--doc all`이면 모든 `requires_ocr=True` 문서를 순차 처리한다.

### 4-2. 페이지 처리 로직

```python
for page_no in pages_to_process:
    # 이미 성공한 페이지 skip (--force 없을 때)
    if not force and _is_page_done(manifest, page_no):
        skipped += 1
        continue

    # 1. 페이지 이미지 추출
    image = extract_page_image(pdf_path, page_no)

    # 2. True Hybrid OCR
    blocks = true_hybrid_ocr_page(image)  # 기존 run_true_hybrid_local 로직 재사용

    # 3. Vision 정제 (--vision-clean 시)
    if vision_clean and any(b.block_type == "table" for b in blocks):
        blocks = clean_table_blocks(blocks, image, vision_client)
        blocks = refine_numeric_cells(blocks, image, vision_client, model=numeric_model)

    # 4. data/extracted 포맷으로 저장
    block_entries = _save_blocks(blocks, out_dir, page_no)

    # 5. manifest 업데이트 (즉시 저장 — 중단 시 복구 가능)
    _update_manifest(manifest_path, page_no, page_label, block_entries)

    success += 1
```

`_is_page_done(manifest, page_no)`: manifest에 해당 page_no 항목이 존재하고
`engine == "true_hybrid"`이면 True를 반환한다.

### 4-3. `_save_blocks()` 변환 규칙

| LayoutBlock.block_type | 저장 위치 | manifest type |
|---|---|---|
| `"text"` | `text/p{NNN}_b{II}.txt` (block.text) | `"text"` |
| `"table"` | `tables/p{NNN}_t{II}.txt` (table_to_text) + `tables/p{NNN}_t{II}.json` (table_json) | `"table"` |
| `"figure"` | 저장하지 않음 (skip) | — |

- `p{NNN}`: 0-indexed 페이지 번호, 3자리 zero-padding (예: `p064`)
- 텍스트 블록 카운터와 표 블록 카운터를 분리한다 (`b{II}` vs `t{II}`)
- `table_json`이 없거나 비어 있는 table block은 skip한다

블록 메타 dict 예시:
```python
{
    "type": "text",           # 또는 "table"
    "file": "text/p064_b00.txt",
    "bbox": block.bbox,
    "confidence": 1.0,
    "chars": len(block.text),
    # table 전용 추가 필드
    "vision_cleaned": block.raw.get("vision_cleaned", False),
    "numeric_refined": block.raw.get("numeric_refined", False),
}
```

### 4-4. manifest.json 구조

파일 전체 구조:
```json
{
  "doc_short": "실무가이드",
  "total_pages": 330,
  "pages": [
    { "page_no": 0, "page_label": 1, "engine": "true_hybrid", "fallback_reason": null, "blocks": [...] },
    ...
  ]
}
```

- `pages`는 `page_no` 오름차순으로 정렬하여 저장한다.
- 기존 manifest에 ppstructure 항목이 있으면, 해당 page_no가 true_hybrid로 처리될 때 덮어쓴다.
- `--force` 없이 실행 시 이미 `engine == "true_hybrid"`인 항목은 건드리지 않는다.
- manifest는 **매 페이지 처리 후 즉시 저장**한다(중단 시 복구 보장).

### 4-5. 진행률 출력 형식

```text
[run_full_ocr] 실무가이드 (330 페이지) 시작
[run_full_ocr] p060 -> SUCCESS (5블록, 18.3초)  [60/330 완료]
[run_full_ocr] p061 -> SKIPPED (기존 true_hybrid 결과)  [61/330 완료]
[run_full_ocr] p062 -> FAILED: CLOVA timeout  [62/330 완료]
...
=== 실무가이드 완료 ===
SUCCESS: 285/330 | SKIPPED: 30/330 | FAILED: 15/330 | 소요: 1h 28m
```

### 4-6. 오류 처리

- 페이지 처리 실패(CLOVA 오류, 타임아웃, 이미지 추출 오류 등)는 WARNING 로그 후 다음 페이지 진행.
- 실패한 페이지는 manifest에 기록하지 않는다 (다음 run에서 재처리됨).
- CLOVA 401(인증 오류) 발생 시 즉시 중단하고 오류 보고.
- OpenAI 401 발생 시(`--vision-clean` 중) vision-clean만 비활성화하고 나머지 페이지는 계속 처리.

### 4-7. `--vision-clean` 비용 안내

스크립트 실행 시 `--vision-clean`이 활성화된 경우, 시작 전 아래를 출력한다:
```text
[경고] --vision-clean 활성화: 표 감지 페이지마다 OpenAI Vision API를 2회 호출합니다.
       전체 실행 시 추가 비용이 발생할 수 있습니다. 계속하려면 Enter를 누르세요.
```
단, `--yes` 플래그 또는 `CI=true` 환경변수가 설정된 경우 확인 없이 진행한다.

### 4-8. True Hybrid OCR 함수 재사용

`run_true_hybrid_local.py`의 내부 로직을 직접 import하지 말고,
아래 모듈들을 직접 import하여 동일한 파이프라인을 구성한다.

```python
from src.parser.clova_ocr import clova_ocr_page
from src.parser.pdf_extractor import extract_page_image
from src.parser.table_vision_cleaner import clean_table_blocks, TableVisionCleanerAuthError
from src.parser.numeric_cell_refiner import refine_numeric_cells, NumericCellRefinerAuthError
```

PP-Structure(ppstructure) 레이아웃 분석은 `run_true_hybrid_local.py`와 동일하게
`src.parser.ocr_engine.run_ppstructure`를 호출하고 layout_regions를 CLOVA에 전달한다.

---

## 5) Validation

```bash
# 1. 단위 테스트
pytest tests/test_run_full_ocr.py -v
# 최소 4개 테스트: _is_page_done, _save_blocks text, _save_blocks table, manifest 업데이트

# 2. 전체 회귀
pytest -q
# 목표: 기존 201개 + 신규 ≥ 4개, 0 failures

# 3. 소규모 smoke test (1페이지)
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64 --yes
# → data/extracted/실무가이드/manifest.json에 page_no=64, engine="true_hybrid" 항목 추가 확인
# → data/extracted/실무가이드/tables/ 또는 text/ 에 p064_* 파일 생성 확인

# 4. resume 동작 확인
python scripts/run_full_ocr.py --doc 실무가이드 --pages 64-65 --yes
# → p064: SKIPPED (기존 true_hybrid), p065: SUCCESS 출력 확인

# 5. 청킹 연동 확인
python -c "
import sys; sys.path.insert(0, '.')
from src import config
from src.parser.ocr_chunker import chunk_from_extracted
from pathlib import Path
source = next(s for s in config.PDF_SOURCES if s.doc_short == '실무가이드')
chunks = chunk_from_extracted('실무가이드', Path('data/extracted/실무가이드'), source)
print(f'청크 수: {len(chunks)}')
print(f'엔진 샘플: {chunks[0].metadata[\"source_method\"]}')
"
# → 청크 수 > 0, source_method에 "ocr_true_hybrid" 포함 확인

# ── 이하는 Codex가 직접 실행하지 않고 운영자(범준님)가 실행 ──
# 6. 전체 실행 (운영자 실행 — 약 3-4시간)
# python scripts/run_full_ocr.py --doc all --yes
# python scripts/run_full_ocr.py --doc all --vision-clean --yes  (선택사항)

# 7. 인덱스 재빌드 (운영자 실행)
# python scripts/ingest.py --include-ocr --stage all
```

---

## 6) Stop Rules

- `pytest -q`에서 기존 테스트 1건이라도 실패 → 즉시 중단, 보고
- `src/parser/ocr_chunker.py` 수정이 필요한 경우 → 중단, 보고 (포맷 변환 로직을 스크립트에서 처리)
- smoke test에서 `manifest.json` 파일 손상 또는 청킹 오류 발생 → 중단, 보고
- CLOVA API 401 → 즉시 중단, 보고
- `run_ppstructure` import 오류 (PaddleOCR 미설치) → 오류 메시지 명시 후 보고; 스크립트 코드는 완성

---

## 7) Output Requirements

구현 완료 후 `docs/49_FULL_OCR_INGEST_REPORT.md`를 작성하고 커밋한다.

보고서 포함 항목:
1. 변경 파일 목록 (함수별 한 줄 설명)
2. `pytest -q` 전체 출력
3. smoke test 결과 (p064 처리 후 manifest 항목, 생성된 파일 목록)
4. resume 동작 확인 결과 (p064 SKIPPED, p065 SUCCESS)
5. 청킹 연동 확인 결과 (청크 수, source_method)
6. 전체 실행 명령 안내 (운영자용)
7. 잔여 블로커 ("None" 또는 구체적 내용)

커밋 포함 항목: `scripts/run_full_ocr.py`, `tests/test_run_full_ocr.py`, `docs/49_FULL_OCR_INGEST_REPORT.md`
커밋 제외 항목: `data/extracted/` 하위 txt/json 파일, `data/index/` 하위 파일, HTML 파일

> **운영자 안내**: 전체 OCR 실행(681페이지)은 CLOVA API 비용·시간이 소요됩니다.
> Codex 구현 검토 후 별도로 `python scripts/run_full_ocr.py --doc all --yes`를 실행하세요.
> vision-clean은 선택 사항이며, 비용 절감을 위해 첫 전체 실행은 vision-clean 없이 진행을 권장합니다.
