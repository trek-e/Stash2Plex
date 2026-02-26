"""GET /health — Health status endpoint.

Returns current provider status including version, uptime, Stash reachability,
and Plex registration state.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from provider import __version__

router = APIRouter()
logger = logging.getLogger(__name__)

# Module-level start time — records when the module was imported (proxy for app start)
_start_time = time.time()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Return provider health status."""
    uptime_seconds = int(time.time() - _start_time)

    # stash_reachable is set by the lifespan on app.state
    stash_reachable: bool = getattr(request.app.state, "stash_reachable", False)

    return JSONResponse(
        content={
            "status": "ok",
            "version": __version__,
            "uptime_seconds": uptime_seconds,
            "stash_reachable": stash_reachable,
            "plex_registered": False,  # Manual registration — Phase 24 does not auto-register
        }
    )
