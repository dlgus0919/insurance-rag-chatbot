# Gemma4/vLLM 스트리밍 응답 누락 수정 보고서

## 1. 문제 현상
Streamlit 앱에서 `vllm:gemma-4-26b-a4b-nvfp4` 모델을 선택한 뒤 일반 질의를 실행했을 때, LLM 답변 본문(생성 텍스트)이 노출되지 않고 출처(Citations)만 하단에 표시되는 현상이 발생했습니다.
- 검색 시간 및 생성 시간은 정상적으로 기록됨.
- 출처 정보도 정상 노출됨.
- 오직 답변 본문만 비어 있는 상태로 노출됨.
- vLLM 서버 자체는 정상이며 `/v1/chat/completions` API가 `200 OK`를 정상적으로 반환함.

## 2. 발생 원인
- `src/llm/openai_compatible_client.py`의 `generate_stream()` 로직이 GPT-OSS Harmony 모델의 스트림 형태만 지원하도록 설계되어 있었습니다.
- Harmony 모델(`gpt-oss-20b` 등)은 `<|channel|>final<|message|>` 마커를 만나기 전까지의 토큰들을 출력 버퍼에만 쌓아두고 클라이언트에 즉시 내보내지(yield) 않습니다.
- 반면, vLLM을 통해 구동되는 Gemma4 모델(`gemma-4-26b-a4b-nvfp4`)은 Harmony 마커를 사용하지 않는 표준 OpenAI 호환 스트림 형태(`delta.content`에 텍스트가 바로 담겨 오는 방식)를 사용합니다.
- 이에 따라 Gemma4 모델이 토큰을 보낼 때 마커를 만나지 못하므로 클라이언트는 토큰들을 버퍼에만 쌓아두고 사용자 화면에 한 단어도 내보내지 못해 본문이 0글자가 되었습니다.
- 본문이 0글자임에도 Streamlit UI의 `append_retrieved_source_citations()`는 검색된 chunks 리스트를 토대로 출처를 붙였기 때문에 본문 없이 출처만 남는 현상이 유발되었습니다.

## 3. 수정 파일
- **[MODIFY]** [openai_compatible_client.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/llm/openai_compatible_client.py)
  - `_uses_harmony_stream(model, provider)` 헬퍼 함수를 추가하여 모델명 및 프로바이더를 기준으로 Harmony 모델 스트림 여부를 판별합니다.
  - `generate()` 및 `generate_stream()` 내부에서 Harmony 모델이 아닐 경우(Gemma4 등 일반 OpenAI-compatible 모델), 마커 검사 없이 토큰(`delta.content`)을 정제하여 즉시 클라이언트로 yield하도록 수정했습니다.
- **[MODIFY]** [streamlit_app.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/src/ui/streamlit_app.py)
  - `_stream_answer()` 함수에서 LLM의 응답 본문(`raw_answer`)이 완전히 비어 있을 경우를 대비한 방어 로직을 구현했습니다.
  - 빈 본문일 때 출처가 단독으로 노출되는 것을 방지하기 위해 출처 가공 함수(`append_retrieved_source_citations()`, `append_evidence_validation_warning()`) 호출을 건너뛰고, UI placeholder에 `st.warning`으로 경고 메시지를 노출한 뒤 즉시 조기 반환(early return) 처리되도록 보완했습니다.
- **[MODIFY]** [test_openai_compatible_client.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/tests/test_openai_compatible_client.py)
  - Gemma4/vLLM 스트림의 정상 즉시 yield 동작을 검증하기 위한 `test_generate_stream_gemma4_yields_immediately` 테스트를 추가했습니다.
  - GPT-OSS Harmony 모델 스트림에 대해서는 기존 마커 게이팅이 정상 동작하는지 검증하기 위한 `test_generate_stream_harmony_gates_output` 테스트를 추가했습니다.
  - `_extract_final_content` 유틸리티 함수가 마커가 없는 일반 텍스트에 대해서도 정상 보존하는지 검증하는 `test_extract_final_content_preserves_plain_text` 테스트를 추가했습니다.
- **[MODIFY]** [test_streamlit_app.py](file:///Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇/tests/test_streamlit_app.py)
  - LLM이 빈 토큰을 반환할 때, 출처를 단독으로 붙이지 않고 명확한 오류 경고 메시지를 보여주는지 모킹을 통해 확인하는 `test_stream_answer_empty_defense` 테스트 케이스를 새로 구축했습니다.

## 4. Harmony 모델과 일반 OpenAI-compatible 모델의 스트림 구조 차이
| 비교 항목 | GPT-OSS Harmony 모델 (e.g. `gpt-oss-20b`) | 일반 OpenAI 호환 모델 (e.g. `gemma-4-26b-a4b-nvfp4`) |
| :--- | :--- | :--- |
| **SSE 응답 토큰 형식** | `<|channel|>analysis<|message|>...` 형태로 시작하여 최종 단계에 `<|channel|>final<|message|>`를 포함하여 전송 | 일반적인 순수 텍스트 토큰이 `delta.content` 필드에 직접 전달됨 |
| **스트림 출력 방식** | 최종 답변 마커인 `final` 메시지가 감지될 때까지 클라이언트 단에서 토큰을 내보내지 않고 버퍼링함 | 들어오는 즉시 불필요한 마커/토큰 필터링 후 클라이언트에 순차적으로 출력(yield) |

## 5. 테스트 결과
로컬 및 원격 DGX GPU 서버 환경에서 전체 pytest를 실행하여 308개 테스트가 모두 성공적으로 작동하는 것을 입증했습니다.
- **검증 명령 (로컬 & 원격):**
  ```bash
  pytest tests/test_openai_compatible_client.py tests/test_streamlit_app.py -v
  ```
- **결과:**
  - `test_generate_stream_gemma4_yields_immediately` (PASS)
  - `test_generate_stream_harmony_gates_output` (PASS)
  - `test_extract_final_content_preserves_plain_text` (PASS)
  - `test_stream_answer_empty_defense` (PASS)
  - 전체 RAG 테스트셋 308 passed 완료.

## 6. 수동 검증 여부
원격 서버 `ai-hang@100.88.5.57` 로컬에서 Gemma4 vLLM SSE API 스트리밍 수동 curl 질의를 아래와 같이 수행하여 SSE 응답 내 `content` 토큰이 올바르게 전달되는 것을 확인했습니다.
```bash
curl -sN http://127.0.0.1:30001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer EMPTY" \
  -d '{
    "model":"gemma-4-26b-a4b-nvfp4",
    "messages":[{"role":"user","content":"로봇 수술의 코드를 알려주세요."}],
    "max_tokens":128,
    "temperature":0,
    "stream":true
  }' | head -40
```
**출력 확인:**
`data: {"choices":[{"delta":{"content":"'"}, ...}]}`
`data: {"choices":[{"delta":{"content":"로"}, ...}]}`
`data: {"choices":[{"delta":{"content":"봇"}, ...}]}`
... (정상 스트리밍 응답 텍스트가 JSON 조각들로 확인됨)

## 7. 남은 위험 및 향후 모니터링 사항
- **vLLM 및 기타 로컬 모델의 Cold Start**: Gemma4 등의 대형 로컬 모델을 처음 시작하거나 재전환할 때 OOM 경합 상황 또는 콜드 스타트 지연이 발생할 수 있습니다.
- **인증 헤더 매핑**: vLLM 포트 `30001`에 질의 시 헤더 누락으로 인한 401 Unauthorized가 발생하지 않도록 Bearer EMPTY 헤더 바인딩의 안정적인 관리가 계속 요구됩니다.
