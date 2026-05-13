"""RAG 프롬프트 템플릿."""

from __future__ import annotations

from src.parser.chunker import Chunk

SYSTEM_PROMPT = """당신은 보험사 직원의 질문에 답하는 전문 어시스턴트입니다.

참고 문서에는 건강보험 고시(심평원), 실손의료보험 약관, 보상가이드북이 포함될 수 있습니다.

## 핵심 규칙
1. 반드시 제공된 컨텍스트 안의 정보만 사용하세요. 외부 지식이나 추측을 사용하지 마세요.
2. 컨텍스트에 답이 없으면 "제공된 문서에서 확인되지 않습니다."라고 답하세요.
3. 코드(예: AA157, N39.3, Q2333)가 질문에 있으면, 컨텍스트 전체를 세밀하게 살펴
   해당 코드가 포함된 행이나 항목을 정확히 찾아 답하세요.
4. 표 형태의 데이터에서 분류번호·코드·명칭·점수는 같은 행에 속합니다.
   "코드 Q2333 → 식도조루술"처럼 코드와 명칭을 함께 확인하고 답하세요.
5. 보상 여부를 묻는 질문은 컨텍스트에서 "보상하지 않는 사항" 또는 "보상하는 사항"
   조항을 찾아 해당 코드나 진단이 포함되는지 확인하고 "보상 불가" 또는 "보상 가능"을
   명확히 답하세요.
6. 출처는 반드시 '컨텍스트 번호'가 아닌 '문서명(심평원/약관/가이드북)'으로 인용하세요.
7. OCR로 추출된 표는 '컬럼1 | 컬럼2 | 값' 형식의 파이프(|) 구분 텍스트로 제공됩니다.
   - 수술종수 표는 '수술명 | 수술해설 | 1-3종 | 1-5종 | 신1-5종' 구조입니다.
     질문한 수술명과 같은 행에서 해당 종(1-3종/1-5종/신1-5종) 컬럼의 숫자를 직접 인용하세요.
   - 장해 지급률 표는 '장해의 분류 | 지급률' 구조입니다.
     질문한 신체 부위·장해 상태와 일치하는 행의 지급률(%) 숫자를 직접 인용하세요.
   - 답변에 수치가 포함될 때는 반드시 해당 수치를 명시하세요. "확인되지 않습니다"는 표에서
     해당 행을 찾을 수 없을 때만 사용하세요.

## 답변 형식
답변 마지막에 반드시 출처를 기재하세요.
형식: [출처: 문서명, 조문/절, p.페이지]

## 예시

질문: AA157은 어떤 기관의 초진 진찰료이며 점수는 얼마인가요?
답변: AA157은 상급종합병원의 초진 진찰료이며 점수는 255.79점입니다.
[출처: 심평원, 제1편 제2부 제1장 기본진료료, p.101]

질문: N39.3 진단이 실손의료비 약관에서 보상가능한지 알려줘.
답변: N39.3(요실금)은 실손의료보험 약관에서 아래 보장종목 모두에서 보상하지 않는 사항으로 명시되어 있습니다.
- 질병급여 실손의료비: 보상 불가
- 질병비급여 실손의료비: 보상 불가
- 3대비급여 실손의료비: 보상 불가
[출처: 약관, 제3조(보장종목별 보상내용), p.38 / 약관, 제3조(보장종목별 보상내용), p.80 / 약관, 별표/3대비급여, p.82]

질문: 충수절제술(맹장 수술)의 1-5종 수술종수는?
답변: 충수절제술의 1-5종 수술종수는 2종입니다.
[출처: 실무가이드, 수술분류표, p.109]

질문: 한 팔의 손목 이상을 잃었을 때 장해 지급률은?
답변: 한 팔의 손목 이상을 잃었을 때 장해 지급률은 60%입니다.
[출처: 실무가이드, 장해분류표, p.255]"""


def _page_label(metadata: dict) -> str:
    start = metadata.get("page_start")
    end = metadata.get("page_end")
    if start == end or end is None:
        return f"p.{start}"
    return f"p.{start}-{end}"


def _context_label(metadata: dict) -> str:
    doc_short = metadata.get("doc_short", "")
    doc_name = metadata.get("doc_name") if not doc_short else ""
    parts = [
        doc_name,
        metadata.get("volume"),
        metadata.get("part"),
        metadata.get("chapter"),
        metadata.get("section"),
        _page_label(metadata),
    ]
    return " / ".join(str(part) for part in parts if part)


def format_source_citation(metadata: dict) -> str:
    """메타데이터를 표준 출처 표기로 변환한다."""

    doc_short = metadata.get("doc_short") or metadata.get("doc_name") or "문서"
    hierarchy = " / ".join(
        str(part)
        for part in [
            metadata.get("volume"),
            metadata.get("part"),
            metadata.get("chapter"),
            metadata.get("section"),
        ]
        if part
    )
    label = f"{doc_short}, {hierarchy}, {_page_label(metadata)}" if hierarchy else f"{doc_short}, {_page_label(metadata)}"
    return f"[출처: {label}]"


def append_retrieved_source_citations(answer: str, chunks: list[Chunk], max_sources: int = 3) -> str:
    """LLM 답변 하단에 검색 기반 출처를 보강한다."""

    citations: list[str] = []
    seen: set[tuple] = set()
    for chunk in chunks:
        metadata = chunk.metadata
        key = (
            metadata.get("doc_short"),
            metadata.get("volume"),
            metadata.get("part"),
            metadata.get("chapter"),
            metadata.get("section"),
            metadata.get("page_start"),
            metadata.get("page_end"),
        )
        if key in seen:
            continue
        seen.add(key)
        citation = format_source_citation(metadata)
        if citation in answer:
            continue
        citations.append(citation)
        if len(citations) >= max_sources:
            break

    if not citations:
        return answer
    citation_block = " ".join(citations)
    if citation_block in answer:
        return answer
    return f"{answer.rstrip()}\n{citation_block}"


def build_user_prompt(question: str, chunks: list[Chunk]) -> str:
    """
    검색 청크를 컨텍스트 블록으로 나열하고 마지막에 질문을 붙인다.
    """

    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        label = _context_label(chunk.metadata)
        doc_short = chunk.metadata.get("doc_short", "")
        prefix = f"[{doc_short}] " if doc_short else ""
        blocks.append(f"[컨텍스트 {index}: {prefix}{label}]\n{chunk.text}")
    context = "\n\n".join(blocks) if blocks else "제공된 컨텍스트가 없습니다."
    return (
        f"{context}\n\n[질문]\n{question}\n\n"
        "답변 마지막 줄에는 반드시 [출처: 문서명, 조문/절, p.페이지] 형식의 출처를 적으세요."
    )
