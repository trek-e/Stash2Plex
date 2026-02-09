"""
Path obfuscation for privacy-safe logging.

Replaces file path segments with deterministic word-based substitutions
so users can share troubleshooting logs without exposing directory structure.

The mapping is per-session (resets on process restart) and deterministic
within a session — same path always maps to same words for log correlation.

Example:
    /media/videos/Studio Name/scene-title.mp4
    → /Crimson/Tiger/Azure/Phoenix.mp4
"""

import hashlib
from pathlib import PurePosixPath, PureWindowsPath

# Module-level state (configured once at startup)
_enabled: bool = False
_segment_map: dict[str, str] = {}

# 64 visually distinct, memorable words (colors, animals, code words)
WORD_LIST = [
    "Crimson", "Azure", "Emerald", "Golden", "Silver",
    "Violet", "Amber", "Coral", "Ivory", "Onyx",
    "Scarlet", "Teal", "Copper", "Indigo", "Jade",
    "Maroon", "Sage", "Bronze", "Cobalt", "Pearl",
    "Tiger", "Phoenix", "Falcon", "Raven", "Wolf",
    "Eagle", "Cobra", "Panther", "Lynx", "Hawk",
    "Otter", "Viper", "Crane", "Bison", "Fox",
    "Owl", "Elk", "Bear", "Lion", "Dove",
    "Atlas", "Beacon", "Cipher", "Delta", "Echo",
    "Forge", "Granite", "Harbor", "Icon", "Jetty",
    "Keystone", "Lantern", "Meridian", "Nexus", "Orbit",
    "Prism", "Quartz", "Ridge", "Summit", "Torch",
    "Vault", "Zenith", "Apex", "Bastion",
]


def configure_obfuscation(enabled: bool) -> None:
    """Configure path obfuscation on/off. Called once at startup."""
    global _enabled, _segment_map
    _enabled = enabled
    _segment_map = {}


def reset_obfuscation() -> None:
    """Reset obfuscation state (for testing)."""
    global _enabled, _segment_map
    _enabled = False
    _segment_map = {}


def _get_word_for_segment(segment: str) -> str:
    """Map a path segment to a deterministic word."""
    if segment in _segment_map:
        return _segment_map[segment]

    h = hashlib.md5(segment.encode('utf-8', errors='replace')).hexdigest()
    index = int(h[:8], 16) % len(WORD_LIST)
    word = WORD_LIST[index]

    # Handle collisions: if word already used for a different segment, add suffix
    existing_words = set(_segment_map.values())
    if word in existing_words:
        counter = 2
        while f"{word}{counter}" in existing_words:
            counter += 1
        word = f"{word}{counter}"

    _segment_map[segment] = word
    return word


def obfuscate_path(path: str) -> str:
    """
    Obfuscate a file path with deterministic word substitutions.

    Returns original path unchanged when obfuscation is disabled.
    Preserves file extension and leading path separator.

    Args:
        path: File path to obfuscate

    Returns:
        Obfuscated path (if enabled) or original path (if disabled)
    """
    if not _enabled or not path:
        return path

    # Detect path type by separator
    if '\\' in path:
        parts = PureWindowsPath(path).parts
        sep = '\\'
    else:
        parts = PurePosixPath(path).parts
        sep = '/'

    obfuscated = []
    for i, part in enumerate(parts):
        # Skip root separators
        if part in ('/', '\\'):
            continue

        if i == len(parts) - 1:
            # Last segment: preserve extension
            p = PurePosixPath(part)
            ext = p.suffix
            stem = p.stem
            obfuscated.append(_get_word_for_segment(stem) + ext)
        else:
            obfuscated.append(_get_word_for_segment(part))

    result = sep.join(obfuscated)
    if path.startswith('/') or path.startswith('\\'):
        result = sep + result

    return result
