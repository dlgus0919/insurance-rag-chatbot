# UAT MRI 세대별 근거 정합성 운영 fixback

## 판정

보호 메인 `1c6812007eb7d24feeb512b28afe078ab770adbb`과 API-only 재기동 후 Chrome
실사용 첫 시나리오가 `P0 FAIL`이므로 후속 UAT를 중단한다.

## 재현 환경

- Chrome, 사용자 로그인 상태
- 새 API PID: `3696667`
- SGLang PID: `344387`
- 모델: `sglang:qwen3-next-80b-a3b-instruct-fp8`
- safe baseline: `safe-baseline-v1.2.0-r2`
- UI 선택: `4세대 실손` checked
- 질문: `4세대 자기공명영상진단(MRI/MRA)의 연간 보상한도는?`

## 실제 최종 말풍선

- 본문: `제공된 문서에서 4세대 실손의료보험에서의 자기공명영상진단(MRI/MRA) 연간
  보상한도에 대한 정보를 확인할 수 없습니다.`
- 기대: 자사 4세대 직접 조항의 `300만원`을 권위 근거와 함께 표시
- 구조화 검토 경로에 사용자 비노출 대상 문구가 여전히 표시됨:
  `직접 연결된 판단 조건 경로를 찾지 못했습니다.`

잘못된 5세대·무관 예시 `200만원` 확정은 fail-closed로 차단됐지만, 실제 4세대 canonical
근거도 복구하지 못했다. 또한 missing summary 제거는 본문 중복에만 적용되어 구조화 패널
자체의 사용자 노출을 해결하지 못했다.

## 원인 가설과 확인 요구

1. `load_source_metadata_lookup()`의 교차키가 정규화 본문 전체 해시와 다수 메타데이터의
   완전 일치를 요구한다. 실제 v2 재청크 행은 canonical 행과 본문 경계 또는 메타데이터가
   달라 4세대 직접 근거 alias가 만들어지지 않은 것으로 추정한다.
2. 엄격 세대 필터는 의도대로 generation-empty hit을 제거했으나, verified 4th hit이 0개가
   되어 직접 답변이 fail-closed 됐다.
3. `_strip_rendered_missing_review_summaries()`는 답변 본문만 정리한다. 구조화 패널 renderer는
   `graph_review_paths[].summary`를 그대로 표시한다.

운영 데이터와 감사 로그를 읽기 전용으로 최소 확인해 다음을 정확히 제시한다.

- 해당 UAT turn의 선택 세대와 최종 source ID/metadata
- 4세대 300만원 canonical 행과 실제 v2 indexed 행의 ID, 안정 provenance 필드, 본문 경계 차이
- 기존 데이터 계약에서 사용할 수 있는 명시적 `source_chunk_id`, 페이지/문서/offset/section 등의
  안정 연결키와 ambiguity 처리
- 구조화 패널의 실제 payload→SPA renderer 경로

민감정보와 대화 원문 전체는 출력하지 않는다.

## Developer 수정 요구

1. 새 isolated workspace/branch를 보호 메인 `1c68120`에서 생성한다. 보호 메인·서비스·운영
   데이터·Graph/ontology/safe baseline·계산 룰·push는 변경하지 않는다.
2. 실제 데이터에서 4세대 직접 근거가 연결되지 않은 지점을 RED로 고정한다.
3. exact full-text hash에만 의존하지 않는 일반 provenance 계약을 사용한다.
   - 명시적 source/canonical ID 또는 안정 문서·페이지·구간 키를 우선한다.
   - 후보가 유일하고 세대 정보가 서로 모순되지 않을 때만 보강한다.
   - 복수 후보, 세대 충돌, 근거 불명확은 계속 fail-closed 한다.
   - MRI, 4/5세대, 300/200만원, 질문 문자열 하드코딩 금지.
4. 사용자에게 표시되는 구조화 패널에서는 `status=missing`의 내부 기술 요약을 렌더하지 않는다.
   정상 검토 결과, 사용자용 추가 확인 질문, 상태 배지, 출처는 보존한다.
5. 운영 동형 fixture로 다음을 회귀 고정한다.
   - 재청크 본문 경계가 canonical과 달라도 안정 provenance로 유일 연결되는 경우
   - 복수/충돌 후보는 매핑되지 않음
   - 4세대 직접 한도는 4세대 근거만, 5세대는 5세대 근거만 사용
   - 세대 미선택·일반 보상 가능성 질의는 과도하게 차단하지 않음
   - missing summary가 최종 본문과 구조화 패널 어디에도 노출되지 않음
6. focused/관련/전체 pytest, frozen 계산/Graph hash, 보호 메인 불변을 보고한다.

## 중지 조건

후보 구현과 독립 Review PASS 전에는 보호 메인 통합·API 재기동·추가 Chrome UAT·push를
수행하지 않는다.

완료 표식:

`DEVELOPER_UAT_MRI_OPERATIONAL_FIXBACK_CANDIDATE_COMPLETE_NO_INTEGRATION_NO_PUSH`
