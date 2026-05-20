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
    cloud_safe: bool = False
    insurance_company: str | None = None
    is_own_company: bool | None = None
    product_name: str | None = None
    product_type: str | None = None
    effective_date: str | None = None
    version: str | None = None
    requires_ocr: bool = False


@dataclass
class SpreadsheetSource:
    """관계형 적재 대상 원본 스프레드시트 정보."""

    path: Path
    source_id: str
    source_name: str
    data_type: str
    cloud_safe: bool = False


PDF_SOURCES: list[PdfSource] = [
    PdfSource(
        path=ROOT_DIR / "BZ202603053039374.pdf",
        doc_type="policy_act",
        doc_name="건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수",
        doc_short="심평원",
        cloud_safe=True,
    ),
    PdfSource(
        path=ROOT_DIR / "2.약관_신한 이지로운 실손의료보험(무배당)_20260401_0325.pdf",
        doc_type="insurance_policy",
        doc_name="신한 이지로운 실손의료보험(무배당) 약관",
        doc_short="약관",
        cloud_safe=True,
        insurance_company="신한EZ",
        is_own_company=True,
        product_name="신한 이지로운 실손의료보험(무배당)",
        product_type="실손",
        effective_date="2026-04-01",
    ),
    PdfSource(
        path=ROOT_DIR / "보상가이드북.pdf",
        doc_type="guide_book",
        doc_name="보상가이드북",
        doc_short="가이드북",
        cloud_safe=False,
    ),
    PdfSource(
        path=ROOT_DIR / "2.약관_신한 SOL 처음건강보험(무배당)(자동갱신형)_20260101.pdf",
        doc_type="insurance_policy",
        doc_name="신한 SOL 처음건강보험(무배당)(자동갱신형) 약관",
        doc_short="자사_SOL건강",
        cloud_safe=True,
        insurance_company="신한EZ",
        is_own_company=True,
        product_name="신한 SOL 처음건강보험(무배당)(자동갱신형)",
        product_type="건강",
        effective_date="2026-01-01",
        version="자동갱신형",
    ),
    PdfSource(
        path=ROOT_DIR / "2.약관_신한 SOL 처음운전자보험(무배당)_20260101.pdf",
        doc_type="insurance_policy",
        doc_name="신한 SOL 처음운전자보험(무배당) 약관",
        doc_short="자사_SOL운전자",
        cloud_safe=True,
        insurance_company="신한EZ",
        is_own_company=True,
        product_name="신한 SOL 처음운전자보험(무배당)",
        product_type="운전자",
        effective_date="2026-01-01",
    ),
    PdfSource(
        path=ROOT_DIR / "(별첨3)[별표 15] 표준약관(제5-13조제1항관련) (6).pdf",
        doc_type="insurance_policy",
        doc_name="표준약관(제5-13조제1항관련)",
        doc_short="표준약관",
        cloud_safe=True,
        product_type="표준약관",
    ),
    PdfSource(
        path=ROOT_DIR / "Claim 실무종합가이드.pdf",
        doc_type="ops_guide_scanned",
        doc_name="Claim 실무종합가이드",
        doc_short="실무가이드",
        cloud_safe=False,
        insurance_company="신한EZ",
        is_own_company=True,
        requires_ocr=True,
    ),
    PdfSource(
        path=ROOT_DIR / "소비자 상담 주요 사례집.pdf",
        doc_type="case_book_scanned",
        doc_name="소비자 상담 주요 사례집",
        doc_short="상담사례집",
        cloud_safe=True,
        requires_ocr=True,
    ),
]
DOC_SHORT_ORDER: list[str] = [source.doc_short for source in PDF_SOURCES]


def indexed_pdf_sources(sources: list[PdfSource] | None = None) -> list[PdfSource]:
    """클라우드에서 조회 가능한 인덱싱 대상 문서 목록을 반환한다."""

    selected_sources = PDF_SOURCES if sources is None else sources
    return [source for source in selected_sources if not source.requires_ocr and source.cloud_safe]


INDEXED_PDF_SOURCES: list[PdfSource] = indexed_pdf_sources()
INDEXED_DOC_SHORT_ORDER: list[str] = [source.doc_short for source in INDEXED_PDF_SOURCES]

SPREADSHEET_SOURCES: list[SpreadsheetSource] = [
    SpreadsheetSource(
        path=ROOT_DIR / "비급여표준모델_전체판(23.12-25.07)_250723(신한EZ전달본).xlsx",
        source_id="D8",
        source_name="비급여 표준 모델 전체판",
        data_type="nonpay_standard",
        cloud_safe=False,
    )
]

PDF_PATH: Path = PDF_SOURCES[0].path
CHUNKS_PATH: Path = ROOT_DIR / "data" / "processed" / "chunks.jsonl"
CHROMA_DIR: Path = ROOT_DIR / "data" / "index" / "chroma"
BM25_PATH: Path = ROOT_DIR / "data" / "index" / "bm25.pkl"
RELATIONAL_INDEX_DIR: Path = ROOT_DIR / "data" / "index" / "relational"
STANDARD_CODES_DB_PATH: Path = RELATIONAL_INDEX_DIR / "standard_codes.sqlite"

OFFLINE_MODE: bool = os.getenv("OFFLINE_MODE", "false").lower() == "true"
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
HF_MODEL_DOWNLOAD: bool = os.getenv("HF_MODEL_DOWNLOAD", "false").lower() == "true"
RERANKER_MODEL: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma3:4b")
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
RERANKER_ENABLED: bool = os.getenv("RERANKER_ENABLED", "true").lower() == "true"
LOG_DIR: str = os.getenv("LOG_DIR", "logs")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_DEFAULT_MODEL: str = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5.2-chat-latest")
OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "1500"))
ALLOW_OLLAMA: bool = os.getenv("ALLOW_OLLAMA", "true").lower() == "true"
CLOUD_DEPLOY: bool = os.getenv("CLOUD_DEPLOY", "false").lower() == "true"
SGLANG_BASE_URL: str = os.getenv("SGLANG_BASE_URL", "http://127.0.0.1:30000/v1")
SGLANG_API_KEY: str = os.getenv("SGLANG_API_KEY", "EMPTY")
SGLANG_DEFAULT_MODEL: str = os.getenv("SGLANG_DEFAULT_MODEL", "gpt-oss-20b")
SGLANG_REASONING_EFFORT: str = os.getenv("SGLANG_REASONING_EFFORT", "low")
SGLANG_CANDIDATE_MODELS: list[str] = [
    model.strip()
    for model in os.getenv("SGLANG_CANDIDATE_MODELS", SGLANG_DEFAULT_MODEL).split(",")
    if model.strip()
]
OLLAMA_CANDIDATE_MODELS: list[str] = [
    "exaone3.5:7.8b",
    "exaone3.5:7.8b-instruct",
    "timHan/llama3korean8B4QKM:latest",   # llama-3-Korean-Bllossom-8B Q4_K_M (커뮤니티 업로드)
    "qwen2.5:7b-instruct",
    "qwen2.5:14b-instruct",
    "gemma3:4b",
    "gemma3:1b",
]
DEFAULT_OPENAI_CANDIDATE_MODELS: list[str] = [
    "gpt-5.5",           # 최신 프론티어 — 복잡한 약관 해석·보상판정
    "gpt-5.2-chat-latest",  # 이전 세대 프론티어 인스턴트 — 일반 질의
    "gpt-5.4-mini",      # 중간 성능, 고속 — 퀵 코드 검색
    "gpt-5-mini",        # 경량/저비용 — 단순 조회·테스트
]
OPENAI_EXCLUDED_STREAMING_MODELS: set[str] = {
    "gpt-5.5-pro",
    "gpt-5.2-pro",
    "gpt-5.2-pro-2025-12-11",
}
OPENAI_CANDIDATE_MODELS: list[str] = [
    model.strip()
    for model in os.getenv("OPENAI_CANDIDATE_MODELS", ",".join(DEFAULT_OPENAI_CANDIDATE_MODELS)).split(",")
    if model.strip() and model.strip() not in OPENAI_EXCLUDED_STREAMING_MODELS
]

TOP_K_DENSE: int = int(os.getenv("TOP_K_DENSE", "12"))
TOP_K_BM25: int = int(os.getenv("TOP_K_BM25", "12"))
TOP_K_FINAL: int = int(os.getenv("TOP_K_FINAL", "8"))
RRF_K: int = int(os.getenv("RRF_K", "60"))
CHUNK_TARGET_CHARS: int = int(os.getenv("CHUNK_TARGET_CHARS", "800"))
CHUNK_OVERLAP_CHARS: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "100"))
