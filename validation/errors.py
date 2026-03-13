"""
Partial sync result tracking for granular error handling.

Non-critical field failures (performers, tags, poster) don't fail the entire
sync job — they are tracked as warnings while the critical metadata edit proceeds.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class FieldUpdateWarning:
    """
    Warning for a non-critical field update that failed.

    These are logged but don't fail the entire sync job.
    Examples: performer sync failed, tag sync failed, poster upload failed.

    Attributes:
        field_name: The field that failed to update (e.g., "performers", "tags", "poster")
        error_message: The exception message describing what went wrong
        error_type: The exception class name (e.g., "PlexTemporaryError")
    """
    field_name: str
    error_message: str
    error_type: str

    def __str__(self) -> str:
        return f"{self.field_name}: {self.error_message}"


@dataclass
class PartialSyncResult:
    """
    Result of a metadata sync that may have partial failures.

    Tracks which fields succeeded, which had warnings, and provides
    a summary for logging. Used by _update_metadata() to return
    granular status instead of all-or-nothing success/failure.

    Attributes:
        success: Overall success status (True if critical fields OK)
        warnings: List of non-critical field failures
        fields_updated: List of fields that were successfully updated
    """
    success: bool = True
    warnings: List[FieldUpdateWarning] = field(default_factory=list)
    fields_updated: List[str] = field(default_factory=list)

    def add_warning(self, field_name: str, error: Exception) -> None:
        """
        Add a warning for a non-critical field failure.

        Args:
            field_name: Name of the field that failed
            error: The exception that caused the failure
        """
        self.warnings.append(FieldUpdateWarning(
            field_name=field_name,
            error_message=str(error),
            error_type=type(error).__name__
        ))

    def add_success(self, field_name: str) -> None:
        """
        Record a successful field update.

        Args:
            field_name: Name of the field that was updated successfully
        """
        self.fields_updated.append(field_name)

    @property
    def has_warnings(self) -> bool:
        """Return True if there are any warnings."""
        return len(self.warnings) > 0

    @property
    def warning_summary(self) -> str:
        """
        Human-readable summary of warnings.

        Returns:
            Empty string if no warnings, otherwise formatted summary
            like "2 warnings: performers: connection error; tags: timeout"
        """
        if not self.warnings:
            return ""
        return f"{len(self.warnings)} warnings: " + "; ".join(str(w) for w in self.warnings)
