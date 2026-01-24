"""
Validation module for PlexSync.

Provides metadata validation, text sanitization, error classification,
and plugin configuration validation.
"""

from validation.sanitizers import sanitize_for_plex
from validation.errors import classify_exception, classify_http_error
from validation.metadata import SyncMetadata, validate_metadata
from validation.config import PlexSyncConfig, validate_config

__all__ = [
    'sanitize_for_plex',
    'classify_exception',
    'classify_http_error',
    'SyncMetadata',
    'validate_metadata',
    'PlexSyncConfig',
    'validate_config',
]
