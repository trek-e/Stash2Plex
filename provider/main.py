"""FastAPI application factory for the Stash2Plex provider.

Wires together configuration, structured logging, lifespan management,
route registration, and HTTP request logging middleware.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from provider import __version__
from provider.config import get_settings
from provider.logging_config import configure_logging
from provider.routes import health, manifest, match, metadata

logger = logging.getLogger(__name__)


async def _check_stash_connectivity(settings) -> bool:  # type: ignore[no-untyped-def]
    """Attempt a lightweight connectivity check against the configured Stash URL.

    Returns True if Stash responded with a non-5xx status, False on any
    connection or timeout error.
    """
    url = settings.stash_url
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            reachable = resp.status_code < 500
    except (httpx.ConnectError, httpx.TimeoutException):
        reachable = False
    except Exception:
        reachable = False

    if reachable:
        logger.info("Stash reachable", extra={"stash_url": url})
    else:
        logger.info(
            "Stash unreachable — will retry on requests",
            extra={"stash_url": url},
        )

    return reachable


def _print_startup_banner(settings, stash_ok: bool) -> None:  # type: ignore[no-untyped-def]
    """Log the startup banner at info level."""
    reachability = "reachable" if stash_ok else "unreachable"
    rule_count = len(settings.path_rules)

    logger.info(
        "Stash2Plex Provider starting",
        extra={
            "version": __version__,
            "port": settings.provider_port,
            "stash_url": settings.stash_url,
            "stash_reachable": stash_ok,
            "plex_url": settings.plex_url,
            "path_rules_loaded": rule_count,
        },
    )
    # Also emit a human-readable summary for log tailing
    logger.info(
        f"Stash2Plex Provider v{__version__} | "
        f"Port: {settings.provider_port} | "
        f"Stash: {settings.stash_url} [{reachability}] | "
        f"Plex: {settings.plex_url} | "
        f"Path rules: {rule_count} loaded"
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager.

    Runs on startup: load config, configure logging, check Stash connectivity,
    print startup banner.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    stash_ok = await _check_stash_connectivity(settings)
    app.state.stash_reachable = stash_ok

    _print_startup_banner(settings, stash_ok)

    yield

    # Shutdown — no cleanup needed in Phase 24
    logger.info("Stash2Plex Provider shutting down")


# ── Application factory ──────────────────────────────────────────────────────

app = FastAPI(
    lifespan=lifespan,
    docs_url=None,    # Machine-to-machine API — no Swagger UI
    redoc_url=None,
)

# Route registration
app.include_router(manifest.router)
app.include_router(match.router)
app.include_router(metadata.router)
app.include_router(health.router)


# ── Request logging middleware ────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
    """Log all incoming requests with method, path, status, and response time."""
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "HTTP request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(elapsed_ms, 2),
        },
    )
    return response


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "provider.main:app",
        host="0.0.0.0",
        port=settings.provider_port,
        log_level=settings.log_level.lower(),
        access_log=False,  # We handle request logging ourselves
    )
