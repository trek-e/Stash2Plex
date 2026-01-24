"""
File path matching logic for finding Plex items.

Provides find_plex_item_by_path function with 3 fallback strategies:
1. Exact path match (most accurate)
2. Filename-only match (handles path prefix differences)
3. Case-insensitive filename match (cross-platform compatibility)
"""

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from plexapi.library import LibrarySection
    from plexapi.video import Video

logger = logging.getLogger('PlexSync.plex.matcher')


def find_plex_item_by_path(
    library: "LibrarySection",
    stash_path: str,
    plex_path_prefix: Optional[str] = None,
    stash_path_prefix: Optional[str] = None,
) -> Optional["Video"]:
    """
    Find Plex item matching a Stash file path.

    Uses 3 fallback strategies in order:
    1. Exact path match (optionally with prefix mapping)
    2. Filename-only match (handles different mount points)
    3. Case-insensitive filename match (Windows/macOS compatibility)

    Args:
        library: Plex library section to search
        stash_path: File path from Stash
        plex_path_prefix: Optional prefix to prepend for Plex paths
                         (e.g., "/media/plex" when Plex sees files here)
        stash_path_prefix: Optional prefix to strip from Stash paths
                          (e.g., "/media/stash" when Stash sees files here)

    Returns:
        Matching Plex item or None if not found / ambiguous

    Example:
        >>> library = plex.library.section("Movies")
        >>> item = find_plex_item_by_path(
        ...     library,
        ...     "/stash/media/movie.mp4",
        ...     plex_path_prefix="/plex/media",
        ...     stash_path_prefix="/stash/media",
        ... )
    """
    # Normalize path
    path = Path(stash_path)
    filename = path.name

    # Apply path prefix mapping if both prefixes are provided
    search_path = stash_path
    if stash_path_prefix and plex_path_prefix:
        if stash_path.startswith(stash_path_prefix):
            search_path = plex_path_prefix + stash_path[len(stash_path_prefix):]
            logger.debug(f"Path mapped: {stash_path} -> {search_path}")

    # Strategy 1: Exact path match (most accurate)
    try:
        results = library.search(Media__Part__file=search_path)
        if results:
            logger.debug(f"Found by exact path: {search_path}")
            return results[0]
    except Exception as e:
        logger.warning(f"Exact path search failed: {e}")

    # Strategy 2: Filename-only match (handles directory differences)
    # Use endswith with leading slash to match full filename only
    try:
        results = library.search(Media__Part__file__endswith=f"/{filename}")
        if len(results) == 1:
            logger.debug(f"Found by filename: {filename}")
            return results[0]
        elif len(results) > 1:
            logger.warning(
                f"Ambiguous filename match for '{filename}': "
                f"{len(results)} items found, skipping"
            )
            # Don't return - try case-insensitive as last resort
    except Exception as e:
        logger.warning(f"Filename search failed: {e}")

    # Strategy 3: Case-insensitive filename match (Windows/macOS)
    # Note: __iendswith is case-insensitive endswith
    try:
        results = library.search(Media__Part__file__iendswith=f"/{filename.lower()}")
        if len(results) == 1:
            logger.debug(f"Found by case-insensitive filename: {filename}")
            return results[0]
        elif len(results) > 1:
            logger.warning(
                f"Ambiguous case-insensitive match for '{filename}': "
                f"{len(results)} items found"
            )
    except Exception as e:
        logger.warning(f"Case-insensitive search failed: {e}")

    # No match found
    logger.debug(f"No Plex item found for path: {stash_path}")
    return None
