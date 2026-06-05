# 175. Dynamic RRF Safe Integration Report

## 요약

팀원 브랜치 `dani/dynamic-rrf-results-20260604`의 동적 RRF/검색 의도 분류 작업을 그대로 병합하지 않고, 정확 코드 검색 회귀를 막는 안전장치를 추가해 편입했다.

이번 편입의 기본 정책은 다음과 같다.

- 검색 의도 분류 결과는 항상 진단 정보로 남긴다.
- 기본 운영값에서는 기존 고정 RRF 검색을 유지한다.
- 동적 가중치는 `DYNAMIC_RRF_ENABLED=true`와 `DYNAMIC_RRF_MODE=weighted|optimized`를 명시해야 적용한다.
- 정확 코드가 있는 질의는 Chroma의 `query_with_filter(filter_codes=...)` 경로를 항상 실행한다.
- 일반 Chroma 검색 생략은 `optimized` 모드에서 코드 필터 hit가 실제로 있을 때만 허용한다.

## 유지한 부분

- `SearchIntentPlan` 기반의 규칙형 검색 의도 분류
- BM25/Chroma 가중치를 받는 `rrf_fuse`
- API 및 관리자 진단 화면의 검색 의도 표시
- 의도 분류 및 weighted RRF 단위 테스트
- 팀원 브랜치의 전후 비교 문서 기록

## 수정한 문제

### 1. 정확 코드 검색 회귀 방지

기존 팀원 구현은 코드 패턴이 감지되면 `skip_dense=True`를 설정해 일반 Chroma뿐 아니라 코드 필터 Chroma 검색까지 생략될 수 있었다.

수정 후에는 다음 순서를 보장한다.

1. 코드가 있으면 query embedding 생성
2. `query_with_filter(filter_codes=...)` 실행
3. 일반 Chroma 검색은 기본 실행
4. 최적화 모드에서 코드 필터 hit가 있을 때만 일반 Chroma 생략 가능
5. 코드 필터 hit는 최종 fused hit 앞쪽에 보존

### 2. 복합 질문 처리

`N39.3 약관 근거와 보상 조건`처럼 코드와 보상 판단이 함께 있는 질문은 `exact_code_compound_lookup`으로 분류한다. 이 경우 일반 Chroma 검색과 GraphRAG 병합 경로를 생략하지 않는다.

### 3. 숫자형 표준코드 인식

`51040` 같은 숫자형 EDI/표준코드는 `코드`, `수가`, `표준`, `EDI`, `비급여표준`, `행위` 같은 문맥 cue가 있을 때만 코드로 인식한다. `100000원`, `50회`, `5세대` 같은 숫자는 코드로 오인하지 않도록 제외한다.

### 4. 진단 정보 정합성

`RetrievalExecutionInfo`를 추가해 관리자/API 진단이 계획값이 아니라 실제 실행값을 표시하도록 했다.

표시 항목:

- 동적 RRF 활성화 여부
- 적용 모드
- 실제 적용 BM25/Chroma weight
- 코드 필터 dense 실행 여부
- 일반 dense 실행 여부
- BM25 실행 여부
- fallback 사유

## 설정값

기본값:

```text
DYNAMIC_RRF_ENABLED=false
DYNAMIC_RRF_MODE=observe
DYNAMIC_RRF_SKIP_GENERAL_DENSE=false
```

운영 안정화 전에는 기본값을 유지한다. 성능 실험 시에는 먼저 `weighted` 모드로 가중치만 적용하고, 검색 생략은 별도 검증 후 `optimized` 모드에서 제한적으로 켠다.

## 검증 결과

실행 완료:

```bash
pytest tests/test_search_intent.py tests/test_hybrid_rrf.py tests/test_pipeline.py -q
```

결과:

```text
53 passed
```

문법 검증:

```bash
python -m py_compile src/rag/search_intent.py src/rag/pipeline.py src/api/routes/chat.py src/ui/admin_page.py src/config.py
```

결과: 통과

diff 검사:

```bash
git diff --check
```

결과: 통과

로컬 API 테스트는 시스템 Python 환경에 `aiosqlite`가 없어 수집 단계에서 실행하지 못했다. 관련 기능은 검색 파이프라인 단위 테스트와 문법 검증으로 우선 확인했다.

## 남은 권장 작업

- DGX 가상환경에서 전체 테스트 재실행
- 실제 인덱스 기반 A/B 평가셋에 Recall@K, MRR, 정확 근거 페이지 적중률 추가
- `weighted` 모드만 켠 상태의 지연시간 p50/p95 측정
- `optimized` 모드는 순수 코드 질의에서만 별도 승인 후 제한 적용
