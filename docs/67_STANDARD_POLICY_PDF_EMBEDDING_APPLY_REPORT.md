# 표준약관 PDF 임베딩 반영 보고서 (2026-05-13)

## 1) 요청/목표
- 팀원 브랜치 `feature/새로운-pdf-데이터-추가` 변경을 로컬에 반영
- 새 PDF 문서 임베딩 관련 산출물 반영 후 `master` 적용

## 2) 반영 커밋
- 참조 커밋: `487522e` (`Add standard policy PDF chunks`)
- 최종 반영 커밋(로컬/원격 master): `cb80d5a` (`Add standard policy PDF chunks`)

## 3) 반영 파일
- `src/config.py`
  - `PDF_SOURCES`에 `표준약관(제5-13조제1항관련)` 소스 추가
- `tests/test_ingest.py`
  - `cloud_only=True` 선택 시 `표준약관` 포함 검증 추가
- `data/processed/chunks.jsonl`
  - 표준약관 청크 `856`개 포함 버전 반영
- `data/index/bm25.pkl`
  - 표준약관 청크 반영된 BM25 인덱스 버전 반영

## 4) 검증
- 청크 파일 확인:
  - 총 청크 수: `5,781`
  - `metadata.doc_short == "표준약관"` 청크 수: `856`
- 원격 반영:
  - `origin/master`에 `cb80d5a` 푸시 완료

## 5) 제약/비고
- 로컬에서 `scripts/ingest.py --stage index` 실행 시, HuggingFace 접근 제한으로 Chroma 임베딩 재생성이 실패함.
- 따라서 Git 관리 대상이 아닌 `data/index/chroma`는 현재 세션에서 자동 재생성 완료하지 못함.
