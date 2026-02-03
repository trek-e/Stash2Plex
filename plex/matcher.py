"""
Plex item matching logic.

Matches by filename (case-insensitive) since Stash and Plex
typically have different base paths to the same files.
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
    Find Plex item matching a Stash file path by filename.

    Matches by filename only (case-insensitive) since Stash and Plex
    typically have different base paths to the same files.

    Args:
        library: Plex library section to search
        stash_path: File path from Stash
        plex_path_prefix: Unused, kept for API compatibility
        stash_path_prefix: Unused, kept for API compatibility

    Returns:
        Matching Plex item or None if not found / ambiguous
    """
    import sys

    filename = Path(stash_path).name
    filename_lower = filename.lower()

    print(f"[PlexSync Matcher] Searching for filename: {filename}", file=sys.stderr)

    try:
        all_items = library.all()
        print(f"[PlexSync Matcher] Scanning {len(all_items)} items...", file=sys.stderr)
        matches = []

        for item in all_items:
            if _item_has_file(item, filename_lower, exact=False, case_insensitive=True):
                matches.append(item)

        if len(matches) == 1:
            print(f"[PlexSync Matcher] Found: {matches[0].title}", file=sys.stderr)
            return matches[0]
        elif len(matches) > 1:
            print(f"[PlexSync Matcher] Ambiguous: {len(matches)} matches", file=sys.stderr)
    except Exception as e:
        print(f"[PlexSync Matcher] Search failed: {e}", file=sys.stderr)

    return None


def find_plex_items_with_confidence(
    library: "LibrarySection",
    stash_path: str,
    plex_path_prefix: Optional[str] = None,
    stash_path_prefix: Optional[str] = None,
) -> tuple[MatchConfidence, Optional["Video"], list["Video"]]:
    """
    Find Plex item with confidence scoring based on filename match.

    Matches by filename only (case-insensitive) since Stash and Plex
    typically have different base paths to the same files.

    Args:
        library: Plex library section to search
        stash_path: File path from Stash
        plex_path_prefix: Unused, kept for API compatibility
        stash_path_prefix: Unused, kept for API compatibility

    Returns:
        Tuple of (confidence, best_match_or_none, all_candidates):
        - HIGH confidence + item: Single unique match found
        - LOW confidence + None: Multiple ambiguous matches (candidates list populated)
        - Raises PlexNotFound if no matches at all

    Raises:
        PlexNotFound: When no matching items found (allows retry logic)
    """
    import sys
    from plex.exceptions import PlexNotFound

    filename = Path(stash_path).name
    filename_lower = filename.lower()

    print(f"[PlexSync Matcher] Searching '{library.title}' for: {filename}", file=sys.stderr)

    candidates = []
    try:
        all_items = library.all()
        print(f"[PlexSync Matcher] Scanning {len(all_items)} items...", file=sys.stderr)

        for item in all_items:
            if _item_has_file(item, filename_lower, exact=False, case_insensitive=True):
                candidates.append(item)
                print(f"[PlexSync Matcher] Found: {item.title}", file=sys.stderr)

    except Exception as e:
        print(f"[PlexSync Matcher] Search failed: {e}", file=sys.stderr)

    # Scoring logic
    if len(candidates) == 0:
        raise PlexNotFound(f"No Plex item found for filename: {filename}")
    elif len(candidates) == 1:
        logger.debug(f"HIGH confidence match for {filename}")
        return (MatchConfidence.HIGH, candidates[0], candidates)
    else:
        # Multiple matches - log warning with candidate paths
        candidate_paths = []
        for item in candidates:
            try:
                if hasattr(item, 'media') and item.media:
                    if hasattr(item.media[0], 'parts') and item.media[0].parts:
                        candidate_paths.append(item.media[0].parts[0].file)
            except (IndexError, AttributeError):
                candidate_paths.append("<path unavailable>")

        logger.warning(
            f"LOW confidence match for '{filename}': "
            f"{len(candidates)} candidates found - {candidate_paths}"
        )
        return (MatchConfidence.LOW, None, candidates)
