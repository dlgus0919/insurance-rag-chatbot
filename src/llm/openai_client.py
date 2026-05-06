"""OpenAI Chat Completions 클라이언트."""

from __future__ import annotations

import json as jsonlib
import os
from typing import Iterator

import requests

from src import config

OPENAI_BASE = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_TIMEOUT = 60


class OpenAIClient:
    """OpenAI Chat Completions API를 호출하는 클라이언트."""

    provider = "openai"

    def __init__(self, model: str, api_key: str | None = None, max_tokens: int | None = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.max_tokens = max_tokens or config.OPENAI_MAX_TOKENS
        self.last_usage: dict | None = None
        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하거나 관리자에게 문의하세요."
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _is_gpt5_family(self) -> bool:
        return self.model.startswith("gpt-5")

    def _payload(self, prompt: str, system: str, temperature: float, stream: bool) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if self._is_gpt5_family():
            payload["max_completion_tokens"] = self.max_tokens
        else:
            payload["temperature"] = temperature
            payload["max_tokens"] = self.max_tokens
        return payload

    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        num_ctx: int | None = None,
    ) -> str:
        """비스트리밍 답변을 생성한다. num_ctx는 OpenAI에서 사용하지 않는다."""

        try:
            response = requests.post(
                f"{OPENAI_BASE}/chat/completions",
                headers=self._headers(),
                json=self._payload(prompt, system, temperature, stream=False),
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"OpenAI 호출 실패: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI 응답 오류(status={response.status_code}): {response.text[:300]}")
        data = response.json()
        self.last_usage = data.get("usage", {})
        return data["choices"][0]["message"]["content"].strip()

    def generate_stream(self, prompt: str, system: str = "", temperature: float = 0.2) -> Iterator[str]:
        """스트리밍 답변 토큰을 생성한다."""

        try:
            with requests.post(
                f"{OPENAI_BASE}/chat/completions",
                headers=self._headers(),
                json=self._payload(prompt, system, temperature, stream=True),
                stream=True,
                timeout=DEFAULT_TIMEOUT,
            ) as response:
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"OpenAI 스트림 오류(status={response.status_code}): {response.text[:300]}"
                    )
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
                    if token:
                        yield token
        except requests.RequestException as exc:
            raise RuntimeError(f"OpenAI 스트림 호출 실패: {exc}") from exc

    def list_models(self) -> list[str]:
        """정적 후보 모델 목록을 반환한다."""

        return list(config.OPENAI_CANDIDATE_MODELS)
