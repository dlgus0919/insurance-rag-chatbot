# 최종 말풍선 근거 경계 독립 리뷰

- 검토일: 2026-07-21 02:44 KST
- 후보 작업공간: `/srv/shared/workspaces/muldae/insurance-rag-chatbot-final-answer-grounding-20260721`
- 후보 기준: `3353fead2492b4ab9f64fbc45bb45445ebf2f6e7`
- 검토 방식: 후보 diff, 구현 보고서, 관련 계획/triage, 독립 집중 회귀, 무상태 경계 확인
- 운영 경계: 코드·테스트·문서만 읽고 검토했다. 서비스 재시작, GraphDB/온톨로지 재빌드, 후보 승격, 활성 계산 규칙/매니페스트/원문/운영 데이터 변경은 수행하지 않았다.

## 검증 결과

다음 명령을 독립 실행했다.

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 \
  /srv/shared/projects/insurance-rag-chatbot/.venv/bin/python -m pytest \
  -p no:cacheprovider \
  tests/test_search_intent.py tests/test_pipeline.py tests/test_graph_context.py \
  tests/test_api_rag_service_payload.py tests/test_api_chat_stream.py \
  tests/test_clause_detail_rows.py -q
```

결과는 `180 passed, 1 warning in 1.90s`였다. 경고는 공유 환경 `passlib`의 `crypt` deprecation 1건이다. `git diff --check`도 통과했다.

무상태 추가 확인에서 다음은 통과했다.

- 숫자 한도만 있는 보상/지급 질문은 `coverage_insufficient`로 분류되어 수치가 답변에 재사용되지 않았다.
- 승인된 직접 근거 결과를 주입한 경우 `coverage_grounded` / `direct` disposition을 유지했다.
- legacy 문자열을 `coerce_answer_disposition()`으로 통과시킨 뒤 최종 표시를 적용하면 `chunk=`, `source=`, `row_id=`가 제거됐다.
- `build_prompt_graph_context()`에는 missing review summary가 없고, 기존 `build_graph_context()`에는 UI용 review summary가 유지됐다.
- source hover/click payload을 만드는 코드와 계산 규칙·매니페스트·GraphDB/온톨로지·원문·프론트엔드 파일은 후보 diff에 포함되지 않았다.

## 발견 사항

### P0-1 — 세대 비교의 양쪽 직접 근거 검증이 없다

계획의 비교 계약은 양쪽 세대의 직접 근거가 모두 있을 때만 비교하고, 한쪽이 없으면 비교 불가를 안내하는 것이다. 그러나 `src/rag/pipeline.py`의 `_build_clause_detail_evidence_answer()`는 상위 두 행을 그대로 비교형으로 렌더링하고, `resolve_answer_disposition()`은 `requires_cross_document=True`만으로 `policy_comparison` / `direct`를 부여한다. 요청된 세대별 근거의 완결성은 확인하지 않는다.

재현 입력은 `4세대와 5세대 검사X의 연간 보상한도를 비교해줘`였고, 4세대 직접 근거 `123만원` 하나만 제공했다. 실제 결과는 다음과 같았다.

```text
intent=policy_attribute_lookup, cross=True
origin=policy_comparison, grounding_state=direct
4세대 기준 보상한도/횟수/기간 기준은 123만원입니다.
```

이는 비교가 불완전한데도 확정 비교로 기록·표시될 수 있음을 뜻한다. UAT의 세대 비교 실패를 일반화한 회귀가 누락됐다.

### P0-2 — 불충분한 보상/지급 판단 차단이 `general` 경로에만 적용된다

`chat_stream()`은 `general` 경로에서만 `prepare_retrieved_context()`가 반환한 `AnswerDisposition`을 받아 LLM 호출 여부를 결정한다. 자동 라우팅된 `formal` 및 `quickcode` 경로는 `prepare_formal_context()` 또는 `prepare_quickcode_context()`만 실행하고, 초기값인 `llm` disposition을 유지한 채 `_generate_llm_stream()`으로 진행한다.

정적 경로 확인 결과는 다음과 같다.

```text
5세대 MRI 연간 보장되나요? -> general
N39.3 진단코드는 4세대 실손 질병급여에서 보상 가능한가요? -> formal / coverage_judgment
식도조루술 수가 코드와 실손 보상 여부를 알려줘 -> quickcode
```

두 번째와 세 번째 경우에는 승인된 직접 보장·면책 근거가 없더라도 이번 구현의 `coverage_insufficient` fallback이 적용되지 않는다. 따라서 LLM이 숫자·코드 근거를 보상/지급 결론으로 확장할 수 있는 경로가 남아 있으며, 이는 이번 작업의 fail-closed 계약을 충족하지 못한다.

## 확인된 유효 부분

- 일반 RAG 경로의 직접 속성 답변은 내부 provenance를 공개 답변에서 제거하도록 개선됐다.
- 일반 RAG 경로의 불충분 보상 판단은 LLM을 호출하지 않는 회귀 테스트가 있다.
- Graph missing/candidate review 내용을 모델 프롬프트와 UI payload로 분리한 구현은 코드와 독립 확인 모두에서 계획과 일치했다.
- 새 감사 필드는 `answer_origin`, `grounding_state`, `grounded_source_count`로 한정되어 있으며, raw prompt나 숨은 사고 과정 추가 저장은 보이지 않았다.

## 판정

`CHANGES_REQUESTED`

두 P0는 같은 최종 답변 권한 경계가 일부 라우팅 경로와 비교 완결성 검사에서 아직 우회됨을 보여 준다. 후보를 메인에 반영하거나 UAT로 진행하기 전 수정이 필요하다.

## 개발자 Fixback Prompt

> 후보 작업공간 `/srv/shared/workspaces/muldae/insurance-rag-chatbot-final-answer-grounding-20260721`에서 이번 slice만 수정하세요. 독립 리뷰의 P0 두 건을 해결해야 합니다. (1) 세대/문서 비교는 질문에서 요청된 각 기준의 직접·선택된 근거가 모두 있을 때만 `policy_comparison/direct`로 렌더링하세요. 하나라도 없으면 비교 불가 disposition(grounding_state=`insufficient`)으로 종료하고, 단일 기준 수치를 비교 결론처럼 표시하거나 감사에 direct comparison으로 기록하지 마세요. 이 검증은 `4th`/`5th` literal이나 MRI 값에 의존하지 말고 기존 요청 기준/근거 provenance를 일반적으로 사용하세요. (2) `general`뿐 아니라 자동 `formal`, `quickcode`, 그리고 명시 모드가 보상·지급 판단을 요청하는 모든 경로에서 같은 승인 직접근거/`coverage_insufficient` 경계를 적용하세요. 직접 승인 근거가 없으면 LLM을 호출하지 말고, 직접 근거가 있으면 기존 조건부 답변과 public finalization을 유지하세요. 일반 설명·순수 코드/속성 조회는 불필요하게 막지 마세요. 각 경로의 LLM 미호출, 승인 직접근거 조건부 경로, 비교 양쪽/한쪽 누락, audit origin/state/count, source payload 및 final public normalization을 회귀 테스트로 추가하세요. 활성 계산 규칙·매니페스트·GraphDB/온톨로지·원문·운영 데이터·서비스 설정은 변경하지 말고, stage/commit/push/restart/rebuild/reindex도 하지 마세요. 수정 후 focused 및 full test 결과와 구현 보고서를 갱신하세요.
