#!/usr/bin/env python3
"""Smoke QA 평가 스크립트."""

from __future__ import annotations

import json
import re
import sys
from argparse import ArgumentParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.prompt import SYSTEM_PROMPT, append_retrieved_source_citations, build_user_prompt
from src.llm.ollama_client import OllamaClient
from src.parser.chunker import Chunk
from src.rag.pipeline import RagPipeline
from src.retrieval.bm25 import BM25Index
from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore

SMOKE_QA_PATH = ROOT / "eval" / "smoke_qa.jsonl"
SMOKE_QA_V2_PATH = ROOT / "eval" / "smoke_qa_v2.jsonl"
OCR_QA_PATH = ROOT / "eval" / "ocr_qa.jsonl"


def load_questions(path: Path = SMOKE_QA_PATH) -> list[dict]:
    """JSONL 평가 문항을 읽는다."""

    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def hit_matches_expected_page(hit, expected_pages: list[int]) -> bool:
    """검색 결과 페이지 범위가 정답 페이지 중 하나를 포함하는지 확인한다."""

    start = hit.metadata.get("page_start")
    end = hit.metadata.get("page_end", start)
    if start is None:
        return False
    return any(start <= page <= end for page in expected_pages)


def answer_mentions_expected_page(answer: str, expected_pages: list[int]) -> bool:
    """
    답변 텍스트에 정답 페이지 번호가 언급됐는지 확인한다.

    단일 페이지 형식(p.38)과 범위 형식(p.36-38)을 모두 인정한다.
    범위 형식은 expected_pages 중 하나가 범위 안에 있으면 정답이다.
    """

    for page in expected_pages:
        single_page_pattern = rf"p\.\s*{page}(?!\d)"
        if re.search(single_page_pattern, answer):
            return True

    for match in re.finditer(r"p\.\s*(\d+)\s*-\s*(\d+)", answer):
        range_start, range_end = int(match.group(1)), int(match.group(2))
        if range_start > range_end:
            range_start, range_end = range_end, range_start
        if any(range_start <= page <= range_end for page in expected_pages):
            return True

    return False


def answer_mentions_expected_codes(answer: str, expected_codes: list[str]) -> bool:
    """답변 텍스트에 기대 코드가 모두 포함됐는지 확인한다."""

    if not expected_codes:
        return True
    normalized = answer.upper()
    return all(code.upper() in normalized for code in expected_codes)


def answer_matches_verdict(answer: str, expected_verdict: str) -> bool:
    """답변이 기대 판정(불가/판정필요)과 일치하는지 확인한다."""

    if expected_verdict == "불가":
        return any(kw in answer for kw in ["보상하지 않", "지급하지 않", "면책", "보상 불가", "청구 불가"])
    if expected_verdict == "판정필요":
        return any(kw in answer for kw in ["약관", "조항", "확인", "판정", "경우에 따라"])
    return True


def answer_mentions_expected_grades(answer: str, expected_grades: dict | None) -> tuple[int, int]:
    """
    답변에서 수술종수 값이 올바르게 언급됐는지 확인한다.

    Returns: (correct_count, total_count)
    """

    if not expected_grades:
        return 0, 0

    correct = 0
    compact_answer = re.sub(r"\s+", "", answer)
    for col, value in expected_grades.items():
        col_text = str(col)
        value_text = str(value)
        col_pattern = re.escape(col_text)
        value_pattern = re.escape(value_text)
        direct_pattern = rf"{col_pattern}\s*(?:[:=]|은|는|이|가)?\s*{value_pattern}\s*종?"
        if re.search(direct_pattern, answer):
            correct += 1
            continue

        compact_col = re.sub(r"\s+", "", col_text)
        compact_value = re.sub(r"\s+", "", value_text)
        col_index = compact_answer.find(compact_col)
        if col_index >= 0:
            after_col = compact_answer[col_index + len(compact_col) : col_index + len(compact_col) + 16]
            if re.search(rf"^(?:[:=]|은|는|이|가)?{re.escape(compact_value)}종?", after_col):
                correct += 1
                continue

        if len(expected_grades) == 1 and re.search(rf"(?<!\d){value_pattern}\s*종?(?!\d)", answer):
            correct += 1
            continue

        if value_text in answer and col_text in answer:
            correct += 1

    return correct, len(expected_grades)


def answer_mentions_expected_rate(answer: str, expected_rate: str | None) -> bool:
    """답변에 기대 지급률(숫자+%)이 포함됐는지 확인한다."""

    if not expected_rate:
        return False
    value = str(expected_rate).rstrip("%")
    return re.search(rf"(?<!\d){re.escape(value)}\s*%?(?!\d)", answer) is not None


def answer_mentions_expected_keywords(answer: str, expected_keywords: list[str] | None) -> tuple[int, int]:
    """expected_keywords 중 답변에 포함된 비율을 반환한다."""

    if not expected_keywords:
        return 1, 1
    matched = sum(1 for keyword in expected_keywords if keyword in answer)
    return matched, len(expected_keywords)


def filter_chunks_by_doc(chunks, doc_sources: list[str] | None):
    """doc_sources가 있으면 해당 문서 출처의 청크/검색 결과만 남긴다."""

    if not doc_sources:
        return chunks
    allowed = set(doc_sources)
    return [chunk for chunk in chunks if chunk.metadata.get("doc_short") in allowed]


def _hit_to_chunk(hit) -> Chunk:
    metadata = dict(hit.metadata)
    metadata.setdefault("char_count", len(hit.document))
    return Chunk(id=hit.id, text=hit.document, metadata=metadata)


def parse_args(argv: list[str] | None = None):
    """평가 CLI 인자를 파싱한다."""

    parser = ArgumentParser(description="Smoke QA 평가 스크립트")
    parser.add_argument("--v2", action="store_true", help="약관 정형 모드 평가 문항을 사용합니다.")
    parser.add_argument("--ocr", action="store_true", help="OCR 문서 평가 문항을 사용합니다.")
    args = parser.parse_args(argv)
    if args.v2 and args.ocr:
        parser.error("--v2와 --ocr는 동시에 사용할 수 없습니다.")
    return args


def main() -> None:
    args = parse_args()
    if args.ocr:
        question_path = OCR_QA_PATH
    elif args.v2:
        question_path = SMOKE_QA_V2_PATH
    else:
        question_path = SMOKE_QA_PATH
    questions = load_questions(question_path)
    if not questions:
        raise SystemExit("평가 문항이 없습니다.")
    if not config.BM25_PATH.exists():
        raise SystemExit("BM25 인덱스가 없습니다. `python scripts/ingest.py --stage index`를 먼저 실행하세요.")

    llm = OllamaClient(config.OLLAMA_HOST, config.OLLAMA_MODEL)
    llm_available = llm.health()
    if not llm_available and args.ocr:
        print("Ollama 서버에 연결할 수 없어 --ocr LLM 답변 평가는 skip하고 retrieval-only로 진행합니다.")
    elif not llm_available:
        raise SystemExit("Ollama 서버에 연결할 수 없습니다. Ollama 데스크톱 앱 또는 `ollama serve`를 실행하세요.")

    embedder = Embedder(config.EMBEDDING_MODEL)
    vector_store = VectorStore(config.CHROMA_DIR)
    bm25 = BM25Index.load(config.BM25_PATH)
    pipeline = RagPipeline(
        embedder=embedder,
        vector_store=vector_store,
        bm25=bm25,
        llm=llm,
        top_k_dense=config.TOP_K_DENSE,
        top_k_bm25=config.TOP_K_BM25,
        top_k_final=config.TOP_K_FINAL,
        rrf_k=config.RRF_K,
    )
    indexed_doc_sources = {metadata.get("doc_short") for metadata in bm25.metadatas if metadata.get("doc_short")}

    recall_hits = 0
    page_hits = 0
    verdict_hits = 0
    doc_hits = 0
    evaluated = 0
    answer_evaluated = 0
    skipped = 0
    grade_correct_total = 0
    grade_total = 0
    rate_hits = 0
    rate_evaluated = 0
    keyword_correct = 0
    keyword_total = 0

    for index, item in enumerate(questions, start=1):
        question = item["question"]
        expected_pages = item["expected_pages"]
        doc_sources = item.get("doc_sources")
        missing_sources = set(doc_sources or []) - indexed_doc_sources
        if item.get("type") == "cross_doc" and missing_sources:
            skipped += 1
            missing_label = ", ".join(sorted(missing_sources))
            print(f"[{index:02d}] {item['type']} skipped({missing_label} 미인덱싱)")
            continue

        fused_hits, _ = pipeline.retrieve_hits(question, top_k=8, doc_filter=doc_sources)
        fused_hits = filter_chunks_by_doc(fused_hits, doc_sources)
        chunks = [_hit_to_chunk(hit) for hit in fused_hits]

        retrieved = any(hit_matches_expected_page(hit, expected_pages) for hit in fused_hits)
        recall_hits += int(retrieved)

        item_type = item.get("type")
        page_ok = code_ok = verdict_ok = doc_ok = False
        grade_result = None
        rate_ok = None
        keyword_result = None
        if llm_available:
            prompt = build_user_prompt(question, chunks)
            num_ctx = None
            if args.ocr:
                prompt += "\n\n평가용 출력 지시: 정답에 필요한 수치와 핵심 근거만 2문장 이내로 답하세요."
                num_ctx = min(config.OLLAMA_NUM_CTX, 4096)
            answer = llm.generate(prompt, system=SYSTEM_PROMPT, temperature=0.2, num_ctx=num_ctx)
            answer = append_retrieved_source_citations(answer, chunks)
            page_ok = answer_mentions_expected_page(answer, expected_pages)
            code_ok = answer_mentions_expected_codes(answer, item.get("expected_codes", []))
            verdict_ok = answer_matches_verdict(answer, item.get("expected_verdict", ""))
            doc_ok = all(hit.metadata.get("doc_short") in set(doc_sources or []) for hit in fused_hits) if doc_sources else True
            page_hits += int(page_ok)
            verdict_hits += int(verdict_ok)
            doc_hits += int(doc_ok)
            answer_evaluated += 1

            if args.ocr and item_type == "surgery_grade":
                grade_result = answer_mentions_expected_grades(answer, item.get("expected_grades"))
                grade_correct_total += grade_result[0]
                grade_total += grade_result[1]
            if args.ocr and item_type == "disability_rate":
                rate_ok = answer_mentions_expected_rate(answer, item.get("expected_rate"))
                rate_hits += int(rate_ok)
                rate_evaluated += 1
            if args.ocr and item_type in {"surgery_description", "disability_criteria", "consultation"}:
                keyword_result = answer_mentions_expected_keywords(answer, item.get("expected_keywords"))
                keyword_correct += keyword_result[0]
                keyword_total += keyword_result[1]

        top_pages = [
            f"{hit.metadata.get('page_start')}-{hit.metadata.get('page_end')}"
            if hit.metadata.get("page_start") != hit.metadata.get("page_end")
            else str(hit.metadata.get("page_start"))
            for hit in fused_hits[:3]
        ]
        if llm_available:
            metric_parts = []
            if grade_result:
                metric_parts.append(f"grade={grade_result[0]}/{grade_result[1]}")
            if rate_ok is not None:
                metric_parts.append(f"rate={'OK' if rate_ok else 'MISS'}")
            if keyword_result:
                metric_parts.append(f"keywords={keyword_result[0]}/{keyword_result[1]}")
            print(
                f"[{index:02d}] {item['type']} recall={'OK' if retrieved else 'MISS'} "
                f"page={'OK' if page_ok else 'MISS'} "
                f"code={'OK' if code_ok else 'MISS'} top_pages={top_pages}"
                + (f" verdict={'OK' if verdict_ok else 'MISS'} doc={'OK' if doc_ok else 'MISS'}" if item_type == "coverage_judgment" else "")
                + (f" {' '.join(metric_parts)}" if metric_parts else "")
            )
        else:
            print(f"[{index:02d}] {item['type']} recall={'OK' if retrieved else 'MISS'} top_pages={top_pages} llm=SKIP")
        evaluated += 1

    if evaluated == 0:
        raise SystemExit("평가 가능한 문항이 없습니다.")
    recall = recall_hits / evaluated
    page_accuracy = page_hits / answer_evaluated if answer_evaluated else None
    print(f"retrieval recall@8: {recall:.3f}")
    if page_accuracy is None:
        print("출처 페이지 정확도: N/A (LLM skip)")
    else:
        print(f"출처 페이지 정확도: {page_accuracy:.3f}")
    if args.ocr:
        if grade_total:
            print(f"수술종수 정확도 (grade_accuracy): {grade_correct_total / grade_total:.3f}")
        else:
            print("수술종수 정확도 (grade_accuracy): N/A")
        if rate_evaluated:
            print(f"장해 지급률 정확도 (rate_accuracy): {rate_hits / rate_evaluated:.3f}")
        else:
            print("장해 지급률 정확도 (rate_accuracy): N/A")
        if keyword_total:
            print(f"키워드 포함율 (keyword_coverage): {keyword_correct / keyword_total:.3f}")
        else:
            print("키워드 포함율 (keyword_coverage): N/A")
    if args.v2:
        print(f"판정 키워드 일치율: {verdict_hits / evaluated:.3f}")
        print(f"문서 출처 일치율: {doc_hits / evaluated:.3f}")
    if skipped:
        print(f"skipped: {skipped}")

    if args.v2:
        return
    if args.ocr:
        if recall < 0.7:
            raise SystemExit(1)
        if grade_total > 0 and grade_correct_total / grade_total < 0.6:
            raise SystemExit(1)
        if rate_evaluated > 0 and rate_hits / rate_evaluated < 0.7:
            raise SystemExit(1)
        return
    if page_accuracy is None:
        raise SystemExit(1)
    if recall < 0.7 or page_accuracy < 0.6:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
