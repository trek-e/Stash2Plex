"""
Tests for sync_queue/dlq_recovery.py - DLQ recovery operations.

Tests error classification, time-windowed queries, and idempotent recovery with
three-gate validation (Plex health, deduplication, scene existence).
"""

import pickle
import sqlite3
import time
from unittest.mock import Mock, MagicMock, patch

import pytest


@pytest.fixture
def dlq(tmp_path):
    """Create DeadLetterQueue with test database."""
    from sync_queue.dlq import DeadLetterQueue
    return DeadLetterQueue(str(tmp_path))


@pytest.fixture
def queue(tmp_path):
    """Create mock SQLiteAckQueue."""
    queue_path = tmp_path / "queue"
    queue_path.mkdir()

    mock_queue = Mock()
    mock_queue.path = str(queue_path)
    return mock_queue


@pytest.fixture
def mock_stash():
    """Create mock StashInterface."""
    stash = Mock()
    stash.find_scene = Mock(return_value={"id": 123})
    return stash


@pytest.fixture
def mock_plex_client():
    """Create mock PlexClient."""
    return Mock()


class TestErrorClassification:
    """Tests for error type classification constants and functions."""

    def test_safe_retry_error_types_defined(self):
        """SAFE_RETRY_ERROR_TYPES contains PlexServerDown only."""
        from sync_queue.dlq_recovery import SAFE_RETRY_ERROR_TYPES

        assert SAFE_RETRY_ERROR_TYPES == ["PlexServerDown"]

    def test_optional_retry_error_types_defined(self):
        """OPTIONAL_RETRY_ERROR_TYPES contains PlexTemporaryError and PlexNotFound."""
        from sync_queue.dlq_recovery import OPTIONAL_RETRY_ERROR_TYPES

        assert set(OPTIONAL_RETRY_ERROR_TYPES) == {"PlexTemporaryError", "PlexNotFound"}

    def test_permanent_error_types_defined(self):
        """PERMANENT_ERROR_TYPES contains auth and permission errors."""
        from sync_queue.dlq_recovery import PERMANENT_ERROR_TYPES

        expected = {"PlexPermanentError", "PlexAuthError", "PlexPermissionError"}
        assert set(PERMANENT_ERROR_TYPES) == expected

    def test_get_error_types_conservative_default(self):
        """get_error_types_for_recovery() with include_optional=False returns safe types only."""
        from sync_queue.dlq_recovery import get_error_types_for_recovery

        result = get_error_types_for_recovery(include_optional=False)
        assert result == ["PlexServerDown"]

    def test_get_error_types_include_optional(self):
        """get_error_types_for_recovery() with include_optional=True returns safe + optional."""
        from sync_queue.dlq_recovery import get_error_types_for_recovery

        result = get_error_types_for_recovery(include_optional=True)
        assert set(result) == {"PlexServerDown", "PlexTemporaryError", "PlexNotFound"}

    def test_permanent_errors_not_in_recovery_list(self):
        """Permanent errors never appear in recovery type list."""
        from sync_queue.dlq_recovery import get_error_types_for_recovery

        # Conservative mode
        conservative = get_error_types_for_recovery(include_optional=False)
        assert "PlexAuthError" not in conservative
        assert "PlexPermanentError" not in conservative

        # Include optional mode
        all_types = get_error_types_for_recovery(include_optional=True)
        assert "PlexAuthError" not in all_types
        assert "PlexPermanentError" not in all_types


class TestGetOutageDLQEntries:
    """Tests for get_outage_dlq_entries() time-windowed query function."""

    def test_empty_dlq_returns_empty_list(self, dlq):
        """get_outage_dlq_entries() returns [] when DLQ is empty."""
        from sync_queue.dlq_recovery import get_outage_dlq_entries

        start_time = time.time() - 3600
        end_time = time.time()
        error_types = ["PlexServerDown"]

        result = get_outage_dlq_entries(dlq, start_time, end_time, error_types)
        assert result == []

    def test_entries_outside_time_window_excluded(self, dlq):
        """get_outage_dlq_entries() excludes entries outside [start_time, end_time]."""
        from sync_queue.dlq_recovery import get_outage_dlq_entries

        # Add entry with older timestamp
        now = time.time()
        old_time = now - 7200  # 2 hours ago
        window_start = now - 3600  # 1 hour ago
        window_end = now

        # Manually insert entry with timestamp outside window
        job = {"pqid": 1, "scene_id": 100, "data": {}}
        with dlq._get_connection() as conn:
            conn.execute(
                "INSERT INTO dead_letters (scene_id, job_data, error_type, failed_at) "
                "VALUES (?, ?, ?, datetime(?, 'unixepoch'))",
                (100, pickle.dumps(job), "PlexServerDown", old_time)
            )
            conn.commit()

        result = get_outage_dlq_entries(dlq, window_start, window_end, ["PlexServerDown"])
        assert result == []

    def test_entries_with_wrong_error_type_excluded(self, dlq):
        """get_outage_dlq_entries() excludes entries not matching error_types filter."""
        from sync_queue.dlq_recovery import get_outage_dlq_entries

        now = time.time()
        start_time = now - 3600
        end_time = now

        # Add entry with different error type
        job = {"pqid": 1, "scene_id": 100, "data": {}}
        with dlq._get_connection() as conn:
            conn.execute(
                "INSERT INTO dead_letters (scene_id, job_data, error_type, failed_at) "
                "VALUES (?, ?, ?, datetime(?, 'unixepoch'))",
                (100, pickle.dumps(job), "PlexPermanentError", now - 1800)
            )
            conn.commit()

        # Query for PlexServerDown only
        result = get_outage_dlq_entries(dlq, start_time, end_time, ["PlexServerDown"])
        assert result == []

    def test_matching_entries_returned(self, dlq):
        """get_outage_dlq_entries() returns matching entries within time window."""
        from sync_queue.dlq_recovery import get_outage_dlq_entries

        now = time.time()
        start_time = now - 3600
        end_time = now

        # Add matching entry
        job = {"pqid": 1, "scene_id": 100, "data": {"title": "Test"}}
        with dlq._get_connection() as conn:
            conn.execute(
                "INSERT INTO dead_letters (scene_id, job_data, error_type, error_message, failed_at) "
                "VALUES (?, ?, ?, ?, datetime(?, 'unixepoch'))",
                (100, pickle.dumps(job), "PlexServerDown", "Server down", now - 1800)
            )
            conn.commit()

        result = get_outage_dlq_entries(dlq, start_time, end_time, ["PlexServerDown"])

        assert len(result) == 1
        assert result[0]["scene_id"] == 100
        assert result[0]["error_type"] == "PlexServerDown"
        assert result[0]["error_message"] == "Server down"
        assert "job_data" in result[0]

    def test_entries_ordered_by_failed_at_asc(self, dlq):
        """get_outage_dlq_entries() returns entries ordered by failed_at ASC (oldest first)."""
        from sync_queue.dlq_recovery import get_outage_dlq_entries

        now = time.time()
        start_time = now - 3600
        end_time = now

        # Add entries in reverse order
        times = [now - 3000, now - 2000, now - 1000]
        for i, t in enumerate(times):
            job = {"pqid": i, "scene_id": 100 + i, "data": {}}
            with dlq._get_connection() as conn:
                conn.execute(
                    "INSERT INTO dead_letters (scene_id, job_data, error_type, failed_at) "
                    "VALUES (?, ?, ?, datetime(?, 'unixepoch'))",
                    (100 + i, pickle.dumps(job), "PlexServerDown", t)
                )
                conn.commit()

        result = get_outage_dlq_entries(dlq, start_time, end_time, ["PlexServerDown"])

        assert len(result) == 3
        # Should be ordered oldest to newest
        assert result[0]["scene_id"] == 100  # oldest
        assert result[1]["scene_id"] == 101
        assert result[2]["scene_id"] == 102  # newest

    def test_multiple_error_types_in_filter(self, dlq):
        """get_outage_dlq_entries() returns all entries matching any error type in list."""
        from sync_queue.dlq_recovery import get_outage_dlq_entries

        now = time.time()
        start_time = now - 3600
        end_time = now

        # Add entries with different error types
        error_types_to_add = ["PlexServerDown", "PlexTemporaryError", "PlexPermanentError"]
        for i, error_type in enumerate(error_types_to_add):
            job = {"pqid": i, "scene_id": 100 + i, "data": {}}
            with dlq._get_connection() as conn:
                conn.execute(
                    "INSERT INTO dead_letters (scene_id, job_data, error_type, failed_at) "
                    "VALUES (?, ?, ?, datetime(?, 'unixepoch'))",
                    (100 + i, pickle.dumps(job), error_type, now - 1800)
                )
                conn.commit()

        # Query for PlexServerDown and PlexTemporaryError
        result = get_outage_dlq_entries(
            dlq, start_time, end_time, ["PlexServerDown", "PlexTemporaryError"]
        )

        assert len(result) == 2
        error_types_found = {entry["error_type"] for entry in result}
        assert error_types_found == {"PlexServerDown", "PlexTemporaryError"}

    def test_boundary_exact_start_time_included(self, dlq):
        """get_outage_dlq_entries() includes entry at exact start_time."""
        from sync_queue.dlq_recovery import get_outage_dlq_entries

        now = time.time()
        start_time = now - 3600
        end_time = now

        # Entry at exact start_time
        job = {"pqid": 1, "scene_id": 100, "data": {}}
        with dlq._get_connection() as conn:
            conn.execute(
                "INSERT INTO dead_letters (scene_id, job_data, error_type, failed_at) "
                "VALUES (?, ?, ?, datetime(?, 'unixepoch'))",
                (100, pickle.dumps(job), "PlexServerDown", start_time)
            )
            conn.commit()

        result = get_outage_dlq_entries(dlq, start_time, end_time, ["PlexServerDown"])
        assert len(result) == 1

    def test_boundary_exact_end_time_included(self, dlq):
        """get_outage_dlq_entries() includes entry at exact end_time."""
        from sync_queue.dlq_recovery import get_outage_dlq_entries

        now = time.time()
        start_time = now - 3600
        end_time = now

        # Entry at exact end_time
        job = {"pqid": 1, "scene_id": 100, "data": {}}
        with dlq._get_connection() as conn:
            conn.execute(
                "INSERT INTO dead_letters (scene_id, job_data, error_type, failed_at) "
                "VALUES (?, ?, ?, datetime(?, 'unixepoch'))",
                (100, pickle.dumps(job), "PlexServerDown", end_time)
            )
            conn.commit()

        result = get_outage_dlq_entries(dlq, start_time, end_time, ["PlexServerDown"])
        assert len(result) == 1


class TestRecoverOutageJobs:
    """Tests for recover_outage_jobs() with three-gate validation."""

    def test_recovery_result_dataclass_exists(self):
        """RecoveryResult dataclass is defined with expected fields."""
        from sync_queue.dlq_recovery import RecoveryResult

        result = RecoveryResult(
            total_dlq_entries=10,
            recovered=5,
            skipped_already_queued=2,
            skipped_plex_down=0,
            skipped_scene_missing=2,
            failed=1,
            recovered_scene_ids=[1, 2, 3, 4, 5]
        )

        assert result.total_dlq_entries == 10
        assert result.recovered == 5
        assert result.skipped_already_queued == 2
        assert result.skipped_plex_down == 0
        assert result.skipped_scene_missing == 2
        assert result.failed == 1
        assert result.recovered_scene_ids == [1, 2, 3, 4, 5]

    @patch("sync_queue.dlq_recovery.check_plex_health")
    @patch("sync_queue.dlq_recovery.get_queued_scene_ids")
    def test_plex_unhealthy_skips_all_entries(
        self, mock_get_queued, mock_health, queue, mock_stash, mock_plex_client, tmp_path
    ):
        """recover_outage_jobs() skips all entries when Plex is unhealthy."""
        from sync_queue.dlq_recovery import recover_outage_jobs

        # Gate 1: Plex unhealthy
        mock_health.return_value = (False, 0.0)

        # Create DLQ entries
        dlq_entries = [
            {"id": 1, "scene_id": 100, "job_data": pickle.dumps({"pqid": 1, "scene_id": 100, "data": {}})},
            {"id": 2, "scene_id": 101, "job_data": pickle.dumps({"pqid": 2, "scene_id": 101, "data": {}})},
        ]

        result = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )

        assert result.total_dlq_entries == 2
        assert result.skipped_plex_down == 2
        assert result.recovered == 0
        assert result.recovered_scene_ids == []

        # Should not check queue or stash when Plex is down
        mock_get_queued.assert_not_called()

    @patch("sync_queue.dlq_recovery.check_plex_health")
    @patch("sync_queue.dlq_recovery.get_queued_scene_ids")
    def test_all_entries_already_queued(
        self, mock_get_queued, mock_health, queue, mock_stash, mock_plex_client, tmp_path
    ):
        """recover_outage_jobs() skips entries already in queue."""
        from sync_queue.dlq_recovery import recover_outage_jobs

        # Gate 1: Plex healthy
        mock_health.return_value = (True, 10.0)

        # Gate 2: All scene_ids already queued
        mock_get_queued.return_value = {100, 101}

        dlq_entries = [
            {"id": 1, "scene_id": 100, "job_data": pickle.dumps({"pqid": 1, "scene_id": 100, "data": {}})},
            {"id": 2, "scene_id": 101, "job_data": pickle.dumps({"pqid": 2, "scene_id": 101, "data": {}})},
        ]

        result = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )

        assert result.total_dlq_entries == 2
        assert result.skipped_already_queued == 2
        assert result.recovered == 0

    @patch("sync_queue.dlq_recovery.check_plex_health")
    @patch("sync_queue.dlq_recovery.get_queued_scene_ids")
    def test_scene_missing_from_stash(
        self, mock_get_queued, mock_health, queue, mock_stash, mock_plex_client, tmp_path
    ):
        """recover_outage_jobs() skips entries for scenes deleted from Stash."""
        from sync_queue.dlq_recovery import recover_outage_jobs

        # Gate 1: Plex healthy
        mock_health.return_value = (True, 10.0)

        # Gate 2: Not queued
        mock_get_queued.return_value = set()

        # Gate 3: Scene missing from Stash
        mock_stash.find_scene.return_value = None

        dlq_entries = [
            {"id": 1, "scene_id": 100, "job_data": pickle.dumps({"pqid": 1, "scene_id": 100, "data": {}})},
        ]

        result = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )

        assert result.total_dlq_entries == 1
        assert result.skipped_scene_missing == 1
        assert result.recovered == 0

    @patch("sync_queue.dlq_recovery.check_plex_health")
    @patch("sync_queue.dlq_recovery.get_queued_scene_ids")
    @patch("sync_queue.dlq_recovery.enqueue")
    def test_successful_recovery(
        self, mock_enqueue, mock_get_queued, mock_health, queue, mock_stash, mock_plex_client, tmp_path
    ):
        """recover_outage_jobs() successfully recovers valid entry."""
        from sync_queue.dlq_recovery import recover_outage_jobs

        # All gates pass
        mock_health.return_value = (True, 10.0)
        mock_get_queued.return_value = set()
        mock_stash.find_scene.return_value = {"id": 100}

        dlq_entries = [
            {
                "id": 1,
                "scene_id": 100,
                "job_data": pickle.dumps({
                    "pqid": 1,
                    "scene_id": 100,
                    "update_type": "metadata",
                    "data": {"title": "Test"}
                })
            },
        ]

        result = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )

        assert result.total_dlq_entries == 1
        assert result.recovered == 1
        assert result.recovered_scene_ids == [100]

        # Verify enqueue was called
        mock_enqueue.assert_called_once()
        call_args = mock_enqueue.call_args
        assert call_args[0][1] == 100  # scene_id
        assert call_args[0][2] == "metadata"  # update_type

    @patch("sync_queue.dlq_recovery.check_plex_health")
    @patch("sync_queue.dlq_recovery.get_queued_scene_ids")
    @patch("sync_queue.dlq_recovery.enqueue")
    def test_duplicate_scene_id_in_batch(
        self, mock_enqueue, mock_get_queued, mock_health, queue, mock_stash, mock_plex_client, tmp_path
    ):
        """recover_outage_jobs() skips duplicate scene_id within same batch (in-memory dedup)."""
        from sync_queue.dlq_recovery import recover_outage_jobs

        mock_health.return_value = (True, 10.0)
        mock_get_queued.return_value = set()
        mock_stash.find_scene.return_value = {"id": 100}

        # Two entries with same scene_id
        dlq_entries = [
            {
                "id": 1,
                "scene_id": 100,
                "job_data": pickle.dumps({
                    "pqid": 1,
                    "scene_id": 100,
                    "update_type": "metadata",
                    "data": {"title": "Test 1"}
                })
            },
            {
                "id": 2,
                "scene_id": 100,
                "job_data": pickle.dumps({
                    "pqid": 2,
                    "scene_id": 100,
                    "update_type": "metadata",
                    "data": {"title": "Test 2"}
                })
            },
        ]

        result = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )

        # First entry recovered, second skipped as duplicate
        assert result.total_dlq_entries == 2
        assert result.recovered == 1
        assert result.skipped_already_queued == 1
        assert result.recovered_scene_ids == [100]

        # enqueue called only once
        assert mock_enqueue.call_count == 1

    @patch("sync_queue.dlq_recovery.check_plex_health")
    @patch("sync_queue.dlq_recovery.get_queued_scene_ids")
    @patch("sync_queue.dlq_recovery.enqueue")
    def test_mixed_results(
        self, mock_enqueue, mock_get_queued, mock_health, queue, mock_stash, mock_plex_client, tmp_path
    ):
        """recover_outage_jobs() correctly counts mixed success/skip results."""
        from sync_queue.dlq_recovery import recover_outage_jobs

        mock_health.return_value = (True, 10.0)
        mock_get_queued.return_value = {101}  # One already queued

        # Scene 100: exists (recover)
        # Scene 101: already queued (skip)
        # Scene 102: missing from Stash (skip)
        # Scene 103: exists (recover)
        mock_stash.find_scene.side_effect = lambda scene_id: (
            {"id": scene_id} if scene_id in {100, 103} else None
        )

        dlq_entries = [
            {"id": 1, "scene_id": 100, "job_data": pickle.dumps({"pqid": 1, "scene_id": 100, "update_type": "metadata", "data": {}})},
            {"id": 2, "scene_id": 101, "job_data": pickle.dumps({"pqid": 2, "scene_id": 101, "update_type": "metadata", "data": {}})},
            {"id": 3, "scene_id": 102, "job_data": pickle.dumps({"pqid": 3, "scene_id": 102, "update_type": "metadata", "data": {}})},
            {"id": 4, "scene_id": 103, "job_data": pickle.dumps({"pqid": 4, "scene_id": 103, "update_type": "metadata", "data": {}})},
        ]

        result = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )

        assert result.total_dlq_entries == 4
        assert result.recovered == 2
        assert result.skipped_already_queued == 1
        assert result.skipped_scene_missing == 1
        assert result.failed == 0
        assert set(result.recovered_scene_ids) == {100, 103}

    @patch("sync_queue.dlq_recovery.check_plex_health")
    @patch("sync_queue.dlq_recovery.get_queued_scene_ids")
    @patch("sync_queue.dlq_recovery.enqueue")
    def test_enqueue_failure_increments_failed(
        self, mock_enqueue, mock_get_queued, mock_health, queue, mock_stash, mock_plex_client, tmp_path
    ):
        """recover_outage_jobs() increments failed count when enqueue raises exception."""
        from sync_queue.dlq_recovery import recover_outage_jobs

        mock_health.return_value = (True, 10.0)
        mock_get_queued.return_value = set()
        mock_stash.find_scene.return_value = {"id": 100}

        # Simulate enqueue failure
        mock_enqueue.side_effect = Exception("Queue full")

        dlq_entries = [
            {"id": 1, "scene_id": 100, "job_data": pickle.dumps({"pqid": 1, "scene_id": 100, "update_type": "metadata", "data": {}})},
        ]

        result = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )

        assert result.total_dlq_entries == 1
        assert result.failed == 1
        assert result.recovered == 0

    @patch("sync_queue.dlq_recovery.check_plex_health")
    @patch("sync_queue.dlq_recovery.get_queued_scene_ids")
    @patch("sync_queue.dlq_recovery.enqueue")
    def test_idempotent_run_twice(
        self, mock_enqueue, mock_get_queued, mock_health, queue, mock_stash, mock_plex_client, tmp_path
    ):
        """recover_outage_jobs() is idempotent - second run with same entries skips all."""
        from sync_queue.dlq_recovery import recover_outage_jobs

        mock_health.return_value = (True, 10.0)
        mock_stash.find_scene.return_value = {"id": 100}

        dlq_entries = [
            {"id": 1, "scene_id": 100, "job_data": pickle.dumps({"pqid": 1, "scene_id": 100, "update_type": "metadata", "data": {}})},
        ]

        # First run: queue is empty
        mock_get_queued.return_value = set()
        result1 = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )
        assert result1.recovered == 1

        # Second run: scene_id now in queue
        mock_get_queued.return_value = {100}
        result2 = recover_outage_jobs(
            dlq_entries, queue, mock_stash, mock_plex_client, str(tmp_path)
        )
        assert result2.recovered == 0
        assert result2.skipped_already_queued == 1
