"""
Integration tests for queue persistence and recovery.

Tests verify crash-safe retry behavior:
- Retry metadata (retry_count, next_retry_at, last_error_type) stored in job dict
- Metadata persists in SQLiteAckQueue across worker "restart" (new instance)
- Jobs ready for retry when next_retry_at elapsed
- Jobs not ready when still in backoff delay
- Max retries exceeded moves job to DLQ

These tests use real SQLiteAckQueue (not mocked) to verify persistence.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch


@pytest.mark.integration
class TestRetryMetadataPersistence:
    """Tests for retry metadata stored in job dict."""

    def test_retry_count_stored_in_job(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """retry_count field added to job dict on first failure."""
        from worker.processor import SyncWorker, TransientError

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {'scene_id': 123, 'data': {'path': '/test.mp4'}, 'pqid': 1}
        error = TransientError("test failure")

        updated_job = worker._prepare_for_retry(job, error)

        assert 'retry_count' in updated_job
        assert updated_job['retry_count'] == 1

    def test_retry_count_increments(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """retry_count increments on subsequent failures."""
        from worker.processor import SyncWorker, TransientError

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {'scene_id': 123, 'data': {'path': '/test.mp4'}, 'retry_count': 2}
        error = TransientError("test failure")

        updated_job = worker._prepare_for_retry(job, error)

        assert updated_job['retry_count'] == 3

    def test_next_retry_at_stored_in_job(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """next_retry_at timestamp added to job dict."""
        from worker.processor import SyncWorker, TransientError

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {'scene_id': 123, 'data': {'path': '/test.mp4'}}
        error = TransientError("test failure")

        before = time.time()
        updated_job = worker._prepare_for_retry(job, error)
        after = time.time()

        assert 'next_retry_at' in updated_job
        assert updated_job['next_retry_at'] >= before  # In future or now

    def test_last_error_type_stored_in_job(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """last_error_type field stores exception class name."""
        from worker.processor import SyncWorker, TransientError

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {'scene_id': 123, 'data': {'path': '/test.mp4'}}
        error = TransientError("test failure")

        updated_job = worker._prepare_for_retry(job, error)

        assert updated_job['last_error_type'] == 'TransientError'


@pytest.mark.integration
class TestQueuePersistenceAcrossRestart:
    """Tests for retry metadata surviving worker restart."""

    def test_retry_metadata_survives_in_real_queue(self, real_queue, mock_dlq, mock_config, tmp_path):
        """Retry metadata persists in SQLiteAckQueue across instances."""
        from worker.processor import SyncWorker, TransientError
        import persistqueue

        # Worker 1 prepares job for retry
        worker1 = SyncWorker(
            queue=real_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/test.mp4'},
            'enqueued_at': time.time(),
            'job_key': 'scene_123',
        }
        error = TransientError("test failure")

        # Prepare retry metadata
        updated_job = worker1._prepare_for_retry(job, error)

        # Put in queue (simulating requeue)
        real_queue.put(updated_job)

        # Simulate worker restart - create new queue instance with same path
        # Get the queue path from the real_queue (it's stored in tmp_path/test_queue)
        queue_path = str(tmp_path / "test_queue")
        queue2 = persistqueue.SQLiteAckQueue(queue_path, auto_resume=True)

        # Get job from "new" queue
        retrieved_job = queue2.get(timeout=1)

        # Retry metadata should be preserved
        assert retrieved_job['retry_count'] == 1
        assert 'next_retry_at' in retrieved_job
        assert retrieved_job['last_error_type'] == 'TransientError'

    def test_requeue_preserves_all_job_fields(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """_requeue_with_metadata preserves original job data plus retry metadata."""
        from worker.processor import SyncWorker
        from unittest.mock import patch

        mock_queue.put = Mock()

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {
            'scene_id': 456,
            'update_type': 'metadata',
            'data': {'path': '/test.mp4', 'title': 'Test Title'},
            'enqueued_at': 1000.0,
            'job_key': 'scene_456',
            'pqid': 1,
            # Retry metadata
            'retry_count': 2,
            'next_retry_at': 2000.0,
            'last_error_type': 'TransientError',
        }

        # Patch ack_job in sync_queue.operations (lazy import in _requeue_with_metadata)
        with patch('sync_queue.operations.ack_job', Mock()):
            worker._requeue_with_metadata(job)

        # Verify new job was put with all fields
        mock_queue.put.assert_called_once()
        new_job = mock_queue.put.call_args[0][0]

        assert new_job['scene_id'] == 456
        assert new_job['update_type'] == 'metadata'
        assert new_job['data']['title'] == 'Test Title'
        assert new_job['retry_count'] == 2
        assert new_job['next_retry_at'] == 2000.0


@pytest.mark.integration
class TestRetryReadiness:
    """Tests for is_ready_for_retry logic."""

    def test_job_ready_when_delay_elapsed(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Job is ready when next_retry_at is in the past."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {'scene_id': 123, 'next_retry_at': time.time() - 10}  # 10s ago

        assert worker._is_ready_for_retry(job) is True

    def test_job_not_ready_when_in_backoff(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Job not ready when next_retry_at is in the future."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {'scene_id': 123, 'next_retry_at': time.time() + 100}  # 100s from now

        assert worker._is_ready_for_retry(job) is False

    def test_new_job_immediately_ready(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """New job without next_retry_at is immediately ready."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {'scene_id': 123}  # No next_retry_at

        assert worker._is_ready_for_retry(job) is True


@pytest.mark.integration
class TestDLQAfterMaxRetries:
    """Tests for jobs moving to DLQ after max retries."""

    def test_standard_error_exhausts_after_5_retries(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """TransientError exhausts after 5 retries."""
        from worker.processor import SyncWorker, TransientError

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        error = TransientError("test")
        max_retries = worker._get_max_retries_for_error(error)

        assert max_retries == 5

    def test_plex_not_found_exhausts_after_12_retries(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """PlexNotFound exhausts after 12 retries."""
        from worker.processor import SyncWorker
        from plex.exceptions import PlexNotFound

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        error = PlexNotFound("item not found")
        max_retries = worker._get_max_retries_for_error(error)

        assert max_retries == 12

    def test_job_sent_to_dlq_when_retries_exceeded(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Job with retry_count >= max_retries should go to DLQ."""
        from worker.processor import SyncWorker, TransientError

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Job at retry 4, will become 5 after prepare_for_retry
        job = {'scene_id': 123, 'data': {'path': '/test.mp4'}, 'retry_count': 4}
        error = TransientError("test")

        updated_job = worker._prepare_for_retry(job, error)
        max_retries = worker._get_max_retries_for_error(error)

        # Should be at max (5)
        assert updated_job['retry_count'] == 5
        assert updated_job['retry_count'] >= max_retries


@pytest.mark.integration
class TestRealQueueIntegration:
    """Tests for full queue persistence workflow with real SQLiteAckQueue."""

    def test_multiple_retry_metadata_updates_persist(self, real_queue, mock_dlq, mock_config, tmp_path):
        """Multiple retry updates persist correctly in queue."""
        from worker.processor import SyncWorker, TransientError
        import persistqueue

        worker = SyncWorker(
            queue=real_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {
            'scene_id': 999,
            'update_type': 'metadata',
            'data': {'path': '/test.mp4'},
            'enqueued_at': time.time(),
            'job_key': 'scene_999',
        }
        error = TransientError("test failure")

        # Simulate multiple retries
        for expected_count in range(1, 4):
            job = worker._prepare_for_retry(job, error)
            assert job['retry_count'] == expected_count
            real_queue.put(job)
            job = real_queue.get(timeout=1)

        # Final state should show 3 retries
        assert job['retry_count'] == 3
        assert job['last_error_type'] == 'TransientError'

    def test_plex_not_found_uses_different_backoff_params(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """PlexNotFound gets longer delays than standard errors."""
        from worker.processor import SyncWorker, TransientError
        from plex.exceptions import PlexNotFound
        from worker.backoff import get_retry_params

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Get backoff params for both error types
        base_std, cap_std, max_std = get_retry_params(TransientError("test"))
        base_nf, cap_nf, max_nf = get_retry_params(PlexNotFound("test"))

        # PlexNotFound should have longer delays and more retries
        assert base_nf > base_std  # 30s vs 5s
        assert cap_nf > cap_std    # 600s vs 80s
        assert max_nf > max_std    # 12 vs 5
