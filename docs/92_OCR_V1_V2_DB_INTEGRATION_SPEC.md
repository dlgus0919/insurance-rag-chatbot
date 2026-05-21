# 92. OCR v1/v2 DB Integration Spec For Sub-Agent

작성일: 2026-05-21
작성 위치: DGX Spark `/srv/shared/projects/insurance-rag-chatbot`
검토 대상: `/srv/shared/workspaces/dani/insurance-rag-chatbot`
목적: Dani 워크스페이스에서 개발된 OCR 원본(v1) 및 수동 보정본(v2) DB화/매핑 작업을 메인 `master`에 안전하게 편입하기 위한 구체 명세를 제공한다.

## 1. 현재 상황 요약

메인 저장소 기준:

- 기준 디렉터리: `/srv/shared/projects/insurance-rag-chatbot`
- 현재 메인에는 다른 서브 에이전트의 미커밋 변경이 존재한다.
- 확인된 미커밋 변경:
  - `scripts/eval.py`
  - `src/config.py`
  - `src/llm/factory.py`
  - `src/rag/evidence.py`
  - `src/rag/pipeline.py`
  - `src/ui/streamlit_app.py`
  - `eval/conflict_qa.jsonl`
  - `tests/test_conflict_detection.py`
  - `docs/00_START_HERE.md`, `docs/89_...`, `docs/90_...`, `docs/91_...`

Dani 워크스페이스 기준:

- 위치: `/srv/shared/workspaces/dani/insurance-rag-chatbot`
- 브랜치: `master`
- `origin/master` 기준 4개 커밋 앞섬
- 주요 커밋:
  - `437bcac Add OCR v1/v2 mapping pipeline and SGLang runtime model validation`
  - `e0de8b8 Set default multi-model config for SGLang GPT-OSS/Gemma4 and Ollama Exaone`
  - `0394c72 Stabilize embedder loading and disable login-time SGLang switch by default`
  - `e267dfe Add vLLM runtime validation and disable app-switch by default`

중요: OCR v1/v2 DB화 작업은 주로 `437bcac`에 들어 있으나, 해당 커밋 안에도 Streamlit/LLM runtime validation 변경이 일부 섞여 있다. 뒤의 3개 커밋은 LLM/provider 런타임 설정 변경 성격이 강하므로 이번 OCR DB 편입 범위에 자동 포함하지 않는다.

## 2. Dani 작업 산출물 진단

### 2.1 코드 변경 범위

`2401fde..HEAD` 기준 Dani 변경 파일은 다음 21개다.

```text
.gitignore
scripts/build_ocr_combined_chunks.py
scripts/build_v1_v2_pair_mapping.py
scripts/cli.py
scripts/ingest.py
scripts/rechunk_v1_sangdam_target16.py
src/config.py
src/llm/prompt.py
src/parser/ocr_chunker.py
src/rag/pipeline.py
src/retrieval/embedder.py
src/retrieval/index_mode.py
src/retrieval/pair_mapping.py
src/ui/admin_page.py
src/ui/streamlit_app.py
tests/test_build_v1_v2_pair_mapping.py
tests/test_embedder.py
tests/test_ingest.py
tests/test_ocr_chunker.py
tests/test_pipeline.py
tests/test_streamlit_app.py
```

OCR DB화에 직접 필요한 핵심 파일은 다음이다.

```text
scripts/build_v1_v2_pair_mapping.py
scripts/build_ocr_combined_chunks.py
scripts/rechunk_v1_sangdam_target16.py
scripts/ingest.py
src/parser/ocr_chunker.py
src/retrieval/index_mode.py
src/retrieval/pair_mapping.py
src/rag/pipeline.py
src/llm/prompt.py
src/ui/admin_page.py
src/ui/streamlit_app.py
tests/test_build_v1_v2_pair_mapping.py
tests/test_ingest.py
tests/test_ocr_chunker.py
tests/test_pipeline.py
tests/test_streamlit_app.py
```

주의 파일:

- `src/config.py`, `src/retrieval/embedder.py`, `.gitignore`, `tests/test_embedder.py`는 후속 LLM/offline 안정화 커밋과 관련된다. 이번 작업에 필요하면 별도 검토 후 최소 패치만 편입한다.
- `scripts/cli.py`의 Dani 변경은 provider factory 대신 `OllamaClient` 직접 의존으로 되돌리는 부분이 있어 현재 메인 설계와 충돌한다. 그대로 복사하지 않는다.
- `src/ui/streamlit_app.py`와 `src/rag/pipeline.py`는 현재 메인 미커밋 변경과 직접 충돌한다. 수동 병합이 필요하다.

### 2.2 Runtime 데이터 산출물

Dani 워크스페이스에는 다음 OCR v1/v2 runtime 산출물이 존재한다.

```text
data/processed/chunks_v1_original_ocr.jsonl        2,044 lines
data/processed/chunks_v1_rechunked_target16.jsonl  2,060 lines
data/processed/chunks_v2_manual.jsonl              2,060 lines
data/processed/chunks_v1_v2_combined.jsonl         4,104 lines
data/mapping/v1_v2_pairs_실무가이드.jsonl           927 lines
data/mapping/v1_v2_pairs_상담사례집.jsonl           1,133 lines
```

인덱스 산출물:

```text
data/index_v1_original_ocr/bm25.pkl
data/index_v1_original_ocr/chroma/
data/index_v2_manual/bm25.pkl
data/index_v2_manual/chroma/
data/index_v1_v2_combined/bm25.pkl
data/index_v1_v2_combined/chroma/
```

Low-confidence mapping report:

```text
reports/mapping_low_confidence/summary.json
reports/mapping_low_confidence/low_confidence_실무가이드.jsonl
reports/mapping_low_confidence/low_confidence_상담사례집.jsonl
```

요약:

- `실무가이드`: total pairs 927, low confidence 18, ratio 1.94%
- `상담사례집`: total pairs 1,133, low confidence 147, ratio 12.97%

판단:

- `실무가이드` 매핑은 비교적 안정적이다.
- `상담사례집`은 low-confidence 비율이 높아, 운영 기본값으로 원본(v1) 컨텍스트를 강하게 주입하기 전에 검수 정책이 필요하다.

### 2.3 실행 검증

Dani 워크스페이스에서 아래 테스트를 실행했다.

```bash
.venv/bin/python -m pytest \
  tests/test_build_v1_v2_pair_mapping.py \
  tests/test_ingest.py \
  tests/test_ocr_chunker.py \
  tests/test_pipeline.py \
  -q
```

결과:

```text
44 passed, 1 warning in 0.37s
```

경고는 `.pytest_cache` 권한 문제이며 테스트 로직 실패는 아니다.

## 3. 편입 원칙

### 3.1 전체 cherry-pick 금지

Dani의 `437bcac`를 그대로 cherry-pick하지 않는다. 이유:

- OCR DB 작업과 SGLang runtime validation 변경이 섞여 있다.
- 현재 메인에는 다른 서브 에이전트의 RAG conflict/evidence 변경이 미커밋 상태로 존재한다.
- `src/rag/pipeline.py`, `src/ui/streamlit_app.py`, `src/config.py`가 양쪽 모두에서 변경되었으므로 자동 병합은 회귀 위험이 높다.

### 3.2 코드와 runtime 산출물 분리

Git에 편입할 것:

- 재현 가능한 스크립트
- retrieval/index mode helper
- optional pair mapping loader
- tests
- 운영 문서

Git에 편입하지 않을 것:

- `data/index_v1_original_ocr/`
- `data/index_v2_manual/`
- `data/index_v1_v2_combined/`
- `data/processed/chunks_v1_*.jsonl`, `chunks_v2_manual.jsonl`, `chunks_v1_v2_combined.jsonl`
- `data/mapping/*.jsonl`
- Chroma sqlite/db 산출물
- handoff tarball

단, 위 runtime 산출물은 DGX 운영 디렉터리 또는 ignored `data/` 경로에 별도 반입하여 앱에서 사용할 수 있게 한다.

### 3.3 기본 검색 모드

초기 기본값은 `v2_only`로 둔다.

- 보정본(v2)을 canonical source로 사용한다.
- 원본(v1)은 교차검증 보조 자료로만 사용한다.
- `v1_v2_combined`는 관리자/평가 모드에서만 우선 제공한다.
- `상담사례집` low-confidence 매핑 147건은 검수 전까지 LLM prompt에 과도하게 주입하지 않는다.

## 4. Sub-Agent 작업 명세

아래 지시를 그대로 서브 에이전트에게 전달한다.

### 4.1 Preflight

1. 반드시 DGX 메인 저장소에서 작업한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
```

2. 현재 미커밋 변경을 확인한다.

```bash
git status --short --branch
```

3. 현재 다른 서브 에이전트 변경이 있으면 먼저 별도 커밋 또는 stash 여부를 사용자에게 확인한다. 임의로 되돌리거나 덮어쓰지 않는다.

4. Dani 워크스페이스는 읽기 전용 원본으로 취급한다.

```bash
DANI=/srv/shared/workspaces/dani/insurance-rag-chatbot
```

5. `dani` repo는 소유자가 다르므로 git 조회 시 safe.directory를 command-local로 지정한다.

```bash
git -c safe.directory=/srv/shared/workspaces/dani/insurance-rag-chatbot -C "$DANI" log --oneline -5
```

### 4.2 코드 편입 단계

#### Step 1. 새 파일 추가

다음 파일은 Dani 버전을 기준으로 메인에 추가한다.

```text
scripts/build_v1_v2_pair_mapping.py
scripts/build_ocr_combined_chunks.py
src/retrieval/index_mode.py
src/retrieval/pair_mapping.py
tests/test_build_v1_v2_pair_mapping.py
```

`scripts/rechunk_v1_sangdam_target16.py`는 그대로 추가하지 말고 아래 보완 후 추가한다.

- 원본 manifest를 직접 수정하지 않도록 한다.
- 입력 manifest root와 출력 manifest root를 인자로 받게 한다.
- 기본 실행에서 `data/extracted_v1_rechunked/`가 없으면 명시적 오류를 내고 종료한다.
- `--in-place` 옵션 없이는 source manifest를 변경하지 않는다.

#### Step 2. `scripts/ingest.py` 최소 패치

Dani 변경 중 다음 기능만 이식한다.

- `build_chunks(..., extracted_root=None, chunks_path=None)` 인자 추가
- `build_index(..., chunks_path=None, index_root=None)` 인자 추가
- CLI 옵션 추가:
  - `--extracted-root`
  - `--chunks-path`
  - `--index-root`

주의:

- 기존 default ingest 동작은 그대로 유지한다.
- 기존 `data/processed/chunks.jsonl`, `data/index/` 경로를 깨지 않는다.

#### Step 3. `src/parser/ocr_chunker.py` hierarchy context 이식

Dani 변경 중 OCR chunk metadata에 `volume`, `part`, `chapter`, `section`을 전파하는 로직을 이식한다.

검증 조건:

- 기존 OCR chunk 생성 테스트 통과
- 새 테스트 `test_chunk_from_extracted_propagates_hierarchy_context` 통과
- table block이 직전 text heading context를 상속하는지 확인

#### Step 4. `src/rag/pipeline.py` pair mapping hook 이식

현재 메인의 conflict/evidence 변경을 보존하면서 다음 기능을 추가한다.

- `RagPipeline.__init__`에 optional 인자 추가:
  - `pair_mapping_store=None`
  - `v1_chunk_lookup: dict[str, dict] | None = None`
- `_build_paired_ocr_context()` 추가
- `build_prompt()` 또는 공통 prompt builder에서 retrieved v2 chunk에 대한 v1 대응 텍스트를 제한적으로 주입

제약:

- `max_pairs` 기본값은 3 이하로 유지한다.
- `pair.use_v1`이 true이고 confidence/score가 충분한 경우만 사용한다.
- 보정본(v2)과 원본(v1)이 충돌하면 v2 우선 원칙을 prompt에 명시한다.
- 현재 메인의 conflict detection prompt injection을 제거하지 않는다.

#### Step 5. `src/llm/prompt.py` v1/v2 원칙 추가

시스템 프롬프트에 다음 원칙을 짧게 추가한다.

- 보정본(v2)을 canonical로 사용한다.
- 원본(v1)은 수치, 코드, 고유명사 교차검증 보조로만 사용한다.
- v1/v2 충돌 시 v2를 우선하고 충돌 사실을 짧게 밝힌다.

주의:

- 프롬프트를 길게 늘리지 않는다.
- 최근 추가된 source-grounding 및 conflict-separation 지침과 중복되지 않게 병합한다.

#### Step 6. UI 편입

`src/ui/streamlit_app.py`는 현재 메인과 충돌 가능성이 높으므로 수동 병합한다.

추가할 기능:

- sidebar에 관리자/고급 옵션 성격의 `OCR 인덱스 모드` 선택 추가
- 선택지:
  - `보정본 OCR만` -> `v2_only`
  - `원본+보정본 OCR 통합` -> `v1_v2_combined`
- `_load_heavy_components(index_mode)`로 BM25/Chroma 경로를 전환
- `v2_only` 또는 `v1_v2_combined`일 때 pair mapping과 v1 lookup을 optional load
- log detail에 `index_mode` 기록

주의:

- provider/model dropdown, strict mode, admin diagnostics 등 현재 메인 변경을 덮어쓰지 않는다.
- `v1_v2_combined` 인덱스 파일이 없을 때는 앱 전체를 죽이지 말고 해당 모드 선택 시 명시적 오류를 보여준다.

`src/ui/admin_page.py`에는 OCR pair mapping summary table을 추가한다.

#### Step 7. `scripts/cli.py`는 그대로 복사 금지

Dani의 `scripts/cli.py`는 `OllamaClient` 직접 의존으로 되돌아가는 변경이 있다. 현재 메인의 provider factory 방향과 충돌하므로 다음만 수동 반영한다.

- `--index-mode` 인자 추가
- `resolve_index_paths(index_mode)`로 BM25/Chroma 경로 선택
- LLM provider 생성은 현재 메인의 factory 기반 구조를 유지

### 4.3 Runtime 산출물 반입 단계

코드 병합과 별도 단계로 진행한다. Git commit에는 포함하지 않는다.

1. Dani 산출물을 tar로 묶는다.

```bash
cd /srv/shared/workspaces/dani/insurance-rag-chatbot
tar -czf /srv/shared/projects/insurance-rag-chatbot/handoff/ocr_v1_v2_db_dani_20260521.tar.gz \
  data/processed/chunks_v1_original_ocr.jsonl \
  data/processed/chunks_v1_rechunked_target16.jsonl \
  data/processed/chunks_v2_manual.jsonl \
  data/processed/chunks_v1_v2_combined.jsonl \
  data/mapping \
  reports/mapping_low_confidence \
  data/index_v1_original_ocr \
  data/index_v2_manual \
  data/index_v1_v2_combined
```

2. 메인 repo에서 압축을 해제한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
tar -xzf handoff/ocr_v1_v2_db_dani_20260521.tar.gz
```

3. 산출물은 ignored runtime artifact인지 확인한다.

```bash
git status --short data reports handoff
```

대형/생성 산출물이 Git에 잡히면 `.gitignore`를 먼저 보완하고, 산출물을 커밋하지 않는다.

### 4.4 검증 단계

코드 병합 후 최소 검증:

```bash
pytest \
  tests/test_build_v1_v2_pair_mapping.py \
  tests/test_ingest.py \
  tests/test_ocr_chunker.py \
  tests/test_pipeline.py \
  tests/test_streamlit_app.py \
  -q
```

전체 회귀:

```bash
pytest -q
```

인덱스 파일 존재 확인:

```bash
python - <<'PY'
from pathlib import Path
for p in [
    'data/index_v2_manual/bm25.pkl',
    'data/index_v2_manual/chroma/chroma.sqlite3',
    'data/index_v1_v2_combined/bm25.pkl',
    'data/index_v1_v2_combined/chroma/chroma.sqlite3',
    'data/mapping/v1_v2_pairs_실무가이드.jsonl',
    'data/mapping/v1_v2_pairs_상담사례집.jsonl',
]:
    path = Path(p)
    print(p, 'OK' if path.exists() else 'MISSING')
PY
```

mapping count 검증:

```bash
wc -l \
  data/mapping/v1_v2_pairs_실무가이드.jsonl \
  data/mapping/v1_v2_pairs_상담사례집.jsonl \
  data/processed/chunks_v1_v2_combined.jsonl
```

기대값:

```text
927   data/mapping/v1_v2_pairs_실무가이드.jsonl
1133  data/mapping/v1_v2_pairs_상담사례집.jsonl
4104  data/processed/chunks_v1_v2_combined.jsonl
```

검색 회귀는 LLM 호출 없이 먼저 확인한다.

```bash
RERANKER_ENABLED=false python scripts/eval.py --ocr
```

단, 현재 다른 팀원이 GPU/LLM 리소스를 사용 중이면 LLM provider 호출 또는 대형 모델 평가는 수행하지 않는다.

## 5. 통합 후 운영 기본값

초기 운영 기본값:

```text
OCR index mode: v2_only
Canonical source: manual-corrected OCR v2
Auxiliary source: original OCR v1 pair context, max 3 pairs
Combined index: admin/evaluation only
```

권장 UI 표현:

- `보정본 OCR만` — 운영 기본값
- `원본+보정본 OCR 통합` — 관리자 검증/비교용

운영자가 `원본+보정본 OCR 통합`을 사용할 때는 답변에서 원본 OCR이 보정본을 대체하지 않도록 주의한다.

## 6. 주요 위험과 대응

### 6.1 상담사례집 low-confidence 비율

`상담사례집` pair mapping은 low-confidence 비율이 12.97%로 높다.

대응:

- low-confidence pair는 prompt 주입에서 제외한다.
- 관리자 페이지에 low-confidence 수량과 report path를 표시한다.
- 추후 검수 후 threshold 또는 page-specific patch를 조정한다.

### 6.2 `rechunk_v1_sangdam_target16.py`의 source mutation

Dani 버전은 manifest를 직접 수정한다.

대응:

- 메인 편입 전 copy-on-write 방식으로 고친다.
- `--in-place` 옵션 없이는 원본 manifest를 수정하지 않는다.

### 6.3 Streamlit/pipeline 충돌

현재 메인에는 다른 서브 에이전트의 evidence/conflict 변경이 있다.

대응:

- `pipeline.py`, `streamlit_app.py`는 파일 복사가 아니라 수동 병합한다.
- 기존 source coverage, conflict detection, provider UI를 보존한다.

### 6.4 runtime artifact Git 오염

Chroma/BM25/JSONL 산출물이 Git에 잡힐 수 있다.

대응:

- `git status --short`로 확인한다.
- 필요 시 `.gitignore`에 `data/index_v*_*/`, `data/mapping/`, `data/processed/chunks_v*_*.jsonl`, `handoff/`를 추가한다.
- 산출물은 commit하지 않는다.

## 7. Commit 전략

권장 커밋 분리:

1. `feat(ocr): add v1-v2 mapping and index mode utilities`
   - scripts, retrieval helper, parser chunk metadata, tests
2. `feat(rag): support optional paired OCR context`
   - pipeline, prompt, UI/admin 최소 병합
3. `docs(ocr): document v1-v2 db integration`
   - 본 문서와 구현 보고서

runtime artifact 반입은 Git commit이 아니라 운영 작업 로그/보고서에만 남긴다.

## 8. 서브 에이전트 완료 보고서 요구사항

작업 완료 후 `docs/93_OCR_V1_V2_DB_INTEGRATION_IMPL_REPORT.md`를 작성한다.

보고서에는 반드시 포함한다.

- 실제 편입한 파일 목록
- Dani 원본 커밋/파일과 달라진 부분
- runtime 산출물 반입 여부와 경로
- mapping count와 low-confidence summary
- 실행한 테스트 명령과 결과
- 실행하지 않은 검증과 이유
- Git에 포함하지 않은 데이터 산출물 목록
- 현재 메인 미커밋 변경과 충돌 없이 병합했는지 여부

## 9. 최종 판단

Dani 작업은 OCR 원본(v1)과 수동 보정본(v2)을 비교·통합하기 위한 중요한 기반이다. 다만 현재 형태는 순수 OCR DB화 코드와 LLM/provider runtime 변경이 섞여 있고, 메인 저장소도 동시에 다른 개선 작업이 진행 중이다.

따라서 편입 방식은 다음이 가장 안전하다.

1. OCR DB화 핵심 코드만 선별 편입한다.
2. runtime 산출물은 Git이 아닌 ignored 운영 데이터로 반입한다.
3. `v2_only`를 기본값으로 유지한다.
4. `v1_v2_combined`는 관리자/평가 모드로 먼저 검증한다.
5. low-confidence pair 검수 후 원본(v1) 보조 컨텍스트 사용 범위를 넓힌다.
