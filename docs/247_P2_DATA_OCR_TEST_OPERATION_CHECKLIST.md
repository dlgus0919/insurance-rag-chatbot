# 247. P2 데이터/OCR 테스트 운영 체크리스트

작성일: 2026-06-18

## 1. 저장공간 정리 경계

- 이 단계는 읽기 전용 인벤토리만 제공한다.
- 데이터, 인덱스, DB 파일, 모델 파일, workspace archive 삭제는 별도의 명시적 승인이 필요하다.
- 운영 인덱스, 온톨로지 manifest, review log, 승인된 rule table, active DB 파일은 보존 대상이다.
- `.git` pack 크기 감축은 별도 이력 관리 프로젝트로 다룬다.

## 2. 병원 영수증 OCR 경계

- 온디바이스 OCR 산출물만으로 자동 보험금 계산을 확정하지 않는다.
- 검증된 OCR row도 row provenance, bbox, row id, 산식, 금액 검증을 모두 통과한 경우에만 보험금 계산 입력 초안이 될 수 있다.
- 실패하거나 불확실한 row는 human review task로 남긴다.
- UI와 보고서에서는 승격된 row를 `draft` 또는 `review helper`로 표현하고, 보험금 계산 완료로 표현하지 않는다.
- LLM은 누락된 영수증 번호, 금액, 청구 가능액을 이미지 맥락으로 추론하거나 생성하지 않는다.

## 3. 온톨로지와 규칙 지식 경계

- OCR에서 파생된 용어, alias, 관계 후보, rule 후보는 pending 후보로 시작한다.
- 보험 지식에 영향을 줄 수 있는 후보는 policy 파일에 조용히 승격하기보다 실무자 승인 흐름을 우선한다.
- active ontology 또는 rule table에 반영하기 전 source evidence와 승인 상태가 확인 가능해야 한다.

## 4. 테스트 명령 그룹

기본 로컬 확인:

```bash
.venv/bin/python -m pytest -m "not llm and not dgx and not slow" -q
```

일반 전체 suite:

```bash
.venv/bin/python -m pytest -q
```

OCR 전용 확인:

```bash
.venv/bin/python -m pytest -m "ocr" -q
```

LLM/DGX runtime smoke:

```bash
.venv/bin/python -m pytest -m "llm or dgx or slow" -q
```

LLM/DGX runtime smoke는 필요한 모델 서버, DGX 경로, runtime 데이터가 의도적으로 준비된 경우에만 실행한다.
