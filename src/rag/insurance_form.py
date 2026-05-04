"""약관 정형 검색 모드."""

from __future__ import annotations

from dataclasses import dataclass

from src.llm.prompt import append_retrieved_source_citations
from src.parser.chunker import Chunk
from src.rag.pipeline import RagPipeline, _hit_to_chunk

COVERAGE_TOPICS = ["질병급여", "질병비급여", "3대비급여"]
INSURANCE_FORM_TOP_K = 8
INSURANCE_DISCLAIMER = "본 답변은 검색 보조이며 최종 판정은 약관 원문과 사내 절차에 따릅니다."


@dataclass
class InsuranceFormInput:
    """약관 정형 검색 입력값."""

    mode: str
    primary: str
    coverage_topics: list[str] | None = None
    situation_note: str | None = None
    article_number: str | None = None
    include_appendix: bool = False


COVERAGE_SYSTEM_PROMPT = """당신은 실손의료보험 약관에 따라 보상가능 여부를 판정하는 어시스턴트입니다.
컨텍스트에서 '보상하지 않는 사항'과 '보상하는 사항' 조항을 모두 살펴
입력된 진단코드/시술명에 대해 선택된 보장종목별로 '보상 가능', '보상 불가', '조건부' 중 하나로 명확히 판정하세요.

## 출력 형식
- 질병급여 실손의료비: <판정> - <근거 1줄>
- 질병비급여 실손의료비: <판정> - <근거 1줄>
- 3대비급여 실손의료비: <판정> - <근거 1줄>

## 규칙
- 컨텍스트에 정보가 없는 보장종목은 "약관에서 확인되지 않습니다."라고 명시.
- 입력된 보장종목 외 항목은 출력에서 제외.
- 답변 마지막 줄에 자동 안내 부착: "본 답변은 검색 보조이며 최종 판정은 약관 원문과 사내 절차에 따릅니다."
- 출처는 [출처: 약관, 조문/별표, p.페이지] 형식으로 쓰세요."""

CLAUSE_SYSTEM_PROMPT = """당신은 실손의료보험 약관 조문을 정확히 인용해 보여주는 어시스턴트입니다.
컨텍스트에서 키워드와 가장 일치하는 조문 또는 별표를 찾아 다음 형식으로 답하세요.

## 출력 형식
[조문] <조문번호 / 제목>
[본문] <컨텍스트의 원문 인용 - 핵심 단락만, 임의 요약 금지>
[부가] <조건·예외 등이 있으면 항목별로>

## 규칙
- 본문은 컨텍스트의 원문을 그대로 인용. 윤문 금지.
- 조문번호가 입력으로 주어졌고 컨텍스트에 그 조문이 없으면 "해당 조문은 검색 결과에 없습니다."
- 출처는 [출처: 약관, 조문번호, p.페이지] 형식으로 쓰세요."""

KEYWORD_SYSTEM_PROMPT = """당신은 약관에서 키워드와 관련된 시술명·용어를 모아 보여주는 어시스턴트입니다.
컨텍스트에서 키워드와 직접 일치하거나 부분일치하는 항목들을 정리해 답하세요.

## 출력 형식
- <항목명>: <한 줄 요약 + 출처 페이지>

## 규칙
- 최대 6개 항목.
- 컨텍스트에 없으면 "검색 결과에 해당 키워드 항목이 없습니다."
- 답변 끝에 [출처: ...] 모음을 붙이세요."""


def build_form_query(form: InsuranceFormInput) -> str:
    """모드별 retrieve 쿼리 문자열을 만든다."""

    if form.mode == "coverage_judgment":
        topics = " ".join(form.coverage_topics or [])
        situation = form.situation_note or ""
        return f"{form.primary} 보상하지 않는 사항 보상하는 사항 {topics} {situation}".strip()
    if form.mode == "clause_lookup":
        article = f"제{form.article_number}조" if form.article_number else ""
        appendix = "별표" if form.include_appendix else ""
        return f"{form.primary} {article} {appendix}".strip()
    if form.mode == "keyword_search":
        return form.primary
    raise ValueError(f"unknown mode: {form.mode}")


def _context_block(chunks: list[Chunk]) -> str:
    """청크 목록을 약관 정형 검색 컨텍스트 블록으로 변환한다."""

    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        label_parts = [
            meta.get("chapter"),
            meta.get("section"),
            f"p.{meta.get('page_start', '?')}",
        ]
        label = " / ".join(str(part) for part in label_parts if part)
        blocks.append(f"[컨텍스트 {index}: {label}]\n{chunk.text}")
    return "\n\n".join(blocks) if blocks else "제공된 컨텍스트 없음"


def build_form_prompt(form: InsuranceFormInput, chunks: list[Chunk]) -> tuple[str, str]:
    """약관 정형 검색용 system/user 프롬프트 쌍을 반환한다."""

    context = _context_block(chunks)
    if form.mode == "coverage_judgment":
        topics = ", ".join(form.coverage_topics or COVERAGE_TOPICS)
        note = f"\n[상황 메모] {form.situation_note}" if form.situation_note else ""
        user = (
            f"{context}\n\n[대상] {form.primary}\n"
            f"[보장종목] {topics}{note}\n"
            "선택된 보장종목별로 판정하세요."
        )
        return COVERAGE_SYSTEM_PROMPT, user

    if form.mode == "clause_lookup":
        extras = []
        if form.article_number:
            extras.append(f"조문번호 제{form.article_number}조")
        if form.include_appendix:
            extras.append("별표 포함")
        condition = ", ".join(extras) if extras else "조건 없음"
        user = f"{context}\n\n[키워드] {form.primary}\n[조건] {condition}\n조문 또는 별표를 인용하세요."
        return CLAUSE_SYSTEM_PROMPT, user

    if form.mode == "keyword_search":
        user = f"{context}\n\n[키워드] {form.primary}\n관련 항목을 정리해 보여주세요."
        return KEYWORD_SYSTEM_PROMPT, user

    raise ValueError(f"unknown mode: {form.mode}")


def merge_insurance_doc_filter(extra_doc_filter: list[str] | None = None) -> list[str]:
    """약관 기본 필터와 사용자가 추가 선택한 문서를 합친다."""

    return list(dict.fromkeys(["약관"] + list(extra_doc_filter or [])))


def retrieve_insurance_form_chunks(
    pipeline: RagPipeline,
    form: InsuranceFormInput,
    extra_doc_filter: list[str] | None = None,
) -> tuple[list[Chunk], list[str]]:
    """약관 정형 검색용 청크와 실제 적용된 문서 필터를 반환한다."""

    doc_filter = merge_insurance_doc_filter(extra_doc_filter)
    hits = pipeline.retrieve_hits(build_form_query(form), top_k=INSURANCE_FORM_TOP_K, doc_filter=doc_filter)
    return [_hit_to_chunk(hit) for hit in hits], doc_filter


def generate_insurance_form_answer(
    pipeline: RagPipeline,
    form: InsuranceFormInput,
    chunks: list[Chunk],
    temperature: float = 0.1,
) -> str:
    """검색 청크를 기반으로 약관 정형 검색 답변을 생성한다."""

    system, user = build_form_prompt(form, chunks)
    answer = pipeline.llm.generate(user, system=system, temperature=temperature)
    answer = append_retrieved_source_citations(answer, chunks)
    if form.mode == "coverage_judgment" and INSURANCE_DISCLAIMER not in answer:
        answer = f"{answer.rstrip()}\n\n{INSURANCE_DISCLAIMER}"
    return answer


def run_insurance_form(
    pipeline: RagPipeline,
    form: InsuranceFormInput,
    extra_doc_filter: list[str] | None = None,
    temperature: float = 0.1,
) -> tuple[str, list[Chunk]]:
    """약관 정형 검색을 실행하고 답변과 출처 청크를 반환한다."""

    chunks, _ = retrieve_insurance_form_chunks(pipeline, form, extra_doc_filter)
    answer = generate_insurance_form_answer(pipeline, form, chunks, temperature)
    return answer, chunks
