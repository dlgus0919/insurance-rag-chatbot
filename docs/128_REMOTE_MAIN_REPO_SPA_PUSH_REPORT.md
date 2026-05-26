# 원격 메인 repo 정리 및 SPA 실행 가이드 반영 보고서

작성일: 2026-05-26
대상 repo: `/srv/shared/projects/insurance-rag-chatbot`
대상 branch: `master` 반영 예정

---

## 1. 작업 목적

DGX Spark 메인 프로젝트 폴더에 반영된 FastAPI + SPA 프론트엔드 통합 작업을 정리하고, 팀원이 GitHub에서 pull한 뒤 개인 workspace에서 실행할 수 있도록 상세 실행 가이드를 추가했다.

---

## 2. 핵심 변경

- `src/api/` FastAPI 백엔드와 `frontend/` SPA 정적 프론트엔드를 메인 repo에 포함했다.
- `/api/chat/stream`이 최신 `src.rag.pipeline.RagPipeline`, GraphDB 컨텍스트, 출처 검증 경고를 사용하도록 연결했다.
- 사용자 관리 저장소에 `viewer` 역할, 계정 상태, 관리자 사용자 CRUD용 함수들을 추가했다.
- `scripts/manage_users.py`에서 `viewer` 역할을 생성할 수 있게 했다.
- `requirements.txt`에 FastAPI 런타임 의존성을 추가했다.
- 팀원 pull 후 실행 절차 문서 `docs/127_DGX_SPARK_TEAM_PULL_AND_SPA_RUN_GUIDE.md`를 추가하고 `docs/TEAM_DEVELOPMENT_GUIDE.md`에서 연결했다.

---

## 3. 검증

원격 DGX Spark 메인 repo에서 다음 검증을 수행했다.

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_api_*.py tests/test_error_responses.py tests/test_request_tracking.py tests/test_rate_limit.py -q
```

결과:

```text
54 passed, 1 warning
```

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

결과:

```text
406 passed, 3 warnings
```

```bash
PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
```

결과:

```text
Q1/Q2 hard query fixture coverage PASS
Detailed Integrity Check: PASS
```

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py --graph data/index/graph/insurance_graph.sqlite --eval eval/graph_qa.jsonl
```

결과:

```text
Evaluation Summary: 5/5 cases passed.
```

```bash
node --check frontend/js/pages/chat.js
```

결과:

```text
syntax OK
```

---

## 4. 남은 주의사항

- `users.json`, `insurance_chat.db`, `data/`, `logs/`, `frontend/node_modules/`는 Git 추적 대상이 아니다.
- 팀원 개인 workspace에서는 공용 repo의 인덱스 산출물을 symlink로 재사용하는 방식을 권장한다.
- LLM 모델 서버는 GPU 메모리 사용량이 크므로 팀원이 임의로 vLLM/SGLang을 전환하거나 종료하지 않아야 한다.
- 이번 반영은 SPA/FastAPI 실행 경로를 활성화하는 단계이며, 기존 Streamlit 경로는 제거하지 않았다.
