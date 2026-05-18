# 명세 44 — 엔드포인트 검증 → OCR 재실행 → HTML 뷰어 갱신 (통합)

## 배경

v43에서 `enableTableDetection: True` 및 네이티브 `tables[]` 경로를 구현했으나,
현재 `reports/ocr_compare/실무가이드/` 의 JSON 파일들은 v43 **이전**에 생성된 데이터다.
따라서 사용자가 HTML 뷰어에서 네이티브 테이블 결과를 볼 수 없다.

이 명세는 세 단계를 순서대로 실행한다.

```
[단계 1] 엔드포인트 호환성 검증
         ↓ (tables[] 비어 있으면 STOP)
[단계 2] CLOVA & True Hybrid OCR 재실행
         ↓
[단계 3] HTML 뷰어 재생성
```

---

## 대상 파일

| 작업 | 파일 |
|------|------|
| 신규 작성 | `scripts/verify_native_table.py` |
| 신규 작성 | `scripts/generate_ocr_html.py` |
| 덮어씀 (실행 결과) | `reports/ocr_compare/실무가이드/p06*_clova.json` |
| 덮어씀 (실행 결과) | `reports/ocr_compare/실무가이드/p06*_true_hybrid.json` |
| 덮어씀 (실행 결과) | `reports/ocr_compare/실무가이드/summary.json` |
| 덮어씀 (실행 결과) | `reports/ocr_compare_v43_review.html` |

**변경 금지**: `src/`, `tests/`, `scripts/run_clova_local.py`, `scripts/run_true_hybrid_local.py`

---

## 단계 1: 엔드포인트 호환성 검증

### 1-1. `scripts/verify_native_table.py` 작성

이 스크립트는 실제 CLOVA API에 p066(표가 있는 페이지)의 이미지를 전송하고,
응답에 `tables[]`가 있는지 확인한다.

**요구사항**:
- `.env` 로드: `Path(__file__).resolve().parents[1] / ".env"` (find_dotenv 사용 금지)
- 이미지 경로: `reports/ocr_compare/실무가이드/p066_original.png`
- `_request_clova()` 직접 호출 (PIL Image로 로드 후 전달)
- 응답의 `tables` 키 유무 및 길이 체크
- 표준 출력으로 아래 형식 출력:
  ```
  [RESULT] tables_found=<True/False> count=<N>
  [SAMPLE] <첫 번째 table의 cells 수>cells / bbox=<boundingPoly vertices 요약>
  ```
- `tables[]`가 비어 있거나 없으면 → **exit code 1**
- `tables[]`가 1개 이상이면 → **exit code 0**

### 1-2. 스크립트 실행

```bash
python scripts/verify_native_table.py
```

출력 결과를 보고서에 그대로 첨부한다.

### 1-3. STOP 규칙

**exit code 1이면 이후 단계 실행 금지.** 보고서에 다음을 기재하고 종료:
- `tables_found=False` 이유 추정 (엔드포인트 미지원 또는 API 설정 문제)
- 권장 조치: CLOVA 도메인 관리자에게 `enableTableDetection` 지원 여부 확인 요청

---

## 단계 2: OCR 재실행 (exit code 0인 경우에만)

### 2-1. CLOVA 재실행

```bash
python scripts/run_clova_local.py --doc 실무가이드 --pages 60-70
```

- 기존 `p0XX_clova.json` 파일을 덮어쓴다
- `summary.json`의 `engines.clova` 갱신됨

### 2-2. True Hybrid 재실행

```bash
python scripts/run_true_hybrid_local.py --doc 실무가이드 --pages 60-70
```

- 기존 `p0XX_true_hybrid.json` 파일을 덮어쓴다
- `summary.json`의 `engines.true_hybrid` 갱신됨

### 네이티브 테이블 확인 기준

재실행 후 `p066_true_hybrid.json`을 파싱하여:
- `blocks[].raw.get("native_table") == True`인 블록이 1개 이상 존재하면 → 네이티브 테이블 경로 정상 동작
- 존재하지 않으면 → 보고서에 `native_table=False` 표기 (CLOVA가 tables[]를 반환했으나 비어 있는 경우)

---

## 단계 3: HTML 뷰어 갱신

### 3-1. `scripts/generate_ocr_html.py` 작성

아래 요구사항을 갖춘 독립 실행 스크립트를 작성한다.

**기능 요구사항**:
- `reports/ocr_compare/<doc_short>/p0*_{engine}.json` 읽기 (engine: true_hybrid, clova, hybrid)
- `reports/ocr_compare/<doc_short>/summary.json` 읽기
- 페이지별 탭 전환 UI (JavaScript)
- 3개 엔진 컬럼 나란히 비교
- 표 블록: `table_json.headers` + `table_json.rows`를 HTML `<table>`로 렌더링
- **네이티브 테이블 구분 표시**:
  - `block.raw.get("native_table") == True` → 헤더에 `🔵 CLOVA 네이티브` 배지 표시
  - 그 외 표 블록 → `🔶 기하학적 재구성` 배지 표시
- 텍스트 블록: 한글비율·노이즈·PASS/MARGINAL/FAIL 배지 표시
- `summary.json`의 엔진별 집계(표 블록 수, 평균 한글비율, grade 분포)를 상단 요약 바에 표시
- `--doc` 인자 (default: `실무가이드`), `--output` 인자 (default: `reports/ocr_compare_v43_review.html`)

**실행 인터페이스**:
```bash
python scripts/generate_ocr_html.py --doc 실무가이드
```

### 3-2. 스크립트 실행

```bash
python scripts/generate_ocr_html.py --doc 실무가이드
```

출력 HTML 경로를 보고서에 기재한다.

---

## 성공 기준

| 기준 | 확인 방법 |
|------|-----------|
| 검증 스크립트 exit code 0 | `echo $?` |
| True Hybrid 재실행 11/11 SUCCESS | 실행 출력 |
| CLOVA 재실행 11/11 SUCCESS | 실행 출력 |
| `p066_true_hybrid.json`에 native_table 블록 ≥ 1 | `python -c "import json; d=json.load(open('reports/ocr_compare/실무가이드/p066_true_hybrid.json')); print(sum(1 for b in d['blocks'] if b.get('raw',{}).get('native_table')))"` |
| HTML 파일 생성 | `ls -lh reports/ocr_compare_v43_review.html` |

---

## 변경 금지 사항

- `.env` 파일 수정 금지
- `src/`, `tests/` 하위 파일 수정 금지
- `scripts/run_clova_local.py`, `scripts/run_true_hybrid_local.py` 수정 금지
- CLOVA API 응답 데이터 변조 금지 (실 응답 그대로 저장)

---

## Git 반영 요청

- 신규 스크립트 2개 (`verify_native_table.py`, `generate_ocr_html.py`)만 커밋
- JSON 결과 파일 및 HTML 파일은 `.gitignore` 여부와 무관하게 커밋 **제외**
- 커밋 메시지: `feat(scripts): add native table verify and html report scripts (#44)`
- `origin/master` 푸시
