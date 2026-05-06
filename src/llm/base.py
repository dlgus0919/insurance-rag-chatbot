"""LLM 클라이언트 공통 프로토콜."""

from __future__ import annotations

from typing import Iterator, Protocol


class LLMClient(Protocol):
    """OllamaClient와 OpenAIClient가 따르는 인터페이스."""

    model: str
    provider: str

    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        num_ctx: int | None = None,
    ) -> str: ...

    def generate_stream(self, prompt: str, system: str = "", temperature: float = 0.2) -> Iterator[str]: ...

    def list_models(self) -> list[str]: ...
