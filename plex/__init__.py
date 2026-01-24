"""
Plex API client module for PlexSync.

This module provides the interface for communicating with Plex servers,
including exception handling, timeout configuration, and retry logic.

Exceptions:
    PlexTemporaryError: Retry-able Plex errors (network, timeout, 5xx)
    PlexPermanentError: Non-retry-able Plex errors (auth, bad request)
    PlexNotFound: Item not found in Plex - may appear after library scan

Functions:
    translate_plex_exception: Convert plexapi exceptions to our hierarchy
"""

from plex.exceptions import (
    PlexTemporaryError,
    PlexPermanentError,
    PlexNotFound,
    translate_plex_exception,
)

__all__ = [
    'PlexTemporaryError',
    'PlexPermanentError',
    'PlexNotFound',
    'translate_plex_exception',
]
