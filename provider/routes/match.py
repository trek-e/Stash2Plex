"""POST /library/metadata/matches — Match endpoint (Phase 24 stub).

Returns an empty matches list. Full implementation in Phase 25.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from provider.models import MediaContainerResponse
from provider.routes.manifest import AGENT_ID

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/library/metadata/matches")
async def match(request: Request) -> JSONResponse:
    """Return an empty match result (stub — Phase 25 will implement real matching)."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    filename = body.get("filename", "<unknown>")
    logger.info(
        "Match request received",
        extra={"filename": filename, "body": body},
    )

    container = MediaContainerResponse(
        size=0,
        offset=0,
        totalSize=0,
        identifier=AGENT_ID,
        Metadata=[],
    )

    return JSONResponse(
        content={"MediaContainer": container.model_dump(by_alias=True)}
    )
