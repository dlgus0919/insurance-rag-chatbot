# 54 Chroma Batch Upsert Fix Report

## 1. 문제

`python scripts/ingest.py --include-ocr --stage all` 실행 중 ChromaDB 저장 단계에서 중단됐다.

```text
chromadb.errors.InternalError: ValueError: Batch size of 7101 is greater than max batch size of 5461
```

원인은 `VectorStore.upsert()`가 7,101개 청크를 ChromaDB에 한 번에 전달한 것이다. 현재 ChromaDB 설치 환경의 최대 upsert batch 크기는 5,461개라 이를 초과했다.

## 2. 변경 사항

- `src/retrieval/vector_store.py`
  - `DEFAULT_UPSERT_BATCH_SIZE = 1000` 추가
  - `VectorStore(..., upsert_batch_size=1000)` 기본값 추가
  - `upsert()` 내부에서 ids/embeddings/metadatas/documents를 batch 단위로 분할 저장
  - 입력 길이 불일치와 잘못된 batch size를 `ValueError`로 방어
  - empty upsert는 안전하게 no-op 처리

- `tests/test_vector_store.py`
  - fake collection 기반 batch split 단위 테스트 추가
  - 5개 입력을 batch size 2로 넣을 때 `2,2,1` 세 번으로 나뉘는지 검증

## 3. 검증

```text
pytest tests/test_vector_store.py -q
10 passed in 0.44s
```

```text
pytest -q
225 passed, 5 warnings in 1.95s
```

## 4. 재실행 가이드

청크 생성과 BM25 저장은 이미 완료됐으므로 전체를 다시 돌릴 필요는 없다. 수정 반영 후 아래 명령으로 index 단계만 재실행하면 된다.

```text
python scripts/ingest.py --include-ocr --stage index
```

주의: 현재 구조상 임베딩 캐시가 없어서 BGE-M3 임베딩은 다시 계산된다. 이전 실행 기준 약 23분 소요됐다.

## 5. Git

- Implementation commit hash: `d386df7`
- Push: 완료 (`master -> origin/master`)
