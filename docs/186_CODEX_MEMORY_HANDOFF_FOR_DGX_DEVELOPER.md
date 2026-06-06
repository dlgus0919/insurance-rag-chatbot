# 186. Codex Memory Handoff for DGX Developer

## 목적

이 문서는 로컬 Codex memory에 남긴 v1.0.2 인수 메모리를 DGX 작업자가 직접 확인할 수 있도록 옮긴 전달용 문서입니다.

## 중요한 정정

- 이전 handoff memory note는 맥북 로컬 Codex memory 경로에 저장되었습니다.
  - 원래 위치: `/Users/june_kim/.codex/memories/extensions/ad_hoc/notes/`
  - 따라서 DGX의 `/home/ai-hang` 또는 프로젝트 폴더에서 해당 memory note가 검색되지 않는 것은 정상입니다.
- 초기 handoff note에는 이후 변경 전 정보가 남아 있습니다.
- 최종 기준은 `2026-06-06-insurance-rag-v102-token-cap-update.md`의 내용입니다.

## 최종 v1.0.2 기준

- DGX main repo: `/srv/shared/projects/insurance-rag-chatbot`
- GitHub repo: `koreaben777/insurance-rag-chatbot`
- 최종 커밋: `c18febf0897fc685516bf84c9126009423ce4103`
- `v1.0.2^{}`는 위 커밋을 가리켜야 합니다.
- `master`와 `origin/master`는 인수 보존 문서 커밋이 추가되면 `c18febf`보다 앞선 커밋을 가리킬 수 있습니다. 이 경우에도 릴리스 기준은 `v1.0.2^{}`의 대상 커밋인 `c18febf`입니다.
- 일반 LLM 출력 상한: `OPENAI_MAX_TOKENS=4096`
- Qwen Thinking reasoning 상한: `SGLANG_REASONING_MAX_TOKENS=10240`

## DGX 개발자가 우선 확인할 문서

- `docs/184_LEGACY_TO_OFFICIAL_VERSION_HANDOFF.md`
- `docs/185_V1_0_2_OFFICIAL_HANDOFF_CHECK_REPORT.md`
- 이 문서: `docs/186_CODEX_MEMORY_HANDOFF_FOR_DGX_DEVELOPER.md`

## 권장 확인 명령

```bash
cd /srv/shared/projects/insurance-rag-chatbot
git status --short
git log -1 --oneline --decorate
git rev-parse master origin/master 'v1.0.2^{}'
```

## 후속 작업 메모

- `docs/185_V1_0_2_OFFICIAL_HANDOFF_CHECK_REPORT.md`가 untracked라면 내용을 검토한 뒤 보존 여부를 결정해야 합니다.
- 185번 보고서가 인수 점검 결과로 유효하다면 커밋/푸시 대상입니다.
- Qwen Thinking 관련 후속 작업 시 내부 추론 문장이 UI/final answer에 노출되지 않는 방어 로직을 유지해야 합니다.
- 추론 모드가 final 없이 reasoning-only로 끝나는 경우 final-only retry 및 warning/audit 기록이 정상 작동해야 합니다.
