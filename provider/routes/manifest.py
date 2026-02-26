"""GET / — MediaProvider manifest endpoint.

Returns the agent registration manifest that Plex uses to identify and configure
the Stash2Plex custom metadata provider.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from provider import __version__
from provider.models import (
    MediaProviderFeature,
    MediaProviderResponse,
    MediaProviderScheme,
    MediaProviderType,
)

router = APIRouter()
logger = logging.getLogger(__name__)

AGENT_ID = "tv.plex.agents.stash2plex"


@router.get("/")
async def manifest() -> JSONResponse:
    """Return the MediaProvider manifest for agent registration."""
    provider = MediaProviderResponse(
        identifier=AGENT_ID,
        title="Stash2Plex",
        version=__version__,
        Types=[
            MediaProviderType(
                type=1,  # Movie
                Scheme=[MediaProviderScheme(scheme=AGENT_ID)],
            )
        ],
        Feature=[
            MediaProviderFeature(type="match", key="/library/metadata/matches"),
            MediaProviderFeature(type="metadata", key="/library/metadata"),
        ],
    )

    logger.info("Manifest requested", extra={"agent_id": AGENT_ID})

    return JSONResponse(
        content={"MediaProvider": provider.model_dump(by_alias=True)}
    )
