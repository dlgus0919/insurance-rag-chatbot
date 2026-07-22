# 팀원 workspace 문서 이동 검토 보고서

## 범위

- 비교 기준: DGX 메인 앱 저장소 `docs/`의 SHA-256
- 접근 가능한 workspace에서 메인에 없던 고유 문서 55개를 보관했습니다.
- 동일 문서의 중복 발생 96건은 `MANIFEST.json`에 출처만 기록했습니다.
- 원래 workspace 파일은 삭제하지 않았습니다.
- 이 문서는 삭제 실행 전 검토용입니다.

## 삭제 후보

아래 문서는 보관본을 남긴 뒤 활성 문서 영역에서 제거해도 영향이 낮은 후보입니다.

1. `209_CODEX_SIDEBAR_RECOVERY_2026_06_10.md`
   - 개인 Codex 채팅·로컬 복구 기록이며 메인 앱 기능과 무관합니다.
2. `44_SYMPHONY_ADOPTION.md`
   - 현재 Planner·Developer·Review Team 운영 방식으로 대체된 과거 오케스트레이션 제안입니다.
3. `MOBILE_OCR_DEVELOPMENT_GUIDE.md`
   - 메인 보험 RAG 앱이 아닌 별도 모바일 OCR 앱 개발 가이드입니다.
4. `qwen80b_claim_exclusion_question_comparison.md`
   - 현재 폐기된 독립 Qwen 비교·시연 흐름의 실험 기록입니다.
5. `2차 발표 준비` 문서 2개와 발표 PDF
   - 실행·설계 문서가 아닌 발표 산출물입니다. 발표 보관이 필요하면 맥북 로컬에만 두는 편이 적절합니다.
6. `개인 개발 가이드.txt`
   - 개인 작업 절차 문서로 메인 앱의 운영·설계 문서가 아닙니다.
7. Streamlit·Local LLM 중심의 이전 아키텍처 문서 3개
   - 현재 FastAPI + 정적 SPA + DGX SGLang 구조와 달라 활성 문서로 두면 혼동을 줍니다.
8. 282~290번의 이전 UAT/MRI fixback 보고서와 2026-07-21의 이전 final-answer grounding/composite 보고서
   - 이후 메인에 반영된 최종 triage·handoff·rereview 문서로 대체된 중간 산출물입니다.

## 보관 권장

초기 설계·평가·OCR 보류 판단, DGX 이관·데이터 동기화 가이드, 설치 프로그램 검토, RBAC 보안 리뷰, FSS 사례 연계 검토, LLM Wiki 편입 제안은 향후 개발 일지와 인수인계에 참고할 가치가 있어 삭제보다 archive 보관을 권장합니다.

## 권한 보류

`eundeo`의 기존 workspace 문서 21개는 현재 계정에서 읽기 권한이 없어 복사하지 못했습니다. 목록과 권한 상태는 `BLOCKED_README.md`에 기록했습니다. 원 소유자 또는 관리자가 읽기 권한을 부여한 뒤 별도 해시 검증이 필요합니다.
