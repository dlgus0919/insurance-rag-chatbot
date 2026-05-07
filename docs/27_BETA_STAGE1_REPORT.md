# 베타 1단계 구현 보고

## 1. 백업 결과

- 백업 위치: `/Users/june_kim/Documents/Claude/Projects/insurance_rag_backup/alpha_v1_20260507_155844`
- 체크섬 요약: `CHECKSUMS.txt`에 SHA256 1,320개 기록 완료
- 백업 폴더 크기: 1.6GB
- 백업 파일 수: 1,321개

## 2. 원본 자료 보호

- `.gitignore`에 루트 PDF/XLS/XLSX, `data/raw/`, `data/extracted/`, `backup/`, `assets.zip`, `data/chat_history/` 보호 패턴 추가
- `scripts/check_raw_assets.py` 추가: staged PDF/XLS/XLSX와 원본/민감 산출물 차단
- 임시 PDF 강제 stage 검증: 차단 확인 후 제거
- `git ls-files | grep -E '\.(pdf|xlsx|xls)$'`: 0건
- 기존 추적 PDF `BZ202603053039374.pdf`는 파일을 유지하고 Git 인덱스에서만 제거

## 3. 카탈로그 검증 결과

- D1: 1,429p, 텍스트 1,387p(97.1%), 표 1,165개/1,146p, 이미지 1,422개/1,389p
- D2: 172p, 텍스트 100%, 표 125개/70p, 이미지 37개/13p
- D3: 493p, 텍스트 100%, 표 269개/194p, 이미지 44개/17p
- D4: 281p, 텍스트 100%, 표 166개/112p, 이미지 50개/19p
- D5: 루트 원본 파일 미존재
- D6: 330p, 텍스트 0%, 이미지 330개/330p
- D7: 351p, 텍스트 0%, 이미지 351개/351p
- D8: 1개 시트(`Result 1`), 529,022 물리 행, 529,020 데이터 행, 23컬럼, `std_cd` 유니크 527,679건

## 4. 비급여 표준 모델 적재

- 산출 DB: `data/index/relational/standard_codes.sqlite`
- 테이블: `nonpay_standard`
- 원본 데이터 행: 529,020
- 적재 행: 527,679
- 중복 `std_cd` 스킵: 1,341행
- DB 크기: 217.4MB
- 적재 시간: 27.9초
- 샘플 조회: `lookup_by_std_cd("050000011")` → `D3베이스주100,000IU(콜레칼시페롤)_(2.5mg/1mL)`

## 5. 메타 스키마 확장

- `PdfSource` 옵션 필드 추가: 보험사, 자사 여부, 상품명/유형, 시행일, 버전, OCR 필요 여부
- 청크 메타 옵션 필드 추가: `insurance_company`, `is_own_company`, `product_name`, `product_type`, `effective_date`, `version`, `coverage_category`, `clause_type`, `content_type`, `source_method`, `confidence`, `bbox`, `linked_std_cds`
- 기본값: `content_type="text"`, `source_method="native"`, 나머지는 `None`
- JSONL 라운드트립 테스트 통과

## 6. 신규 자료 등록

- D3 `자사_SOL건강`, D4 `자사_SOL운전자`, D6 `실무가이드`, D7 `상담사례집`을 `PDF_SOURCES`에 등록
- D8 비급여 표준 모델을 `SPREADSHEET_SOURCES`에 등록
- 실제 신규 PDF 인덱싱, OCR, GraphDB 구축은 수행하지 않음

## 7. 회귀 테스트

- `pytest -q --ignore=tests/test_vector_store.py`: 125 passed, 5 warnings
- `pytest -q tests/test_standard_codes.py`: 2 passed
- `python scripts/check_raw_assets.py`: 통과
- 보안 문자열 점검: API 키 접두어·비밀번호 해시 패턴 검색 결과 0건
- Streamlit 부팅: `streamlit run src/ui/streamlit_app.py --server.headless true --server.port 8501` 후 `curl http://localhost:8501` HTML 응답 확인

## 8. 다음 단계 권고

- D5 `보상가이드북.pdf` 원본 확보 여부 확인
- D6 `cloud_safe` 정책과 D7 외부 공시 출처 확정
- 다음 명세에서 D3·D4 신규 약관 인덱싱과 D6·D7 OCR 파이프라인을 분리 착수

## 9. GitHub 반영

- 구현 변경은 커밋 후 `master` 브랜치에서 `origin/master`로 푸시한다.
- 원본 PDF/XLSX와 SQLite 산출 DB는 Git 추적 대상에서 제외한다.
