"""
Configuration validation for PlexSync.

Provides pydantic v2 models for validating plugin configuration
with fail-fast behavior and sensible defaults.
"""

from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import Optional
import logging

log = logging.getLogger('PlexSync.config')


class PlexSyncConfig(BaseModel):
    """
    PlexSync plugin configuration with validation.

    Required:
        plex_url: Plex server URL (e.g., http://192.168.1.100:32400)
        plex_token: Plex authentication token

    Optional tunables:
        enabled: Master on/off switch (default: True)
        max_retries: Retry attempts before DLQ (default: 5, range: 1-20)
        poll_interval: Worker poll interval in seconds (default: 1.0, range: 0.1-60.0)
        strict_mode: If True, reject invalid metadata; if False, sanitize and continue (default: False)
        plex_connect_timeout: Connection timeout in seconds (default: 5.0, range: 1.0-30.0)
        plex_read_timeout: Read timeout in seconds (default: 30.0, range: 5.0-120.0)
    """

    # Required fields
    plex_url: str
    plex_token: str

    # Optional tunables with defaults
    enabled: bool = True
    max_retries: int = Field(default=5, ge=1, le=20)
    poll_interval: float = Field(default=1.0, ge=0.1, le=60.0)
    strict_mode: bool = False

    # Plex connection timeouts (in seconds)
    plex_connect_timeout: float = Field(default=5.0, ge=1.0, le=30.0)
    plex_read_timeout: float = Field(default=30.0, ge=5.0, le=120.0)

    @field_validator('plex_url', mode='after')
    @classmethod
    def validate_plex_url(cls, v: str) -> str:
        """Validate plex_url is a valid HTTP/HTTPS URL."""
        if not v:
            raise ValueError('plex_url is required')
        if not v.startswith(('http://', 'https://')):
            raise ValueError('plex_url must start with http:// or https://')
        return v.rstrip('/')  # Normalize: remove trailing slash

    @field_validator('plex_token', mode='after')
    @classmethod
    def validate_plex_token(cls, v: str) -> str:
        """Validate plex_token is present and reasonable length."""
        if not v:
            raise ValueError('plex_token is required')
        if len(v) < 10:
            raise ValueError('plex_token appears invalid (too short)')
        return v

    def log_config(self) -> None:
        """Log configuration with masked token for security."""
        if len(self.plex_token) > 8:
            masked = self.plex_token[:4] + '****' + self.plex_token[-4:]
        else:
            masked = '****'
        log.info(
            f"PlexSync config: url={self.plex_url}, token={masked}, "
            f"max_retries={self.max_retries}, enabled={self.enabled}, "
            f"strict_mode={self.strict_mode}, "
            f"connect_timeout={self.plex_connect_timeout}s, "
            f"read_timeout={self.plex_read_timeout}s"
        )


def validate_config(config_dict: dict) -> tuple[Optional[PlexSyncConfig], Optional[str]]:
    """
    Validate configuration dictionary and return PlexSyncConfig or error message.

    Args:
        config_dict: Dictionary containing configuration values

    Returns:
        Tuple of (PlexSyncConfig, None) on success,
        or (None, error_message) on validation failure
    """
    try:
        config = PlexSyncConfig(**config_dict)
        return (config, None)
    except ValidationError as e:
        # Extract user-friendly error messages
        errors = []
        for error in e.errors():
            field = '.'.join(str(loc) for loc in error['loc'])
            msg = error['msg']
            errors.append(f"{field}: {msg}")
        error_message = '; '.join(errors)
        return (None, error_message)


# Re-export ValidationError for external use
__all__ = ['PlexSyncConfig', 'validate_config', 'ValidationError']
