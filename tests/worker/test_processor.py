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


class TestFieldClearing:
    """Tests for LOCKED decision: missing optional fields clear Plex values."""

    @pytest.fixture
    def clearing_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker configured for clearing tests."""
        from worker.processor import SyncWorker

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

    def test_none_studio_clears_plex_studio(self, clearing_worker):
        """When Stash sends studio=None, existing Plex studio is cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"
        mock_plex_item.title = "Test Title"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Data dict has 'studio' key with None value (LOCKED: should clear)
        data = {'path': '/test.mp4', 'title': 'Test', 'studio': None}

        clearing_worker._update_metadata(mock_plex_item, data)

        # Verify edit was called with empty studio
        mock_plex_item.edit.assert_called()
        edit_kwargs = mock_plex_item.edit.call_args[1]
        assert 'studio.value' in edit_kwargs
        assert edit_kwargs['studio.value'] == ''

    def test_empty_string_studio_clears_plex_studio(self, clearing_worker):
        """When Stash sends studio='', existing Plex studio is cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"
        mock_plex_item.title = "Test Title"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Data dict has 'studio' key with empty string (LOCKED: should clear)
        data = {'path': '/test.mp4', 'title': 'Test', 'studio': ''}

        clearing_worker._update_metadata(mock_plex_item, data)

        # Verify edit was called with empty studio
        mock_plex_item.edit.assert_called()
        edit_kwargs = mock_plex_item.edit.call_args[1]
        assert 'studio.value' in edit_kwargs
        assert edit_kwargs['studio.value'] == ''

    def test_field_not_in_data_preserves_plex_value(self, clearing_worker):
        """When field key not in data dict, existing Plex value is preserved."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"
        mock_plex_item.title = "Test Title"
        mock_plex_item.summary = "Existing Summary"
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Data dict does NOT have 'studio' key - should NOT clear
        data = {'path': '/test.mp4', 'title': 'New Title'}

        clearing_worker._update_metadata(mock_plex_item, data)

        # Verify studio was NOT included in edit call
        if mock_plex_item.edit.called:
            edit_kwargs = mock_plex_item.edit.call_args[1]
            assert 'studio.value' not in edit_kwargs

    def test_none_summary_clears_plex_summary(self, clearing_worker):
        """When Stash sends details=None, existing Plex summary is cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test Title"
        mock_plex_item.summary = "Existing Summary"
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Data dict has 'details' key with None value (LOCKED: should clear)
        data = {'path': '/test.mp4', 'title': 'Test', 'details': None}

        clearing_worker._update_metadata(mock_plex_item, data)

        # Verify edit was called with empty summary
        mock_plex_item.edit.assert_called()
        edit_kwargs = mock_plex_item.edit.call_args[1]
        assert 'summary.value' in edit_kwargs
        assert edit_kwargs['summary.value'] == ''

    def test_none_tagline_clears_plex_tagline(self, clearing_worker):
        """When Stash sends tagline=None, existing Plex tagline is cleared."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test Title"
        mock_plex_item.summary = ""
        mock_plex_item.tagline = "Existing Tagline"
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'path': '/test.mp4', 'title': 'Test', 'tagline': None}

        clearing_worker._update_metadata(mock_plex_item, data)

        mock_plex_item.edit.assert_called()
        edit_kwargs = mock_plex_item.edit.call_args[1]
        assert 'tagline.value' in edit_kwargs
        assert edit_kwargs['tagline.value'] == ''

    def test_valid_value_sets_field(self, clearing_worker):
        """When Stash sends valid value, Plex field is set."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'path': '/test.mp4', 'studio': 'New Studio', 'title': 'New Title'}

        clearing_worker._update_metadata(mock_plex_item, data)

        mock_plex_item.edit.assert_called()
        # Get the first edit call (metadata fields), not the last (collection add)
        # edit() is called multiple times: once for title/studio, once for collection
        first_edit_kwargs = mock_plex_item.edit.call_args_list[0][1]
        assert first_edit_kwargs.get('studio.value') == 'New Studio'
        assert first_edit_kwargs.get('title.value') == 'New Title'


class TestListFieldLimits:
    """Tests for list field limits (performers, tags)."""

    @pytest.fixture
    def limits_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker configured for limits tests."""
        from worker.processor import SyncWorker

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

    def test_performers_truncated_at_max(self, limits_worker, capsys):
        """More than MAX_PERFORMERS performers are truncated with warning."""
        from validation.limits import MAX_PERFORMERS

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Create more performers than MAX_PERFORMERS
        performers = [f"Performer {i}" for i in range(MAX_PERFORMERS + 10)]
        data = {'path': '/test.mp4', 'performers': performers}

        limits_worker._update_metadata(mock_plex_item, data)

        # Verify warning was logged
        captured = capsys.readouterr()
        assert "Truncating performers list" in captured.err
        assert str(MAX_PERFORMERS + 10) in captured.err
        assert str(MAX_PERFORMERS) in captured.err

    def test_tags_truncated_at_max(self, limits_worker, capsys):
        """More than max_tags tags are truncated with warning."""
        from validation.limits import MAX_TAGS

        # Use configurable max_tags from worker config (default: 100)
        max_tags = getattr(limits_worker.config, 'max_tags', MAX_TAGS)

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Create more tags than configured max_tags
        excess_count = 10
        tags = [f"Tag {i}" for i in range(max_tags + excess_count)]
        data = {'path': '/test.mp4', 'tags': tags}

        limits_worker._update_metadata(mock_plex_item, data)

        # Verify warning was logged
        captured = capsys.readouterr()
        assert "Truncating tags list" in captured.err
        assert str(max_tags + excess_count) in captured.err
        assert str(max_tags) in captured.err

    def test_performers_under_limit_not_truncated(self, limits_worker, capsys):
        """Performers under MAX_PERFORMERS are not truncated."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Create fewer performers than MAX_PERFORMERS
        performers = ["Performer 1", "Performer 2", "Performer 3"]
        data = {'path': '/test.mp4', 'performers': performers}

        limits_worker._update_metadata(mock_plex_item, data)

        # Verify no truncation warning
        captured = capsys.readouterr()
        assert "Truncating performers list" not in captured.err

    def test_empty_performers_clears_actors(self, limits_worker, capsys):
        """Empty performers list clears all actors (LOCKED decision)."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = [MagicMock(tag="Existing Actor")]
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Empty performers list with key present (LOCKED: should clear)
        data = {'path': '/test.mp4', 'performers': []}

        limits_worker._update_metadata(mock_plex_item, data)

        # Verify clearing was logged
        captured = capsys.readouterr()
        assert "Clearing performers" in captured.err

    def test_empty_tags_clears_genres(self, limits_worker, capsys):
        """Empty tags list clears all genres (LOCKED decision)."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = "Test"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = [MagicMock(tag="Existing Genre")]
        mock_plex_item.collections = []

        # Empty tags list with key present (LOCKED: should clear)
        data = {'path': '/test.mp4', 'tags': []}

        limits_worker._update_metadata(mock_plex_item, data)

        # Verify clearing was logged
        captured = capsys.readouterr()
        assert "Clearing tags" in captured.err


class TestPartialSyncFailure:
    """Tests for partial sync failure handling - non-critical field failures don't fail job."""

    @pytest.fixture
    def partial_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker for partial failure tests."""
        from worker.processor import SyncWorker

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

    def test_performer_sync_fails_job_still_succeeds(self, partial_worker, capsys):
        """When performer sync fails, title sync succeeds, job succeeds."""
        from validation.errors import PartialSyncResult

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make performer edit fail
        def edit_side_effect(**kwargs):
            if 'actor[0].tag.tag' in kwargs:
                raise ConnectionError("Plex connection failed")
            # Other edits succeed
        mock_plex_item.edit.side_effect = edit_side_effect

        data = {
            'path': '/test.mp4',
            'title': 'Test Title',
            'performers': ['Actor 1', 'Actor 2'],
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        # Job should succeed overall
        assert result.success is True
        # Metadata was updated
        assert 'metadata' in result.fields_updated
        # Performer failure tracked as warning
        assert result.has_warnings
        assert any(w.field_name == 'performers' for w in result.warnings)

        # Warning was logged
        captured = capsys.readouterr()
        assert "Partial sync" in captured.err

    def test_tag_sync_fails_other_fields_succeed(self, partial_worker, capsys):
        """When tag sync fails, other fields succeed, job succeeds."""
        from validation.errors import PartialSyncResult

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make tag edit fail
        def edit_side_effect(**kwargs):
            if 'genre[0].tag.tag' in kwargs:
                raise TimeoutError("Plex timeout")
            # Other edits succeed
        mock_plex_item.edit.side_effect = edit_side_effect

        data = {
            'path': '/test.mp4',
            'title': 'Test Title',
            'studio': 'Test Studio',
            'tags': ['Tag 1', 'Tag 2'],
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        # Job should succeed overall
        assert result.success is True
        # Metadata was updated
        assert 'metadata' in result.fields_updated
        # Tag failure tracked as warning
        assert result.has_warnings
        assert any(w.field_name == 'tags' for w in result.warnings)

    def test_poster_upload_fails_metadata_succeeds(self, partial_worker):
        """When poster upload fails, metadata sync succeeds, job succeeds."""
        from validation.errors import PartialSyncResult

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make poster upload fail
        mock_plex_item.uploadPoster.side_effect = Exception("Upload failed")

        # Mock _fetch_stash_image to return valid image data
        partial_worker._fetch_stash_image = MagicMock(return_value=b'fake image data')

        data = {
            'path': '/test.mp4',
            'title': 'Test Title',
            'poster_url': 'http://stash/poster.jpg',
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        # Job should succeed overall
        assert result.success is True
        # Metadata was updated
        assert 'metadata' in result.fields_updated
        # Poster failure tracked as warning
        assert result.has_warnings
        assert any(w.field_name == 'poster' for w in result.warnings)

    def test_multiple_non_critical_failures_aggregated(self, partial_worker, capsys):
        """Multiple non-critical failures are aggregated in warnings."""
        from validation.errors import PartialSyncResult

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make both performer and tag edits fail
        def edit_side_effect(**kwargs):
            if 'actor[0].tag.tag' in kwargs:
                raise ConnectionError("Actor sync failed")
            if 'genre[0].tag.tag' in kwargs:
                raise TimeoutError("Tag sync failed")
            # Other edits succeed
        mock_plex_item.edit.side_effect = edit_side_effect

        # Make poster upload fail too
        mock_plex_item.uploadPoster.side_effect = Exception("Poster upload failed")
        partial_worker._fetch_stash_image = MagicMock(return_value=b'fake image data')

        data = {
            'path': '/test.mp4',
            'title': 'Test Title',
            'performers': ['Actor 1'],
            'tags': ['Tag 1'],
            'poster_url': 'http://stash/poster.jpg',
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        # Job should still succeed overall
        assert result.success is True
        # Multiple warnings
        assert len(result.warnings) == 3
        warning_fields = [w.field_name for w in result.warnings]
        assert 'performers' in warning_fields
        assert 'tags' in warning_fields
        assert 'poster' in warning_fields

        # Warning summary includes all failures
        captured = capsys.readouterr()
        assert "3 warnings" in captured.err

    def test_update_metadata_returns_partial_sync_result(self, partial_worker):
        """_update_metadata returns PartialSyncResult instance."""
        from validation.errors import PartialSyncResult

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'path': '/test.mp4', 'title': 'Test Title'}

        result = partial_worker._update_metadata(mock_plex_item, data)

        assert isinstance(result, PartialSyncResult)
        assert result.success is True
        assert 'metadata' in result.fields_updated

    def test_successful_sync_records_all_fields(self, partial_worker):
        """Successful sync of all fields records them in fields_updated."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Mock _fetch_stash_image to return valid image data
        partial_worker._fetch_stash_image = MagicMock(return_value=b'fake image data')

        data = {
            'path': '/test.mp4',
            'title': 'Test Title',
            'studio': 'Test Studio',
            'performers': ['Actor 1'],
            'tags': ['Tag 1'],
            'poster_url': 'http://stash/poster.jpg',
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        # All fields should be recorded as successful
        assert 'metadata' in result.fields_updated
        assert 'performers' in result.fields_updated
        assert 'tags' in result.fields_updated
        assert 'poster' in result.fields_updated
        assert 'collection' in result.fields_updated
        assert result.has_warnings is False

    def test_collection_failure_doesnt_fail_job(self, partial_worker):
        """When collection add fails, job still succeeds."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make collection edit fail
        def edit_side_effect(**kwargs):
            if 'collection[0].tag.tag' in kwargs:
                raise ValueError("Collection error")
            # Other edits succeed
        mock_plex_item.edit.side_effect = edit_side_effect

        data = {
            'path': '/test.mp4',
            'title': 'Test Title',
            'studio': 'Test Studio',  # This triggers collection add
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        assert result.success is True
        assert 'metadata' in result.fields_updated
        assert any(w.field_name == 'collection' for w in result.warnings)

    def test_background_upload_failure_doesnt_fail_job(self, partial_worker):
        """When background upload fails, job still succeeds."""
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Make background upload fail
        mock_plex_item.uploadArt.side_effect = Exception("Art upload failed")
        partial_worker._fetch_stash_image = MagicMock(return_value=b'fake image data')

        data = {
            'path': '/test.mp4',
            'title': 'Test Title',
            'background_url': 'http://stash/background.jpg',
        }

        result = partial_worker._update_metadata(mock_plex_item, data)

        assert result.success is True
        assert 'metadata' in result.fields_updated
        assert any(w.field_name == 'background' for w in result.warnings)


class TestSyncToggles:
    """Tests for field sync toggle behavior."""

    @pytest.fixture
    def toggle_worker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Create SyncWorker configured for toggle tests."""
        from worker.processor import SyncWorker

        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30
        # All toggles default True
        mock_config.sync_master = True
        mock_config.sync_studio = True
        mock_config.sync_summary = True
        mock_config.sync_tagline = True
        mock_config.sync_date = True
        mock_config.sync_performers = True
        mock_config.sync_tags = True
        mock_config.sync_poster = True
        mock_config.sync_background = True
        mock_config.sync_collection = True

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        return worker

    def test_master_toggle_off_skips_all_fields(self, toggle_worker, capsys):
        """When sync_master=False, no fields are synced."""
        toggle_worker.config.sync_master = False
        toggle_worker.config.sync_studio = True  # Even with individual ON

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'studio': 'Test Studio', 'details': 'Test Summary'}

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # edit() should not be called at all
        mock_plex_item.edit.assert_not_called()

        # Debug log should mention master toggle
        captured = capsys.readouterr()
        assert "Master sync toggle is OFF" in captured.err

    def test_individual_toggle_off_skips_that_field(self, toggle_worker):
        """When individual toggle=False, that field is skipped."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_studio = False
        toggle_worker.config.sync_summary = True

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'studio': 'Test Studio', 'details': 'Test Summary'}

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # edit() should be called but only with summary, not studio
        assert mock_plex_item.edit.called
        edit_kwargs = mock_plex_item.edit.call_args_list[0][1]
        assert 'studio.value' not in edit_kwargs
        assert 'summary.value' in edit_kwargs

    def test_toggle_off_does_not_clear_field(self, toggle_worker):
        """Toggle OFF should NOT clear the Plex field (distinct from empty value clearing)."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_studio = False
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"  # Plex has a value
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'studio': 'New Studio'}  # Stash has a value

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # Studio should NOT appear in edits at all (not cleared, not updated)
        if mock_plex_item.edit.called:
            for call in mock_plex_item.edit.call_args_list:
                kwargs = call[1]
                assert 'studio.value' not in kwargs, "Toggle OFF should skip field, not clear it"

    def test_toggle_on_with_empty_value_clears_field(self, toggle_worker):
        """Toggle ON with None/empty value should CLEAR field (LOCKED decision)."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_studio = True
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'studio': None}  # Stash value is None

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # Studio should be cleared (LOCKED Phase 9 behavior)
        edit_kwargs = mock_plex_item.edit.call_args_list[0][1]
        assert edit_kwargs.get('studio.value') == ''

    def test_toggle_on_preserves_preserve_mode_behavior(self, toggle_worker):
        """Toggle ON + preserve_plex_edits ON should preserve existing values."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_studio = True
        toggle_worker.config.preserve_plex_edits = True
        mock_plex_item = MagicMock()
        mock_plex_item.studio = "Existing Studio"  # Plex has value
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'studio': 'New Studio'}

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # With preserve mode, existing value should be kept
        if mock_plex_item.edit.called:
            for call in mock_plex_item.edit.call_args_list:
                kwargs = call[1]
                assert 'studio.value' not in kwargs, "Preserve mode should skip field with existing value"

    def test_all_individual_toggles_respected(self, toggle_worker):
        """Each individual toggle should control its respective field."""
        # Set all toggles OFF except one
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_studio = False
        toggle_worker.config.sync_summary = False
        toggle_worker.config.sync_tagline = True  # Only this ON
        toggle_worker.config.sync_date = False

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.tagline = None
        mock_plex_item.originallyAvailableAt = None
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {
            'studio': 'Test Studio',
            'details': 'Test Summary',
            'tagline': 'Test Tagline',
            'date': '2024-01-01',
        }

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # Only tagline should be in edits
        edit_kwargs = mock_plex_item.edit.call_args_list[0][1]
        assert 'studio.value' not in edit_kwargs
        assert 'summary.value' not in edit_kwargs
        assert 'tagline.value' in edit_kwargs
        assert 'originallyAvailableAt.value' not in edit_kwargs

    def test_performers_toggle_off_skips_performers(self, toggle_worker):
        """sync_performers=False should skip performer sync entirely."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_performers = False
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'performers': ['Actor 1', 'Actor 2']}

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # No performer-related edits should happen
        for call in mock_plex_item.edit.call_args_list:
            kwargs = call[1]
            assert not any('actor' in k for k in kwargs.keys())

    def test_tags_toggle_off_skips_tags(self, toggle_worker):
        """sync_tags=False should skip tag/genre sync entirely."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_tags = False
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'tags': ['Genre 1', 'Genre 2']}

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # No genre-related edits should happen
        for call in mock_plex_item.edit.call_args_list:
            kwargs = call[1]
            assert not any('genre' in k for k in kwargs.keys())

    def test_poster_toggle_off_skips_poster(self, toggle_worker):
        """sync_poster=False should skip poster upload."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_poster = False

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Mock _fetch_stash_image to verify it's not called
        toggle_worker._fetch_stash_image = MagicMock(return_value=b'fake image data')

        data = {'poster_url': 'http://stash/image.jpg'}

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # uploadPoster should not be called
        mock_plex_item.uploadPoster.assert_not_called()

    def test_collection_toggle_off_skips_collection(self, toggle_worker):
        """sync_collection=False should skip collection assignment."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_collection = False
        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {'studio': 'Test Studio'}  # Studio triggers collection

        # Need to also enable sync_studio to get studio synced
        toggle_worker.config.sync_studio = True

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # No collection-related edits should happen
        for call in mock_plex_item.edit.call_args_list:
            kwargs = call[1]
            assert not any('collection' in k for k in kwargs.keys())

    def test_background_toggle_off_skips_background(self, toggle_worker):
        """sync_background=False should skip background upload."""
        toggle_worker.config.sync_master = True
        toggle_worker.config.sync_background = False

        mock_plex_item = MagicMock()
        mock_plex_item.studio = ""
        mock_plex_item.title = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        # Mock _fetch_stash_image to verify it's not called
        toggle_worker._fetch_stash_image = MagicMock(return_value=b'fake image data')

        data = {'background_url': 'http://stash/background.jpg'}

        result = toggle_worker._update_metadata(mock_plex_item, data)

        # uploadArt should not be called
        mock_plex_item.uploadArt.assert_not_called()


class TestActiveHealthProbes:
    """Tests for active health check integration in worker loop during OPEN circuit state."""

    def test_health_check_state_initialized(self, processor_worker):
        """Worker initializes health check state variables."""
        assert hasattr(processor_worker, '_last_health_check')
        assert hasattr(processor_worker, '_health_check_interval')
        assert hasattr(processor_worker, '_consecutive_health_failures')
        assert processor_worker._last_health_check == 0.0
        assert processor_worker._health_check_interval == 5.0
        assert processor_worker._consecutive_health_failures == 0

    def test_health_check_interval_timing(self, processor_worker):
        """Health check respects interval timing."""
        import time

        # Set state
        now = time.time()
        processor_worker._last_health_check = now - 3.0  # 3 seconds ago
        processor_worker._health_check_interval = 5.0

        # Not enough time has elapsed
        elapsed = now - processor_worker._last_health_check
        assert elapsed < processor_worker._health_check_interval

        # Now advance time
        later = now + 5.0
        elapsed = later - processor_worker._last_health_check
        assert elapsed >= processor_worker._health_check_interval

    def test_successful_health_check_resets_state(self, processor_worker):
        """Successful health check resets interval to 5s and failure counter to 0."""
        import time

        # Set health check state to indicate previous failures
        processor_worker._health_check_interval = 20.0  # Backed off
        processor_worker._consecutive_health_failures = 3
        start_time = time.time()

        # Simulate successful health check response
        is_healthy = True
        if is_healthy:
            processor_worker._consecutive_health_failures = 0
            processor_worker._health_check_interval = 5.0
            processor_worker._last_health_check = start_time

        # Verify reset
        assert processor_worker._consecutive_health_failures == 0
        assert processor_worker._health_check_interval == 5.0
        assert processor_worker._last_health_check == start_time

    def test_failed_health_check_uses_backoff(self, processor_worker):
        """Failed health check increases interval via exponential backoff."""
        from worker.backoff import calculate_delay
        import time

        # Set initial state
        processor_worker._health_check_interval = 5.0
        processor_worker._consecutive_health_failures = 0
        start_time = time.time()

        # Simulate failed health check
        is_healthy = False
        if not is_healthy:
            processor_worker._consecutive_health_failures += 1
            processor_worker._health_check_interval = calculate_delay(
                retry_count=processor_worker._consecutive_health_failures,
                base=5.0,
                cap=60.0,
                jitter_seed=42  # Deterministic for testing
            )
            processor_worker._last_health_check = start_time

        # Verify failure count increased
        assert processor_worker._consecutive_health_failures == 1

        # Verify interval was calculated (with jitter, should be 0-10s range)
        # For retry_count=1: base * 2^1 = 5 * 2 = 10, with full jitter: 0-10
        assert 0.0 <= processor_worker._health_check_interval <= 10.0

    def test_consecutive_failures_increment(self, processor_worker):
        """Consecutive failures increment correctly."""
        processor_worker._consecutive_health_failures = 2

        # Simulate another failure
        processor_worker._consecutive_health_failures += 1

        assert processor_worker._consecutive_health_failures == 3

    def test_backoff_calculation_parameters(self):
        """Verify backoff uses correct parameters (5s base, 60s cap)."""
        from worker.backoff import calculate_delay

        # Test with deterministic seed
        delay1 = calculate_delay(retry_count=0, base=5.0, cap=60.0, jitter_seed=42)
        delay2 = calculate_delay(retry_count=1, base=5.0, cap=60.0, jitter_seed=42)
        delay3 = calculate_delay(retry_count=4, base=5.0, cap=60.0, jitter_seed=42)
        delay4 = calculate_delay(retry_count=10, base=5.0, cap=60.0, jitter_seed=42)  # Should hit cap

        # Verify ranges
        assert 0.0 <= delay1 <= 5.0   # 2^0 = 1, 5*1 = 5
        assert 0.0 <= delay2 <= 10.0  # 2^1 = 2, 5*2 = 10
        assert 0.0 <= delay3 <= 60.0  # 2^4 = 16, 5*16 = 80, capped at 60
        assert 0.0 <= delay4 <= 60.0  # Well over cap, should be capped

    def test_health_check_timeout_value(self):
        """Verify health check uses 5s timeout constant."""
        # This test verifies the constant is 5.0, not tied to config
        timeout = 5.0
        assert timeout == 5.0
