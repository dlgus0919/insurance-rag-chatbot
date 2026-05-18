# 명세 45 — 표 다단 헤더 감지 + Vision LLM 그림 셀 정제

## 1. Goal

두 가지 표 파싱 품질 문제를 해결하여 RAG DB에 저장되는 표 구조의 정확도를 높인다.

1. **다단 병합 헤더 자동 감지**: CLOVA native tables[]에서 2행으로 구성된 헤더(병합 행 + 서브헤더 행)를 올바르게 해석해, 컬럼명이 `수술종수 / 수술종수_2 / 수술종수_3` 대신 `1-3종 / 1-5종 / 신1-5종`으로 추출되도록 한다.
2. **Vision LLM 기반 그림 셀 정제**: 표 안에 삽입된 해부도·도표 셀을 Claude Vision API로 감지하여 OCR 텍스트를 `[그림]` 마커로 교체하고, 명백한 OCR 오류도 함께 보정한다.

문서 DB 구축은 문서당 1회만 수행하므로 처리 시간 증가(Vision API 호출)는 허용한다.

---

## 2. Background

### 문제 A: 다단 헤더

CLOVA가 반환하는 표에서 헤더가 2행으로 구성될 때:

```
Row 0: "수술명"(rowSpan=2) │ "수술해설"(rowSpan=2) │ "수술종수"(colSpan=3)
Row 1:                     │                       │ "1-3종" │ "1-5종" │ "신1-5종"
Row 2: 베이커낭종 적출술   │ 설명...               │         │    2    │    2
```

현재 `_table_to_json()`은 `grid[0]`을 항상 헤더로 사용한다.
`"수술종수"` 병합셀이 grid[0]의 열 2·3·4를 모두 채우므로 `_unique_headers()`가
`수술종수 / 수술종수_2 / 수술종수_3`으로 중복 처리한다.
결과적으로 Row 1(서브헤더)이 데이터 행으로 밀리고, 실제 컬럼명이 사라진다.

p064 실측 예:
```
현재 headers: ['수술명', '수술해설', '수술종수', '수술종수_2', '수술종수_3']
현재 row[0]:  {'수술명': '수술명', '수술해설': '수술해설', '수술종수': '1-3종', ...}
               ↑ 서브헤더 행이 데이터로 처리됨

목표 headers: ['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']
목표 row[0]:  {'수술명': '베이커낭종 적출술', '수술해설': '무릎 뒤쪽...', '1-3종': '', ...}
```

### 문제 B: 표 안 그림 셀

p064 row[2]:
```python
{'수술해설': "베이커, 낭종이 되는 부위\nBaker' s Cyst\n보통 관절내 염증이나\n활막염 동반하는 경우 흔함"}
```
이것은 해부도 안의 텍스트가 일반 셀 내용으로 오인식된 것이다.
PP-Structure의 figure bbox는 과잉 감지 문제가 있어 사용하지 않는다.
대신 Claude Vision API로 표 이미지를 보고 그림 셀을 직접 판별한다.

---

## 3. Target files

| 파일 | 변경 종류 |
|------|-----------|
| `src/parser/clova_ocr.py` | `_table_to_json()` 다단 헤더 로직 추가 |
| `src/parser/table_vision_cleaner.py` | **신규** — Vision LLM 표 정제 모듈 |
| `scripts/run_true_hybrid_local.py` | Vision 정제 단계 통합 (`--vision-clean` 플래그) |
| `scripts/run_clova_local.py` | 동일하게 `--vision-clean` 플래그 추가 |
| `tests/test_clova_ocr.py` | 다단 헤더 테스트 추가 |
| `tests/test_table_vision_cleaner.py` | **신규** 테스트 파일 |

**변경 금지**: `src/parser/ocr_engine.py`, `src/parser/ocr_preprocessor.py`, 기타 `src/` 내 모든 파일

---

## 4. Detailed Requirements

### Part 1: `_table_to_json()` 다단 헤더 감지

#### 알고리즘

**Step 1 — 헤더 행 수 판별 (`_detect_header_rows`)**

```
입력: cells (CLOVA raw cell list)

1. row 0 셀 중 colSpan > 1인 셀이 존재하는가?
   → 없으면: n_header_rows = 1, 종료

2. row 0의 colSpan 셀이 점유하는 열 집합(colspan_cols)을 계산한다
   예: colIndex=2, colSpan=3 → {2, 3, 4}

3. colspan_cols 위치에 rowIndex=1인 독립 셀이 존재하는가?
   (rowIndex=0 rowSpan=2 셀의 fill이 아닌, 실제 row 1 셀)
   → 있으면: n_header_rows = 2
   → 없으면: n_header_rows = 1

반환: 1 또는 2
```

**Step 2 — 컬럼 헤더 구성 (`_build_column_headers`)**

```
n_header_rows == 1: 기존 로직 그대로 (_unique_headers(grid[0], width))

n_header_rows == 2:
  for col_idx in range(width):
    if col_idx in colspan_cols:   # row 0에서 colSpan 병합된 열
        header = grid[1][col_idx]  # row 1 서브헤더 값 사용
    else:                          # row 0에서 rowSpan 셀 또는 단독 셀
        header = grid[0][col_idx]
  → _unique_headers(headers, width) 적용
```

**Step 3 — 데이터 시작 행**

```
data_start = n_header_rows   (1 또는 2)
rows = [grid[i] for i in range(data_start, len(grid))]
```

#### 처리 예시 (p064)

```
raw cells:
  row=0, col=0, rSpan=2, cSpan=1 → "수술명"
  row=0, col=1, rSpan=2, cSpan=1 → "수술해설"
  row=0, col=2, rSpan=1, cSpan=3 → "수술종수"   ← colSpan 감지
  row=1, col=2, rSpan=1, cSpan=1 → "1-3종"       ← 서브헤더
  row=1, col=3, rSpan=1, cSpan=1 → "1-5종"
  row=1, col=4, rSpan=1, cSpan=1 → "신1-5종"

결과:
  n_header_rows = 2
  colspan_cols = {2, 3, 4}
  headers = ['수술명', '수술해설', '1-3종', '1-5종', '신1-5종']
  data starts from grid[2]
```

#### 일반 병합 셀 (rowSpan in data rows)

데이터 행에서 rowSpan > 1인 셀의 값을 이후 행에 전파하는 기존 fill 로직은 유지한다.
colSpan > 1인 데이터 셀도 기존 fill 로직으로 처리한다.
추가 변경 불필요.

---

### Part 2: `src/parser/table_vision_cleaner.py` (신규)

#### 모듈 구조

```python
# 공개 인터페이스
def clean_table_blocks(
    blocks: list[LayoutBlock],
    page_image: PIL.Image,
    client: openai.OpenAI,
    model: str = "gpt-4o-mini",
) -> list[LayoutBlock]:
    """표 블록 리스트를 OpenAI Vision LLM으로 정제하여 반환한다."""
```

#### 처리 흐름 (블록당 1회 API 호출)

```
1. block.block_type == "table"인 블록만 처리
2. page_image.crop(block.bbox)로 표 영역 이미지 추출
3. 이미지를 base64 JPEG로 인코딩 (최대 800px 너비로 리사이즈, 품질 보존)
4. OpenAI Chat Completions API 호출:
   - model: 파라미터 전달값 (기본 gpt-4o-mini)
   - max_tokens: 2048
   - messages[0].content: [
       {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<b64>"}},
       {"type": "text", "text": <프롬프트>}
     ]
5. 응답: response.choices[0].message.content 에서 JSON 추출
6. 파싱 실패 시 원본 block 반환 (graceful degradation)
7. 성공 시 block.table_json, block.text, block.html 갱신
```

#### Vision Prompt

```
당신은 보험 약관 문서의 표를 검토하는 전문가입니다.
첨부 이미지는 표 영역 크롭입니다.

아래 JSON은 이 표의 OCR 추출 결과입니다.
다음 두 가지만 수정하세요:

1. 텍스트가 아닌 그림/도표/해부학적 이미지를 포함하는 셀:
   해당 셀의 텍스트를 "[그림]"으로 대체하세요.
   (셀 안에 그림이 있고 그 그림 위의 레이블 텍스트가 셀 값으로 잘못 인식된 경우)

2. 명백한 OCR 오탈자(문맥상 분명히 틀린 글자):
   올바른 텍스트로 수정하세요.

표 구조(행/열 수, headers 리스트, rows 키 이름)는 절대 변경하지 마세요.
JSON 형식만 반환하고 다른 설명은 출력하지 마세요.

현재 table_json:
{table_json}
```

#### 응답 파싱

- 응답 텍스트에서 `{` ~ `}` 범위 추출 후 `json.loads()` 시도
- 실패(JSON 파싱 오류, 구조 불일치, API 오류) 시 원본 table_json 유지 + 경고 로그 출력
- 성공 시 `block.raw["vision_cleaned"] = True` 추가

#### OpenAI 클라이언트 초기화

- `.env` 파일에서 `OPENAI_API_KEY` 로드 (`Path(__file__).resolve().parents[2] / ".env"`)
- 클라이언트는 호출부에서 생성 후 전달 (모듈 내부에서 직접 초기화하지 않음)
- 기본 모델: `gpt-4o-mini` (Vision 지원, 속도·비용 균형)

---

### Part 3: run 스크립트 통합

#### `run_true_hybrid_local.py` 변경

```python
# 인자 추가
parser.add_argument("--vision-clean", action="store_true", default=False,
                    help="OpenAI Vision LLM으로 표 셀 그림 감지 및 OCR 보정")

# 실행 로직 (기존 blocks 조립 직후)
if args.vision_clean:
    from src.parser.table_vision_cleaner import clean_table_blocks
    import openai
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    blocks = clean_table_blocks(blocks, image, client)
```

#### `run_clova_local.py` 동일 변경

동일한 `--vision-clean` 플래그와 통합 로직 추가.

---

## 5. Validation

```bash
# Part 1: 단위 테스트
pytest tests/test_clova_ocr.py -v -k "header"

# Part 1+2: 전체 테스트
pytest -q
# 기대: 190 passed 이상, 0 failed

# import 확인
python -c "from src.parser.table_vision_cleaner import clean_table_blocks; print('import OK')"

# 다단 헤더 수동 검증 (API 미호출)
python -c "
from src.parser.clova_ocr import _table_to_json

# 수술종수 2단 헤더 시뮬레이션
fake_table = {'cells': [
    {'rowIndex':0,'columnIndex':0,'rowSpan':2,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'수술명'}]}]},
    {'rowIndex':0,'columnIndex':1,'rowSpan':2,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'수술해설'}]}]},
    {'rowIndex':0,'columnIndex':2,'rowSpan':1,'columnSpan':3,
     'cellTextLines':[{'cellWords':[{'inferText':'수술종수'}]}]},
    {'rowIndex':1,'columnIndex':2,'rowSpan':1,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'1-3종'}]}]},
    {'rowIndex':1,'columnIndex':3,'rowSpan':1,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'1-5종'}]}]},
    {'rowIndex':1,'columnIndex':4,'rowSpan':1,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'신1-5종'}]}]},
    {'rowIndex':2,'columnIndex':0,'rowSpan':1,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'봉합술'}]}]},
    {'rowIndex':2,'columnIndex':1,'rowSpan':1,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'설명'}]}]},
    {'rowIndex':2,'columnIndex':3,'rowSpan':1,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'2'}]}]},
    {'rowIndex':2,'columnIndex':4,'rowSpan':1,'columnSpan':1,
     'cellTextLines':[{'cellWords':[{'inferText':'2'}]}]},
]}
result = _table_to_json(fake_table)
print('headers:', result['headers'])
print('row[0]:', result['rows'][0])
assert result['headers'] == ['수술명', '수술해설', '1-3종', '1-5종', '신1-5종'], f'FAIL: {result[\"headers\"]}'
assert result['rows'][0]['수술명'] == '봉합술', f'FAIL row: {result[\"rows\"][0]}'
print('PASS')
"

# Vision 정제 실행 검증 (ANTHROPIC_API_KEY 필요)
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 64 --vision-clean
python -c "
import json
d = json.load(open('reports/ocr_compare/실무가이드/p064_true_hybrid.json'))
for b in d['blocks']:
    if b['block_type'] == 'table':
        print('headers:', b['table_json']['headers'])
        for i,r in enumerate(b['table_json']['rows'][:4]):
            print(f'row[{i}]:', r)
        print('vision_cleaned:', b.get('raw',{}).get('vision_cleaned'))
"
```

---

## 6. Stop rules

- `_table_to_json()` 변경 후 기존 테스트 1건이라도 실패 → 즉시 중단 후 보고
- `clean_table_blocks()` 구현 중 `LayoutBlock` 구조 변경이 필요하면 → 즉시 중단 후 보고
- OpenAI API 호출 시 `401` 오류 → OPENAI_API_KEY 설정 오류로 간주, 중단 후 보고
- Vision 응답이 지속적으로 파싱 실패하면 → graceful degradation(원본 유지) 처리 후 경고 로그로 남기고 계속 진행 (중단하지 않음)
- run 스크립트 변경으로 기존 `--vision-clean` 없이 실행 시 동작이 달라지면 → 즉시 중단 후 보고

---

## 7. Output requirements

보고서(`docs/45_TABLE_MULTIHEADER_VISION_REPORT.md`)에 포함:

1. **변경 파일 목록** — 함수별 1줄 설명
2. **다단 헤더 검증 결과** — 수동 검증 one-liner 출력 (`PASS` 확인)
3. **테스트 결과** — `pytest -q` 전체 출력 붙여넣기
4. **Vision 정제 실행 결과 (p064)** — 적용 전/후 headers + row[0] 비교, `vision_cleaned` 값 확인
5. **잔여 위험** — 없으면 "None"

---

## Git

- 커밋 메시지: `feat(parser): multi-level header detection and vision table cleaner (#45)`
- JSON/HTML 결과 파일 커밋 제외
- `origin/master` 푸시
