# 000. Project Development Guardrails

## 0. 문서의 지위

이 문서는 보험 문서 RAG 챗봇 프로젝트의 개발 전반에 우선 적용하는 규칙이다.

적용 범위:

- 로컬 맥북 checkout: `/Users/june_kim/Projects/insurance-rag-chatbot`
- DGX 메인 저장소: `/srv/shared/projects/insurance-rag-chatbot`
- 소스 코드, 문서, 데이터 인덱스, 평가 스크립트, 운영 스크립트, 온톨로지/GraphDB/RuleRegistry 관련 작업

우선순위:

1. 시스템/보안/도구 정책
2. 사용자의 현재 명시 요청
3. 이 문서
4. `AGENTS.md`
5. 최신 번호의 설계/구현 문서
6. 오래된 개별 작업 명세와 README

오래된 문서와 이 문서가 충돌하면 이 문서를 우선한다. 단, 외부 보안 정책, 비밀정보 처리 정책, 사용자 명시 지시는 항상 이 문서보다 우선한다.

## 1. 핵심 원칙

이 프로젝트는 단순 RAG 챗봇이 아니라 문서 기반 보험 판단 지식 운영 시스템이다.

개발자는 다음 원칙을 기본값으로 둔다.

- 코드는 일반 처리 방식을 담당한다.
- 보험 지식은 코드가 아니라 데이터, manifest, rule table, GraphDB, evidence metadata, 승인 이력으로 관리한다.
- LLM은 최종 판단 권위가 아니라 질문 해석, 근거 요약, 표현 보조 역할을 담당한다.
- 원문 근거가 없는 판단은 확정 답변으로 만들지 않는다.
- 새 지식은 후보 상태에서 시작하고, 검증 또는 실무자 승인 후에만 운영 지식으로 승격한다.
- 모든 중요한 변경은 재현 가능한 검증 명령 또는 평가 결과와 함께 끝낸다.

## 2. 하드코딩 지식 금지

금지:

- 보험 개념, 보장/면책/감액 판단, 공제율, 한도, 필요서류, 지급 조건을 Python 상수나 질문별 분기로 확정하는 방식
- 특정 평가 문항 ID, 특정 질문 문장, 특정 사용자 예시에 맞춘 분기
- 약관 개정 시 코드를 수정해야만 값이 바뀌는 구조
- LLM이 문서에 없는 보험 지식, 의학 인과, 수치, 계산 규칙을 생성하게 하는 구조
- `if "통원" in question: return "2만원"` 같은 질문 문자열 기반 지식 반환

허용:

- 조항/표/행/열/페이지/chunk id를 가진 source evidence에서 값을 읽어오는 로직
- 일반화된 extractor, parser, validator, retriever, planner, answer builder
- 정책 파일 또는 ontology manifest에서 동의어, stopword, 위험어, 가중치, schema를 읽는 방식
- rule table 또는 approved manifest에 저장된 값을 deterministic interpreter가 실행하는 방식
- 평가 fixture에 기대값을 두고 시스템이 source evidence에서 같은 값을 찾아내는지 검증하는 방식

경계 규칙:

- 정책 파일도 지식 하드코딩이 될 수 있다. 정책 파일에는 synonym, stopword, category, weight, guardrail 같은 처리 기준을 둘 수 있지만, 특정 상품의 정답 수치와 지급 판단을 넣지 않는다.
- 테스트 fixture의 기대 정답은 허용된다. 단, production code가 fixture 값을 참조하면 안 된다.

## 3. Source Grounding

답변과 구조화 판단은 원천 근거를 따라가야 한다.

필수:

- 답변은 제공된 context, GraphDB evidence, table row evidence, approved rule table에 근거해야 한다.
- 출처는 문서명, 조항/절, 페이지, chunk id 또는 row id로 추적 가능해야 한다.
- 코드/수치/표 질의에서는 같은 행의 값인지 확인한다.
- 문서별 값이 다르면 하나로 통일하지 않고 문서별로 분리한다.
- 근거가 없으면 "제공된 문서에서 확인되지 않습니다" 또는 검토 필요 상태로 반환한다.

금지:

- 컨텍스트 밖 외부 지식으로 보험 판단을 보강하는 행위
- 문서 밖 의학 인과, 임상 상식, 외부 ontology를 전역 GraphDB에 자동 추가하는 행위
- candidate/review_required/missing 상태를 확정 근거처럼 표시하는 행위
- LLM 답변에 근거 row에 없는 숫자가 새로 생기는 것을 허용하는 행위

## 4. OCR과 인덱스 기준

일반 질의, 평가, 자동 파라미터 검증의 기본 DB 기준은 보정본 OCR 데이터 편입본이다.

규칙:

- 일반 질의에서 OCR 문서가 검색에 포함되지 않는 경로를 기본값으로 제공하지 않는다.
- 평가 명령은 목적상 예외가 아니라면 `v2_only` 또는 보정본 OCR 편입본 기준을 명시한다.
- 보정본(v2)와 원본(v1)이 함께 있을 때 최종 판단은 보정본(v2)을 우선한다.
- 원본(v1)은 수치, 코드, 고유명사 교차 확인 보조로만 사용한다.
- 보정본과 원본이 충돌하면 보정본 기준으로 답하되 충돌 사실을 표시한다.
- OCR 품질 문제가 의심되면 LLM 추론으로 메우지 말고 OCR/row/chunk provenance를 점검한다.

금지:

- 기본 OCR index와 보정본 OCR 결과를 섞은 평가 결과를 자동 파라미터 최적값의 근거로 쓰는 것
- OCR 제외 "기본 인덱스"를 일반 실무자 질의의 정상 경로로 유지하는 것
- 원본 OCR만으로 새로운 보험 판단을 만드는 것

## 5. Ontology와 GraphDB 운영

온톨로지와 GraphDB는 승인 기반 운영 지식 계층이다.

규칙:

- raw 문서, OCR, LLM enrichment에서 나온 concept, alias, relation, rule은 candidate 또는 pending 상태로 시작한다.
- 승인되지 않은 candidate concept는 운영 GraphDB의 확정 근거로 사용하지 않는다.
- active ontology와 GraphDB rebuild는 승인 또는 명시된 작업 범위 안에서만 수행한다.
- `data/ontology/concepts.json`은 base manifest이고 직접 수정은 원칙적으로 피한다.
- 승인된 후보는 merge/apply 경로를 통해 `concepts.active.json`과 GraphDB rebuild에 반영한다.
- source evidence 없는 후보는 자동 승인하지 않는다.
- 지급, 면책, 감액, 한도, 보험금 계산 rule은 개발용 자동 승인 대상에서 제외한다.
- 실무자 UI는 후보 개념, 승인 대상 표현, 참고 유사 표현, 근거, 품질 경고, 판단 기준을 사람이 읽을 수 있게 표시해야 한다.

개발용 자동 승인:

- 개발 편의를 위한 자동 승인은 운영 실무자 승인을 대체하지 않는다.
- 자동 승인은 dev-only guardrail, source evidence, low-risk type, policy validation을 모두 통과해야 한다.
- 자동 승인 결과가 0건이어도 실패로 단정하지 않고, hold/reject 원인을 진단한다.

## 6. RuleRegistry와 계산 로직

보험금 계산, 공제, 한도, 세대별 규칙은 LLM 생성이 아니라 deterministic rule layer에서 처리한다.

규칙:

- 계산 지식은 가능한 한 rule table로 분리한다.
- 계산기는 rule table을 해석하고 실행한다.
- LLM은 계산 결과를 설명할 수 있지만 계산 rule을 발명하지 않는다.
- 계산 결과는 "확정 지급 보험금"이 아니라 근거 기반 예상 또는 검토 결과로 표현한다.
- 영수증/OCR/수가코드 기반 계산은 입력 품질과 표준코드 근거를 함께 표시한다.

금지:

- 청구 항목명 문자열만 보고 코드에 박힌 공제율을 적용하는 것
- 문서/승인 rule 없이 예외 조항을 추측하는 것
- 테스트 통과만을 위해 계산식을 특수 분기하는 것

## 7. RAG와 LLM 사용 원칙

RAG 경로:

- 검색은 BM25, Chroma, RRF, reranker, GraphDB, table/row evidence를 목적에 맞게 조합한다.
- exact code, clause detail, coverage judgment, cross-doc compare는 서로 다른 retrieval profile을 사용할 수 있다.
- 자동 Top-K/temperature는 지식 체계를 바꾸지 않고 검색/생성 파라미터만 조절해야 한다.
- GraphDB source chunk, exact code chunk, 문서별 coverage chunk는 자동 cutoff보다 보존 규칙이 우선한다.

LLM 경로:

- 보험 보상/면책/한도/계산/수치 질의는 낮은 temperature를 기본으로 한다.
- 온톨로지 enrichment LLM 출력은 shadow evaluation 또는 후보 보조 정보일 뿐, 자동 운영 반영 근거가 아니다.
- LLM 모델 선택은 기능별 평가 결과에 따른다. 답변 생성 모델과 온톨로지 enrichment 모델은 별도 역할로 판단한다.
- 모델 서버 기동/종료는 작업 목적과 현재 실행 중인 프로세스 영향을 확인하고 수행한다.

금지:

- 답변 품질 문제를 근거층 점검 없이 모델 교체나 prompt 수정만으로 해결하려는 것
- LLM에게 source evidence 없이 수치, 조항, 보험 판단을 채우게 하는 것
- 외부 cloud LLM을 망분리 또는 로컬 실행 요구와 충돌하게 사용하는 것

## 8. Clause/Table Detail Lookup 규칙

조항·표 세부 질의는 chunk 요약만으로 처리하지 않는다.

규칙:

- 조항, 표, row, 숫자, facet, source chunk를 가진 evidence layer를 우선한다.
- 값은 source row에서 읽고, LLM은 표현 정리에만 사용한다.
- selected row에 없는 숫자가 답변에 나오면 coverage validation 실패로 본다.
- row evidence가 불안정하면 확정 답변 대신 근거 추출 불안정 경고를 표시한다.

권장 구조:

- `clause_detail_rows` manifest 또는 SQLite
- query facet extractor
- row retrieval/ranking
- evidence-first answer builder
- numeric/clause/table coverage validator

## 9. 평가와 검증

모든 기능 변경은 적절한 테스트 또는 재현 가능한 검증 명령과 함께 완료한다.

기본 원칙:

- 버그 수정에는 회귀 테스트를 추가한다.
- 외부 API, 네트워크, LLM, OCR, DB, 파일 시스템 의존성은 테스트에서 mock, monkeypatch, fixture로 격리한다.
- 장시간 DGX 평가가 필요한 경우 목적, 모델, DB 기준, output path를 기록한다.
- 실패한 테스트를 임의로 skip, xfail, 삭제하지 않는다.
- 테스트를 실행하지 못하면 최종 보고에 이유와 남은 위험을 명시한다.

평가 기준:

- 필수 수치 포함 여부
- 필수 조항/표/문서 근거 포함 여부
- source evidence recall
- 답변 어조와 실무자-facing 형식
- 근거 밖 단정 여부
- latency와 resource impact
- 기존 전체 pass rate 악화 여부

## 10. 데이터와 산출물 관리

원본 자료와 생성 산출물은 커밋 대상인지 항상 구분한다.

금지:

- 원본 PDF/XLSX, OCR 추출본, 대용량 백업, 모델 snapshot, secrets를 GitHub에 푸시하는 것
- `git add .` 또는 `git add -A`로 의도하지 않은 산출물을 포함하는 것
- 사용자 데이터, 상담 로그, raw DB를 임의로 커밋하는 것
- 대용량 산출물을 문서화 없이 덮어쓰는 것

허용:

- schema, script, policy file, small fixture, 재현 가능한 report 문서
- 평가 summary나 구현 보고서처럼 검토 가능한 작은 산출물
- 커밋 전 파일별 의도 확인이 끝난 변경

## 11. 보안과 비밀정보

비밀정보는 출력, 커밋, 문서화하지 않는다.

규칙:

- API key, password, token, credential, secret path의 값은 출력하지 않는다.
- 필요한 경우 키 이름만 표시하고 값은 마스킹한다.
- `.env`, secret JSON, private key, 운영 credential은 커밋하지 않는다.
- 외부 API 호출은 작업 목적상 필요한 경우에만 수행하고, 테스트에서는 mock을 우선한다.
- 망분리 또는 로컬 LLM 정책이 명시된 작업에서는 외부 LLM/API fallback을 사용하지 않는다.

## 12. Git과 DGX 운영

작업 전후에 `git status --short --branch`를 확인한다.

규칙:

- 사용자가 만들었거나 기존에 있던 변경을 되돌리지 않는다.
- 커밋은 의도한 파일만 staging한다.
- 원격 push는 원칙적으로 사용자 요청 또는 명시된 standing instruction이 있는 범위에서만 수행한다.
- DGX 메인 저장소 반영은 사용자가 승인한 프로젝트 범위 안에서 수행하되, 변경 파일 범위와 커밋 메시지를 명확히 남긴다.
- destructive command, 대량 삭제, reset, checkout revert는 명시 승인 없이는 금지한다.
- DGX에서 장시간 모델/평가 프로세스를 실행할 때는 기존 프로세스 영향과 stop 조건을 확인한다.

커밋 메시지:

```text
feat(scope): summary
fix(scope): summary
docs(scope): summary
test(scope): summary
refactor(scope): summary
```

## 13. Frontend와 사용자 경험

현재 정식 앱 경로는 FastAPI + 정적 SPA다.

규칙:

- 신규 기능 개발과 운영 검증은 FastAPI + SPA 기준으로 수행한다.
- Streamlit은 legacy 검증/참고 경로로만 남긴다.
- 사용자가 명시하지 않으면 Streamlit UI를 새 기능에 맞춰 업데이트하지 않는다.
- 일반 보험 실무자가 이해할 수 있는 문구와 화면을 우선한다.
- 고급 RAG 파라미터는 기본 화면에서 숨기거나 자동 설정으로 두고, 필요한 경우 토글/고급 설정으로 제공한다.
- 승인 UI는 코드 리터러시 없는 실무자도 판단할 수 있도록 후보 개념, 승인 대상 표현, 설명, 예시 질문, 근거, 판단 기준을 표시한다.

## 14. 문서화와 보고

복잡한 구현이나 정책 변경은 문서로 남긴다.

규칙:

- 계획 문서는 목적, 기존 근거, 적용 범위, 제외 범위, 위험, 검증 기준을 포함한다.
- 구현 보고서는 변경 파일, 핵심 변경, 검증 명령, 결과, 미검증 위험을 포함한다.
- 문서 번호는 기존 numbering을 유지한다.
- 전역 원칙 변경은 이 000번 문서를 수정하거나, 후속 문서에서 000번과의 관계를 명시한다.
- 오래된 문서의 내용이 현재 구조와 맞지 않으면 새 문서에서 "legacy" 또는 "deprecated" 상태를 명확히 표시한다.

## 15. 충돌 해결 규칙

문서나 코드가 충돌할 때는 다음 순서로 판단한다.

1. 사용자 현재 요청과 보안 정책
2. source evidence와 실제 DGX/로컬 상태
3. 이 000번 원칙 문서
4. 최신 구현 보고서와 테스트 결과
5. 오래된 명세/README

대표 충돌 정리:

- README에 Streamlit 실행 경로가 남아 있어도 신규 기능은 FastAPI + SPA를 기준으로 한다.
- 과거 문서가 기본 OCR index를 언급해도 일반 질의와 자동 파라미터 평가는 보정본 OCR 편입본을 기준으로 한다.
- 과거 문서가 특정 모델을 후보로 언급해도 최신 모델 평가와 코드 metadata가 우선한다.
- 임시 실험 결과가 좋아 보여도 source grounding, approval, regression gate를 통과하지 않으면 운영 반영하지 않는다.

## 16. 작업 전 체크리스트

- [ ] 현재 요청 범위를 벗어난 작업을 시작하지 않았는가
- [ ] 관련 코드, 테스트, 최신 문서를 먼저 확인했는가
- [ ] 보험 지식값을 코드에 직접 넣지 않았는가
- [ ] source evidence, manifest, rule table, GraphDB, policy file 중 적절한 데이터 계층을 사용했는가
- [ ] OCR 기준이 보정본 편입본인지 확인했는가
- [ ] LLM이 근거 밖 판단을 생성하지 않도록 제한했는가
- [ ] 테스트 또는 검증 명령을 수행했는가
- [ ] 실행하지 못한 검증과 남은 위험을 기록했는가
- [ ] secrets, raw 자료, 대용량 산출물, 사용자 데이터가 staging되지 않았는가
- [ ] DGX와 로컬 중 어느 저장소를 source of truth로 삼았는지 명확한가

## 17. 작업 후 체크리스트

- [ ] 변경 파일이 요청 범위와 일치하는가
- [ ] 기존 사용자 변경을 되돌리지 않았는가
- [ ] 커밋 대상 파일만 staging했는가
- [ ] 테스트 실패를 숨기지 않았는가
- [ ] 문서 또는 보고서가 필요한 작업이면 작성했는가
- [ ] DGX 반영이 필요한 작업이면 DGX 상태와 push 결과를 확인했는가
- [ ] 최종 보고에 변경 파일, 핵심 변경, 검증 결과, 남은 위험을 포함했는가
