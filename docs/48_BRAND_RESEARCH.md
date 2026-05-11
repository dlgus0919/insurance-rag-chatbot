# 48 브랜드 조사 기록 — 신한EZ손해보험 UI 테마

## 조사 일시

- 2026-05-11

## 공식 출처

- 신한EZ손해보험 브랜드 페이지: https://www.shinhanez.co.kr/static/cmy/CMY10010M01.html
- 신한금융그룹 CI 페이지: https://www.shinhangroup.com/kr/about/identity/ci
- 신한금융그룹 캐릭터 페이지: https://www.shinhangroup.com/kr/about/identity/character

## 확인 결과

| 항목 | 값 | 출처/근거 |
| --- | --- | --- |
| Primary color | `#0046ff` | 신한금융그룹 CI 페이지의 Shinhan Blue |
| Secondary color | `#8cd2f5`, `#4baff5`, `#2878f5`, `#00236e` | 신한금융그룹 CI 페이지의 Secondary Color |
| Neutral text | `#1A1A2E` | 앱 가독성을 위한 UI 텍스트 색상. 공식 Black `#000000`보다 화면 피로도를 낮춘 적용값 |
| Background | `#FFFFFF` | 신한금융그룹 CI 페이지의 White |
| Logo source | `https://www.shinhanez.co.kr/resources/image/logo-shez.svg` | 신한EZ손해보험 브랜드 페이지의 BI 이미지 |
| Mascot source | `https://www.shinhangroup.com/resources/publish/kr/images/about/character_friends.png` | 신한금융그룹 캐릭터 페이지의 신한프렌즈 이미지 |

## 적용 판단

- Streamlit 테마의 `primaryColor`는 공식 Shinhan Blue인 `#0046FF`를 사용한다.
- 사이드바/카드 배경은 명세 기본값 `#F4F7FC`를 사용하고, CSS 강조선과 버튼/포커스 컬러는 `#0046FF` 계열로 맞춘다.
- 보조 UI 강조에는 공식 secondary color 중 Royal Blue `#2878F5`와 Light Blue `#8CD2F5`를 제한적으로 사용한다.
- 신한EZ 공식 로고는 SVG 원본을 `assets/logo.svg`로 보관하고, Streamlit 표시 및 명세 충족을 위해 `assets/logo.png`로 변환해 함께 저장했다.
- 마스코트는 신한EZ 전용 마스코트를 별도로 확인하지 못했으므로 신한금융그룹 공식 대표 캐릭터 신한프렌즈 이미지를 `assets/mascot.png`로 저장했다.

## 저작권/사용 주의

- 로고와 캐릭터 이미지는 공식 웹사이트에서 공개 노출되는 브랜드 자산이다.
- 본 프로젝트는 사내 캡스톤 검토용이므로 앱 내부 표시 용도로 사용한다.
- 외부 공개 배포, 홍보물 사용, 상업적 재가공 전에는 신한금융그룹/신한EZ손해보험의 브랜드 사용 기준 및 법무 확인이 필요하다.
