"""
Tests for SyncMetadata Pydantic model and validate_metadata helper.

Tests validation rules for required/optional fields, sanitization behavior,
and error handling for the metadata validation module.
"""

import pytest
from pydantic import ValidationError

from validation.metadata import SyncMetadata, validate_metadata


class TestSyncMetadata:
    """Tests for SyncMetadata Pydantic model."""

    # =========================================================================
    # Required field tests
    # =========================================================================

    def test_valid_minimal_metadata(self):
        """Minimum required fields create valid model."""
        metadata = SyncMetadata(scene_id=1, title="Test")
        assert metadata.scene_id == 1
        assert metadata.title == "Test"

    @pytest.mark.parametrize("invalid_scene_id", [0, -1, -100])
    def test_scene_id_must_be_positive(self, invalid_scene_id):
        """scene_id must be greater than 0."""
        with pytest.raises(ValidationError) as exc_info:
            SyncMetadata(scene_id=invalid_scene_id, title="Test")
        # Verify error mentions scene_id constraint
        errors = exc_info.value.errors()
        assert any("scene_id" in str(e.get("loc", [])) for e in errors)

    def test_scene_id_required(self):
        """scene_id is a required field."""
        with pytest.raises(ValidationError) as exc_info:
            SyncMetadata(title="Test")
        errors = exc_info.value.errors()
        assert any("scene_id" in str(e.get("loc", [])) for e in errors)

    def test_title_required(self):
        """title is a required field."""
        with pytest.raises(ValidationError) as exc_info:
            SyncMetadata(scene_id=1)
        errors = exc_info.value.errors()
        assert any("title" in str(e.get("loc", [])) for e in errors)

    def test_title_cannot_be_empty(self):
        """Empty string title is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncMetadata(scene_id=1, title="")
        errors = exc_info.value.errors()
        assert any("title" in str(e.get("loc", [])) for e in errors)

    def test_title_whitespace_only_rejected(self):
        """Whitespace-only title is rejected (becomes empty after sanitization)."""
        with pytest.raises(ValidationError) as exc_info:
            SyncMetadata(scene_id=1, title="   ")
        errors = exc_info.value.errors()
        assert any("title" in str(e.get("loc", [])) for e in errors)

    # =========================================================================
    # Optional field tests
    # =========================================================================

    def test_all_optional_fields_accepted(self, sample_metadata_dict):
        """Model accepts all optional fields."""
        metadata = SyncMetadata(**sample_metadata_dict)
        assert metadata.scene_id == sample_metadata_dict["scene_id"]
        assert metadata.title == sample_metadata_dict["title"]
        assert metadata.details == sample_metadata_dict["details"]
        assert metadata.date == sample_metadata_dict["date"]
        assert metadata.rating100 == sample_metadata_dict["rating100"]
        assert metadata.studio == sample_metadata_dict["studio"]
        assert metadata.performers == sample_metadata_dict["performers"]
        assert metadata.tags == sample_metadata_dict["tags"]

    def test_details_max_length_accepted(self):
        """10000 character details is accepted."""
        long_details = "x" * 10000
        metadata = SyncMetadata(scene_id=1, title="Test", details=long_details)
        assert len(metadata.details) <= 10000

    def test_details_exceeds_max_length_truncated(self):
        """Details exceeding 10000 chars is truncated by sanitizer."""
        long_details = "x" * 10001
        metadata = SyncMetadata(scene_id=1, title="Test", details=long_details)
        # Sanitizer truncates to max_length before Pydantic validation
        assert len(metadata.details) == 10000

    @pytest.mark.parametrize("rating,should_pass", [
        (0, True),
        (50, True),
        (100, True),
        (-1, False),
        (101, False),
    ])
    def test_rating100_range(self, rating, should_pass):
        """rating100 must be 0-100."""
        if should_pass:
            metadata = SyncMetadata(scene_id=1, title="Test", rating100=rating)
            assert metadata.rating100 == rating
        else:
            with pytest.raises(ValidationError) as exc_info:
                SyncMetadata(scene_id=1, title="Test", rating100=rating)
            errors = exc_info.value.errors()
            assert any("rating100" in str(e.get("loc", [])) for e in errors)

    def test_performers_list_accepted(self):
        """performers field accepts list of strings."""
        metadata = SyncMetadata(scene_id=1, title="Test", performers=["A", "B"])
        assert metadata.performers == ["A", "B"]

    def test_tags_list_accepted(self):
        """tags field accepts list of strings."""
        metadata = SyncMetadata(scene_id=1, title="Test", tags=["X", "Y"])
        assert metadata.tags == ["X", "Y"]

    # =========================================================================
    # Sanitization tests
    # =========================================================================

    def test_title_control_chars_removed(self):
        """Control characters are removed from title."""
        metadata = SyncMetadata(scene_id=1, title="Test\x00Title\x1f")
        assert "\x00" not in metadata.title
        assert "\x1f" not in metadata.title
        assert "Test" in metadata.title
        assert "Title" in metadata.title

    def test_title_smart_quotes_converted(self):
        """Smart quotes in title are converted to ASCII equivalents."""
        # Left/right double quotes
        metadata = SyncMetadata(scene_id=1, title="\u201cQuoted\u201d")
        assert metadata.title == '"Quoted"'

    def test_title_smart_single_quotes_converted(self):
        """Smart single quotes are converted to ASCII."""
        metadata = SyncMetadata(scene_id=1, title="\u2018Hello\u2019")
        assert metadata.title == "'Hello'"

    def test_title_dashes_converted(self):
        """En dash and em dash are converted to hyphen."""
        # En dash
        metadata1 = SyncMetadata(scene_id=1, title="A\u2013B")
        assert metadata1.title == "A-B"
        # Em dash
        metadata2 = SyncMetadata(scene_id=1, title="A\u2014B")
        assert metadata2.title == "A-B"

    def test_title_ellipsis_converted(self):
        """Unicode ellipsis is converted to three dots."""
        metadata = SyncMetadata(scene_id=1, title="Wait\u2026")
        assert metadata.title == "Wait..."

    def test_details_sanitized(self):
        """Details field is sanitized."""
        metadata = SyncMetadata(scene_id=1, title="Test", details="Text\x00with\x1fcontrol")
        assert "\x00" not in metadata.details
        assert "\x1f" not in metadata.details

    def test_studio_sanitized(self):
        """Studio name is sanitized."""
        metadata = SyncMetadata(scene_id=1, title="Test", studio="Studio\x00Name")
        assert "\x00" not in metadata.studio

    def test_performers_sanitized(self):
        """Performer names in list are sanitized."""
        metadata = SyncMetadata(scene_id=1, title="Test", performers=["Name\x00One", "Name\x1fTwo"])
        for performer in metadata.performers:
            assert "\x00" not in performer
            assert "\x1f" not in performer

    def test_tags_sanitized(self):
        """Tag names in list are sanitized."""
        metadata = SyncMetadata(scene_id=1, title="Test", tags=["Tag\x00One", "Tag\x1fTwo"])
        for tag in metadata.tags:
            assert "\x00" not in tag
            assert "\x1f" not in tag

    def test_title_whitespace_normalized(self):
        """Multiple whitespace in title is collapsed."""
        metadata = SyncMetadata(scene_id=1, title="Test   Title  Here")
        assert metadata.title == "Test Title Here"

    def test_title_stripped(self):
        """Leading/trailing whitespace is stripped from title."""
        metadata = SyncMetadata(scene_id=1, title="  Test Title  ")
        assert metadata.title == "Test Title"

    def test_empty_performers_list_becomes_none(self):
        """Empty list after sanitization becomes None."""
        metadata = SyncMetadata(scene_id=1, title="Test", performers=[])
        assert metadata.performers is None

    def test_performers_with_empty_strings_filtered(self):
        """Empty strings in performers list are filtered out."""
        metadata = SyncMetadata(scene_id=1, title="Test", performers=["Valid", "", "   ", "Also Valid"])
        assert metadata.performers == ["Valid", "Also Valid"]


class TestValidateMetadata:
    """Tests for validate_metadata helper function."""

    def test_validate_metadata_success_returns_model(self, sample_metadata_dict):
        """Valid data returns (model, None)."""
        result, error = validate_metadata(sample_metadata_dict)
        assert result is not None
        assert error is None
        assert isinstance(result, SyncMetadata)
        assert result.scene_id == sample_metadata_dict["scene_id"]

    def test_validate_metadata_failure_returns_error(self):
        """Invalid data returns (None, error_string)."""
        result, error = validate_metadata({"scene_id": -1, "title": "Test"})
        assert result is None
        assert error is not None
        assert isinstance(error, str)

    def test_validate_metadata_error_includes_field_name(self):
        """Error message mentions the failing field."""
        result, error = validate_metadata({"title": "Test"})  # Missing scene_id
        assert result is None
        assert "scene_id" in error

    def test_validate_metadata_missing_title_error(self):
        """Missing title produces error mentioning title."""
        result, error = validate_metadata({"scene_id": 1})
        assert result is None
        assert "title" in error

    def test_validate_metadata_empty_dict(self):
        """Empty dict returns error for missing fields."""
        result, error = validate_metadata({})
        assert result is None
        assert error is not None

    def test_validate_metadata_extra_fields_ignored(self):
        """Extra fields not in model are ignored."""
        data = {"scene_id": 1, "title": "Test", "unknown_field": "value"}
        result, error = validate_metadata(data)
        assert result is not None
        assert error is None
        assert not hasattr(result, "unknown_field")

    def test_validate_metadata_none_title_error(self):
        """None title produces meaningful error."""
        result, error = validate_metadata({"scene_id": 1, "title": None})
        assert result is None
        assert "title" in error
