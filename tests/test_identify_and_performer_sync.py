"""
TDD tests for GitHub issue #10 — two independent defects.

Bug 1: Deferred Identify-hook jobs have no file path, so the worker rehydrates
them from Stash's GraphQL API. Every hydration failure was blanket-wrapped as
PermanentError, so a transient failure (expired session cookie, network
timeout, transient 5xx) sent the job straight to the DLQ on attempt zero
instead of retrying. `run_batch` also hid a non-empty DLQ behind a truthful
but misleading "Queue is empty" message.

Bug 2: The add-path performer/tag writes never sent the `actor.locked` /
`genre.locked` key that the clear paths already send, so Plex silently
dropped the write on its next refresh. Success was also logged/recorded
purely from the absence of an exception, with no verification that the
write actually took.
"""

import urllib.error
import socket

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def worker(mock_queue, mock_dlq, mock_config, tmp_path, mock_queue_manager):
    """SyncWorker with mocked dependencies, matching other worker test fixtures."""
    from worker.processor import SyncWorker

    mock_config.plex_connect_timeout = 10.0
    mock_config.plex_read_timeout = 30.0
    mock_config.preserve_plex_edits = False
    mock_config.strict_matching = False
    mock_config.dlq_retention_days = 30
    mock_config.skip_not_found = False

    return SyncWorker(
        queue_manager=mock_queue_manager,
        dlq=mock_dlq,
        config=mock_config,
        data_dir=str(tmp_path),
    )


def _http_error(code, msg="error"):
    return urllib.error.HTTPError(
        url="http://stash.example/graphql", code=code, msg=msg, hdrs=None, fp=None
    )


class TestHydrationErrorClassification:
    """Bug 1, slice 1: _hydrate_job_from_stash failures are classified honestly."""

    def test_http_401_raises_transient(self, worker):
        from worker.processor import TransientError

        with patch.object(worker, '_hydrate_job_from_stash', side_effect=_http_error(401)):
            with pytest.raises(TransientError):
                worker._process_job({'scene_id': 1, 'data': {}})

    def test_http_403_raises_transient(self, worker):
        from worker.processor import TransientError

        with patch.object(worker, '_hydrate_job_from_stash', side_effect=_http_error(403)):
            with pytest.raises(TransientError):
                worker._process_job({'scene_id': 1, 'data': {}})

    def test_http_5xx_raises_transient(self, worker):
        from worker.processor import TransientError

        with patch.object(worker, '_hydrate_job_from_stash', side_effect=_http_error(503)):
            with pytest.raises(TransientError):
                worker._process_job({'scene_id': 1, 'data': {}})

    def test_url_error_raises_transient(self, worker):
        from worker.processor import TransientError

        err = urllib.error.URLError("connection refused")
        with patch.object(worker, '_hydrate_job_from_stash', side_effect=err):
            with pytest.raises(TransientError):
                worker._process_job({'scene_id': 1, 'data': {}})

    def test_socket_timeout_raises_transient(self, worker):
        from worker.processor import TransientError

        with patch.object(worker, '_hydrate_job_from_stash', side_effect=socket.timeout("timed out")):
            with pytest.raises(TransientError):
                worker._process_job({'scene_id': 1, 'data': {}})

    def test_http_404_raises_permanent(self, worker):
        from worker.processor import PermanentError

        with patch.object(worker, '_hydrate_job_from_stash', side_effect=_http_error(404)):
            with pytest.raises(PermanentError):
                worker._process_job({'scene_id': 1, 'data': {}})

    def test_permanent_error_from_hydration_propagates_unchanged(self, worker):
        """PermanentError raised inside hydration (e.g. missing stash_url) is not
        re-wrapped, downgraded, or converted to TransientError."""
        from worker.processor import PermanentError

        original = PermanentError("Job 1 missing file path and stash_url is not configured")
        with patch.object(worker, '_hydrate_job_from_stash', side_effect=original):
            with pytest.raises(PermanentError) as exc_info:
                worker._process_job({'scene_id': 1, 'data': {}})

        assert exc_info.value is original


class TestHydrationRetryEndToEnd:
    """Bug 1, slice 1: the actual user-visible regression — a job whose
    hydration hits a transient failure must be retried, not dumped straight
    into the DLQ with retry_count=0."""

    def test_401_hydration_failure_is_retried_not_dlqd(self, worker):
        """This is the regression from #10/#12: a deferred Identify-hook job
        (no 'path' in data) whose hydration hits an expired-session 401 used
        to land in the DLQ on attempt zero. It must now retry instead."""
        job = {
            'job_id': 1,
            'scene_id': 42,
            'update_type': 'metadata',
            'data': {'identified': True, 'updated_at': 1000.0},  # no 'path' key
            'enqueued_at': 1000.0,
            'job_key': 'scene_42',
            'retry_count': 0,
        }

        with patch.object(worker, '_hydrate_job_from_stash', side_effect=_http_error(401)):
            with patch.object(worker, '_requeue_with_metadata') as mock_requeue:
                outcome = worker._handle_job(job, recently_synced=set(), sync_timestamps={})

        assert outcome == 'retrying'
        worker.dlq.add.assert_not_called()
        mock_requeue.assert_called_once()
        requeued_job = mock_requeue.call_args[0][0]
        # Retried with incremented retry metadata, not dumped at retry_count=0
        assert requeued_job.get('retry_count', 0) >= 1


class TestRunBatchEmptyQueueMessage:
    """Bug 1, slice 2: 'Queue is empty' must not hide a non-empty DLQ."""

    def test_empty_queue_with_dlq_entries_mentions_dlq(self, worker, capsys):
        worker.dlq.get_count.return_value = 7

        with patch('sync_queue.operations.get_stats', return_value={'pending': 0, 'in_progress': 0}):
            result = worker.run_batch()

        assert result == {'processed': 0, 'failed': 0, 'skipped': 0}
        captured = capsys.readouterr()
        assert "Queue is empty" in captured.err
        assert "7" in captured.err
        assert "dead letter queue" in captured.err

    def test_empty_queue_with_empty_dlq_message_unchanged(self, worker, capsys):
        worker.dlq.get_count.return_value = 0

        with patch('sync_queue.operations.get_stats', return_value={'pending': 0, 'in_progress': 0}):
            worker.run_batch()

        captured = capsys.readouterr()
        assert "Queue is empty — nothing to process" in captured.err
        assert "dead letter queue" not in captured.err


class TestPerformerAndTagLockedWrites:
    """Bug 2, slices 3 & 4: add-path writes lock the field and verify the write."""

    def _mock_plex_item(self):
        item = MagicMock()
        item.studio = ""
        item.title = ""
        item.summary = ""
        item.actors = []
        item.genres = []
        item.collections = []
        return item

    def test_sync_performers_add_path_locks_actor_field(self, worker):
        from validation.errors import PartialSyncResult

        plex_item = self._mock_plex_item()
        result = PartialSyncResult()
        pending = []

        worker._sync_performers(plex_item, {'performers': ['Actor 1']}, result, False, pending)

        edit_kwargs = plex_item.edit.call_args[1]
        assert edit_kwargs.get('actor.locked') == 1

    def test_sync_tags_add_path_locks_genre_field(self, worker):
        from validation.errors import PartialSyncResult

        plex_item = self._mock_plex_item()
        result = PartialSyncResult()
        pending = []

        worker._sync_tags(plex_item, {'tags': ['Tag 1']}, result, False, pending)

        edit_kwargs = plex_item.edit.call_args[1]
        assert edit_kwargs.get('genre.locked') == 1

    def test_sync_performers_clear_path_still_locks_and_succeeds(self, worker):
        from validation.errors import PartialSyncResult

        plex_item = self._mock_plex_item()
        result = PartialSyncResult()
        pending = []

        needs_reload = worker._sync_performers(plex_item, {'performers': []}, result, False, pending)

        edit_kwargs = plex_item.edit.call_args[1]
        assert edit_kwargs.get('actor.locked') == 1
        assert needs_reload is True
        assert 'performers' in result.fields_updated
        assert not result.has_warnings

    def test_sync_tags_clear_path_still_locks_and_succeeds(self, worker):
        from validation.errors import PartialSyncResult

        plex_item = self._mock_plex_item()
        result = PartialSyncResult()
        pending = []

        needs_reload = worker._sync_tags(plex_item, {'tags': []}, result, False, pending)

        edit_kwargs = plex_item.edit.call_args[1]
        assert edit_kwargs.get('genre.locked') == 1
        assert needs_reload is True
        assert 'tags' in result.fields_updated
        assert not result.has_warnings

    def test_verification_records_warning_when_write_did_not_take(self, worker):
        """End-to-end via _update_metadata: if the post-reload state doesn't
        show the new performer, a warning is recorded instead of a success —
        this is the actual user-visible bug (Plex silently drops the write)."""
        plex_item = self._mock_plex_item()

        # Plex accepts the edit but the reload shows the actor list unchanged —
        # simulating exactly the silent-drop behavior reported in #10.
        # (actors/genres remain [] after reload — no side effect needed since
        # the mock is static.)

        data = {'path': '/test.mp4', 'performers': ['Actor 1']}
        result = worker._update_metadata(plex_item, data)

        assert any(w.field_name == 'performers' for w in result.warnings)
        assert 'performers' not in result.fields_updated

    def test_verification_records_success_when_write_took(self, worker):
        """Contrast case: when reload confirms the write, success is recorded."""
        plex_item = self._mock_plex_item()

        def reload_side_effect():
            plex_item.actors = [MagicMock(tag='Actor 1')]
        plex_item.reload.side_effect = reload_side_effect

        data = {'path': '/test.mp4', 'performers': ['Actor 1']}
        result = worker._update_metadata(plex_item, data)

        assert 'performers' in result.fields_updated
        assert not any(w.field_name == 'performers' for w in result.warnings)
