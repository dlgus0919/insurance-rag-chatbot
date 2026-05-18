# Codex 개발자 프롬프트 — CLOVA OCR 로컬 실행 스크립트 (v40)

## 역할

당신은 이 프로젝트의 개발자입니다. 기획·검토 에이전트가 작성한 명세를 구현하고, 구현 결과를 보고서로 작성합니다.

---

## 배경

보험 문서 RAG 챗봇 프로젝트에서 OCR 비교 파이프라인을 구축 중입니다.

이전 태스크(39번)에서 `scripts/ocr_compare.py --engines all`을 실행했으나 **CLOVA OCR이 11개 페이지 전부 SKIPPED**되었습니다.

원인: Codex 실행 환경(클라우드 샌드박스)에서 NAVER Cloud API Gateway(`ea1lfq3tos.apigw.ntruss.com`) DNS 해석이 차단됨.

**이번 태스크**: 사용자가 로컬 Mac에서 직접 CLOVA API를 호출해 결과를 저장하는 독립 스크립트를 작성합니다.

---

## 구현 명세

`docs/40_CODEX_SPEC_OCR_CLOVA_LOCAL.md`를 정독하고 아래 순서로 구현하세요.

### 구현 순서

1. **`scripts/run_clova_local.py` 신규 작성**
   - `--doc`, `--pages`, `--output-dir`, `--timeout` CLI 인수
   - 기존 `p0{xx}_original.png` 파일을 읽어 `clova_ocr_page()` 호출
   - 결과를 `p0{xx}_clova.json`으로 저장 (명세의 스키마와 동일)
   - 완료 후 `summary.json` CLOVA 섹션 업데이트
   - `find_dotenv()` 사용 금지 — `Path(__file__).parent.parent / ".env"` 사용

2. **`tests/test_run_clova_local.py` 신규 작성**
   - `_block_quality()`, `_header_score()`, `_update_summary()`, `parse_pages()` 단위 테스트

3. **검증 실행**
   - `pytest tests/test_run_clova_local.py -q`
   - `pytest -q` (전체)
   - `python -c "import scripts.run_clova_local; print('import OK')"`

---

## 보고서 작성 요구사항

구현 완료 후 `docs/40_CODEX_REPORT_CLOVA_LOCAL.md`를 작성하세요.

**필수 포함 항목:**

1. `pytest -q` 결과 (전체 통과 수)

2. 사용자가 복사해서 바로 실행할 수 있는 명령어:
   ```bash
   python scripts/run_clova_local.py --doc 실무가이드 --pages 60-70
   ```

3. 실행 결과 예상 출력 형식

4. 구현 시 판단 사항

---

## 주의사항

- Codex 환경에서 `run_clova_local.py`를 실제로 실행하지 말 것 — DNS 차단으로 모두 실패함
- 기존 `src/parser/clova_ocr.py`의 `clova_ocr_page()` 함수를 그대로 사용할 것 — 새로 API 호출 코드 작성 금지
- 기존 `p0{xx}_clova.json` 파일은 Codex가 덮어쓰지 말 것 — 스크립트 작성만 하고 실행은 사용자가 로컬에서 함
- HTML 결과지 재생성은 이번 범위 외
