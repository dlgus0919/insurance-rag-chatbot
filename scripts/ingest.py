#!/usr/bin/env python3
"""PDF를 청크와 검색 인덱스로 변환하는 스크립트."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.parser.chunker import chunk_pages, save_chunks
from src.parser.pdf_parser import parse_pdf


def build_chunks() -> None:
    """PDF에서 chunks.jsonl을 생성한다."""

    started = time.perf_counter()
    print("[M1] PDF 파싱 시작")
    pages = parse_pdf(config.PDF_PATH)
    non_empty_pages = sum(1 for _, text in pages if text.strip())
    print(f"[M1] PDF 파싱 완료: 전체 {len(pages)}페이지, 텍스트 {non_empty_pages}페이지")

    print("[M1] 청킹 시작")
    chunks = chunk_pages(
        pages,
        target_chars=config.CHUNK_TARGET_CHARS,
        overlap_chars=config.CHUNK_OVERLAP_CHARS,
    )
    save_chunks(chunks, config.CHUNKS_PATH)

    lengths = [chunk.metadata["char_count"] for chunk in chunks]
    code_chunks = sum(1 for chunk in chunks if chunk.metadata["codes"])
    avg_len = statistics.mean(lengths) if lengths else 0
    ratio = (code_chunks / len(chunks) * 100) if chunks else 0
    elapsed = time.perf_counter() - started

    print(f"[M1] 청킹 완료: {config.CHUNKS_PATH}")
    print(f"[M1] 청크 수: {len(chunks):,}")
    print(f"[M1] 평균 길이: {avg_len:.1f}자")
    print(f"[M1] 코드 포함 청크: {code_chunks:,}개 ({ratio:.1f}%)")
    print(f"[M1] 소요 시간: {elapsed:.1f}초")


def main() -> None:
    parser = argparse.ArgumentParser(description="보험 고시 PDF 인제스트")
    parser.add_argument("--stage", choices=["chunks", "index", "all"], default="all")
    args = parser.parse_args()

    if args.stage in {"chunks", "all"}:
        build_chunks()
    if args.stage in {"index", "all"}:
        raise SystemExit("M2에서 인덱싱 단계를 구현합니다. 현재는 --stage chunks를 사용하세요.")


if __name__ == "__main__":
    main()
