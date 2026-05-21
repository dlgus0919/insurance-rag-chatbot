"""RAG 인덱스 모드별 경로 해석 유틸."""

from __future__ import annotations

from pathlib import Path

from src import config

INDEX_MODES = ("default", "v2_only", "v1_v2_combined")


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
