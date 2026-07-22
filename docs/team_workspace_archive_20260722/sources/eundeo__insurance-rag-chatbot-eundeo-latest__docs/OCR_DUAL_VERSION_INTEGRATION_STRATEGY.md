# OCR 이중 버전 통합 전략 (Original + V2_Manual)

## 목차
1. [현황 분석](#현황-분석)
2. [통합 아키텍처](#통합-아키텍처)
3. [구현 단계](#구현-단계)
4. [품질 게이트](#품질-게이트)
5. [운영 매뉴얼](#운영-매뉴얼)

---

## 현황 분석

### 0. 사전 검토 결론 (2026-05-18)
- **그대로 시행 금지**: 최초 초안에는 현재 코드와 맞지 않는 경로/파일명이 있어 일부 단계가 실패한다.
- **시행 전 필수 정정**: BM25는 디렉터리가 아니라 `data/index/bm25.pkl` 파일이며, 보정본은 `data/index/bm25_v2_manual.pkl` 같은 별도 pickle 파일로 저장해야 한다.
- **검색 이중화 위치**: 현재 `src/retrieval/retriever.py`는 없고, 실제 검색 조합은 `src/rag/pipeline.py`, 로딩은 `scripts/cli.py`, `scripts/eval.py`, `src/ui/streamlit_app.py`에서 이뤄진다.
- **메타데이터 키**: 기존 청크는 `source_doc`가 아니라 `doc_short`를 사용한다. 비교/필터/QA는 `doc_short` 기준으로 작성한다.
- **V2_Manual 범위**: 보정본 대상은 현재 `requires_ocr=True` 문서인 `실무가이드`, `상담사례집`이다. 비OCR 문서는 원본 PDF 파싱 결과를 그대로 함께 포함해 전체 RAG 인덱스를 구성한다.
- **구현 결정**: Streamlit 운영 화면은 버전 선택 UI를 두지 않고, 기본값으로 보정본 통합 인덱스(`v2_manual`)만 참조한다. 원본 OCR 인덱스는 비교 테스트용으로 별도 생성한다.
- **스크립트 전제**: `scripts/compare_ocr_versions.py`를 본 통합 작업에서 새로 생성해 원본 OCR 인덱스와 보정본 통합 인덱스를 터미널에서 비교한다.

### 1.1 현재 시스템 상태
- **OCR 원본**: `/data/extracted/` 디렉토리에 저장
  - 구조: `extracted/{doc_short}/manifest.json` + 문서별 OCR 결과
  - 비교용 청크 출력: `data/processed/chunks_original_ocr.jsonl`
  - 비교용 인덱스 출력: `data/index/bm25_original_ocr.pkl`, `data/index/chroma_original_ocr/`

- **인제스트 파이프라인** (`scripts/ingest.py`):
  - `build_chunks()`: PDF 파싱 또는 OCR 추출물에서 청크 생성
  - `build_index()`: BM25 + ChromaDB 벡터 인덱스 구성
  - 현재는 고정된 경로만 지원 (EXTRACTED_BASE, CHUNKS_PATH, CHROMA_DIR)

### 1.2 V2_Manual 보정본 상태
- **제공 형식**: ocr_v2_manual_handoff_*.tar.gz 아카이브
- **포함 내용**:
  - 상담사례집: 350페이지 (14배치)
  - 실무가이드: 328페이지 (13배치)
  - 배치별 검증 및 보정 기록
  - 검증 스크립트 (`validate_v2_manual_batch.py`)

### 1.3 주요 문제점
1. **경로 고정**: ingest.py가 EXTRACTED_BASE 등을 하드코딩
2. **인덱스 충돌**: 버전별 출력 경로를 분리하지 않으면 chunks/index 산출물이 서로 덮어써짐
3. **버전 선택 부재**: 두 버전 중 어느 것을 사용할지 선택 메커니즘 없음
4. **품질 검증 부재**: v2_manual 통합 전 품질 기준이 명확하지 않음

---

## 통합 아키텍처

### 2.1 이중 경로 구조
```
data/
├── extracted/              # 원본 OCR
│   ├── 실무가이드/
│   ├── 상담사례집/
│   └── ... (기타 문서)
├── extracted_v2_manual/    # V2_Manual 보정본
│   ├── 실무가이드/
│   └── 상담사례집/
├── processed/
│   ├── chunks.jsonl                 # 기존 레거시 청크
│   ├── chunks_original_ocr.jsonl    # 원본 OCR 비교용 통합 청크
│   ├── chunks_v2_manual.jsonl       # V2_Manual 운영 통합 청크
│   └── manifest.json                # 통합 메타데이터
└── index/
    ├── bm25.pkl                     # 기존 레거시 BM25
    ├── chroma/                      # 기존 레거시 ChromaDB
    ├── bm25_original_ocr.pkl        # 원본 OCR 비교용 BM25
    ├── chroma_original_ocr/         # 원본 OCR 비교용 ChromaDB
    ├── bm25_v2_manual.pkl           # V2_Manual 운영 BM25
    └── chroma_v2_manual/            # V2_Manual 운영 ChromaDB
```

### 2.2 설정 시스템 개선
**현재 (hardcoded)**:
```python
EXTRACTED_BASE = ROOT / "data" / "extracted"
CHUNKS_PATH = config.CHUNKS_PATH  # 고정값
CHROMA_DIR = config.CHROMA_DIR    # 고정값
```

**개선 (파라미터화)**:
```python
class OCRVersion(Enum):
    ORIGINAL = "original"
    V2_MANUAL = "v2_manual"

class IngestConfig:
    def __init__(self, version: OCRVersion = OCRVersion.ORIGINAL):
        self.version = version
        if version == OCRVersion.ORIGINAL:
            self.extracted_base = ROOT / "data" / "extracted"
            self.chunks_path = ROOT / "data" / "processed" / "chunks_original_ocr.jsonl"
            self.bm25_path = ROOT / "data" / "index" / "bm25_original_ocr.pkl"
            self.chroma_dir = ROOT / "data" / "index" / "chroma_original_ocr"
        elif version == OCRVersion.V2_MANUAL:
            self.extracted_base = ROOT / "data" / "extracted_v2_manual"
            self.chunks_path = ROOT / "data" / "processed" / "chunks_v2_manual.jsonl"
            self.bm25_path = ROOT / "data" / "index" / "bm25_v2_manual.pkl"
            self.chroma_dir = ROOT / "data" / "index" / "chroma_v2_manual"
```

### 2.3 메타데이터 통합 레이어
v2_manual 통합 후 두 버전을 비교/선택할 수 있도록, 각 청크에 메타데이터 추가:

```python
chunk.metadata.update({
    "ocr_version": "original" | "v2_manual",
    "doc_short": "상담사례집",
    "page_start": 42,
    "confidence": 0.92,  # v2_manual에서 manifest/block 정보가 제공될 때만 포함
    "correction_batches": [5, 7],  # v2_manual 배치 번호
    "validation_status": "verified"  # v2_manual only
})
```

---

## 구현 단계

### 단계 1: V2_Manual 데이터 준비 (1-2시간)

#### 1.1 아카이브 다운로드 및 추출
```bash
# DGX에서 다운로드 (또는 rsync)
rsync -av user@dgx:/path/to/ocr_v2_manual_handoff_*.tar.gz ./

# 추출
tar -xzf ocr_v2_manual_handoff_*.tar.gz

# 구조 확인
ls -la data/extracted_v2_manual/
# → 실무가이드/, 상담사례집/, manifest.json 등 확인
```

#### 1.2 디렉토리 구조 검증
```bash
# validate_v2_manual_batch.py 실행으로 모든 배치 검증
python scripts/validate_v2_manual_batch.py --all
```

**예상 출력**:
```
[V2M] 배치 1/27 검증: 상담사례집-배치1 ... PASSED
[V2M] 배치 2/27 검증: 상담사례집-배치2 ... PASSED
...
[V2M] 전체 배치 검증 완료: 27/27
```

### 단계 2: ingest.py 파라미터화 (2-3시간)

#### 2.1 config.py 확장
```python
# src/config.py에 추가

class OCRVersion(Enum):
    ORIGINAL = "original"
    V2_MANUAL = "v2_manual"

OCR_VERSIONS_ENABLED = [OCRVersion.ORIGINAL]  # 기본값
# 통합 후: [OCRVersion.ORIGINAL, OCRVersion.V2_MANUAL]

def get_ingest_paths(version: OCRVersion):
    """OCR 버전별 경로 반환"""
    if version == OCRVersion.ORIGINAL:
        return {
            "extracted_base": ROOT / "data" / "extracted",
            "chunks_path": ROOT / "data" / "processed" / "chunks_original_ocr.jsonl",
            "bm25_path": ROOT / "data" / "index" / "bm25_original_ocr.pkl",
            "chroma_dir": ROOT / "data" / "index" / "chroma_original_ocr",
        }
    elif version == OCRVersion.V2_MANUAL:
        return {
            "extracted_base": ROOT / "data" / "extracted_v2_manual",
            "chunks_path": ROOT / "data" / "processed" / "chunks_v2_manual.jsonl",
            "bm25_path": ROOT / "data" / "index" / "bm25_v2_manual.pkl",
            "chroma_dir": ROOT / "data" / "index" / "chroma_v2_manual",
        }
```

#### 2.2 ingest.py 수정
```bash
# 변경 사항 (scripts/ingest.py)

# 1. CLI 인수 추가
parser.add_argument(
    "--ocr-version",
    choices=["original", "v2_manual", "both"],
    default="original",
    help="사용할 OCR 버전"
)

# 2. build_chunks() 함수 수정
def build_chunks(sources=None, ocr_version: OCRVersion = OCRVersion.ORIGINAL) -> None:
    paths = get_ingest_paths(ocr_version)
    
    # chunk.metadata에 ocr_version 추가
    chunk.metadata["ocr_version"] = ocr_version.value
    
    save_chunks(all_chunks, paths["chunks_path"])

# 3. build_index() 함수 수정
def build_index(ocr_version: OCRVersion = OCRVersion.ORIGINAL) -> None:
    paths = get_ingest_paths(ocr_version)
    chunks = load_chunks(paths["chunks_path"])
    
    vector_store = VectorStore(paths["chroma_dir"], reset=True)
    bm25.save(paths["bm25_path"])
```

#### 2.3 CLI 사용 예시
```bash
# 원본 인제스트 (기존과 동일)
python scripts/ingest.py --stage all

# V2_Manual만 인제스트
python scripts/ingest.py --stage all --ocr-version v2_manual

# 두 버전 모두 인제스트
python scripts/ingest.py --stage all --ocr-version both
```

### 단계 3: 검색 시스템 이중화 (2시간)

#### 3.1 eval.py 파라미터 추가
```python
# scripts/eval.py, scripts/cli.py, src/ui/streamlit_app.py의 로딩 경로에 적용
# 별도 DualRetriever를 새로 만들기보다 기존 RagPipeline 구성에 version별 경로를 주입한다.

paths = get_ingest_paths(version)
vector_store = VectorStore(paths["chroma_dir"])
bm25 = BM25Index.load(paths["bm25_path"])
pipeline = RagPipeline(embedder, vector_store, bm25, llm, ...)

version = config.DEFAULT_OCR_VERSION  # 운영 기본값은 v2_manual
```

#### 3.2 Streamlit 운영 모드
```python
# src/ui/streamlit_app.py
# 운영 화면에서는 별도 OCR 버전 선택 UI를 노출하지 않는다.
# 앱은 DEFAULT_OCR_VERSION(v2_manual) 기준 통합 인덱스를 로드한다.
pipeline = _get_pipeline(model, top_k)
```

### 단계 4: 품질 검증 및 비교 (3-4시간)

#### 4.1 비교 검증 스크립트
```python
# scripts/compare_ocr_versions.py (새 파일)

def compare_versions():
    """원본 vs V2_Manual 비교"""
    
    original_chunks = load_chunks("data/processed/chunks_original_ocr.jsonl")
    v2manual_chunks = load_chunks("data/processed/chunks_v2_manual.jsonl")
    
    # 공통 문서에 대해서만 비교
    shared_docs = set(c.metadata["doc_short"] for c in original_chunks) & \
                  set(c.metadata["doc_short"] for c in v2manual_chunks)
    
    for doc in shared_docs:
        orig_doc_chunks = [c for c in original_chunks 
                          if c.metadata["doc_short"] == doc]
        v2m_doc_chunks = [c for c in v2manual_chunks 
                         if c.metadata["doc_short"] == doc]
        
        print(f"\n[비교] {doc}")
        print(f"  원본: {len(orig_doc_chunks):,} 청크")
        print(f"  보정본: {len(v2m_doc_chunks):,} 청크")
        print(f"  차이: {len(v2m_doc_chunks) - len(orig_doc_chunks):+d}")

def quality_metrics():
    """품질 지표 계산"""
    
    # 1. 코드 포함율 비교
    # 2. 평균 청크 길이 비교
    # 3. 검색 질문 재현율 비교
    
    embedder = Embedder(config.EMBEDDING_MODEL)
    test_queries = [
        "재진 진찰료",
        "입원료",
        "특정 비급여 항목",
        # ... 15-20개 대표 질문
    ]
    
    for query in test_queries:
        orig_results = build_pipeline(OCRVersion.ORIGINAL).retrieve_hits(query)[0]
        v2m_results = build_pipeline(OCRVersion.V2_MANUAL).retrieve_hits(query)[0]
        
        # 상위 결과 비교
        print(f"[{query}]")
        print(f"  원본 재현율: {len(set(orig_results[:3]))}/5")
        print(f"  보정본 재현율: {len(set(v2m_results[:3]))}/5")
```

#### 4.2 pytest 통합 테스트
```python
# tests/test_ocr_integration.py

class TestOCRVersions:
    
    def test_v2_manual_chunk_validity(self):
        """V2_Manual 청크 유효성 검증"""
        chunks = load_chunks("data/processed/chunks_v2_manual.jsonl")
        assert len(chunks) > 0, "V2_Manual 청크가 비어있음"
        
        for chunk in chunks:
            assert chunk.metadata["ocr_version"] == "v2_manual"
            assert "validation_status" in chunk.metadata
            assert len(chunk.text) > 0
    
    def test_v2_manual_index_builds(self):
        """V2_Manual 인덱스 생성 성공"""
        paths = get_ingest_paths(OCRVersion.V2_MANUAL)
        
        # BM25 검증
        bm25 = BM25Index.load(paths["bm25_path"])
        assert len(bm25.ids) > 0
        
        # ChromaDB 검증
        vs = VectorStore(paths["chroma_dir"])
        results = vs.query(embedder.embed_query("재진 진찰료"), top_k=1)
        assert len(results) > 0
    
    def test_dual_retrieval(self):
        """이중 검색 시스템 작동"""
        query = "재진 진찰료"
        
        orig_results = build_pipeline(OCRVersion.ORIGINAL).retrieve_hits(query)[0]
        v2m_results = build_pipeline(OCRVersion.V2_MANUAL).retrieve_hits(query)[0]
        
        assert len(orig_results) > 0
        assert len(v2m_results) > 0
```

---

## 품질 게이트

### 3.1 V2_Manual 통합 전 필수 검사 (Go/No-Go)

| # | 검사 항목 | 기준 | 담당 | 상태 |
|---|----------|------|------|------|
| 1 | 배치 완전성 | 27/27 배치 pass | validate_v2_manual_batch.py | 대기 |
| 2 | 청크 생성 성공 | chunks_v2_manual.jsonl 생성됨 | scripts/ingest.py | ⏳ |
| 3 | 인덱스 생성 성공 | BM25, ChromaDB 생성됨 | scripts/ingest.py | ⏳ |
| 4 | 테스트 스위트 | pytest 100% pass | pytest tests/test_ocr_integration.py | ⏳ |
| 5 | 검색 품질 | recall@8 ≥ 1.000 | eval.py 또는 비교 스크립트 | ⏳ |
| 6 | 비교 분석 | 원본 대비 개선도 명확 | compare_ocr_versions.py | ⏳ |
| 7 | 신경망 임베딩 | 384-dim 임베딩 일치 | 자동 검증 | ⏳ |

### 3.2 체크리스트
```bash
# 1. V2_Manual 데이터 추출 및 검증
python scripts/validate_v2_manual_batch.py --all
# 27/27 배치 검증 완료

# 2. 청크 및 인덱스 생성
python scripts/ingest.py --stage all --ocr-version v2_manual
# chunks_v2_manual.jsonl 생성 완료
# BM25, ChromaDB 생성 완료

# 3. 테스트 실행
pytest tests/test_ocr_integration.py -v
# 모든 테스트 통과

# 4. 품질 비교
python scripts/compare_ocr_versions.py
# 결과 검토 및 승인

# 5. 정규화 및 표 재구성 (OCR 보정본과 직접 관련된 표 색인이 바뀐 경우에만)
python scripts/build_relational_db.py
# nonpay_standard 테이블 업데이트

# 6. Streamlit QA
streamlit run src/ui/streamlit_app.py
# 보정본 통합 인덱스 기준 QA 완료

# 모든 게이트 통과 -> Production 배포
```

---

## 운영 매뉴얼

### 4.1 초기 통합 절차 (Day 1)

```bash
# 1. V2_Manual 데이터 다운로드
rsync -av user@dgx:/path/ocr_v2_manual_handoff_*.tar.gz ./
tar -xzf ocr_v2_manual_handoff_*.tar.gz
mv extracted_v2_manual data/

# 2. 배치 검증
python scripts/validate_v2_manual_batch.py --all

# 3. 인제스트
python scripts/ingest.py --stage all --ocr-version v2_manual

# 4. 테스트
pytest tests/test_ocr_integration.py -v

# 5. 품질 비교
python scripts/compare_ocr_versions.py > reports/comparison_20260518.txt

# 6. 검토 및 승인
# 결과를 팀과 공유, 의사결정
```

### 4.2 이중 운영 모드 (Day 2+)

#### 모드 A: 원본만 사용 (기존)
```bash
# 기본 설정: OCR_VERSIONS_ENABLED = [OCRVersion.ORIGINAL]
python scripts/ingest.py --stage all  # 자동으로 원본 사용
```

#### 모드 B: 보정본 우선 (새 권장)
```python
# src/config.py에서:
OCR_VERSIONS_ENABLED = [OCRVersion.V2_MANUAL]  # 보정본 우선

# 또는 CLI에서:
python scripts/ingest.py --stage all --ocr-version v2_manual
```

#### 모드 C: 이중 인덱싱 (A/B 테스트)
```bash
# 두 버전 모두 빌드 (별도 경로에 저장)
python scripts/ingest.py --stage all --ocr-version original
python scripts/ingest.py --stage all --ocr-version v2_manual

# 비교 테스트는 Streamlit이 아니라 scripts/compare_ocr_versions.py로 수행
python scripts/compare_ocr_versions.py --retrieval --query "재진 진찰료"
```

### 4.3 모니터링 및 로깅

```python
# src/utils/ingest_logger.py (새 파일)

import logging
from datetime import datetime

class IngestLogger:
    def __init__(self, ocr_version: str):
        self.version = ocr_version
        self.log_file = f"logs/ingest_{ocr_version}_{datetime.now().isoformat()}.log"
        
    def log_chunk_stats(self, chunk_count, avg_length, code_ratio):
        print(f"[{self.version}] 청크: {chunk_count:,}, "
              f"평균 길이: {avg_length:.0f}자, "
              f"코드 포함율: {code_ratio:.1f}%")
    
    def log_index_stats(self, bm25_size, chroma_size):
        print(f"[{self.version}] BM25: {bm25_size:.1f}MB, "
              f"ChromaDB: {chroma_size:.1f}MB")
```

### 4.4 롤백 절차 (문제 발생 시)
```bash
# V2_Manual 사용 중 문제 발생 → 원본으로 복구
python scripts/ingest.py --stage all --ocr-version original

# 또는 원본 인덱스 복구 (백업 있을 경우)
cp -r data/index.backup data/index
cp data/processed/chunks_original_ocr.jsonl.backup data/processed/chunks_original_ocr.jsonl
```

---

## 타임라인 및 리소스

| 단계 | 소요 시간 | 담당 | 완료 예상 |
|------|---------|------|---------|
| 1. V2_Manual 준비 | 1-2시간 | 인프라 | 2026-05-18 |
| 2. ingest.py 파라미터화 | 2-3시간 | 개발 | 2026-05-18 |
| 3. 검색 시스템 이중화 | 2시간 | 개발 | 2026-05-18 |
| 4. 품질 검증 | 3-4시간 | 테스트/분석 | 2026-05-18 |
| **총 통합 시간** | **8-12시간** | **팀** | **2026-05-18** |

---

## 의사결정 트리

```
V2_Manual 품질 검증 완료?
├─ YES
│  ├─ 원본 대비 개선도 명확?
│  │  ├─ YES → V2_Manual 우선 운영 시작
│  │  └─ NO  → 이중 인덱싱 (A/B 테스트 진행)
│  └─ 개선도 미미?
│     └─ 원본 계속 사용, V2_Manual은 참고만
├─ NO (품질 이슈)
│  └─ 배치 재검증 후 재진입
```

---

## 부록: 파일 수정 목록

### 필수 수정
- [x] `src/config.py` - OCRVersion enum, get_ingest_paths() 추가
- [x] `scripts/ingest.py` - --ocr-version CLI 인수 추가
- [x] `scripts/cli.py`, `scripts/eval.py`, `src/ui/streamlit_app.py` - version별 경로 로딩 적용
- [ ] `src/rag/pipeline.py` - 필요 시 `ocr_version` 메타데이터를 debug/log에 노출
- [x] `tests/test_config.py`, `tests/test_ingest.py` - 버전 경로/청크 생성 테스트 추가

### 신규 생성
- [x] `scripts/compare_ocr_versions.py` - 버전 비교 분석
- [ ] `src/utils/ingest_logger.py` - 통합 로깅
- [x] `data/index/bm25_v2_manual.pkl` - v2_manual BM25 인덱스 파일 (Git 제외)
- [x] `data/index/chroma_v2_manual/` - v2_manual ChromaDB 경로 (Git 제외)

### 선택사항
- [x] Streamlit UI는 버전 선택 없이 v2_manual 통합 인덱스를 기본 참조
- [ ] 대시보드에 버전별 통계 추가
- [ ] 자동화된 품질 게이트 CI/CD 파이프라인

---

## 문의 및 롤백

**담당자**: Data Engineering / OCR Integration Team  
**긴급 연락처**: eundeo@hanyang.ac.kr  
**롤백 승인**: 팀 리드 승인 필수

---

**최종 수정**: 2026-05-18  
**상태**: 구현 완료 (운영 기본값 v2_manual, 원본 OCR은 비교 테스트용)
