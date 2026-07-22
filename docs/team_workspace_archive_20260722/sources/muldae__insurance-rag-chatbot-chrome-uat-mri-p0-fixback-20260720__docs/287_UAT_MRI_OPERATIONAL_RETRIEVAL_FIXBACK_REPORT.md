# UAT 세대별 약관 속성 검색 보완 보고서

## 범위

- 대상: 선택된 실손 세대의 약관 속성 조회(한도, 횟수, 기간, 공제, 비율)
- 제외: 활성 계산 룰, 온톨로지, GraphDB, safe-baseline 산출물, 운영 API와 사용자 데이터
- 작업 위치: DGX 격리 workspace만 수정

## 원인과 최소 보정

UAT의 4세대 직접 한도 질의는 일반 검색 결과가 상담사례집에 치우치고, 세대별 직접 조항이 최종 후보로 회수되지 않아 답변이 비어 있었다. 5세대 읽기 전용 smoke에서는 OCR 표의 열 분할로 직접 조항의 긴 의료행위 명칭이 본문에서 연속 문자열로 남지 않았다. 그 결과 동일 명칭이 연속으로 남은 `1회` 적용 조항이 연간 금액 한도 조항보다 먼저 선택됐다.

다음의 일반 계약으로 보정했다.

1. 순수 약관 속성 조회는 모호한 의료 용어 분류보다 먼저 직접 조항 검색을 요청한다.
2. 화면 선택 또는 질문에 명시된 세대만 대상으로, 의료행위 anchor와 속성 문맥 및 수치 단위가 함께 존재하는 원문 조항을 별도 후보로 회수한다.
3. OCR 표에서 명칭이 분절된 경우에는 3개 이상 조각이 제한된 거리 안에서 순서대로 확인될 때만 같은 anchor로 인정한다. 짧은 약어에는 적용하지 않는다.
4. 금액 한도 질의는 금액 단위를, 횟수 질의는 회 단위를, 기간 질의는 기간 단위를 가진 근거만 직접 후보로 허용한다.
5. `보장되나요`, `받을 수 있나요`, `청구`, `지급`, `계산` 등 보상 판단 의도가 있으면 기존 확인 질문을 유지한다.

상품·세대·문서·청크 식별자, 금액, 특정 질문 문구를 제품 코드의 조건으로 사용하지 않았다.

## 원문 확인

- 4세대 자사 약관의 직접 조항에는 자기공명영상진단의 1년 한도 `300만원`이 존재했다.
- 5세대 표준약관의 직접 표 조항에는 같은 범주의 1년 한도 `200만원`이 존재했다.
- 5세대에서 먼저 선택되던 후보는 1회 적용 절차를 설명하는 조항이었다. 수치 단위와 OCR 분절 anchor 검증으로 직접 금액 한도 조항을 우선하도록 수정했다.

## 검증

### RED to GREEN

- OCR 분절 명칭과 `1회` 조항, 금액 한도 조항을 함께 둔 회귀가 수정 전 실패했다.
- 보정 후 동일 회귀가 통과했다.

### 집중 및 실제 v2 읽기 전용 smoke

```text
pytest tests/test_search_intent.py tests/test_pipeline.py -k policy_attribute...: 5 passed
actual v2 smoke:
  4세대 직접 한도: source 1건, 300만원 확인
  5세대 직접 한도: source 2건, 200만원 확인
  4/5세대 비교: 양쪽 세대 source 확인
  보장 여부 질의: clarification 유지
```

### 관련 및 전체 회귀

```text
Graph/API/계산/세션 관련: 173 passed, 1 warning
전체 pytest: 1165 passed, 3 warnings
Node frontend tests: 48 passed
node --check frontend/js/pages/chat.js: pass
frontend production build: pass
git diff --check: pass
```

Node의 모듈 유형 경고와 Python의 기존 deprecation 경고만 있었으며 실패는 없었다. 프런트엔드 빌드는 보호 저장소의 기존 의존성을 읽기 전용 임시 링크로 사용한 뒤 링크를 제거했다.

## 불변성 확인

```text
claim_deductible_rules.active.json
  ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818
rule_links.active.json
  ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9
processing_policy.py
  5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f
safe-baseline r2 Graph SQLite
  2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb
```

보호 메인은 기준 커밋을 유지했으며 기존 runtime SQLite WAL/SHM sidecar만 남아 있다. 운영 API, LLM, GraphDB, 온톨로지, 룰, 대화/계정/감사 데이터는 변경하지 않았다.

## 남은 위험

- 이번 검증은 실제 v2 인덱스와 원문을 읽기 전용으로 사용했지만 운영 API 요청은 사용자·대화 데이터를 만들 수 있어 실행하지 않았다.
- OCR 손상이 anchor 조각의 순서와 거리 제한을 모두 만족하지 못하는 문서는 여전히 fail-closed로 일반 검색 또는 추가 확인 경로를 따른다.
