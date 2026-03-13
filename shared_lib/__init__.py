"""
shared_lib — Cross-service shared code for Stash2Plex.

Importable by both the Stash plugin (via sys.path at repo root)
and the provider service (via Docker COPY).

NOT the same as the existing shared/ package (Stash binary logging protocol).

Public API:
    PathMapper, PathRule          -- bidirectional path translation
"""

from shared_lib.path_mapper import PathMapper, PathRule

__all__ = [
    "PathMapper",
    "PathRule",
]
