# 보안 및 관리자/직원 권한 범위 리뷰

- 작성일: 2026-07-01
- 작업 브랜치: `ihyun`
- 기준 버전: `origin/master` 최신 커밋 `f5dbfb5` 병합 후 리뷰
- 리뷰 범위: FastAPI 인증/인가, 관리자 API, 직원 세션 격리, 프론트엔드 관리자 접근 제어, 운영 보안 설정

## 요약

현재 서버 권한 구조는 `users.json` 사용자 저장소, HttpOnly 쿠키 기반 JWT, `require_permission()` 의존성으로 구성되어 있다. 직원 권한은 채팅/보험금 계산/본인 세션 조회·삭제·내보내기로 제한되고, 관리자 API는 서버 라우트에서 권한 의존성을 통해 보호된다.

직원이 관리자 API를 직접 호출하거나 다른 직원의 채팅 세션을 조회하는 명확한 우회 경로는 발견하지 못했다. 다만 운영 보안 측면에서 기본 JWT 시크릿 허용, 공개 시스템 상태 API의 내부 정보 노출, 토큰 폐기/회전 부재는 개선 권고 대상이다.

## 권한 범위 현황

| 역할 | 허용 범위 | 제한 범위 | 근거 코드 |
| --- | --- | --- | --- |
| `admin` | 채팅, 세션, 관리자 로그/통계/시스템 진단/사용자 관리 | 없음 | `src/api/security.py` `ROLE_PERMISSIONS` |
| `employee` | 채팅 스트림, 보험금 계산, 본인 세션 읽기/삭제/내보내기 | 관리자 로그/통계/사용자 관리/감사 데이터 접근 불가 | `src/api/security.py`, `src/api/routes/sessions.py` |
| `viewer` | 본인 세션 읽기/내보내기 | 채팅 생성/삭제, 관리자 기능 불가 | `src/api/security.py` |

### 확인된 보호 장치

- 관리자 API는 `require_permission("admin.*")` 또는 `require_permission("admin.users.manage")`로 보호된다.
- 세션 목록, 메시지 조회, 삭제, 내보내기는 모두 `ChatSession.user_id == 현재 사용자` 조건을 통과해야 한다.
- 채팅/보험금 계산에서 전달된 `session_id`도 현재 사용자 소유가 아니면 기존 세션을 재사용하지 않고 새 세션을 만든다.
- 비활성/잠김 사용자는 `current_user()`에서 차단된다.
- 관리자 본인 계정 또는 마지막 활성 관리자 계정을 비활성화/강등/삭제하지 못하도록 보호한다.
- 로그인 실패, 로그인 성공, 채팅 질의, 보험금 계산 등 주요 이벤트는 감사 로그에 기록된다.

## 변경 권고 사항

### P1. 기본 JWT 시크릿을 운영에서 차단

현재 `src/api/settings.py`의 기본값이 `dev-only-change-me`이다. 운영 래퍼(`ops/bin/insurance-rag-common`)는 자동으로 안전한 값을 생성하지만, FastAPI 앱을 직접 실행하면 기본 시크릿으로 토큰을 발급할 수 있다.

권고:
- 앱 시작 시 `API_JWT_SECRET` 또는 `SECRET_KEY`가 없고 기본값이 사용되면 운영 모드에서 부팅 실패 처리.
- 최소 길이와 `dev-only-change-me` 금지 검증 추가.
- 테스트/로컬 개발에서는 명시적으로 `API_ALLOW_DEV_JWT_SECRET=true` 같은 플래그를 둔다.

영향:
- 기본 시크릿으로 서명된 JWT 위조 위험을 줄인다.

### P2. 공개 `/api/system/status` 정보 축소 또는 인증 적용

`/api/system/status`는 인증 없이 인덱스, GraphDB, 표준코드 DB, `users.json` 존재 여부를 반환한다. 비밀값 자체는 노출하지 않지만 내부 파일/자산 상태를 외부 사용자가 추정할 수 있다.

권고:
- `/api/health`는 현재처럼 공개 유지.
- `/api/system/status`는 관리자 권한으로 제한하거나, 공개 응답에서는 `status` 정도만 반환하고 상세 경로/자산 상태는 `/api/admin/system-summary`로 일원화.

영향:
- 내부 구성 정보 노출 범위를 줄인다.

### P2. Refresh Token 폐기/회전 체계 추가

현재 로그아웃은 쿠키 삭제 방식이며, 서버 측 refresh token 폐기 목록이나 토큰 버전 검증은 없다. 탈취된 refresh token은 만료 전까지 재사용 가능하다.

권고:
- 사용자별 `token_version` 또는 `session_version`을 `users.json`에 저장하고 JWT에 포함.
- 비밀번호 재설정, 계정 비활성화, 강제 로그아웃 시 버전 증가.
- refresh token 재발급 시 회전하거나, 최소한 서버 측 폐기 목록을 둔다.

영향:
- 비밀번호 변경/계정 차단 이후 기존 refresh token 재사용 위험을 줄인다.

### P3. Refresh 경로의 상태 확인 명시화

`/api/auth/refresh`는 사용자가 존재하는지만 확인한 뒤 새 access token을 발급한다. 발급된 access token은 이후 `current_user()`에서 비활성 사용자를 차단하므로 즉시 권한 상승으로 이어지지는 않지만, 인증 수명주기 정책상 refresh 단계에서도 `status == active`를 확인하는 편이 명확하다.

권고:
- `refresh()`에서 `user.status != "active"`이면 `PermissionException` 또는 `AuthException` 반환.

영향:
- 비활성 계정에 대한 토큰 재발급 동작을 정책과 일치시킨다.

### P3. 관리자 감사 로그에 사용자 관리 이벤트 추가

사용자 생성/수정/삭제/비밀번호 재설정 API에는 현재 전용 감사 이벤트가 없다. 관리자 오남용 추적을 위해 계정 관리 이벤트는 명시 로그가 있는 편이 좋다.

권고:
- `ADMIN_USER_CREATED`, `ADMIN_USER_UPDATED`, `ADMIN_USER_DELETED`, `ADMIN_PASSWORD_RESET` 감사 이벤트 기록.
- 민감값은 기록하지 않고 대상 사용자, 변경 필드, 요청자, request id만 기록.

영향:
- 관리자 권한 사용 이력 추적성이 좋아진다.

## 결론

관리자/직원 권한 분리는 서버 측에서 대체로 올바르게 적용되어 있다. 즉시 고쳐야 할 권한 우회 취약점은 확인되지 않았지만, 운영 환경 기준으로는 JWT 시크릿 강제 검증과 시스템 상태 API 노출 축소를 우선 반영하는 것이 좋다.
