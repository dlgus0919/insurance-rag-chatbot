"""Lightweight rate limiting decorators for FastAPI routes.

The project keeps ``slowapi`` in requirements as an operations-friendly option,
but this wrapper avoids making direct route-unit tests depend on slowapi's
request injection behavior.
"""

from __future__ import annotations

import inspect
import os
import time
from collections import defaultdict, deque
from collections.abc import Callable
from functools import wraps
from typing import Any

from src.api.exceptions import RateLimitException


class RateLimitExceeded(Exception):
    """Compatibility exception name for rate-limit handler registration."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def user_or_ip_key(request: Any) -> str:
    """Use authenticated subject when available, otherwise fall back to IP."""

    user = getattr(getattr(request, "state", None), "user", None)
    username = getattr(user, "username", None)
    if username:
        return f"user:{username}"
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) or "unknown"
    return f"ip:{host}"


class Limiter:
    """In-process fixed-window limiter with a slowapi-compatible decorator API."""

    def __init__(self, key_func: Callable = user_or_ip_key, default_limits: list[str] | None = None, **_: Any) -> None:
        self.key_func = key_func
        self.default_limits = default_limits or []
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def limit(self, rule: str) -> Callable:
        max_hits, window_seconds = _parse_rule(rule)

        def decorator(func: Callable) -> Callable:
            if inspect.iscoroutinefunction(func):
                @wraps(func)
                async def async_wrapper(*args, **kwargs):
                    self._check(rule, max_hits, window_seconds, _find_request(args, kwargs))
                    return await func(*args, **kwargs)

                return async_wrapper

            @wraps(func)
            def wrapper(*args, **kwargs):
                self._check(rule, max_hits, window_seconds, _find_request(args, kwargs))
                return func(*args, **kwargs)

            return wrapper

        return decorator

    def _check(self, rule: str, max_hits: int, window_seconds: int, request: Any | None) -> None:
        if os.getenv("API_RATE_LIMIT_DISABLED", "false").lower() == "true":
            return
        if request is None:
            return
        key = (rule, self.key_func(request))
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] >= window_seconds:
            bucket.popleft()
        if len(bucket) >= max_hits:
            raise RateLimitException(detail=rule)
        bucket.append(now)

    def reset(self) -> None:
        self._hits.clear()


def _parse_rule(rule: str) -> tuple[int, int]:
    count_text, unit = rule.split("/", 1)
    count = int(count_text)
    unit = unit.strip().lower()
    if unit.startswith("second"):
        return count, 1
    if unit.startswith("minute"):
        return count, 60
    if unit.startswith("hour"):
        return count, 60 * 60
    raise ValueError(f"Unsupported rate limit unit: {unit}")


def _find_request(args: tuple, kwargs: dict) -> Any | None:
    request = kwargs.get("request")
    if _looks_like_request(request):
        return request
    for value in args:
        if _looks_like_request(value):
            return value
    return None


def _looks_like_request(value: Any) -> bool:
    return hasattr(value, "headers") and hasattr(value, "state") and hasattr(value, "client")


limiter = Limiter(key_func=user_or_ip_key, default_limits=["200/minute"])
