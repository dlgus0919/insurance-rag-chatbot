"""FastAPI app entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from src.api.db import init_db
from src.api.exceptions import AppException, error_response
from src.api.middleware import request_id_middleware
from src.api.rate_limit import RateLimitExceeded, limiter
from src.api.rag_service import get_rag_pipeline
from src.api.routes.claim import CLAIM_RAG_TOP_K
from src.api.routes import admin, auth, chat, claim, knowledge, sessions, system
from src.api.settings import get_api_settings
from src import config

logger = logging.getLogger(__name__)


async def _warm_claim_rag_pipelines() -> None:
    """Warm claim-calculation retrieval pipelines in the background after startup."""

    model = f"sglang:{config.SGLANG_DEFAULT_MODEL}"
    for index_mode in ("v2_only",):
        try:
            await asyncio.to_thread(get_rag_pipeline, model, CLAIM_RAG_TOP_K, index_mode)
            logger.info("Prewarmed claim RAG pipeline: model=%s index_mode=%s top_k=%s", model, index_mode, CLAIM_RAG_TOP_K)
        except Exception as exc:  # pragma: no cover - runtime fallback
            logger.warning("Claim RAG prewarm failed: model=%s index_mode=%s error=%s", model, index_mode, exc)


async def _warm_primary_chat_rag_pipelines() -> None:
    """Warm the most common chat/formal retrieval pipelines after startup."""

    model = f"sglang:{config.SGLANG_DEFAULT_MODEL}"
    top_k = 10
    for index_mode in ("v2_only",):
        try:
            await asyncio.to_thread(get_rag_pipeline, model, top_k, index_mode)
            logger.info("Prewarmed chat RAG pipeline: model=%s index_mode=%s top_k=%s", model, index_mode, top_k)
        except Exception as exc:  # pragma: no cover - runtime fallback
            logger.warning("Chat RAG prewarm failed: model=%s index_mode=%s error=%s", model, index_mode, exc)


async def _warm_primary_rag_pipelines() -> None:
    """Warm claim and primary chat pipelines together."""

    await _warm_primary_chat_rag_pipelines()
    await _warm_claim_rag_pipelines()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize API-owned resources."""

    await init_db()
    await _warm_primary_rag_pipelines()
    yield


async def static_cache_middleware(request: Request, call_next):
    """Set cache headers for frontend static assets."""

    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/css/", "/js/")):
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif path.startswith("/html/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def create_app() -> FastAPI:
    """Create the FastAPI application."""

    settings = get_api_settings()
    app = FastAPI(title="Shinhan EZ Insurance RAG API", version="0.1.0", lifespan=lifespan)
    app.state.limiter = limiter

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(request_id_middleware)
    app.middleware("http")(static_cache_middleware)

    _register_exception_handlers(app)

    app.include_router(system.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(claim.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(knowledge.router, prefix="/api")

    # Mount frontend static files
    base_dir = Path(__file__).resolve().parent.parent.parent
    frontend_dir = base_dir / "frontend"
    logger.info(f"Frontend directory: {frontend_dir} (exists: {frontend_dir.exists()})")

    if frontend_dir.exists():
        class SPAStaticFiles(StaticFiles):
            async def get_response(self, path: str, scope) -> Response:
                # If the path has an extension (contains a dot) or is an API path, do not fallback to index.html
                if "." in path or path.startswith("api/") or path.startswith("api"):
                    return await super().get_response(path, scope)
                try:
                    response = await super().get_response(path, scope)
                    if response.status_code == 404:
                        return await super().get_response("index.html", scope)
                    return response
                except Exception:
                    try:
                        return await super().get_response("index.html", scope)
                    except Exception:
                        raise HTTPException(status_code=404, detail="index.html not found")

        app.mount("/", SPAStaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict(_request_id(request)))

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code_map = {
            400: "INVALID_INPUT",
            401: "AUTH_FAILED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            409: "DUPLICATE_ENTRY",
            429: "RATE_LIMIT_EXCEEDED",
            500: "INTERNAL_ERROR",
        }
        message = exc.detail if isinstance(exc.detail, str) else "요청 처리 중 오류가 발생했습니다."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(code_map.get(exc.status_code, "HTTP_ERROR"), message, None, _request_id(request)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=error_response("INVALID_INPUT", "입력값이 올바르지 않습니다.", str(exc), _request_id(request)),
        )

    if RateLimitExceeded is not None:
        @app.exception_handler(RateLimitExceeded)
        async def rate_limit_exceeded_handler(request: Request, exc: Exception):
            detail = str(getattr(exc, "detail", exc))
            return JSONResponse(
                status_code=429,
                content=error_response(
                    "RATE_LIMIT_EXCEEDED",
                    "요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
                    detail,
                    _request_id(request),
                ),
            )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        request_id = _request_id(request)
        logger.error("[%s] Unhandled exception: %s", request_id, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "서버 내부 오류가 발생했습니다.", None, request_id),
        )


app = create_app()
