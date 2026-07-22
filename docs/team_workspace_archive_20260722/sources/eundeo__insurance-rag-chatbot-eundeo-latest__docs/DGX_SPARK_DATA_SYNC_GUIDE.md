# DGX Spark 데이터 보정본 적용 가이드

## 목적

팀원들이 각자 MacBook에서 DGX Spark를 연결해 작업하되, 원본 데이터는 GitHub에 올리지 않고 보정 완료된 데이터만 메인 서버인 DGX Spark에 안전하게 반영하기 위한 작업 흐름을 정리한다.

## 기본 원칙

```text
GitHub = 코드 관리
DGX Spark = 데이터 저장 / 통합 / 학습 / 서비스 실행
MacBook = 개인 작업 공간
```

GitHub에는 코드와 문서만 업로드하고, 원본 데이터와 보정본 데이터는 업로드하지 않는다.

## GitHub에 올리는 항목

- Python 코드
- 데이터 처리 스크립트
- 설정 파일 템플릿
- 실행 방법 문서
- `.gitignore`

## GitHub에 올리지 않는 항목

- 원본 데이터
- 보정본 데이터
- 개인정보 또는 민감 정보
- 모델 파일
- 대용량 결과물

예시 `.gitignore`:

```gitignore
data/
raw_data/
corrected_data/
outputs/
models/
*.csv
*.xlsx
*.parquet
*.pt
*.bin
```

## 전체 작업 흐름

```text
1. GitHub에서 최신 코드 받기
2. MacBook에서 데이터 보정 작업
3. 보정본을 corrected_data/에 저장
4. rsync 또는 scp로 DGX Spark 서버에 업로드
5. DGX Spark에서 검증 스크립트 실행
6. 통합 스크립트로 final_data/에 반영
7. 학습 또는 서비스 실행
```

## MacBook에서 보정 작업

각 팀원은 본인의 MacBook에서 원본 데이터를 받아 보정 작업을 진행한다.

예시 폴더 구조:

```text
project/
  scripts/
  corrected_data/
    my_result_file.csv
```

보정이 완료된 파일은 `corrected_data/` 폴더에 따로 정리한다.

## DGX Spark 서버로 보정본 업로드

보정 완료 파일은 GitHub가 아니라 DGX Spark 메인 서버로 직접 업로드한다.

### scp 사용

```bash
scp -r corrected_data/ username@DGX_SPARK_IP:/path/to/project/corrected_data/사용자이름/
```

### rsync 사용

`rsync`는 변경된 파일만 전송하므로 반복 업로드에 더 적합하다.

```bash
rsync -avz corrected_data/ username@DGX_SPARK_IP:/path/to/project/corrected_data/사용자이름/
```

예시:

```bash
rsync -avz ./corrected_data/ kim@192.168.0.10:/home/project/corrected_data/kim/
```

## DGX Spark 서버 권장 폴더 구조

팀원별 업로드 폴더를 분리해 충돌을 방지한다.

```text
/project/
  scripts/
    validate_corrected_data.py
    merge_corrected_data.py

  corrected_data/
    user_a/
    user_b/
    user_c/

  final_data/
```

각 팀원은 본인 이름 또는 계정명으로 된 폴더에만 보정본을 업로드한다.

## 검증 및 통합

DGX Spark 서버에서 보정본을 검증한 뒤 최종 데이터에 반영한다.

예시:

```bash
python scripts/validate_corrected_data.py
python scripts/merge_corrected_data.py
```

권장 흐름:

```text
팀원별 보정본 업로드
        ↓
데이터 형식 검증
        ↓
중복 / 누락 / 오류 확인
        ↓
최종 데이터로 병합
        ↓
학습 또는 서비스에 반영
```

## 충돌 방지 규칙

- 각자 본인 폴더에만 업로드한다.
- 최종 데이터 폴더는 직접 수정하지 않는다.
- 최종 병합은 담당자 또는 자동 스크립트가 수행한다.
- 파일명에 날짜, 작업자명, 버전을 포함한다.
- 업로드 후 검증 스크립트를 반드시 실행한다.

파일명 예시:

```text
claims_corrected_kim_2026-05-18_v1.csv
claims_corrected_lee_2026-05-18_v1.csv
```

## 추천 업로드 명령어

```bash
rsync -avz ./corrected_data/ username@DGX_SPARK_IP:/서버/프로젝트경로/corrected_data/내이름/
```

이 방식은 원본 데이터를 GitHub에 올리지 않으면서도, 각자 작업한 보정본을 안전하게 DGX Spark 메인 서버에 반영할 수 있다.
