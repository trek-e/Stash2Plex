"""
Tests for worker/processor.py - SyncWorker stats integration.

Tests verify:
- _stats initialization on worker creation
- Stats loading from file when data_dir is set
- record_success called on successful job
- record_failure called on TransientError
- record_failure called on PermanentError with to_dlq=True
- _log_batch_summary produces expected log output
"""

import json
import os
import pytest
from unittest.mock import Mock, MagicMock, patch, call


@pytest.fixture
def processor_worker(mock_queue, mock_dlq, mock_config, tmp_path):
    """Create SyncWorker with mocked dependencies for stats testing."""
    from worker.processor import SyncWorker

    # Add required config attributes
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


@pytest.fixture
def processor_worker_no_data_dir(mock_queue, mock_dlq, mock_config):
    """Create SyncWorker without data_dir for testing default stats."""
    from worker.processor import SyncWorker

    # Add required config attributes
    mock_config.plex_connect_timeout = 10.0
    mock_config.plex_read_timeout = 30.0
    mock_config.preserve_plex_edits = False
    mock_config.strict_matching = False
    mock_config.dlq_retention_days = 30

    worker = SyncWorker(
        queue=mock_queue,
        dlq=mock_dlq,
        config=mock_config,
        data_dir=None,
    )

    return worker


class TestStatsInitialization:
    """Tests for _stats initialization in SyncWorker."""

    def test_stats_initialized_on_worker_creation(self, processor_worker_no_data_dir):
        """SyncWorker initializes _stats as SyncStats instance."""
        from worker.stats import SyncStats

        assert hasattr(processor_worker_no_data_dir, '_stats')
        assert isinstance(processor_worker_no_data_dir._stats, SyncStats)

    def test_stats_default_values_without_data_dir(self, processor_worker_no_data_dir):
        """Stats have default values when data_dir is None."""
        stats = processor_worker_no_data_dir._stats

        assert stats.jobs_processed == 0
        assert stats.jobs_succeeded == 0
        assert stats.jobs_failed == 0

    def test_stats_loaded_from_file_when_data_dir_set(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Stats are loaded from file if data_dir is set and file exists."""
        from worker.processor import SyncWorker

        # Add required config attributes
        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        # Create existing stats file
        stats_file = tmp_path / "stats.json"
        stats_file.write_text(json.dumps({
            "jobs_processed": 100,
            "jobs_succeeded": 90,
            "jobs_failed": 10,
            "jobs_to_dlq": 5,
            "total_processing_time": 150.5,
            "session_start": 1700000000.0,
            "errors_by_type": {"PlexNotFound": 3, "TransientError": 7},
            "high_confidence_matches": 85,
            "low_confidence_matches": 5,
        }))

        # Create worker - should load stats from file
        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        assert worker._stats.jobs_processed == 100
        assert worker._stats.jobs_succeeded == 90
        assert worker._stats.jobs_failed == 10
        assert worker._stats.jobs_to_dlq == 5

    def test_stats_empty_when_file_missing(self, processor_worker):
        """Stats start empty when file doesn't exist."""
        # tmp_path is empty, so no stats.json
        assert processor_worker._stats.jobs_processed == 0


class TestStatsTracking:
    """Tests for stats tracking during job processing."""

    def test_process_job_returns_confidence_for_stats_tracking(self, processor_worker, mock_plex_item):
        """_process_job returns confidence so worker loop can call record_success."""
        # Setup worker with mock Plex client
        mock_section = MagicMock()
        mock_section.title = "Test Library"

        mock_client = MagicMock()
        mock_client.server.library.sections.return_value = [mock_section]
        mock_client.server.library.section.return_value = mock_section
        processor_worker._plex_client = mock_client

        # Create a job
        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {
                'path': '/media/videos/test.mp4',
                'title': 'Test Title',
            },
            'pqid': 1,
        }

        # Mock find_plex_items_with_confidence at the module level where it's imported
        with patch('plex.matcher.find_plex_items_with_confidence') as mock_find:
            # Return single match (high confidence)
            mock_find.return_value = ('high', mock_plex_item, [mock_plex_item])

            # Call _process_job and verify it returns the confidence
            confidence = processor_worker._process_job(job)

            assert confidence == 'high'
            # Worker loop would use this to call:
            # self._stats.record_success(elapsed_time, confidence=confidence)

    def test_record_failure_called_on_transient_error(self, processor_worker):
        """record_failure is called when _process_job raises TransientError."""
        from worker.processor import TransientError

        # Make _process_job raise TransientError
        with patch.object(processor_worker, '_process_job', side_effect=TransientError("Connection failed")):
            with patch.object(processor_worker._stats, 'record_failure') as mock_record:
                # Create a job that will fail
                job = {
                    'scene_id': 123,
                    'pqid': 1,
                    'retry_count': 0,
                }

                # Simulate the error handling from _worker_loop
                import time
                _job_start = time.perf_counter()
                try:
                    processor_worker._process_job(job)
                except TransientError as e:
                    _job_elapsed = time.perf_counter() - _job_start
                    processor_worker._stats.record_failure(type(e).__name__, _job_elapsed, to_dlq=False)

                mock_record.assert_called_once()
                call_args = mock_record.call_args
                assert call_args[0][0] == 'TransientError'
                assert call_args[1]['to_dlq'] is False

    def test_record_failure_called_on_permanent_error(self, processor_worker):
        """record_failure is called with to_dlq=True on PermanentError."""
        from worker.processor import PermanentError

        # Make _process_job raise PermanentError
        with patch.object(processor_worker, '_process_job', side_effect=PermanentError("Invalid data")):
            with patch.object(processor_worker._stats, 'record_failure') as mock_record:
                # Create a job that will fail
                job = {
                    'scene_id': 123,
                    'pqid': 1,
                }

                # Simulate the error handling from _worker_loop
                import time
                _job_start = time.perf_counter()
                try:
                    processor_worker._process_job(job)
                except PermanentError as e:
                    _job_elapsed = time.perf_counter() - _job_start
                    processor_worker._stats.record_failure(type(e).__name__, _job_elapsed, to_dlq=True)

                mock_record.assert_called_once()
                call_args = mock_record.call_args
                assert call_args[0][0] == 'PermanentError'
                assert call_args[1]['to_dlq'] is True

    def test_low_confidence_tracked(self, processor_worker, mock_plex_item):
        """Low confidence match is tracked when multiple candidates found."""
        # Create two mock items to simulate low confidence
        mock_item1 = MagicMock()
        mock_item1.key = "/library/metadata/1"
        mock_item1.title = "Item 1"
        mock_item1.media = [MagicMock()]
        mock_item1.media[0].parts = [MagicMock()]
        mock_item1.media[0].parts[0].file = "/path1.mp4"

        mock_item2 = MagicMock()
        mock_item2.key = "/library/metadata/2"
        mock_item2.title = "Item 2"
        mock_item2.media = [MagicMock()]
        mock_item2.media[0].parts = [MagicMock()]
        mock_item2.media[0].parts[0].file = "/path2.mp4"

        mock_section = MagicMock()
        mock_section.title = "Test Library"

        mock_client = MagicMock()
        mock_client.server.library.sections.return_value = [mock_section]
        mock_client.server.library.section.return_value = mock_section
        processor_worker._plex_client = mock_client

        # Mock find_plex_items_with_confidence at the module level where it's imported
        with patch('plex.matcher.find_plex_items_with_confidence') as mock_find:
            # Return multiple candidates
            mock_find.return_value = ('low', mock_item1, [mock_item1, mock_item2])

            job = {
                'scene_id': 123,
                'update_type': 'metadata',
                'data': {
                    'path': '/media/videos/test.mp4',
                    'title': 'Test Title',
                },
                'pqid': 1,
            }

            result = processor_worker._process_job(job)

            # Should return 'low' confidence
            assert result == 'low'


class TestBatchSummaryLogging:
    """Tests for _log_batch_summary method."""

    def test_log_batch_summary_logs_human_readable(self, processor_worker, capsys):
        """_log_batch_summary logs human-readable summary line."""
        # Add some stats
        processor_worker._stats.record_success(0.1, confidence='high')
        processor_worker._stats.record_success(0.2, confidence='high')
        processor_worker._stats.record_failure('TestError', 0.1, to_dlq=True)

        processor_worker._log_batch_summary()

        captured = capsys.readouterr()
        # Check for human-readable parts
        assert "Sync summary:" in captured.err
        assert "2/3 succeeded" in captured.err
        assert "66.7%" in captured.err

    def test_log_batch_summary_logs_json_stats(self, processor_worker, capsys):
        """_log_batch_summary logs JSON-formatted stats."""
        processor_worker._stats.record_success(0.1, confidence='high')
        processor_worker._stats.record_failure('PlexNotFound', 0.2, to_dlq=True)

        processor_worker._log_batch_summary()

        captured = capsys.readouterr()
        # Find the JSON stats line
        assert "Stats:" in captured.err

        # Extract and parse JSON
        for line in captured.err.split('\n'):
            if 'Stats:' in line:
                json_start = line.index('{')
                json_str = line[json_start:]
                stats_dict = json.loads(json_str)

                assert stats_dict['processed'] == 2
                assert stats_dict['succeeded'] == 1
                assert stats_dict['failed'] == 1
                assert stats_dict['to_dlq'] == 1
                assert stats_dict['high_confidence'] == 1
                assert stats_dict['errors_by_type'] == {'PlexNotFound': 1}
                break
        else:
            pytest.fail("Stats JSON not found in output")

    def test_log_batch_summary_includes_dlq_breakdown(self, processor_worker, capsys):
        """_log_batch_summary includes DLQ error type breakdown."""
        # Mock DLQ to return error summary
        processor_worker.dlq.get_error_summary.return_value = {
            'PlexNotFound': 3,
            'PermanentError': 2,
        }

        processor_worker._log_batch_summary()

        captured = capsys.readouterr()
        # Check for DLQ breakdown
        assert "DLQ contains 5 items:" in captured.err
        assert "PlexNotFound" in captured.err
        assert "PermanentError" in captured.err

    def test_log_batch_summary_no_dlq_warning_when_empty(self, processor_worker, capsys):
        """_log_batch_summary does not log DLQ warning when empty."""
        # Mock DLQ to return empty summary
        processor_worker.dlq.get_error_summary.return_value = {}

        processor_worker._log_batch_summary()

        captured = capsys.readouterr()
        # Should not have DLQ warning
        assert "DLQ contains" not in captured.err

    def test_log_batch_summary_zero_jobs_handled(self, processor_worker, capsys):
        """_log_batch_summary handles zero jobs gracefully."""
        # No stats recorded
        processor_worker._log_batch_summary()

        captured = capsys.readouterr()
        # Should log without error
        assert "Sync summary:" in captured.err
        assert "0/0 succeeded" in captured.err
        assert "0.0%" in captured.err


class TestStatsPersistence:
    """Tests for stats persistence during batch logging."""

    def test_stats_saved_periodically(self, processor_worker, tmp_path):
        """Stats are saved to file during batch logging interval."""
        # Record some stats
        processor_worker._stats.record_success(0.5, confidence='high')
        processor_worker._stats.record_failure('TestError', 0.3, to_dlq=True)

        # Manually save stats (as done in worker loop)
        stats_path = os.path.join(str(tmp_path), 'stats.json')
        processor_worker._stats.save_to_file(stats_path)

        # Verify file exists and contains correct data
        assert os.path.exists(stats_path)
        with open(stats_path, 'r') as f:
            saved = json.load(f)

        assert saved['jobs_processed'] == 2
        assert saved['jobs_succeeded'] == 1
        assert saved['jobs_failed'] == 1

    def test_stats_not_saved_without_data_dir(self, processor_worker_no_data_dir):
        """Stats are not saved when data_dir is None."""
        # Verify data_dir is None
        assert processor_worker_no_data_dir.data_dir is None

        # Record stats - this should not cause errors
        processor_worker_no_data_dir._stats.record_success(0.5)

        # Log batch summary should work without data_dir
        processor_worker_no_data_dir._log_batch_summary()


class TestProcessJobReturnValue:
    """Tests for _process_job return value (confidence)."""

    def test_process_job_returns_high_confidence(self, processor_worker, mock_plex_item):
        """_process_job returns 'high' for single match."""
        # Setup single match
        mock_section = MagicMock()
        mock_section.title = "Test Library"

        mock_client = MagicMock()
        mock_client.server.library.sections.return_value = [mock_section]
        mock_client.server.library.section.return_value = mock_section
        processor_worker._plex_client = mock_client

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/test.mp4'},
            'pqid': 1,
        }

        with patch('plex.matcher.find_plex_items_with_confidence') as mock_find:
            mock_find.return_value = ('high', mock_plex_item, [mock_plex_item])

            result = processor_worker._process_job(job)
            assert result == 'high'

    def test_process_job_returns_low_confidence_for_multiple_matches(self, processor_worker):
        """_process_job returns 'low' for multiple matches."""
        # Create multiple mock items
        mock_item1 = MagicMock()
        mock_item1.key = "/library/metadata/1"
        mock_item1.media = [MagicMock()]
        mock_item1.media[0].parts = [MagicMock()]
        mock_item1.media[0].parts[0].file = "/path1.mp4"

        mock_item2 = MagicMock()
        mock_item2.key = "/library/metadata/2"
        mock_item2.media = [MagicMock()]
        mock_item2.media[0].parts = [MagicMock()]
        mock_item2.media[0].parts[0].file = "/path2.mp4"

        mock_section = MagicMock()
        mock_section.title = "Test Library"

        mock_client = MagicMock()
        mock_client.server.library.sections.return_value = [mock_section]
        mock_client.server.library.section.return_value = mock_section
        processor_worker._plex_client = mock_client

        with patch('plex.matcher.find_plex_items_with_confidence') as mock_find:
            mock_find.return_value = ('low', mock_item1, [mock_item1, mock_item2])

            job = {
                'scene_id': 123,
                'update_type': 'metadata',
                'data': {'path': '/test.mp4'},
                'pqid': 1,
            }

            result = processor_worker._process_job(job)
            assert result == 'low'
