# 보험 문서 RAG 챗봇

신한EZ손해보험 보상 실무를 돕기 위한 FastAPI + 정적 SPA 기반 RAG 애플리케이션입니다. 약관, 심평원 고시, 실무가이드, 상담사례집, 관계형 표준코드, GraphDB, 보험금 계산 로직을 source-grounded 방식으로 결합합니다.

원본 PDF/XLSX, OCR 추출본, 백업 자료, 사용자 데이터, 비밀키는 Git에 커밋하지 않습니다.

## Current Official Runtime

정식 앱 경로는 FastAPI가 `frontend/` 정적 SPA와 `/api/*` API를 함께 제공하는 구조입니다.

```bash
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

일반 질의의 사용자-facing 기본 인덱스는 보정본 OCR 데이터가 포함되는 `v2_only`입니다. `default`, 빈 값, 기본 계열 alias는 일반 사용자 경로에서 `v2_only`로 해석됩니다. OCR 문서가 검색에서 빠지는 일반 질의 경로는 허용하지 않습니다.

## DGX Runtime

DGX Spark 메인 저장소 기준 실행은 `ops/bin` wrapper를 사용합니다.

```bash
/srv/ai-ops/bin/insurance-rag-up --provider sglang --model qwen3-next-80b-a3b-instruct-fp8
```

데스크톱 아이콘은 `ops/bin/insurance-rag-desktop-launcher`를 통해 현재 실행 중인 LLM 유지, SGLang/vLLM 전환, 온톨로지 승인 검토를 제공합니다. `gpt-oss-120b`는 SGLang, vLLM, Transformers, TensorRT-LLM 경로에서 DGX Spark 편입 불가로 판정되어 일반 선택지에서 제외됩니다.

## Local Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/manage_users.py init
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

기본 실행은 외부 네트워크 다운로드를 전제로 하지 않습니다. 필요한 embedding/reranker/LLM 모델은 운영 환경에 미리 준비해야 합니다.

## Data And Evidence Policy

- 보험금 지급, 면책, 감액, 공제, 한도 등 보험 지식은 코드 상수로 하드코딩하지 않습니다.
- 신규 PDF, Excel, 이미지 파일은 즉시 운영 인덱스를 변경하지 않고 dry-run intake plan에서 시작합니다.
- 신규 온톨로지, alias, relation, rule 후보는 pending 상태로 생성하고 실무자 승인 후에만 운영 지식으로 승격합니다.
- LLM 출력은 최종 계산 권한이 아니며, 수치와 판단은 원문 row, 약관, 관계형 DB, 승인된 GraphDB 근거에서 읽어야 합니다.

## New File Intake

신규 파일 추가 기능은 다음 단계로 확장됩니다.

```python
from src.ingest.file_intake_planner import plan_file_intake

plan = plan_file_intake("new_policy.pdf")
```

현재 구현은 비파괴 dry-run 계획 생성입니다. Excel, PDF, 이미지 입력을 분류하고, OCR/표 추출/온톨로지 후보 생성/실무자 승인 대기 단계를 반환합니다. 이 함수는 DB, 인덱스, 온톨로지 manifest를 변경하지 않습니다.

## Testing

관련 범위별 검증을 먼저 실행합니다.

```bash
python -m pytest tests/test_runtime_model_metadata.py tests/test_index_mode_defaults.py tests/test_file_intake_planner.py -q
bash -n ops/bin/insurance-rag-common ops/bin/insurance-rag-desktop-launcher
```

전체 회귀가 필요할 때:

```bash
python -m pytest -q
```

로컬 의존성이 부족한 환경에서는 FastAPI, SQLAlchemy, aiosqlite, OCR 관련 테스트가 먼저 실패할 수 있습니다. DGX 검증에는 `/srv/shared/projects/insurance-rag-chatbot/.venv/bin/python`을 우선 사용합니다.

## Legacy Streamlit

`src/ui/streamlit_app.py`는 과거 검증용 legacy 경로입니다. 신규 기능 개발, 운영 검증, 문서화의 기준은 FastAPI + SPA입니다. 보존 필요가 별도로 확인되지 않는 한 Streamlit 앱은 새 기능 대상으로 업데이트하지 않습니다.

## Key Documents

- `docs/000_PROJECT_DEVELOPMENT_GUARDRAILS.md`
- `docs/247_P0_SOURCE_GROUNDED_KNOWLEDGE_REMOVAL_REPORT.md`
