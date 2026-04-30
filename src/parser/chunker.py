"""한국어 고시 문서용 계층 인식 청커."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

VOLUME_RE = re.compile(r"^\s*제\s*\d+\s*편\b.*")
PART_RE = re.compile(r"^\s*제\s*\d+\s*부\b.*")
CHAPTER_RE = re.compile(r"^\s*제\s*\d+\s*장\b.*")
SECTION_RE = re.compile(r"^\s*제\s*\d+\s*절\b.*")
CODE_RE = re.compile(r"\b[A-Z]{1,3}\d{2,5}\b|\b\d{5}\b")


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


def chunk_to_dict(chunk: Chunk) -> dict:
    """Chunk를 JSON 직렬화 가능한 dict로 변환한다."""

    return asdict(chunk)


def chunk_from_dict(data: dict) -> Chunk:
    """dict에서 Chunk를 복원한다."""

    return Chunk(id=data["id"], text=data["text"], metadata=dict(data["metadata"]))


def load_chunks(path: Path) -> list[Chunk]:
    """JSONL 청크 파일을 읽는다."""

    with path.open("r", encoding="utf-8") as file:
        return [chunk_from_dict(json.loads(line)) for line in file if line.strip()]


def save_chunks(chunks: Iterable[Chunk], path: Path) -> None:
    """JSONL 청크 파일을 저장한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk_to_dict(chunk), ensure_ascii=False) + "\n")


def _normalize_line(line: str) -> str:
    return re.sub(r"[ \t]+", " ", line).strip()


def _header_level(line: str) -> str | None:
    if VOLUME_RE.match(line):
        return "volume"
    if PART_RE.match(line):
        return "part"
    if CHAPTER_RE.match(line):
        return "chapter"
    if SECTION_RE.match(line):
        return "section"
    return None


def _update_context(context: dict, level: str, value: str) -> dict:
    updated = dict(context)
    if level == "volume":
        updated.update({"volume": value, "part": None, "chapter": None, "section": None})
    elif level == "part":
        updated.update({"part": value, "chapter": None, "section": None})
    elif level == "chapter":
        updated.update({"chapter": value, "section": None})
    elif level == "section":
        updated["section"] = value
    return updated


def _extract_codes(text: str) -> list[str]:
    seen: set[str] = set()
    codes: list[str] = []
    for code in CODE_RE.findall(text):
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _sliding_windows(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    target_chars = max(1, target_chars)
    overlap_chars = max(0, min(overlap_chars, target_chars - 1))
    step = max(1, target_chars - overlap_chars)

    windows: list[str] = []
    start = 0
    while start < len(text):
        window = text[start : start + target_chars].strip()
        if window:
            windows.append(window)
        if start + target_chars >= len(text):
            break
        start += step
    return windows


def _split_text(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    if len(paragraphs) <= 1:
        return _sliding_windows(text, target_chars, overlap_chars)

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target_chars:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(_sliding_windows(paragraph, target_chars, overlap_chars))
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= target_chars:
            current = candidate
        else:
            if current.strip():
                chunks.append(current.strip())
            current = paragraph

    if current.strip():
        chunks.append(current.strip())
    return chunks


def _make_chunk(chunk_id: str, text: str, context: dict, page_start: int, page_end: int) -> Chunk:
    metadata = {
        "page_start": page_start,
        "page_end": page_end,
        "volume": context.get("volume"),
        "part": context.get("part"),
        "chapter": context.get("chapter"),
        "section": context.get("section"),
        "codes": _extract_codes(text),
        "char_count": len(text),
    }
    return Chunk(id=chunk_id, text=text, metadata=metadata)


def chunk_pages(
    pages: list[tuple[int, str]],
    target_chars: int = 800,
    overlap_chars: int = 100,
) -> list[Chunk]:
    """
    페이지를 순회하며 편/부/장/절 컨텍스트를 청크 메타데이터에 전파한다.

    새 헤더가 나오면 기존 버퍼를 닫고 헤더 레벨에 맞게 하위 컨텍스트를
    초기화한다. 긴 청크는 빈 줄 단위로 나누고, 그래도 길면 슬라이딩
    윈도우를 적용한다.
    """

    chunks: list[Chunk] = []
    context: dict = {"volume": None, "part": None, "chapter": None, "section": None}
    buffer_lines: list[str] = []
    buffer_context = dict(context)
    page_start: int | None = None
    page_end: int | None = None
    buffer_has_body = False

    def flush() -> None:
        nonlocal buffer_lines, page_start, page_end, buffer_context, buffer_has_body
        text = "\n".join(buffer_lines).strip()
        if not text or page_start is None or page_end is None:
            buffer_lines = []
            buffer_has_body = False
            return
        for piece in _split_text(text, target_chars, overlap_chars):
            chunk_id = f"ch_{len(chunks) + 1:06d}"
            chunks.append(_make_chunk(chunk_id, piece, buffer_context, page_start, page_end))
        buffer_lines = []
        page_start = None
        page_end = None
        buffer_context = dict(context)
        buffer_has_body = False

    for page_no, raw_text in pages:
        for raw_line in raw_text.splitlines():
            line = _normalize_line(raw_line)
            if not line:
                if buffer_lines and buffer_lines[-1] != "":
                    buffer_lines.append("")
                continue

            level = _header_level(line)
            if level is not None:
                if buffer_has_body:
                    flush()
                context = _update_context(context, level, line)
                buffer_context = dict(context)

            if page_start is None:
                page_start = page_no
            page_end = page_no
            buffer_lines.append(line)
            if level is None:
                buffer_has_body = True

    flush()
    return chunks
