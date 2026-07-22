# 256. 보험금 계산 스레드 후속 재계산 구현 보고서

## 목적

보험금 계산 기능으로 생성된 계산 결과를 같은 채팅 스레드 안에서 이어서 질의할 수 있도록, 일반 질의 입력에서 제한된 형태의 후속 재계산 요청을 처리한다.

주요 사용 흐름은 다음과 같다.

1. A 고객 영수증으로 보험금 계산을 수행한다.
2. 같은 스레드에서 "비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요"처럼 후속 조건을 말한다.
3. 시스템은 직전 계산 스냅샷을 기준으로 기존 보험금 계산 파이프라인을 다시 호출한다.
4. 분류가 없거나 항목명/계산 기준이 모호하면 임의 계산하지 않고 되묻는다.

## 핵심 변경

- `src/claim_calculation/thread_recalculation.py`
  - 후속 재계산 의도 감지, 계산 스냅샷 선택, 항목 매칭, 재계산 payload 생성을 담당한다.
  - "보상한다면"처럼 분류가 없는 요청은 `covered_unspecified`로 판단하고 계산 대신 명확화 질문을 반환한다.
  - 같은 이름 조각에 여러 항목이 매칭되면 계산하지 않고 구체 항목명을 되묻는다.
  - 여러 계산 스냅샷이 있는 스레드에서 "최근 계산", "마지막 계산", "직전 계산" 같은 선택 표현이 없으면 계산 기준을 되묻는다.

- `src/api/routes/chat.py`
  - `/chat/stream`에서 일반 RAG 처리 전에 보험금 계산 후속 요청을 먼저 감지한다.
  - 명확화 질문, 조건부 보상 제외 응답, 재계산 응답을 모두 같은 채팅 스레드에 저장한다.
  - 명시적 분류 변경 요청은 기존 `run_claim_calculation` 파이프라인으로 재계산한다.
  - RAG pipeline 초기화 실패 시 일반 보험금 계산 API와 동일하게 구조화 계산 fallback으로 진행한다.
  - 후속 계산 감사 로그에 `claim_follow_up_action`, `claim_follow_up_status`, `claim_follow_up_item_count`, `claim_follow_up_requires_review`를 남긴다.

- `src/api/routes/claim.py`
  - 계산 스냅샷 context에 재계산에 필요한 구조화 필드를 보존한다.
  - 보존 필드: `treatment_date`, `visit_type`, `coverage_topic`, `diagnosis_code`, `diagnosis_name`, `accident_type`, `policy_generation`, 시설/동일질병/합병증 관련 플래그, `treatment_purpose`, `evidence_tags`.
  - 자유 입력 성격의 `situation_note`와 항목 `extra_info`는 저장하지 않는다.

## 처리 범위

이번 구현에서 자동 처리하는 요청은 좁게 제한한다.

- 처리 가능
  - "비타민D 주사를 비급여로 보상한다면 다시 계산해 주세요"
  - "최근 계산 기준으로 도수치료를 보상하지 않는다면 얼마인가요?"
  - "진찰료를 급여 본인부담으로 보상한다면?"
  - "MRI를 3대비급여로 보상한다면?"

- 되묻는 요청
  - "비타민D 주사를 보상한다면?"처럼 보상 분류가 없는 요청
  - "비타민D를 비급여로 보상한다면?"처럼 여러 항목과 매칭되는 요청
  - 여러 계산이 있는 스레드에서 어느 계산 기준인지 밝히지 않은 요청
  - 계산 항목 목록에 없는 항목명을 언급한 요청

## 000번 규칙 점검

- 보험 지식이나 보상률을 새로 하드코딩하지 않았다.
- 금액 계산은 기존 보험금 계산 파이프라인에 위임한다.
- 후속 질문 파서는 사용자 발화의 의도와 항목 매칭만 담당한다.
- 스냅샷에는 재계산에 필요한 구조화 입력만 저장하고, 자유 입력 원문은 저장하지 않는다.
- "보상하지 않는다면"은 문서 기반 신규 규칙이 아니라 사용자가 명시한 가정 조건으로만 처리하며, 결과 스냅샷에 `conditional_follow_up`으로 표시한다.

## 검증

로컬 작업공간:

```bash
python -m py_compile \
  src/api/routes/chat.py \
  src/api/routes/claim.py \
  tests/test_api_chat_stream.py \
  tests/test_claim_thread_snapshot.py \
  src/claim_calculation/thread_recalculation.py
```

결과: 통과.

```bash
python -m pytest tests/test_claim_thread_recalculation.py -q
```

결과: `16 passed`.

로컬 시스템 Python에는 FastAPI와 aiosqlite가 설치되어 있지 않아 API 테스트 수집은 실패했다. 이 테스트는 DGX `.venv`에서 최종 확인한다.

DGX 메인 저장소:

```bash
.venv/bin/python -m py_compile \
  src/api/routes/chat.py \
  src/api/routes/claim.py \
  src/claim_calculation/thread_recalculation.py \
  tests/test_api_chat_stream.py \
  tests/test_claim_thread_recalculation.py \
  tests/test_claim_thread_snapshot.py

.venv/bin/python -m pytest \
  tests/test_claim_thread_recalculation.py \
  tests/test_claim_thread_snapshot.py \
  tests/test_api_chat_stream.py \
  -q
```

결과: `52 passed, 1 warning`.

```bash
.venv/bin/python -m pytest \
  tests/test_api_claim_calculation.py \
  tests/test_claim_calculation_pipeline.py \
  -q
```

결과: `46 passed, 1 warning`.

Ponytail 점검 및 프론트엔드 검증:

```bash
cd frontend && npm run build
npx playwright test tests/e2e/chat.spec.js --project=chromium
```

결과: frontend build 통과, Chromium E2E `8 passed`.

Ponytail 점검 결과, 새 의존성/미래용 config/보험 지식 하드코딩은 발견되지 않았다. 손작성 응답 컨테이너 클래스만 표준 `dataclass`로 축소했다.

## 남은 위험

- 현재 의도 감지는 좁은 한국어 패턴 기반이다. 다양한 자연어 표현을 모두 이해하지 않는다.
- 조건부 "보상하지 않음"은 기존 지급액에서 해당 항목 지급액을 제거하는 단순 가정 처리다. 실제 약관상 재분류 계산이 필요한 경우에는 분류를 명시해 재계산해야 한다.
- 같은 스레드 안에 여러 계산이 있으면 "최근 계산 기준" 같은 기준 표현을 요구한다. 이는 오작동 방지를 위한 의도된 제약이다.
