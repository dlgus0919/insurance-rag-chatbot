# 253. 보험금 계산 스레드 스냅샷 구현 보고서

## 목적

보험금 계산과 일반 질의를 하나의 채팅 스레드에서 이어갈 수 있도록, 계산 결과를 채팅 히스토리에 구조화 스냅샷으로 저장하고 다시 불러올 때 계산 카드 형태로 복원한다.

## 핵심 변경

- 보험금 계산 API가 `save_to_history=true`일 때 사용자 입력 요약과 assistant 응답을 `ChatMessage`로 저장한다.
- assistant 메시지 `sources`에는 `assistant_meta.claim_snapshot`을 저장해 계산 결과, 항목별 산정 결과, 추가 확인 필요 항목을 복원할 수 있게 했다.
- 스냅샷 저장 범위는 허용 목록 기반으로 제한했다. 자유기재 원문, 긴 근거 본문, 원문 청크 텍스트는 저장하지 않는다.
- 일반 질의 히스토리 컨텍스트에 최근 보험금 계산 스냅샷을 요약 주입한다. 이를 통해 “이 항목을 보상한다면/하지 않는다면” 같은 후속 질의가 이전 계산 맥락을 참고할 수 있다.
- 프론트엔드는 저장된 스냅샷이 있는 assistant 메시지를 계산 결과 카드로 렌더링한다.
- 후보 선택 후 재계산되는 보험금 계산도 같은 스레드 히스토리에 저장되도록 했다.
- 재계산 의도 탐지 MVP를 추가했다. 실제 자동 재계산 실행은 후속 단계에서 별도 적용한다.

## 안전장치

- 스냅샷은 `input_name`, 금액, 카테고리, 계산 상태, 검토 사유 등 재계산 맥락에 필요한 필드만 저장한다.
- `extra_info`, `situation_note`, `applied_basis.content`처럼 자유기재 또는 장문 근거가 될 수 있는 필드는 저장 대상에서 제외했다.
- 일반 질의에 주입되는 계산 컨텍스트는 길이 제한과 prompt/role marker 제거를 적용한다.
- 최근 계산 스냅샷은 최대 3개만 요약하고, 길이 초과 시 최신 계산을 우선 보존한다.

## 검증 결과

DGX 메인 저장소 `/srv/shared/projects/insurance-rag-chatbot`에 패치를 적용한 뒤 다음 검증을 수행했다.

```bash
.venv/bin/python -m pytest tests/test_claim_thread_snapshot.py tests/test_claim_thread_recalculation.py -q
# 19 passed, 1 warning

npm --prefix frontend run build
# passed

.venv/bin/python -m pytest tests/test_api_claim_calculation.py tests/test_api_chat_stream.py -q
# 29 passed, 1 warning

npm run test:e2e -- --project=chromium tests/e2e/chat.spec.js -g "보험금 계산"
# 2 passed
```

Firefox/WebKit 전체 E2E는 DGX에 해당 Playwright 브라우저 바이너리가 없어 실패했다. 기능 회귀는 설치된 Chromium 프로젝트로 통과 확인했다.

## 남은 작업

- P2 후속 단계에서 재계산 의도 탐지 결과를 실제 보험금 계산 재실행 UX와 연결해야 한다.
- 추가 확인 항목이 보상/비보상/카테고리 변경으로 확정됐을 때, 이전 계산 스냅샷을 기준으로 새 계산 요청을 생성하는 사용자 확인 UI가 필요하다.
- 여러 계산 스냅샷이 같은 스레드에 있을 때 어떤 계산을 기준으로 재계산할지 명시적으로 선택하는 UX는 후속 보완 대상이다.
