# fivetaku/llm-wiki 분석 및 보험 RAG 챗봇 편입 제안서

작성일: 2026-06-22  
대상 저장소: <https://github.com/fivetaku/llm-wiki>  
대상 프로젝트: `insurance-rag-chatbot`

## 1. 결론

`fivetaku/llm-wiki`는 코드 라이브러리라기보다 **LLM이 raw 자료를 영구 Markdown 지식베이스로 합성, 유지, 질의, 점검하는 운영 템플릿**이다. 우리 프로젝트에는 저장소를 그대로 복제하기보다 다음 두 방향으로 선별 편입하는 것이 적합하다.

1. **개발 과정 편입**
   - 현재 산발적으로 누적되는 보고서, 평가 결과, 모델 실험, 결함 분석, 운영 runbook을 `개발 위키`로 구조화한다.
   - 신규 자료 수집과 정제, 질의, 점검을 `/ingest`, `/compile`, `/query`, `/lint`에 해당하는 내부 워크플로우로 나눈다.
   - 발표 준비, 인수인계, 회귀 원인 추적, 모델 선택 근거를 재검색 없이 축적한다.

2. **챗봇 아이디어 편입**
   - `index.md = catalog`가 아니라 `index.md = router`라는 관점을 보험 질의 라우팅에 도입한다.
   - `aliases.md` 정본화, source summary, provenance, query 파일백, lint 건강검진을 기존 OntologyRegistry, GraphDB, Hybrid RAG와 연결한다.
   - 최종 목표는 Markdown Wiki를 운영 지식의 사람이 읽는 canonical layer로 두고, Graph/Vector/RDB 인덱스는 재생성 가능한 파생 layer로 관리하는 것이다.

핵심 판단: **llm-wiki는 우리 챗봇의 검색 엔진을 대체하지 않는다. 대신 지식 운영, 정본화, 라우팅, 근거 관리, 개발 기록 축적 방식을 보강한다.**

## 2. llm-wiki 저장소 분석

### 2.1 저장소 성격

README 기준으로 `llm-wiki`는 raw 소스를 LLM이 직접 합성, 유지하는 영구 Markdown 위키 워크스페이스다. 매 질문마다 원문을 새로 검색하는 RAG와 달리, 한 번 합성한 지식을 최신 상태로 누적하는 것을 목표로 한다.

확인한 공개 구조:

```text
llm-wiki/
  .claude/
    commands/
      ingest.md
      compile.md
      query.md
      lint.md
    hooks/
      session-start.sh
    settings.json
  00-system/
    conventions.md
  10-inbox/
  20-raw/
  30-wiki/
  40-templates/
    source.md
    entity.md
    concept.md
  50-queries/
  90-archive/
  _meta/
  CLAUDE.md
  README.md
```

저장소는 MIT License이며, GitHub 기준 공개 템플릿 성격이다. 릴리스 패키지나 Python/JS 라이브러리 형태는 아니고, Claude Code 워크스페이스 규약과 Markdown 명령 파일 중심으로 동작한다.

### 2.2 핵심 개념

| 개념 | llm-wiki 방식 | 우리 프로젝트 적용 의미 |
|---|---|---|
| raw 불변성 | `20-raw/`는 처리 완료 원본, LLM은 읽기만 함 | 보험 원문 PDF/OCR/추출본과 승인 지식을 분리 |
| inbox 분리 | `10-inbox/`는 미컴파일 자료 대기열 | 신규 약관, 회의록, 평가 로그, 모델 결과를 임시 수집 |
| wiki 합성 | `30-wiki/`는 LLM이 쓰는 영구 지식 페이지 | 개발 지식과 보험 지식을 Markdown canonical layer로 축적 |
| schema layer | `CLAUDE.md`, `00-system/conventions.md` | Codex/개발자/LLM이 따를 운영 규약 문서화 |
| router index | `index.md`는 전체 카탈로그가 아니라 의도별 라우터 | 현재 `query_router.py`, `search_intent.py`를 데이터 기반으로 확장 |
| aliases | 표기 흔들림을 정본명으로 매핑 | 보험 용어, 상품명, 담보명, 의료 코드, 조항 별칭 정본화 |
| provenance | 모든 사실 주장에 source 역링크 요구 | hallucination 방지, Graph review path와 evidence panel 강화 |
| query fileback | 좋은 질의 결과를 `50-queries/`에 저장 | 반복 질문, 발표 답변, 결함 재현 질문을 자산화 |
| lint | 모순, 죽은 링크, 고아 페이지, 인덱스 정합 점검 | ontology/graph/vector sync 점검과 결합 |

### 2.3 명령 워크플로우

`llm-wiki`는 네 동사를 명확히 분리한다.

| 명령 | 역할 | 중요한 설계 판단 |
|---|---|---|
| `/ingest` | URL, 파일, 텍스트를 inbox에 저장만 함 | 수집과 지식 확정을 분리 |
| `/compile` | inbox 자료를 source/entity/concept 페이지로 합성 | aliases, router, index, overview, log까지 함께 갱신 |
| `/query` | router와 aliases로 2단 라우팅 후 필요한 페이지만 읽음 | 위키가 커져도 질문당 토큰 비용을 일정하게 유지 |
| `/lint` | 모순, 링크, 고아, index, aliases, provenance 점검 | 지식베이스를 운영 대상으로 취급 |

이 분리는 우리 프로젝트의 장기 방향인 `candidate -> validation -> human approval -> active ontology -> GraphDB rebuild -> evaluation` 흐름과 잘 맞는다.

### 2.4 라우팅 모델

가장 중요한 아이디어는 **index를 목록이 아니라 라우터로 쓰는 것**이다.

`llm-wiki`의 질의는 다음 두 단계로 나뉜다.

```text
Phase A: Route
  질문에서 엔티티, 타입, 연산을 파악
  aliases로 정본화
  router만 읽고 열어야 할 타입/샤드 결정

Phase B: Search
  지정된 샤드와 후보 페이지만 읽음
  본문과 1-hop 링크만 보강
  근거 있는 내용만 답변
```

우리 프로젝트는 이미 `src/rag/query_router.py`, `src/rag/search_intent.py`, `src/rag/auto_params.py`에서 질의 유형 분류와 파라미터 조정을 하고 있다. 여기에 llm-wiki식 정본화/라우터 테이블을 붙이면, 하드코딩된 cue 중심 라우팅을 점진적으로 데이터 기반으로 옮길 수 있다.

### 2.5 강점

- 구조가 단순하다. Markdown 파일, aliases, index, log만으로 시작할 수 있다.
- LLM 친화적이다. BLUF, frontmatter, 고정 섹션, 링크, provenance가 있어 agent가 읽고 쓰기 쉽다.
- RAG와 상호보완적이다. vector/BM25가 실패해도 router와 aliases가 fallback 역할을 할 수 있다.
- 운영성이 좋다. `/lint` 개념이 있어 지식의 drift, 모순, 고아 페이지를 정기 점검 대상으로 만든다.
- 개발 지식 축적에 강하다. 모델 실험, 결함 분석, 발표 준비, 운영 결정이 휘발되지 않는다.

### 2.6 한계와 주의점

- 실행 가능한 RAG 프레임워크가 아니다. 실제 검색, chunking, embedding, GraphDB, API 기능은 우리 코드가 담당해야 한다.
- Claude Code 중심 템플릿이다. Codex 환경에서는 명령 파일을 그대로 쓰기보다 `docs/wiki` 규약과 스크립트로 재해석해야 한다.
- 보험 도메인에서는 자동 compile 결과를 active knowledge로 바로 쓰면 위험하다. 지급/면책/계산 rule은 반드시 후보와 승인 단계를 거쳐야 한다.
- Markdown 위키가 커지면 검증 자동화가 없을 경우 또 다른 문서 부채가 된다. 처음부터 lint와 평가 연결이 필요하다.
- 원본 보험 문서, OCR 산출물, 내부 로그에는 민감정보가 섞일 수 있어 raw/wiki 공개 범위를 엄격히 나눠야 한다.

## 3. 현재 프로젝트와의 접점

우리 프로젝트는 이미 단순 RAG를 넘어 다음 요소를 갖고 있다.

- FastAPI + SPA 챗봇
- Dense/BM25/RRF/Reranker 기반 Hybrid RAG
- OCR 및 표 인덱스
- GraphDB review path
- OntologyRegistry와 candidate approval workflow
- 보험금 계산 pipeline
- 모델/인덱스 평가 문서와 운영 보고서

따라서 llm-wiki 편입의 방향은 “새 RAG를 만드는 것”이 아니라 **지식 운영 계층을 명시화하고, 기존 검색/그래프/온톨로지의 정본화와 점검 능력을 강화하는 것**이다.

## 4. 개발 과정 편입 제안

### 4.1 개발 위키 디렉터리 신설

제안 경로:

```text
docs/dev-wiki/
  00-system/
    conventions.md
  10-inbox/
  20-raw/
  30-wiki/
    index.md
    log.md
    project/
      index.md
      aliases.md
      overview.md
      indexes/
      sources/
      entities/
      concepts/
    models/
    retrieval/
    ontology/
    graph/
    claim-calculation/
  40-templates/
    source.md
    entity.md
    concept.md
    decision.md
    experiment.md
  50-queries/
  90-archive/
```

`docs/` 아래에 두는 이유는 기존 보고서 문화와 맞고, 코드 실행 경로와 분리되며, Git 관리가 쉽기 때문이다.

### 4.2 개발 위키에 넣을 대상

| 대상 | 예시 | 위키화 가치 |
|---|---|---|
| 모델 실험 | SGLang/vLLM/Ollama 모델별 결과 | 같은 실험 반복 방지 |
| 검색 결함 | retrieval miss, row-level grounding 실패 | 결함 유형별 해결 이력 축적 |
| 평가 결과 | smoke QA, graph QA, claim E2E | 성능 변화 추적 |
| 운영 결정 | 기본 모델 변경, provider 제외 사유 | 발표/인수인계 근거 |
| 설계 결정 | GraphDB rule node, ontology approval | 왜 그렇게 만들었는지 보존 |
| 발표 자료 | 1차/2차 발표 준비 문서 | 큰 그림 유지 |
| 외부 자료 | llm-wiki, GraphRAG, RAG 논문 | 프로젝트 방향성 보강 |

### 4.3 개발 워크플로우

```text
새 자료/실험 결과 발생
  -> docs/dev-wiki/10-inbox/에 저장
  -> compile-dev-wiki 실행 또는 Codex에게 "dev-wiki로 정리" 요청
  -> source/decision/experiment/concept 페이지 생성
  -> aliases/index/overview/log 갱신
  -> 중요한 질의 결과는 50-queries/에 파일백
  -> 주 1회 lint로 링크, 중복, 모순, stale 결과 점검
```

초기에는 완전 자동화하지 말고, Codex가 문서 작업을 수행하되 `conventions.md`를 기준으로 쓰게 하는 방식이 현실적이다. 이후 반복 패턴이 안정되면 `scripts/dev_wiki_lint.py`, `scripts/dev_wiki_compile.py`를 추가한다.

### 4.4 개발 위키 템플릿 확장

llm-wiki의 `source/entity/concept`에 더해 우리 프로젝트에는 다음 템플릿이 필요하다.

| 템플릿 | 용도 |
|---|---|
| `decision.md` | 기본 모델 변경, architecture 선택, 폐기 결정 |
| `experiment.md` | 평가셋, 모델, 파라미터, 결과, 결론 |
| `defect.md` | 재현 질문, 원인, 수정 파일, 회귀 테스트 |
| `runbook.md` | DGX/배포/장애 대응 절차 |

예시 frontmatter:

```yaml
type: experiment
canonical: "qwen3-next-80b-auto-rag-eval"
topic: "models"
summary: "Qwen3 Next 80B 기반 auto RAG 파라미터 평가. 검색 의도별 top-k/temperature 자동 조절 검증."
status: active
sources:
  - docs/229_AUTO_RAG_PARAMETER_CONTROL_COMPLETION_REPORT.md
updated: 2026-06-22
```

## 5. 챗봇 아이디어 편입 제안

### 5.1 보험 도메인 aliases 정본화 강화

현재 `OntologyRegistry`는 aliases와 candidate_aliases를 갖고 있다. 여기에 Markdown `aliases.md`를 사람이 읽고 검토할 수 있는 운영 뷰로 추가한다.

제안:

```text
data/ontology/wiki/
  30-wiki/insurance/
    aliases.md
    index.md
    indexes/
      coverage-items.md
      exclusions.md
      deductible-rules.md
      required-documents.md
      hira-codes.md
```

역할 분리:

- `data/ontology/concepts.active.json`: 런타임 canonical manifest
- `data/ontology/wiki/.../aliases.md`: 사람이 리뷰하기 쉬운 정본화 뷰
- `scripts/check_ontology_sync.py`: JSON과 Markdown alias/index의 diff 검사

기대 효과:

- “실비/실손/실손보험/실손의료보험” 같은 표기 흔들림을 질의 전 단계에서 안정화
- 담보명, 특약명, 운전자보험 조항명, HIRA 코드명, 수술명 별칭 관리 개선
- 하드코딩 cue를 줄이고 운영 데이터로 라우팅 키 관리

### 5.2 Router as Data

현재 `query_router.py`는 Python cue와 regex 중심이다. llm-wiki식 라우터 표를 데이터로 외부화하면 아래 구조가 가능하다.

```text
data/routing/
  insurance_router.yaml
  aliases.md
  route_index.md
```

라우터 예시:

```yaml
routes:
  - route: quickcode
    intent: procedure_code_lookup
    aliases:
      - 수가코드
      - EDI코드
      - 행위코드
    target_indexes:
      - hira_codes
    default_params:
      top_k_dense: 8
      top_k_bm25: 16
      temperature: 0.0

  - route: formal
    intent: coverage_judgment
    aliases:
      - 보상
      - 지급
      - 실손
      - 실비
    target_indexes:
      - clauses
      - exclusions
      - deductible_rules
      - required_documents
```

초기에는 Python fallback을 유지하고, YAML router가 match되면 우선 적용하는 하이브리드 방식이 안전하다.

### 5.3 Source Summary Page를 Evidence Layer로 활용

llm-wiki는 raw 1개당 source summary 1개를 만든다. 우리 프로젝트는 PDF chunk와 Graph node는 많지만, “문서 전체가 무엇을 보장하고 어떤 질문에 강한가”를 요약한 상위 source page가 부족하다.

제안:

```text
data/knowledge/insurance-wiki/30-wiki/policies/sources/
  sol-health-policy.md
  sol-driver-policy.md
  standard-policy.md
  hira-fee-schedule.md
  consultation-cases.md
```

각 source page는 다음을 포함한다.

- 문서 범위
- 주요 보장/면책/한도/공제 단위
- 강한 질의 유형
- 취약 질의 유형
- 연결된 Graph node/index
- chunk manifest 또는 source_file 역링크

효과:

- 거시 질문에서 `overview.md`와 source summary를 먼저 보고 내려갈 수 있다.
- 평가 실패 원인을 source coverage 문제와 retrieval 문제로 나누기 쉬워진다.
- 신규 문서 편입 시 어떤 router/index를 갱신해야 하는지 명확해진다.

### 5.4 Query Fileback으로 반복 질의 자산화

현재 평가셋은 `eval/*.jsonl` 중심이고, 채팅 세션은 DB/로그로 남는다. llm-wiki식 `50-queries/`를 도입하면 “좋은 질의와 좋은 답변의 구조”를 지식화할 수 있다.

대상:

- 실제 상담/보상 검토에서 반복되는 질문
- 답변 실패 후 수정한 재현 질문
- 발표 데모 질문
- 모델 비교에서 품질 차이가 드러난 질문

저장 예시:

```text
data/knowledge/insurance-wiki/50-queries/
  driver-diagnosis-confirmation-requirements.md
  hira-pancreas-transplant-code-lookup.md
  fourth-generation-deductible-example.md
```

운영 방식:

- 단순 채팅 로그 전체를 저장하지 않는다.
- 실무 가치가 있고 개인정보가 제거된 질의만 큐레이션한다.
- 저장된 query는 eval case 후보로 승격할 수 있게 한다.

### 5.5 Lint를 운영 진단으로 확장

llm-wiki의 `/lint`는 우리 프로젝트의 운영 진단과 잘 맞는다.

제안 lint 항목:

| 영역 | 점검 |
|---|---|
| Markdown wiki | 죽은 링크, 고아 페이지, frontmatter 누락, BLUF 누락 |
| aliases | active ontology alias와 wiki aliases diff |
| router | route target index 존재 여부, cue 중복, stale route |
| Graph | Graph node source evidence와 chunk_id 역참조 가능 여부 |
| Vector | canonical chunk manifest와 vectorstore key sync |
| Eval | 저장 query 중 eval 미반영 고가치 질문 |
| Provenance | source 없는 확정 주장, auto tier 미검수 |

기존 `scripts/check_ontology_sync.py`, `scripts/check_graph_vector_sync.py`, `scripts/eval_graph_review_paths.py`를 묶어 관리자 진단 탭에도 노출할 수 있다.

## 6. 구현 로드맵

### Phase 0. 파일럿 문서화

목표: 코드 변경 없이 제안서와 규약만으로 개발 위키 운영을 시작한다.

작업:

- `docs/dev-wiki/` 골격 생성
- `00-system/conventions.md` 작성
- 기존 핵심 문서 5개를 source page로 수동 compile
- 발표 준비 문서를 `50-queries/` 또는 `project/overview.md`에 연결

완료 기준:

- “왜 Qwen3 Next 80B가 주력인가?”, “GraphDB는 무엇을 해결했나?”, “남은 검색 병목은 무엇인가?” 같은 질문에 dev-wiki만 보고 답할 수 있다.

### Phase 1. Ontology alias/index Markdown 뷰

목표: 보험 지식 정본화를 사람이 검토 가능한 형태로 만든다.

작업:

- `data/ontology/wiki/30-wiki/insurance/aliases.md` 생성
- active ontology manifest에서 aliases를 Markdown으로 export
- Markdown aliases와 JSON manifest diff 검사 추가
- 후보 alias 승인/차단 상태 표시

완료 기준:

- Python 코드 수정 없이 alias 후보 검토와 정본명 확인이 가능하다.

### Phase 2. Router YAML 실험

목표: cue 기반 라우팅 일부를 데이터 기반 router로 이전한다.

작업:

- `data/routing/insurance_router.yaml` 추가
- `query_router.py`에 optional router config loader 추가
- 기존 regex/cue fallback 유지
- quickcode, formal, general 3개 route부터 적용
- route decision을 debug payload에 기록

완료 기준:

- 기존 `tests/test_query_router.py` 통과
- 신규 router config 테스트 추가
- route 결과가 관리자/디버그 로그에서 확인 가능

### Phase 3. Source Summary + Query Fileback

목표: 문서 단위 설명과 반복 질의를 영구 자산화한다.

작업:

- 보험 문서별 source summary page 작성
- 실패/성공 대표 질의 20개를 `50-queries/`로 선별 저장
- `eval/*.jsonl` 후보 생성 스크립트 설계

완료 기준:

- 저장된 query 중 일부가 평가셋으로 승격되고, 회귀 테스트에서 재사용된다.

### Phase 4. Wiki Lint 통합

목표: 위키와 런타임 지식의 drift를 자동 점검한다.

작업:

- `scripts/wiki_lint.py` 추가
- dead link/frontmatter/alias diff/router target/evidence sync 점검
- 관리자 시스템 상태 또는 CI에 일부 연결

완료 기준:

- Markdown wiki가 문서 부채가 아니라 운영 진단 대상이 된다.

## 7. 가져오지 않을 것

다음은 현재 단계에서 가져오지 않는 편이 좋다.

| 항목 | 이유 |
|---|---|
| llm-wiki 폴더 구조 전체 복제 | 현재 프로젝트 구조와 충돌하고 중복 문서 부채가 생김 |
| 자동 compile 결과를 active ontology에 바로 반영 | 보험 판단 도메인에서 위험. 실무 승인 필요 |
| raw 보험 문서를 Git tracked wiki raw에 저장 | 민감 문서/저작권/용량 문제 |
| graph 검색을 Markdown 링크 traversal로 대체 | 기존 GraphRetriever와 VectorStore가 더 적합 |
| Claude 전용 `.claude/commands` 의존 | Codex/팀 운영 환경에서는 일반 Markdown 규약과 Python 스크립트가 더 이식성 높음 |

## 8. 예상 효과

### 개발 생산성

- 평가 결과와 결함 원인을 다시 찾는 시간이 줄어든다.
- 모델 제외 사유, 기본값 변경 사유, 운영 이슈가 누적된다.
- 발표 자료와 실제 개발 이력이 같은 지식 기반에서 이어진다.

### 챗봇 품질

- alias 정본화로 검색 miss가 줄어든다.
- route decision이 설명 가능해진다.
- source summary를 통해 거시 질문과 문서 범위 질문이 안정된다.
- query fileback을 통해 실무 질문이 평가셋으로 자연스럽게 승격된다.

### 운영 안정성

- ontology, graph, vector, markdown 지식 사이의 drift를 lint로 감지한다.
- auto/candidate/reviewed/approved 상태가 더 명확해진다.
- 근거 없는 확정 주장과 stale index를 조기에 잡을 수 있다.

## 9. 리스크와 대응

| 리스크 | 대응 |
|---|---|
| Markdown 위키가 또 다른 문서 더미가 됨 | 처음부터 lint, log, index 갱신을 완료 기준에 포함 |
| LLM이 출처 없는 내용을 위키에 확정 기재 | provenance 필수, auto tier 분리, reviewed/approved 승격 제한 |
| 기존 ontology JSON과 wiki aliases가 불일치 | export/import를 단방향으로 시작하고 diff 검사 도입 |
| 라우팅 config가 기존 동작을 깨뜨림 | optional loader + Python fallback + 기존 테스트 유지 |
| 민감 정보 저장 | raw 원문 저장 금지, 개인정보 제거 query만 파일백 |

## 10. 우선순위 제안

가장 먼저 할 일은 챗봇 코드 변경이 아니라 **개발 위키 파일럿**이다. 이유는 비용이 낮고, 실패해도 런타임에 영향이 없으며, 곧바로 발표/인수인계/운영 지식 정리에 도움이 되기 때문이다.

권장 순서:

1. `docs/dev-wiki/` 파일럿 생성
2. 현재 핵심 문서 5개를 source/decision/experiment로 정리
3. ontology alias Markdown export 설계
4. router YAML을 optional로 도입
5. wiki lint를 운영 진단과 연결

## 11. 참고 링크

- fivetaku/llm-wiki README: <https://github.com/fivetaku/llm-wiki>
- 운영 규약 `CLAUDE.md`: <https://raw.githubusercontent.com/fivetaku/llm-wiki/main/CLAUDE.md>
- 페이지/라우팅 규약 `00-system/conventions.md`: <https://raw.githubusercontent.com/fivetaku/llm-wiki/main/00-system/conventions.md>
- `/ingest` 명령: <https://raw.githubusercontent.com/fivetaku/llm-wiki/main/.claude/commands/ingest.md>
- `/compile` 명령: <https://raw.githubusercontent.com/fivetaku/llm-wiki/main/.claude/commands/compile.md>
- `/query` 명령: <https://raw.githubusercontent.com/fivetaku/llm-wiki/main/.claude/commands/query.md>
- `/lint` 명령: <https://raw.githubusercontent.com/fivetaku/llm-wiki/main/.claude/commands/lint.md>
- source/entity/concept 템플릿: <https://github.com/fivetaku/llm-wiki/tree/main/40-templates>

