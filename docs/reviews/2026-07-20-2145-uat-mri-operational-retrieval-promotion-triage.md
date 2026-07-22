# UAT MRI 운영 검색 보완 — 보호 메인 승격 triage

## 승인 근거

- 최종 Review PASS: `docs/reviews/2026-07-20-214057-uat-mri-operational-retrieval-fixback3-rereview.md`
- 보호 메인 기준: `ba3426eb8b75eabb8be5d1c6e3d8c64195470d59`
- 적용 후보(순서 고정):
  1. `53f658344dbb79d248a532b8109194b28a2f125b`
  2. `14f68c7f09228d0ccc69426b7a936115bfb1041b`
  3. `a988ef14ce988dfb1163b1897ba740e4249c8169`

## 허용 작업

1. 보호 메인의 현재 HEAD·clean 범위와 운영 프로세스 PID·health·model·불변 해시를 먼저 기록한다.
2. 위 세 커밋만 순서대로 cherry-pick한다. 충돌 또는 예상 외 변경이 있으면 즉시 중단한다.
3. 임시 DB·lock 경로로 focused, 관련, 전체 Python, 전체 Node, syntax, production build, diff-check를 수행한다.
4. 검증 통과 후 API 서비스만 표준 절차로 재기동한다. SGLang PID는 유지한다.
5. 재기동 후 health/model/PID와 frozen rule/manifest/processing policy/Graph SHA, 운영 DB 본체를 다시 확인한다.

## 금지

- push 금지
- SGLang 재기동 금지
- GraphDB/온톨로지 재빌드 금지
- active rule/manifest 변경 금지
- 운영 DB·사용자·대화·감사 데이터 수동 변경 금지
- WAL/SHM 수동 삭제 금지

## 중단 조건

- 보호 메인이 `ba3426e...`가 아니거나 예상 외 tracked 변경 존재
- cherry-pick 충돌 또는 후보 외 파일 포함
- focused/관련/전체 검증 실패
- SGLang PID 변경, health/model 이상, frozen hash/DB 본체 변경

완료 marker:

`DEVELOPER_UAT_MRI_RETRIEVAL_PROMOTION_COMPLETE_NO_PUSH`
