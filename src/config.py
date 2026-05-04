"""프로젝트 설정과 경로 상수."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 런타임 의존성 안내는 README에서 다룬다.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass
class PdfSource:
    """인제스트 대상 PDF 문서 정보."""

    path: Path
    doc_type: str
    doc_name: str
    doc_short: str


PDF_SOURCES: list[PdfSource] = [
    PdfSource(
        path=ROOT_DIR / "BZ202603053039374.pdf",
        doc_type="policy_act",
        doc_name="건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수",
        doc_short="심평원",
    ),
    PdfSource(
        path=ROOT_DIR / "2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf",
        doc_type="insurance_policy",
        doc_name="신한 이지로운 실손의료보험(무배당) 약관",
        doc_short="약관",
    ),
    PdfSource(
        path=ROOT_DIR / "보상가이드북.pdf",
        doc_type="guide_book",
        doc_name="보상가이드북",
        doc_short="가이드북",
    ),
]

PDF_PATH: Path = PDF_SOURCES[0].path
CHUNKS_PATH: Path = ROOT_DIR / "data" / "processed" / "chunks.jsonl"
CHROMA_DIR: Path = ROOT_DIR / "data" / "index" / "chroma"
BM25_PATH: Path = ROOT_DIR / "data" / "index" / "bm25.pkl"

EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma3:4b")
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
RERANKER_ENABLED: bool = os.getenv("RERANKER_ENABLED", "true").lower() == "true"
OLLAMA_CANDIDATE_MODELS: list[str] = [
    "exaone3.5:7.8b-instruct",
    "qwen2.5:7b-instruct",
    "qwen2.5:14b-instruct",
    "gemma3:4b",
    "gemma3:1b",
]

TOP_K_DENSE: int = int(os.getenv("TOP_K_DENSE", "12"))
TOP_K_BM25: int = int(os.getenv("TOP_K_BM25", "12"))
TOP_K_FINAL: int = int(os.getenv("TOP_K_FINAL", "8"))
RRF_K: int = int(os.getenv("RRF_K", "60"))
CHUNK_TARGET_CHARS: int = int(os.getenv("CHUNK_TARGET_CHARS", "800"))
CHUNK_OVERLAP_CHARS: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "100"))
