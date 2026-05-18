# Codex 명세 — CLOVA OCR 로컬 실행 스크립트 작성 (v40)

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)  
선행 보고서: `docs/39_OCR_COMPARE_REPORT.md`

---

## 배경 및 문제 정의

### 현재 상황

`scripts/ocr_compare.py --engines clova` 실행 결과, CLOVA OCR의 11개 페이지가 모두 SKIPPED되었다.

```
"status": "SKIPPED",
"error": "API 요청 실패: HTTPSConnectionPool(host='ea1lfq3tos.apigw.ntruss.com', port=443): Max retries exceeded ... (Caused by NameResolutionError(\"...: Failed to resolve 'ea1lfq3tos.apigw.ntruss.com' ([Errno 8] nodename nor servname provided, or not known)\"))"
```

### 근본 원인

Codex의 실행 환경(클라우드 샌드박스)은 외부 도메인 `ea1lfq3tos.apigw.ntruss.com`에 대한 DNS 해석이 차단되어 있다. 반면 **기획자(사용자)의 로컬 Mac에서는 동일 URL로 CLOVA 호출이 정상 작동한다** (이전 테스트에서 확인됨).

### 해결 전략

Codex는 **사용자가 로컬 Mac에서 직접 실행하는 독립 스크립트** `scripts/run_clova_local.py`를 작성한다.

이 스크립트는:
1. 이미 저장된 `reports/ocr_compare/실무가이드/p0{xx}_original.png` 파일을 읽는다 (PDF 재추출 불필요)
2. `.env`에서 CLOVA 인증 정보를 로드한다
3. 각 PNG를 CLOVA API에 전송하여 결과를 얻는다
4. 결과를 기존 `p0{xx}_clova.json`과 **동일한 스키마**로 덮어쓴다

---

## 구현 명세

### 파일: `scripts/run_clova_local.py` (신규)

#### 역할

- `reports/ocr_compare/{doc_short}/` 폴더의 `p0{xx}_original.png` 파일을 순서대로 읽어 CLOVA OCR을 호출
- 각 페이지 결과를 `p0{xx}_clova.json`으로 저장 (기존 SKIPPED 파일 덮어쓰기)
- 완료 후 콘솔에 per-page 결과 요약 출력

#### CLI 인터페이스

```bash
python scripts/run_clova_local.py \
    --doc 실무가이드 \
    --pages 60-70 \
    --output-dir reports/ocr_compare/
```

인수:
- `--doc`: 문서 단축명 (예: `실무가이드`), `reports/ocr_compare/{doc_short}/` 폴더 매핑
- `--pages`: 페이지 범위 (예: `60-70`, `66`, `60,62,66`)
- `--output-dir`: 출력 루트 디렉터리 (기본: `reports/ocr_compare/`)
- `--timeout`: CLOVA API 타임아웃 초 (기본: 60)

#### 출력 JSON 스키마

기존 `p0{xx}_clova.json` 파일과 **완전히 동일한 형식**을 사용한다:

```json
{
  "engine": "clova",
  "doc_short": "실무가이드",
  "page_no": 66,
  "elapsed_sec": 7.34,
  "status": "SUCCESS",
  "error": null,
  "original_image": "p066_original.png",
  "masked_image": "p066_masked.png",
  "figures": [],
  "blocks": [
    {
      "block_type": "text",
      "bbox": [x1, y1, x2, y2],
      "text": "인식된 텍스트",
      "table_json": null,
      "source_method": "ocr_clova",
      "quality": {
        "chars": 120,
        "korean_ratio": 0.85,
        "noise_ratio": 0.02,
        "grade": "PASS"
      }
    }
  ],
  "metrics": {
    "total_blocks": 3,
    "table_blocks": 1,
    "text_blocks": 2,
    "figure_blocks": 0,
    "avg_korean_ratio": 0.75,
    "avg_noise_ratio": 0.01,
    "grade_pass": 2,
    "grade_marginal": 1,
    "grade_fail": 0,
    "header_score_avg": 0.6
  }
}
```

#### 핵심 구현 사항

**1. 환경 변수 로딩**

```python
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")
```

`find_dotenv()` 사용 금지 — `stdin` 실행 시 AssertionError 발생 이력 있음.

**2. 기존 `clova_ocr_page()` 직접 활용**

```python
from src.parser.clova_ocr import clova_ocr_page, ClovaOcrError
```

`clova_ocr_page(image, page_name=page_name, timeout_sec=args.timeout)` 를 각 페이지에 호출한다.  
새로운 API 호출 코드를 별도로 작성하지 않는다.

**3. layout_regions 인수**

이 스크립트는 `layout_regions` 없이 호출한다 (전체 페이지 단위 CLOVA 호출).  
후처리에서 `_fields_to_single_block` 방식으로 블록을 구성한다 — 기존 로직을 그대로 사용한다.

**4. 품질 지표 계산**

`p0{xx}_hybrid.json`과 동일하게 각 블록에 `quality` 딕셔너리를 추가한다:

```python
from scripts.ocr_compare import _block_quality  # 또는 동일 로직 인라인
```

`scripts/ocr_compare.py`에서 `_block_quality()` 함수가 이미 구현되어 있으면 import해서 재사용한다.  
없으면 아래 로직을 인라인으로 구현한다:

```python
import re

HEADER_KEYWORDS = ['수술종수', '수술명', '수술해설', '종수', '분류']

def _block_quality(block_dict: dict) -> dict:
    text = block_dict.get('text', '')
    chars = len(text.replace(' ', '').replace('\n', ''))
    if chars == 0:
        return {'chars': 0, 'korean_ratio': 0.0, 'noise_ratio': 0.0, 'grade': 'FAIL'}
    korean = len(re.findall(r'[가-힣]', text))
    noise = len(re.findall(r'[^\w\s가-힣\.\,\!\?\:\;\-\(\)\[\]\{\}\/\\\|\@\#\$\%\^\&\*\+\=\'\"\`\~]', text))
    kr_ratio = korean / chars
    noise_ratio = noise / chars
    if kr_ratio >= 0.5 and noise_ratio <= 0.05:
        grade = 'PASS'
    elif kr_ratio >= 0.3 or noise_ratio <= 0.1:
        grade = 'MARGINAL'
    else:
        grade = 'FAIL'
    return {'chars': chars, 'korean_ratio': round(kr_ratio, 3), 'noise_ratio': round(noise_ratio, 3), 'grade': grade}
```

**5. 헤더 점수 계산**

표 블록이 있을 경우 `header_score_avg`를 계산한다:

```python
def _header_score(table_json: dict) -> float:
    headers = table_json.get('headers', [])
    if not headers:
        return 0.0
    matched = sum(1 for h in headers if any(kw in h for kw in HEADER_KEYWORDS))
    return matched / len(headers)
```

**6. 오류 처리**

- `ClovaOcrError` 발생 시 해당 페이지를 SKIPPED로 기록하고 계속 진행
- 타임아웃도 마찬가지
- 오류 JSON:

```json
{
  "engine": "clova",
  "page_no": 66,
  "elapsed_sec": 60.1,
  "status": "SKIPPED",
  "error": "오류 메시지",
  "blocks": [],
  "metrics": { "total_blocks": 0, ... }
}
```

**7. 콘솔 출력**

```
[run_clova_local] p060 → SUCCESS (3블록, 7.1초)
[run_clova_local] p061 → SUCCESS (4블록, 8.3초)
[run_clova_local] p062 → SKIPPED (타임아웃)
...
=== 완료 ===
SUCCESS: 10/11 | SKIPPED: 1/11 | 총 소요: 82.4초
저장 위치: reports/ocr_compare/실무가이드/
```

---

## summary.json 업데이트 명세

CLOVA 결과가 채워진 후 `summary.json`을 업데이트하는 로직을 `run_clova_local.py` 마지막에 추가한다.

기존 `summary.json`을 읽어 `engines.clova` 섹션만 갱신한다:

```python
def _update_summary(output_dir: Path, doc_short: str, clova_results: list[dict]) -> None:
    summary_path = output_dir / doc_short / "summary.json"
    if not summary_path.exists():
        return
    
    with open(summary_path) as f:
        summary = json.load(f)
    
    # CLOVA 섹션 재계산
    success = [r for r in clova_results if r['status'] == 'SUCCESS']
    skipped_pages = [r['page_no'] for r in clova_results if r['status'] == 'SKIPPED']
    
    avg_elapsed = sum(r['elapsed_sec'] for r in success) / len(success) if success else None
    all_blocks = [b for r in success for b in r.get('blocks', [])]
    table_blocks = [b for b in all_blocks if b.get('block_type') == 'table']
    
    kr_ratios = [b['quality']['korean_ratio'] for b in all_blocks if b.get('quality')]
    avg_kr = sum(kr_ratios) / len(kr_ratios) if kr_ratios else None
    
    noise_ratios = [b['quality']['noise_ratio'] for b in all_blocks if b.get('quality')]
    avg_noise = sum(noise_ratios) / len(noise_ratios) if noise_ratios else None
    
    header_scores = [r.get('metrics', {}).get('header_score_avg', 0) for r in success]
    avg_header = sum(header_scores) / len(header_scores) if header_scores else None
    
    grades = {'PASS': 0, 'MARGINAL': 0, 'FAIL': 0}
    for b in all_blocks:
        g = b.get('quality', {}).get('grade', '')
        if g in grades:
            grades[g] += 1
    
    summary['engines']['clova'] = {
        'avg_elapsed_sec': round(avg_elapsed, 3) if avg_elapsed else None,
        'avg_korean_ratio': round(avg_kr, 3) if avg_kr else None,
        'avg_noise_ratio': round(avg_noise, 3) if avg_noise else None,
        'table_blocks': len(table_blocks),
        'header_score_avg': round(avg_header, 3) if avg_header else None,
        'grade': grades,
        'skipped_pages': skipped_pages,
        'status': 'SUCCESS' if not skipped_pages else ('PARTIAL' if success else 'SKIPPED'),
    }
    summary['clova_rerun_at'] = datetime.datetime.now().isoformat(timespec='seconds')
    
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'[run_clova_local] summary.json 업데이트 완료')
```

---

## 단위 테스트 명세

**파일:** `tests/test_run_clova_local.py` (신규)

테스트 항목:
1. `_block_quality()`: 한글 비율 / 노이즈 비율 계산 확인, 경계 케이스 (빈 텍스트)
2. `_header_score()`: 키워드 매칭 확인
3. `_update_summary()`: 기존 summary.json 읽기 → CLOVA 섹션 업데이트 → 저장 확인 (tmp 파일 사용)
4. `parse_pages()` (CLI 인수 파서 헬퍼): `"60-70"` → `[60,...,70]`, `"66"` → `[66]`, `"60,62,66"` → `[60,62,66]`

---

## 검증 순서

Codex는 스크립트 작성 후 아래 순서로 검증한다:

```bash
# 1. 단위 테스트
pytest tests/test_run_clova_local.py -q

# 2. 전체 테스트 통과 확인
pytest -q

# 3. dry-run: 스크립트 문법/import 확인 (API 호출 없이)
python -c "import scripts.run_clova_local; print('import OK')"
```

**주의: Codex 환경에서 `python scripts/run_clova_local.py`를 직접 실행하지 않는다** — DNS 차단으로 모두 SKIPPED될 뿐이다.

---

## 보고서 작성 요구사항

구현 완료 후 `docs/40_CODEX_REPORT_CLOVA_LOCAL.md`를 작성한다.

필수 포함 항목:
1. `pytest -q` 결과 (전체 통과 수 + 신규 테스트 통과 수)
2. 스크립트 사용 방법 (복사해서 바로 실행 가능한 명령어)
3. 생성된 파일 목록 및 위치
4. 구현 시 판단 사항 (명세 불명확 부분)

---

## 주의사항

- `find_dotenv()` 사용 금지 → `Path(__file__).parent.parent / ".env"` 사용
- `layout_regions` 없이 전체 페이지 단위로 CLOVA 호출 (region 분할 불필요)
- 기존 `p0{xx}_clova.json` 파일의 `"figures"`, `"masked_image"` 등 필드는 대응하는 hybrid.json에서 복사해도 됨
- `summary.json` 업데이트는 기존 파일을 파괴하지 않고 `engines.clova` 섹션만 교체
- HTML 결과지 재생성은 Codex 범위 외 — 사용자가 기획·검토 에이전트에게 요청
