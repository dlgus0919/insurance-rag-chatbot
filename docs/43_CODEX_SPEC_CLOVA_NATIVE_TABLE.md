# 명세 43 — CLOVA 네이티브 테이블 감지 통합

## 배경 및 목적

팀원이 작성한 `insurance-rag-ocr-changes-20260508/` 폴더의 코드를 검토한 결과, 현재 프로젝트의 `src/parser/clova_ocr.py`에 두 가지 중대한 결함이 확인됐다.

1. **`_cell_words_text()` 버그**: CLOVA API 응답의 실제 키를 잘못 참조하고 있어 표 셀 텍스트를 항상 빈 문자열로 반환함
2. **`enableTableDetection` 미사용**: CLOVA 네이티브 표 감지 기능을 활성화하지 않아 기하학적 재구성(`reconstruct_table_from_fields()`)에만 의존 — 컬럼 과분할(5열 → 7열) 문제 발생

팀원의 `parse_clova_ocr_outputs.py`에서 올바른 키와 네이티브 테이블 파싱 로직을 확인했다. 이번 명세는 해당 수정을 프로젝트에 통합한다.

---

## 대상 파일

| 파일 | 변경 종류 |
|------|-----------|
| `src/parser/clova_ocr.py` | 버그 수정 + 기능 추가 |
| `tests/test_clova_ocr.py` | 테스트 픽스처 수정 + 신규 테스트 추가 |

**변경 금지 파일**: `scripts/run_true_hybrid_local.py`, `scripts/run_clova_local.py`, `src/parser/ocr_preprocessor.py`, 기타 모든 파일

---

## 변경 사항 상세

### 변경 1: `_cell_words_text()` 버그 수정

**위치**: `src/parser/clova_ocr.py`

**현재 코드 (버그)**:
```python
def _cell_words_text(cell):
    lines = []
    for line in cell.get("cellTextLines", []):
        words = []
        for word in line.get("words", []):          # ← WRONG KEY
            text = str(word.get("text", "")).strip() # ← WRONG KEY
            if text:
                words.append(text)
        if words:
            lines.append(" ".join(words))
    return "\n".join(lines)
```

**수정 후**:
```python
def _cell_words_text(cell):
    lines = []
    for line in cell.get("cellTextLines", []):
        words = []
        for word in line.get("cellWords", []):           # ← 수정
            text = str(word.get("inferText", "")).strip() # ← 수정
            if text:
                words.append(text)
        if words:
            lines.append(" ".join(words))
    return "\n".join(lines)
```

**근거**: CLOVA API 실제 응답 구조:
- `cellTextLines[n].cellWords` (not `words`)
- `cellWords[n].inferText` (not `text`)

`data/ocr_preview_clova/Claim/raw_responses/page_006.json` 로 직접 확인됨:
```
cellTextLine keys: ['boundingPoly', 'inferConfidence', 'cellWords']
cellWord keys: ['boundingPoly', 'inferText', 'inferConfidence']
```

---

### 변경 2: `_request_clova()` — `enableTableDetection` 추가

**위치**: `src/parser/clova_ocr.py`의 `_request_clova()` 함수

CLOVA API payload의 최상위 레벨에 `"enableTableDetection": True`를 추가한다.

**현재 payload 구성** (multipart/form-data 방식이므로 message JSON에 포함):
```python
message = {
    "version": "V2",
    "requestId": str(uuid.uuid4()),
    "timestamp": int(time.time() * 1000),
    "lang": "ko",
    "images": [...],
}
```

**수정 후**:
```python
message = {
    "version": "V2",
    "requestId": str(uuid.uuid4()),
    "timestamp": int(time.time() * 1000),
    "lang": "ko",
    "enableTableDetection": True,   # ← 추가
    "images": [...],
}
```

**근거**: 팀원의 `clova_ocr_preview_claim.py` 및 `data/ocr_preview_clova/Claim/manifest.json`에서 `enable_table_detection: True`가 실제로 동작함을 확인. 이 플래그가 있어야 응답에 `tables[]` 배열이 포함된다.

---

### 변경 3: `clova_ocr_page()` — 네이티브 테이블 우선 경로 추가

**위치**: `src/parser/clova_ocr.py`의 `clova_ocr_page()` 함수

현재 로직은 표 region에 대해 항상 `reconstruct_table_from_fields()`를 호출한다. CLOVA가 `tables[]`를 반환하면 이를 우선 사용하고, 비어 있으면 기존 기하학적 방법으로 폴백한다.

**처리 흐름 (수도코드)**:

```python
# CLOVA 응답에서 네이티브 tables 추출
native_tables = image_result.get("tables") or []

# 네이티브 테이블이 있을 때
if native_tables:
    # 네이티브 테이블 처리
    for table in native_tables:
        block = _table_to_json(table)   # 기존 함수 재사용 (버그 수정 후 정상 동작)
        # bbox: table["boundingPoly"]["vertices"] → [x1,y1,x2,y2]
        # block_type: "table"
        blocks.append(block)

    # 네이티브 테이블 bbox에 속하는 fields를 used_indices에 추가
    # (기존 텍스트 블록 조립 시 중복 제거에 사용)
    for table in native_tables:
        table_bbox = vertices_to_bbox(table["boundingPoly"]["vertices"])
        for idx, field in enumerate(fields):
            if field_in_bbox(field, table_bbox):
                used_indices.add(idx)

# 네이티브 테이블이 없을 때 (폴백)
else:
    # 기존 로직: layout region이 table인 경우 reconstruct_table_from_fields() 호출
    for region in layout_regions:
        if region.block_type == "table":
            ...reconstruct_table_from_fields(...)
```

**bbox 변환 헬퍼** (`vertices_to_bbox`): CLOVA `boundingPoly.vertices` 형식(`[{x,y}, ...]`)을 `[x1, y1, x2, y2]`로 변환. 이미 `clova_ocr.py` 내부에 유사 로직이 있으면 재사용한다.

**`field_in_bbox`**: field의 boundingPoly 중심점이 table bbox 내부에 있으면 True.

---

### 변경 4: `tests/test_clova_ocr.py` — 픽스처 키 수정

**위치**: `tests/test_clova_ocr.py`의 `test_table_to_json_merges_cells_and_serializes_rows` 테스트

**현재 테스트 픽스처 (잘못된 키)**:
```python
"cellTextLines": [{"words": [{"text": "수술종수"}]}]
```

**수정 후**:
```python
"cellTextLines": [{"cellWords": [{"inferText": "수술종수"}]}]
```

이 수정이 없으면 변경 1 적용 후 기존 테스트가 실패한다.

---

### 변경 5: `tests/test_clova_ocr.py` — 신규 테스트 추가

다음 두 가지 신규 테스트를 추가한다:

**테스트 A — `enableTableDetection` 페이로드 포함 검증**:
```python
def test_request_clova_includes_enable_table_detection(monkeypatch):
    """_request_clova()가 보내는 message에 enableTableDetection이 True로 포함되는지 검증"""
    captured = {}
    def fake_post(url, **kwargs):
        # multipart data에서 message JSON 추출하여 captured에 저장
        ...
        return FakeResponse({"images": [{"fields": [], "tables": []}]})
    monkeypatch.setattr(requests, "post", fake_post)
    # _request_clova() 호출 후 captured["message"]["enableTableDetection"] == True 확인
```

**테스트 B — 네이티브 테이블 우선 경로 검증**:
```python
def test_clova_ocr_page_uses_native_tables_when_present(monkeypatch):
    """tables[]가 있으면 reconstruct_table_from_fields()를 호출하지 않고 네이티브 테이블을 사용"""
    # native_tables가 있는 fake CLOVA 응답 구성
    # reconstruct_table_from_fields 호출 여부 spy
    # clova_ocr_page() 호출
    # assert: reconstruct_table_from_fields 미호출
    # assert: 반환된 blocks에 block_type=="table" 존재
```

---

## 성공 기준

1. `pytest tests/test_clova_ocr.py -v` — 모든 기존 테스트 PASS + 신규 테스트 2개 PASS
2. `pytest -q` — 전체 회귀 186 passed 이상, 0 failed
3. `python -c "import src.parser.clova_ocr; print('import OK')"` — 성공
4. `_cell_words_text({"cellTextLines": [{"cellWords": [{"inferText": "테스트"}]}]})` → `"테스트"` 반환 확인

---

## 변경 금지 사항

- `_table_to_json()` 함수 시그니처 변경 금지
- `reconstruct_table_from_fields()` 삭제 금지 (폴백 경로에서 사용)
- `scripts/` 폴더 내 파일 수정 금지
- CLOVA API 실제 호출 실행 금지 (테스트는 모두 mock/monkeypatch 사용)
- 기존 `clova_ocr_page()` 반환 타입/인터페이스 변경 금지

---

## Git 반영 요청

구현 완료 후 커밋 및 `origin/master` 푸시.
커밋 메시지: `fix(clova): enable native table detection, fix _cell_words_text keys (#43)`
