"""
Tests for sync_queue/operations.py - Queue operations.

Tests enqueue, dequeue, ack, nack, fail, stats, and timestamp operations.
Also tests create_sync_job from models.py for explicit coverage.
"""

import json
import os
import sqlite3
import time

import pytest
from unittest.mock import MagicMock, patch


# =============================================================================
# enqueue() Tests
# =============================================================================


class TestEnqueue:
    """Tests for enqueue() function."""

    def test_enqueue_creates_job_with_required_fields(self, mock_queue):
        """enqueue creates job with scene_id, update_type, data, enqueued_at, job_key."""
        from sync_queue.operations import enqueue

        job = enqueue(mock_queue, scene_id=123, update_type="metadata", data={"title": "Test"})

        assert job["scene_id"] == 123
        assert job["update_type"] == "metadata"
        assert job["data"] == {"title": "Test"}
        assert "enqueued_at" in job
        assert isinstance(job["enqueued_at"], float)
        assert job["job_key"] == "scene_123"

    def test_enqueue_adds_job_to_queue(self, mock_queue):
        """enqueue calls queue.put() with the job."""
        from sync_queue.operations import enqueue

        enqueue(mock_queue, scene_id=456, update_type="image", data={"path": "/test.jpg"})

        mock_queue.put.assert_called_once()
        call_args = mock_queue.put.call_args[0][0]
        assert call_args["scene_id"] == 456

    def test_enqueue_returns_job_dict(self, mock_queue):
        """enqueue returns the job dict that was enqueued."""
        from sync_queue.operations import enqueue

        job = enqueue(mock_queue, scene_id=789, update_type="metadata", data={})

        assert isinstance(job, dict)
        assert job["scene_id"] == 789


# =============================================================================
# get_pending() Tests
# =============================================================================


class TestGetPending:
    """Tests for get_pending() function."""

    def test_get_pending_returns_job(self, mock_queue):
        """get_pending returns job from queue.get()."""
        from sync_queue.operations import get_pending

        expected_job = {"scene_id": 100, "pqid": 1}
        mock_queue.get.return_value = expected_job

        result = get_pending(mock_queue)

        assert result == expected_job
        mock_queue.get.assert_called_once_with(timeout=0)

    def test_get_pending_returns_none_when_queue_empty(self, mock_queue):
        """get_pending returns None when queue.get() returns None."""
        from sync_queue.operations import get_pending

        mock_queue.get.return_value = None

        result = get_pending(mock_queue, timeout=0.1)

        assert result is None

    def test_get_pending_returns_none_on_empty_exception(self, mock_queue):
        """get_pending returns None when queue raises Empty (queue exhausted)."""
        from sync_queue.operations import Empty, get_pending

        mock_queue.get.side_effect = Empty()

        result = get_pending(mock_queue, timeout=10)

        assert result is None

    def test_get_pending_uses_provided_timeout(self, mock_queue):
        """get_pending passes timeout to queue.get()."""
        from sync_queue.operations import get_pending

        mock_queue.get.return_value = None

        get_pending(mock_queue, timeout=5.0)

        mock_queue.get.assert_called_once_with(timeout=5.0)


# =============================================================================
# ack_job() Tests
# =============================================================================


class TestAckJob:
    """Tests for ack_job() function."""

    def test_ack_job_calls_queue_ack(self, mock_queue):
        """ack_job calls queue.ack() with the job."""
        from sync_queue.operations import ack_job

        job = {"pqid": 42, "scene_id": 123}
        ack_job(mock_queue, job)

        mock_queue.ack.assert_called_once_with(job)

    def test_ack_job_logs_completion(self, mock_queue, capsys):
        """ack_job logs job completion."""
        from sync_queue.operations import ack_job

        job = {"pqid": 99, "scene_id": 123}
        ack_job(mock_queue, job)

        captured = capsys.readouterr()
        assert "99" in captured.out
        assert "completed" in captured.out.lower()


# =============================================================================
# nack_job() Tests
# =============================================================================


class TestNackJob:
    """Tests for nack_job() function."""

    def test_nack_job_calls_queue_nack(self, mock_queue):
        """nack_job calls queue.nack() with the job."""
        from sync_queue.operations import nack_job

        job = {"pqid": 55, "scene_id": 456}
        nack_job(mock_queue, job)

        mock_queue.nack.assert_called_once_with(job)

    def test_nack_job_logs_retry(self, mock_queue, capsys):
        """nack_job logs that job was returned for retry."""
        from sync_queue.operations import nack_job

        job = {"pqid": 77, "scene_id": 456}
        nack_job(mock_queue, job)

        captured = capsys.readouterr()
        assert "77" in captured.out
        assert "retry" in captured.out.lower()


# =============================================================================
# fail_job() Tests
# =============================================================================


class TestFailJob:
    """Tests for fail_job() function."""

    def test_fail_job_calls_ack_failed(self, mock_queue):
        """fail_job calls queue.ack_failed() with the job."""
        from sync_queue.operations import fail_job

        job = {"pqid": 88, "scene_id": 789}
        fail_job(mock_queue, job)

        mock_queue.ack_failed.assert_called_once_with(job)

    def test_fail_job_logs_failure(self, mock_queue, capsys):
        """fail_job logs that job was marked as failed."""
        from sync_queue.operations import fail_job

        job = {"pqid": 66, "scene_id": 789}
        fail_job(mock_queue, job)

        captured = capsys.readouterr()
        assert "66" in captured.out
        assert "failed" in captured.out.lower()


# =============================================================================
# get_stats() Tests
# =============================================================================


class TestGetStats:
    """Tests for get_stats() function."""

    def test_get_stats_returns_zeros_no_db(self, tmp_path):
        """get_stats returns all zeros when database doesn't exist."""
        from sync_queue.operations import get_stats

        queue_path = tmp_path / "nonexistent_queue"

        stats = get_stats(str(queue_path))

        assert stats == {
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
        }

    def test_get_stats_returns_zeros_no_table(self, tmp_path):
        """get_stats returns all zeros when table doesn't exist."""
        from sync_queue.operations import get_stats

        queue_path = tmp_path / "queue"
        queue_path.mkdir()

        # Create empty database
        db_path = queue_path / "data.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        stats = get_stats(str(queue_path))

        assert stats == {
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
        }

    def test_get_stats_counts_by_status(self, tmp_path):
        """get_stats counts jobs by status correctly."""
        from sync_queue.operations import get_stats

        queue_path = tmp_path / "queue"
        queue_path.mkdir()

        # Create database with test data
        db_path = queue_path / "data.db"
        conn = sqlite3.connect(str(db_path))

        # Create table matching persist-queue schema
        conn.execute("""
            CREATE TABLE ack_queue_default (
                _id INTEGER PRIMARY KEY,
                data BLOB,
                status INTEGER
            )
        """)

        # Insert test data with various statuses
        # 0, 1 = pending; 2 = in_progress; 5 = completed; 9 = failed
        test_data = [
            (1, b"job1", 0),  # inited -> pending
            (2, b"job2", 1),  # ready -> pending
            (3, b"job3", 1),  # ready -> pending
            (4, b"job4", 2),  # unack -> in_progress
            (5, b"job5", 5),  # acked -> completed
            (6, b"job6", 5),  # acked -> completed
            (7, b"job7", 9),  # ack_failed -> failed
        ]
        conn.executemany(
            "INSERT INTO ack_queue_default (_id, data, status) VALUES (?, ?, ?)",
            test_data,
        )
        conn.commit()
        conn.close()

        stats = get_stats(str(queue_path))

        assert stats["pending"] == 3
        assert stats["in_progress"] == 1
        assert stats["completed"] == 2
        assert stats["failed"] == 1


# =============================================================================
# load_sync_timestamps() Tests
# =============================================================================


class TestLoadSyncTimestamps:
    """Tests for load_sync_timestamps() function."""

    def test_load_sync_timestamps_empty_file_missing(self, tmp_path):
        """load_sync_timestamps returns empty dict when file doesn't exist."""
        from sync_queue.operations import load_sync_timestamps

        result = load_sync_timestamps(str(tmp_path))

        assert result == {}

    def test_load_sync_timestamps_loads_existing(self, tmp_path):
        """load_sync_timestamps loads existing timestamps."""
        from sync_queue.operations import load_sync_timestamps

        # Create timestamps file
        timestamps = {"123": 1700000000.0, "456": 1700001000.0}
        ts_path = tmp_path / "sync_timestamps.json"
        with open(ts_path, "w") as f:
            json.dump(timestamps, f)

        result = load_sync_timestamps(str(tmp_path))

        # Keys should be converted to int
        assert result == {123: 1700000000.0, 456: 1700001000.0}

    def test_load_sync_timestamps_returns_empty_on_json_error(self, tmp_path):
        """load_sync_timestamps returns empty dict on JSON decode error."""
        from sync_queue.operations import load_sync_timestamps

        # Create invalid JSON file
        ts_path = tmp_path / "sync_timestamps.json"
        with open(ts_path, "w") as f:
            f.write("not valid json {{{")

        result = load_sync_timestamps(str(tmp_path))

        assert result == {}

    def test_load_sync_timestamps_converts_string_keys_to_int(self, tmp_path):
        """load_sync_timestamps converts string scene IDs to integers."""
        from sync_queue.operations import load_sync_timestamps

        timestamps = {"100": 1700000000.0, "200": 1700002000.0}
        ts_path = tmp_path / "sync_timestamps.json"
        with open(ts_path, "w") as f:
            json.dump(timestamps, f)

        result = load_sync_timestamps(str(tmp_path))

        assert all(isinstance(k, int) for k in result.keys())
        assert 100 in result
        assert 200 in result


# =============================================================================
# save_sync_timestamp() Tests
# =============================================================================


class TestSaveSyncTimestamp:
    """Tests for save_sync_timestamp() function."""

    def test_save_sync_timestamp_creates_file(self, tmp_path):
        """save_sync_timestamp creates JSON file when it doesn't exist."""
        from sync_queue.operations import save_sync_timestamp

        save_sync_timestamp(str(tmp_path), scene_id=123, timestamp=1700000000.0)

        ts_path = tmp_path / "sync_timestamps.json"
        assert ts_path.exists()

        with open(ts_path) as f:
            data = json.load(f)
        assert "123" in data  # JSON stores keys as strings
        assert data["123"] == 1700000000.0

    def test_save_sync_timestamp_updates_existing(self, tmp_path):
        """save_sync_timestamp preserves existing timestamps and adds new."""
        from sync_queue.operations import save_sync_timestamp

        # Create initial timestamps
        initial = {"100": 1700000000.0}
        ts_path = tmp_path / "sync_timestamps.json"
        with open(ts_path, "w") as f:
            json.dump(initial, f)

        # Save new timestamp
        save_sync_timestamp(str(tmp_path), scene_id=200, timestamp=1700001000.0)

        # Both should be present
        with open(ts_path) as f:
            data = json.load(f)
        assert "100" in data
        assert data["100"] == 1700000000.0
        assert "200" in data
        assert data["200"] == 1700001000.0

    def test_save_sync_timestamp_overwrites_existing_scene(self, tmp_path):
        """save_sync_timestamp overwrites timestamp for same scene."""
        from sync_queue.operations import save_sync_timestamp

        save_sync_timestamp(str(tmp_path), scene_id=123, timestamp=1700000000.0)
        save_sync_timestamp(str(tmp_path), scene_id=123, timestamp=1700999999.0)

        ts_path = tmp_path / "sync_timestamps.json"
        with open(ts_path) as f:
            data = json.load(f)

        # Should have new value
        assert data["123"] == 1700999999.0

    def test_save_sync_timestamp_atomic_write(self, tmp_path):
        """save_sync_timestamp uses atomic write (temp file + rename)."""
        from sync_queue.operations import save_sync_timestamp

        save_sync_timestamp(str(tmp_path), scene_id=123, timestamp=1700000000.0)

        # temp file should not remain
        temp_path = tmp_path / "sync_timestamps.json.tmp"
        assert not temp_path.exists()

        # actual file should exist
        ts_path = tmp_path / "sync_timestamps.json"
        assert ts_path.exists()


# =============================================================================
# create_sync_job() Tests (from models.py)
# =============================================================================


class TestCreateSyncJob:
    """Tests for create_sync_job() function from models.py."""

    def test_create_sync_job_returns_dict(self):
        """create_sync_job returns a dict (SyncJob TypedDict)."""
        from sync_queue.models import create_sync_job

        job = create_sync_job(scene_id=123, update_type="metadata", data={"title": "Test"})

        assert isinstance(job, dict)

    def test_create_sync_job_sets_scene_id(self):
        """create_sync_job sets scene_id field correctly."""
        from sync_queue.models import create_sync_job

        job = create_sync_job(scene_id=456, update_type="metadata", data={})

        assert job["scene_id"] == 456

    def test_create_sync_job_sets_update_type(self):
        """create_sync_job sets update_type field correctly."""
        from sync_queue.models import create_sync_job

        job = create_sync_job(scene_id=1, update_type="image", data={})

        assert job["update_type"] == "image"

    def test_create_sync_job_sets_data(self):
        """create_sync_job sets data field correctly."""
        from sync_queue.models import create_sync_job

        test_data = {"title": "Test", "studio": "Studio", "performers": ["A", "B"]}
        job = create_sync_job(scene_id=1, update_type="metadata", data=test_data)

        assert job["data"] == test_data

    def test_create_sync_job_sets_enqueued_at(self):
        """create_sync_job sets enqueued_at as current timestamp."""
        from sync_queue.models import create_sync_job

        before = time.time()
        job = create_sync_job(scene_id=1, update_type="metadata", data={})
        after = time.time()

        assert isinstance(job["enqueued_at"], float)
        assert before <= job["enqueued_at"] <= after

    def test_create_sync_job_sets_job_key(self):
        """create_sync_job sets job_key as 'scene_{scene_id}'."""
        from sync_queue.models import create_sync_job

        job = create_sync_job(scene_id=789, update_type="metadata", data={})

        assert job["job_key"] == "scene_789"

    def test_create_sync_job_returns_syncjob_structure(self):
        """create_sync_job returns dict with all SyncJob keys."""
        from sync_queue.models import create_sync_job

        job = create_sync_job(scene_id=1, update_type="metadata", data={"test": True})

        required_keys = {"scene_id", "update_type", "data", "enqueued_at", "job_key"}
        assert set(job.keys()) == required_keys
