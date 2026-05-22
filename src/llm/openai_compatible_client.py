"""OpenAI-compatible local Chat Completions client."""

from __future__ import annotations

import json as jsonlib
import re
from typing import Iterator

import requests

from src import config

DEFAULT_TIMEOUT = 120
FINAL_MARKER_RE = re.compile(r"<\|channel\|>final<\|message\|>")
HARMONY_TOKEN_RE = re.compile(r"<\|(?:channel|message|end|start|return)\|>|<pad>")


def _extract_final_content(content: str) -> str:
    """Return final-channel text from GPT-OSS Harmony output."""

    match = list(FINAL_MARKER_RE.finditer(content))
    if match:
        content = content[match[-1].end() :]
    content = content.split("<|end|>", 1)[0].split("<|return|>", 1)[0]
    return HARMONY_TOKEN_RE.sub("", content).strip()


def _uses_harmony_stream(model: str, provider: str) -> bool:
    """Return whether the model uses GPT-OSS Harmony special tokens stream."""
    name = model.lower()
    return "gpt-oss" in name or "harmony" in name


class OpenAICompatibleClient:
    """Client for local OpenAI-compatible servers such as SGLang."""

    provider = "sglang"

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tokens: int | None = None,
        provider: str = "sglang",
    ):
        self.model = model
        self.base_url = (base_url or config.sglang_base_url_for_model(model)).rstrip("/")
        self.api_key = api_key if api_key is not None else config.SGLANG_API_KEY
        self.max_tokens = max_tokens or config.OPENAI_MAX_TOKENS
        self.provider = provider
        self.last_usage: dict | None = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, prompt: str, system: str, temperature: float, stream: bool) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if self.provider == "sglang" and config.SGLANG_REASONING_EFFORT:
            payload["reasoning_effort"] = config.SGLANG_REASONING_EFFORT
        return payload

    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        num_ctx: int | None = None,
    ) -> str:
        """Generate a non-streaming answer. num_ctx is ignored by OpenAI-compatible APIs."""

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=self._payload(prompt, system, temperature, stream=False),
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"SGLang 호출 실패: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"SGLang 응답 오류(status={response.status_code}): {response.text[:300]}")
        data = response.json()
        self.last_usage = data.get("usage", {})
        content = data["choices"][0]["message"].get("content", "")
        if _uses_harmony_stream(self.model, self.provider):
            return _extract_final_content(content)
        else:
            return HARMONY_TOKEN_RE.sub("", content).strip()

    def generate_stream(self, prompt: str, system: str = "", temperature: float = 0.2) -> Iterator[str]:
        """Yield streaming answer tokens."""

        try:
            with requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=self._payload(prompt, system, temperature, stream=True),
                stream=True,
                timeout=DEFAULT_TIMEOUT,
            ) as response:
                if response.status_code >= 400:
                    raise RuntimeError(f"SGLang 스트림 오류(status={response.status_code}): {response.text[:300]}")

                harmony_mode = _uses_harmony_stream(self.model, self.provider)
                buffer = ""
                emitting = not harmony_mode

                for raw in response.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8")
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: ") :]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        data = jsonlib.loads(payload)
                    except jsonlib.JSONDecodeError:
                        continue
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content") or ""
                    if not token:
                        continue

                    if not harmony_mode:
                        cleaned = HARMONY_TOKEN_RE.sub("", token)
                        if cleaned:
                            yield cleaned
                        continue

                    if emitting:
                        cleaned = HARMONY_TOKEN_RE.sub("", token.replace("<|return|>", "").replace("<|end|>", ""))
                        if cleaned:
                            yield cleaned
                        continue
                    buffer += token
                    match = FINAL_MARKER_RE.search(buffer)
                    if match:
                        emitting = True
                        cleaned = _extract_final_content(buffer)
                        if cleaned:
                            yield cleaned
        except requests.RequestException as exc:
            raise RuntimeError(f"SGLang 스트림 호출 실패: {exc}") from exc

    def list_models(self) -> list[str]:
        """Return model IDs reported by the configured endpoint."""

        try:
            response = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=5)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return []
        return [item.get("id") for item in payload.get("data", []) if item.get("id")]

    def health(self) -> bool:
        """Return whether the OpenAI-compatible /models endpoint is reachable."""

        try:
            response = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=5)
        except requests.RequestException:
            return False
        return response.status_code < 400
