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


def normalize_ocr_text(text: str) -> str:
    """OCR 출력 텍스트를 한국어 후처리 규칙으로 정규화한다."""

    for pattern, replacement in _SUFFIX_FIXES:
        text = re.sub(pattern, replacement, text)
    for noise_pattern in _NOISE_PATTERNS:
        text = noise_pattern.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
