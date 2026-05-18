# Codex 명세 #46 — 숫자 셀 Vision 정제 + Streamlit Cloud 인덱스 수정

## 1) Goal

두 가지 독립적인 품질 개선을 구현한다.

**Part 1**: CLOVA OCR이 단선 `1`을 표 세로선과 혼동하여 blank로 처리하는 문제를 해결하기 위해,
수술종수 유형 컬럼이 모두 blank인 행에 한해 OpenAI Vision LLM으로 실제 값을 재판독하는
`numeric_cell_refiner` 모듈을 추가하고 `--vision-clean` 플래그에 연결한다.

**Part 2**: Streamlit Cloud에서 두 SOL 문서가 검색되지 않는 문제를 진단하고 수정한다.
원인은 `chunks.jsonl` / `bm25.pkl`이 SOL 문서를 포함하도록 갱신(`b730b4a`)됐지만
ChromaDB zip(`INDEX_RELEASE_URL`)은 그 이전 버전이라 dense vector 검색에서 두 문서가 누락되는 것이다.
로컬에서 cloud-only 인덱스를 재빌드·패키징하는 스크립트를 추가하고, cloud 부트스트랩 로직을 보강한다.

---

## 2) Background

### Part 1 — 숫자 셀 blank 문제

- p068 등에서 `1-3종` / `1-5종` / `신1-5종` 컬럼이 실제로는 `1` 또는 `2`인데 blank로 기록된다.
- CLOVA OCR은 한 획짜리 `1`을 표 세로 경계선으로 오인해 인식 누락한다.
- v45에서 구현한 Vision 정제(`table_vision_cleaner.py`)는 그림 셀 교정에 집중하고
  수치 재판독은 포함하지 않는다.
- 해결책(Method B): 수술종수 컬럼이 전부 blank인 행만 선택적으로 Vision LLM에 재질의한다.

### Part 2 — Streamlit Cloud 검색 누락

현재 commit 상태:
- `data/processed/chunks.jsonl` — **커밋됨**, SOL 두 문서 포함 (`b730b4a`)
- `data/index/bm25.pkl` — **커밋됨**, SOL 두 문서 포함 (`b730b4a`)
- `data/index/chroma/` — **git 제외**, `INDEX_RELEASE_URL` zip으로 배포

SOL 두 문서(`자사_SOL건강`, `자사_SOL운전자`)는 `cloud_safe=True`이고 `requires_ocr=False`이므로
인덱스에 포함돼야 한다. 그러나 현재 배포된 ChromaDB zip은 `b730b4a` 이전에 패키징된 버전이어서
이 두 문서의 벡터가 없다. 결과적으로 dense search에서 0건 반환 → RAG 파이프라인에서 검색 실패.

---

## 3) Target Files

### 신규 생성
- `src/parser/numeric_cell_refiner.py`
- `scripts/build_cloud_index.py`
- `tests/test_numeric_cell_refiner.py`

### 수정 허용
- `src/parser/table_vision_cleaner.py` — `clean_table_blocks()`가 numeric refine도 순차 호출하도록 (또는 두 함수를 별도 호출로 유지)
- `scripts/run_true_hybrid_local.py` — `--vision-clean` 시 numeric refine 연결
- `scripts/run_clova_local.py` — 동일
- `scripts/generate_ocr_html.py` — 수치 정제 배지 렌더링 추가
- `scripts/bootstrap_assets.py` — `REBUILD_INDEX_FROM_CHUNKS` 환경변수 지원 추가

### 수정 금지
- `src/parser/ocr_engine.py`
- `src/parser/clova_ocr.py`
- `src/config.py`
- 그 외 `src/` 파일 (위 허용 목록 외)

---

## 4) Detailed Requirements

---

### Part 1: `src/parser/numeric_cell_refiner.py`

#### 4-1. 컬럼 패턴 매칭

아래 패턴 중 하나라도 컬럼명에 포함되면 "수술종수 유형" 컬럼으로 분류한다.

```python
NUMERIC_COL_PATTERNS = [
    r"^(1|2|3)-[0-9]+종$",   # "1-3종", "1-5종", "신1-5종"
    r"^신[0-9]+-[0-9]+종$",
    r"^수술종수",              # "수술종수", "수술종수_2", "수술종수_3"
]
```

#### 4-2. 트리거 조건

다음 조건을 **모두** 만족하는 행에 대해서만 Vision LLM 재판독을 수행한다.

1. 해당 table block에 수술종수 유형 컬럼이 1개 이상 존재한다.
2. 해당 데이터 행의 수술종수 유형 컬럼 **전부**가 `""` (공백).
3. 같은 행에서 `수술명` 또는 `수술해설` 컬럼에 비어있지 않은 텍스트가 있다. (헤더 오인 방지)

조건 2에서 "전부 blank"인 행이 하나도 없는 table block은 Vision LLM 호출 없이 그대로 반환한다.

#### 4-3. Vision LLM 프롬프트

```
당신은 보험 약관 표의 수술종수 컬럼 값을 판독하는 전문가입니다.
첨부 이미지는 해당 표 영역의 크롭입니다.

아래 JSON에서 blank("")로 기록된 수술종수 컬럼들이 실제 이미지에는
어떤 값(1, 2, 3 또는 공란)이 적혀 있는지 확인하여 채워주세요.

규칙:
- 허용 값: "1", "2", "3", "" (진짜 공란인 경우)
- 수술종수 이외 컬럼은 절대 변경하지 마세요.
- 표 구조(headers, row 수, key 이름)는 변경하지 마세요.
- 수정한 셀에 대해서만 rows[i]["_corrections"][col] = {"from": "", "to": "새값"} 형태로
  메타 정보를 추가하세요. ("_corrections" 키는 rows 내 임의 추가 허용)
- JSON 형식만 반환하고 다른 설명은 출력하지 마세요.

현재 table_json:
{table_json}
```

#### 4-4. 결과 처리

- Vision LLM 응답에서 `rows[i]["_corrections"]`가 있으면 해당 셀 값을 적용한다.
- 수정 내역을 `block.raw["numeric_corrections"]`에 기록한다:
  ```python
  block.raw["numeric_corrections"] = [
      {"row_index": i, "col": "1-3종", "from": "", "to": "1"},
      ...
  ]
  ```
- `block.raw["numeric_refined"] = True`로 설정한다.
- `block.text`와 `block.html`을 갱신한다 (`_table_to_text`, `_table_json_to_html` 재호출).
- Vision LLM 응답이 유효하지 않거나 API 오류 시 원본 block을 그대로 반환하고 WARNING 로그.

#### 4-5. 공개 함수 시그니처

```python
def refine_numeric_cells(
    blocks: list[LayoutBlock],
    page_image: PIL.Image.Image,
    client: Any,                  # openai.OpenAI
    model: str = "gpt-4o-mini",
) -> list[LayoutBlock]:
    """수술종수 컬럼이 전부 blank인 행을 Vision LLM으로 재판독한다."""
```

`table_vision_cleaner.TableVisionCleanerAuthError`와 동일한 401 처리 패턴을 적용할 것.
`NumericCellRefinerAuthError(RuntimeError)`를 동 모듈 내에 정의한다.

#### 4-6. run script 연결

`scripts/run_true_hybrid_local.py`와 `scripts/run_clova_local.py`에서
`--vision-clean` 플래그가 활성화된 경우 `clean_table_blocks()` 호출 **다음에** `refine_numeric_cells()`를 호출한다.

```python
if args.vision_clean:
    from src.parser.table_vision_cleaner import clean_table_blocks
    from src.parser.numeric_cell_refiner import refine_numeric_cells
    import openai as _openai
    _client = _openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    blocks = clean_table_blocks(blocks, image, _client)
    blocks = refine_numeric_cells(blocks, image, _client)
```

#### 4-7. HTML 배지

`scripts/generate_ocr_html.py`에서 `block.raw.get("numeric_refined")`이 `True`이면
`✏️ 숫자 정제` 배지를 추가한다. `vision_cleaned`가 동시에 True이면 두 배지를 모두 표시한다.

---

### Part 2: Streamlit Cloud 인덱스 수정

#### 4-8. 진단 스크립트 (선택, 권장)

`scripts/check_cloud_index.py`를 작성해 다음을 출력한다.

- `chunks.jsonl` 내 doc_short 별 청크 수
- ChromaDB 내 doc_short 별 벡터 수 (비어 있으면 0으로 표시)
- BM25 인덱스 내 doc_short 별 문서 수
- 누락 문서 요약

#### 4-9. 클라우드 인덱스 재빌드 스크립트

`scripts/build_cloud_index.py`를 작성한다.

```
python scripts/build_cloud_index.py [--zip-output PATH]
```

동작:
1. `config.INDEXED_PDF_SOURCES` (cloud_safe=True, requires_ocr=False) 문서만 대상으로 한다.
2. `data/processed/chunks.jsonl`에서 해당 doc_short 청크만 필터링하여 로드한다.
3. `Embedder(config.EMBEDDING_MODEL)`로 임베딩 생성.
4. `VectorStore(config.CHROMA_DIR, reset=True)`에 저장.
5. `BM25Index`를 동일 청크로 재빌드하여 `config.BM25_PATH`에 저장.
6. `--zip-output` 경로가 지정되면 `data/index/chroma/` 디렉토리를 zip으로 패키징.
   (chunks.jsonl, bm25.pkl은 이미 커밋되어 있으므로 zip에 포함 불필요)

Load `.env` with `Path(__file__).resolve().parents[1] / ".env"`.

#### 4-10. `bootstrap_assets.py` 보강

`main()` 내에 `REBUILD_INDEX_FROM_CHUNKS` 환경변수 지원을 추가한다.

```python
if os.getenv("REBUILD_INDEX_FROM_CHUNKS", "false").lower() == "true":
    if not (config.CHROMA_DIR.exists() and any(config.CHROMA_DIR.iterdir())):
        print("ChromaDB가 비어있습니다. chunks.jsonl에서 인덱스를 재빌드합니다...")
        from scripts.build_cloud_index import rebuild_from_chunks
        rebuild_from_chunks()
        print("인덱스 재빌드 완료")
    else:
        print("ChromaDB 존재 - 재빌드 스킵")
    return 0
```

`build_cloud_index.py`에 `rebuild_from_chunks()` 함수를 추가로 공개 노출한다.

기존 `INDEX_RELEASE_URL` 경로는 변경하지 않는다 (`REBUILD_INDEX_FROM_CHUNKS`가 False이거나 미설정이면 기존 로직 유지).

---

## 5) Validation

### Part 1 유효성 검사

```bash
# 1. 단위 테스트
pytest tests/test_numeric_cell_refiner.py -v

# 2. 기존 테스트 회귀
pytest tests/test_table_vision_cleaner.py tests/test_clova_ocr.py -q

# 3. 전체 회귀
pytest -q
# 목표: 기존 193개 + 신규 ≥ 4개, 실패 0건

# 4. 모듈 임포트 확인
python -c "from src.parser.numeric_cell_refiner import refine_numeric_cells; print('OK')"

# 5. end-to-end (--vision-clean 플래그로 숫자 정제 포함)
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 68 --vision-clean
# → numeric_refined=True 블록이 1개 이상 있어야 함
# → 수술종수 컬럼에 "1" 또는 "2" 값이 채워져야 함
```

### Part 2 유효성 검사

```bash
# 1. 진단
python scripts/check_cloud_index.py
# → 자사_SOL건강, 자사_SOL운전자 모두 ChromaDB에 0인지 확인

# 2. 재빌드 (로컬 — 임베딩 모델 필요)
python scripts/build_cloud_index.py
# → ChromaDB에 자사_SOL건강, 자사_SOL운전자 벡터가 생성돼야 함

# 3. 재진단
python scripts/check_cloud_index.py
# → 자사_SOL건강, 자사_SOL운전자 모두 벡터 수 > 0 이어야 함

# 4. bootstrap 경로 테스트 (ChromaDB를 임시로 비운 뒤)
REBUILD_INDEX_FROM_CHUNKS=true python scripts/bootstrap_assets.py
# → "인덱스 재빌드 완료" 출력
```

---

## 6) Stop Rules

- `pytest -q`에서 기존 테스트가 1건이라도 실패 → 즉시 중단, 보고
- `LayoutBlock` 구조 변경이 필요하다고 판단되는 경우 → 중단, 보고
- `--vision-clean` 없이 실행 시 동작이 변경되는 경우 → 중단, 보고
- OpenAI 401 발생 시 → `NumericCellRefinerAuthError` raise, 중단 조건 아님 (graceful)
- `src/parser/ocr_engine.py`, `src/parser/clova_ocr.py`, `src/config.py` 수정이 필요한 경우 → 중단, 보고
- 임베딩 모델 다운로드가 필요한데 환경에 없는 경우 → `build_cloud_index.py`는 명확한 오류 메시지로 종료 (앱 코드는 수정하지 않음)

---

## 7) Output Requirements

구현 완료 후 `docs/46_NUMERIC_REFINER_CLOUD_REPORT.md`를 작성하고 커밋한다.

보고서 포함 항목:
1. 변경된 파일 목록 (함수별 한 줄 설명)
2. `pytest -q` 전체 출력 (통과 수 명시)
3. p068 수정 전후 비교 (해당 rows에서 수술종수 컬럼 값)
4. `check_cloud_index.py` 출력 — 재빌드 전/후 비교
5. `block.raw["numeric_refined"]` 및 `block.raw["numeric_corrections"]` 샘플
6. 잔여 블로커 (없으면 "None")

JSON 결과 파일과 HTML 파일은 커밋하지 않는다.
ChromaDB 디렉토리(`data/index/chroma/`)는 커밋하지 않는다.
