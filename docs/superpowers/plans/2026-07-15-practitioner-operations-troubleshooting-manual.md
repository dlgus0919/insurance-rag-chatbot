# Practitioner Operations Troubleshooting Manual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 애플리케이션 오류 계약에 근거한 한국어 전체 운영 대응 매뉴얼을 Markdown과 검증된 PDF로 제공한다.

**Architecture:** Markdown을 내용의 기준 원본으로 유지하고, 실제 코드·테스트·운영 문서에서 확인한 오류만 안정적인 항목 ID로 정리한다. 별도 ReportLab 생성기가 Markdown의 제한된 문서 구조를 PDF로 변환하며, 텍스트 추출 검사와 Poppler 전 페이지 렌더링 검사를 모두 통과해야 한다.

**Tech Stack:** Python 3.11+, pytest, ReportLab 4.x, pypdf, pdfplumber, Poppler (`pdfinfo`, `pdftoppm`), Markdown

## Global Constraints

- 사용자-facing 문서와 보고는 한국어로 작성하고 코드 식별자는 영어를 사용한다.
- 비밀번호, API 키, 토큰, 사용자 원문 질의, 보험 원본 문서를 매뉴얼이나 테스트 fixture에 포함하지 않는다.
- 실무자 절차에는 삭제, DB 수정, 인덱스 재생성, 강제 종료 같은 파괴적 조치를 포함하지 않는다.
- Markdown은 기준 원본이고 PDF는 동일 내용을 제공하는 배포 산출물이다.
- PDF 최종 경로는 `output/pdf/practitioner_operations_troubleshooting_manual.pdf`이다.
- PDF 중간 렌더링은 `tmp/pdfs/`만 사용하고 최종 검증 후 제거한다.
- 사용자 승인 없이 커밋하거나 원격 push하지 않는다. 각 Task의 마지막 단계는 검토 체크포인트이며, 커밋은 사용자가 별도로 승인한 경우에만 수행한다.
- 작업 시작 시 `git status --short`와 대상 파일 diff를 확인하고 기존 사용자 변경을 보존한다.

---

## File Structure

- Create: `docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md` - 기준 운영 매뉴얼
- Create: `scripts/build_operations_manual_pdf.py` - Markdown을 검증 가능한 PDF로 생성
- Create: `tests/test_operations_manual_artifacts.py` - Markdown 구조, 민감정보 방지, PDF 생성·텍스트 계약 검증
- Create: `requirements-docs.txt` - 문서 생성 전용 Python 의존성
- Create: `output/pdf/practitioner_operations_troubleshooting_manual.pdf` - 최종 배포 PDF
- Modify: `README.md` - 운영 매뉴얼 진입 링크
- Modify: `docs/264_DGX_DEMO_SCENARIO_GUIDE.md` - 기존 빠른 대응 절에서 새 매뉴얼 연결
- Create: `docs/267_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL_REPORT.md` - 작성 근거와 검증 결과

## Task 1: Establish the manual contract from real error surfaces

**Files:**
- Create: `tests/test_operations_manual_artifacts.py`
- Create: `docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md`

**Interfaces:**
- Consumes: 오류 코드와 사용자 문구가 있는 `src/api/`, `src/ingest/`, `frontend/js/`, 기존 테스트와 DGX 운영 문서
- Produces: 안정적인 오류 항목 ID와 필수 절 구조를 가진 Markdown 기준 원본

- [ ] **Step 1: Record the clean scope boundary**

Run:

```bash
git status --short
git diff -- README.md docs/264_DGX_DEMO_SCENARIO_GUIDE.md
```

Expected: 기존 변경을 확인하고 본 계획 대상과 겹치는 변경이 있으면 덮어쓰지 않고 해당 diff를 보존한다.

- [ ] **Step 2: Collect the actual error vocabulary**

Run:

```bash
rg -n "AUTH_FAILED|PERMISSION_DENIED|INVALID_INPUT|NOT_FOUND|RATE_LIMIT_EXCEEDED|INTERNAL_ERROR|candidate_extraction_failed|blocked_scanned_pdf|blocked_unsupported|requires_review|GraphDB 파일이 없습니다|Chroma 인덱스가 없습니다" src frontend tests docs/264_DGX_DEMO_SCENARIO_GUIDE.md
```

Expected: 각 문자열의 정의 위치, 화면 표시 위치와 테스트 근거가 확인된다. 일치하는 문자열이 없는 항목은 매뉴얼에 실제 오류 코드인 것처럼 쓰지 않는다.

- [ ] **Step 3: Write the failing Markdown contract test**

Add to `tests/test_operations_manual_artifacts.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it fails**

Run:

```bash
pytest -q tests/test_operations_manual_artifacts.py -k operations_manual
```

Expected: FAIL because the manual file or required sections do not exist.

- [ ] **Step 5: Create the complete manual structure and item index**

Create `docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md` with these exact top-level sections and IDs:

```markdown
# 실무자 전체 운영 오류 대응 매뉴얼

문서 버전: 1.0
기준일: 2026-07-15

## 1. 빠른 장애 분류
## 2. 오류 색인
## 3. 공통 증거 수집과 보안
## 4. 로그인·세션·권한
### AUTH-001 로그인 실패
### AUTH-002 관리자 권한 거부
### SESSION-001 세션 만료 또는 인증 상태 상실
## 5. 화면·네트워크·API
### UI-001 화면 또는 정적 자산 로딩 실패
### API-001 API 서버 연결 실패
### API-002 요청 제한 초과
## 6. 일반 질의·RAG·근거
### RAG-001 검색 결과 없음
### RAG-002 답변 생성 실패 또는 시간 초과
### RAG-003 근거 누락 또는 GraphDB-Vector 정합성 경고
## 7. 보험금 계산
### CLAIM-001 계산 입력값 오류
### CLAIM-002 실무 검토 필요 상태
### CLAIM-003 계산 처리 실패
## 8. 문서 반입·지식 확장
### INTAKE-001 지원하지 않는 문서
### INTAKE-002 스캔 PDF 차단
### INTAKE-003 검토 후보 생성 실패
## 9. 검색 인덱스
### INDEX-001 BM25 또는 Chroma 인덱스 누락
### INDEX-002 활성 소스와 인덱스 불일치
## 10. GraphDB
### GRAPH-001 GraphDB 파일 누락
### GRAPH-002 GraphDB 읽기 또는 빌드 상태 확인 실패
### GRAPH-003 GraphDB-Vector 정합성 경고
## 11. LLM 서버
### LLM-001 활성 모델 서버 연결 실패
### LLM-002 응답 지연 또는 시간 초과
## 12. DGX Spark 시스템
### SYSTEM-001 저장공간 부족
### SYSTEM-002 메모리 또는 스왑 압박
### SYSTEM-003 애플리케이션 프로세스 중단
## 13. 복구 확인 체크리스트
```

Under every item, use the exact field sequence:

```markdown
| 구분 | 내용 |
|---|---|
| 증상 | 사용자가 실제로 관찰할 수 있는 상태 |
| 오류 코드·문구 | 코드와 화면에서 확인한 값만 기재 |
| 심각도·업무 영향 | 긴급/주요/일반/안내 및 업무 지속 가능 여부 |
| 즉시 확인 | 상태를 바꾸지 않는 확인 절차 |
| 실무자 조치 | 되돌릴 수 있는 권한 내 조치 |
| 중단·이관 기준 | 반복 시도를 멈출 조건 |
| 관리자 진단 | 관리자 화면 또는 읽기 전용 명령 |
| 복구 확인 | 같은 기능의 정상 재검증 절차 |
| 수집 증거 | 시각, 기능명, 요청 ID, 민감정보가 제거된 화면 |
| 금지 사항 | 비밀번호 수집, 임의 삭제·재빌드 금지 |
```

- [ ] **Step 6: Run the Markdown contract tests**

Run:

```bash
pytest -q tests/test_operations_manual_artifacts.py -k operations_manual
```

Expected: PASS.

- [ ] **Step 7: Review checkpoint**

Run:

```bash
git diff --check -- tests/test_operations_manual_artifacts.py docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md
git status --short -- tests/test_operations_manual_artifacts.py docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md
```

Do not stage or commit unless the user explicitly authorizes it.

## Task 2: Fill every response procedure with evidence-backed content

**Files:**
- Modify: `docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md`
- Modify: `tests/test_operations_manual_artifacts.py`

**Interfaces:**
- Consumes: Task 1 item IDs and actual error contracts
- Produces: 실무자 조치, 관리자 진단, 이관 기준과 복구 확인이 모두 채워진 매뉴얼

- [ ] **Step 1: Add a completeness test for every item**

Add:

```python
ITEM_FIELDS = (
    "증상", "오류 코드·문구", "심각도·업무 영향", "즉시 확인",
    "실무자 조치", "중단·이관 기준", "관리자 진단", "복구 확인",
    "수집 증거", "금지 사항",
)


def test_every_manual_item_has_all_response_fields() -> None:
    text = MANUAL.read_text(encoding="utf-8")
    starts = [text.index(f"### {item_id}") for item_id in REQUIRED_IDS]
    starts.append(len(text))
    for index, item_id in enumerate(REQUIRED_IDS):
        block = text[starts[index]:starts[index + 1]]
        for field in ITEM_FIELDS:
            assert f"| {field} |" in block, (item_id, field)
        assert "중단·이관 기준" in block
        assert "복구 확인" in block
```

- [ ] **Step 2: Run the test and confirm incomplete items fail**

Run:

```bash
pytest -q tests/test_operations_manual_artifacts.py::test_every_manual_item_has_all_response_fields
```

Expected: FAIL until all 25 item blocks contain the required fields.

- [ ] **Step 3: Populate authentication, API, RAG, and claim procedures**

Use these evidence sources:

```bash
rg -n "AUTH_FAILED|PERMISSION_DENIED|RATE_LIMIT_EXCEEDED|INVALID_INPUT|requires_review|request_id|timeout" src/api frontend/js tests/test_error_responses.py tests/test_api_* tests/test_claim_*
```

For `CLAIM-002`, state explicitly that `requires_review=true` is an 안내/검토 상태 and not a calculation engine failure. For `RAG-003`, distinguish no evidence, stale diagnostics, and sampled GraphDB-Vector mismatch.

- [ ] **Step 4: Populate intake, index, GraphDB, LLM, and DGX procedures**

Use these evidence sources:

```bash
rg -n "blocked_scanned_pdf|blocked_unsupported|candidate_extraction_failed|graph_rebuilt|index_rebuilt|GraphDB 파일이 없습니다|Chroma 인덱스가 없습니다|available.*false|disk|storage|memory|swap" src scripts frontend/js tests docs/263_DGX_DEMO_REHEARSAL_REPORT.md docs/264_DGX_DEMO_SCENARIO_GUIDE.md
```

Only include commands already present in the repository or NVIDIA DGX operating guidance. Mark service restart, index rebuild, GraphDB rebuild, DB mutation and file deletion as administrator change procedures outside the practitioner's direct actions.

- [ ] **Step 5: Complete the quick triage and error index**

The quick triage must route by observed impact:

```text
전체 화면 접근 불가 -> SYSTEM-003 or API-001
로그인만 실패 -> AUTH-001 or SESSION-001
관리자 메뉴만 거부 -> AUTH-002
답변만 실패 -> RAG-001/RAG-002 or LLM-001/LLM-002
계산만 실패 -> CLAIM-001/CLAIM-003
문서 처리만 실패 -> INTAKE-001/INTAKE-002/INTAKE-003
관리자 상태에서 인덱스 이상 -> INDEX-001/INDEX-002
GraphDB 상태 이상 -> GRAPH-001/GRAPH-002/GRAPH-003
호스트 자원 이상 -> SYSTEM-001/SYSTEM-002
```

The error index must include columns `기능`, `화면 문구·상태`, `항목 ID`, `업무 지속`, `담당`.

- [ ] **Step 6: Run focused tests and source-string audit**

Run:

```bash
pytest -q tests/test_operations_manual_artifacts.py -k manual
rg -n "TBD|TODO|FIXME|/srv/shared/|password:|api_key:" docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md
```

Expected: tests PASS; `rg` produces no output.

- [ ] **Step 7: Review checkpoint**

Run:

```bash
git diff --check -- docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md tests/test_operations_manual_artifacts.py
```

Do not stage or commit unless explicitly authorized.

## Task 3: Generate a Korean PDF from the canonical Markdown

**Files:**
- Create: `requirements-docs.txt`
- Create: `scripts/build_operations_manual_pdf.py`
- Modify: `tests/test_operations_manual_artifacts.py`
- Create: `output/pdf/practitioner_operations_troubleshooting_manual.pdf`

**Interfaces:**
- Consumes: `build_pdf(source: Path, output: Path, font_path: Path) -> None`
- Produces: 페이지 번호, 문서 버전, 한국어 내장 글꼴과 줄바꿈을 가진 PDF

- [ ] **Step 1: Declare document-only dependencies**

Create `requirements-docs.txt`:

```text
reportlab>=4.2,<5
pdfplumber>=0.10,<1
pypdf>=5,<7
```

Poppler is a system dependency and must be checked with `command -v pdfinfo` and `command -v pdftoppm`; do not install it silently.

- [ ] **Step 2: Write failing PDF generator tests**

Add:

```python
from pypdf import PdfReader

from scripts.build_operations_manual_pdf import build_pdf, resolve_korean_font


PDF_OUTPUT = ROOT / "output/pdf/practitioner_operations_troubleshooting_manual.pdf"


def test_resolve_korean_font_requires_an_existing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPERATIONS_MANUAL_FONT", str(tmp_path / "missing.ttf"))
    try:
        resolve_korean_font()
    except FileNotFoundError as exc:
        assert "한국어 글꼴" in str(exc)
    else:
        raise AssertionError("missing font must fail")


def test_build_pdf_contains_manual_title_and_item_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPERATIONS_MANUAL_FONT", raising=False)
    font_path = resolve_korean_font()
    output = tmp_path / "manual.pdf"
    build_pdf(MANUAL, output, font_path)
    reader = PdfReader(str(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "실무자 전체 운영 오류 대응 매뉴얼" in text
    assert "AUTH-001" in text
    assert "GRAPH-003" in text
    assert "SYSTEM-003" in text
    assert len(reader.pages) >= 3
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
pytest -q tests/test_operations_manual_artifacts.py -k "font or build_pdf"
```

Expected: FAIL because the generator module does not exist.

- [ ] **Step 4: Implement the generator public interface**

Create `scripts/build_operations_manual_pdf.py` with these public functions and CLI:

```python
from __future__ import annotations

import argparse
import html
import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, PageBreak,
    Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md"
DEFAULT_OUTPUT = ROOT / "output/pdf/practitioner_operations_troubleshooting_manual.pdf"
FONT_CANDIDATES = (
    ROOT / "assets/fonts/NotoSansKR-Regular.ttf",
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
)


def resolve_korean_font() -> Path:
    explicit = os.getenv("OPERATIONS_MANUAL_FONT")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"한국어 글꼴 파일이 없습니다: {path}")
        return path
    for path in FONT_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "한국어 글꼴을 찾지 못했습니다. OPERATIONS_MANUAL_FONT에 TTF/TTC 경로를 지정하세요."
    )


def build_pdf(source: Path, output: Path, font_path: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"매뉴얼 Markdown이 없습니다: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(TTFont("ManualKorean", str(font_path)))
    document = OperationsManualDocument(str(output), source_name=source.name)
    document.build(parse_manual_markdown(source.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the practitioner operations manual PDF.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    build_pdf(args.source, args.output, args.font or resolve_korean_font())
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add these exact document and parser definitions above `build_pdf` in the same file:

```python
PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 18 * mm
RIGHT_MARGIN = 18 * mm
TOP_MARGIN = 20 * mm
BOTTOM_MARGIN = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    return escaped


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "ManualTitle", parent=base["Title"], fontName="ManualKorean",
            fontSize=22, leading=30, alignment=TA_CENTER, spaceAfter=12 * mm,
            textColor=colors.HexColor("#0B2545"),
        ),
        "H2": ParagraphStyle(
            "ManualH2", parent=base["Heading2"], fontName="ManualKorean",
            fontSize=15, leading=21, spaceBefore=7 * mm, spaceAfter=3 * mm,
            textColor=colors.HexColor("#123B66"), keepWithNext=True,
        ),
        "H3": ParagraphStyle(
            "ManualH3", parent=base["Heading3"], fontName="ManualKorean",
            fontSize=12, leading=17, spaceBefore=5 * mm, spaceAfter=2 * mm,
            textColor=colors.HexColor("#1D5A91"), keepWithNext=True,
        ),
        "Body": ParagraphStyle(
            "ManualBody", parent=base["BodyText"], fontName="ManualKorean",
            fontSize=9.5, leading=15, alignment=TA_LEFT, wordWrap="CJK",
            spaceAfter=2.2 * mm,
        ),
        "Bullet": ParagraphStyle(
            "ManualBullet", parent=base["BodyText"], fontName="ManualKorean",
            fontSize=9.5, leading=15, leftIndent=6 * mm, firstLineIndent=-3 * mm,
            bulletIndent=1.5 * mm, wordWrap="CJK", spaceAfter=1.2 * mm,
        ),
        "Code": ParagraphStyle(
            "ManualCode", parent=base["Code"], fontName="ManualKorean",
            fontSize=7.5, leading=11, leftIndent=3 * mm, rightIndent=3 * mm,
            borderColor=colors.HexColor("#D8E2EC"), borderWidth=0.5,
            borderPadding=5, backColor=colors.HexColor("#F5F8FB"),
            wordWrap="CJK", spaceBefore=1.5 * mm, spaceAfter=2.5 * mm,
        ),
        "TableHeader": ParagraphStyle(
            "ManualTableHeader", parent=base["BodyText"], fontName="ManualKorean",
            fontSize=8.5, leading=12, textColor=colors.white, wordWrap="CJK",
        ),
        "TableCell": ParagraphStyle(
            "ManualTableCell", parent=base["BodyText"], fontName="ManualKorean",
            fontSize=8.2, leading=12, wordWrap="CJK",
        ),
    }


class OperationsManualDocument(BaseDocTemplate):
    def __init__(self, filename: str, source_name: str) -> None:
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=LEFT_MARGIN,
            rightMargin=RIGHT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
            title="실무자 전체 운영 오류 대응 매뉴얼",
            author="insurance-rag-chatbot",
            subject=source_name,
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="manual-body",
        )
        self.addPageTemplates(PageTemplate(id="manual", frames=[frame], onPage=self._on_page))

    @staticmethod
    def _on_page(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("ManualKorean", 7.5)
        canvas.setFillColor(colors.HexColor("#526579"))
        canvas.drawString(LEFT_MARGIN, PAGE_HEIGHT - 11 * mm, "실무자 전체 운영 오류 대응 매뉴얼")
        canvas.drawRightString(
            PAGE_WIDTH - RIGHT_MARGIN,
            9 * mm,
            f"문서 버전 1.0 | {doc.page}",
        )
        canvas.restoreState()


def _is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _table_flowable(lines: list[str], styles: dict[str, ParagraphStyle]) -> Table:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    if len(rows) > 1 and _is_table_separator(lines[1]):
        rows.pop(1)
    column_count = max(len(row) for row in rows)
    normalized = [row + [""] * (column_count - len(row)) for row in rows]
    data = []
    for row_index, row in enumerate(normalized):
        style = styles["TableHeader"] if row_index == 0 else styles["TableCell"]
        data.append([Paragraph(_inline(cell), style) for cell in row])
    if column_count == 2:
        widths = [36 * mm, CONTENT_WIDTH - 36 * mm]
    else:
        widths = [CONTENT_WIDTH / column_count] * column_count
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#245B88")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B7C6D6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FB")]),
    ]))
    return table


def parse_manual_markdown(text: str) -> list:
    styles = _styles()
    lines = text.splitlines()
    story: list = []
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            story.append(Spacer(1, 1.5 * mm))
            index += 1
            continue
        if stripped.startswith("```"):
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1
            code = "<br/>".join(html.escape(line or " ", quote=False) for line in code_lines)
            story.append(Paragraph(code, styles["Code"]))
            continue
        if stripped.startswith("|"):
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            story.append(_table_flowable(table_lines, styles))
            story.append(Spacer(1, 2.5 * mm))
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            style = styles["Title"] if level == 1 else styles[f"H{level}"]
            story.append(Paragraph(_inline(heading.group(2)), style))
            index += 1
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if bullet or numbered:
            marker = "•" if bullet else f"{numbered.group(1)}."
            body = bullet.group(1) if bullet else numbered.group(2)
            story.append(Paragraph(_inline(body), styles["Bullet"], bulletText=marker))
            index += 1
            continue
        paragraph_lines = [stripped]
        index += 1
        while index < len(lines):
            next_line = lines[index].strip()
            if (
                not next_line
                or next_line.startswith(("#", "|", "```", "- ", "* "))
                or re.match(r"^\d+\.\s+", next_line)
            ):
                break
            paragraph_lines.append(next_line)
            index += 1
        story.append(Paragraph(_inline(" ".join(paragraph_lines)), styles["Body"]))
    return story
```

This parser intentionally supports only the canonical manual's documented subset. If authors add nested lists, HTML, images, or merged table cells later, add a failing parser test before extending the grammar.

- [ ] **Step 5: Run generator tests**

Run:

```bash
pytest -q tests/test_operations_manual_artifacts.py -k "font or build_pdf"
```

Expected: PASS.

- [ ] **Step 6: Generate the final PDF**

Run with the bundled PDF runtime:

```bash
/Users/june_kim/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/build_operations_manual_pdf.py
```

Expected: prints `output/pdf/practitioner_operations_troubleshooting_manual.pdf` and exits 0.

- [ ] **Step 7: Validate PDF metadata and text**

Run:

```bash
pdfinfo output/pdf/practitioner_operations_troubleshooting_manual.pdf
/Users/june_kim/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -c "from pypdf import PdfReader; p='output/pdf/practitioner_operations_troubleshooting_manual.pdf'; t='\n'.join(x.extract_text() or '' for x in PdfReader(p).pages); assert 'AUTH-001' in t and 'GRAPH-003' in t and 'SYSTEM-003' in t; print('pdf text OK')"
```

Expected: valid A4 PDF information and `pdf text OK`.

- [ ] **Step 8: Review checkpoint**

Run:

```bash
git status --short -- requirements-docs.txt scripts/build_operations_manual_pdf.py tests/test_operations_manual_artifacts.py output/pdf/practitioner_operations_troubleshooting_manual.pdf
```

Do not stage or commit unless explicitly authorized.

## Task 4: Render every PDF page and complete delivery documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/264_DGX_DEMO_SCENARIO_GUIDE.md`
- Create: `docs/267_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL_REPORT.md`
- Verify: `output/pdf/practitioner_operations_troubleshooting_manual.pdf`

**Interfaces:**
- Consumes: Task 3 final PDF
- Produces: visually approved PDF, public entry links and implementation report

- [ ] **Step 1: Render all pages to PNG**

Run:

```bash
mkdir -p tmp/pdfs
pdftoppm -png output/pdf/practitioner_operations_troubleshooting_manual.pdf tmp/pdfs/operations-manual
```

Expected: one PNG per PDF page under `tmp/pdfs/`.

- [ ] **Step 2: Inspect every rendered page**

Use the local image viewer on every generated PNG. Check:

```text
Korean glyphs render normally
no black squares or missing glyphs
no clipped headings or table cells
tables repeat headers when split
code lines wrap without leaving the page
header, footer and page number are aligned
no blank interior page
section starts are readable and consistent
```

If any defect exists, fix `scripts/build_operations_manual_pdf.py`, regenerate the PDF, delete old PNGs, rerender all pages and restart this inspection from page 1.

- [ ] **Step 3: Add entry links**

Add a concise `운영 오류 대응` entry in `README.md` linking to:

```markdown
- [실무자 전체 운영 오류 대응 매뉴얼](docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md)
- PDF 배포본: `output/pdf/practitioner_operations_troubleshooting_manual.pdf`
```

In `docs/264_DGX_DEMO_SCENARIO_GUIDE.md`, keep the existing quick-response content and add one sentence directing full incidents to the new manual. Do not replace historical rehearsal evidence.

- [ ] **Step 4: Write the implementation report**

Create `docs/267_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL_REPORT.md` with exact sections:

```markdown
# 실무자 전체 운영 오류 대응 매뉴얼 작성 보고서

## 1. 범위
## 2. 변경 파일
## 3. 오류 근거 수집 결과
## 4. Markdown-PDF 일치 검증
## 5. PDF 시각 검증
## 6. 실행한 명령과 결과
## 7. 남은 위험
```

Record the PDF page count, font path category without exposing usernames, Poppler validation result, rendered page count and zero-defect visual result.

- [ ] **Step 5: Remove intermediate files**

Run only after visual approval:

```bash
find tmp/pdfs -type f -name 'operations-manual-*.png' -delete
rmdir tmp/pdfs 2>/dev/null || true
```

Expected: final PDF remains; temporary rendered images are gone.

- [ ] **Step 6: Run focused and full verification**

Run:

```bash
pytest -q tests/test_operations_manual_artifacts.py
python -m compileall -q scripts/build_operations_manual_pdf.py
git diff --check -- README.md docs/264_DGX_DEMO_SCENARIO_GUIDE.md docs/266_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL.md docs/267_PRACTITIONER_OPERATIONS_TROUBLESHOOTING_MANUAL_REPORT.md scripts/build_operations_manual_pdf.py tests/test_operations_manual_artifacts.py requirements-docs.txt
git status --short
```

Expected: tests PASS, compile check PASS, no whitespace errors, and only intended files plus pre-existing user changes are listed.

- [ ] **Step 7: Final self-inspection**

Confirm:

```text
[ ] all 25 error IDs have complete procedures
[ ] practitioner and administrator actions are separated
[ ] no secrets, internal credentials or raw user data appear
[ ] Markdown and PDF carry the same version and item IDs
[ ] all PDF pages were visually inspected after the final generation
[ ] temporary PNGs were removed
[ ] no unrelated file was modified
[ ] no commit or push occurred without explicit approval
```

- [ ] **Step 8: Delivery checkpoint**

Report changed files, focused test results, PDF page count, visual inspection result and any unrun DGX validation. Do not stage, commit or push unless the user explicitly requests it.
