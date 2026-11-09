"""FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from yojana import __version__
from yojana.api.routes import chat, eligibility, schemes, system
from yojana.api.services import Services
from yojana.config import Settings, get_settings
from yojana.llm.gateway import AllProvidersExhausted
from yojana.logging_setup import configure_logging, request_id_var

logger = logging.getLogger("yojana.api")


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    """Build the app. Tests pass prebuilt `services`; normal runs build them on startup."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        app.state.services = services or Services.build(settings)
        app.state.background = set()
        if settings.warmup_models and services is None:
            task = asyncio.create_task(asyncio.to_thread(app.state.services.warmup))
            app.state.background.add(task)
            task.add_done_callback(app.state.background.discard)
        logger.info(
            "Ready: %d schemes, %d chunks",
            len(app.state.services.registry),
            len(app.state.services.chunks),
        )
        yield
        await app.state.services.gateway.aclose()

    app = FastAPI(title="Yojana Sahayak", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 8 <= len(incoming) <= 64 else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    @app.exception_handler(AllProvidersExhausted)
    async def exhausted_handler(request: Request, exc: AllProvidersExhausted) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": "all_providers_exhausted",
                "detail": "All language model providers are busy or unavailable. "
                "Please try again in a minute.",
            },
        )

    app.include_router(chat.router)
    app.include_router(schemes.router)
    app.include_router(eligibility.router)
    app.include_router(system.router)
    return app


app = create_app()
