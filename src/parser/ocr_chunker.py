"""OCR 구조화 추출물을 RAG Chunk로 변환한다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.parser.chunker import Chunk, EXTENDED_META_DEFAULTS, _extract_codes, _split_text
from src.parser.ocr_postprocess import is_noise_text_block, normalize_ocr_text

if TYPE_CHECKING:
    from src.config import PdfSource


def _base_meta(doc_source: "PdfSource", page_no: int, engine: str, content_type: str, block_info: dict, text: str) -> dict:
    codes = _extract_codes(text)
    metadata = {
        **EXTENDED_META_DEFAULTS,
        "doc_short": doc_source.doc_short,
        "doc_name": doc_source.doc_name,
        "doc_type": doc_source.doc_type,
        "pdf_filename": doc_source.path.name,
        "page_start": page_no + 1,
        "page_end": page_no + 1,
        "volume": None,
        "part": None,
        "chapter": None,
        "section": None,
        "codes": codes,
        "is_code_table": content_type == "table" or len(codes) >= 5,
        "char_count": len(text),
        "content_type": content_type,
        "source_method": f"ocr_{engine}",
        "confidence": block_info.get("confidence", 1.0),
        "bbox": block_info.get("bbox"),
    }
    for field in (
        "insurance_company",
        "is_own_company",
        "product_name",
        "product_type",
        "effective_date",
        "version",
    ):
        value = getattr(doc_source, field, None)
        if value is not None:
            metadata[field] = value
    return metadata


def _table_json_path(text_path: Path) -> Path:
    if text_path.name.endswith("_text.txt"):
        return text_path.with_name(text_path.name.replace("_text.txt", ".json"))
    return text_path.with_suffix(".json")


def _figure_caption_path(image_path: Path) -> Path:
    return image_path.with_name(f"{image_path.stem}_caption.txt")


def chunk_from_extracted(
    doc_short: str,
    extracted_dir: Path,
    doc_source: "PdfSource",
    id_offset: int = 0,
) -> list[Chunk]:
    """data/extracted/<doc_short>/manifest.json을 읽어 OCR Chunk 목록을 생성한다."""

    manifest_path = extracted_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"OCR manifest가 없습니다: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    next_index = id_offset

    for page_info in manifest.get("pages", []):
        page_no = int(page_info["page_no"])
        engine = str(page_info.get("engine", "ppstructure"))

        for block_info in page_info.get("blocks", []):
            block_type = str(block_info.get("type", "text"))
            relative_file = block_info.get("file")
            if not relative_file:
                continue
            file_path = extracted_dir / relative_file
            if not file_path.exists():
                continue

            if block_type == "table":
                text = file_path.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                metadata = _base_meta(doc_source, page_no, engine, "table", block_info, text)
                json_path = _table_json_path(file_path)
                metadata["table_json"] = json_path.read_text(encoding="utf-8") if json_path.exists() else "{}"
                chunks.append(Chunk(id=f"{doc_short}_ch_{next_index:06d}", text=text, metadata=metadata))
                next_index += 1
                continue

            if block_type == "figure":
                caption_path = _figure_caption_path(file_path)
                caption = caption_path.read_text(encoding="utf-8").strip() if caption_path.exists() else ""
                caption = normalize_ocr_text(caption)
                if not caption:
                    continue
                metadata = _base_meta(doc_source, page_no, engine, "figure", block_info, caption)
                metadata["image_path"] = str(file_path)
                chunks.append(Chunk(id=f"{doc_short}_ch_{next_index:06d}", text=caption, metadata=metadata))
                next_index += 1
                continue

            text = normalize_ocr_text(file_path.read_text(encoding="utf-8"))
            if not text or is_noise_text_block(text):
                continue
            for piece in _split_text(text, target_chars=800, overlap_chars=100):
                metadata = _base_meta(doc_source, page_no, engine, "text", block_info, piece)
                chunks.append(Chunk(id=f"{doc_short}_ch_{next_index:06d}", text=piece, metadata=metadata))
                next_index += 1

    return chunks
