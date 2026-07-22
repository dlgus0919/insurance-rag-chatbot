# UAT MRI 세대별 한도 회귀 배포 재개

## 상태

- 보호 메인 HEAD: `2ea0d81666bd121b9b52d7d40c2deca4f1122d87`
- 적용된 승인 커밋: `f844c71`, `2ea0d81`
- 기존 API PID: `3432126` (승인 커밋 적용 전 기동)
- Review Team 판정: `PASS` — 운영과 동일한 safe-baseline 환경에서 API-only 재기동 허용
- push 금지

## 실패 분리 근거

보호 메인 셸에서 safe-baseline 환경변수를 지정하지 않으면 ignored
`data/ontology/concepts.active.json`이 provenance 없이 선택되어 registry가
`stale / MANIFEST_READ_FAILED / 0 concepts`로 닫힌다. 실제 API에는 다음 값이
설정되어 있으며 해당 runtime ontology는 active manifest, provenance, base, lock을
모두 포함한다.

```text
INSURANCE_SAFE_BASELINE_RUNTIME_ROOT=/srv/ai-ops/runtime/insurance-rag-chatbot/safe-baseline-v1.2.0-r2
```

Review Team이 같은 환경으로 재검증한 결과:

- focused/관련: `206 passed, 1 failed`
- 단일 실패는 safe-baseline 우선순위를 해제하지 않은 기존 테스트 격리 문제이며,
  해당 환경변수를 해제하면 `1 passed`
- 전체: `1149 passed, 5 failed`
- 나머지 4건은 `/tmp` rebuild lock 및 보호 checkout Qwen template 권한 문제
- MRI 패치, 운영 ontology, Graph, 계산 규칙 회귀는 재현되지 않음

## Developer 재개 지시

1. 보호 메인이 정확히 `2ea0d81666bd121b9b52d7d40c2deca4f1122d87`이고
   tracked/staged clean인지 확인한다.
2. 계산 룰·rule links·processing policy 및 r2 Graph SHA가 기존 기준과 같은지 재확인한다.
3. 현재 API PID의 r2 safe-baseline과 SGLang 모델 환경을 보존한 채 API만 표준 절차로
   재기동한다. LLM을 재기동하거나 전환하지 않는다.
4. 새 API PID가 `2ea0d81` 코드를 로드했고 다음 환경을 유지하는지 확인한다.
   - `INSURANCE_SAFE_BASELINE_RUNTIME_ROOT=.../safe-baseline-v1.2.0-r2`
   - `INSURANCE_RAG_PROVIDER=sglang`
   - `INSURANCE_RAG_MODEL=qwen3-next-80b-a3b-instruct-fp8`
5. health, 모델 표시, ontology `valid/55`, Graph 경로·SHA, 반복 Graph 조회 후
   WAL/SHM 0건을 확인한다.
6. MRI 세대별 한도 API smoke와 내부 `_review` 표식 미노출 smoke를 수행한다.
7. 출처 링크, 보험금 계산, 수술종수, 사용자 DB·계정·대화·로그는 변경하지 않는다.
8. push하지 않는다.

## 중단 조건

- 보호 메인 HEAD 또는 tracked/staged 상태 불일치
- frozen 계산 해시, r2 Graph SHA 또는 모델 변경
- API health 실패, ontology 무결성 실패, Graph sidecar 생성
- 예상 밖 데이터 쓰기 또는 LLM 재기동 필요

완료 표식:

`DEVELOPER_UAT_MRI_GENERATION_REGRESSION_DEPLOYMENT_COMPLETE_NO_PUSH`
