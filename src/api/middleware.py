"""Request tracking middleware."""

from __future__ import annotations

import logging
import time
import uuid
import inspect

from fastapi import Request

logger = logging.getLogger(__name__)


async def request_id_middleware(request: Request, call_next):
    """Attach a request id and process time to every response."""

    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        request_id = f"req_{uuid.uuid4().hex[:16]}"

    request.state.request_id = request_id
    request.state.start_time = time.time()

    logger.info(
        "[%s] %s %s",
        request_id,
        request.method,
        request.url.path,
        extra={"request_id": request_id},
    )
    try:
        response = call_next(request)
        if inspect.isawaitable(response):
            response = await response
    except Exception:
        process_time = time.time() - request.state.start_time
        logger.exception(
            "[%s] %s %s -> ERROR (%.3fs)",
            request_id,
            request.method,
            request.url.path,
            process_time,
            extra={"request_id": request_id},
        )
        raise

    process_time = time.time() - request.state.start_time
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    logger.info(
        "[%s] %s %s -> %s (%.3fs)",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        process_time,
        extra={"request_id": request_id},
    )
    return response
