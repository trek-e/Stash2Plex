"""
Pydantic metadata validation model for Stash2Plex.

Provides SyncMetadata model with field validation and sanitization
to ensure clean data before enqueueing for Plex sync.
"""

from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import Optional, Any

from validation.sanitizers import sanitize_for_plex


def _string_sanitizer(max_length: int, required: bool = False):
    """Create a Pydantic field_validator that sanitizes string fields.

    Args:
        max_length: Maximum allowed length after sanitization
        required: If True, None/empty raises ValueError
    """
    def validator(cls, v):
        if v is None:
            if required:
                raise ValueError("title is required")
            return None
        if not isinstance(v, str):
            v = str(v)
        sanitized = sanitize_for_plex(v, max_length=max_length)
        if required and not sanitized:
            raise ValueError("title cannot be empty after sanitization")
        return sanitized if sanitized else None
    return classmethod(validator)


class SyncMetadata(BaseModel):
    """
    Validated metadata structure for Plex sync jobs.

    Required fields:
        scene_id: Positive integer identifying the scene in Stash
        title: Non-empty string (1-255 chars) for the scene title

    Optional fields:
        details: Description/summary (max 10000 chars)
        date: Release date string
        rating100: Rating on 0-100 scale
        studio: Studio name (max 255 chars)
        performers: List of performer names
        tags: List of tag names

    All string fields are automatically sanitized via field_validator
    to remove control characters and normalize text.

    Example:
        >>> from validation.metadata import SyncMetadata
        >>> meta = SyncMetadata(
        ...     scene_id=123,
        ...     title="Example Scene",
        ...     studio="Example Studio",
        ...     performers=["Actor One", "Actor Two"]
        ... )
        >>> print(meta.title)
        Example Scene
    """

    # Required fields
    scene_id: int = Field(..., gt=0, description="Stash scene ID (positive integer)")
    title: str = Field(..., min_length=1, max_length=255, description="Scene title")

    # Optional fields
    details: Optional[str] = Field(default=None, max_length=10000, description="Scene description")
    date: Optional[str] = Field(default=None, description="Release date")
    rating100: Optional[int] = Field(default=None, ge=0, le=100, description="Rating 0-100")
    studio: Optional[str] = Field(default=None, max_length=255, description="Studio name")
    performers: Optional[list[str]] = Field(default=None, description="Performer names")
    tags: Optional[list[str]] = Field(default=None, description="Tag names")

    # Sanitize string fields via factory (DRY — all follow same pattern)
    sanitize_title = field_validator('title', mode='before')(
        _string_sanitizer(255, required=True))
    sanitize_details = field_validator('details', mode='before')(
        _string_sanitizer(10000))
    sanitize_studio = field_validator('studio', mode='before')(
        _string_sanitizer(255))

    @field_validator('performers', 'tags', mode='before')
    @classmethod
    def sanitize_string_list(cls, v: Any) -> Optional[list[str]]:
        """Sanitize list of string fields."""
        if v is None:
            return None
        if not isinstance(v, list):
            return None
        sanitized = [
            sanitize_for_plex(str(item), max_length=255)
            for item in v
            if item
        ]
        # Filter out empty strings after sanitization
        return [s for s in sanitized if s] or None


def validate_metadata(data: dict) -> tuple[Optional[SyncMetadata], Optional[str]]:
    """
    Validate metadata dictionary and return result.

    This helper allows callers to handle validation errors gracefully
    without needing to catch exceptions.

    Args:
        data: Dictionary containing metadata fields

    Returns:
        Tuple of (SyncMetadata, None) on success
        Tuple of (None, error_message) on validation failure
    """
    try:
        model = SyncMetadata(**data)
        return (model, None)
    except ValidationError as e:
        # Extract readable error message
        errors = e.errors()
        if errors:
            first_error = errors[0]
            field = '.'.join(str(loc) for loc in first_error.get('loc', []))
            msg = first_error.get('msg', 'validation error')
            return (None, f"{field}: {msg}")
        return (None, str(e))


# Re-export ValidationError for caller convenience
__all__ = ['SyncMetadata', 'validate_metadata', 'ValidationError']
