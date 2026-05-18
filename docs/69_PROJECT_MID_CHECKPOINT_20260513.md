# 69_PROJECT_MID_CHECKPOINT_20260513

작성일: 2026-05-13  
기준 커밋: `d4df1c4` (Improve OCR quality: table downcast, noise filtering, and remainder split)

## 1) 현재 진행 상황 요약

최근 OCR/RAG 관련 핵심 진행 상태:

- OCR 파이프라인/보정 계열
  - CLOVA Native 중심 워크플로우 정립
  - 수술종수 Vision 후보정(숫자 셀 refiner) 및 규칙 보강 반영
  - 단어 순서/라인 분리 이슈(#50~#51) 반영
  - N-value guard 및 all-N 수술행 방어(#65) 반영
  - **신규 반영(#68): table false-positive 억제 + 노이즈 텍스트 필터 + remainder 분리 강화**
- RAG 품질 계열
  - 수술명 기반 row boost, structured context 주입(A/B), C hook(TableStore)까지 반영
  - Parquet 기반 수술종수/장해율 인덱스 구축(spec #60)
- 평가/검증
  - 최근 코드 기준 전체 테스트: `pytest -q` → **255 passed**

## 2) 이번 턴 적용 내용(#68) 점검

- 표 오검출 억제
  - table 품질 평가 후 약한 표를 text로 다운캐스트
  - 메타: `downcast_from_table`, `downcast_reason`
- 텍스트 노이즈 제거
  - 숫자/기호-only 짧은 라인, 장식성 영문 라인(`Shares`, `Year` 등) 제거
  - OCR 저장 단계 + 청킹 단계 공통 적용
- remainder 분리 안정화
  - Y-gap + 들여쓰기 변화 기준으로 문단 분리 강화

정량 자체검토(기존 `data/extracted` 기준 휴리스틱 적용 집계):

- `상담사례집`: table 223 중 downcast 후보 148
- `실무가이드`: table 317 중 downcast 후보 10

해석: 상담사례집의 표 오검출 개선 여지가 크며, 실무가이드는 핵심 표 보존에 유리한 보수적 적용 범위.

## 3) Codex 환경에서 미실행/차단된 항목

1. 샘플 OCR 재실행(CLOVA API 호출)
- 사유: Codex 실행 환경의 외부 API data egress 정책 차단
- 영향: 코드 적용 후 실제 OCR 산출물 재생성/비교는 사용자 로컬 터미널에서 수행 필요

2. 장시간 전체 재빌드/평가
- 사유: 실행 시간 장기(수십 분~수시간)
- 영향: 야간 배치 또는 수동 실행 권장

## 4) 사용자 터미널 실행 가이드 (권장 순서)

아래 명령은 프로젝트 루트에서 실행:

```bash
cd "/Users/june_kim/Documents/Claude/Projects/보험 문서 RAG 챗봇"
```

### A. 빠른 회귀 확인 (필수)

```bash
pytest -q
```

### B. 샘플 페이지 OCR 재실행 (권한 차단 대체 검증)

권장 샘플: 실무가이드 `p064,p074`, 상담사례집 `p044,p220`

```bash
caffeinate -dimsu python scripts/run_full_ocr.py \
  --doc 실무가이드 \
  --pages 64,74 \
  --force \
  --yes 2>&1 | tee logs/ocr_sample_실무가이드_$(date +%Y%m%d_%H%M%S).log

caffeinate -dimsu python scripts/run_full_ocr.py \
  --doc 상담사례집 \
  --pages 44,220 \
  --force \
  --yes 2>&1 | tee logs/ocr_sample_상담사례집_$(date +%Y%m%d_%H%M%S).log
```

### C. 샘플 시각 비교 HTML 생성

```bash
python scripts/generate_ocr_image_compare_html.py \
  --doc 실무가이드 \
  --pages 64,74 \
  --output reports/ocr_compare_midcheck_실무가이드.html

python scripts/generate_ocr_image_compare_html.py \
  --doc 상담사례집 \
  --pages 44,220 \
  --output reports/ocr_compare_midcheck_상담사례집.html
```

### D. 인제스트/인덱스 재생성 (필요 시)

전체 OCR 포함 청킹+인덱스:

```bash
caffeinate -dimsu python scripts/ingest.py --include-ocr --stage all \
  2>&1 | tee logs/ingest_all_ocr_$(date +%Y%m%d_%H%M%S).log
```

이미 청킹이 끝났다면 index만:

```bash
caffeinate -dimsu python scripts/ingest.py --include-ocr --stage index \
  2>&1 | tee logs/ingest_index_ocr_$(date +%Y%m%d_%H%M%S).log
```

### E. 평가 (장시간)

OCR 평가:

```bash
caffeinate -dimsu \
env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ENABLED=false \
python scripts/eval.py --ocr 2>&1 | tee logs/eval_ocr_$(date +%Y%m%d_%H%M%S).log
```

스모크 평가:

```bash
python scripts/eval.py
python scripts/eval.py --v2
```

## 5) 다음 의사결정 포인트

1. 샘플 OCR 재실행 후 `상담사례집`에서 table downcast가 과도하면 임계치 완화 필요  
2. 샘플 결과가 양호하면 weekend 자동화에서 배치당 검증 항목에 `downcast_from_table` 집계를 추가  
3. 이후 full OCR 재실행 시점에 맞춰 인제스트/평가를 한 번에 실행해 지표 확정

