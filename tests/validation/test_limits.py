"""
Tests for validation/limits.py - Plex field limit constants.

Tests verify:
- All constants are positive integers
- PLEX_LIMITS dict contains all expected keys
- Imports work correctly
"""

import pytest


class TestFieldLimitConstants:
    """Tests for individual limit constants."""

    def test_max_title_length_is_positive_int(self):
        """MAX_TITLE_LENGTH is a positive integer."""
        from validation.limits import MAX_TITLE_LENGTH
        assert isinstance(MAX_TITLE_LENGTH, int)
        assert MAX_TITLE_LENGTH > 0

    def test_max_studio_length_is_positive_int(self):
        """MAX_STUDIO_LENGTH is a positive integer."""
        from validation.limits import MAX_STUDIO_LENGTH
        assert isinstance(MAX_STUDIO_LENGTH, int)
        assert MAX_STUDIO_LENGTH > 0

    def test_max_summary_length_is_positive_int(self):
        """MAX_SUMMARY_LENGTH is a positive integer."""
        from validation.limits import MAX_SUMMARY_LENGTH
        assert isinstance(MAX_SUMMARY_LENGTH, int)
        assert MAX_SUMMARY_LENGTH > 0

    def test_max_tagline_length_is_positive_int(self):
        """MAX_TAGLINE_LENGTH is a positive integer."""
        from validation.limits import MAX_TAGLINE_LENGTH
        assert isinstance(MAX_TAGLINE_LENGTH, int)
        assert MAX_TAGLINE_LENGTH > 0

    def test_max_performer_name_length_is_positive_int(self):
        """MAX_PERFORMER_NAME_LENGTH is a positive integer."""
        from validation.limits import MAX_PERFORMER_NAME_LENGTH
        assert isinstance(MAX_PERFORMER_NAME_LENGTH, int)
        assert MAX_PERFORMER_NAME_LENGTH > 0

    def test_max_tag_name_length_is_positive_int(self):
        """MAX_TAG_NAME_LENGTH is a positive integer."""
        from validation.limits import MAX_TAG_NAME_LENGTH
        assert isinstance(MAX_TAG_NAME_LENGTH, int)
        assert MAX_TAG_NAME_LENGTH > 0

    def test_max_performers_is_positive_int(self):
        """MAX_PERFORMERS is a positive integer."""
        from validation.limits import MAX_PERFORMERS
        assert isinstance(MAX_PERFORMERS, int)
        assert MAX_PERFORMERS > 0

    def test_max_tags_is_positive_int(self):
        """MAX_TAGS is a positive integer."""
        from validation.limits import MAX_TAGS
        assert isinstance(MAX_TAGS, int)
        assert MAX_TAGS > 0

    def test_max_collections_is_positive_int(self):
        """MAX_COLLECTIONS is a positive integer."""
        from validation.limits import MAX_COLLECTIONS
        assert isinstance(MAX_COLLECTIONS, int)
        assert MAX_COLLECTIONS > 0


class TestFieldLimitValues:
    """Tests for expected limit values."""

    def test_title_limit_is_255(self):
        """Title limit is 255 characters."""
        from validation.limits import MAX_TITLE_LENGTH
        assert MAX_TITLE_LENGTH == 255

    def test_studio_limit_is_255(self):
        """Studio limit is 255 characters."""
        from validation.limits import MAX_STUDIO_LENGTH
        assert MAX_STUDIO_LENGTH == 255

    def test_summary_limit_is_10000(self):
        """Summary limit is 10000 characters."""
        from validation.limits import MAX_SUMMARY_LENGTH
        assert MAX_SUMMARY_LENGTH == 10000

    def test_tagline_limit_is_255(self):
        """Tagline limit is 255 characters."""
        from validation.limits import MAX_TAGLINE_LENGTH
        assert MAX_TAGLINE_LENGTH == 255

    def test_performers_limit_is_50(self):
        """Performers limit is 50."""
        from validation.limits import MAX_PERFORMERS
        assert MAX_PERFORMERS == 50

    def test_tags_limit_is_50(self):
        """Tags limit is 50."""
        from validation.limits import MAX_TAGS
        assert MAX_TAGS == 50

    def test_collections_limit_is_20(self):
        """Collections limit is 20."""
        from validation.limits import MAX_COLLECTIONS
        assert MAX_COLLECTIONS == 20


class TestPlexLimitsDict:
    """Tests for PLEX_LIMITS dictionary."""

    def test_plex_limits_is_dict(self):
        """PLEX_LIMITS is a dictionary."""
        from validation.limits import PLEX_LIMITS
        assert isinstance(PLEX_LIMITS, dict)

    def test_plex_limits_contains_title_key(self):
        """PLEX_LIMITS contains 'title' key."""
        from validation.limits import PLEX_LIMITS
        assert 'title' in PLEX_LIMITS

    def test_plex_limits_contains_studio_key(self):
        """PLEX_LIMITS contains 'studio' key."""
        from validation.limits import PLEX_LIMITS
        assert 'studio' in PLEX_LIMITS

    def test_plex_limits_contains_summary_key(self):
        """PLEX_LIMITS contains 'summary' key."""
        from validation.limits import PLEX_LIMITS
        assert 'summary' in PLEX_LIMITS

    def test_plex_limits_contains_tagline_key(self):
        """PLEX_LIMITS contains 'tagline' key."""
        from validation.limits import PLEX_LIMITS
        assert 'tagline' in PLEX_LIMITS

    def test_plex_limits_contains_performer_name_key(self):
        """PLEX_LIMITS contains 'performer_name' key."""
        from validation.limits import PLEX_LIMITS
        assert 'performer_name' in PLEX_LIMITS

    def test_plex_limits_contains_tag_name_key(self):
        """PLEX_LIMITS contains 'tag_name' key."""
        from validation.limits import PLEX_LIMITS
        assert 'tag_name' in PLEX_LIMITS

    def test_plex_limits_contains_performers_count_key(self):
        """PLEX_LIMITS contains 'performers_count' key."""
        from validation.limits import PLEX_LIMITS
        assert 'performers_count' in PLEX_LIMITS

    def test_plex_limits_contains_tags_count_key(self):
        """PLEX_LIMITS contains 'tags_count' key."""
        from validation.limits import PLEX_LIMITS
        assert 'tags_count' in PLEX_LIMITS

    def test_plex_limits_contains_collections_count_key(self):
        """PLEX_LIMITS contains 'collections_count' key."""
        from validation.limits import PLEX_LIMITS
        assert 'collections_count' in PLEX_LIMITS

    def test_plex_limits_values_match_constants(self):
        """PLEX_LIMITS values match individual constants."""
        from validation.limits import (
            PLEX_LIMITS,
            MAX_TITLE_LENGTH,
            MAX_STUDIO_LENGTH,
            MAX_SUMMARY_LENGTH,
            MAX_TAGLINE_LENGTH,
            MAX_PERFORMER_NAME_LENGTH,
            MAX_TAG_NAME_LENGTH,
            MAX_PERFORMERS,
            MAX_TAGS,
            MAX_COLLECTIONS,
        )

        assert PLEX_LIMITS['title'] == MAX_TITLE_LENGTH
        assert PLEX_LIMITS['studio'] == MAX_STUDIO_LENGTH
        assert PLEX_LIMITS['summary'] == MAX_SUMMARY_LENGTH
        assert PLEX_LIMITS['tagline'] == MAX_TAGLINE_LENGTH
        assert PLEX_LIMITS['performer_name'] == MAX_PERFORMER_NAME_LENGTH
        assert PLEX_LIMITS['tag_name'] == MAX_TAG_NAME_LENGTH
        assert PLEX_LIMITS['performers_count'] == MAX_PERFORMERS
        assert PLEX_LIMITS['tags_count'] == MAX_TAGS
        assert PLEX_LIMITS['collections_count'] == MAX_COLLECTIONS

    def test_plex_limits_has_expected_key_count(self):
        """PLEX_LIMITS has exactly 9 keys."""
        from validation.limits import PLEX_LIMITS
        assert len(PLEX_LIMITS) == 9


class TestImports:
    """Tests for module imports."""

    def test_import_all_constants(self):
        """All constants can be imported."""
        from validation.limits import (
            MAX_TITLE_LENGTH,
            MAX_STUDIO_LENGTH,
            MAX_SUMMARY_LENGTH,
            MAX_TAGLINE_LENGTH,
            MAX_PERFORMER_NAME_LENGTH,
            MAX_TAG_NAME_LENGTH,
            MAX_PERFORMERS,
            MAX_TAGS,
            MAX_COLLECTIONS,
            PLEX_LIMITS,
        )
        # All imports succeeded
        assert True

    def test_import_plex_limits_only(self):
        """PLEX_LIMITS can be imported alone."""
        from validation.limits import PLEX_LIMITS
        assert PLEX_LIMITS is not None
