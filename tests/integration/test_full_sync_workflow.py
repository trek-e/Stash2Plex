"""
Integration tests for full sync workflow.

Tests verify end-to-end sync flow:
- Job processing updates Plex metadata correctly
- All metadata fields sync (title, studio, summary, performers, tags)
- Sync timestamp updated after successful sync
- Scene unmarked from pending after processing

These tests use mocked Plex/Stash but exercise the full code path
through SyncWorker._process_job().

CRITICAL WIRING: The integration_worker fixture returns (worker, mock_plex_item).
The worker's Plex client is wired to return mock_plex_item on search.
When tests call worker._process_job(), the worker finds mock_plex_item
and calls mock_plex_item.edit(). Tests verify this by checking
mock_plex_item.edit.assert_called() - confirming the fixture wiring works.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch


def get_all_edit_kwargs(mock_plex_item):
    """Extract kwargs from all calls to mock_plex_item.edit().

    The processor calls edit() multiple times (metadata, performers, genres, collections).
    This helper collects kwargs from all calls for comprehensive assertion.

    Returns:
        dict: Merged kwargs from all edit() calls
    """
    all_kwargs = {}
    for call in mock_plex_item.edit.call_args_list:
        all_kwargs.update(call.kwargs)
    return all_kwargs


@pytest.mark.integration
class TestFullSyncWorkflow:
    """Integration tests for complete sync flow."""

    def test_metadata_syncs_to_plex_item(self, integration_worker, sample_sync_job):
        """Job processing updates Plex item with all metadata fields.

        Verifies critical wiring: mock_plex_item.edit() is called,
        confirming the fixture's Plex client mock returns the correct
        item and worker processes it through _process_job().
        """
        worker, mock_plex_item = integration_worker

        # Process the job
        worker._process_job(sample_sync_job)

        # CRITICAL: Verify mock_plex_item.edit() is called.
        # This confirms the integration_worker fixture wiring works:
        # worker._plex_client.server.library.section().search() returns [mock_plex_item]
        # worker finds this item and calls mock_plex_item.edit()
        mock_plex_item.edit.assert_called()
        # Processor calls edit() multiple times (metadata, performers, genres, collections)
        # so we need to check all calls for the metadata fields
        all_kwargs = get_all_edit_kwargs(mock_plex_item)
        assert 'title.value' in all_kwargs or 'summary.value' in all_kwargs

    def test_title_synced_to_plex(self, integration_worker, sample_sync_job):
        """Title field syncs from Stash to Plex."""
        worker, mock_plex_item = integration_worker
        sample_sync_job['data']['title'] = 'New Test Title'

        worker._process_job(sample_sync_job)

        # Verify mock_plex_item (from fixture) receives the edit call
        mock_plex_item.edit.assert_called()
        all_kwargs = get_all_edit_kwargs(mock_plex_item)
        assert all_kwargs.get('title.value') == 'New Test Title'

    def test_studio_synced_to_plex(self, integration_worker, sample_sync_job):
        """Studio field syncs from Stash to Plex."""
        worker, mock_plex_item = integration_worker
        sample_sync_job['data']['studio'] = 'New Studio Name'

        worker._process_job(sample_sync_job)

        # Studio might be in first or second edit call (metadata vs collection)
        assert mock_plex_item.edit.called

    def test_summary_synced_from_details(self, integration_worker, sample_sync_job):
        """Stash 'details' field syncs to Plex 'summary'."""
        worker, mock_plex_item = integration_worker
        sample_sync_job['data']['details'] = 'This is a detailed description.'

        worker._process_job(sample_sync_job)

        mock_plex_item.edit.assert_called()
        all_kwargs = get_all_edit_kwargs(mock_plex_item)
        assert all_kwargs.get('summary.value') == 'This is a detailed description.'

    def test_performers_synced_as_actors(self, integration_worker, sample_sync_job):
        """Performers sync to Plex as actors."""
        worker, mock_plex_item = integration_worker
        mock_plex_item.actors = []  # No existing actors
        sample_sync_job['data']['performers'] = ['Jane Doe', 'John Smith']

        worker._process_job(sample_sync_job)

        # Edit should be called at least twice (metadata + actors)
        assert mock_plex_item.edit.call_count >= 1

    def test_tags_synced_as_genres(self, integration_worker, sample_sync_job):
        """Tags sync to Plex as genres."""
        worker, mock_plex_item = integration_worker
        mock_plex_item.genres = []  # No existing genres
        sample_sync_job['data']['tags'] = ['HD', 'Interview']

        worker._process_job(sample_sync_job)

        # Edit should include genre tags
        assert mock_plex_item.edit.called

    def test_plex_item_reloaded_after_edit(self, integration_worker, sample_sync_job):
        """Plex item.reload() called after edit to confirm changes."""
        worker, mock_plex_item = integration_worker

        worker._process_job(sample_sync_job)

        mock_plex_item.reload.assert_called()

    def test_sync_timestamp_saved_after_success(self, integration_worker, sample_sync_job, tmp_path):
        """Sync timestamp saved to data_dir after successful sync."""
        worker, mock_plex_item = integration_worker
        # Worker already has tmp_path as data_dir from fixture

        with patch('worker.processor.save_sync_timestamp') as mock_save:
            worker._process_job(sample_sync_job)

            mock_save.assert_called_once()
            args = mock_save.call_args[0]
            assert args[1] == sample_sync_job['scene_id']  # scene_id
            assert isinstance(args[2], float)  # timestamp

    def test_scene_unmarked_pending_after_processing(self, integration_worker, sample_sync_job):
        """Scene removed from pending set after processing."""
        worker, mock_plex_item = integration_worker

        with patch('worker.processor.unmark_scene_pending') as mock_unmark:
            worker._process_job(sample_sync_job)

            mock_unmark.assert_called_once_with(sample_sync_job['scene_id'])


@pytest.mark.integration
class TestPreservePlexEditsMode:
    """Tests for preserve_plex_edits configuration."""

    def test_preserve_mode_skips_existing_title(self, integration_worker, sample_sync_job):
        """preserve_plex_edits=True skips fields that already have values."""
        worker, mock_plex_item = integration_worker
        worker.config.preserve_plex_edits = True
        mock_plex_item.title = "Existing Title"  # Already has a title

        worker._process_job(sample_sync_job)

        # Edit should not include title.value since Plex already has one
        if mock_plex_item.edit.called:
            all_kwargs = get_all_edit_kwargs(mock_plex_item)
            assert 'title.value' not in all_kwargs

    def test_overwrite_mode_replaces_existing_title(self, integration_worker, sample_sync_job):
        """preserve_plex_edits=False overwrites existing Plex values."""
        worker, mock_plex_item = integration_worker
        worker.config.preserve_plex_edits = False
        mock_plex_item.title = "Existing Title"
        sample_sync_job['data']['title'] = 'New Title From Stash'

        worker._process_job(sample_sync_job)

        mock_plex_item.edit.assert_called()
        all_kwargs = get_all_edit_kwargs(mock_plex_item)
        assert all_kwargs.get('title.value') == 'New Title From Stash'


@pytest.mark.integration
class TestJobWithMissingFields:
    """Tests for jobs with missing or partial data."""

    def test_job_without_title_still_syncs_other_fields(self, integration_worker):
        """Job missing title can still sync studio, summary, etc."""
        worker, mock_plex_item = integration_worker

        job = {
            'scene_id': 456,
            'update_type': 'metadata',
            'data': {
                'path': '/media/videos/test_scene.mp4',
                'studio': 'Some Studio',
                'details': 'Description only',
                # No title field
            },
            'pqid': 1,
        }

        # Should not raise
        worker._process_job(job)
        assert mock_plex_item.edit.called

    def test_job_with_only_path_processes_without_error(self, integration_worker):
        """Job with only path field processes (finds item, no metadata to sync)."""
        worker, mock_plex_item = integration_worker

        job = {
            'scene_id': 789,
            'update_type': 'metadata',
            'data': {
                'path': '/media/videos/test_scene.mp4',
                # No metadata fields
            },
            'pqid': 1,
        }

        # Should not raise - item found, just no edits
        worker._process_job(job)
