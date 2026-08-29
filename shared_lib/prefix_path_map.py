"""
shared_lib.prefix_path_map — Bidirectional prefix-based path mapping.

Parses the ``plex_unmatched_path_map`` config setting into an ordered list
of ``(plex_prefix, stash_prefix)`` pairs, and applies them to translate a
path in either direction (first match wins).

This is the single implementation of the prefix-mapping logic used by:
    - reconciliation/engine.py (Plex -> Stash, for the unmatched pre-filter)
    - Stash2Plex.trigger_plex_scan_for_scene (Stash -> Plex, for scan paths)

Format: '/plex/prefix=>/stash/prefix; /plex2=>/stash2'

Note: this is a simple ordered prefix-substitution scheme, distinct from
shared_lib.path_mapper.PathMapper (regex-based, capture-group rules). It
mirrors the existing plex_unmatched_path_map config surface rather than
introducing a second, incompatible mapping mechanism.
"""
from typing import List, Optional, Tuple

from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("PrefixPathMap")


def parse_prefix_mappings(raw: Optional[str]) -> List[Tuple[str, str]]:
    """Parse a `plex_unmatched_path_map`-style string into (plex, stash) prefix pairs.

    Args:
        raw: Raw config value, e.g. '/plex/prefix=>/stash/prefix; /plex2=>/stash2'

    Returns:
        Ordered list of (plex_prefix, stash_prefix) tuples. Empty list if
        `raw` is empty/None or contains no valid entries.
    """
    raw = (raw or '').strip()
    if not raw:
        return []

    pairs: List[Tuple[str, str]] = []
    for item in [x.strip() for x in raw.split(';') if x.strip()]:
        if '=>' not in item:
            log_warn(f"Invalid path map entry (missing '=>'): {item}")
            continue
        src, dst = item.split('=>', 1)
        src = src.strip().rstrip('/')
        dst = dst.strip().rstrip('/')
        if not src or not dst:
            continue
        pairs.append((src, dst))
    return pairs


def _apply_prefix(path: str, mappings: List[Tuple[str, str]]) -> str:
    """Apply the first matching (src, dst) prefix pair to `path`."""
    normalized = path.replace('\\\\', '/')
    for src, dst in mappings:
        if normalized.startswith(src + '/') or normalized == src:
            return dst + normalized[len(src):]
    return normalized


def map_plex_to_stash(plex_path: str, mappings: List[Tuple[str, str]]) -> str:
    """Translate a Plex-side path to its Stash-side equivalent.

    Returns `plex_path` unchanged when no mapping matches (or none configured).
    """
    return _apply_prefix(plex_path, mappings)


def map_stash_to_plex(stash_path: str, mappings: List[Tuple[str, str]]) -> str:
    """Translate a Stash-side path to its Plex-side equivalent.

    Returns `stash_path` unchanged when no mapping matches (or none configured).
    """
    reversed_pairs = [(dst, src) for src, dst in mappings]
    return _apply_prefix(stash_path, reversed_pairs)
