# 55 OCR 포함 인덱싱 완료 보고서

## 1. 실행 명령

```text
python scripts/ingest.py --include-ocr --stage index
```

직전 실패 원인이었던 ChromaDB batch size 초과 문제는 `VectorStore.upsert()` batch 분할 수정 후 해결됐다.

## 2. 실행 결과 요약

- 청크 로드: `7,101개`
- BM25 저장: 성공
- 임베딩 모델: `BAAI/bge-m3`
- 임베딩 결과: `(7101, 1024)`
- 임베딩 소요: `1305.1초`
- ChromaDB 저장: 성공
- 전체 index 단계 소요: `1343.3초`

샘플 질의 `재진 진찰료`에 대해 Dense/BM25 모두 심평원 진찰료 관련 chunk를 반환했다.

## 3. 문서별 인덱스 검증

`scripts/check_cloud_index.py`로 `chunks.jsonl`, ChromaDB, BM25 카운트를 대조했다.

| 문서 | chunks.jsonl | ChromaDB | BM25 |
|---|---:|---:|---:|
| 심평원 | 2,286 | 2,286 | 2,286 |
| 약관 | 384 | 384 | 384 |
| 가이드북 | 0 | 0 | 0 |
| 자사_SOL건강 | 1,494 | 1,494 | 1,494 |
| 자사_SOL운전자 | 761 | 761 | 761 |
| 실무가이드 | 995 | 995 | 995 |
| 상담사례집 | 1,181 | 1,181 | 1,181 |

검증 결과:

```text
[missing cloud vectors]
None
```

## 4. 판단

OCR 스캔본 2종(`실무가이드`, `상담사례집`)을 포함한 총 6개 문서가 ChromaDB와 BM25에 정상 반영됐다. 현재 로컬 검색 인덱스는 OCR 포함 최신 상태다.

## 5. 후속 작업

- Streamlit 앱에서 OCR 문서 질의 QA
- 필요 시 최신 `data/index/chroma`, `data/index/bm25.pkl`, `data/processed/chunks.jsonl`을 배포용 자산으로 패키징
- `실무가이드` unresolved 수술종수 셀 133건은 별도 수동 검토 가능
