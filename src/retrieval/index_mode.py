"""RAG 인덱스 모드별 경로 해석 유틸."""

from __future__ import annotations

import re
from pathlib import Path

from src import config

INDEX_MODES = ("default", "v2_only", "v1_v2_combined")


def resolve_effective_index_mode(question: str, requested_index_mode: str = "default") -> str:
    """질문 유형에 맞춰 기본 운영 인덱스를 안전하게 라우팅한다."""

    requested = (requested_index_mode or "default").strip().lower()
    if requested != "default":
        return requested

    text = re.sub(r"\s+", "", question or "").lower()
    if not text:
        return "default"

    if any(keyword in text for keyword in ("원본ocr", "보정본", "ocr비교", "원본+보정본", "v1", "v2")):
        return "v1_v2_combined"

    corrected_ocr_keywords = (
        "실무가이드",
        "수술종수",
        "수술분류표",
        "신1-5종",
        "1-5종",
        "1-3종",
        "장해",
        "지급률",
        "상담사례집",
        "고지의무",
        "알릴의무",
        "계약전알릴의무",
    )
    if any(keyword in text for keyword in corrected_ocr_keywords):
        return "v2_only"

    return "default"


def resolve_index_paths(mode: str) -> tuple[Path, Path]:
    """인덱스 모드 이름을 (bm25_path, chroma_dir) 경로로 변환한다."""

    normalized = (mode or "default").strip().lower()
    if normalized == "default":
        return config.BM25_PATH, config.CHROMA_DIR
    if normalized == "v2_only":
        root = config.ROOT_DIR / "data" / "index_v2_manual"
        return root / "bm25.pkl", root / "chroma"
    if normalized == "v1_v2_combined":
        root = config.ROOT_DIR / "data" / "index_v1_v2_combined"
        return root / "bm25.pkl", root / "chroma"
    raise ValueError(f"지원하지 않는 인덱스 모드입니다: {mode}")
