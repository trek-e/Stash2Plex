"""
Tests for recovering dead-lettered jobs that failed on a hydration auth error.

Background (issue #10 follow-up): a 401 during _hydrate_job_from_stash used to
be blanket-wrapped as PermanentError and dead-lettered on the first attempt
(retry_count=0). That classification is fixed going forward, but entries
already written off before the fix stay stuck: the "Retry Not-Found Entries"
task only re-queues PlexNotFound, and outage recovery only covers
PlexServerDown. This extends the not-found recovery task to also re-queue
PermanentError entries whose recorded failure was an auth/network/timeout
condition during hydration -- matched narrowly on the failure signature so
genuinely permanent entries (bad data, 404, scene deleted) stay put.
"""

import pickle
import time
from unittest.mock import MagicMock, Mock, patch

import pytest


# =============================================================================
# is_recoverable_hydration_failure — narrow message-signature matcher
# =============================================================================


class TestIsRecoverableHydrationFailure:
    def _entry(self, error_type="PermanentError", error_message=""):
        return {"error_type": error_type, "error_message": error_message}

    # --- positive cases -----------------------------------------------

    def test_exact_legacy_401_message(self):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(
            error_message="Job 123 missing file path and hydration failed: "
            "HTTP Error 401: Unauthorized"
        )
        assert is_recoverable_hydration_failure(entry) is True

    @pytest.mark.parametrize("code,reason", [
        (403, "Forbidden"),
        (408, "Request Timeout"),
        (429, "Too Many Requests"),
        (500, "Internal Server Error"),
        (503, "Service Unavailable"),
        (599, "Network Connect Timeout Error"),
    ])
    def test_recoverable_http_status_codes(self, code, reason):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(
            error_message=f"Job 5 missing file path and hydration failed: "
            f"HTTP Error {code}: {reason}"
        )
        assert is_recoverable_hydration_failure(entry) is True

    @pytest.mark.parametrize("message", [
        "Job 6 missing file path and hydration failed: <urlopen error timed out>",
        "Job 7 missing file path and hydration failed: <urlopen error [Errno 8] "
        "nodename nor servname provided, or not known>",
        "Job 8 missing file path and hydration failed: <urlopen error [Errno 61] "
        "Connection refused>",
        "Job 9 missing file path and hydration failed: URLError: timed out",
        "Job 10 missing file path and hydration failed: Connection reset by peer",
    ])
    def test_recoverable_network_and_timeout_phrasing(self, message):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(error_message=message)
        assert is_recoverable_hydration_failure(entry) is True

    # --- negative cases (the important ones) ---------------------------

    def test_false_for_plain_missing_file_path_no_http_or_network_signature(self):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(error_message="Job 1 missing file path")
        assert is_recoverable_hydration_failure(entry) is False

    def test_false_for_404(self):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(
            error_message="Job 2 missing file path and hydration failed: "
            "HTTP Error 404: Not Found"
        )
        assert is_recoverable_hydration_failure(entry) is False

    def test_false_for_400_bad_request(self):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(
            error_message="Job 3 missing file path and hydration failed: "
            "HTTP Error 400: Bad Request"
        )
        assert is_recoverable_hydration_failure(entry) is False

    def test_false_for_scene_not_found_in_stash(self):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(
            error_message="Scene 4 not found in Stash during deferred hydration"
        )
        assert is_recoverable_hydration_failure(entry) is False

    def test_false_for_no_file_path_bad_data(self):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(
            error_message="Scene 4 has no file path during deferred hydration"
        )
        assert is_recoverable_hydration_failure(entry) is False

    def test_false_for_missing_stash_url(self):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(
            error_message="Job 11 missing file path and stash_url is not configured"
        )
        assert is_recoverable_hydration_failure(entry) is False

    def test_false_for_scene_id_that_looks_like_a_status_code(self):
        """A scene_id of 404 embedded in prose must not be mistaken for an
        HTTP status code — only an actual 'HTTP Error NNN' signature counts."""
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(error_message="Job 404 missing file path")
        assert is_recoverable_hydration_failure(entry) is False

    def test_false_when_error_type_is_not_permanent_error(self):
        """Even a message with a recoverable signature must not qualify if the
        DLQ entry's recorded error_type isn't PermanentError — this predicate
        is specifically about PermanentError entries."""
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = self._entry(
            error_type="PlexNotFound",
            error_message="Job 12 missing file path and hydration failed: "
            "HTTP Error 401: Unauthorized",
        )
        assert is_recoverable_hydration_failure(entry) is False

    def test_false_for_missing_error_message(self):
        from sync_queue.dlq_recovery import is_recoverable_hydration_failure

        entry = {"error_type": "PermanentError", "error_message": None}
        assert is_recoverable_hydration_failure(entry) is False


# =============================================================================
# Retry Not-Found Entries task — now also recovers qualifying PermanentError
# hydration failures, reporting the two categories separately.
# =============================================================================


@pytest.fixture
def dlq(tmp_path):
    from sync_queue.dlq import DeadLetterQueue
    return DeadLetterQueue(str(tmp_path))


def _insert_dlq_entry(dlq, scene_id, error_type, failed_at, error_message=""):
    job = {"job_id": scene_id, "scene_id": scene_id, "update_type": "metadata", "data": {}}
    with dlq._get_connection() as conn:
        conn.execute(
            "INSERT INTO dead_letters (scene_id, job_data, error_type, error_message, failed_at) "
            "VALUES (?, ?, ?, ?, datetime(?, 'unixepoch'))",
            (scene_id, pickle.dumps(job), error_type, error_message, failed_at),
        )
        conn.commit()


class TestHandleRetryNotFoundJobsRecoversHydrationFailures:
    @patch('Stash2Plex.get_plugin_data_dir')
    def test_requeues_both_not_found_and_qualifying_permanent_errors(
        self, mock_get_data_dir, dlq, tmp_path
    ):
        import Stash2Plex

        mock_get_data_dir.return_value = str(tmp_path)

        now = time.time()
        _insert_dlq_entry(dlq, 100, "PlexNotFound", now, "not found")
        _insert_dlq_entry(
            dlq, 200, "PermanentError", now,
            "Job 200 missing file path and hydration failed: HTTP Error 401: Unauthorized",
        )
        # Non-qualifying PermanentError — must stay in the DLQ.
        _insert_dlq_entry(
            dlq, 300, "PermanentError", now,
            "Job 300 missing file path and hydration failed: HTTP Error 404: Not Found",
        )
        _insert_dlq_entry(
            dlq, 400, "PermanentError", now, "Job 400 missing file path",
        )

        mock_queue_manager = MagicMock()
        mock_queue = Mock()
        mock_queue.path = str(tmp_path / "queue")
        mock_queue_manager.get_queue.return_value = mock_queue

        mock_config = Mock()
        mock_config.plex_url = "http://localhost:32400"
        mock_config.plex_token = "token"

        mock_stash = Mock()
        mock_stash.find_scene.return_value = {"id": 1}

        with patch.object(Stash2Plex, 'queue_manager', mock_queue_manager), \
             patch.object(Stash2Plex, 'config', mock_config), \
             patch.object(Stash2Plex, 'stash_interface', mock_stash), \
             patch('sync_queue.dlq_recovery.check_plex_health', return_value=(True, 5.0)), \
             patch('sync_queue.dlq_recovery.get_queued_scene_ids', return_value=set()), \
             patch('sync_queue.dlq_recovery.enqueue') as mock_enqueue, \
             patch('plex.client.PlexClient'):
            Stash2Plex.handle_retry_not_found_jobs()

        # Only scene 100 (PlexNotFound) and scene 200 (qualifying auth
        # failure) were re-enqueued — scenes 300 (404) and 400 (bad data)
        # were left in the DLQ.
        recovered_scene_ids = {call.args[1] for call in mock_enqueue.call_args_list}
        assert recovered_scene_ids == {100, 200}

        # Non-qualifying entries remain in the DLQ untouched.
        remaining = {e["scene_id"] for e in dlq.get_recent(limit=10)}
        assert 300 in remaining
        assert 400 in remaining

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_summary_reports_both_categories_separately(
        self, mock_get_data_dir, dlq, tmp_path
    ):
        import Stash2Plex

        mock_get_data_dir.return_value = str(tmp_path)

        now = time.time()
        _insert_dlq_entry(dlq, 100, "PlexNotFound", now, "not found")
        _insert_dlq_entry(
            dlq, 200, "PermanentError", now,
            "Job 200 missing file path and hydration failed: HTTP Error 503: Service Unavailable",
        )

        mock_queue_manager = MagicMock()
        mock_queue = Mock()
        mock_queue.path = str(tmp_path / "queue")
        mock_queue_manager.get_queue.return_value = mock_queue

        mock_config = Mock()
        mock_config.plex_url = "http://localhost:32400"
        mock_config.plex_token = "token"

        mock_stash = Mock()
        mock_stash.find_scene.return_value = {"id": 1}

        with patch.object(Stash2Plex, 'queue_manager', mock_queue_manager), \
             patch.object(Stash2Plex, 'config', mock_config), \
             patch.object(Stash2Plex, 'stash_interface', mock_stash), \
             patch('sync_queue.dlq_recovery.check_plex_health', return_value=(True, 5.0)), \
             patch('sync_queue.dlq_recovery.get_queued_scene_ids', return_value=set()), \
             patch('sync_queue.dlq_recovery.enqueue'), \
             patch('plex.client.PlexClient'), \
             patch('Stash2Plex.log_info') as mock_log_info:
            Stash2Plex.handle_retry_not_found_jobs()

        log_calls = [c.args[0] for c in mock_log_info.call_args_list]
        summary_lines = [msg for msg in log_calls if "recovered" in msg.lower()]
        assert summary_lines, f"No summary line found in logs: {log_calls}"
        summary = summary_lines[-1]

        # Two categories reported separately in the summary.
        assert "not-found" in summary.lower() or "not found" in summary.lower()
        assert "hydration" in summary.lower() or "auth" in summary.lower()
        assert "1" in summary  # one of each category recovered


class TestYmlDescriptionMentionsAuthHydrationRetry:
    def test_task_description_mentions_hydration_or_auth_failures(self):
        import os

        yml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Stash2Plex.yml')
        with open(yml_path) as f:
            content = f.read()

        section = content.split('Retry Not-Found Entries')[1].split('- name:')[0]
        assert 'hydration' in section.lower() or 'auth' in section.lower()
