"""
Plex API client module for Stash2Plex.

This module provides the interface for communicating with Plex servers,
including exception handling, timeout configuration, retry logic, and matching.

Classes:
    PlexClient: Wrapper around PlexServer with timeouts and retry
    PlexCache: Disk-backed cache for library data
    MatchCache: Disk-backed cache for path-to-item mappings
    MatchConfidence: Enum for match confidence scoring (HIGH/LOW)

Exceptions:
    PlexTemporaryError: Retry-able Plex errors (network, timeout, 5xx)
    PlexPermanentError: Non-retry-able Plex errors (auth, bad request)
    PlexNotFound: Item not found in Plex - may appear after library scan
    PlexServerDown: Server unreachable (special circuit breaker handling)

Functions:
    translate_plex_exception: Convert plexapi exceptions to our hierarchy
    find_plex_items_with_confidence: Find Plex items with confidence scoring
    check_plex_health: Deep health check via /identity endpoint
"""

from plex.exceptions import (
    PlexTemporaryError,
    PlexPermanentError,
    PlexNotFound,
    PlexServerDown,
    translate_plex_exception,
)
from plex.client import PlexClient
from plex.matcher import find_plex_items_with_confidence, MatchConfidence
from plex.cache import PlexCache, MatchCache
from plex.health import check_plex_health

__all__ = [
    # Client
    'PlexClient',
    # Exceptions
    'PlexTemporaryError',
    'PlexPermanentError',
    'PlexNotFound',
    'PlexServerDown',
    'translate_plex_exception',
    # Matching
    'find_plex_items_with_confidence',
    'MatchConfidence',
    # Caching
    'PlexCache',
    'MatchCache',
    # Health
    'check_plex_health',
]
