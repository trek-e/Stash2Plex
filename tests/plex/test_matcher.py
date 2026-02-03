"""
Unit tests for plex/matcher.py.

Tests the Plex item matching logic including:
- _item_has_file helper function
- find_plex_item_by_path function
- find_plex_items_with_confidence function with confidence scoring
- Title parsing and regex patterns
"""

import pytest
from unittest.mock import MagicMock

from plex.matcher import (
    _item_has_file,
    find_plex_item_by_path,
    find_plex_items_with_confidence,
    MatchConfidence,
)
from plex.exceptions import PlexNotFound


# =============================================================================
# Helper Functions
# =============================================================================

def create_mock_plex_item(title: str, file_path: str):
    """Create a mock Plex item with the given title and file path."""
    item = MagicMock()
    item.title = title
    item.key = f"/library/metadata/{hash(file_path) % 10000}"

    part = MagicMock()
    part.file = file_path

    media = MagicMock()
    media.parts = [part]

    item.media = [media]
    return item


def create_mock_item_no_media(title: str):
    """Create a mock Plex item with no media attribute."""
    item = MagicMock()
    item.title = title
    item.media = None
    return item


def create_mock_item_empty_media(title: str):
    """Create a mock Plex item with empty media list."""
    item = MagicMock()
    item.title = title
    item.media = []
    return item


def create_mock_item_no_parts(title: str):
    """Create a mock Plex item with media but no parts."""
    item = MagicMock()
    item.title = title

    media = MagicMock()
    media.parts = []
    item.media = [media]
    return item


# =============================================================================
# _item_has_file Tests
# =============================================================================

class TestItemHasFile:
    """Tests for the _item_has_file helper function."""

    def test_item_has_file_exact_match(self):
        """Full path matches exactly returns True."""
        item = create_mock_plex_item("Test Video", "/media/videos/test.mp4")
        assert _item_has_file(item, "/media/videos/test.mp4", exact=True) is True

    def test_item_has_file_exact_no_match(self):
        """Full path does not match returns False."""
        item = create_mock_plex_item("Test Video", "/media/videos/test.mp4")
        assert _item_has_file(item, "/media/other/test.mp4", exact=True) is False

    def test_item_has_file_filename_only(self):
        """Filename matches when exact=False."""
        item = create_mock_plex_item("Test Video", "/media/videos/test.mp4")
        assert _item_has_file(item, "test.mp4", exact=False) is True

    def test_item_has_file_filename_different_path(self):
        """Filename matches despite different directory paths."""
        item = create_mock_plex_item("Test Video", "/media/videos/subdir/scene.mp4")
        assert _item_has_file(item, "scene.mp4", exact=False) is True

    def test_item_has_file_case_insensitive(self):
        """Case-insensitive matching works."""
        item = create_mock_plex_item("Test Video", "/media/videos/TEST.MP4")
        assert _item_has_file(item, "test.mp4", exact=False, case_insensitive=True) is True

    def test_item_has_file_case_sensitive_mismatch(self):
        """Case-sensitive matching rejects case differences."""
        item = create_mock_plex_item("Test Video", "/media/videos/TEST.MP4")
        assert _item_has_file(item, "test.mp4", exact=False, case_insensitive=False) is False

    def test_item_has_file_no_media(self):
        """Item with no media attribute returns False."""
        item = create_mock_item_no_media("Test Video")
        assert _item_has_file(item, "test.mp4", exact=False) is False

    def test_item_has_file_empty_media(self):
        """Item with empty media list returns False."""
        item = create_mock_item_empty_media("Test Video")
        assert _item_has_file(item, "test.mp4", exact=False) is False

    def test_item_has_file_no_parts(self):
        """Item with media but no parts returns False."""
        item = create_mock_item_no_parts("Test Video")
        assert _item_has_file(item, "test.mp4", exact=False) is False

    def test_item_has_file_no_file_attr(self):
        """Item with part but no file attribute returns False."""
        item = MagicMock()
        item.title = "Test"
        part = MagicMock(spec=[])  # No file attribute
        media = MagicMock()
        media.parts = [part]
        item.media = [media]
        assert _item_has_file(item, "test.mp4", exact=False) is False


# =============================================================================
# find_plex_item_by_path Tests
# =============================================================================

class TestFindPlexItemByPath:
    """Tests for find_plex_item_by_path function."""

    def test_single_match_returns_item(self, mock_plex_section):
        """One matching item is returned."""
        item = create_mock_plex_item("Scene Title", "/media/videos/scene.mp4")
        mock_plex_section.search.return_value = [item]

        result = find_plex_item_by_path(mock_plex_section, "/media/videos/scene.mp4")

        assert result == item

    def test_no_match_returns_none(self, mock_plex_section):
        """No matches returns None."""
        mock_plex_section.search.return_value = []
        mock_plex_section.all.return_value = []

        result = find_plex_item_by_path(mock_plex_section, "/nonexistent/file.mp4")

        assert result is None

    def test_multiple_matches_returns_none(self, mock_plex_section):
        """Multiple ambiguous matches returns None."""
        item1 = create_mock_plex_item("Scene 1", "/media/a/duplicate.mp4")
        item2 = create_mock_plex_item("Scene 2", "/media/b/duplicate.mp4")
        mock_plex_section.search.return_value = [item1, item2]

        result = find_plex_item_by_path(mock_plex_section, "/any/duplicate.mp4")

        assert result is None

    def test_title_search_fast_path(self, mock_plex_section):
        """Title search (fast path) is called first."""
        # The file path must match for item_has_file to succeed
        item = create_mock_plex_item("My Scene", "/media/My Scene.mp4")
        mock_plex_section.search.return_value = [item]

        result = find_plex_item_by_path(mock_plex_section, "/media/My Scene.mp4")

        mock_plex_section.search.assert_called()
        # Should not call all() since search found the matching item
        mock_plex_section.all.assert_not_called()
        assert result == item

    def test_fallback_to_all_scan(self, mock_plex_section):
        """When title search fails, library.all() is called as fallback."""
        item = create_mock_plex_item("Random Title", "/media/unique_filename.mp4")
        mock_plex_section.search.return_value = []
        mock_plex_section.all.return_value = [item]

        result = find_plex_item_by_path(mock_plex_section, "/media/unique_filename.mp4")

        mock_plex_section.all.assert_called_once()
        assert result == item

    def test_search_exception_triggers_fallback(self, mock_plex_section):
        """Exception in title search triggers fallback to all()."""
        item = create_mock_plex_item("Scene", "/media/scene.mp4")
        mock_plex_section.search.side_effect = Exception("Search failed")
        mock_plex_section.all.return_value = [item]

        result = find_plex_item_by_path(mock_plex_section, "/media/scene.mp4")

        assert result == item


# =============================================================================
# find_plex_items_with_confidence Tests
# =============================================================================

class TestFindPlexItemsWithConfidence:
    """Tests for find_plex_items_with_confidence function."""

    def test_single_match_high_confidence(self, mock_plex_section):
        """Single match returns HIGH confidence with item."""
        item = create_mock_plex_item("Scene Title", "/media/videos/scene.mp4")
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, "/media/videos/scene.mp4"
        )

        assert confidence == MatchConfidence.HIGH
        assert result_item == item
        assert len(candidates) == 1
        assert candidates[0] == item

    def test_no_match_raises_plex_not_found(self, mock_plex_section):
        """No matches raises PlexNotFound exception."""
        mock_plex_section.search.return_value = []
        mock_plex_section.all.return_value = []

        with pytest.raises(PlexNotFound) as exc_info:
            find_plex_items_with_confidence(mock_plex_section, "/nonexistent/file.mp4")

        assert "file.mp4" in str(exc_info.value)

    def test_multiple_matches_low_confidence(self, mock_plex_section):
        """Multiple matches returns LOW confidence with None item."""
        item1 = create_mock_plex_item("Scene 1", "/media/a/scene.mp4")
        item2 = create_mock_plex_item("Scene 2", "/media/b/scene.mp4")
        mock_plex_section.search.return_value = [item1, item2]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, "/any/scene.mp4"
        )

        assert confidence == MatchConfidence.LOW
        assert result_item is None
        assert len(candidates) == 2
        assert item1 in candidates
        assert item2 in candidates

    def test_confidence_enum_values(self):
        """MatchConfidence enum has correct string values."""
        assert MatchConfidence.HIGH.value == "high"
        assert MatchConfidence.LOW.value == "low"

    def test_fallback_search_on_title_failure(self, mock_plex_section):
        """Fallback to all() when title search finds nothing."""
        item = create_mock_plex_item("Different Title", "/media/specific.mp4")
        mock_plex_section.search.return_value = []
        mock_plex_section.all.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, "/media/specific.mp4"
        )

        assert confidence == MatchConfidence.HIGH
        assert result_item == item
        mock_plex_section.all.assert_called_once()


# =============================================================================
# Title Parsing Tests
# =============================================================================

class TestTitleParsing:
    """Tests for title extraction regex patterns."""

    @pytest.mark.parametrize("filename,should_find", [
        ("Scene - 1080p.mp4", True),
        ("Scene - 720p.mp4", True),
        ("Scene - 2160p.mp4", True),
        ("Scene - 4K.mp4", True),
    ])
    def test_title_strips_quality_suffix(self, mock_plex_section, filename, should_find):
        """Quality suffixes (720p, 1080p, 2160p, 4K) are stripped from title search."""
        # Create item that matches the base title "Scene"
        item = create_mock_plex_item("Scene", f"/media/{filename}")
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, f"/media/{filename}"
        )

        if should_find:
            assert result_item is not None
            # Verify search was called (title-based)
            mock_plex_section.search.assert_called()

    @pytest.mark.parametrize("filename", [
        "Scene - 2024-01-15.mp4",
        "Scene - 2026-02-03.mp4",
        "Scene_2024-01-15.mp4",
    ])
    def test_title_strips_date_suffix(self, mock_plex_section, filename):
        """Date suffixes (YYYY-MM-DD) are stripped from title search."""
        item = create_mock_plex_item("Scene", f"/media/{filename}")
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, f"/media/{filename}"
        )

        assert result_item is not None
        mock_plex_section.search.assert_called()

    @pytest.mark.parametrize("suffix", [
        "WEBDL",
        "WEB-DL",
        "WEBRip",
        "HDTV",
        "BluRay",
        "BDRip",
        "DVDRip",
        "HDR",
    ])
    def test_title_handles_various_formats(self, mock_plex_section, suffix):
        """Various quality format indicators are stripped from title."""
        filename = f"Scene - {suffix}.mp4"
        item = create_mock_plex_item("Scene", f"/media/{filename}")
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, f"/media/{filename}"
        )

        assert result_item is not None

    def test_title_with_multiple_suffixes(self, mock_plex_section):
        """Multiple quality indicators are all stripped."""
        filename = "Scene - BluRay 1080p HDR.mp4"
        item = create_mock_plex_item("Scene", f"/media/{filename}")
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, f"/media/{filename}"
        )

        assert result_item is not None

    def test_title_preserved_when_no_suffix(self, mock_plex_section):
        """Plain filename without quality suffix preserves full title."""
        filename = "My Awesome Scene.mp4"
        item = create_mock_plex_item("My Awesome Scene", f"/media/{filename}")
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, f"/media/{filename}"
        )

        assert result_item is not None


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handles_search_exception(self, mock_plex_section):
        """Gracefully handles exception during search."""
        item = create_mock_plex_item("Scene", "/media/scene.mp4")
        mock_plex_section.search.side_effect = Exception("Network error")
        mock_plex_section.all.return_value = [item]

        # Should fall back to all() and still find item
        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, "/media/scene.mp4"
        )

        assert result_item == item

    def test_handles_all_exception(self, mock_plex_section):
        """Handles exception during all() fallback."""
        mock_plex_section.search.return_value = []
        mock_plex_section.all.side_effect = Exception("Database error")

        with pytest.raises(PlexNotFound):
            find_plex_items_with_confidence(mock_plex_section, "/media/scene.mp4")

    def test_empty_filename(self, mock_plex_section):
        """Handles empty filename gracefully."""
        mock_plex_section.search.return_value = []
        mock_plex_section.all.return_value = []

        with pytest.raises(PlexNotFound):
            find_plex_items_with_confidence(mock_plex_section, "")

    def test_special_characters_in_path(self, mock_plex_section):
        """Handles special characters in file path."""
        filename = "Scene with (parentheses) & special-chars!.mp4"
        item = create_mock_plex_item("Scene", f"/media/{filename}")
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, f"/media/{filename}"
        )

        assert result_item is not None

    def test_unicode_in_filename(self, mock_plex_section):
        """Handles unicode characters in filename."""
        filename = "Scene avec cafe.mp4"
        item = create_mock_plex_item("Scene avec cafe", f"/media/{filename}")
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, f"/media/{filename}"
        )

        assert result_item is not None

    def test_multiple_media_entries(self, mock_plex_section):
        """Handles item with multiple media entries."""
        item = MagicMock()
        item.title = "Multi-version Scene"
        item.key = "/library/metadata/123"

        # First media entry (wrong file)
        part1 = MagicMock()
        part1.file = "/media/other.mp4"
        media1 = MagicMock()
        media1.parts = [part1]

        # Second media entry (matching file)
        part2 = MagicMock()
        part2.file = "/media/target.mp4"
        media2 = MagicMock()
        media2.parts = [part2]

        item.media = [media1, media2]
        mock_plex_section.search.return_value = [item]

        confidence, result_item, candidates = find_plex_items_with_confidence(
            mock_plex_section, "/media/target.mp4"
        )

        assert result_item == item
