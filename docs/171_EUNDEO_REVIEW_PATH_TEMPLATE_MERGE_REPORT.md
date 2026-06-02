# 171. Eundeo Review Path Template Merge Report

작성일: 2026-06-02

## 목적
`eundeo` 워크스페이스의 `Review_path` 브랜치에서 구현된 review path 답변 템플릿 개선을 최신 `master` 기준 GraphRAG/명확화 UX 구조에 맞게 편입했다.

## 반영 범위
- `graph_summary` 4섹션 요약 생성 추가
- Graph context에서 candidate/후보 신뢰도 항목의 확정 섹션 격리 강화
- API payload에 `graph_summary` 직렬화 추가
- 채팅 UI에 4섹션 summary 렌더링 및 스타일 추가
- review path 4섹션 완전성 평가 함수와 회귀 테스트 추가

## 주의한 점
- 최근 `clarification` 상태 동기화 수정과 충돌하지 않도록, 되묻기 관련 프론트 로직은 건드리지 않았다.
- `eundeo` 커밋에 포함된 배포 가이드, 로그인/시스템 상태, provider 기본값 변경은 이번 편입 범위에서 제외했다.
- `src/llm/prompt.py`에는 4섹션 응답 규칙만 최소 범위로 추가했다.

## 검증 계획
- Python 문법 검증
- JS 문법 검증
- Graph context / payload / evaluator / API chat 관련 pytest 실행
- `git diff --check`
