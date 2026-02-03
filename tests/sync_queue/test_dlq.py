"""
Tests for sync_queue/dlq.py - DeadLetterQueue class.

Tests DLQ initialization, add, query, and cleanup operations.
"""

import sqlite3
import time
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def dlq(tmp_path):
    """Create DeadLetterQueue with isolated database."""
    from sync_queue.dlq import DeadLetterQueue

    return DeadLetterQueue(str(tmp_path))


@pytest.fixture
def sample_failed_job():
    """Sample job dict for DLQ testing."""
    return {
        "pqid": 42,
        "scene_id": 123,
        "update_type": "metadata",
        "data": {"title": "Test Title", "studio": "Test Studio"},
        "enqueued_at": 1700000000.0,
        "job_key": "scene_123",
    }


class TestDeadLetterQueue:
    """Tests for DeadLetterQueue class."""

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_creates_database_file(self, tmp_path):
        """DeadLetterQueue creates dlq.db in data_dir."""
        from sync_queue.dlq import DeadLetterQueue

        DeadLetterQueue(str(tmp_path))

        db_path = tmp_path / "dlq.db"
        assert db_path.exists()

    def test_creates_table_schema(self, tmp_path):
        """DeadLetterQueue creates dead_letters table with correct schema."""
        from sync_queue.dlq import DeadLetterQueue

        DeadLetterQueue(str(tmp_path))

        # Verify table exists with expected columns
        db_path = tmp_path / "dlq.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(dead_letters)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        expected_columns = {
            "id",
            "job_id",
            "scene_id",
            "job_data",
            "error_type",
            "error_message",
            "stack_trace",
            "retry_count",
            "failed_at",
        }
        assert expected_columns.issubset(columns)

    def test_creates_indexes(self, tmp_path):
        """DeadLetterQueue creates indexes for efficient querying."""
        from sync_queue.dlq import DeadLetterQueue

        DeadLetterQueue(str(tmp_path))

        db_path = tmp_path / "dlq.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='dead_letters'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "idx_failed_at" in indexes
        assert "idx_scene_id" in indexes

    # =========================================================================
    # add() Tests
    # =========================================================================

    def test_add_stores_job_and_error(self, dlq, sample_failed_job):
        """add() stores job and increments count."""
        error = ValueError("Test error message")

        dlq.add(sample_failed_job, error, retry_count=5)

        assert dlq.get_count() == 1

    def test_add_preserves_job_data(self, dlq, sample_failed_job):
        """add() preserves all job fields."""
        error = Exception("Test")

        dlq.add(sample_failed_job, error, retry_count=3)

        recent = dlq.get_recent(limit=1)
        full_job = dlq.get_by_id(recent[0]["id"])

        assert full_job["scene_id"] == 123
        assert full_job["pqid"] == 42
        assert full_job["data"]["title"] == "Test Title"

    def test_add_captures_error_type(self, dlq, sample_failed_job):
        """add() stores error type name."""
        error = ValueError("Value error message")

        dlq.add(sample_failed_job, error, retry_count=1)

        recent = dlq.get_recent(limit=1)
        assert recent[0]["error_type"] == "ValueError"

    def test_add_captures_error_message(self, dlq, sample_failed_job):
        """add() stores error message."""
        error = RuntimeError("Specific runtime error")

        dlq.add(sample_failed_job, error, retry_count=1)

        recent = dlq.get_recent(limit=1)
        assert recent[0]["error_message"] == "Specific runtime error"

    def test_add_captures_stack_trace(self, dlq, sample_failed_job):
        """add() stores non-empty stack trace."""
        try:
            raise TypeError("Intentional test error")
        except TypeError as e:
            dlq.add(sample_failed_job, e, retry_count=2)

        # Get full entry from database to check stack_trace
        db_path = dlq.db_path
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT stack_trace FROM dead_letters LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0]  # Non-empty string
        assert "TypeError" in row[0]

    def test_add_captures_retry_count(self, dlq, sample_failed_job):
        """add() stores retry count."""
        error = Exception("Test")

        dlq.add(sample_failed_job, error, retry_count=7)

        # Query retry_count directly
        db_path = dlq.db_path
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT retry_count FROM dead_letters LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        assert row[0] == 7

    def test_add_stores_job_id_from_pqid(self, dlq, sample_failed_job):
        """add() stores job_id from job's pqid field."""
        error = Exception("Test")

        dlq.add(sample_failed_job, error, retry_count=1)

        recent = dlq.get_recent(limit=1)
        assert recent[0]["job_id"] == 42

    def test_add_stores_scene_id(self, dlq, sample_failed_job):
        """add() stores scene_id correctly."""
        error = Exception("Test")

        dlq.add(sample_failed_job, error, retry_count=1)

        recent = dlq.get_recent(limit=1)
        assert recent[0]["scene_id"] == 123

    # =========================================================================
    # get_recent() Tests
    # =========================================================================

    def test_get_recent_returns_empty_initially(self, dlq):
        """get_recent() returns empty list when DLQ is empty."""
        result = dlq.get_recent(limit=10)

        assert result == []

    def test_get_recent_respects_limit(self, dlq):
        """get_recent() returns only requested number of entries."""
        error = Exception("Test")

        # Add 5 jobs
        for i in range(5):
            job = {"pqid": i, "scene_id": 100 + i, "data": {}}
            dlq.add(job, error, retry_count=1)

        result = dlq.get_recent(limit=2)

        assert len(result) == 2

    def test_get_recent_orders_by_failed_at_desc(self, dlq):
        """get_recent() returns newest entries first."""
        error = Exception("Test")

        # Add jobs with slight delays to ensure different timestamps
        for i in range(3):
            job = {"pqid": i, "scene_id": 200 + i, "data": {}}
            dlq.add(job, error, retry_count=1)

        result = dlq.get_recent(limit=3)

        # Most recent (scene_id 202) should be first
        assert result[0]["scene_id"] == 202
        assert result[1]["scene_id"] == 201
        assert result[2]["scene_id"] == 200

    def test_get_recent_returns_summary_fields(self, dlq, sample_failed_job):
        """get_recent() returns summary fields (no job_data blob)."""
        error = ValueError("Test error")

        dlq.add(sample_failed_job, error, retry_count=3)

        result = dlq.get_recent(limit=1)

        assert "id" in result[0]
        assert "job_id" in result[0]
        assert "scene_id" in result[0]
        assert "error_type" in result[0]
        assert "error_message" in result[0]
        assert "failed_at" in result[0]
        # job_data should NOT be in summary
        assert "job_data" not in result[0]

    # =========================================================================
    # get_by_id() Tests
    # =========================================================================

    def test_get_by_id_returns_none_for_missing(self, dlq):
        """get_by_id() returns None for nonexistent ID."""
        result = dlq.get_by_id(999)

        assert result is None

    def test_get_by_id_unpickles_job_data(self, dlq, sample_failed_job):
        """get_by_id() unpickles and returns full job structure."""
        error = Exception("Test")

        dlq.add(sample_failed_job, error, retry_count=2)

        recent = dlq.get_recent(limit=1)
        full_job = dlq.get_by_id(recent[0]["id"])

        # Should have original job structure
        assert full_job["pqid"] == 42
        assert full_job["scene_id"] == 123
        assert full_job["update_type"] == "metadata"
        assert full_job["data"]["title"] == "Test Title"
        assert full_job["data"]["studio"] == "Test Studio"

    def test_get_by_id_returns_correct_job(self, dlq):
        """get_by_id() returns correct job when multiple exist."""
        error = Exception("Test")

        # Add multiple jobs
        for i in range(3):
            job = {"pqid": i, "scene_id": 300 + i, "data": {"index": i}}
            dlq.add(job, error, retry_count=1)

        recent = dlq.get_recent(limit=3)

        # Get middle job by ID
        middle_id = recent[1]["id"]
        full_job = dlq.get_by_id(middle_id)

        assert full_job["scene_id"] == recent[1]["scene_id"]

    # =========================================================================
    # get_count() Tests
    # =========================================================================

    def test_get_count_returns_zero_initially(self, dlq):
        """get_count() returns 0 when DLQ is empty."""
        assert dlq.get_count() == 0

    def test_get_count_returns_accurate_count(self, dlq):
        """get_count() returns accurate count after adding jobs."""
        error = Exception("Test")

        for i in range(3):
            job = {"pqid": i, "scene_id": i, "data": {}}
            dlq.add(job, error, retry_count=1)

        assert dlq.get_count() == 3

    def test_get_count_increments_on_add(self, dlq, sample_failed_job):
        """get_count() increases with each add."""
        error = Exception("Test")

        assert dlq.get_count() == 0

        dlq.add(sample_failed_job, error, retry_count=1)
        assert dlq.get_count() == 1

        dlq.add(sample_failed_job, error, retry_count=1)
        assert dlq.get_count() == 2

    # =========================================================================
    # delete_older_than() Tests
    # =========================================================================

    def test_delete_older_than_removes_old_entries(self, dlq, sample_failed_job):
        """delete_older_than() removes entries older than specified days."""
        error = Exception("Test")

        # Add a job
        dlq.add(sample_failed_job, error, retry_count=1)

        # Manually update the failed_at timestamp to be old
        db_path = dlq.db_path
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE dead_letters SET failed_at = datetime('now', '-40 days')"
        )
        conn.commit()
        conn.close()

        assert dlq.get_count() == 1

        # Delete entries older than 30 days
        dlq.delete_older_than(days=30)

        assert dlq.get_count() == 0

    def test_delete_older_than_preserves_recent(self, dlq):
        """delete_older_than() preserves entries within retention period."""
        error = Exception("Test")

        # Add current job
        job = {"pqid": 1, "scene_id": 100, "data": {}}
        dlq.add(job, error, retry_count=1)

        assert dlq.get_count() == 1

        # Delete entries older than 30 days (should not affect current entry)
        dlq.delete_older_than(days=30)

        assert dlq.get_count() == 1

    def test_delete_older_than_mixed_ages(self, dlq):
        """delete_older_than() removes only old entries, keeps recent."""
        error = Exception("Test")

        # Add two jobs
        job1 = {"pqid": 1, "scene_id": 100, "data": {}}
        job2 = {"pqid": 2, "scene_id": 200, "data": {}}
        dlq.add(job1, error, retry_count=1)
        dlq.add(job2, error, retry_count=1)

        # Make first job old
        db_path = dlq.db_path
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE dead_letters SET failed_at = datetime('now', '-60 days') WHERE job_id = 1"
        )
        conn.commit()
        conn.close()

        assert dlq.get_count() == 2

        # Delete entries older than 30 days
        dlq.delete_older_than(days=30)

        # Only one should remain
        assert dlq.get_count() == 1

        # The remaining one should be scene_id 200
        recent = dlq.get_recent(limit=1)
        assert recent[0]["scene_id"] == 200

    def test_delete_older_than_default_days(self, dlq, sample_failed_job):
        """delete_older_than() uses 30 days by default."""
        error = Exception("Test")

        dlq.add(sample_failed_job, error, retry_count=1)

        # Make job 35 days old
        db_path = dlq.db_path
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE dead_letters SET failed_at = datetime('now', '-35 days')"
        )
        conn.commit()
        conn.close()

        # Call without days argument (default 30)
        dlq.delete_older_than()

        assert dlq.get_count() == 0


class TestDeadLetterQueueEdgeCases:
    """Edge case tests for DeadLetterQueue."""

    def test_add_job_without_pqid(self, dlq):
        """add() handles job without pqid field."""
        job = {"scene_id": 999, "data": {"title": "No pqid"}}
        error = Exception("Test")

        dlq.add(job, error, retry_count=1)

        assert dlq.get_count() == 1
        recent = dlq.get_recent(limit=1)
        assert recent[0]["job_id"] is None
        assert recent[0]["scene_id"] == 999

    def test_add_job_without_scene_id(self, dlq):
        """add() handles job without scene_id field."""
        job = {"pqid": 100, "data": {"title": "No scene_id"}}
        error = Exception("Test")

        dlq.add(job, error, retry_count=1)

        assert dlq.get_count() == 1
        recent = dlq.get_recent(limit=1)
        assert recent[0]["job_id"] == 100
        assert recent[0]["scene_id"] is None

    def test_add_with_unicode_error_message(self, dlq, sample_failed_job):
        """add() handles unicode in error message."""
        error = ValueError("Error with unicode: \u00e9\u00e0\u00fc\u4e2d\u6587")

        dlq.add(sample_failed_job, error, retry_count=1)

        recent = dlq.get_recent(limit=1)
        assert "\u00e9" in recent[0]["error_message"] or "unicode" in recent[0]["error_message"]

    def test_multiple_errors_same_scene(self, dlq):
        """DLQ stores multiple failures for same scene."""
        error1 = ValueError("First error")
        error2 = RuntimeError("Second error")

        job = {"pqid": 1, "scene_id": 500, "data": {}}
        dlq.add(job, error1, retry_count=1)

        job["pqid"] = 2
        dlq.add(job, error2, retry_count=2)

        assert dlq.get_count() == 2

        recent = dlq.get_recent(limit=2)
        assert all(r["scene_id"] == 500 for r in recent)
        error_types = {r["error_type"] for r in recent}
        assert error_types == {"ValueError", "RuntimeError"}


class TestDeadLetterQueueErrorSummary:
    """Tests for get_error_summary() method."""

    def test_get_error_summary_returns_empty_dict_for_empty_dlq(self, dlq):
        """get_error_summary() returns empty dict when DLQ is empty."""
        result = dlq.get_error_summary()

        assert result == {}

    def test_get_error_summary_returns_correct_counts_by_error_type(self, dlq):
        """get_error_summary() returns correct counts grouped by error type."""
        job1 = {"pqid": 1, "scene_id": 100, "data": {}}
        job2 = {"pqid": 2, "scene_id": 200, "data": {}}

        dlq.add(job1, ValueError("Error 1"), retry_count=1)
        dlq.add(job2, RuntimeError("Error 2"), retry_count=1)

        result = dlq.get_error_summary()

        assert result == {"ValueError": 1, "RuntimeError": 1}

    def test_get_error_summary_with_multiple_entries_same_type(self, dlq):
        """get_error_summary() correctly counts multiple entries of same error type."""
        for i in range(3):
            job = {"pqid": i, "scene_id": 100 + i, "data": {}}
            dlq.add(job, ValueError(f"Error {i}"), retry_count=1)

        result = dlq.get_error_summary()

        assert result == {"ValueError": 3}

    def test_get_error_summary_with_multiple_different_error_types(self, dlq):
        """get_error_summary() correctly aggregates multiple different error types."""
        # Add 3 PlexNotFound errors
        for i in range(3):
            job = {"pqid": i, "scene_id": 100 + i, "data": {}}

            class PlexNotFound(Exception):
                pass

            dlq.add(job, PlexNotFound(f"Not found {i}"), retry_count=1)

        # Add 2 PermanentError errors
        for i in range(2):
            job = {"pqid": 10 + i, "scene_id": 200 + i, "data": {}}

            class PermanentError(Exception):
                pass

            dlq.add(job, PermanentError(f"Permanent {i}"), retry_count=1)

        # Add 1 TransientError
        job = {"pqid": 20, "scene_id": 300, "data": {}}

        class TransientError(Exception):
            pass

        dlq.add(job, TransientError("Transient"), retry_count=1)

        result = dlq.get_error_summary()

        assert result == {"PlexNotFound": 3, "PermanentError": 2, "TransientError": 1}
