# Codex Spec #61 — smoke_v2 recall 개선: 약관 조항 청크 분할 재설계

> **작성일:** 2026-05-13  
> **작성자:** Claude (검토자)  
> **구현 담당:** Codex  
> **성격:** 진단 + 청크 분할 개선 + eval 재실행  
> **우선순위:** 🟡 중간 (OCR eval 목표 달성 후 진행)

---

## 1. 배경 및 문제 진단

### 1-1. smoke_v2 recall 현황

`python scripts/eval.py --v2` 결과(2026-05-13):

| 항목 | 결과 |
|---|---|
| retrieval recall@8 | **0.600** (10건 중 6건) |
| 판정 키워드 일치율 | 0.900 |
| 문서 출처 일치율 | 1.000 |

MISS 4건:

| ID | 질문 | expected_pages | 실제 top_pages |
|---|---|---|---|
| [05] | 음주 골절 → 상해급여 보상? | `[5, 6]` | `78-84, 43-45, 36-38` |
| [06] | 선천성 심장질환 수술 → 실손 가능? | `[38]` | `8-31, 8-31, 71-78` |
| [08] | 가입 3일째 교통사고 → 보장개시일? | `[14, 15]` | `92-93, 36-38, 78-84` |
| [10] | 직장 동료 폭행 → 상해급여 보상? | `[5, 6]` | `78-84, 31-36, 36-38` |

### 1-2. 확인된 원인

`data/processed/chunks.jsonl`에서 확인한 약관 청크 구조:

- `page=4-8` 범위 청크가 **다수 존재**: 내용은 목차(TOC), 갱신 규정 소개, 안내 문구 위주.
- `page=8-31` 범위 청크가 소수 존재: 한 청크가 최대 23페이지를 포괄.
- p5-6 (음주·폭행 면책), p14-15 (보장개시일 특칙) 해당 내용이 **목차 텍스트와 동일 청크로 묶여** 임베딩 희석.

근본 원인: 약관 PDF는 페이지당 내용이 짧고, 현재 chunker가 페이지를 충분히 분리하지 않아 목차 페이지(4-8)와 실질 조항 페이지가 같은 청크에 섞임.

---

## 2. Task 1 — 진단: 실제 페이지 내용 확인

구현 전, 아래를 실행해 MISS 항목의 expected_pages 내용을 확인한다.

```bash
python3 -c "
import json

with open('data/processed/chunks.jsonl') as f:
    chunks = [json.loads(l) for l in f]

target_pages = [5, 6, 14, 15, 38]
yak = [c for c in chunks if c.get('metadata',{}).get('doc_short') == '약관']

for tp in target_pages:
    hits = [c for c in yak
            if c['metadata'].get('page_start', 0) <= tp <= c['metadata'].get('page_end', 0)]
    print(f'=== page {tp} 포함 청크 ({len(hits)}건) ===')
    for h in hits:
        ps = h['metadata']['page_start']
        pe = h['metadata']['page_end']
        print(f'  [{ps}-{pe}] {h[\"text\"][:150]}')
    print()
"
```

**확인 항목:**

1. p5-6 청크에 실제로 "음주", "상해 면책", "폭행" 관련 조항 텍스트가 있는가?
2. p14-15 청크에 "보장개시일", "보장개시", "계약일" 텍스트가 있는가?
3. p38 청크에 "선천성", "Q21", "보상하지 않는" 텍스트가 있는가?

**결과에 따른 분기:**

- **텍스트가 있음** → 청크 분할이 너무 넓어 임베딩 희석. → Task 2(청크 재분할)로 이동.
- **텍스트가 없음** → smoke_qa_v2.jsonl의 expected_pages 값이 잘못됨. → Task 3(eval set 수정)으로 이동.
- 진단 결과를 보고서에 명시할 것.

---

## 3. Task 2 — 약관 청크 재분할 (텍스트 있는 경우)

### 3-1. 문제 범위

약관 문서 청크만 대상. 다른 문서(실무가이드, 상담사례집 등)는 수정하지 않는다.

### 3-2. 개선 방향

현재 chunker는 `CHUNK_SIZE_CHARS`(기본값 환경변수)를 초과할 때 분리한다. 약관은 조문(제X조)마다 의미 단위가 명확하므로 조문 경계에서 우선 분리한다.

**`src/parser/chunker.py`에서 약관 조문 경계 인식 추가:**

조문 시작 패턴(`제\d+조`) 또는 소제목 패턴이 등장할 때, 현재 버퍼를 flush하고 새 청크를 시작한다. 이 로직은 `doc_short == "약관"` 인 경우에만 적용한다.

```python
import re

# 약관 조문 경계 패턴
_YAKGWAN_SECTION_PATTERN = re.compile(
    r'^(제\s*\d+\s*조|□|■|\[별표|<별표|\(별표)',
    re.MULTILINE
)

def is_yakgwan_section_boundary(line: str) -> bool:
    """약관 전용: 조문 또는 별표 시작 여부 판정"""
    return bool(_YAKGWAN_SECTION_PATTERN.match(line.strip()))
```

chunk_pages 함수(또는 동등 함수)에서, `doc_short == "약관"` 조건 하에 위 패턴을 활용해 경계 flush를 수행한다.

**목표 청크 구조:**
- 현재: `page=4-8` 1개 대형 청크
- 개선 후: `page=4-5` (목차), `page=5-6` (상해 면책), `page=6-7` (…) 식으로 분리

### 3-3. 재인제스트

청크 분할 수정 후:

```bash
python scripts/ingest.py --stage all
```

`data/processed/chunks.jsonl` 및 ChromaDB, BM25 인덱스 전체 재구축.

> **주의:** 약관 관련 청크만 변경되므로 OCR 문서(실무가이드, 상담사례집) 검색 품질에는 영향 없어야 함. 재인제스트 후 아래 검증 필수.

---

## 4. Task 3 — smoke_qa_v2.jsonl 수정 (텍스트 없는 경우)

진단 결과 해당 내용이 PDF에 없거나 페이지 번호가 다른 경우:

1. MISS 4건의 expected_pages를 실제 텍스트가 있는 페이지로 수정.
2. 수정 전 원본 값을 주석으로 남긴다(`// was: [5, 6]`).
3. 수정 근거를 보고서에 기재.

---

## 5. 검증

```bash
# 청크 재분할 확인
python3 -c "
import json
with open('data/processed/chunks.jsonl') as f:
    chunks = [json.loads(l) for l in f]
yak = [c for c in chunks if c.get('metadata',{}).get('doc_short') == '약관']
print(f'약관 총 청크수: {len(yak)}')
widths = [c['metadata']['page_end'] - c['metadata']['page_start'] for c in yak
          if c['metadata'].get('page_end') and c['metadata'].get('page_start')]
wide = [w for w in widths if w > 5]
print(f'6페이지 이상 청크: {len(wide)}건 (개선 전 대비 감소 여부 확인)')
"

# smoke recall 재측정
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py --v2

# smoke v1 회귀 없음 확인
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py

# OCR recall 회귀 없음 확인
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
  OLLAMA_HOST=http://localhost:9 python scripts/eval.py --ocr

# 전체 테스트
pytest -q
```

**기대 결과:**
- smoke_v2 recall@8: **0.600 → 0.800 이상** (4건 중 2건 이상 회복)
- smoke v1 recall@8: **1.000 유지** (회귀 없음)
- OCR recall@8: **1.000 유지** (회귀 없음)
- pytest: 전원 통과

---

## 6. 보고서 요구사항

`docs/61_SMOKEV2_RECALL_FIX_REPORT.md`에 다음을 포함한다:

1. Task 1 진단 결과: 각 MISS 페이지의 실제 텍스트 내용 (있음/없음)
2. 선택된 해결 경로 (Task 2 또는 Task 3) 및 이유
3. 수정 전후 약관 청크 수 비교
4. 6페이지 이상 대형 청크 건수 변화
5. smoke_v2/v1/OCR recall 비교표
6. pytest 결과

---

## 7. 중단 조건

- smoke v1 recall@8 < 1.000 → 즉시 롤백 후 보고
- OCR recall@8 < 1.000 → 즉시 롤백 후 보고
- pytest 실패 → 즉시 중단

---

## 8. 커밋

커밋 메시지: `Fix yakgwan early-page retrieval by improving article-boundary chunking (spec #61)`  
푸시: `origin/master`
