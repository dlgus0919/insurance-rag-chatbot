# 285. UAT 세대별 직접 조항 근거 정합성 수정 보고서

## 범위

UAT에서 선택한 실손 세대와 다른 세대의 수치 근거가 일반 질의 최종 답변에 섞이는 문제를 수정했다. 이 변경은 특정 의료행위, 세대, 금액 또는 질문 문구를 예외 처리하지 않는다.

## 원인

v2 재청크 인덱스의 식별자가 canonical 청크 식별자와 달라 원본의 `policy_generation` 메타데이터 보강이 실패했다. 기존 세대 필터는 세대 값이 비어 있는 hit을 허용하므로, 선택 세대가 있는 직접 조항 속성 질의에 근거 미확인 hit이 남을 수 있었다.

Graph의 `missing` 검토 경로 요약도 구조화 패널을 표시하는 경우 최종 본문에 다시 생성될 수 있었다.

## 수정

- 재청크된 hit을 본문 해시와 안정 메타데이터로 canonical 청크에 교차 연결해 세대 메타데이터를 보강한다. 연결이 유일하지 않거나 근거가 없으면 매핑하지 않는다.
- 선택된 세대가 있고 진단 기준, 서류, 공제, 한도, 횟수 또는 기간을 직접 조회하는 질의에서는 해당 세대가 확인된 hit만 최종 후보로 남긴다. 다른 일반 질의와 세대 미선택 질의의 기존 동작은 유지한다.
- Graph 구조화 패널의 `missing` 경로와 동일한 요약 문장만 최종 본문에서 제거한다. 정상 본문, 추가 질문, 출처 표시는 유지한다.

## 회귀 검증

RED:

- 재청크 4세대 hit와 세대 미확인 hit이 함께 남는 경계: 실패 확인.
- Graph `missing` 요약이 최종 답변 본문에 남는 경계: 실패 확인.

GREEN:

- 신규 핵심 2건: `2 passed`.
- 세대 메타데이터 보강, 엄격 세대 필터, Graph missing-summary 제거 3건: `3 passed`.
- 관련 검색/Graph/채팅/근거 평가 묶음: `168 passed, 1 warning`.
- 전체 pytest: `1156 passed, 3 warnings`.
- `git diff --check`: 통과.

## 불변 경계

다음 계산 경계는 변경하지 않았고 SHA-256이 기준값과 일치한다.

- `claim_deductible_rules.active.json`: `ab4f75c34ad3e4e1859b7a299f403eb744df6cab8fee79907aee4367e3a2a818`
- `rule_links.active.json`: `ab941d9ba6636e316f1e057d4cc388d7c99b1ce0cc1e89f4d54dd3f756ed26d9`
- `processing_policy.py`: `5a479a7020fccd7f62cdfc7327a9da339fbad1b1a29faedef4e10dd8489bf72f`

안전 기준 r2 Graph DB도 변경하지 않았으며 SHA-256은 `2b39c60cd5f8f9d936021a2bb2e1707928870719943cfad7932f81efa7aca9eb`이다.

## 미실행 및 다음 단계

보호 메인과 운영 API, LLM, GraphDB, 온톨로지, 활성 계산 룰, 사용자 대화/계정 데이터에는 쓰지 않았다. 따라서 실제 운영 UI의 최종 말풍선 확인은 후보 검토 및 별도 배포 승인 후 수행해야 한다.
