# M10 최종 평가 결과

작성일: 2026-05-04

## 요약

- 대상 범위: M8(LLM 설정/프롬프트), M9(코드 라우팅/reranker), M10(코드 테이블 메타데이터/재인덱싱)
- 최종 인덱스: 심평원 2,286청크 + 약관 384청크 = 2,670청크
- 보상가이드북: `보상가이드북.pdf` 파일 없음으로 건너뜀
- 최종 자동 평가: `retrieval recall@8 = 1.000`, `출처 페이지 정확도 = 1.000`
- Streamlit 기동 smoke: `streamlit run src/ui/streamlit_app.py --server.headless true --server.port 8505` 정상 기동 확인

## 재인덱싱 결과

```text
[M6] 멀티 문서 PDF 파싱 시작
[M6] PDF 파싱: 심평원 (BZ202603053039374.pdf)
[M6] 심평원: 전체 1429페이지, 텍스트 1387페이지
[M6] 심평원: 2,286 청크
[M6] PDF 파싱: 약관 (2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf)
[M6] 약관: 전체 172페이지, 텍스트 172페이지
[M6] 약관: 384 청크
[M10] 보상가이드북 파일 없음, 건너뜀: 보상가이드북.pdf
[M6] 청킹 완료: data/processed/chunks.jsonl
[M6] 문서별 청크 수: 심평원=2,286
[M6] 문서별 청크 수: 약관=384
[M6] 전체 청크 수: 2,670
[M6] 평균 길이: 596.2자
[M6] 코드 포함 청크: 1,716개 (64.3%)
[M2] 문서 임베딩 완료: (2670, 1024)
[M2] ChromaDB 저장 완료: data/index/chroma
```

## eval.py 콘솔 출력

명령:

```bash
RERANKER_ENABLED=false python scripts/eval.py
```

결과:

```text
[01] code recall=OK page=OK code=OK top_pages=['101', '80', '100']
[02] code recall=OK page=OK code=OK top_pages=['100', '80', '100']
[03] code recall=OK page=OK code=OK top_pages=['101', '109', '103']
[04] code recall=OK page=OK code=OK top_pages=['107', '111', '86']
[05] code recall=OK page=OK code=OK top_pages=['115', '114', '919']
[06] semantic recall=OK page=OK code=OK top_pages=['80', '81', '923']
[07] semantic recall=OK page=OK code=OK top_pages=['81', '80', '78']
[08] semantic recall=OK page=OK code=OK top_pages=['101', '100', '101']
[09] semantic recall=OK page=OK code=OK top_pages=['95', '1022', '96']
[10] semantic recall=OK page=OK code=OK top_pages=['76', '289', '413']
[11] code recall=OK page=OK code=OK top_pages=['36-38', '78-84', '78-84']
[12] code recall=OK page=OK code=OK top_pages=['442', '821', '438']
[13] cross_doc skipped(가이드북 미인덱싱)
[14] semantic recall=OK page=OK code=OK top_pages=['69-70', '71-78', '69']
[15] semantic recall=OK page=OK code=OK top_pages=['66-69', '39-40', '8-31']
retrieval recall@8: 1.000
출처 페이지 정확도: 1.000
skipped: 1
```

## 문항별 Pass/Fail

| 번호 | 유형 | 질문 요약 | Recall | 페이지 | 코드 | 판정 |
|---:|---|---|---|---|---|---|
| 01 | code | AA157 초진 진찰료 | OK | OK | OK | PASS |
| 02 | code | AA154 의원 초진 점수 | OK | OK | OK | PASS |
| 03 | code | 10200 한의원 진찰료 | OK | OK | OK | PASS |
| 04 | code | AD100 무균치료실 | OK | OK | OK | PASS |
| 05 | code | AQ200 임종실 입원료 | OK | OK | OK | PASS |
| 06 | semantic | 진찰료 산정 | OK | OK | OK | PASS |
| 07 | semantic | 동일 의사 여러 상병 | OK | OK | OK | PASS |
| 08 | semantic | 재진 야간/공휴일 가산 | OK | OK | OK | PASS |
| 09 | semantic | 가정간호 별도 산정 | OK | OK | OK | PASS |
| 10 | semantic | 상급종합병원 종별가산율 | OK | OK | OK | PASS |
| 11 | code | N39.3 보상 여부 | OK | OK | OK | PASS |
| 12 | code | 식도조루술 코드 | OK | OK | OK | PASS |
| 13 | cross_doc | 식도조루술 코드+가이드북 | SKIP | SKIP | SKIP | 가이드북 미인덱싱 |
| 14 | semantic | 3대비급여 항목 | OK | OK | OK | PASS |
| 15 | semantic | 본인부담금 상한제 환급 | OK | OK | OK | PASS |

## Streamlit Q1-Q5 재검증 결과

검증 방법:

- Streamlit 서버 기동 smoke를 먼저 확인했습니다.
- Q1-Q5 답변 품질은 Streamlit UI와 동일한 `RagPipeline.answer()` 경로로 실행해 확인했습니다.
- Reranker는 최초 모델 로딩 지연을 피하기 위해 `RERANKER_ENABLED=false`로 비활성화했습니다. 코드 라우팅, 청킹, 출처 보강 로직은 동일하게 적용됩니다.

| 시나리오 | 질문 요약 | 확인 결과 | 판정 |
|---|---|---|---|
| Q1 | AA157 기관/점수 | `상급종합병원`, `255.79점`, `심평원 p.101` 포함 | PASS |
| Q2 | N39.3 보상 여부 | `N39.3`, `요실금`, `보상 불가`, 약관 출처 포함 | PASS |
| Q3 | 식도조루술 코드 | `Q2333` 포함, 심평원 출처 포함 | PASS |
| Q4 | 3대비급여 항목 | `도수치료`, `체외충격파치료`, `증식치료` 포함, 약관 p.69-70 출처 포함 | PASS |
| Q5 | 도수치료 보상 한도 | `350만원`, `50회`, 약관 p.71-78 출처 포함 | PASS |

## 이전 Alpha v1 결과와 비교

| 항목 | Alpha v1 | M10 |
|---|---:|---:|
| Q1-Q5 기능 검증 | 2/5 | 5/5 |
| retrieval recall@8 | 1.000 | 1.000 |
| 출처 페이지 정확도 | 0.714~0.786 구간 | 1.000 |
| Q3 식도조루술 | R3200 오반환 가능 | Q2333 포함 |
| Q4 3대비급여 항목 | 정의 중심 답변 | 항목 열거 포함 |

## 특이사항

- `RERANKER_ENABLED=true`가 기본값이지만, 로컬 평가에서는 BGE reranker 최초 로딩 지연이 길어 `false`로 평가했습니다.
- 보상가이드북이 아직 없으므로 cross-doc 문항 13은 정상적으로 skip 처리했습니다.
- `scripts/ingest.py --stage all`은 Chroma 컬렉션을 리셋한 뒤 새 `is_code_table` 메타데이터를 반영해 재저장합니다.
