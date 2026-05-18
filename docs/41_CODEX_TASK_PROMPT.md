# Codex 개발자 프롬프트 — True Hybrid OCR 구현 (v41)

## 역할

당신은 이 프로젝트의 개발자입니다. 기획·검토 에이전트가 작성한 명세를 구현하고, 구현 결과를 보고서로 작성합니다.

---

## 배경

보험 문서 RAG 챗봇에서 OCR 엔진 비교 실험을 진행 중입니다.

지금까지 확인된 결과:
- **Hybrid** (PP-Structure + PaddleOCR Korean): 표 구조 ✅, 텍스트 정확도 ❌
- **CLOVA** (layout 없음): 텍스트 정확도 ✅, 표 구조 ❌, 텍스트 순서 혼재

두 엔진의 장점만 결합하는 **True Hybrid** 구현이 목표입니다.

핵심 구조:
```
preprocess_page(image)          # PP-Structure bbox + figure 마스킹
    ↓
clova_ocr_page(masked_image,    # CLOVA 텍스트 + layout_regions 기반 표 재구성
               layout_regions=prep.regions)
```

**이 두 함수는 이미 구현되어 있고 호환성이 확인되었습니다.** 새로 작성할 코드는 이를 연결하는 스크립트 뼈대뿐입니다.

---

## 구현 명세

`docs/41_CODEX_SPEC_TRUE_HYBRID.md`를 정독하고 아래 순서로 구현하세요.

### 구현 순서

1. **`run_clova_local.py` 소수 수정**
   - `_update_summary()` 에 `engine_key: str = "clova"` 파라미터 추가
   - 기존 동작 완전 유지, 기존 테스트 5개 전부 통과 필수

2. **`scripts/run_true_hybrid_local.py` 신규 작성**
   - `run_clova_local.py`의 유틸 함수들 import 재사용
   - `preprocess_page()` → `clova_ocr_page(layout_regions=prep.regions)` 연결
   - 출력: `p{page_no:03d}_true_hybrid.json` + `summary.json` engines.true_hybrid 갱신

3. **`tests/test_run_true_hybrid_local.py` 신규 작성**
   - 4개 테스트 (명세 참조), 외부 API·PP-Structure 모두 mock

4. **검증 실행**
   - `pytest -q` (전체, 회귀 포함)
   - `python -c "import scripts.run_true_hybrid_local; print('import OK')"`

---

## 보고서 작성 요구사항

구현 완료 후 `docs/41_CODEX_REPORT_TRUE_HYBRID.md`를 작성하세요.

필수 포함 항목:
1. `pytest -q` 결과
2. 로컬 실행 명령어 (복사해서 바로 실행 가능)
3. `run_clova_local.py` 수정 사항
4. 구현 시 판단 사항

---

## 주의사항

- `find_dotenv()` 사용 금지 → `Path(__file__).parent.parent / ".env"` 사용
- `figure_save_dir`: `p{page_no:03d}_true_hybrid_figures` (기존 hybrid 폴더와 분리)
- 기존 `p0{xx}_hybrid.json`, `p0{xx}_clova.json` 파일 수정 금지
- Codex 환경에서 `run_true_hybrid_local.py` 직접 실행 금지 (DNS 차단)
- `run_clova_local.py` 수정 후 기존 테스트 5개 모두 통과 확인 필수
