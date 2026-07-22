# 5세대 약관 출처 권위 및 재인제스트 안전성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 5세대 표준약관이 실제 등록·검색된 답변에서 자사약관 부재를 정적으로 단정하지 않고 선택된 근거의 권위를 정확히 표시하며, 다음 전체 인제스트에서도 4·5세대 메타데이터를 보존한다.

**Architecture:** 최종 직접 근거 청크를 `own`/`standard`/`other`로 분류하여 권위 문구를 결정하고 온톨로지의 정적 부재 문구 의존을 제거한다. `PdfSource`의 세대 필드를 복구하여 신규 청크 메타데이터 계약을 보존하되, 현재 운영 인덱스와 GraphDB는 재구축하지 않는다.

**Tech Stack:** Python dataclasses, deterministic RAG guard, ontology JSON, PDF chunk metadata, pytest.

## Global Constraints

- 격리된 최신 `origin/master` 기반 작업공간에서만 구현한다. 보호된 DGX 메인 체크아웃에서 직접 수정하지 않는다.
- 현재 운영 BM25, Chroma, GraphDB, 대화 DB를 재구축·재작성하지 않는다.
- 과거 저장 메시지를 수정하거나 재생성하지 않는다.
- 표준약관을 자사 상품약관으로 표시하지 않는다.
- 실제 인벤토리 조회 없이 자사약관 존재/부재를 단정하지 않는다.
- 활성 온톨로지 매니페스트를 후보 승인 절차 없이 직접 덮어쓰지 않는다.
- 신규 보험금 룰이나 온톨로지 후보를 승인하지 않는다.
- 변경 전 회귀 테스트를 실패시키고, 최소 구현 후 통과시키는 순서로 진행한다.

---

## Task 1: 기준선과 생성자 호환성 확인

**Files:**

- Inspect: `src/config.py`
- Inspect: `src/parser/chunker.py`
- Inspect: `src/rag/source_grounded_answers.py`
- Inspect: `data/ontology/concepts.json`
- Inspect: `data/ontology/concepts.active.json` when present

- [ ] 격리 작업공간의 기준 커밋과 오염 여부를 기록한다.

Run:

```bash
git rev-parse HEAD
git status --short
```

Expected: 최신 `origin/master` 기준이며 작업 시작 전 의도하지 않은 변경이 없다.

- [ ] `PdfSource` 생성 위치와 위치 인자 사용 여부를 확인한다.

Run:

```bash
rg -n "PdfSource\(" src scripts tests
```

Expected: 새 필드는 기본값을 가진 후방 필드로 추가할 수 있고 기존 호출은 키워드 인자 중심이다. 위치 인자 호출이 있으면 인자 순서를 바꾸지 않는다.

- [ ] 현재 설정과 런타임의 정적 문구 의존을 증거로 기록한다.

Run:

```bash
rg -n "policy_generation|standard_reference_note|_authority_note" src data/ontology tests
```

Expected: 청커 전달 목록에는 세대 필드가 있지만 `PdfSource`에는 없고, 런타임은 프로필의 정적 문구를 읽는다.

## Task 2: 출처 권위 계약 회귀 테스트 추가

**Files:**

- Modify: `tests/test_source_grounded_answers.py`
- Test: `tests/test_source_grounded_answers.py`

- [ ] 테스트 헬퍼가 `doc_short`, `product_type`, `is_own_company`를 독립 지정하도록 확장한다.

권장 인터페이스:

```python
def _hair_clause(
    *,
    generation: str,
    own_company: bool | None,
    doc_short: str | None = None,
    product_type: str | None = None,
) -> Chunk:
    ...
```

- [ ] 표준약관 단독 5세대 테스트를 추가한다.

```python
def test_fifth_generation_standard_clause_reports_registered_direct_authority() -> None:
    decision = build_policy_clause_decision(
        "노화현상으로 인한 탈모는 보상 가능한가요?",
        [_hair_clause(
            generation="5th",
            own_company=None,
            doc_short="표준약관",
            product_type="표준약관",
        )],
        policy_generation="5th",
    )

    assert decision is not None
    assert "5세대 표준약관은 등록되어 있으며" in decision.payload["authority_note"]
    assert "등록된 5세대 자사 상품 약관이 없" not in decision.answer
```

- [ ] 자사 단독, 자사+표준 혼합, 기타/불명 출처 테스트를 각각 추가한다.

Expected assertions:

```python
assert "자사 상품약관의 직접 조항" in own_decision.payload["authority_note"]
assert "자사 상품약관과 표준약관" in mixed_decision.payload["authority_note"]
assert "기준 문서의 직접 조항" in unknown_decision.payload["authority_note"]
```

- [ ] 활성 프로필에 낡은 문구가 남아도 유출되지 않는 테스트를 추가한다.

프로필 fixture의 `standard_reference_note`에 고유 문자열 `STALE-AUTHORITY-NOTE`를 넣고 `decision.answer`와 payload 모두에 나타나지 않음을 검증한다.

- [ ] 새 테스트가 현재 코드에서 예상대로 실패하는지 확인한다.

Run:

```bash
pytest tests/test_source_grounded_answers.py -v
```

Expected: 새 권위 문구·혼합 출처·낡은 프로필 차단 테스트만 실패한다.

## Task 3: 메타데이터 기반 권위 판정 구현

**Files:**

- Modify: `src/rag/source_grounded_answers.py`
- Test: `tests/test_source_grounded_answers.py`

- [ ] 출처 분류 헬퍼를 추가한다.

권장 구현 형태:

```python
def _policy_source_authority(chunk: Chunk) -> str:
    metadata = chunk.metadata or {}
    if metadata.get("is_own_company") is True:
        return "own"
    if metadata.get("product_type") == "표준약관" or metadata.get("doc_short") == "표준약관":
        return "standard"
    return "other"
```

- [ ] `_authority_note()`를 선택 청크 집합 기반으로 변경한다.

권장 계약:

```python
def _authority_note(policy_generation: str, direct_chunks: list[Chunk]) -> str:
    generation_label = policy_generation.replace("th", "세대")
    authorities = {_policy_source_authority(chunk) for chunk in direct_chunks}
    has_own = "own" in authorities
    has_standard = "standard" in authorities
    if has_own and has_standard:
        return f"현재 선택한 {generation_label} 자사 상품약관과 표준약관의 직접 조항을 함께 근거로 확인했습니다."
    if has_own:
        return f"현재 선택한 {generation_label} 자사 상품약관의 직접 조항 근거입니다."
    if has_standard:
        return f"{generation_label} 표준약관은 등록되어 있으며, 현재 답변은 해당 표준약관의 직접 조항을 근거로 합니다."
    return f"현재 선택한 {generation_label} 기준 문서의 직접 조항 근거입니다."
```

- [ ] 함수 호출에서 `profile` 전달을 제거하고 정적 `standard_reference_note` 접근을 완전히 삭제한다.

- [ ] 관련 테스트를 다시 실행한다.

Run:

```bash
pytest tests/test_source_grounded_answers.py -v
```

Expected: 모든 출처 권위 계약 테스트와 기존 탈모 분기 테스트가 통과한다.

## Task 4: 다음 인제스트의 세대 메타데이터 복구

**Files:**

- Modify: `src/config.py`
- Modify: `tests/test_chunker.py`
- Test: `tests/test_chunker.py`

- [ ] `PdfSource`에 기본값이 있는 세대 필드를 복구한다.

```python
policy_generation: str | None = None
```

필드는 기존 위치 인자 계약을 깨지 않는 후방 기본값 영역에 둔다.

- [ ] 실손 원본 설정을 명시한다.

```python
# 신한 이지로운 실손의료보험
policy_generation="4th"

# 표준약관
is_own_company=False
policy_generation="5th"
```

- [ ] 설정 원본과 청크 전파 회귀 테스트를 추가한다.

테스트는 `PDF_SOURCES`에서 `doc_short`로 두 문서를 찾고 다음을 검증한다.

```python
assert own_source.policy_generation == "4th"
assert own_source.is_own_company is True
assert standard_source.policy_generation == "5th"
assert standard_source.is_own_company is False
```

또한 `chunk_pages(..., doc_source=standard_source)` 결과에 아래가 보존되는지 검증한다.

```python
assert chunk.metadata["policy_generation"] == "5th"
assert chunk.metadata["is_own_company"] is False
```

- [ ] focused 테스트를 실행한다.

Run:

```bash
pytest tests/test_chunker.py -v
```

Expected: `False`가 누락되지 않고 모든 기존 청킹 테스트가 통과한다.

## Task 5: 기본 온톨로지 문구 중립화 및 직접 근거 고정 보존

**Files:**

- Modify: `data/ontology/concepts.json`
- Modify: `tests/test_source_grounded_answers.py` or the existing ontology registry test file
- Test: `scripts/check_ontology_sync.py`

- [ ] 기본 매니페스트의 `standard_reference_note`를 제거한다. 스키마 호환 때문에 키 유지가 필요하면 `5세대 표준약관의 직접 조항 근거입니다.`처럼 존재/부재를 단정하지 않는 값으로 바꾼다.

- [ ] `direct_source_chunk_ids`의 다음 값이 변하지 않았음을 테스트한다.

```json
{
  "4th": ["약관_ch_002457"],
  "5th": ["표준약관_ch_005453"]
}
```

- [ ] 활성 매니페스트를 직접 수정하지 않는다. 런타임이 그 안의 낡은 문구를 읽지 않는다는 Task 2 테스트를 증거로 사용한다.

- [ ] 온톨로지 구조 검증을 실행한다.

Run:

```bash
python scripts/check_ontology_sync.py
```

Expected: 구조 및 동기화 불변조건 검사가 통과한다.

## Task 6: 파이프라인·API 회귀 검증

**Files:**

- Test: `tests/test_pipeline.py`
- Test: `tests/test_api_chat_stream.py`
- Modify only if an assertion encodes the obsolete wording

- [ ] 세대 필터와 source-grounded hair-loss 경로의 우선순위가 그대로인지 확인한다.

Run:

```bash
pytest tests/test_pipeline.py -v
```

Expected: 4세대 질문은 자사 직접 청크를, 5세대 질문은 표준약관 직접 청크를 사용하며 일반 RAG가 결정적 답변을 덮어쓰지 않는다.

- [ ] API 스트림의 새 답변 문구와 저장 순서를 확인한다.

Run:

```bash
pytest tests/test_api_chat_stream.py -v
```

Expected: 새 5세대 응답에는 표준약관 등록·직접 근거 문구가 나타나고 정적 자사약관 부재 문구가 없다. 과거 메시지 fixture를 재작성하는 동작은 없다.

- [ ] 운영 대화 DB에 쓰지 않는 격리 smoke를 실행한다.

직접 `Chunk` fixture 또는 임시 테스트 DB만 사용해 4세대와 5세대 질문을 각각 호출한다. 실제 계정, 세션, 대화 내용은 복사하지 않는다.

Expected:

```text
4세대 -> 자사 상품약관 직접 조항
5세대 -> 5세대 표준약관 등록 및 직접 조항
```

## Task 7: 종합 검증과 변경 보고서

**Files:**

- Create: `docs/<next-number>_FIFTH_POLICY_SOURCE_AUTHORITY_FIX_REPORT.md`
- Do not modify: `docs/270_*`
- Do not modify: `docs/271_*`

- [ ] 최신 문서 번호를 확인하고 충돌하지 않는 구현 보고서를 작성한다.

보고서에 포함할 내용:

- 사용자 증상과 검색 성공/문구 오류의 구분
- 변경 파일과 권위 판정 계약
- 재인제스트 메타데이터 복구
- 실행한 테스트와 결과
- 재인덱스·GraphDB 재구축·과거 메시지 수정이 없었음
- 표준약관 전체 구간 재분류가 남은 별도 위험임

- [ ] 관련 테스트 묶음을 실행한다.

Run:

```bash
pytest tests/test_source_grounded_answers.py tests/test_chunker.py tests/test_pipeline.py tests/test_api_chat_stream.py -v
python scripts/check_ontology_sync.py
git diff --check
```

Expected: 모두 성공하고 공백 오류가 없다.

- [ ] 여건이 허용되면 전체 테스트를 실행한다.

Run:

```bash
pytest -q
```

Expected: 전체 통과. 실행하지 못하면 이유와 실행한 focused 범위를 보고서와 최종 응답에 명시한다.

- [ ] 최종 자체 점검을 수행한다.

Checklist:

- 요청 범위 밖의 인덱스·DB·룰 변경이 없는가
- 정적 자사약관 부재 문구가 런타임에서 완전히 차단되는가
- 기존 인덱스의 `None` 메타데이터도 표준약관으로 인식하는가
- 다음 인제스트에서 세대와 `False`가 보존되는가
- 임시 로그·캐시·테스트 산출물이 남지 않았는가
- 작업공간 상태와 남은 위험을 정확히 보고했는가

## Task 8: 전달 경계

- [ ] 구현 결과를 Planner/사용자에게 보고한다.

반드시 포함:

- 기준 커밋과 격리 작업공간 경로
- 변경 파일
- 테스트 명령과 통과/실패 수
- 재인덱스·운영 DB 쓰기 여부
- 표준약관 구간별 재분류가 별도 과제라는 사실
- 커밋/푸시를 하지 않았는지 여부

사용자의 별도 승인 전에는 커밋, 푸시, protected main 반영, 서비스 재기동을 수행하지 않는다.
