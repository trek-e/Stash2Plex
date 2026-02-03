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
# TestRequiresPlexSync - Helper function for filtering sync-worthy updates
# =============================================================================

class TestRequiresPlexSync:
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
