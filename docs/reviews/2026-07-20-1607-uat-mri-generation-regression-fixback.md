# UAT MRI 세대별 한도 회귀 fixback

## 판정

Review Team 판정: `CHANGES_REQUESTED`

후보 `e5156781f878c00db6a6dfc0b0f96521af7c6b9d`는 핵심 기능 회귀를 통과했으나, 최종 답변 정리 정규식이 정상 사용자 텍스트까지 삭제할 수 있어 보호 메인 통합이 불가하다.

## 재현 결함

- 위치: `src/api/rag_service.py`의 내부 경로 표식 정리
- 입력: `약어는 【mri】로 표기됩니다.`
- 현재 출력: `약어는`
- 원인: `【[a-z][a-z0-9_]*】`가 실제 내부 review path가 아닌 일반 소문자 토큰까지 매칭하고, 해당 표식 뒤 텍스트를 버린다.

## 최소 수정 요구

1. 기존 격리 workspace와 브랜치에서만 후속 커밋을 만든다.
2. 제거 대상은 실제 내부 Graph review path 이름으로 제한한다.
   - 우선안: 알려진 review path 집합 또는 `_review` 접미사를 가진 내부 식별자만 허용
   - `【mri】`, `【note】` 등 정상 토큰은 그대로 보존
3. 기존 `【claim_condition_review】`, `【generation_rule_review】` 및 단독 `---` 제거 동작은 유지한다.
4. 표식이 문장 중간에 있더라도 정상 선행·후행 사용자 텍스트를 임의로 자르지 않는 계약을 명시적으로 테스트한다.
5. 기존 4세대 300만원, 5세대 200만원, 비교, 보상 가능성 변형, 최종 내부 문구 미노출 회귀를 유지한다.
6. 전체 회귀는 기존 결과를 재사용하되 변경된 정리 함수 관련 focused/상위 회귀를 다시 실행한다. 전체 pytest는 최종 후보에서 1회만 실행한다.

## 금지 사항

- MRI/세대/금액/UAT 문장 하드코딩
- 보호 메인 통합·커밋·push
- 운영 API/LLM 재기동
- active 계산 룰, rule links, ontology/GraphDB, safe baseline 변경
- 운영 사용자 데이터 쓰기

## 완료 보고

- 새 후보 HEAD와 부모
- 변경 파일 및 diff 범위
- RED/GREEN 회귀 결과
- 관련/전체 회귀 결과
- frozen hash와 보호 메인 비변경 상태

완료 표식: `DEVELOPER_UAT_MRI_GENERATION_REGRESSION_FIXBACK_COMPLETE_NO_INTEGRATION_NO_PUSH`
