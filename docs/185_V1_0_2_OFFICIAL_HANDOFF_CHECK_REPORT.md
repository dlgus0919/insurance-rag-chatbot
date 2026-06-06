# 185. v1.0.2 정식 개발 인수 점검 보고서

작성일: 2026-06-06

## 기준

- DGX 메인 저장소: `/srv/shared/projects/insurance-rag-chatbot`
- GitHub remote: `https://github.com/koreaben777/insurance-rag-chatbot.git`
- 브랜치: `master`
- v1.0.2 릴리스 대상 커밋: `c18febf0897fc685516bf84c9126009423ce4103`
- 태그: `v1.0.2`

`git fetch origin master --tags` 후 다음 상태를 확인했다.

```text
HEAD        c18febf chore(llm): raise default output token cap
origin/master c18febf
v1.0.2^{}   c18febf
```

`v1.0.2`는 annotated tag이므로 tag object 해시는 별도이나, dereference한 릴리스 커밋은 `c18febf`로 일치한다.

2026-06-06 보존 작업 이후 `docs/185`와 설정 예시 정렬 커밋이 `master`에 추가되었다. 따라서 현재 `master`/`origin/master`는 보존 문서 커밋을 가리킬 수 있으며, 이 경우에도 `v1.0.2^{}`가 `c18febf`를 유지하면 릴리스 태그 정합성은 보존된다.

## 인계 문서 확인

확인한 repo 문서:

- `docs/183_QWEN_REASONING_MODE_FINAL_RETRY_FIX_REPORT.md`
- `docs/184_LEGACY_TO_OFFICIAL_VERSION_HANDOFF.md`
- `docs/179_RELEASE_1_0_VERIFICATION_REPORT.md`
- `docs/154_PROJECT_ARCHITECTURE_CURRENT_STATUS_REPORT.md`
- `docs/167_GRAPHDB_ONTOLOGY_STAGE2_IMPL_REPORT.md`

지정된 Codex memory note는 맥북 로컬 Codex memory(`/Users/june_kim/.codex/memories/...`)에 저장된 handoff note이므로, DGX 저장소 및 `/home/ai-hang`에서 발견되지 않는 것이 정상이다. DGX 인수 기준은 위 repo 문서와 현재 `v1.0.2` 커밋/설정값으로 고정한다.

## 현재 기능 상태

v1.0.2 기준 주요 운영 설정은 다음과 일치한다.

- `OPENAI_MAX_TOKENS=4096`
- `SGLANG_REASONING_MAX_TOKENS=10240`
- Qwen Thinking `reasoning_mode=off` 기본값 유지
- Qwen Thinking `reasoning_mode=on` reasoning-only 종료 시 final-only 1회 retry
- audit detail에 `finish_reason`, `final_retry_finish_reason` 기록
- 프론트 기본값:
  - Top-K `10`
  - 온도 `0.2`
  - OCR 인덱스 `v2_only`

Qwen Thinking 내부 추론은 UI에 표시하지 않는 정책을 유지한다.

## 검증 결과

작업트리:

```text
git status --short --branch
## master...origin/master
```

관련 테스트:

```bash
timeout 240 .venv/bin/pytest tests/test_openai_compatible_client.py tests/test_api_chat_stream.py tests/test_qwen_thinking_template.py -q
```

결과:

```text
32 passed, 1 warning
```

전체 테스트:

```bash
timeout 1200 .venv/bin/pytest tests/ -q
```

결과:

```text
572 passed, 3 warnings
```

경고는 passlib `crypt` deprecation 및 Pillow `getdata` deprecation으로, v1.0.2 기능 결함은 아니다.

운영 wrapper 문법:

```bash
bash -n /srv/ai-ops/bin/insurance-rag-up
bash -n /srv/ai-ops/bin/insurance-rag-status
bash -n /srv/ai-ops/bin/insurance-rag-desktop-launcher
bash -n ops/bin/prepare-llm-model-assets
bash -n ops/bin/switch-sglang-model
```

결과: 통과.

## 앱 기동 확인

인계 시점과 동일하게 최초 상태에서는 `insurance-rag-api`, `sglang-local` tmux 세션이 없었고, Ollama만 `127.0.0.1:11434`에서 응답했다.

프론트 사용 가능 여부 확인을 위해 안정적인 Ollama 모델로 앱을 기동했다.

```bash
/srv/ai-ops/bin/insurance-rag-up --replace --provider ollama --model exaone3.5:7.8b
```

결과:

```text
app ready: http://127.0.0.1:18080
```

확인:

- `/api/health`: `{"status":"ok"}`
- `/api/system/models`: 기본 local model `ollama:exaone3.5:7.8b`
- `/login`: HTTP 200, `text/html`
- `/chat`: HTTP 200, `text/html`
- `/srv/ai-ops/bin/insurance-rag-status`:
  - `app_tmux`: ok
  - `app_port`: ok
  - `api_health`: ok
  - `api_models`: ok
  - `ollama`: ok
  - `sglang`, `vllm`: warn
  - BM25/Chroma/GraphDB/standard DB/users.json: ok

`sglang`, `vllm` warn은 해당 서버를 이번 점검에서 기동하지 않았기 때문에 예상된 상태다.

## 운영 인수 판단

`v1.0.2` 릴리스 태그는 릴리스 커밋 `c18febf`에 정합하다. `master`는 이후 인수 보존 문서 커밋을 포함할 수 있다. 테스트, wrapper, 앱 기동, SPA 주요 라우트, system models 응답이 정상이다.

후속 개발은 정식 `1.0.x` 안정화 범위로 제한하고, 다음 원칙을 유지한다.

- Qwen Thinking 내부 추론은 사용자 화면에 노출하지 않는다.
- `finish_reason`/`final_retry_finish_reason` audit은 Qwen Thinking 디버깅 근거로 유지한다.
- Dynamic RRF는 기본 observe/off 정책을 유지하고, 운영 적용 전 평가셋과 latency 지표를 먼저 확보한다.
- 대규모 리팩터링보다 운영 결함 수정, smoke 자동화, 진단 가시성 개선을 우선한다.
