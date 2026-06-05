"""OpenAI-compatible local Chat Completions client."""

from __future__ import annotations

import json as jsonlib
import re
import time
from typing import Iterator

import requests

from src import config

DEFAULT_TIMEOUT = 120
MAX_RETRIES = 3
FINAL_MARKER_RE = re.compile(r"<\|channel\|>final<\|message\|>")
HARMONY_TOKEN_RE = re.compile(r"<\|(?:channel|message|end|start|return)\|>|<pad>")
THINK_END_TOKEN_RE = re.compile(r"</\s*think\s*>", re.IGNORECASE)
THINK_TOKEN_RE = re.compile(r"<\s*/?\s*think\s*>", re.IGNORECASE)
FINAL_ANSWER_MARKER_RE = re.compile(r"(?:\[답변\]|최종\s*답변\s*[:：]?|답변\s*[:：]|결론\s*[:：]|final\s+answer\s*[:：])", re.IGNORECASE)
HANGUL_RE = re.compile(r"[가-힣]")
REASONING_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"okay\b|let'?s\b|we\s+need\b|i\s+(?:need|should|will)\b|"
    r"the\s+question\b|need\s+to\b|first[,.\s]|to\s+answer\b|"
    r"(?:먼저|우선).{0,20}(?:분석|살펴|검토|생각)|"
    r"질문을\s*(?:분석|살펴)|생각해|추론|검토해보"
    r")",
    re.IGNORECASE,
)
THINKING_EMPTY_FINAL_FALLBACK = (
    "모델이 내부 추론만 반환하고 최종 답변을 제공하지 않았습니다. "
    "검색 근거를 다시 확인하거나 다른 검증된 모델로 재시도해 주세요."
)
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


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


def _uses_think_stream(model: str, provider: str) -> bool:
    """Return whether the model emits a hidden think block before final text."""

    name = model.lower()
    return "thinking" in name or "reasoning" in name


def _split_after_last_think_end(content: str) -> tuple[bool, str]:
    """Return text after the last think-end token, if one exists."""

    matches = list(THINK_END_TOKEN_RE.finditer(content))
    if not matches:
        return False, content
    return True, content[matches[-1].end() :]


def _extract_marked_final_content(content: str) -> str:
    """Extract Korean final-answer text after an explicit answer marker."""

    for marker in FINAL_ANSWER_MARKER_RE.finditer(content):
        candidate = THINK_TOKEN_RE.sub("", content[marker.end():]).strip()
        if HANGUL_RE.search(candidate):
            return candidate
    return ""


def _looks_like_visible_answer(content: str, *, allow_short: bool = False) -> bool:
    """Return whether buffered thinking-model text appears to be final Korean text."""

    text = THINK_TOKEN_RE.sub("", content).strip()
    if not text:
        return False
    if _extract_marked_final_content(text):
        return True
    if REASONING_PREFIX_RE.search(text):
        return False
    if not HANGUL_RE.search(text):
        return False
    compact = re.sub(r"\s+", "", text)
    return allow_short or len(compact) >= 8 or "\n" in text


def _extract_visible_content(
    content: str,
    *,
    require_think_end: bool = False,
    fallback_on_hidden: bool = False,
) -> str:
    """Remove hidden think blocks and return user-visible final text."""

    has_think_end, visible = _split_after_last_think_end(content)
    if has_think_end:
        return THINK_TOKEN_RE.sub("", visible).strip()

    marked = _extract_marked_final_content(content)
    if marked:
        return marked

    if require_think_end:
        if _looks_like_visible_answer(content, allow_short=True):
            return THINK_TOKEN_RE.sub("", content).strip()
        return THINKING_EMPTY_FINAL_FALLBACK if fallback_on_hidden and content.strip() else ""

    if THINK_TOKEN_RE.match(content.lstrip()):
        return ""
    return THINK_TOKEN_RE.sub("", content).strip()


def _clean_stream_token(token: str) -> str:
    """Clean a visible stream token without dropping ordinary spacing."""

    if "<think" in token.lower() or THINK_END_TOKEN_RE.search(token):
        return _extract_visible_content(token)
    return token


def _should_disable_thinking(model: str, provider: str) -> bool:
    """Return whether the serving template should emit final content directly."""

    name = model.lower()
    if provider == "vllm" and "nemotron" in name:
        return True
    return provider == "sglang" and "qwen" in name and _uses_think_stream(model, provider)


def _retry_delay_seconds(response: requests.Response | None, attempt: int) -> float:
    """Return a bounded retry delay for transient local-serving errors."""

    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 10.0))
            except ValueError:
                pass
    return min(float(2 ** attempt), 10.0)


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
        disable_thinking = _should_disable_thinking(self.model, self.provider)
        if self.provider == "sglang" and config.SGLANG_REASONING_EFFORT and not disable_thinking:
            payload["reasoning_effort"] = config.SGLANG_REASONING_EFFORT
        if disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        num_ctx: int | None = None,
    ) -> str:
        """Generate a non-streaming answer. num_ctx is ignored by OpenAI-compatible APIs."""

        response: requests.Response | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(prompt, system, temperature, stream=False),
                    timeout=DEFAULT_TIMEOUT,
                )
            except requests.RequestException as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(_retry_delay_seconds(None, attempt))
                    continue
                raise RuntimeError(f"SGLang 호출 실패: {exc}") from exc
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt >= MAX_RETRIES:
                break
            time.sleep(_retry_delay_seconds(response, attempt))

        if response is None:
            raise RuntimeError("SGLang 호출 실패: 응답을 받지 못했습니다.")
        if response.status_code >= 400:
            raise RuntimeError(f"SGLang 응답 오류(status={response.status_code}): {response.text[:300]}")
        data = response.json()
        self.last_usage = data.get("usage", {})
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        if _uses_harmony_stream(self.model, self.provider):
            return _extract_final_content(content)
        content = HARMONY_TOKEN_RE.sub("", content)
        return _extract_visible_content(
            content,
            require_think_end=_uses_think_stream(self.model, self.provider),
            fallback_on_hidden=_uses_think_stream(self.model, self.provider),
        )

    def generate_stream(self, prompt: str, system: str = "", temperature: float = 0.2) -> Iterator[str]:
        """Yield streaming answer tokens."""

        for attempt in range(MAX_RETRIES + 1):
            try:
                with requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(prompt, system, temperature, stream=True),
                    stream=True,
                    timeout=DEFAULT_TIMEOUT,
                ) as response:
                    if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                        time.sleep(_retry_delay_seconds(response, attempt))
                        continue
                    if response.status_code >= 400:
                        raise RuntimeError(f"SGLang 스트림 오류(status={response.status_code}): {response.text[:300]}")

                    harmony_mode = _uses_harmony_stream(self.model, self.provider)
                    think_mode = _uses_think_stream(self.model, self.provider)
                    buffer = ""
                    emitting = not harmony_mode
                    think_buffer = ""
                    think_emitting = not think_mode
                    visible_yielded = False

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
                            if not think_emitting:
                                think_buffer += token
                                if THINK_END_TOKEN_RE.search(think_buffer):
                                    think_emitting = True
                                    cleaned = _extract_visible_content(think_buffer, require_think_end=True)
                                    if cleaned:
                                        visible_yielded = True
                                        yield cleaned
                                elif _extract_marked_final_content(think_buffer) or _looks_like_visible_answer(think_buffer):
                                    think_emitting = True
                                    cleaned = _extract_visible_content(think_buffer, require_think_end=True)
                                    if cleaned:
                                        visible_yielded = True
                                        yield cleaned
                                continue
                            cleaned = HARMONY_TOKEN_RE.sub("", token)
                            cleaned = _clean_stream_token(cleaned)
                            if cleaned:
                                visible_yielded = True
                                yield cleaned
                            continue

                        if emitting:
                            cleaned = HARMONY_TOKEN_RE.sub("", token.replace("<|return|>", "").replace("<|end|>", ""))
                            cleaned = _clean_stream_token(cleaned)
                            if cleaned:
                                visible_yielded = True
                                yield cleaned
                            continue
                        buffer += token
                        match = FINAL_MARKER_RE.search(buffer)
                        if match:
                            emitting = True
                            cleaned = _extract_final_content(buffer)
                            if cleaned:
                                visible_yielded = True
                                yield cleaned
                    if think_mode and not visible_yielded and think_buffer.strip():
                        fallback = _extract_visible_content(
                            think_buffer,
                            require_think_end=True,
                            fallback_on_hidden=True,
                        )
                        if fallback:
                            yield fallback
                    return
            except requests.RequestException as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(_retry_delay_seconds(None, attempt))
                    continue
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
