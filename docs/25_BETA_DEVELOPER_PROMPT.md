# 베타 개발자 첫 단계 전달 명세 — 통합 보상 DB 구축의 1단계

> **작성:** 기획자
> **작성일:** 2026-05-07
> **대상:** 신규 베타 개발자(Codex 에이전트)
> **목적:** 알파 완료 상태의 보험 문서 RAG 챗봇을 "통합 보험 보상 DB(VectorDB + GraphDB + 관계형 + 객체 저장)" 베이스로 전환하기 위한 **첫 번째 단계** 작업 지시.
> **이 명세는 첫 단계만 다룬다.** 이후 단계(OCR 본격, 그래프 구축, 약관 비교, 과제 2)는 본 단계 완료 후 별도 명세로 전달한다.

---

## 1. 필수 사전 조치 (작업 본격 시작 전, 무조건 먼저 수행)

본 단계는 알파 코드베이스를 만지기 시작하는 첫 시점이므로 **롤백 안전망**과 **원본 자료 보호**가 다른 모든 작업보다 우선한다.

### 1.1 알파 폴더 전체 백업 (롤백 가능 상태 확보)

알파 완성 시점의 코드베이스를 별도 위치에 *완전 사본*으로 보관한다.

```bash
# 프로젝트 루트에서
ts=$(date +%Y%m%d_%H%M%S)
backup_dir="../insurance_rag_backup/alpha_v1_${ts}"
mkdir -p "$backup_dir"
# .git, data/, logs/, .venv 등을 포함한 전체 폴더를 별도 디렉토리로 복사
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
      ./ "$backup_dir/"
# 원본 PDF 자산은 추가로 별도 압축 저장 (배포 자산 보존)
zip -r "$backup_dir/raw_pdfs_and_assets.zip" \
       *.pdf *.xlsx data/index 2>/dev/null || true
```

요건:

- 백업은 **프로젝트 폴더 외부**에 저장 (git tracked 영역 외)
- 백업 후 `${backup_dir}/CHECKSUMS.txt`에 모든 파일의 sha256 해시 기록
- 본 단계 PR에 백업 위치·시각·체크섬 요약을 보고서로 첨부 (실제 백업 자료는 보고서에 포함하지 말고 경로만)
- 백업이 비어 있거나 실패하면 본 단계의 어떤 코드 변경도 시작 금지

### 1.2 원본 파일 GitHub 업로드 절대 금지

다음 파일은 **GitHub에 절대 푸시되지 않아야 한다**. 라이선스·사내 자료·파일 크기 모두 위험.

대상 (프로젝트 루트의 모든 PDF·XLSX와 향후 추가될 원본 자료):

```
*.pdf
*.xlsx
*.xls
data/raw/**
data/extracted/**
backup/**
```

조치:

- `.gitignore`에 위 패턴이 모두 포함되어 있는지 확인. 누락 시 추가.
- 추가로 `.gitignore` 같은 디렉토리에 다음 안전망 추가:
  ```
  # 원본 자료 — GitHub 푸시 금지
  /*.pdf
  /*.xlsx
  /*.xls
  /data/raw/
  /data/extracted/
  /backup/
  ```
- 신규 pre-commit 훅 또는 간단 검사 스크립트 `scripts/check_raw_assets.py`를 추가:
  - `git diff --cached --name-only` 결과에 위 패턴이 포함되면 차단·에러 종료
  - README에 "원본 자료는 GitHub에 절대 푸시 금지" 1줄 안내 추가
- 본 단계 PR에서 `git ls-files | grep -E '\.(pdf|xlsx|xls)$'` 결과가 **빈 결과**임을 보고서에 명시

### 1.3 데이터 디렉토리 표준화 (정리만 수행, 파일 이동은 보수적으로)

향후 단계에서 사용할 표준 디렉토리를 미리 정의하고 빈 디렉토리만 생성. 실제 자료 이동은 본 단계에서 수행하지 않는다(알파 동작 보호).

```
data/
├── raw/                     # 원본 PDF/XLSX (현재는 프로젝트 루트에 산재해 있음 — 본 단계에서는 이동 금지)
├── extracted/               # OCR/추출 산출물 (페이지별 텍스트·표 JSON·이미지)
├── index/
│   ├── chroma/              # 기존 (유지)
│   ├── bm25.pkl             # 기존 (유지)
│   ├── graph/               # 신설 — 그래프 직렬화 (NetworkX/Neo4j export)
│   └── relational/          # 신설 — SQLite 또는 DuckDB
└── processed/               # 기존 (유지)
```

- `data/extracted/`, `data/index/graph/`, `data/index/relational/`만 빈 디렉토리(`.gitkeep`)로 생성
- 기존 `data/processed/`, `data/index/chroma/`, `data/index/bm25.pkl`은 손대지 않는다

---

## 2. 첫 단계 작업 범위 (본 단계의 산출)

본 단계의 목표는 **"향후 단계의 토대"**를 까는 것. OCR 본격 처리·GraphDB 본격 구축은 다음 단계.

### 2.1 원본 데이터 카탈로그 검증 (`docs/26_RAW_DOCUMENTS_CATALOG.md` 기준)

기획자가 작성한 카탈로그(D1~D8)에 대해 다음을 실측해 검증·갱신한다.

- 각 PDF의 페이지 수, 텍스트 레이어 비율, 표·이미지 영역 통계
- 비급여 엑셀의 행 수·시트 수·컬럼 정합성
- 결과를 `docs/26_RAW_DOCUMENTS_CATALOG.md`의 1·2장 표에 *수치로 보강*하는 PR. 기존 카탈로그를 보존하면서 측정 결과만 추가.

검증 도구는 기존 의존성(`pdfplumber`, `pymupdf`, `openpyxl`)으로 충분. 외부 OCR/Vision 호출은 본 단계에서 금지.

### 2.2 비급여 표준 모델 엑셀 → 관계형 DB 1차 적재 (마스터 데이터)

D8(`비급여표준모델_전체판...xlsx`)을 SQLite로 변환해 통합 DB의 첫 관계형 자산을 만든다.

```
산출:
- scripts/build_relational_db.py
- data/index/relational/standard_codes.sqlite
- src/db/standard_codes.py  (간단한 read 헬퍼)
- tests/test_standard_codes.py
```

요건:

- 테이블명: `nonpay_standard`
- 컬럼: 엑셀 영문 키와 동일 (`std_cd`, `std_cd_nm`, `mid_category_cd`, …)
- 인덱스: `std_cd` (UNIQUE), `mid_category_cd`, `medical_class_cd`, `apply_start_date`
- 헬퍼 함수:
  ```python
  def lookup_by_std_cd(std_cd: str) -> dict | None: ...
  def search_by_name(keyword: str, limit: int = 50) -> list[dict]: ...
  def list_categories() -> list[tuple[str, str]]: ...   # mid_category_cd 분포
  ```
- 본 단계에서는 *DB 적재와 read 헬퍼*까지만. UI/검색 통합은 다음 단계.

### 2.3 청크 메타 스키마 확장 (정의만, 인덱스 재생성은 다음 단계)

향후 단계에서 사용할 메타 필드 정의를 코드에 도입한다. 기존 청크는 영향받지 않도록 **누락 시 None**을 허용한다.

확장 메타 (모두 옵션):

```python
# src/parser/chunker.py 또는 src/config.py
EXTENDED_META_FIELDS = [
    "insurance_company",     # str | None
    "is_own_company",        # bool | None
    "product_name",          # str | None
    "product_type",          # str | None  (실손/건강/상해/운전자/여행/장기치료)
    "effective_date",        # str | None  (ISO YYYY-MM-DD)
    "version",               # str | None
    "coverage_category",     # str | None  (질병급여/질병비급여/3대비급여/상해급여/...)
    "clause_type",           # str | None  (보상하는 사항/보상하지 않는 사항/면책/정의/...)
    "content_type",          # "text"|"table"|"image"|"formula"  (기본 "text")
    "source_method",         # "native"|"ocr_paddle"|"ocr_clova"|"ocr_upstage"|"vision_llm"|"manual"
    "confidence",            # float | None
    "bbox",                  # [x0,y0,x1,y1] | None
    "linked_std_cds",        # list[str] | None  (D8 표준코드 매핑)
]
```

요건:

- 기존 `Chunk.metadata` 구조 유지하면서 위 필드를 *옵션*으로 받아들이도록 확장
- chunker가 PDF 처리 중 자연스럽게 채울 수 있는 필드(`content_type="text"`, `source_method="native"`)는 기본값 자동 주입
- 나머지 필드는 다음 단계에서 메타 yaml/csv로 주입할 예정 — 본 단계는 *받아들이는 그릇만* 마련
- 단위 테스트로 라운드트립(JSONL save/load) 호환성 확인

### 2.4 새 자료 등록만 (실제 인덱싱은 다음 단계)

`src/config.py`의 `PDF_SOURCES` 또는 별도 카탈로그 파일에 D3·D4·D6·D7·D8을 *등록만* 한다. 실제 인덱싱은 다음 단계.

```python
# src/config.py 또는 data/sources.yaml
PDF_SOURCES = [
    PdfSource(... 기존 D1, D2, D5 ...),
    # 신규 등록 — 인덱싱은 다음 단계 OCR/메타 확장 단계에서
    PdfSource(path=ROOT_DIR/"2.약관_신한 SOL 처음건강보험(무배당)(자동갱신형)_20260101.pdf",
              doc_short="자사_SOL건강", doc_type="insurance_policy",
              insurance_company="신한EZ", is_own_company=True,
              product_type="건강", effective_date="2026-01-01",
              cloud_safe=True),
    PdfSource(path=ROOT_DIR/"2.약관_신한 SOL 처음운전자보험(무배당)_20260101.pdf",
              doc_short="자사_SOL운전자", doc_type="insurance_policy",
              insurance_company="신한EZ", is_own_company=True,
              product_type="운전자", effective_date="2026-01-01",
              cloud_safe=True),
    PdfSource(path=ROOT_DIR/"Claim 실무종합가이드.pdf",
              doc_short="실무가이드", doc_type="ops_guide_scanned",
              insurance_company="신한EZ", is_own_company=True,
              cloud_safe=False, requires_ocr=True),
    PdfSource(path=ROOT_DIR/"소비자 상담 주요 사례집.pdf",
              doc_short="상담사례집", doc_type="case_book_scanned",
              cloud_safe=True, requires_ocr=True),
]
```

`PdfSource` 데이터클래스에 누락된 옵션 필드(`insurance_company`, `is_own_company`, `product_type`, `effective_date`, `version`, `cloud_safe`, `requires_ocr`)를 모두 추가한다. 기존 항목은 None/기본값으로 호환.

### 2.5 README 갱신

새 베타 단계 진입을 표시:

- "현재 단계: 베타 1 — 통합 DB 구축 1단계 (마스터 데이터 적재 + 메타 스키마 확장)"
- 백업·원본 자료 푸시 금지 1줄 안내
- 신규 의존성(있다면) 안내

---

## 3. 검증 기준 (자가 점검 후 PR 보고)

### 3.1 자동 검증

```bash
# 1) 회귀 테스트
pytest -q --ignore=tests/test_vector_store.py

# 2) 신규 모듈 테스트
pytest -q tests/test_standard_codes.py

# 3) 원본 자료 미커밋 확인
git ls-files | grep -E '\.(pdf|xlsx|xls)$'   # 결과: 빈 출력이어야 함

# 4) Streamlit 부팅 회귀
streamlit run src/ui/streamlit_app.py --server.headless true &
sleep 8; curl -s http://localhost:8501 | head -5; kill %1
```

### 3.2 수동 점검

- [ ] 알파 백업 폴더가 프로젝트 외부에 존재하고 CHECKSUMS.txt가 갖춰져 있다
- [ ] `.gitignore`에 원본 자료 패턴이 모두 포함되어 있다
- [ ] `scripts/check_raw_assets.py`가 의도적으로 PDF를 stage했을 때 차단한다
- [ ] `data/index/relational/standard_codes.sqlite`가 생성되고 행 수가 ~529,000 (±1%) 이다
- [ ] `lookup_by_std_cd("050000011")` 호출이 D3베이스주 row를 반환한다
- [ ] 기존 알파 일반 질의/퀵 코드/약관 정형 검색이 모두 정상 동작 (회귀 없음)
- [ ] Streamlit Cloud 배포가 깨지지 않는다 (PR 머지 후 1분 내 구동 확인)

### 3.3 PR 보고서 양식 (`docs/27_BETA_STAGE1_REPORT.md` 신규 생성)

```
# 베타 1단계 구현 보고

## 1. 백업 결과
- 백업 위치: ../insurance_rag_backup/alpha_v1_YYYYMMDD_HHMMSS
- 체크섬 요약: SHA256 NN개 파일 기록 완료
- 백업 폴더 크기: NNN MB

## 2. 원본 자료 보호
- .gitignore 패턴 추가: ...
- pre-commit 검사 결과: 통과
- git ls-files 결과: PDF/XLSX 0건

## 3. 카탈로그 검증 결과
- D1~D8 페이지 수·텍스트 레이어 비율 측정값:
  ...

## 4. 비급여 표준 모델 적재
- 행 수: 529,022
- 적재 시간: NN초
- 인덱스 크기: NN MB
- 헬퍼 호출 sample: lookup_by_std_cd("050000011") = ...

## 5. 메타 스키마 확장
- 추가 필드: insurance_company, content_type, source_method 등
- 라운드트립 테스트: 통과

## 6. 신규 자료 등록
- D3·D4·D6·D7 PDF_SOURCES 등록 (인덱싱은 다음 단계)

## 7. 회귀 테스트
- pytest: 119 + N passed
- Streamlit Cloud 부팅 확인: OK

## 8. 다음 단계 권고
- (있다면)
```

---

## 4. 보안 및 배포 주의

- 실제 OpenAI API 키, 실제 사용자 비밀번호 hash, 실제 `USERS_JSON`을 절대 커밋 금지
- `assets.zip`, `data/chat_history/`도 커밋 금지 (기존 정책 유지)
- **원본 PDF/XLSX, OCR 추출본, 백업 디렉토리** 모두 커밋 금지 (1.2 참조)
- 커밋 전 검사:
  ```bash
  rg -n "s[k]-|s[k]-proj-|pbkdf2-sha256\\$29000" README.md docs src tests .env.example
  git ls-files | grep -E '\.(pdf|xlsx|xls)$'
  ```
- 둘 다 빈 결과여야 머지 가능

---

## 5. 명세 외 / 임의 시작 금지 항목

본 단계에서는 다음 작업을 절대 시작하지 않는다 (다음 단계 명세에서 별도 전달):

- OCR 파이프라인 본격 구축 (PaddleOCR/CLOVA/Upstage 통합) — 다음 단계
- GraphDB 본격 구축 (Neo4j/NetworkX 그래프 모델·데이터 적재) — 다음다음 단계
- 다중 약관 자동 인덱싱 (`scripts/ingest_batch.py`)·약관 비교 모드 — 다음 단계군 후반
- 과제 2(영수증·진단서 처리)·EDI 매핑 본격 구현 — 별도 트랙
- exaone3.5 등 7B+ 로컬 모델 클라우드 호스팅 — 캡스톤 범위 외
- 마이크로서비스·자체 GPU·외부 객체 저장소 — 회사 확장 범위

---

## 6. 본 단계 완료 후의 다음 단계 미리보기 (참고만)

본 단계 PR이 머지되면 다음 명세를 기획자가 별도 작성한다. 큰 그림만 미리 알린다:

1. **단계 2 — 스캔본 OCR 파이프라인**: PaddleOCR + PP-Structure로 D6·D7 처리, 텍스트·표·이미지 분리 추출, 노이즈 필터, 추출 산출물 `data/extracted/<doc_id>/` 표준화
2. **단계 3 — 신규 약관 인덱싱·메타 적용**: D3·D4·D6·D7 인덱싱, 메타 강화 적용, 사이드바 자사·타사 토글 등
3. **단계 4 — GraphDB 도입 평가 + PoC**: 4.3 신호표 기준 평가 → PoC 구축(NetworkX 또는 Neo4j Community)
4. **단계 5 — 약관 비교 모드 + 환각 방지 강화**
5. **단계 6 — 베타 배포** (캡스톤 1차 산출 완성 시점)
6. **단계 7+ — 과제 2 진입**

각 단계는 본 단계 완료 후 별도 명세로 전달된다.

---

*본 명세는 `docs/26_RAW_DOCUMENTS_CATALOG.md`와 짝을 이룬다. 카탈로그를 먼저 읽고 본 명세를 따라 작업하라.*
