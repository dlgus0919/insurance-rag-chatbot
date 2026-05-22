# 113. GraphDB RAG 런타임 검토 및 보강 명세

## 1. 목적

이 문서는 `docs/112_GRAPHDB_RETRIEVER_SYNC_REVIEW_FIX_SPEC.md` 이후 구현된 GraphDB 연동 상태를 검토한 결과와, 다음 서브 에이전트가 수행해야 할 보강 작업을 정의한다.

현재 GraphDB는 빌드, 정합성 검사, 5개 자동 QA, pytest 기준으로는 통과 상태다. 그러나 실제 사용 플로우 기준으로는 자동평가가 잡지 못한 런타임 품질 결함이 남아 있다. 특히 사용자가 복합 질의를 입력했을 때 GraphDB가 불필요한 별표 조항을 함께 주입하면 LLM 답변이 다시 혼합되거나 근거가 흐려질 수 있다.

작업 기준 디렉터리는 항상 DGX Spark의 `/srv/shared/projects/insurance-rag-chatbot`이다. 맥 로컬 프로젝트는 개발 기준으로 사용하지 않는다.

## 2. 현재 검토 결과

### 2.1 정상 확인된 사항

원격 DGX 환경에서 다음 검증은 보고와 일치했다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot
PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl
# Evaluation Summary: 5/5 cases passed.

PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py
# Detailed Integrity Check: PASS

.venv/bin/pytest -q
# 325 passed, 3 warnings
```

현재 Streamlit은 `ai-hang` 사용자로 8501 포트에서 실행 중이며, 8502 포트는 `dani` 사용자 소유 프로세스가 별도로 점유 중이다. 8502는 본 작업에서 임의 종료하지 않는다.

### 2.2 발견된 주요 결함

#### 결함 A: 별표 항목 번호 파싱이 너무 넓다

`GraphRetriever`의 `policy_appendix_payment_lookup` 경로가 질문 안의 모든 숫자를 별표 항목 번호 후보로 본다. 그 결과 아래 질의에서 `신1-5종`, `[별표7]`, `3가지`의 숫자가 별표 항목 번호처럼 해석된다.

```text
기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고,
이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘.
그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘.
```

실제 출력에서 `rule_sol_health_별표7_1`, `rule_sol_health_별표7_3` 같은 불필요한 `DEFINED_IN_APPENDIX` fact가 섞였다. 자동평가는 기대 fact가 존재하는지만 확인했기 때문에 이 과잉 fact를 잡지 못했다.

#### 결함 B: 평가셋이 과잉 검색을 실패로 보지 않는다

현재 `eval_graph_qa.py`는 expected fact가 있으면 PASS가 가능하다. 그러나 RAG에서는 관련 없는 구조화 fact가 프롬프트에 주입되는 것 자체가 답변 품질 저하 요인이다. GraphDB 평가에는 "있어야 하는 사실"뿐 아니라 "있으면 안 되는 사실"도 검증해야 한다.

#### 결함 C: `DEFINED_IN_APPENDIX` confirmed fact에 evidence가 없다

별표 조항 직접 조회는 confirmed로 반환되지만, fact 자체의 `evidence`가 비어 있다. 최종 답변에서는 "확정 구조화 사실"으로 보이는데 출처 행/청크를 따라갈 수 없으면 보험 업무 보조 도구로서 신뢰성이 떨어진다.

#### 결함 D: peer 목록의 선택 기준이 불명확하다

동일 등급 수술 peer는 SQL `LIMIT`에 의존하고 있어 사용자가 기대한 "동일 대분류 우선" 또는 "SOL 별표7 대분류와 연결되는 항목 우선"이 보장되지 않는다. 같은 종수 268개 중 임의 3개가 나올 수 있으며, 답변 재현성도 낮아진다.

#### 결함 E: Graph context가 답변 프롬프트를 과도하게 오염시킬 수 있다

현재 Graph context는 confirmed/candidate/missing을 모두 텍스트로 prepend한다. 관련 없는 confirmed 별표 fact가 섞이면 LLM이 핵심 질의보다 별표 조항 설명으로 흐를 수 있다. Graph facts는 질문 의도별로 엄격하게 필터링하고, 후보 조항은 근거 후보임을 UI와 prompt에서 모두 분명히 해야 한다.

## 3. 구현 목표

다음 작업의 목표는 GraphDB를 "검색 보조 근거"가 아니라 "정량/관계 질의의 구조화 기준선"으로 안정화하는 것이다.

1. 별표 항목 번호 파싱을 안전하게 축소한다.
2. 자동평가가 과잉 fact와 잘못된 status 승격을 실패로 잡게 한다.
3. `DEFINED_IN_APPENDIX`, `POLICY_COVERS_PROCEDURE`, `PAYS_BY_RATIO` fact가 추적 가능한 evidence를 갖게 한다.
4. 동일 등급 peer 추천을 질문 목적에 맞게 안정적으로 정렬한다.
5. Streamlit/RAG 프롬프트에 들어가는 Graph context를 관련 fact 중심으로 제한한다.
6. 보험금 계산 파이프라인에서는 candidate fact를 확정 지급 규칙으로 쓰지 못하게 한다.

## 4. 세부 구현 명세

### 4.1 Query Planner에 별표 항목 번호 필드 추가

`src/graph/query_planner.py`의 `GraphQueryPlan`에 다음 필드를 추가한다.

```python
appendix_numbers: list[str] = field(default_factory=list)
```

항목 번호는 다음처럼 명시적 패턴에서만 추출한다.

- 허용: `18번`, `19번 항목`, `18번 조항`, `18항`
- 허용: `별표7의 18번`, `별표 7 18번 항목`
- 금지: `신1-5종`의 `1`, `5`
- 금지: `별표7`의 `7`
- 금지: `3가지`, `3개`, `top 3`의 `3`

권장 구현:

```python
appendix_number_rx = re.compile(r"(?<!별표\s?)(\d{1,3})\s*(?:번\s*)?(?:항목|조항|항)\b|(\d{1,3})\s*번\b")
```

실제 구현에서는 위 정규식을 그대로 쓰기보다 테스트를 먼저 작성하고, 한국어 띄어쓰기 변형을 포함해 조정한다.

### 4.2 Retriever의 별표 직접 조회 조건 강화

`src/graph/retriever.py`에서 `policy_appendix_payment_lookup`이 별표 조항을 직접 조회하는 경우는 아래로 제한한다.

1. `plan.appendix`가 존재한다.
2. `plan.appendix_numbers`가 1개 이상 존재한다.
3. 질문이 특정 번호 항목 조회 의도일 때만 `DEFINED_IN_APPENDIX` facts를 반환한다.

`plan.appendix_numbers`가 비어 있는 경우에는 `[별표7]`이 언급되어도 별표 전체의 조항을 임의로 반환하지 않는다. 대신 수술명 또는 카테고리와 연결된 `POLICY_COVERS_PROCEDURE`/`PAYS_BY_RATIO` 후보만 반환한다.

### 4.3 `DEFINED_IN_APPENDIX` evidence 연결

`DEFINED_IN_APPENDIX` fact를 만들 때 해당 rule node와 연결된 evidence를 조회해 fact에 포함한다.

권장 조회 우선순위:

1. `graph_node_evidence`에 연결된 evidence
2. `DEFINED_IN_APPENDIX` edge의 `source_evidence_id`
3. 둘 다 없으면 candidate 또는 warning으로 하향 처리

confirmed fact는 최소 1개 이상의 evidence를 가져야 한다. evidence가 없으면 `status="candidate"` 또는 `warnings`에 명시한다.

### 4.4 동일 등급 peer 정렬 기준 고정

동일 등급 peer 조회는 단순 `LIMIT` 대신 안정적인 정렬을 적용한다.

권장 우선순위:

1. 질문 대상 수술과 동일 대분류 `HAS_CATEGORY`를 공유하는 수술
2. SOL [별표7] 후보 조항과 같은 `category_large`에 속하는 수술
3. evidence가 존재하는 수술
4. canonical name 오름차순

반환 개수는 `requested_peer_count`를 지키되, 후보가 부족하면 warning을 남긴다.

### 4.5 Graph context 필터링

`src/graph/context.py` 또는 호출부에서 질문 의도별로 context fact를 제한한다.

- `surgery_grade_lookup`: 대상 수술의 등급 fact와 직접 관련 candidate policy fact만 포함
- `same_grade_surgery_list`: peer fact는 요청 개수까지만 포함
- `category_grade_listing`: category/grade 결과는 표 형태로 압축하고, missing code/payment fact는 명확히 표시
- `policy_appendix_payment_lookup`: 명시 번호가 있을 때만 해당 rule details 포함
- `hira_code_lookup`: 수가코드 fact 또는 missing fact 중심으로 제한

Graph context는 LLM에게 주는 구조화 근거이므로, 최대 fact 수를 config로 제한한다.

권장 env:

```env
GRAPH_CONTEXT_TOP_K=20
GRAPH_CONTEXT_MAX_CHARS=5000
```

`GRAPH_CONTEXT_MAX_CHARS`가 없으면 추가한다.

### 4.6 평가 스크립트 강화

`eval/graph_qa.jsonl` 케이스에 다음 선택 필드를 추가한다.

```json
{
  "forbidden_facts": [
    {"subject": "rule_sol_health_별표7_1", "relation": "DEFINED_IN_APPENDIX"},
    {"subject": "rule_sol_health_별표7_3", "relation": "DEFINED_IN_APPENDIX"}
  ],
  "max_facts_by_relation": {
    "DEFINED_IN_APPENDIX": 0
  },
  "requires_evidence_for_status": ["confirmed"]
}
```

`scripts/eval_graph_qa.py`는 다음을 검증해야 한다.

- `forbidden_facts`가 하나라도 검색되면 FAIL
- relation별 최대 개수 초과 시 FAIL
- `status="confirmed"` fact에 evidence가 없으면 FAIL
- expected status가 `candidate`인데 실제가 `confirmed`면 FAIL
- missing fact의 object가 있으면 FAIL

Q1 케이스에는 `DEFINED_IN_APPENDIX` 직접 fact가 나오면 실패하도록 설정한다. Q4처럼 18/19번을 직접 묻는 케이스에만 `DEFINED_IN_APPENDIX`를 허용한다.

### 4.7 보험금 계산 파이프라인 안전장치

`src/claim_calculation/pipeline.py`에서 GraphDB fact를 계산 근거로 사용할 때 다음 원칙을 지킨다.

- confirmed fact: 계산 근거 후보로 사용 가능
- candidate fact: `review_required=True`를 강제하고, 자동 계산 결과에는 "검토 후보"로만 표시
- missing fact: 계산식 작성 근거로 사용 금지

회귀 테스트를 추가한다.

- candidate `PAYS_BY_RATIO`만 있는 경우 지급예상액을 확정 문구로 표시하지 않는다.
- confirmed evidence가 없는 fact는 계산 근거에서 제외된다.

### 4.8 Streamlit 수동 테스트 시나리오 보강

8501 포트 기준으로 다음 수동 테스트를 수행하고 보고서에 결과를 남긴다.

```bash
ssh -L 8501:localhost:8501 ai-hang@100.88.5.57
```

브라우저 접속:

```text
http://localhost:8501
```

테스트 질문:

1. `기관지 식도루 폐쇄술의 신1-5종 수술 종수는 몇 종이고, 이와 같은 종수에 해당하는 다른 수술을 3가지 더 알려줘. 그 중 SOL 처음건강보험 [별표7]에서 동일한 대분류 항목에 들어가는 수술이 있다면 표시해줘.`
   - 기대: 신1-5종 4종
   - 기대: peer 3개
   - 기대: 별표7 1번/3번 조항이 GraphDB 근거에 노출되지 않음
   - 기대: SOL 후보 조항은 candidate로 표시

2. `SOL 건강보험 별표7의 18번 항목과 19번 항목의 차이점과 각각 해당하는 수술종류를 알려주세요.`
   - 기대: 18번/19번만 confirmed로 표시
   - 기대: 각 fact에 evidence 표시

3. `신1-5종 수술분류표에서 5종에 해당하는 수술을 소화기계 카테고리에서 모두 나열해줘. 각각의 수가코드와 SOL 건강보험에서 지급되는 보험금 비율도 같이 알려줘.`
   - 기대: 간장 이식수술, 췌장 이식수술
   - 기대: 수가코드가 없으면 missing으로 표시하고 임의 생성하지 않음
   - 기대: 지급비율은 candidate로 표시

4. `존재하지않는가상의수술의 수가코드를 조회해줘.`
   - 기대: missing으로 표시하고 코드 환각 없음

## 5. 필수 검증 명령

DGX에서 아래 명령을 모두 실행한다.

```bash
cd /srv/shared/projects/insurance-rag-chatbot

PYTHONPATH=. .venv/bin/python scripts/check_graph_index.py

PYTHONPATH=. .venv/bin/python scripts/eval_graph_qa.py \
  --graph data/index/graph/insurance_graph.sqlite \
  --eval eval/graph_qa.jsonl

.venv/bin/pytest tests/test_graph_*.py -v

.venv/bin/pytest tests/test_streamlit_app.py tests/test_claim_*.py -v

.venv/bin/pytest -q
```

무거운 LLM/SGLang/vLLM 재기동 검증은 다른 팀원의 테스트와 충돌할 수 있으므로 필요 시 사용자 확인 후 진행한다.

## 6. 산출물

서브 에이전트는 작업 완료 후 다음 문서를 작성한다.

```text
docs/114_GRAPHDB_RAG_RUNTIME_HARDENING_IMPL_REPORT.md
```

보고서에는 다음을 포함한다.

- 변경 파일 목록
- 결함 A~E에 대한 조치 내역
- Graph QA 평가 결과
- 전체 pytest 결과
- Streamlit 8501 수동 테스트 결과 또는 미실행 사유
- 남은 리스크

## 7. Git 관리 지침

커밋 전 `git status --short`를 확인한다. 다음은 커밋 대상이다.

- `src/graph/**`
- `src/rag/pipeline.py`
- `src/claim_calculation/pipeline.py`
- `src/retrieval/vector_store.py`
- `src/ui/chat_store.py`
- `src/ui/streamlit_app.py`
- `src/config.py`
- `scripts/eval_graph_qa.py`
- `eval/graph_qa.jsonl`
- 관련 테스트 파일
- `docs/114_GRAPHDB_RAG_RUNTIME_HARDENING_IMPL_REPORT.md`

다음은 커밋하지 않는다.

- `data/index/graph/insurance_graph.sqlite*`
- `reports/graph/eval_graph_qa_results.jsonl`
- `logs/*.log`
- `._*`
- 다른 팀원의 임시 파일 또는 workspace 산출물

## 8. 자체 점검 결론

현재 GraphDB 연동은 빌드와 기본 검색 검증 단계는 통과했지만, 실제 보험 보상 업무 보조라는 목적에는 "관련 없는 구조화 fact가 하나라도 프롬프트에 들어가면 위험하다"는 기준을 적용해야 한다. 따라서 다음 단계는 신규 기능 확장보다 런타임 검색 결과의 정밀도와 평가 엄격도를 높이는 작업이 우선이다.

이 명세의 핵심은 GraphDB가 LLM의 답변을 강하게 보정하도록 하되, 잘못 연결된 candidate 또는 과잉 조항이 확정 근거처럼 보이지 않게 하는 것이다.
