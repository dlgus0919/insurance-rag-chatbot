"""퀵 코드 검색 모드."""

from __future__ import annotations

from src.parser.chunker import Chunk
from src.rag.pipeline import RagPipeline, _hit_to_chunk

QUICK_CODE_TOP_K = 6

QUICK_SYSTEM_PROMPT = """당신은 보험사 직원의 시술/수술 코드 조회를 돕는 어시스턴트입니다.
아래 컨텍스트에서 입력된 시술명에 가장 정확히 일치하는 코드와 분류명을 우선 추출하세요.

## 출력 형식 (반드시 이 순서·라벨로)
[코드] <코드> - <분류명>
[분류 / 점수] <분류번호> / <점수>
{사용자 옵션에 따라 아래 줄 추가}
[산정지침 요약] <간단 요약 1-2문장>
[보상] <실손 약관 기준 보상 가능/불가/조건부> - <근거 한 줄>

## 규칙
- 코드를 찾을 수 없으면 "[코드] 정확한 코드를 찾지 못했습니다."를 출력하고 일반 모드 사용을 권유.
- 컨텍스트에 없는 정보는 추측하지 말고 해당 줄 자체를 생략.
- 출처는 본문 끝에 [출처: 문서명, p.페이지] 형식으로 붙이세요."""


def determine_doc_filter(include_coverage: bool) -> list[str]:
    """보상 옵션에 따라 퀵 코드 검색의 기본 문서 필터를 정한다."""

    return ["심평원", "약관"] if include_coverage else ["심평원"]


def merge_doc_filters(auto_filter: list[str], selected_docs: list[str] | None) -> list[str]:
    """자동 필터와 사용자가 선택한 문서를 순서 보존 합집합으로 합친다."""

    return list(dict.fromkeys(auto_filter + list(selected_docs or [])))


def build_quick_code_prompt(
    procedure_name: str,
    chunks: list[Chunk],
    include_summary: bool,
    include_coverage: bool,
) -> tuple[str, str]:
    """시스템 프롬프트와 유저 프롬프트를 조립한다."""

    sections = ["[코드] / [분류 / 점수] 두 줄은 항상 출력."]
    if include_summary:
        sections.append("[산정지침 요약] 줄 추가.")
    if include_coverage:
        sections.append("[보상] 줄 추가 - 실손 약관 컨텍스트가 있을 때만.")
    instructions = " ".join(sections)

    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        label = f"{meta.get('doc_short', '')} p.{meta.get('page_start', '?')}"
        blocks.append(f"[컨텍스트 {index}: {label}]\n{chunk.text}")
    context_block = "\n\n".join(blocks) if blocks else "제공된 컨텍스트 없음"

    user_prompt = (
        f"{context_block}\n\n[시술명] {procedure_name}\n"
        f"[지시] {instructions}\n"
        "답변 마지막에 [출처: 문서명, p.페이지]를 적으세요."
    )
    return QUICK_SYSTEM_PROMPT, user_prompt


def retrieve_quick_code_chunks(
    pipeline: RagPipeline,
    procedure_name: str,
    include_coverage: bool,
    selected_docs: list[str] | None = None,
) -> tuple[list[Chunk], list[str]]:
    """퀵 코드 검색용 청크와 실제 적용된 문서 필터를 반환한다."""

    doc_filter = merge_doc_filters(determine_doc_filter(include_coverage), selected_docs)
    hits = pipeline.retrieve_hits(procedure_name, top_k=QUICK_CODE_TOP_K, doc_filter=doc_filter)
    return [_hit_to_chunk(hit) for hit in hits], doc_filter


def generate_quick_code_answer(
    pipeline: RagPipeline,
    procedure_name: str,
    chunks: list[Chunk],
    include_summary: bool,
    include_coverage: bool,
    temperature: float = 0.0,
) -> str:
    """검색 청크를 기반으로 퀵 코드 답변을 생성한다."""

    system, user = build_quick_code_prompt(procedure_name, chunks, include_summary, include_coverage)
    return pipeline.llm.generate(user, system=system, temperature=temperature)


def run_quick_code(
    pipeline: RagPipeline,
    procedure_name: str,
    include_summary: bool,
    include_coverage: bool,
    temperature: float = 0.0,
    selected_docs: list[str] | None = None,
) -> tuple[str, list[Chunk]]:
    """퀵 코드 검색을 실행하고 답변과 출처 청크를 반환한다."""

    chunks, _ = retrieve_quick_code_chunks(pipeline, procedure_name, include_coverage, selected_docs)
    answer = generate_quick_code_answer(pipeline, procedure_name, chunks, include_summary, include_coverage, temperature)
    return answer, chunks
