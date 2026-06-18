# 248. P1 Runtime Operations Alignment Report

## Summary

P1 계획에 따라 앱 기동 경로, 모델 선택 메타데이터, 일반 질의 기본 인덱스, 신규 파일 편입 진입점을 현재 운영 원칙에 맞게 정렬했다.

이번 변경은 새 보험 지식을 추가하지 않는다. 000번 규칙에 따라 코드는 런타임 선택과 source-grounded 경로 선택만 담당하고, 신규 지식 편입은 후보 생성 및 실무자 승인 단계로 남긴다.

## Changed Areas

### Runtime Model Policy

- `gpt-oss-120b` TensorRT-LLM 경로를 일반 앱 기동 후보에서 제거했다.
- `openai/gpt-oss-120b`, `gpt-oss-120b`, `/models/gpt-oss-120b`는 `unsupported_on_dgx_spark` 상태로 보존했다.
- `/system/models`는 기본 응답에서 선택 불가능 모델을 숨기고, `include_diagnostics=true`일 때만 미지원 진단 항목으로 표시한다.
- `ops/bin/insurance-rag-up`은 `--provider trtllm` 앱 기동을 즉시 거부한다.
- DGX 데스크톱 런처는 TensorRT-LLM 120B 시작/유지 선택지를 표시하지 않는다. 단, 상태 출력에서 이미 떠 있는 TRTLLM endpoint 감지는 진단용으로 유지한다.
- Python config와 DGX shell 환경의 TRTLLM candidate 기본값은 비워두고, 120B alias는 disabled/unsupported 진단 메타데이터로만 남겼다.

### Default Retrieval Path

- 사용자-facing `default`, `basic`, `기본`, `기본 인덱스` 요청은 보정본 OCR 포함 경로인 `v2_only`로 해석한다.
- `/system/status`의 기본 `bm25`/`chroma` 상태도 사용자-facing 기본값과 같이 `v2_only` 기준으로 표시한다.
- OCR 비교 목적의 `ocr_comparison`만 `v1_v2_combined`로 유지한다.
- 명시적으로 `v1_v2_combined`를 요청한 경우에는 기존 결합 인덱스 동작을 유지한다.

### Clause Detail Diagnostics

- `clause_detail_rows` manifest 상태를 `/system/status` diagnostics에 노출한다.
- 진단 정보는 row 수, 파일 존재 여부, 상태만 제공하며 답변 지식이나 지급 판단을 만들지 않는다.

### New File Intake Planning

- `src/ingest/file_intake_planner.py`를 추가했다.
- PDF, Excel, image 입력에 대해 어떤 파이프라인을 태울지 dry-run 계획만 생성한다.
- 계획 결과는 `mutates_indexes=false`이며, 신규 지식 편입은 `ontology_candidates_pending`과 `wait_for_practitioner_approval` 단계로 남긴다.
- 실제 파일 선택 UI, OCR 실행, 인덱스 갱신, GraphDB rebuild는 이번 P1 범위에 포함하지 않았다.

### README

- README를 현재 앱 구조 기준으로 정리했다.
- legacy Streamlit 중심 설명을 제거하고 FastAPI + 정적 SPA, DGX SGLang/vLLM 운영, OCR 포함 기본 인덱스, 신규 파일 편입 원칙을 명시했다.

## Ponytail Review Fixes

Ponytail 관점에서 다음 과잉 또는 결점을 줄였다.

- 데스크톱 런처에 남아 있던 미사용 TensorRT-LLM 120B image/model path 설정을 제거했다.
- `trtllm_model_ready` 함수는 더 이상 호출되지 않아 삭제했다.
- 이미 떠 있는 TRTLLM endpoint를 "현재 실행 중인 모델 유지" 선택지로 보여주던 충돌을 제거했다.
- TRTLLM candidate export를 빈 값으로 단순화했다.
- runtime model diagnostics 순서를 dict 정의 순서로 고정했다.
- `SystemStatusResponse.diagnostics`의 mutable 기본값을 `Field(default_factory=dict)`로 교체했다.

## Validation

통과:

```bash
python -m pytest tests/test_runtime_model_metadata.py tests/test_index_mode_defaults.py tests/test_file_intake_planner.py tests/test_llm_factory.py tests/test_pipeline.py tests/test_clause_detail_rows.py -q
```

결과:

- `85 passed`

통과:

```bash
bash -n ops/bin/insurance-rag-common ops/bin/insurance-rag-desktop-launcher ops/bin/insurance-rag-up
```

결과:

- shell syntax error 없음

통과:

```bash
rg -n 'TRTLLM_IMAGE|TRTLLM_REQUIRE_LOCAL_IMAGE|TRTLLM_GPT_OSS_MODEL|TRTLLM_GPT_OSS_MODEL_DIR' ops/bin/insurance-rag-desktop-launcher ops/bin/insurance-rag-common ops/bin/insurance-rag-up
rg -n 'current\|trtllm|start\|trtllm|TensorRT-LLM 유지' ops/bin/insurance-rag-desktop-launcher
```

결과:

- 일반 데스크톱 선택 경로에서 120B TRTLLM 시작/유지 항목 없음

미실행/실패:

```bash
python -m pytest tests/test_api_system_status.py tests/test_api_chat_stream.py -q
python -m pytest tests/test_api_auth_system.py -q
```

결과:

- 현재 로컬 worktree Python 환경에 `fastapi`, `aiosqlite`가 없어 collection 단계에서 중단된다.
- `tests/test_api_auth_system.py`는 `fastapi` 미설치로 collection 단계에서 중단된다.
- `tests/test_api_system_status.py`는 `fastapi` 미설치로 collection 단계에서 중단된다.
- `tests/test_api_chat_stream.py`는 `aiosqlite` 미설치로 collection 단계에서 중단된다.
- DGX 메인 저장소의 `.venv` 또는 완전한 로컬 venv에서 API 계열 테스트를 재실행해야 한다.

## Self-Inspection Against 000 Guardrails

- 보험 보장, 면책, 감액, 한도, 공제율, 지급 판단 수치를 코드에 추가하지 않았다.
- 신규 파일 편입 계획은 인덱스/GraphDB를 직접 변경하지 않고 실무자 승인 단계를 요구한다.
- 일반 질의 기본 경로가 OCR 보정본을 제외하지 않도록 `v2_only`를 사용자-facing 기본값으로 조정했다.
- 120B는 운영 선택지가 아니라 미지원 진단 메타데이터로만 남겼다.
- Streamlit legacy 실행 경로는 수정하지 않았다.
- 원본 데이터, OCR 산출물, DB, 모델 파일은 수정하지 않았다.

## Remaining Risk

- `/system/status`, `/system/models`의 FastAPI route 테스트는 현재 로컬 의존성 부족으로 미검증이다.
- `ops/bin/switch-trtllm-model` 같은 직접 진단 스크립트는 남아 있다. 앱 기동 wrapper와 데스크톱 런처에서는 차단되지만, 운영자가 직접 호출하면 과거 진단 경로를 재시도할 수 있다.
- 신규 파일 편입은 아직 dry-run planner이다. 실제 파일 탐색기, 자동 분류, DB staging, ontology candidate 생성, approval/rebuild 연결은 다음 단계 작업이다.
