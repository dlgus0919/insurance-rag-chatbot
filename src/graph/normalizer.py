from __future__ import annotations

import re

# 정규표현식 정의
WHITESPACE_RE = re.compile(r"\s+")
SPECIAL_CHAR_RE = re.compile(r"[^\w\s\-]")
KOREAN_PARTICLES = ("으로", "에서", "에게", "부터", "까지", "처럼", "로", "을", "를", "은", "는", "이", "가", "에", "의", "도", "만", "와", "과")


def normalize_name(name: str) -> str:
    """이름을 정규화한다. 공백 제거, 특수문자 제거, 소문자 변환 수행."""
    if not name:
        return ""
    text = name.strip()
    # 괄호 및 대괄호 내용을 보존할지 결정: 공백 제거 및 소문자화를 기본으로 처리
    text = WHITESPACE_RE.sub("", text)
    text = SPECIAL_CHAR_RE.sub("", text)
    return text.lower()


def normalize_code(code: str) -> str:
    """코드를 정규화한다. 공백 제거 및 대문자 변환."""
    if not code:
        return ""
    return WHITESPACE_RE.sub("", code).strip().upper()


def clean_korean_particles(text: str) -> str:
    """단어 끝의 조사(은/는/이/가/을/를/의 등)를 제거한다."""
    if not text:
        return ""
    normalized = text.strip()
    for suffix in KOREAN_PARTICLES:
        if len(normalized) > len(suffix) + 1 and normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized
