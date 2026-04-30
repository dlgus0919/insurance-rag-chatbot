"""프로젝트 설정과 경로 상수."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 런타임 의존성 안내는 README에서 다룬다.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]

PDF_PATH: Path = ROOT_DIR / "BZ202603053039374.pdf"
CHUNKS_PATH: Path = ROOT_DIR / "data" / "processed" / "chunks.jsonl"
CHROMA_DIR: Path = ROOT_DIR / "data" / "index" / "chroma"
BM25_PATH: Path = ROOT_DIR / "data" / "index" / "bm25.pkl"

EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")

TOP_K_DENSE: int = int(os.getenv("TOP_K_DENSE", "12"))
TOP_K_BM25: int = int(os.getenv("TOP_K_BM25", "12"))
TOP_K_FINAL: int = int(os.getenv("TOP_K_FINAL", "8"))
RRF_K: int = int(os.getenv("RRF_K", "60"))
CHUNK_TARGET_CHARS: int = int(os.getenv("CHUNK_TARGET_CHARS", "800"))
CHUNK_OVERLAP_CHARS: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "100"))
