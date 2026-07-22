# 관리자 GraphDB 3D 시각화 구현 및 DGX 검증 보고서

## 1. 구현 범위

관리자 페이지에 읽기 전용 GraphDB 탐색 화면을 추가했다. 기본 화면은 사전 생성한 핵심 구조만
불러오며, 검색·노드 선택 이후에는 서버가 제한한 부분 그래프만 조회한다. 노드 편집, 관계 변경,
GraphDB 재빌드와 전체 그래프 전송은 범위에 포함하지 않았다.

화면은 자체 호스팅한 `3d-force-graph` 번들을 우선 사용한다. WebGL을 사용할 수 없으면 키보드로
선택할 수 있는 2D 관계 목록으로 자동 전환한다. 그래프 탭을 벗어나면 렌더링을 일시정지하고,
화면을 해제할 때 WebGL 자원을 정리한다.

## 2. 변경 파일

- 프로파일링·스냅샷: `scripts/profile_graph_visualization.py`,
  `scripts/build_graph_visualization_snapshot.py`
- 조회 엔진: `src/graph/visualization.py`, `src/graph/store.py`, `src/config.py`
- 관리자 API: `src/api/routes/admin_graph.py`, `src/api/schemas/admin_graph.py`, `src/api/main.py`
- 프런트엔드: `frontend/js/modules/admin-graph.js`, `frontend/js/pages/admin-graph.js`,
  `frontend/js/graph/`, `frontend/html/admin.html`, `frontend/css/admin.css`
- 자체 호스팅 번들: `frontend/dist/graph-viz.min.js`, `frontend/dist/app.min.js`
- 테스트: `tests/test_graph_visualization.py`, `tests/test_graph_store.py`,
  `tests/test_api_admin_graph.py`, `tests/test_admin_graph_frontend.mjs`,
  `tests/e2e/admin-graph.spec.js`

## 3. 실제 GraphDB 분포와 계층 정책

DGX 운영 GraphDB를 읽기 전용으로 프로파일링한 결과는 다음과 같다.

| 항목 | 값 |
| --- | ---: |
| 전체 노드 | 545,223 |
| 전체 관계 | 46,241 |
| 연결된 노드 | 17,521 |
| 고립 노드 | 527,702 |
| 연결 컴포넌트 | 2개 |
| 컴포넌트 크기 | 11,568 / 5,953 |
| 차수 중앙값 / 90백분위 / 99백분위 | 0 / 0 / 2 |
| 최대 차수 | 9,020 |

대량의 비급여 표준 코드 노드가 고립 상태이므로 전체 노드를 브라우저로 보내는 방식은 사용할 수
없다. 핵심 구조는 유형별 할당량과 연결도를 함께 적용해 편중을 제한한다.

실제 관계 방향을 표본과 집계로 확인한 결과 계층 정책은 다음과 같이 확정했다.

- `HAS_CATEGORY`: 출발 노드가 하위 개념, 도착 노드가 상위 분류이다.
- `SAME_CATEGORY_AS`: 속성이 `subclass_of`인 관계만 출발 노드를 하위, 도착 노드를 상위로 본다.
- 그 밖의 관계와 동등 범주 관계는 상하위로 추측하지 않고 일반 연관 관계로 분류한다.

## 4. API 및 렌더링 상한

| 구분 | 기본 노드/관계 | 서버 절대 상한 노드/관계 |
| --- | --- | --- |
| 핵심 구조 | 120 / 240 | 150 / 300 |
| 집중 보기 | 180 / 360 | 250 / 500 |

- 검색 결과는 최대 20건, 하위 탐색 깊이는 최대 3단계이다.
- 스냅샷과 모든 API는 제한 초과 요청을 서버에서 거부하거나 잘라낸다.
- 내부 픽셀 비율은 1.25 이하, 물리 계산 종료 시간은 1.2초로 제한한다.
- 근거 상세에는 안전한 문서 표시명과 페이지 범위만 노출한다.

## 5. 개발 PC 검증

| 검증 | 결과 |
| --- | --- |
| GraphDB 조회·관계 방향·상한 단위 테스트 | 11건 통과 |
| 관리자 GraphDB와 기존 지식 확장 Node 테스트 | 22건 통과 |
| 프런트엔드 빌드 | 통과, 외부 CDN 참조 없음 |
| Python 모듈 컴파일 | 통과 |
| diff whitespace 검사 | 통과 |

## 6. DGX Spark LLM 동시 실행 검증

- 환경: Ubuntu 24.04, NVIDIA 커널, Playwright 1.60 Chromium 프로젝트
- LLM: SGLang 기반 Qwen3 Next 80B Instruct FP8
- 브라우저: DGX 호스트에서 실행한 headless Chromium, 기본 1280x720 viewport
- 프롬프트: 답이 고정된 짧은 합성 질의, 응답 본문은 저장하지 않음
- 표본: 단독 7회, GraphDB 반복 조작 동시 7회

| 지표 | LLM 단독 중앙값 | GraphDB 동시 중앙값 | 변화 |
| --- | ---: | ---: | ---: |
| 최초 응답 바이트 | 82.9ms | 83.8ms | +1.1% |
| 전체 응답 | 118.0ms | 122.2ms | +3.6% |

동시 실행 중 LLM OOM, 브라우저 중단, WebGL 컨텍스트 손실은 없었다. 테스트 종료 후 SGLang과
임시 Uvicorn을 종료했고, 8000·30000 포트가 비어 있으며 시스템 가용 메모리는 약 117GB로
회복된 것을 확인했다.

## 7. 성능 측정 결과

| 측정 | 결과 | 기준 |
| --- | ---: | ---: |
| 실제 핵심 구조 API | 166.5ms, 120노드/21관계 | 2초 이내 |
| 실제 검색 API | 344.2ms, 최대 20건 | 1초 이내 |
| 실제 최대 집중 API | 110.7ms, 250노드/249관계 | 1초 이내 |
| 실제 GraphDB 브라우저 핵심 구조 | 120노드/27관계, 표시 성공 | 서버 상한 준수 |
| 동시 실행 핵심 구조 표시 | 153ms | 2초 이내 |
| 30회 집중/초기화 반복 | 12.8초 | 중단 없음 |
| 카메라 전환 프레임률 | 31.08 FPS | 30 FPS 이상 |
| WebGL 컨텍스트 손실 | 0건 | 0건 |
| LLM 최초 응답 중앙값 악화 | 1.1% | 10% 이내 |

## 8. 실행한 검증과 결과

- DGX 집중 Python 테스트: 17건 통과
- DGX GraphDB·채팅 Chromium 회귀: 11건 통과
- 실제 DGX GraphDB를 연결한 자체 호스팅 3D 브라우저 스모크: 1건 통과
- Qwen 80B 동시 실행 3D 반복 테스트: 통과
- 전체 pytest: 문서 전용 `pypdf`가 DGX 앱 가상환경에 없어 수집 단계에서 중단
- 문서 전용 런타임 검증: 매뉴얼 구조 3건과 PDF 생성·추출 검사 통과

문서 의존성은 `requirements-docs.txt`로 분리되어 있으므로 앱 가상환경을 임의 변경하지 않았다.
실패 테스트를 삭제하거나 skip 처리하지 않았다.

## 9. 남은 위험

- DGX 물리 데스크톱의 실제 Chromium 창, 사용자 확대율, DGX Dashboard와 온도 수치는 이번 SSH
  기반 검증에서 측정하지 못했다. 호스트 로컬 headless Chromium 결과를 물리 GUI 결과로
  단정하지 않는다.
- 차수가 매우 큰 허브는 서버 상한 때문에 일부 관계가 잘린다. 화면의 잘림 안내를 보고 검색이나
  단계 확장으로 좁혀야 한다.
- 전체 pytest를 한 환경에서 실행하려면 앱 의존성과 문서 의존성을 함께 갖춘 별도 검증 환경이
  필요하다.
- 운영 GraphDB와 스냅샷의 빌드 시점이 달라지면 핵심 구조가 오래될 수 있으므로 GraphDB 빌드
  절차에서 스냅샷 생성 성공 여부를 함께 확인해야 한다.
