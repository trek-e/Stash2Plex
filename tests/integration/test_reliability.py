"""
Integration tests for reliability hardening - field limits and clearing.

Tests verify the LOCKED user decision (missing optional fields clear Plex values)
and field limit enforcement across the full sync workflow.
"""

import pytest
from unittest.mock import MagicMock, patch

from validation.limits import (
    MAX_TITLE_LENGTH,
    MAX_STUDIO_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_PERFORMERS,
    MAX_TAGS,
)
from validation.sanitizers import sanitize_for_plex, strip_emojis


class TestFieldClearing:
    """Test LOCKED decision: missing optional fields clear Plex values."""

    @pytest.fixture
    def clearing_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker configured for clearing tests."""
        from worker.processor import SyncWorker

        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        return worker

    def test_none_studio_clears_plex_studio(self, clearing_worker):
        """When Stash sends studio=None, existing Plex studio is cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"
        mock_plex_item.title = "Test Title"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Data dict has 'studio' key with None value (LOCKED: should clear)
        data = {'path': '/test.mp4', 'title': 'Test', 'studio': None}

        clearing_worker._update_metadata(mock_plex_item, data)

        # Verify edit was called with empty studio
        mock_plex_item.edit.assert_called()
        first_edit = mock_plex_item.edit.call_args_list[0][1]
        assert 'studio.value' in first_edit
        assert first_edit['studio.value'] == ''

    def test_empty_string_clears_plex_value(self, clearing_worker):
        """When Stash sends empty string, existing Plex value is cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"
        mock_plex_item.title = "Test Title"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Empty string should also clear (LOCKED decision)
        data = {'path': '/test.mp4', 'title': 'Test', 'studio': ''}

        clearing_worker._update_metadata(mock_plex_item, data)

        mock_plex_item.edit.assert_called()
        first_edit = mock_plex_item.edit.call_args_list[0][1]
        assert first_edit['studio.value'] == ''

    def test_empty_performers_clears_plex_actors(self, clearing_worker, capsys):
        """When Stash sends performers=[], existing Plex actors are cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = [MagicMock(tag="Actor 1"), MagicMock(tag="Actor 2")]
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Empty performers list (LOCKED: should clear all actors)
        data = {'path': '/test.mp4', 'performers': []}

        clearing_worker._update_metadata(mock_plex_item, data)

        # Verify clearing was logged
        captured = capsys.readouterr()
        assert "Clearing performers" in captured.err

    def test_empty_tags_clears_plex_genres(self, clearing_worker, capsys):
        """When Stash sends tags=[], existing Plex genres are cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = [MagicMock(tag="Genre 1")]
        mock_plex_item.collections = []

        # Empty tags list (LOCKED: should clear all genres)
        data = {'path': '/test.mp4', 'tags': []}

        clearing_worker._update_metadata(mock_plex_item, data)

        captured = capsys.readouterr()
        assert "Clearing tags" in captured.err

    def test_field_not_in_data_preserves_plex_value(self, clearing_worker):
        """When field key not in data dict, existing Plex value preserved."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"
        mock_plex_item.title = "Test"
        mock_plex_item.summary = "Existing Summary"
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Data dict does NOT have 'studio' key - should NOT clear
        data = {'path': '/test.mp4', 'title': 'New Title'}

        clearing_worker._update_metadata(mock_plex_item, data)

        # Verify studio was NOT included in any edit call
        for call in mock_plex_item.edit.call_args_list:
            if call[1]:  # has kwargs
                assert 'studio.value' not in call[1]

    def test_none_date_clears_plex_date(self, clearing_worker):
        """When Stash sends date=None, existing Plex date is cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.originallyAvailableAt = "2020-01-01"
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Date is None (LOCKED: should clear)
        data = {'path': '/test.mp4', 'date': None}

        clearing_worker._update_metadata(mock_plex_item, data)

        # Find the edit call with date
        found_date_clear = False
        for call in mock_plex_item.edit.call_args_list:
            if call[1] and 'originallyAvailableAt.value' in call[1]:
                assert call[1]['originallyAvailableAt.value'] == ''
                found_date_clear = True
        assert found_date_clear, "Date clearing not found in edit calls"


class TestFieldLimits:
    """Test field length and count limits."""

    @pytest.fixture
    def limits_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker configured for limits tests."""
        from worker.processor import SyncWorker

        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        return worker

    def test_performers_truncated_at_max(self, limits_worker, capsys):
        """More than MAX_PERFORMERS performers are truncated with warning."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Create more performers than MAX_PERFORMERS
        excess_count = 10
        performers = [f"Performer {i}" for i in range(MAX_PERFORMERS + excess_count)]
        data = {'path': '/test.mp4', 'performers': performers}

        limits_worker._update_metadata(mock_plex_item, data)

        captured = capsys.readouterr()
        assert "Truncating performers list" in captured.err
        assert str(MAX_PERFORMERS + excess_count) in captured.err
        assert str(MAX_PERFORMERS) in captured.err

    def test_tags_truncated_at_max(self, limits_worker, capsys):
        """More than MAX_TAGS tags are truncated with warning."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Create more tags than MAX_TAGS
        excess_count = 15
        tags = [f"Tag {i}" for i in range(MAX_TAGS + excess_count)]
        data = {'path': '/test.mp4', 'tags': tags}

        limits_worker._update_metadata(mock_plex_item, data)

        captured = capsys.readouterr()
        assert "Truncating tags list" in captured.err

    def test_long_title_truncated(self, limits_worker):
        """Title longer than MAX_TITLE_LENGTH is truncated."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Create title longer than max
        long_title = "x" * (MAX_TITLE_LENGTH + 50)
        data = {'path': '/test.mp4', 'title': long_title}

        limits_worker._update_metadata(mock_plex_item, data)

        # Verify title was truncated
        mock_plex_item.edit.assert_called()
        first_edit = mock_plex_item.edit.call_args_list[0][1]
        assert len(first_edit['title.value']) <= MAX_TITLE_LENGTH

    def test_long_summary_truncated(self, limits_worker):
        """Summary longer than MAX_SUMMARY_LENGTH is truncated."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Create summary longer than max
        long_summary = "x" * (MAX_SUMMARY_LENGTH + 500)
        data = {'path': '/test.mp4', 'details': long_summary}

        limits_worker._update_metadata(mock_plex_item, data)

        # Verify summary was truncated
        mock_plex_item.edit.assert_called()
        first_edit = mock_plex_item.edit.call_args_list[0][1]
        assert len(first_edit['summary.value']) <= MAX_SUMMARY_LENGTH

    def test_combined_performers_truncated(self, limits_worker, capsys):
        """Combined existing + new performers are truncated at max."""
        mock_actor = MagicMock()
        mock_actor.tag = "Existing Actor"

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        # Start with many existing actors
        mock_plex_item.actors = [MagicMock(tag=f"Existing {i}") for i in range(MAX_PERFORMERS - 5)]
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Add more performers that would exceed the limit when combined
        performers = [f"New Performer {i}" for i in range(20)]
        data = {'path': '/test.mp4', 'performers': performers}

        limits_worker._update_metadata(mock_plex_item, data)

        captured = capsys.readouterr()
        # Should warn about truncating combined list
        assert "Truncating" in captured.err


class TestEmojiHandling:
    """Test emoji handling in metadata."""

    def test_emoji_in_title_preserved_by_default(self):
        """Emojis in title are preserved by default."""
        # U+1F600 GRINNING FACE
        text = "Hello \U0001F600 World"
        result = sanitize_for_plex(text)
        assert "\U0001F600" in result
        assert "Hello" in result
        assert "World" in result

    def test_emoji_stripping_when_enabled(self):
        """Emojis stripped when strip_emoji=True."""
        # U+1F600 GRINNING FACE
        text = "Hello \U0001F600 World"
        result = sanitize_for_plex(text, strip_emoji=True)
        assert "\U0001F600" not in result
        assert "Hello" in result
        assert "World" in result

    def test_strip_emojis_basic(self):
        """strip_emojis removes common emojis."""
        # U+1F525 FIRE, U+1F389 PARTY POPPER
        text = "Test \U0001F525 \U0001F389 content"
        result = strip_emojis(text)
        assert "Test" in result
        assert "content" in result
        # Emojis should be removed (they are in 'So' category)
        assert "\U0001F525" not in result
        assert "\U0001F389" not in result

    def test_emoji_with_control_chars(self):
        """Emoji and control chars are handled correctly together."""
        # U+1F525 FIRE emoji
        text = "Test\x00\U0001F525 data"
        result = sanitize_for_plex(text, strip_emoji=True)
        # Control char removed
        assert "\x00" not in result
        # Emoji removed
        assert "\U0001F525" not in result
        # Text preserved
        assert "Test" in result
        assert "data" in result

    def test_unicode_text_preserved_with_emoji_strip(self):
        """Unicode letters preserved when stripping emojis."""
        # U+2B50 WHITE MEDIUM STAR
        text = "Caf\u00e9 \u2B50 r\u00e9sum\u00e9"
        result = sanitize_for_plex(text, strip_emoji=True)
        # Unicode letters preserved (e with acute accent)
        assert "\u00e9" in result
        # Emoji removed
        assert "\u2B50" not in result


class TestFullReliabilityWorkflow:
    """Integration tests for full reliability workflow."""

    @pytest.fixture
    def workflow_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker for workflow tests."""
        from worker.processor import SyncWorker

        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        return worker

    def test_mixed_clearing_and_setting(self, workflow_worker):
        """Mix of clearing some fields and setting others."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Old Studio"
        mock_plex_item.title = "Old Title"
        mock_plex_item.summary = "Old Summary"
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Clear studio, set new title and summary
        data = {
            'path': '/test.mp4',
            'title': 'New Title',
            'studio': None,  # Clear
            'details': 'New summary content',
        }

        workflow_worker._update_metadata(mock_plex_item, data)

        mock_plex_item.edit.assert_called()
        first_edit = mock_plex_item.edit.call_args_list[0][1]
        # Title should be set
        assert first_edit['title.value'] == 'New Title'
        # Studio should be cleared
        assert first_edit['studio.value'] == ''
        # Summary should be set
        assert first_edit['summary.value'] == 'New summary content'

    def test_all_fields_cleared(self, workflow_worker, capsys):
        """All fields can be cleared in single update."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Studio"
        mock_plex_item.title = "Title"
        mock_plex_item.summary = "Summary"
        mock_plex_item.tagline = "Tagline"
        mock_plex_item.originallyAvailableAt = "2020-01-01"
        mock_plex_item.actors = [MagicMock(tag="Actor")]
        mock_plex_item.genres = [MagicMock(tag="Genre")]
        mock_plex_item.collections = []

        # Clear everything
        data = {
            'path': '/test.mp4',
            'title': '',
            'studio': None,
            'details': '',
            'tagline': None,
            'date': '',
            'performers': [],
            'tags': [],
        }

        workflow_worker._update_metadata(mock_plex_item, data)

        mock_plex_item.edit.assert_called()
        first_edit = mock_plex_item.edit.call_args_list[0][1]
        # All scalar fields should be cleared
        assert first_edit['title.value'] == ''
        assert first_edit['studio.value'] == ''
        assert first_edit['summary.value'] == ''
        assert first_edit['tagline.value'] == ''
        assert first_edit['originallyAvailableAt.value'] == ''

        # List fields logged as cleared
        captured = capsys.readouterr()
        assert "Clearing performers" in captured.err
        assert "Clearing tags" in captured.err

    def test_sanitization_applied_with_limits(self, workflow_worker):
        """Sanitization and truncation applied together."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Title with control chars and over max length
        title_with_issues = "\x00Long title " + "x" * MAX_TITLE_LENGTH
        data = {'path': '/test.mp4', 'title': title_with_issues}

        workflow_worker._update_metadata(mock_plex_item, data)

        mock_plex_item.edit.assert_called()
        first_edit = mock_plex_item.edit.call_args_list[0][1]
        result_title = first_edit['title.value']
        # Control char removed
        assert "\x00" not in result_title
        # Truncated to max length
        assert len(result_title) <= MAX_TITLE_LENGTH


class TestPartialFailure:
    """Integration tests for partial sync failure recovery."""

    @pytest.fixture
    def partial_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker for partial failure tests."""
        from worker.processor import SyncWorker

        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        return worker

    def test_performer_failure_doesnt_fail_job(self, partial_worker, capsys):
        """Performer sync failure doesn't fail the overall job."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make performer edit fail
        def edit_side_effect(**kwargs):
            if 'actor[0].tag.tag' in kwargs:
                raise ConnectionError("Plex connection failed")
        mock_plex_item.edit.side_effect = edit_side_effect

        data = {
            'path': '/test.mp4',
            'title': 'Test Movie',
            'performers': ['Actor 1', 'Actor 2'],
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        # Job succeeds
        assert result.success is True
        # Metadata was updated
        assert 'metadata' in result.fields_updated
        # Performer warning recorded
        assert any(w.field_name == 'performers' for w in result.warnings)

        captured = capsys.readouterr()
        assert "Partial sync" in captured.err

    def test_poster_upload_failure_doesnt_fail_job(self, partial_worker):
        """Poster upload failure doesn't fail the overall job."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make poster upload fail
        mock_plex_item.uploadPoster.side_effect = Exception("Upload failed")
        partial_worker._fetch_stash_image = MagicMock(return_value=b'image data')

        data = {
            'path': '/test.mp4',
            'title': 'Test Movie',
            'poster_url': 'http://stash/poster.jpg',
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        assert result.success is True
        assert 'metadata' in result.fields_updated
        assert any(w.field_name == 'poster' for w in result.warnings)

    def test_multiple_field_failures_aggregated(self, partial_worker, capsys):
        """Multiple non-critical failures are aggregated into warnings."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make performer and tag edits fail
        def edit_side_effect(**kwargs):
            if 'actor[0].tag.tag' in kwargs:
                raise ConnectionError("Actor error")
            if 'genre[0].tag.tag' in kwargs:
                raise TimeoutError("Tag error")
        mock_plex_item.edit.side_effect = edit_side_effect

        data = {
            'path': '/test.mp4',
            'title': 'Test Movie',
            'performers': ['Actor 1'],
            'tags': ['Tag 1'],
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        # Job succeeds with warnings
        assert result.success is True
        assert len(result.warnings) == 2
        warning_fields = [w.field_name for w in result.warnings]
        assert 'performers' in warning_fields
        assert 'tags' in warning_fields

        captured = capsys.readouterr()
        assert "2 warnings" in captured.err

    def test_title_failure_fails_job(self, partial_worker):
        """Title (critical field) failure propagates and fails job."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make core edit fail
        mock_plex_item.edit.side_effect = ConnectionError("Plex down")

        data = {
            'path': '/test.mp4',
            'title': 'Test Movie',
        }

        # Critical field failure should propagate
        with pytest.raises(ConnectionError):
            partial_worker._update_metadata(mock_plex_item, data)


class TestResponseValidation:
    """Integration tests for API response validation."""

    @pytest.fixture
    def validation_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker for validation tests."""
        from worker.processor import SyncWorker

        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        return worker

    def test_validate_edit_result_detects_mismatch(self, validation_worker):
        """_validate_edit_result detects when Plex value differs from sent."""
        mock_plex_item = MagicMock()
        mock_plex_item.title = "Different Title"  # Plex has different value

        edits = {'title.value': 'Sent Title'}

        issues = validation_worker._validate_edit_result(mock_plex_item, edits)

        assert len(issues) == 1
        assert 'title' in issues[0]
        assert 'Sent Title' in issues[0]
        assert 'Different Title' in issues[0]

    def test_validate_edit_result_passes_on_match(self, validation_worker):
        """_validate_edit_result returns empty list when values match."""
        mock_plex_item = MagicMock()
        mock_plex_item.title = "Test Title"
        mock_plex_item.studio = "Test Studio"

        edits = {
            'title.value': 'Test Title',
            'studio.value': 'Test Studio',
        }

        issues = validation_worker._validate_edit_result(mock_plex_item, edits)

        assert issues == []

    def test_validate_edit_result_detects_empty_after_set(self, validation_worker):
        """_validate_edit_result detects when value didn't save."""
        mock_plex_item = MagicMock()
        mock_plex_item.title = ""  # Value didn't save
        mock_plex_item.studio = None

        edits = {
            'title.value': 'Test Title',
            'studio.value': 'Test Studio',
        }

        issues = validation_worker._validate_edit_result(mock_plex_item, edits)

        assert len(issues) == 2
        assert any('title' in issue for issue in issues)
        assert any('studio' in issue for issue in issues)

    def test_edit_validation_logs_issues(self, validation_worker, capsys):
        """Edit validation issues are logged at debug level."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Different"  # Doesn't match sent value
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {
            'path': '/test.mp4',
            'title': 'Test Title',
        }

        validation_worker._update_metadata(mock_plex_item, data)

        captured = capsys.readouterr()
        # Validation issues logged at debug level
        assert "validation issues" in captured.err

    def test_silent_truncation_detected(self, validation_worker):
        """Server-side truncation is detected by validation."""
        mock_plex_item = MagicMock()
        # Simulate Plex truncating a long title
        mock_plex_item.title = "Short"

        edits = {'title.value': 'Very Long Title That Got Truncated By Plex'}

        issues = validation_worker._validate_edit_result(mock_plex_item, edits)

        assert len(issues) == 1
        assert 'title' in issues[0]

    def test_validation_skips_empty_values(self, validation_worker):
        """Validation doesn't flag fields that were intentionally cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.title = ""
        mock_plex_item.studio = ""

        # Intentionally clearing fields
        edits = {
            'title.value': '',
            'studio.value': '',
        }

        issues = validation_worker._validate_edit_result(mock_plex_item, edits)

        # No issues for intentional clears
        assert issues == []

    def test_validation_skips_locked_fields(self, validation_worker):
        """Validation ignores locked field flags."""
        mock_plex_item = MagicMock()
        mock_plex_item.title = "Test"

        edits = {
            'title.value': 'Test',
            'actor.locked': 1,  # Lock flag, not a value
        }

        issues = validation_worker._validate_edit_result(mock_plex_item, edits)

        # Locked field not validated
        assert issues == []
