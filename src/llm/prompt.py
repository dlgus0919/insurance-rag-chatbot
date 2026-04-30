"""RAG 프롬프트 템플릿."""

from __future__ import annotations

from src.parser.chunker import Chunk

SYSTEM_PROMPT = """당신은 보험사 직원의 질문에 답하는 어시스턴트입니다. 참고 문서에는 건강보험 고시(심평원), 실손의료보험 약관, 보상가이드북 등이 포함될 수 있습니다.
규칙:
1. 반드시 제공된 참고 문맥(컨텍스트) 안의 정보만 사용해 답하세요.
2. 컨텍스트에 답이 없거나 모호하면 "제공된 문서에서 확인되지 않습니다."라고 답하세요.
3. 추측하거나 외부 지식을 사용하지 마세요.
4. 답변 마지막에 반드시 아래 형식으로 출처를 기재하세요. 생략하지 마세요.
   형식: [출처: 문서명, 조문/절, p.페이지]
   예시: [출처: 심평원, 제1절 진찰료, p.101]
5. 한국어로 간결하고 정확하게 답하세요."""


def _page_label(metadata: dict) -> str:
    start = metadata.get("page_start")
    end = metadata.get("page_end")
    if start == end or end is None:
        return f"p.{start}"
    return f"p.{start}-{end}"


def _context_label(metadata: dict) -> str:
    doc_name = metadata.get("doc_name") or metadata.get("doc_short", "")
    parts = [
        doc_name,
        metadata.get("volume"),
        metadata.get("part"),
        metadata.get("chapter"),
        metadata.get("section"),
        _page_label(metadata),
    ]
    return " / ".join(str(part) for part in parts if part)


def build_user_prompt(question: str, chunks: list[Chunk]) -> str:
    """
    검색 청크를 컨텍스트 블록으로 나열하고 마지막에 질문을 붙인다.
    """

    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        label = _context_label(chunk.metadata)
        blocks.append(f"[컨텍스트 {index}] {label}\n{chunk.text}")
    context = "\n\n".join(blocks) if blocks else "제공된 컨텍스트가 없습니다."
    return (
        f"{context}\n\n[질문]\n{question}\n\n"
        "답변 마지막 줄에는 반드시 [출처: 문서명, 조문/절, p.페이지] 형식의 출처를 적으세요."
    )
