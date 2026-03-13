"""
Validation module for Stash2Plex.

Provides metadata validation, text sanitization, partial sync result tracking,
and plugin configuration validation.
"""

from validation.sanitizers import sanitize_for_plex
from validation.errors import PartialSyncResult, FieldUpdateWarning
from validation.metadata import SyncMetadata, validate_metadata
from validation.config import Stash2PlexConfig, validate_config
from validation.obfuscation import obfuscate_path, configure_obfuscation

__all__ = [
    'sanitize_for_plex',
    'PartialSyncResult',
    'FieldUpdateWarning',
    'SyncMetadata',
    'validate_metadata',
    'Stash2PlexConfig',
    'validate_config',
    'obfuscate_path',
    'configure_obfuscation',
]
