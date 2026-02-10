"""
Unit tests for hooks/handlers.py.

Tests hook handler filtering, validation, and enqueueing with mocked dependencies.
Covers requires_plex_sync, is_scan_running, pending scene functions, and on_scene_update.
"""

import pytest
from unittest.mock import MagicMock, patch


# Import functions under test
from hooks.handlers import (
    requires_plex_sync,
    is_scan_running,
    mark_scene_pending,
    unmark_scene_pending,
    is_scene_pending,
    on_scene_update,
)


@pytest.fixture(autouse=True)
def clear_pending_scenes():
    """Clear pending scene IDs before and after each test to prevent state pollution."""
    from hooks import handlers
    handlers._pending_scene_ids.clear()
    yield
    handlers._pending_scene_ids.clear()


# =============================================================================
# TestRequiresStash2Plex - Helper function for filtering sync-worthy updates
# =============================================================================

class TestRequiresStash2Plex:
    """Tests for requires_plex_sync helper function."""

    def test_title_triggers_sync(self):
        """Title update should trigger sync."""
        assert requires_plex_sync({"title": "New Title"}) is True

    def test_details_triggers_sync(self):
        """Details update should trigger sync."""
        assert requires_plex_sync({"details": "New description"}) is True

    def test_studio_id_triggers_sync(self):
        """studio_id update should trigger sync."""
        assert requires_plex_sync({"studio_id": 1}) is True

    def test_performer_ids_triggers_sync(self):
        """performer_ids update should trigger sync."""
        assert requires_plex_sync({"performer_ids": [1, 2, 3]}) is True

    def test_tag_ids_triggers_sync(self):
        """tag_ids update should trigger sync."""
        assert requires_plex_sync({"tag_ids": [1]}) is True

    def test_rating100_triggers_sync(self):
        """rating100 update should trigger sync."""
        assert requires_plex_sync({"rating100": 50}) is True

    def test_date_triggers_sync(self):
        """date update should trigger sync."""
        assert requires_plex_sync({"date": "2024-01-01"}) is True

    def test_rating_triggers_sync(self):
        """rating (legacy field) update should trigger sync."""
        assert requires_plex_sync({"rating": 4}) is True

    def test_studio_triggers_sync(self):
        """studio (name string) update should trigger sync."""
        assert requires_plex_sync({"studio": "Test Studio"}) is True

    def test_performers_triggers_sync(self):
        """performers list update should trigger sync."""
        assert requires_plex_sync({"performers": ["Actor 1"]}) is True

    def test_tags_triggers_sync(self):
        """tags list update should trigger sync."""
        assert requires_plex_sync({"tags": ["Tag 1"]}) is True

    def test_play_count_does_not_trigger(self):
        """play_count update should not trigger sync."""
        assert requires_plex_sync({"play_count": 5}) is False

    def test_view_history_does_not_trigger(self):
        """last_played_at update should not trigger sync."""
        assert requires_plex_sync({"last_played_at": 123456789}) is False

    def test_empty_update_does_not_trigger(self):
        """Empty update data should not trigger sync."""
        assert requires_plex_sync({}) is False

    def test_file_only_update_does_not_trigger(self):
        """File-only updates should not trigger sync."""
        assert requires_plex_sync({"files": [{"path": "/test.mp4"}]}) is False

    def test_multiple_sync_fields(self):
        """Multiple sync-worthy fields should trigger sync."""
        assert requires_plex_sync({
            "title": "New Title",
            "studio_id": 1,
            "rating100": 80
        }) is True

    def test_mixed_sync_and_non_sync_fields(self):
        """Update with both sync and non-sync fields should trigger sync."""
        assert requires_plex_sync({
            "play_count": 5,
            "title": "New Title"
        }) is True


# =============================================================================
# TestIsScanRunning - Helper function for detecting active scan jobs
# =============================================================================

class TestIsScanRunning:
    """Tests for is_scan_running helper function."""

    def test_no_stash_returns_false(self):
        """is_scan_running(None) should return False."""
        assert is_scan_running(None) is False

    def test_no_jobs_returns_false(self):
        """Empty job queue should return False."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {"jobQueue": []}

        assert is_scan_running(mock_stash) is False

    def test_scan_running_returns_true(self):
        """RUNNING job with 'scan' in description should return True."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": "RUNNING", "description": "Scanning library..."}
            ]
        }

        assert is_scan_running(mock_stash) is True

    def test_generate_running_returns_true(self):
        """RUNNING job with 'generate' in description should return True."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": "RUNNING", "description": "Generate thumbnails"}
            ]
        }

        assert is_scan_running(mock_stash) is True

    def test_auto_tag_running_returns_true(self):
        """RUNNING job with 'auto tag' in description should return True."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": "RUNNING", "description": "Auto tag scenes"}
            ]
        }

        assert is_scan_running(mock_stash) is True

    def test_identify_running_returns_true(self):
        """RUNNING job with 'identify' in description should return True."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": "RUNNING", "description": "Identify task"}
            ]
        }

        assert is_scan_running(mock_stash) is True

    def test_ready_status_returns_true(self):
        """READY job with scan keyword should return True."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": "READY", "description": "Scanning..."}
            ]
        }

        assert is_scan_running(mock_stash) is True

    def test_completed_scan_returns_false(self):
        """FINISHED job should return False."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": "FINISHED", "description": "Scanning library..."}
            ]
        }

        assert is_scan_running(mock_stash) is False

    def test_non_scan_job_running_returns_false(self):
        """RUNNING job without scan keyword should return False."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": "RUNNING", "description": "Exporting data"}
            ]
        }

        assert is_scan_running(mock_stash) is False

    def test_gql_error_returns_false(self):
        """Exception during GQL call should return False (safe default)."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.side_effect = Exception("Connection error")

        assert is_scan_running(mock_stash) is False

    def test_gql_returns_none(self):
        """GQL returning None should return False."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = None

        assert is_scan_running(mock_stash) is False

    def test_missing_jobqueue_key(self):
        """GQL response without jobQueue key should return False."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {}

        assert is_scan_running(mock_stash) is False

    def test_null_status_in_job(self):
        """Job with null status should be handled gracefully."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": None, "description": "Scanning..."}
            ]
        }

        assert is_scan_running(mock_stash) is False

    def test_null_description_in_job(self):
        """Job with null description should be handled gracefully."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "jobQueue": [
                {"status": "RUNNING", "description": None}
            ]
        }

        assert is_scan_running(mock_stash) is False


# =============================================================================
# TestPendingScenes - In-memory deduplication functions
# =============================================================================

class TestPendingScenes:
    """Tests for mark_scene_pending, unmark_scene_pending, and is_scene_pending."""

    def test_mark_and_check_pending(self):
        """Mark scene as pending, verify is_scene_pending returns True."""
        scene_id = 123
        assert is_scene_pending(scene_id) is False

        mark_scene_pending(scene_id)

        assert is_scene_pending(scene_id) is True

    def test_unmark_clears_pending(self):
        """Mark then unmark scene, verify is_scene_pending returns False."""
        scene_id = 456
        mark_scene_pending(scene_id)
        assert is_scene_pending(scene_id) is True

        unmark_scene_pending(scene_id)

        assert is_scene_pending(scene_id) is False

    def test_unmark_nonexistent_safe(self):
        """Unmark scene never marked should not raise error."""
        scene_id = 999
        assert is_scene_pending(scene_id) is False

        # Should not raise
        unmark_scene_pending(scene_id)

        assert is_scene_pending(scene_id) is False

    def test_separate_scenes_independent(self):
        """Marking one scene should not affect others."""
        scene_id_1 = 100
        scene_id_2 = 200

        mark_scene_pending(scene_id_1)

        assert is_scene_pending(scene_id_1) is True
        assert is_scene_pending(scene_id_2) is False

    def test_multiple_marks_idempotent(self):
        """Marking same scene multiple times should not cause issues."""
        scene_id = 333
        mark_scene_pending(scene_id)
        mark_scene_pending(scene_id)
        mark_scene_pending(scene_id)

        assert is_scene_pending(scene_id) is True

        unmark_scene_pending(scene_id)

        assert is_scene_pending(scene_id) is False

    def test_mark_multiple_scenes(self):
        """Multiple scenes can be pending simultaneously."""
        scene_ids = [1, 2, 3, 4, 5]

        for scene_id in scene_ids:
            mark_scene_pending(scene_id)

        for scene_id in scene_ids:
            assert is_scene_pending(scene_id) is True

        # Unmarking one should not affect others
        unmark_scene_pending(3)
        assert is_scene_pending(3) is False
        assert is_scene_pending(1) is True
        assert is_scene_pending(5) is True


# =============================================================================
# TestOnSceneUpdate - Main handler function tests
# =============================================================================

class TestOnSceneUpdate:
    """Tests for on_scene_update handler function."""

    # -------------------------------------------------------------------------
    # Fixtures for on_scene_update tests
    # -------------------------------------------------------------------------

    @pytest.fixture
    def mock_stash_gql(self):
        """Mock Stash interface with call_GQL returning scene data."""
        stash = MagicMock()
        stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "details": "Test description",
                "date": "2024-01-15",
                "rating100": 80,
                "files": [{"path": "/media/test.mp4"}],
                "studio": {"name": "Test Studio"},
                "performers": [{"name": "Actor One"}, {"name": "Actor Two"}],
                "tags": [{"name": "Tag One"}],
                "paths": {
                    "screenshot": "http://stash/screenshot.jpg",
                    "preview": "http://stash/preview.mp4"
                }
            }
        }
        return stash

    @pytest.fixture
    def mock_validated_metadata(self):
        """Mock validated metadata object."""
        validated = MagicMock()
        validated.title = "Test Scene"
        validated.scene_id = 123
        validated.details = "Test description"
        validated.rating100 = 80
        validated.date = "2024-01-15"
        validated.studio = "Test Studio"
        validated.performers = ["Actor One", "Actor Two"]
        validated.tags = ["Tag One"]
        return validated

    # -------------------------------------------------------------------------
    # Filter tests
    # -------------------------------------------------------------------------

    def test_filters_non_sync_events(self, mock_queue):
        """Non-metadata updates (play_count) should return False."""
        result = on_scene_update(
            scene_id=123,
            update_data={"play_count": 5},
            queue=mock_queue,
            stash=None
        )

        assert result is False
        mock_queue.put.assert_not_called()

    def test_filters_during_scan(self, mock_queue, mocker, mock_stash_gql):
        """Updates during active scan should return False."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=True)

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert result is False
        mock_queue.put.assert_not_called()

    def test_identification_bypasses_scan_gate(self, mock_queue, mocker, mock_stash_gql):
        """Identification events should bypass scan-running gate."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=True)
        mocker.patch('hooks.handlers.enqueue', return_value=True)

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test", "studio_id": "1", "performer_ids": ["1"]},
            queue=mock_queue,
            stash=mock_stash_gql,
            is_identification=True
        )

        assert result is True

    def test_filters_already_pending(self, mock_queue, mocker, mock_stash_gql):
        """Scene already pending should return False."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)

        # Mark scene as already pending
        mark_scene_pending(123)

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert result is False

    def test_filters_already_synced_timestamp(self, mock_queue, mocker, mock_stash_gql):
        """Scene with newer sync timestamp should return False."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)

        # Sync timestamps with recent sync
        sync_timestamps = {123: 9999999999.0}  # Far future timestamp

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test", "updated_at": 1000000000.0},
            queue=mock_queue,
            sync_timestamps=sync_timestamps,
            stash=mock_stash_gql
        )

        assert result is False

    def test_passes_filter_when_stash_updated_newer(self, mock_queue, mocker, mock_stash_gql):
        """Scene updated after last sync should pass filter."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        # Sync timestamp in past
        sync_timestamps = {123: 1000000000.0}

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test", "updated_at": 2000000000.0},
            queue=mock_queue,
            sync_timestamps=sync_timestamps,
            stash=mock_stash_gql
        )

        assert result is True
        mock_enqueue.assert_called_once()

    # -------------------------------------------------------------------------
    # File path tests
    # -------------------------------------------------------------------------

    def test_returns_false_no_file_path(self, mock_queue, mocker):
        """Scene without file path should return False."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)

        # Stash returns scene without files
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [],  # No files
                "studio": None,
                "performers": [],
                "tags": [],
                "paths": {}
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is False

    def test_extracts_file_path_from_scene(self, mock_queue, mocker, mock_stash_gql):
        """File path should be extracted from GQL response."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert result is True
        # Verify enqueue was called with data containing path
        call_args = mock_enqueue.call_args
        assert call_args is not None

    # -------------------------------------------------------------------------
    # Validation tests
    # -------------------------------------------------------------------------

    def test_validates_metadata_before_enqueue(self, mock_queue, mocker, mock_stash_gql):
        """validate_metadata should be called with correct data."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mock_validate = mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        on_scene_update(
            scene_id=123,
            update_data={"title": "New Title"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        mock_validate.assert_called_once()
        # Verify scene_id is in validation data
        call_args = mock_validate.call_args[0][0]
        assert call_args['scene_id'] == 123

    def test_enqueues_on_valid_metadata(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata):
        """Valid metadata should trigger enqueue."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, None))

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert result is True
        mock_enqueue.assert_called_once()

    def test_returns_false_on_title_validation_error(self, mock_queue, mocker, mock_stash_gql):
        """Title validation error should return False."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        # Validation returns None for validated object with title error message
        # Note: Must provide non-empty title to trigger validation path
        mocker.patch('hooks.handlers.validate_metadata', return_value=(None, "title is required and cannot be empty"))

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Bad Title"},  # Non-empty to trigger validation
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert result is False
        mock_enqueue.assert_not_called()

    def test_continues_on_non_critical_validation_error(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata):
        """Non-critical validation errors should still enqueue with warning."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        # Return validated metadata with non-critical error (not title-related)
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, "rating100 out of range"))

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test", "rating100": 150},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert result is True
        mock_enqueue.assert_called_once()

    # -------------------------------------------------------------------------
    # Enqueue tests
    # -------------------------------------------------------------------------

    def test_enqueues_with_correct_structure(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata):
        """Enqueue should be called with (queue, scene_id, 'metadata', data)."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, None))

        on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        mock_enqueue.assert_called_once()
        call_args = mock_enqueue.call_args
        # Verify positional args: (queue, scene_id, update_type, data)
        assert call_args[0][0] == mock_queue
        assert call_args[0][1] == 123
        assert call_args[0][2] == "metadata"
        assert isinstance(call_args[0][3], dict)

    def test_marks_scene_pending_after_enqueue(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata):
        """After successful enqueue, scene should be marked pending."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, None))

        assert is_scene_pending(123) is False

        on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert is_scene_pending(123) is True

    def test_returns_true_on_success(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata):
        """Successful enqueue should return True."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, None))

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert result is True

    # -------------------------------------------------------------------------
    # Timing test
    # -------------------------------------------------------------------------

    def test_logs_warning_over_100ms(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata, capsys):
        """Execution over 100ms should log warning."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, None))

        # Mock time to simulate slow execution
        time_values = [0.0, 0.15]  # Start at 0, end at 150ms later
        mocker.patch('time.time', side_effect=time_values)

        on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        # Check stderr for warning about exceeding 100ms
        captured = capsys.readouterr()
        assert "exceeded 100ms" in captured.err or "100ms target" in captured.err

    # -------------------------------------------------------------------------
    # Edge case tests
    # -------------------------------------------------------------------------

    def test_handles_missing_studio(self, mock_queue, mocker):
        """Scene without studio should be handled gracefully (syncs if other metadata present)."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=["Performer A"], tags=None
        ), None))

        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": None,  # No studio
                "performers": [{"id": "1", "name": "Performer A"}],
                "tags": [],
                "paths": {}
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is True
        mock_enqueue.assert_called_once()

    def test_defers_sync_when_no_metadata(self, mock_queue, mocker):
        """Scene with no metadata beyond title/path should defer sync (may still be identifying)."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')

        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": None,
                "performers": [],
                "tags": [],
                "paths": {}
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is False
        mock_enqueue.assert_not_called()

    def test_handles_missing_performers(self, mock_queue, mocker):
        """Scene without performers should be handled gracefully."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": {"name": "Studio"},
                "performers": [],  # No performers
                "tags": [{"name": "Tag"}],
                "paths": {}
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is True

    def test_handles_missing_tags(self, mock_queue, mocker):
        """Scene without tags should be handled gracefully."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": {"name": "Studio"},
                "performers": [{"name": "Actor"}],
                "tags": [],  # No tags
                "paths": {}
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is True

    def test_handles_missing_paths(self, mock_queue, mocker):
        """Scene without paths should be handled gracefully."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": {"name": "Studio"},
                "performers": [],
                "tags": [],
                "paths": None  # No paths
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is True

    def test_gql_fallback_to_callGraphQL(self, mock_queue, mocker):
        """Fallback to _callGraphQL when call_GQL not available."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        mock_stash = MagicMock(spec=[])  # Empty spec to avoid call_GQL
        mock_stash._callGraphQL = MagicMock(return_value={
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": None,
                "performers": [],
                "tags": [],
                "paths": {}
            }
        })
        # Need to add hasattr behavior
        type(mock_stash).call_GQL = None
        mock_stash.call_GQL = MagicMock(side_effect=AttributeError("no call_GQL"))

        # Since the mock needs special handling, create fresh mock
        mock_stash = MagicMock()
        # Remove call_GQL so hasattr returns False
        del mock_stash.call_GQL
        mock_stash._callGraphQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": {"name": "Test Studio"},
                "performers": [{"name": "Actor One"}],
                "tags": [{"name": "Tag One"}],
                "paths": {}
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is True
        mock_stash._callGraphQL.assert_called_once()

    def test_gql_fallback_to_find_scene(self, mock_queue, mocker):
        """Fallback to find_scene when GQL calls fail."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        mock_stash = MagicMock()
        mock_stash.call_GQL.side_effect = Exception("GQL failed")
        mock_stash.find_scene.return_value = {
            "id": "123",
            "title": "Test Scene",
            "files": [{"path": "/media/test.mp4"}],
            "studio": {"name": "Test Studio"},
            "performers": [{"name": "Actor One"}],
            "tags": [{"name": "Tag One"}],
            "paths": {}
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is True
        mock_stash.find_scene.assert_called_once_with(123)

    def test_enqueue_not_available(self, mock_queue, mocker, mock_stash_gql):
        """Missing enqueue function should return False."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mocker.patch('hooks.handlers.enqueue', None)

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        assert result is False

    def test_no_title_skips_validation(self, mock_queue, mocker):
        """Missing title in update should skip validation and enqueue as-is."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mock_validate = mocker.patch('hooks.handlers.validate_metadata')

        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": None,  # No title in scene
                "files": [{"path": "/media/test.mp4"}],
                "studio": {"name": "Test Studio"},
                "performers": [{"name": "Actor One"}],
                "tags": [],
                "paths": {}
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"studio_id": 1},  # No title in update
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is True
        # Validation should not be called when no title
        mock_validate.assert_not_called()
        mock_enqueue.assert_called_once()

    def test_sync_timestamps_none_uses_current_time(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata):
        """When sync_timestamps is None, scene should pass filter."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, None))

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            sync_timestamps=None,  # No timestamps
            stash=mock_stash_gql
        )

        assert result is True
        mock_enqueue.assert_called_once()

    def test_preserves_extra_fields_from_update_data(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata):
        """Extra fields like studio_id should be preserved in enqueue data."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, None))

        on_scene_update(
            scene_id=123,
            update_data={"title": "Test", "studio_id": 5, "performer_ids": [1, 2]},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        call_args = mock_enqueue.call_args
        enqueued_data = call_args[0][3]
        # Extra fields should be preserved
        assert "studio_id" in enqueued_data
        assert enqueued_data["studio_id"] == 5

    def test_stash_fetch_exception_handled(self, mock_queue, mocker):
        """Exception during Stash fetch should be handled gracefully."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)

        mock_stash = MagicMock()
        mock_stash.call_GQL.side_effect = Exception("Network error")
        mock_stash.find_scene.side_effect = Exception("Also failed")

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        # Should return False since no file path could be obtained
        assert result is False

    def test_timestamp_fallback_when_updated_at_missing(self, mock_queue, mocker, mock_stash_gql, mock_validated_metadata):
        """When sync_timestamps exists but updated_at is missing, use current time."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_validated_metadata, None))
        mocker.patch('time.time', return_value=2000000000.0)

        # Sync timestamp in past, no updated_at in update_data
        sync_timestamps = {123: 1000000000.0}

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},  # No updated_at field
            queue=mock_queue,
            sync_timestamps=sync_timestamps,
            stash=mock_stash_gql
        )

        # Should pass filter since current time (2000000000) > last_synced (1000000000)
        assert result is True
        mock_enqueue.assert_called_once()

    def test_stash_without_call_gql_or_callGraphQL(self, mock_queue, mocker):
        """Stash without call_GQL or _callGraphQL should use find_scene."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        mocker.patch('hooks.handlers.validate_metadata', return_value=(MagicMock(
            title="Test Scene", scene_id=123, details=None, rating100=None,
            date=None, studio=None, performers=None, tags=None
        ), None))

        # Create a mock stash that has neither call_GQL nor _callGraphQL
        class MinimalStash:
            def find_scene(self, scene_id):
                return {
                    "id": "123",
                    "title": "Test Scene",
                    "files": [{"path": "/media/test.mp4"}],
                    "studio": {"name": "Test Studio"},
                    "performers": [{"name": "Actor One"}],
                    "tags": [{"name": "Tag One"}],
                    "paths": {}
                }

        mock_stash = MinimalStash()

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test"},
            queue=mock_queue,
            stash=mock_stash
        )

        assert result is True
        mock_enqueue.assert_called_once()

    def test_validation_returns_none_with_non_title_error(self, mock_queue, mocker, mock_stash_gql):
        """Validation returning None with non-title error should return False."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_enqueue = mocker.patch('hooks.handlers.enqueue')
        # Validation returns None (no validated object) with non-title error
        mocker.patch('hooks.handlers.validate_metadata', return_value=(None, "invalid date format"))

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test", "date": "not-a-date"},
            queue=mock_queue,
            stash=mock_stash_gql
        )

        # Should return False because validated is None (line 347)
        assert result is False
        mock_enqueue.assert_not_called()
