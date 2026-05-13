"""OCR 한국어 텍스트 후처리 정규화."""

from __future__ import annotations

import re

_SUFFIX_FIXES = [
    (r"수술올\b", "수술을"),
    (r"서명틀\b", "서명을"),
    (r"제거해내논", "제거해내는"),
    (r"(?<=[가-힣])올\b", "을"),
    (r"(?<=[가-힣])틀\b", "를"),
    (r"(?<=[가-힣])롤\b", "를"),
    (r"덥니다", "됩니다"),
    (r"됩니닥", "됩니다"),
    (r"엎올", "었을"),
    (r"잃엎", "잃었"),
    (r"없엎", "없었"),
]

_NOISE_PATTERNS = [
    re.compile(r"^\s*제\d+장\s+\S+분류표\s+해설\s+\d+\s*$", re.MULTILINE),
    re.compile(r"^\s*[\d\s]+\s*$", re.MULTILINE),
    re.compile(r"^\s*[\{\}\[\]]\s*$", re.MULTILINE),
]
_DECORATIVE_ENGLISH_TOKENS = {"shares", "year", "corp", "inc", "ltd", "guide", "claim"}
_KOREAN_RE = re.compile(r"[가-힣]")
_ALPHA_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


def normalize_ocr_text(text: str) -> str:
    """OCR 출력 텍스트를 한국어 후처리 규칙으로 정규화한다."""

    for pattern, replacement in _SUFFIX_FIXES:
        text = re.sub(pattern, replacement, text)
    for noise_pattern in _NOISE_PATTERNS:
        text = noise_pattern.sub("", text)
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_short_numeric_or_symbol_line(line):
            continue
        if _is_decorative_english_line(line):
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_short_numeric_or_symbol_line(line: str) -> bool:
    compact = line.strip()
    if not compact:
        return True
    if len(compact) > 20:
        return False
    return re.fullmatch(r"[\d\W_]+", compact) is not None


def _is_decorative_english_line(line: str) -> bool:
    compact = line.strip()
    if not compact or len(compact) > 40 or _KOREAN_RE.search(compact):
        return False
    tokens = [token for token in re.split(r"\s+", compact) if token]
    if not tokens or len(tokens) > 6:
        return False
    if not all(_ALPHA_TOKEN_RE.match(token) for token in tokens):
        return False
    lowered = {token.lower() for token in tokens}
    return any(token in lowered for token in _DECORATIVE_ENGLISH_TOKENS)


def is_noise_text_block(text: str) -> bool:
    compact = text.strip()
    if not compact:
        return True
    lines = [line.strip() for line in compact.splitlines() if line.strip()]
    if not lines:
        return True
    if all(_is_short_numeric_or_symbol_line(line) for line in lines):
        return True
    if all(_is_decorative_english_line(line) for line in lines):
        return True
    return False
