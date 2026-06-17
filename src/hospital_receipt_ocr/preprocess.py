"""Input validation, image loading, and document type helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PIL import Image, ImageOps

from .models import DocumentType, SourceDocument


SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MAX_FILE_BYTES = 30 * 1024 * 1024
MIN_IMAGE_SIDE = 300
MAX_IMAGE_SIDE = 10000


def collect_input_files(input_file: Path | None = None, input_dir: Path | None = None) -> list[Path]:
    if bool(input_file) == bool(input_dir):
        raise ValueError("--input-file 또는 --input-dir 중 정확히 하나를 지정해야 합니다.")
    if input_file:
        return [validate_input_file(input_file)]
    assert input_dir is not None
    if not input_dir.exists() or not input_dir.is_dir():
        raise ValueError(f"입력 폴더가 존재하지 않습니다: {input_dir}")
    files = [
        validate_input_file(path)
        for path in sorted(input_dir.iterdir(), key=lambda p: _natural_sort_key(p.name))
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]
    if not files:
        raise ValueError(f"처리 가능한 이미지 파일이 없습니다: {input_dir}")
    return files


def validate_input_file(path: Path) -> Path:
    if not path.exists() or not path.is_file():
        raise ValueError(f"입력 파일이 존재하지 않습니다: {path}")
    if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"지원하지 않는 이미지 형식입니다: {path.name}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"빈 파일입니다: {path.name}")
    if size > MAX_FILE_BYTES:
        raise ValueError(f"파일 크기가 너무 큽니다: {path.name}")
    with Image.open(path) as image:
        width, height = image.size
    if min(width, height) < MIN_IMAGE_SIDE or max(width, height) > MAX_IMAGE_SIDE:
        raise ValueError(f"지원 범위를 벗어난 이미지 크기입니다: {path.name} ({width}x{height})")
    return path


def load_rgb_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def make_document_id(path: Path, page_index: int = 0) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"doc_{page_index + 1:03d}_{digest}"


def make_source_document(path: Path, image: Image.Image, page_index: int, document_type: DocumentType, reason: str) -> SourceDocument:
    return SourceDocument(
        document_id=make_document_id(path, page_index),
        source_file=path.name,
        page_index=page_index,
        width=image.width,
        height=image.height,
        document_type=document_type,
        classification_reason=reason,
    )


def classify_document_from_text(text: str, fallback: DocumentType = "unknown") -> tuple[DocumentType, str]:
    normalized = re.sub(r"\s+", "", text or "")
    if "진료비세부산정내역" in normalized:
        return "medical_detail_statement", "title:진료비세부산정내역"

    scores: dict[DocumentType, int] = {
        "medical_bill_receipt": _keyword_score(
            normalized,
            (
                "진료비계산서",
                "영수증번호",
                "금액산정내용",
                "납부한금액",
                "납부할금액",
                "카드",
                "수납자",
                "사업자등록번호",
                "상한액초과금",
            ),
        ),
        "diagnosis_certificate": _keyword_score(
            normalized,
            (
                "진단서",
                "질병분류기호",
                "임상적추정",
                "최종진단",
                "진단연월일",
                "치료내용",
                "치료에대한소견",
            ),
        ),
        "surgery_certificate": _keyword_score(
            normalized,
            (
                "수술확인서",
                "술확인서",
                "수술일자",
                "술일자",
                "수술명",
                "술명",
                "위와같이확인함",
            ),
        ),
    }
    document_type, score = max(scores.items(), key=lambda item: item[1])
    if score >= 2:
        return document_type, f"weighted-keywords:{document_type}:{score}"
    return fallback, "fallback" if fallback != "unknown" else "no-title-match"


def document_type_from_mode(mode: str) -> DocumentType:
    mapping: dict[str, DocumentType] = {
        "detail_statement": "medical_detail_statement",
        "medical_detail_statement": "medical_detail_statement",
        "receipt": "medical_bill_receipt",
        "medical_bill_receipt": "medical_bill_receipt",
        "diagnosis": "diagnosis_certificate",
        "diagnosis_certificate": "diagnosis_certificate",
        "surgery_certificate": "surgery_certificate",
        "unknown": "unknown",
    }
    if mode not in mapping:
        raise ValueError(f"지원하지 않는 문서 유형 모드입니다: {mode}")
    return mapping[mode]


def _keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _natural_sort_key(value: str) -> list[object]:
    parts = re.split(r"(\d+)", value)
    return [int(part) if part.isdigit() else part for part in parts]
