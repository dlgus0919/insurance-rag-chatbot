from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md"

REQUIRED_SECTIONS = (
    "# 실무자 전체 운영 오류 대응 매뉴얼",
    "## 1. 빠른 장애 분류",
    "## 2. 오류 색인",
    "## 3. 공통 증거 수집과 보안",
    "## 4. 로그인·세션·권한",
    "## 5. 화면·네트워크·API",
    "## 6. 일반 질의·RAG·근거",
    "## 7. 보험금 계산",
    "## 8. 문서 반입·지식 확장",
    "## 9. 검색 인덱스",
    "## 10. GraphDB",
    "## 11. LLM 서버",
    "## 12. DGX Spark 시스템",
    "## 13. 복구 확인 체크리스트",
)

REQUIRED_IDS = (
    "AUTH-001", "AUTH-002", "SESSION-001",
    "UI-001", "API-001", "API-002",
    "RAG-001", "RAG-002", "RAG-003",
    "CLAIM-001", "CLAIM-002", "CLAIM-003",
    "INTAKE-001", "INTAKE-002", "INTAKE-003",
    "INDEX-001", "INDEX-002",
    "GRAPH-001", "GRAPH-002", "GRAPH-003",
    "LLM-001", "LLM-002",
    "SYSTEM-001", "SYSTEM-002", "SYSTEM-003",
)

ITEM_FIELDS = (
    "증상",
    "오류 코드·문구",
    "심각도·업무 영향",
    "즉시 확인",
    "실무자 조치",
    "중단·이관 기준",
    "관리자 진단",
    "복구 확인",
    "수집 증거",
    "금지 사항",
)


def test_operations_manual_has_required_structure() -> None:
    text = MANUAL.read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in text
    for item_id in REQUIRED_IDS:
        assert text.count(item_id) >= 2, item_id


def test_operations_manual_has_no_placeholders_or_secrets() -> None:
    text = MANUAL.read_text(encoding="utf-8")
    assert not re.search(r"\b(TBD|TODO|FIXME)\b", text)
    assert not re.search(r"(?i)(api[_-]?key|password|passwd)\s*[:=]\s*\S+", text)
    assert "/srv/shared/" not in text


def test_each_manual_item_has_a_complete_response_table() -> None:
    text = MANUAL.read_text(encoding="utf-8")
    for item_id in REQUIRED_IDS:
        match = re.search(
            rf"### {item_id}[^\n]*\n(?P<body>.*?)(?=\n### |\n## |\Z)",
            text,
            flags=re.DOTALL,
        )
        assert match, item_id
        body = match.group("body")
        for field in ITEM_FIELDS:
            assert f"| {field} |" in body, f"{item_id}: {field}"
