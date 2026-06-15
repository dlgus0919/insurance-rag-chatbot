# 233. clause_detail_rows and Policy Externalization Patch Report

작성일: 2026-06-15

## 목적

`docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`, `docs/231_CLAUSE_DETAIL_LOOKUP_SOURCE_GROUNDED_PLAN.md`, `docs/232_CLAUSE_DETAIL_LOOKUP_SOURCE_GROUNDED_PATCH_REPORT.md` 기준으로 다음을 구현했다.

- 자동 RAG profile별 Top-K/temperature 정책을 코드 상수에서 정책 파일로 분리
- `clause_detail_lookup` facet, row boundary, conflict, scoring 기준을 정책 파일로 분리
- 기존 OCR `table_json` chunk에서 `clause_detail_rows` manifest를 생성/로드하는 구조화 evidence 계층 추가
- semi-adaptive-k를 기본 전략으로 켜고, 프론트엔드에서 톱니 버튼으로 끌 수 있게 노출

## 핵심 설계

### 정책 파일 분리

- `config/auto_rag_profile_policy.json`
  - profile별 `top_k`, `min_top_k`, `max_top_k`, `temperature` 처리 기준
  - 특정 상품의 정답 수치, 지급 판단, 공제율, 한도는 포함하지 않음
- `config/clause_detail_lookup_policy.json`
  - row parsing regex, facet group, required facet group, coverage conflict, scoring weight
  - 정답값이 아니라 검색/검증 기준만 포함

코드의 기존 상수는 정책 파일을 읽을 수 없을 때의 fallback으로만 남겼다.

### clause_detail_rows

- `scripts/build_clause_detail_rows.py`
  - `data/processed/chunks_v2_manual.jsonl` 또는 `chunks_v1_v2_combined.jsonl`의 기존 `metadata.table_json`만 읽음
  - OCR 또는 table extraction 로직은 재작성하지 않음
  - row마다 `doc_short`, `article`, `table_label`, `page`, `chunk_id`, `parent_heading`, `row_label`, `value_text`, `numbers`, `source_metadata`를 JSONL로 저장
- `src/rag/clause_detail_rows.py`
  - index mode별 manifest 경로 해석
  - JSONL manifest lazy load
- `src/rag/pipeline.py`
  - manifest row를 먼저 점수화
  - manifest가 없거나 충분하지 않으면 검색 chunk의 `table_json`, 그다음 기존 text row fallback 사용
  - 답변 수치는 `value_text` 또는 원문 text row에서 추출된 값만 사용

DGX 생성 결과:

- `v2_only`: 892개 table chunk에서 10,126개 row 생성
- `v1_v2_combined`: 1,068개 table chunk에서 11,236개 row 생성
- 생성 manifest는 `data/*` gitignore 범위의 인덱스 산출물이므로 커밋하지 않음

## 검증 결과

로컬:

- `python -m pytest tests/test_clause_detail_rows.py tests/test_auto_rag_params.py tests/test_auto_rag_param_eval.py tests/test_pipeline.py -q`
  - 63 passed
- `python -m py_compile src/rag/pipeline.py src/rag/auto_params.py src/rag/clause_detail_rows.py src/api/rag_service.py src/api/routes/chat.py src/api/schemas/chat.py scripts/eval_auto_rag_params.py scripts/build_clause_detail_rows.py`
  - passed
- `find frontend/js -name '*.js' -print0 | xargs -0 -n1 node --check`
  - passed
- `npm run build` in `frontend/`
  - passed

DGX:

- `.venv/bin/python -m pytest tests/test_clause_detail_rows.py tests/test_auto_rag_params.py tests/test_auto_rag_param_eval.py tests/test_api_chat_stream.py::test_chat_stream_applies_auto_params_and_records_requested_values tests/test_api_chat_stream.py::test_chat_stream_can_disable_adaptive_k_separately tests/test_api_chat_stream.py::test_rag_diagnostics_include_clarification_and_normalized_terms tests/test_pipeline.py -q`
  - 66 passed, 1 warning
- `find frontend/js -name "*.js" -print0 | xargs -0 -n1 node --check && cd frontend && npm run build`
  - passed
- `scripts/build_clause_detail_rows.py --index-mode v2_only`
  - 10,126 rows
- `scripts/build_clause_detail_rows.py --index-mode v1_v2_combined`
  - 11,236 rows

`policy_xlsx_018/019/026` 스모크:

- 세 문항 모두 필수 수치 포함, LLM 미사용, deterministic source-grounded answer 경로 통과
- 단, 현재 DGX `chunks_v2_manual.jsonl`과 `chunks_v1_v2_combined.jsonl`에는 `약관`의 table_json chunk가 0개임
- 따라서 세 문항은 `clause_detail_rows`가 아니라 기존 text row fallback으로 통과
- 이는 이번 코드 경로 결함이 아니라 현재 보정본 OCR table_json 산출 범위가 `실무가이드`, `상담사례집` 중심인 데이터 상태로 확인됨

## 000번 규칙 self-inspection

- 특정 상품의 정답 수치, 지급 판단, 공제율, 한도를 새 정책 파일이나 코드에 추가하지 않았다.
- 새 정책 파일은 synonym/facet/row boundary/scoring 같은 처리 기준만 가진다.
- `clause_detail_rows` manifest 값은 원천 OCR `table_json` row에서만 복사한다.
- LLM이 수치나 지급 판단을 생성하도록 하지 않았다.
- pre-existing deterministic guard의 일부 hardcoded answer block은 이번 범위에서 새로 추가하지 않았으며, 별도 000번 규칙 정리 대상으로 남긴다.

## 남은 위험

- 현재 약관 PDF는 table_json chunk가 없어 `policy_xlsx_018/019/026`은 text fallback에 의존한다.
- 약관 표까지 row manifest로 쓰려면 약관 PDF table extraction 또는 chunk metadata 보강 작업이 별도 필요하다.
- semi-adaptive-k 기본값은 켰지만, 프론트엔드에서 끌 수 있고 API audit에 `adaptive_k` 및 top-k strategy를 기록한다.
