"""GET /library/metadata/{ratingKey} — Metadata endpoint (Phase 24 stub).

Returns empty metadata. Full implementation in Phase 26.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from provider.models import MediaContainerResponse
from provider.routes.manifest import AGENT_ID

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/library/metadata/{ratingKey}")
async def get_metadata(ratingKey: str) -> JSONResponse:
    """Return empty metadata for a given ratingKey (stub — Phase 26 will implement real metadata)."""
    logger.info(
        "Metadata request received",
        extra={"rating_key": ratingKey},
    )

    container = MediaContainerResponse(
        size=0,
        identifier=AGENT_ID,
        Metadata=[],
    )

    return JSONResponse(
        content={"MediaContainer": container.model_dump(by_alias=True)}
    )
