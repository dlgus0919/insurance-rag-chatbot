"""RAG 프롬프트 템플릿."""

from __future__ import annotations

from src.parser.chunker import Chunk

SYSTEM_PROMPT = """당신은 대한민국 건강보험 고시 문서를 참고해 보험사 직원의 질문에 답하는 어시스턴트입니다.
규칙:
1. 반드시 제공된 참고 문맥(컨텍스트) 안의 정보만 사용해 답하세요.
2. 컨텍스트에 답이 없거나 모호하면 "제공된 문서에서 확인되지 않습니다."라고 답하세요.
3. 추측하거나 외부 지식을 사용하지 마세요.
4. 답변 마지막에 사용한 출처를 [출처: 편/부/장/절, p.페이지] 형식으로 나열하세요.
5. 한국어로 간결하고 정확하게 답하세요."""


def _page_label(metadata: dict) -> str:
    start = metadata.get("page_start")
    end = metadata.get("page_end")
    if start == end or end is None:
        return f"p.{start}"
    return f"p.{start}-{end}"


def _context_label(metadata: dict) -> str:
    parts = [
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
    return f"{context}\n\n[질문]\n{question}"
