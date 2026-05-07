# Codex 개발자 명세 — M8 · M9 · M10 (Alpha v1 → Beta)

> **문서 유형:** Codex 전달용 개발자 명세
> **작성일:** 2026-04-30
> **기반 자료:**
> - `docs/06_STREAMLIT_TEST_RESULT_v1.md` — Alpha v1 실사용 테스트 결과 (정답률 40%)
> - `docs/07_IMPROVEMENT_PLAN.md` — 기획자 작성 개선 계획서
> **목표:** M10 완료 시 정답률 90%+, Retrieval Recall@8 90%+

---

## 섹션 0 — Codex에게 전달할 프롬프트 (복사 붙여넣기용)

```
당신은 시니어 Python 개발자입니다.
"보험 문서 RAG 챗봇" 프로젝트에서 Alpha v1 실사용 테스트 결과 발견된 문제점을 해결하는
M8(LLM 업그레이드 + 프롬프트 재설계), M9(코드 라우팅 + Reranker), M10(청킹 개선 + 재인덱싱)
3개 마일스톤을 순서대로 구현해주세요.

---

## 테스트에서 발견된 핵심 문제 (반드시 숙지)

| 문제 | 해당 질문 | 근본 원인 |
|------|----------|----------|
| LLM이 컨텍스트 내 N39.3을 인식 못함 | Q2 | 3B 모델 역량 한계 |
| 식도조루술 코드로 R3200 오반환 (정답: Q2333) | Q3 | BM25가 코드 인덱스 테이블(p.442)을 원문(p.531)보다 우선 반환 |
| 3대비급여 구체 항목 열거 실패 | Q4 | 3B 모델 추출 능력 한계 |
| 출처 인용 형식 "컨텍스트 N" 혼재 | Q2 | 프롬프트 지침 부족 |

> ⚠️ 질문3(식도조루술 수술코드+수술해설+1-5종)의 경우, 현재 보상가이드북이 인덱싱되어 있지
> 않습니다. 코드(Q2333)는 심평원에서 답할 수 있으나, 수술해설과 종별(3종) 정보는
> 보상가이드북이 추가 인덱싱된 이후에만 완전한 답변이 가능합니다.
> 현재 단계에서는 "코드는 Q2333이며, 수술해설 및 종별 정보는 보상가이드북(현재 미인덱싱)에
> 있습니다"로 답변하는 것이 올바른 동작입니다.

---

## M8 — LLM 업그레이드 + 프롬프트 재설계

### M8-1. LLM 모델 업그레이드

**파일:** `.env.example`, `.env` (사용자 환경)

현재 `.env.example` 내용에 아래 주석 옵션을 추가하세요:

```
# LLM 모델 설정 (성능 순)
# OLLAMA_MODEL=qwen2.5:7b-instruct         # 추천: 범용 7B
# OLLAMA_MODEL=exaone3.5:7.8b-instruct     # 추천: 한국어 특화 7.8B
# OLLAMA_MODEL=qwen2.5:14b-instruct        # 고성능: 14B (메모리 10GB+)
OLLAMA_MODEL=gemma3:4b                     # 기본값 (테스트 환경 호환)
```

`src/llm/ollama_client.py`에서 `num_ctx` 기본값을 변경하세요:
- 현재: `num_ctx=8192`
- 변경: `num_ctx=16384`

단, `num_ctx`는 `.env`에서 오버라이드 가능하도록 환경변수로 분리하세요:
```
OLLAMA_NUM_CTX=16384
```

### M8-2. 시스템 프롬프트 재설계

**파일:** `src/llm/prompt.py`

`SYSTEM_PROMPT`를 아래 내용으로 교체하세요. Few-shot 예시 2개를 포함합니다:

```python
SYSTEM_PROMPT = """당신은 보험사 직원의 질문에 답하는 전문 어시스턴트입니다.

참고 문서에는 건강보험 고시(심평원), 실손의료보험 약관, 보상가이드북이 포함될 수 있습니다.

## 핵심 규칙
1. 반드시 제공된 컨텍스트 안의 정보만 사용하세요. 외부 지식이나 추측을 사용하지 마세요.
2. 컨텍스트에 답이 없으면 "제공된 문서에서 확인되지 않습니다."라고 답하세요.
3. 코드(예: AA157, N39.3, Q2333)가 질문에 있으면, 컨텍스트 전체를 세밀하게 살펴
   해당 코드가 포함된 행이나 항목을 정확히 찾아 답하세요.
4. 표 형태의 데이터에서 분류번호·코드·명칭·점수는 같은 행에 속합니다.
   "코드 Q2333 → 식도조루술"처럼 코드와 명칭을 함께 확인하고 답하세요.
5. 보상 여부를 묻는 질문은 컨텍스트에서 "보상하지 않는 사항" 또는 "보상하는 사항"
   조항을 찾아 해당 코드나 진단이 포함되는지 확인하고 "보상 불가" 또는 "보상 가능"을
   명확히 답하세요.
6. 출처는 반드시 '컨텍스트 번호'가 아닌 '문서명(심평원/약관/가이드북)'으로 인용하세요.

## 답변 형식
답변 마지막에 반드시 출처를 기재하세요.
형식: [출처: 문서명, 조문/절, p.페이지]

## 예시

질문: AA157은 어떤 기관의 초진 진찰료이며 점수는 얼마인가요?
답변: AA157은 상급종합병원의 초진 진찰료이며 점수는 255.79점입니다.
[출처: 심평원, 제1편 제2부 제1장 기본진료료, p.101]

질문: N39.3 진단이 실손의료비 약관에서 보상가능한지 알려줘.
답변: N39.3(요실금)은 실손의료보험 약관에서 아래 보장종목 모두에서 보상하지 않는 사항으로 명시되어 있습니다.
- 질병급여 실손의료비: 보상 불가
- 질병비급여 실손의료비: 보상 불가
- 3대비급여 실손의료비: 보상 불가
[출처: 약관, 제3조(보장종목별 보상내용), p.38 / 약관, 제3조(보장종목별 보상내용), p.80 / 약관, 별표/3대비급여, p.82]"""
```

### M8-3. 컨텍스트 레이블 개선

**파일:** `src/llm/prompt.py` 내 `build_user_prompt()` 또는 `_context_label()` 함수

컨텍스트 레이블에서 `doc_short`가 앞에 오도록 수정하세요:

```python
# 현재 (개선 전)
f"[컨텍스트 {index}] {label}"

# 개선 후
doc_short = metadata.get("doc_short", "")
prefix = f"[{doc_short}] " if doc_short else ""
f"[컨텍스트 {index}: {prefix}{label}]"
```

### M8-4. M8 완료 검증 (필수)

M8 구현 완료 후 아래 명령으로 smoke_qa 5문항(Q1-Q5)을 재실행하고 결과를 보고하세요:

```bash
python scripts/eval.py
```

**M8 합격 기준:**
- Q1(AA157): 기관명 + 점수 모두 정답 ✅
- Q2(N39.3): "보상 불가" 또는 "보상하지 않습니다" 포함 ✅
- Q3(식도조루술): 코드 Q2333 포함, 또는 "보상가이드북 미인덱싱"으로 종별 생략 허용 ✅
- Q4(3대비급여): 도수치료·비급여 주사료·MRI 중 2개 이상 열거 ✅
- Q5(도수치료 한도): 350만원 또는 50회 포함 ✅

---

## M9 — 코드 라우팅 + Reranker

### M9-1. VectorStore `query_with_filter` 메서드 추가

**파일:** `src/retrieval/vector_store.py`

`codes` 메타데이터 필드에 특정 코드가 포함된 청크만 검색하는 메서드를 추가하세요:

```python
def query_with_filter(
    self,
    query_embedding: list[float],
    filter_codes: list[str],
    top_k: int,
) -> list[Hit]:
    """codes 메타데이터에 특정 코드가 포함된 청크만 검색한다.

    ChromaDB where 필터: codes 필드에 filter_codes 중 하나라도 포함.
    결과가 없으면 빈 리스트를 반환한다 (일반 검색으로 fallback).
    """
    where_filter = {
        "$or": [
            {"codes": {"$contains": code}}
            for code in filter_codes
        ]
    }
    try:
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    hits = []
    ids = result["ids"][0]
    docs = result["documents"][0]
    metas = result["metadatas"][0]
    dists = result["distances"][0]
    for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists):
        score = 1.0 - dist  # cosine distance → similarity
        hits.append(Hit(id=chunk_id, document=doc, metadata=meta, score=score))
    return hits
```

> `Hit` 데이터클래스는 기존 `vector_store.py`에 이미 정의된 것을 사용하세요.
> `codes` 필드가 리스트 형태이면 ChromaDB의 `$contains` 연산자가 동작합니다.
> 단, 저장 시 `codes`가 문자열(쉼표구분)이면 `$contains` 대신 문자열 contains 필터를 사용하세요.
> 실제 메타데이터 저장 형식을 확인 후 필터 쿼리를 작성하세요.

### M9-2. 코드 라우팅 파이프라인 수정

**파일:** `src/rag/pipeline.py`

```python
import re

# 의료 코드 패턴 (절 상단에 정의)
_CODE_PATTERN = re.compile(
    r'\b[A-Z]{1,3}\d{2,5}\b'        # 심평원 코드: AA157, Q2333, R3200 등
    r'|\b[A-Z]\d{2}(?:\.\d{1,2})?\b' # ICD-10 코드: N39.3, C50.9 등
)

def _extract_query_codes(question: str) -> list[str]:
    """질문에서 의료 코드 패턴 추출. 중복 제거."""
    return list(set(_CODE_PATTERN.findall(question)))
```

`RagPipeline.answer()` 또는 검색 호출 부분을 아래와 같이 수정하세요:

```python
def answer(self, question: str, top_k: int = 8, temperature: float = 0.2) -> RagAnswer:
    query_codes = _extract_query_codes(question)
    query_embedding = self.embedder.embed_query(question)

    if query_codes:
        # 코드 포함 쿼리: 코드 필터 검색(절반) + 일반 검색(절반) 병합
        half_k = max(1, self.top_k_dense // 2)
        code_hits = self.vector_store.query_with_filter(
            query_embedding, filter_codes=query_codes, top_k=half_k
        )
        general_hits = self.vector_store.query(query_embedding, top_k=half_k)
        # 중복 제거 (id 기준)
        seen = {h.id for h in code_hits}
        dense_hits = code_hits + [h for h in general_hits if h.id not in seen]
    else:
        dense_hits = self.vector_store.query(query_embedding, top_k=self.top_k_dense)

    bm25_hits = self.bm25.query(question, top_k=self.top_k_bm25)
    fused_hits = rrf_fuse(dense_hits, bm25_hits, top_k=self.top_k_rrf)

    # Reranker가 설정된 경우 적용 (M9-3에서 추가)
    if hasattr(self, "reranker") and self.reranker is not None:
        fused_hits = self.reranker.rerank(question, fused_hits, top_k=top_k)
    else:
        fused_hits = fused_hits[:top_k]

    # 이하 기존 LLM 호출 로직 동일
    ...
```

### M9-3. Reranker 모듈 신규 작성

**파일:** `src/retrieval/reranker.py` (신규 생성)

```python
"""BGE-reranker-v2-m3 크로스인코더 reranker.

설치:
    pip install sentence-transformers

최초 실행 시 모델이 HuggingFace에서 자동 다운로드됩니다 (~1.1GB).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import CrossEncoder
    _CROSS_ENCODER_AVAILABLE = True
except ImportError:
    _CROSS_ENCODER_AVAILABLE = False


@dataclass
class Hit:
    """Reranker 입출력용 공통 Hit 타입. pipeline.py의 Hit과 동일."""
    id: str
    document: str
    metadata: dict
    score: float


class Reranker:
    """BGE-reranker-v2-m3 기반 크로스인코더 reranker."""

    DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"

    def __init__(self, model_name: str = DEFAULT_MODEL, enabled: bool = True):
        self.enabled = enabled and _CROSS_ENCODER_AVAILABLE
        if not _CROSS_ENCODER_AVAILABLE:
            logger.warning("sentence-transformers 미설치 — reranker 비활성화")
            return
        if not enabled:
            return
        logger.info("Reranker 로딩: %s", model_name)
        self.model = CrossEncoder(model_name, max_length=512)
        logger.info("Reranker 로딩 완료")

    def rerank(self, question: str, hits: list, top_k: int) -> list:
        """hits 리스트를 rerank하여 상위 top_k개를 반환한다.

        sentence_transformers를 사용할 수 없거나 enabled=False이면
        원본 hits[:top_k]를 그대로 반환한다.
        """
        if not self.enabled or not hits:
            return hits[:top_k]

        pairs = [(question, hit.document) for hit in hits]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(hits, scores), key=lambda x: x[1], reverse=True)
        result = [hit for hit, _ in ranked[:top_k]]
        return result


def build_reranker(enabled: bool = True) -> Reranker:
    """설정에 따라 Reranker 인스턴스를 생성한다."""
    return Reranker(enabled=enabled)
```

### M9-4. Reranker를 파이프라인에 통합

**파일:** `src/rag/pipeline.py` 또는 파이프라인을 초기화하는 곳

```python
from src.retrieval.reranker import build_reranker

class RagPipeline:
    def __init__(self, ...):
        ...
        reranker_enabled = os.getenv("RERANKER_ENABLED", "true").lower() == "true"
        self.reranker = build_reranker(enabled=reranker_enabled)
```

**`.env.example`에 추가:**
```
RERANKER_ENABLED=true   # false로 설정 시 reranker 생략 (속도 우선)
```

Reranker 비활성 시 기존 동작과 100% 동일해야 합니다.

### M9-5. RRF 풀 크기 확대

Reranker가 활성화된 경우 RRF 단계에서 더 많은 후보를 생성해야 합니다:

```python
# RRF top_k 설정
top_k_rrf = top_k * 2 if (hasattr(self, "reranker") and self.reranker and self.reranker.enabled) else top_k
fused_hits = rrf_fuse(dense_hits, bm25_hits, top_k=top_k_rrf)
```

### M9-6. M9 완료 검증 (필수)

```bash
python scripts/eval.py
```

**M9 합격 기준 (전체 smoke_qa 15문항 기준):**
- `recall@8 >= 0.85`
- `page_accuracy >= 0.75`
- Q3(식도조루술) 정답 코드 Q2333이 LLM 답변에 포함될 것

---

## M10 — 청킹 개선 + 전체 재인덱싱

### M10-1. 코드 테이블 청크 마킹

**파일:** `src/parser/chunker.py`

`_make_chunk()` 함수 내에서 코드 밀도를 계산하여 `is_code_table` 메타데이터를 추가하세요:

```python
def _make_chunk(text: str, metadata: dict, ...) -> Chunk:
    codes = _extract_codes(text)
    # 청크 내 코드가 5개 이상이면 코드 테이블로 간주
    is_code_table = len(codes) >= 5
    metadata = {
        **metadata,
        "codes": codes,             # 기존
        "is_code_table": is_code_table,  # 신규
    }
    ...
```

> ⚠️ `codes` 필드의 저장 형식을 확인하세요.
> ChromaDB는 메타데이터에 리스트를 직접 저장하지 못합니다.
> 현재 `codes`가 쉼표 구분 문자열로 저장된다면, `is_code_table`도 bool이 아닌
> `"true"/"false"` 문자열로 저장하거나, ChromaDB 메타데이터 제약에 맞게 변환하세요.

### M10-2. 코드 라우팅에서 is_code_table 활용

**파일:** `src/retrieval/vector_store.py`

`query_with_filter` 메서드에 `prefer_non_table` 옵션을 추가하세요:

```python
def query_with_filter(
    self,
    query_embedding: list[float],
    filter_codes: list[str],
    top_k: int,
    prefer_non_table: bool = True,  # M10 신규 파라미터
) -> list[Hit]:
    where_filter = {
        "$and": [
            {"$or": [{"codes": {"$contains": code}} for code in filter_codes]},
        ]
    }
    if prefer_non_table:
        # 코드 테이블이 아닌 청크 우선 시도
        non_table_filter = {
            "$and": [
                *where_filter["$and"],
                {"is_code_table": {"$eq": "false"}},
            ]
        }
        hits = self._raw_query(query_embedding, non_table_filter, top_k)
        if hits:
            return hits
        # fallback: 테이블 포함 재시도
    return self._raw_query(query_embedding, where_filter, top_k)
```

실제 ChromaDB 메타데이터 저장 형식에 맞게 필터를 조정하세요.

### M10-3. 전체 재인덱싱

코드 테이블 마킹이 포함된 메타데이터를 적용하기 위해 전체 재인덱싱이 필요합니다:

```bash
python scripts/ingest.py --stage all
```

인덱싱 완료 후 청크 수가 기존(2,670)과 크게 다르지 않아야 합니다 (±5% 이내).

### M10-4. 보상가이드북 인덱싱 준비 (조건부)

보상가이드북 PDF가 제공된 경우에만 수행합니다.
파일이 아직 없다면 이 단계는 건너뜁니다.

`src/config.py`의 `PDF_SOURCES`에 이미 등록된 가이드북 경로를 확인하고:
- 파일이 있으면: `python scripts/ingest.py --stage all`로 함께 인덱싱
- 파일이 없으면: 로그에 "보상가이드북 파일 없음, 건너뜀" 메시지 출력 후 계속 진행
  (이 동작은 이미 `ingest.py`에 구현되어 있어야 합니다)

보상가이드북 인덱싱 완료 시:
- Q3 전체 답변(코드+수술해설+종별)이 가능해집니다
- `smoke_qa.jsonl` 항목 13(cross_doc)의 `doc_sources: ["심평원", "가이드북"]`이 활성화됩니다

### M10-5. 최종 평가 + 결과 보고

```bash
python scripts/eval.py
```

**M10 합격 기준 (최종 목표):**
- `recall@8 >= 0.90`
- `page_accuracy >= 0.80`
- Q1–Q5 Streamlit 수동 테스트 정답률 4/5 이상

평가 결과를 `docs/09_EVAL_RESULT_M10.md`로 저장하세요. 포함 내용:
- eval.py 콘솔 출력 전체
- 개별 문항별 pass/fail 표
- Streamlit 수동 재테스트 결과 (Q1-Q5, 이전 `06_STREAMLIT_TEST_RESULT_v1.md`와 비교)

---

## 섹션 1 — 파일별 변경 요약

| 파일 | 마일스톤 | 변경 유형 |
|------|---------|---------|
| `.env.example` | M8, M9 | 수정 — 모델 옵션 주석 추가, `RERANKER_ENABLED` 추가 |
| `src/llm/ollama_client.py` | M8 | 수정 — `num_ctx` 환경변수화 |
| `src/llm/prompt.py` | M8 | 수정 — `SYSTEM_PROMPT` 전면 교체 (few-shot 포함), 컨텍스트 레이블 개선 |
| `src/rag/pipeline.py` | M9 | 수정 — 코드 라우팅 분기, reranker 통합, RRF 풀 확대 |
| `src/retrieval/vector_store.py` | M9, M10 | 수정 — `query_with_filter` 추가, `prefer_non_table` 옵션 추가 |
| `src/retrieval/reranker.py` | M9 | 신규 — BGE-reranker-v2-m3 모듈 |
| `src/parser/chunker.py` | M10 | 수정 — `is_code_table` 메타데이터 추가 |
| `docs/09_EVAL_RESULT_M10.md` | M10 | 신규 — 최종 평가 결과 보고서 |

---

## 섹션 2 — 의존성 및 설치

`requirements.txt`에 이미 `sentence-transformers`가 포함되어 있어야 합니다 (M6 이전 추가).
Reranker 모델(BAAI/bge-reranker-v2-m3)은 `Reranker.__init__()` 최초 호출 시 자동 다운로드됩니다.

추가 설치가 필요한 경우:
```bash
pip install sentence-transformers  # 이미 설치되어 있을 가능성 높음
```

---

## 섹션 3 — 구현 순서 및 독립성

```
M8 (LLM + 프롬프트) ──┐
                       ├──→ M9 (코드 라우팅 + Reranker) ──→ M10 (청킹 + 재인덱싱)
                       │
                       └── M8은 M9의 선행 조건입니다.
                           M9 검증 후 M10으로 진행하세요.
```

- M8은 재인덱싱 없이 LLM과 프롬프트만 변경합니다.
- M9는 검색 파이프라인 변경이며 재인덱싱이 필요 없습니다.
- M10만 전체 재인덱싱(`--stage all`)을 요구합니다.

---

## 섹션 4 — 예시 Q&A 및 예상 답변 (검증 기준)

### Q1 — AA157 진찰료 코드 조회 (심평원)

**질문:** AA157은 어떤 기관의 초진 진찰료이며 점수는 얼마인가요?

**M8+ 이후 기대 답변:**
> AA157은 상급종합병원의 초진 진찰료이며 점수는 255.79점입니다.
> [출처: 심평원, 제1편 제2부 제1장 기본진료료, p.101]

**검증 포인트:** "상급종합병원" + "255.79" + 심평원 출처 포함

---

### Q2 — N39.3 보상 여부 (약관)

**질문:** N39.3 진단이 실손의료비 약관에서 보상가능한지 알려줘.

**M8+ 이후 기대 답변:**
> N39.3(요실금)은 실손의료보험 약관에서 보상하지 않는 사항으로 명시되어 있습니다.
> - 질병급여 실손의료비: 보상 불가
> - 질병비급여 실손의료비: 보상 불가
> - 3대비급여 실손의료비: 보상 불가
> [출처: 약관, 제3조(보장종목별 보상내용), p.38 / p.80 / p.82]

**검증 포인트:**
- "보상 불가" 또는 "보상하지 않습니다" 포함
- 약관 출처 표시
- 질병급여/비급여 구분 언급 (권장, 없어도 부분 합격)

---

### Q3 — 식도조루술 코드 (심평원, 가이드북 없이 부분 답변)

**질문:** 식도조루술의 코드를 알려줘.

**M9+ 이후 기대 답변:**
> 식도조루술의 코드는 Q2333입니다.
> [출처: 심평원, p.531]

**검증 포인트:**
- 코드 "Q2333" 포함 (R3200 반환 시 실패)
- 심평원 출처 표시

**Q3 확장 질문 (보상가이드북 없을 때):**
> 질문: "식도조루술의 수술코드, 수술해설과 1-5종 해당여부를 알려줘."
> 기대 답변: "코드는 Q2333입니다. 수술해설 및 1-5종 분류 정보는 보상가이드북에 있으며
> 현재 해당 문서가 인덱싱되어 있지 않아 확인이 불가합니다."

---

## 섹션 5 — 알려진 제약 사항 (구현 전 숙지)

1. **ChromaDB `$contains` 필터**: `codes` 필드가 문자열 타입이면 `{"codes": {"$contains": "Q2333"}}`이 부분 문자열 검색으로 동작합니다. `codes` 필드가 쉼표 구분 문자열(예: `"Q2333,R3200"`)로 저장되어 있다면 이 필터로 정확히 동작합니다.

2. **Reranker 초기 로딩 시간**: 최초 실행 시 모델 다운로드 (~1.1GB) 및 로딩에 1~3분 소요됩니다. 두 번째 실행부터는 캐시에서 로드됩니다.

3. **응답 지연 증가**: 7B 모델은 3B 대비 응답 생성에 2~3배 시간이 더 걸릴 수 있습니다. Streamlit 사이드바에 "모델 응답 중..." 스피너가 표시되도록 기존 UI가 구현되어 있어야 합니다.

4. **Q3 전체 답변 불가**: 보상가이드북이 인덱싱되기 전까지 수술해설과 1-5종 종별 분류 답변은 불가합니다. 이는 데이터 한계이며 버그가 아닙니다.

5. **기존 ChromaDB 컬렉션**: M10에서 청킹 메타데이터가 바뀌므로 기존 컬렉션을 삭제하고 재인덱싱해야 합니다 (`--stage all`). M8, M9 단계에서는 재인덱싱 불필요.

---

## 섹션 6 — Codex 완료 보고서 형식

각 마일스톤 완료 후 아래 형식으로 보고하세요:

```
## M{N} 완료 보고

### 변경된 파일
- [파일 경로]: [변경 내용 한 줄 요약]

### eval.py 결과
recall@8: X.XXX
page_accuracy: X.XXX

### 합격 기준 달성 여부
- [ ] 기준 1
- [ ] 기준 2

### 이슈 및 특이사항
[없으면 "없음"]
```
```

---

*이 명세는 `docs/06_STREAMLIT_TEST_RESULT_v1.md`와 `docs/07_IMPROVEMENT_PLAN.md`를 기반으로 기획자가 작성하였습니다.*
*Codex는 구현 중 명세와 충돌하는 상황이 발생하면 즉시 보고하고 진행 방향을 확인하세요.*
