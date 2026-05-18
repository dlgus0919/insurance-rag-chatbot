# Codex 명세 — True Hybrid figure 마스킹 제거 (v42)

작성일: 2026-05-08  
작성자: 기획·검토 에이전트  
대상: Codex (개발 에이전트)  
선행 보고서: `docs/41_CODEX_REPORT_TRUE_HYBRID.md`

---

## 배경 및 문제

### 현재 True Hybrid (v41)의 결함

`run_true_hybrid_local.py`는 아래 순서로 동작한다:

```
preprocess_page(image)
    → prep.masked_image   (figure 영역을 흰 사각형으로 덮은 이미지)
    → prep.regions        (PP-Structure bbox 목록: table/text/figure)

clova_ocr_page(prep.masked_image, layout_regions=prep.regions)
    → figure 영역: masked_image에서 이미 흰색 → 텍스트 소실
    → figure 영역: clova_ocr_page 내부에서 완전 skip
```

### 실측 피해 규모 (실무가이드 60-70p, 11페이지)

| 페이지 | figure 마스킹 면적 | 표 추출 결과 |
|--------|-------------------|-------------|
| p060   | 52.3% (2개 영역)  | 표 0개 |
| p063   | 60.2% (1개 영역)  | 표 0개 |
| p064   | 28.9% (1개 영역)  | 표 1개 |
| p065   | 63.0% (1개 영역)  | 표 0개 |
| p069   | 60.8% (1개 영역)  | 표 0개 |

**근본 원인**: PP-Structure (`lang='ch'`)가 대형 표나 텍스트 영역을 "figure"로 잘못 분류하는 오탐(false positive)이 발생한다. 이 오탐이 두 겹의 데이터 손실을 만든다:

1. **마스킹 손실**: `prep.masked_image`에서 해당 영역이 흰 사각형으로 덮여 CLOVA가 읽을 수 없음
2. **Skip 손실**: `clova_ocr_page(layout_regions=prep.regions)` 내부에서 figure 타입 region은 완전히 skip됨

### 해결 방향

`preprocess_page()`는 계속 호출한다 — PP-Structure의 **표/텍스트 bbox**는 여전히 표 재구성(`reconstruct_table_from_fields`)에 필요하다.

단, CLOVA 호출 시:
1. 마스킹 이미지 대신 **원본 이미지**를 전달 → 마스킹 손실 제거
2. layout_regions에서 **figure 타입을 제외** → skip 손실 제거. figure였던 영역의 OCR 결과는 "나머지 텍스트" 경로로 처리됨

---

## 구현 명세

### 변경 파일: `scripts/run_true_hybrid_local.py` (수정)

#### 1. `run_true_hybrid_local()` 함수 내 핵심 변경

```python
# ===== 변경 전 =====
prep = preprocess_page(image, figure_save_dir=figure_save_dir, page_name=page_name)
blocks = clova_ocr_page(
    prep.masked_image,              # ← 마스킹된 이미지
    page_name=page_name,
    layout_regions=prep.regions,    # ← figure 타입 포함
    timeout_sec=timeout_sec,
)

# ===== 변경 후 =====
prep = preprocess_page(image, figure_save_dir=figure_save_dir, page_name=page_name)
layout_regions_no_fig = [r for r in prep.regions if r.block_type != "figure"]
blocks = clova_ocr_page(
    image,                               # ← 원본 이미지 (마스킹 없음)
    page_name=page_name,
    layout_regions=layout_regions_no_fig, # ← figure 타입 제외
    timeout_sec=timeout_sec,
)
```

`image` 변수는 `with Image.open(original_path) as image:` 블록 내에서 이미 사용 가능하다. `image.load()`가 먼저 호출되어 있으므로 안전하게 재사용 가능하다.

#### 2. `_write_page_json()` 함수 내 `masked_image` 필드 변경

마스킹을 수행하지 않으므로 `masked_image` 필드를 `None`으로 변경한다.

```python
# ===== 변경 전 =====
"masked_image": f"p{page_no:03d}_masked.png",

# ===== 변경 후 =====
"masked_image": None,
```

#### 3. 그 외 변경 없음

- `preprocess_page()` 호출: 변경 없음 (레이아웃 bbox + figure 메타데이터 수집 유지)
- `_extract_figures()`: 변경 없음 (figure bbox 및 저장 경로 기록 유지)
- `_update_summary()` 호출: 변경 없음
- 출력 파일명: `p{page_no:03d}_true_hybrid.json` — 변경 없음 (v41 결과 덮어쓰기)
- figure_save_dir: `p{page_no:03d}_true_hybrid_figures` — 변경 없음

---

### 변경 파일: `tests/test_run_true_hybrid_local.py` (수정)

#### `test_run_true_hybrid_success()` 강화

현재 테스트는 `recorder.layout_regions is not None`만 확인한다. 아래 두 가지를 추가 검증한다:

1. **figure 타입이 layout_regions에서 제거되었는지**: `fake_preprocess_page`가 table + figure 두 region을 반환하므로, `fake_clova_ocr_page`에 전달된 `layout_regions`에는 table region만 있어야 한다.

```python
# 추가 검증
assert all(r.block_type != "figure" for r in recorder.layout_regions)
assert len(recorder.layout_regions) == 1  # table 1개만
```

2. **`clova_ocr_page`가 원본 이미지를 받았는지**: `fake_clova_ocr_page`가 받은 `image` 인자를 recorder에 저장하고, `prep.masked_image`가 아닌 원본 image임을 검증한다.

```python
# _CallRecorder에 image 필드 추가
@dataclass
class _CallRecorder:
    layout_regions: list | None = None
    received_image: object = None  # 추가

# fake_clova_ocr_page에서 recorder 저장
def fake_clova_ocr_page(image, page_name, layout_regions, timeout_sec):
    recorder.layout_regions = layout_regions
    recorder.received_image = image  # 추가
    ...

# 검증 추가: masked_image가 아닌 원본 image를 받았는지
# PIL Image는 직접 동일성 비교가 어려우므로, 
# fake_preprocess_page에서 원본 image와 명시적으로 다른 masked_image를 만들고
# recorder.received_image가 masked_image가 아님을 size 또는 id로 확인한다.
# 가장 간단한 방법: masked_image를 다른 색으로 만들고 픽셀 비교
```

**구현 힌트**: `fake_preprocess_page`에서 `masked_image`를 원본과 다른 색으로 생성:

```python
def fake_preprocess_page(image, figure_save_dir, page_name):
    masked = Image.new("RGB", image.size, color="red")  # 원본과 명확히 다름
    ...
    return PreprocessResult(
        original_image=image,
        masked_image=masked,   # 빨간색
        ...
    )
```

그리고 검증:
```python
# clova_ocr_page가 받은 이미지가 빨간 masked_image가 아닌지 확인
import numpy as np
received_arr = np.array(recorder.received_image)
assert received_arr[0, 0, 0] != 255 or received_arr[0, 0, 1] != 0  # 빨간색(255,0,0)이 아님
```

3. **`masked_image` 필드가 `None`인지 확인**:

```python
assert output["masked_image"] is None
```

#### 기타 테스트 (`test_run_true_hybrid_clova_error`, `test_run_true_hybrid_missing_png`, `test_update_summary_true_hybrid_key`)

변경 불필요. 단, `test_run_true_hybrid_clova_error`의 `fake_preprocess_page`도 `masked_image`로 `image.copy()`를 반환하고 있는데, 이는 테스트 논리상 문제없다 — clova_ocr_page가 예외를 던지므로 어떤 image를 전달했는지는 테스트 목적과 무관하다.

---

## 검증 순서

```bash
# 1. 전체 테스트 (회귀 포함)
pytest -q

# 2. 신규/수정 테스트
pytest tests/test_run_true_hybrid_local.py -v

# 3. import 확인
python -c "import scripts.run_true_hybrid_local; print('import OK')"
```

기존 182개 테스트가 전부 통과해야 한다. `run_clova_local.py`는 수정하지 않으므로 기존 5개 clova 테스트에는 영향 없음.

---

## 보고서 작성 요구사항

구현 완료 후 `docs/42_CODEX_REPORT_NO_MASKING.md`를 작성한다.

**필수 포함 항목:**

1. `pytest -q` 결과 (전체 통과 수)
2. `run_true_hybrid_local.py` 변경 사항 요약 (diff 형식 또는 설명)
3. 테스트 변경 사항 (`test_run_true_hybrid_success` 추가 검증 항목)
4. 구현 시 판단 사항

---

## 주의사항

- `find_dotenv()` 사용 금지 → `Path(__file__).parent.parent / ".env"` 사용 (기존 코드 유지)
- `preprocess_page()` 제거 금지 — 레이아웃 bbox는 여전히 필요
- `run_clova_local.py` 수정 금지
- `ocr_preprocessor.py`, `clova_ocr.py` 수정 금지
- Codex 환경에서 `run_true_hybrid_local.py` 직접 실행 금지 (DNS 차단)
- 기존 `p0{xx}_hybrid.json`, `p0{xx}_clova.json` 파일 수정 금지
