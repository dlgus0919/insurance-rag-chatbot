# 181. Qwen Thinking Stability and Toggle Plan

## 목적

`qwen3-next-80b-a3b-thinking-fp8`를 1.0.x 앱에서 실제 사용자용 모델로 안정화하기 위한 추가 패치 계획을 정의한다.

현재 관찰된 현상은 두 가지다.

1. Qwen Thinking이 영어 내부 추론 문장을 사용자 응답으로 길게 노출할 수 있다.
2. 누출 방어 후처리를 강화하면 reasoning-only 응답은 막히지만, 실제 답변 대신 fallback 문구가 자주 나올 수 있다.

따라서 목표는 단순 문자열 제거가 아니라 **추론 모드 on/off 제어, 템플릿 정합성, stream gating, API/프론트엔드 토글, live audit 검증**을 함께 완성하는 것이다.

## 현재 원인 분석

### 1. SGLang 요청 payload만으로는 thinking off가 보장되지 않음

현재 client는 Qwen Thinking 요청에 다음 payload를 보낼 수 있다.

```json
{
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

그러나 DGX의 현재 모델 템플릿은 `enable_thinking` 값을 읽지 않는다.

현재 `/srv/ai-ops/llm/models/qwen3-next-80b-a3b-thinking-fp8/chat_template.jinja`의 generation prompt는 사실상 다음과 같다.

```jinja
{%- if add_generation_prompt %}
    {{- '<|im_start|>assistant\n<think>\n' }}
{%- endif %}
```

즉, `chat_template_kwargs={"enable_thinking": false}`를 보내도 template이 항상 `<think>`를 붙인다.

### 2. 후처리만으로는 사용자 경험이 완성되지 않음

후처리는 내부 추론 누출을 막는 마지막 안전망이어야 한다.  
하지만 모델이 `</think>` 없이 reasoning-only로 종료하면 후처리는 답변을 복원할 수 없다.

이 경우 현재 가능한 안전 동작은 fallback 문구 반환뿐이다.

```text
모델이 내부 추론만 반환하고 최종 답변을 제공하지 않았습니다. 검색 근거를 다시 확인하거나 다른 검증된 모델로 재시도해 주세요.
```

이는 보안상 안전하지만, 앱 사용성 기준으로는 실패에 가깝다.

### 3. 프론트엔드에는 Qwen reasoning mode 제어가 없음

현재 `ChatRequest`에는 `model`, `provider`, `top_k`, `temperature`, `index_mode` 등이 있지만, reasoning 기능 on/off 필드는 없다.

프론트엔드도 활성 모델 선택은 지원하지만, Qwen Thinking의 추론 모드를 켜고 끄는 토글은 없다.

## 개발 목표

1. Qwen Thinking을 기본적으로 **thinking off**로 안정 운용한다.
2. 사용자가 명시적으로 선택한 경우에만 **thinking on**으로 요청한다.
3. thinking on 상태에서도 내부 chain-of-thought는 화면에 노출하지 않는다.
4. thinking on/off 상태를 API 요청, audit log, 관리자 진단에서 추적 가능하게 한다.
5. thinking off에서 정상적인 한국어 최종 답변이 나오는지 live smoke로 증명한다.

## 구현 계획

### Phase 1. Qwen template를 switchable template로 교체

repo에 Qwen Thinking 전용 switchable template를 추가한다.

권장 경로:

```text
ops/templates/qwen3_thinking_switchable.jinja
```

핵심 동작:

```jinja
{%- set enable_thinking = enable_thinking | default(false) %}
...
{%- if add_generation_prompt %}
    {%- if enable_thinking %}
        {{- '<|im_start|>assistant\n<think>\n' }}
    {%- else %}
        {{- '<|im_start|>assistant\n' }}
    {%- endif %}
{%- endif %}
```

`ops/bin/prepare-llm-model-assets`는 이 template를 다음 위치에 설치한다.

```text
/srv/ai-ops/llm/models/qwen3-next-80b-a3b-thinking-fp8/chat_template.jinja
```

`ops/bin/switch-sglang-model`은 Qwen Thinking 모델의 template가 `enable_thinking`을 포함하는지 검사하고, 없으면 `prepare-llm-model-assets` 실행을 안내한다.

### Phase 2. API request schema 확장

`src/api/schemas/chat.py`에 reasoning option을 추가한다.

권장 필드:

```python
reasoning_mode: Literal["off", "on"] = "off"
```

기본값은 반드시 `"off"`다.

`src/api/routes/chat.py`는 `chat_request.reasoning_mode`를 `pipeline.llm.generate_stream()`에 전달한다.

audit detail에는 다음 값을 추가한다.

```json
{
  "reasoning_mode": "off",
  "reasoning_supported": true,
  "reasoning_filtered": true
}
```

### Phase 3. LLM client를 per-request reasoning 제어 구조로 변경

현재 `OpenAICompatibleClient._payload()`는 instance model/provider만 보고 thinking을 비활성화한다.

변경 방향:

```python
def generate_stream(..., reasoning_mode: str = "off") -> Iterator[str]:
    ...

def _payload(..., reasoning_mode: str = "off") -> dict:
    ...
```

Qwen Thinking에서:

- `reasoning_mode="off"`:
  - `chat_template_kwargs={"enable_thinking": False}`
  - `reasoning_effort` 미전송
  - stream parser는 일반 답변을 즉시 방출하되 `<think>`가 나오면 gating
- `reasoning_mode="on"`:
  - `chat_template_kwargs={"enable_thinking": True}`
  - 내부 reasoning token은 계속 gating
  - `</think>` 이후 final answer만 방출
  - `</think>` 없이 종료하면 fallback + warning

중요:

- thinking on은 내부 추론을 **사용**하는 옵션이지, 내부 추론을 **화면에 표시**하는 옵션이 아니다.
- 화면에 chain-of-thought를 노출하지 않는다.

### Phase 4. fallback을 warning으로 구분

현재 fallback 문구가 일반 답변처럼 저장될 수 있다.

권장 개선:

- client에 `last_safety_warning` 또는 structured metadata를 둔다.
- `chat.py`에서 fallback 발생 시 SSE `warning` event를 추가한다.
- final answer에는 fallback 문구를 내보내되, UI에서 `처리 경고`로 표시한다.

권장 warning code:

```text
THINKING_ONLY_OUTPUT
THINKING_OUTPUT_FILTERED
```

### Phase 5. 프론트엔드 reasoning toggle 추가

위치:

- `frontend/html/chat.html`
- `frontend/js/pages/chat.js`
- 필요 시 `frontend/css/chat.css`

표시 조건:

- 선택 모델 ID가 `qwen3-next-80b-a3b-thinking-fp8` 또는 reasoning 지원 모델일 때만 표시

권장 UI:

```text
[ ] 추론 모드
```

툴팁/보조 문구:

```text
추론 모드는 답변 품질 검토용입니다. 내부 추론 문장은 화면에 표시하지 않습니다.
```

요청 payload:

```json
{
  "reasoning_mode": "off"
}
```

또는 toggle on:

```json
{
  "reasoning_mode": "on"
}
```

상태 저장:

```text
localStorage: qwen_reasoning_mode
```

### Phase 6. 테스트 계획

단위 테스트:

- Qwen Thinking `reasoning_mode=off` payload가 `enable_thinking=false`를 보냄
- Qwen Thinking `reasoning_mode=on` payload가 `enable_thinking=true`를 보냄
- `</think>` 이후 final answer만 방출
- `</think>` 없는 영어 reasoning-only는 fallback
- 영어 reasoning 중 한글 인용이 있어도 final answer로 오판하지 않음
- 일반 non-thinking 모델 whitespace streaming 회귀 없음
- GPT-OSS Harmony gating 회귀 없음

API 테스트:

- `ChatRequest.reasoning_mode` 기본값 off
- `/api/chat/stream`이 reasoning_mode를 client까지 전달
- audit log에 reasoning_mode 기록
- fallback 발생 시 warning event 기록

프론트엔드 테스트:

- Qwen Thinking 선택 시 toggle 표시
- 다른 모델 선택 시 toggle 숨김
- toggle on/off가 `/chat/stream` payload에 반영
- token/final 렌더링에서 `<think>`, `</think>`, 영어 reasoning 문장 미노출

Live smoke:

```bash
/srv/ai-ops/bin/insurance-rag-up --replace --provider sglang --model qwen3-next-80b-a3b-thinking-fp8
curl -s http://127.0.0.1:30000/v1/models
curl -s http://127.0.0.1:18080/api/system/models
```

앱 질의:

1. reasoning off
   - 기대: 한국어 최종 답변 정상 생성
   - 금지: fallback 반복, 영어 reasoning 노출
2. reasoning on
   - 기대: 내부 reasoning은 숨김, 최종 답변만 표시
   - 허용: 모델이 final answer를 내지 못하면 warning + fallback

audit 확인:

```sql
select event_type, detail, created_at
from audit_logs
where event_type = 'CHAT_QUERY'
order by id desc
limit 5;
```

확인 필드:

- `detail.model`
- `detail.reasoning_mode`
- `detail.source_count`
- `detail.elapsed_ms`
- warning code

## 릴리스 판단 기준

Qwen Thinking을 1.0.x 사용 가능 모델로 인정하려면 다음을 모두 만족해야 한다.

1. thinking off에서 실제 앱 질의가 fallback 없이 한국어 최종 답변을 생성한다.
2. thinking on에서 내부 reasoning이 화면과 final answer에 노출되지 않는다.
3. thinking on에서 final answer가 없을 경우 fallback + warning으로 처리된다.
4. `/v1/models`, `/api/system/models`, `audit_logs`가 실제 Qwen Thinking 경로를 증명한다.
5. 전체 회귀 테스트가 통과한다.

위 조건을 만족하기 전까지는 Qwen Thinking을 기본 모델로 두지 않는다.

## 운영 권고

현재 단계에서는 다음이 안전하다.

- 기본 운영 모델: `gpt-oss-20b` 또는 `qwen3-next-80b-a3b-instruct-fp8`
- Qwen Thinking: `검증대상` 또는 관리자 전용 실험 모델
- `v1.0.0` 태그는 안정 모델 기준으로 유지하고, Qwen Thinking 안정화는 `v1.0.1` 또는 `v1.1.0` 후보로 관리
