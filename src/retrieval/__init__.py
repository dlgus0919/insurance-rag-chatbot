"""검색 모듈 공통 타입."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Hit:
    """검색 결과 한 건."""

    id: str
    score: float
    document: str
    metadata: dict = field(default_factory=dict)
