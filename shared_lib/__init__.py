"""
shared_lib — Cross-service shared code for Stash2Plex v2.0.

Importable by both the Stash plugin (via sys.path at repo root)
and the provider service (via Docker COPY).

NOT the same as the existing shared/ package (Stash binary logging protocol).

Public API:
    PathMapper, PathRule          -- bidirectional path translation
    StashClient                   -- async Stash GraphQL client
    StashScene, StashFile         -- typed Pydantic scene models
    StashConnectionError          -- server unreachable or timed out
    StashQueryError               -- GraphQL errors array returned
    StashSceneNotFound            -- findScene returned null
"""

from shared_lib.path_mapper import PathMapper, PathRule
from shared_lib.stash_client import (
    StashClient,
    StashScene,
    StashFile,
    StashConnectionError,
    StashQueryError,
    StashSceneNotFound,
)

__all__ = [
    "PathMapper",
    "PathRule",
    "StashClient",
    "StashScene",
    "StashFile",
    "StashConnectionError",
    "StashQueryError",
    "StashSceneNotFound",
]
