"""
File path matching logic for finding Plex items.

Provides find_plex_item_by_path function with 3 fallback strategies:
1. Exact path match (most accurate)
2. Filename-only match (handles path prefix differences)
3. Case-insensitive filename match (cross-platform compatibility)
"""

from enum import Enum
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from plexapi.library import LibrarySection
    from plexapi.video import Video

logger = logging.getLogger('PlexSync.plex.matcher')


def _item_has_file(item, path_or_filename: str, exact: bool = True, case_insensitive: bool = False) -> bool:
    """
    Check if a Plex item has a media file matching the given path or filename.

    Args:
        item: Plex video item
        path_or_filename: Full path or just filename to match
        exact: If True, match full path; if False, match filename only
        case_insensitive: If True, compare case-insensitively

    Returns:
        True if item has matching file
    """
    try:
        if not hasattr(item, 'media') or not item.media:
            return False

        compare_val = path_or_filename.lower() if case_insensitive else path_or_filename

        for media in item.media:
            if not hasattr(media, 'parts') or not media.parts:
                continue
            for part in media.parts:
                if not hasattr(part, 'file') or not part.file:
                    continue

                file_path = part.file
                if case_insensitive:
                    file_path = file_path.lower()

                if exact:
                    if file_path == compare_val:
                        return True
                else:
                    # Match filename only
                    if file_path.endswith('/' + compare_val) or file_path.endswith('\\' + compare_val):
                        return True
                    # Also check without path separator for edge cases
                    if Path(file_path).name == (Path(path_or_filename).name if not case_insensitive else Path(path_or_filename).name.lower()):
                        return True
    except Exception as e:
        logger.debug(f"Error checking item files: {e}")

    return False


class MatchConfidence(Enum):
    HIGH = "high"   # Single unique match - auto-sync safe
    LOW = "low"     # Multiple candidates - needs review


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

    # Strategy 1: Search by title derived from filename, then verify file path
    # Extract title from filename (remove extension)
    title_search = path.stem
    # Clean up common suffixes like resolution, year, etc.
    import re
    title_search = re.sub(r'\s*[-_]\s*(WEBDL|WEB-DL|HDTV|BluRay|BDRip|DVDRip|720p|1080p|2160p|4K).*$', '', title_search, flags=re.IGNORECASE)

    try:
        # Search by title
        results = library.search(title=title_search)
        for item in results:
            # Check if any media file matches our path
            if _item_has_file(item, search_path):
                logger.debug(f"Found by title+path match: {title_search}")
                return item
            if _item_has_file(item, filename, exact=False):
                logger.debug(f"Found by title+filename match: {filename}")
                return item
    except Exception as e:
        logger.warning(f"Title search failed: {e}")

    # Strategy 2: Iterate through all items (slower but comprehensive)
    try:
        # Only do this for smaller libraries or as fallback
        all_items = library.all()
        matches = []
        filename_lower = filename.lower()

        for item in all_items:
            if _item_has_file(item, search_path):
                logger.debug(f"Found by exact path iteration: {search_path}")
                return item
            if _item_has_file(item, filename_lower, exact=False, case_insensitive=True):
                matches.append(item)

        if len(matches) == 1:
            logger.debug(f"Found by filename iteration: {filename}")
            return matches[0]
        elif len(matches) > 1:
            logger.warning(
                f"Ambiguous filename match for '{filename}': "
                f"{len(matches)} items found, skipping"
            )
    except Exception as e:
        logger.warning(f"Iteration search failed: {e}")

    # No match found
    logger.debug(f"No Plex item found for path: {stash_path}")
    return None


def find_plex_items_with_confidence(
    library: "LibrarySection",
    stash_path: str,
    plex_path_prefix: Optional[str] = None,
    stash_path_prefix: Optional[str] = None,
) -> tuple[MatchConfidence, Optional["Video"], list["Video"]]:
    """
    Find Plex item with confidence scoring based on match uniqueness.

    Uses same 3-strategy matching as find_plex_item_by_path but collects
    all candidates to determine confidence level.

    Args:
        library: Plex library section to search
        stash_path: File path from Stash
        plex_path_prefix: Optional prefix for Plex paths
        stash_path_prefix: Optional prefix to strip from Stash paths

    Returns:
        Tuple of (confidence, best_match_or_none, all_candidates):
        - HIGH confidence + item: Single unique match found
        - LOW confidence + None: Multiple ambiguous matches (candidates list populated)
        - Raises PlexNotFound if no matches at all

    Raises:
        PlexNotFound: When no matching items found (allows retry logic)
    """
    # Lazy import to avoid circular dependency
    from plex.exceptions import PlexNotFound

    # Normalize path
    path = Path(stash_path)
    filename = path.name

    # Apply path prefix mapping if both prefixes are provided
    search_path = stash_path
    if stash_path_prefix and plex_path_prefix:
        if stash_path.startswith(stash_path_prefix):
            search_path = plex_path_prefix + stash_path[len(stash_path_prefix):]
            logger.debug(f"Path mapped: {stash_path} -> {search_path}")

    # Collect all matches from each strategy
    candidates = []
    import re

    # Strategy 1: Search by title derived from filename, then verify file path
    title_search = path.stem
    # Clean up common suffixes
    title_search = re.sub(r'\s*[-_]\s*(WEBDL|WEB-DL|HDTV|BluRay|BDRip|DVDRip|720p|1080p|2160p|4K).*$', '', title_search, flags=re.IGNORECASE)

    try:
        results = library.search(title=title_search)
        for item in results:
            if _item_has_file(item, search_path):
                candidates.append(item)
                logger.debug(f"Found by title+exact path: {search_path}")
            elif _item_has_file(item, filename, exact=False):
                candidates.append(item)
                logger.debug(f"Found by title+filename: {filename}")
    except Exception as e:
        logger.warning(f"Title search failed: {e}")

    # Strategy 2: Iterate through all items if no matches yet
    if not candidates:
        try:
            all_items = library.all()
            filename_lower = filename.lower()

            for item in all_items:
                if _item_has_file(item, search_path):
                    candidates.append(item)
                    logger.debug(f"Found by exact path iteration: {search_path}")
                elif _item_has_file(item, filename_lower, exact=False, case_insensitive=True):
                    candidates.append(item)
                    logger.debug(f"Found by filename iteration: {filename}")
        except Exception as e:
            logger.warning(f"Iteration search failed: {e}")

    # Deduplicate candidates (same item might match multiple strategies)
    # Use ratingKey as unique identifier
    unique_candidates = {}
    for item in candidates:
        unique_candidates[item.ratingKey] = item
    deduplicated = list(unique_candidates.values())

    # Scoring logic
    if len(deduplicated) == 0:
        raise PlexNotFound(f"No Plex item found for path: {stash_path}")
    elif len(deduplicated) == 1:
        logger.debug(f"HIGH confidence match for {stash_path}")
        return (MatchConfidence.HIGH, deduplicated[0], deduplicated)
    else:
        # Multiple matches - log warning with candidate paths
        candidate_paths = []
        for item in deduplicated:
            try:
                # Get first media part path
                if hasattr(item, 'media') and item.media:
                    if hasattr(item.media[0], 'parts') and item.media[0].parts:
                        candidate_paths.append(item.media[0].parts[0].file)
            except (IndexError, AttributeError):
                candidate_paths.append("<path unavailable>")

        logger.warning(
            f"LOW confidence match for '{stash_path}': "
            f"{len(deduplicated)} candidates found - {candidate_paths}"
        )
        return (MatchConfidence.LOW, None, deduplicated)
