"""
Tests for worker/stats.py - SyncStats dataclass.

Tests statistics tracking, persistence, and cumulative merging.
"""

import json
import os
import time

import pytest


@pytest.fixture
def stats():
    """Create fresh SyncStats instance."""
    from worker.stats import SyncStats

    return SyncStats()


@pytest.fixture
def stats_file(tmp_path):
    """Return path for stats JSON file in temp directory."""
    return str(tmp_path / "stats.json")


class TestSyncStatsRecordSuccess:
    """Tests for record_success method."""

    def test_record_success_increments_jobs_processed(self, stats):
        """record_success increments jobs_processed counter."""
        assert stats.jobs_processed == 0

        stats.record_success(0.5)

        assert stats.jobs_processed == 1

    def test_record_success_increments_jobs_succeeded(self, stats):
        """record_success increments jobs_succeeded counter."""
        assert stats.jobs_succeeded == 0

        stats.record_success(0.5)

        assert stats.jobs_succeeded == 1

    def test_record_success_adds_processing_time(self, stats):
        """record_success adds to total_processing_time."""
        stats.record_success(0.5)
        stats.record_success(1.2)

        assert stats.total_processing_time == pytest.approx(1.7, rel=1e-6)

    def test_record_success_tracks_high_confidence(self, stats):
        """record_success with confidence='high' increments high_confidence_matches."""
        stats.record_success(0.5, confidence='high')

        assert stats.high_confidence_matches == 1
        assert stats.low_confidence_matches == 0

    def test_record_success_tracks_low_confidence(self, stats):
        """record_success with confidence='low' increments low_confidence_matches."""
        stats.record_success(0.5, confidence='low')

        assert stats.low_confidence_matches == 1
        assert stats.high_confidence_matches == 0

    def test_record_success_default_high_confidence(self, stats):
        """record_success defaults to high confidence."""
        stats.record_success(0.5)

        assert stats.high_confidence_matches == 1

    def test_record_success_multiple_calls(self, stats):
        """record_success accumulates correctly with multiple calls."""
        stats.record_success(0.1, confidence='high')
        stats.record_success(0.2, confidence='low')
        stats.record_success(0.3, confidence='high')

        assert stats.jobs_processed == 3
        assert stats.jobs_succeeded == 3
        assert stats.high_confidence_matches == 2
        assert stats.low_confidence_matches == 1
        assert stats.total_processing_time == pytest.approx(0.6, rel=1e-6)


class TestSyncStatsRecordFailure:
    """Tests for record_failure method."""

    def test_record_failure_increments_jobs_processed(self, stats):
        """record_failure increments jobs_processed counter."""
        stats.record_failure('TestError', 0.5)

        assert stats.jobs_processed == 1

    def test_record_failure_increments_jobs_failed(self, stats):
        """record_failure increments jobs_failed counter."""
        stats.record_failure('TestError', 0.5)

        assert stats.jobs_failed == 1

    def test_record_failure_adds_processing_time(self, stats):
        """record_failure adds to total_processing_time."""
        stats.record_failure('TestError', 0.3)
        stats.record_failure('AnotherError', 0.7)

        assert stats.total_processing_time == pytest.approx(1.0, rel=1e-6)

    def test_record_failure_tracks_error_type(self, stats):
        """record_failure tracks error type count."""
        stats.record_failure('PlexNotFound', 0.5)

        assert stats.errors_by_type == {'PlexNotFound': 1}

    def test_record_failure_accumulates_same_error_type(self, stats):
        """record_failure accumulates count for same error type."""
        stats.record_failure('PlexNotFound', 0.1)
        stats.record_failure('PlexNotFound', 0.2)
        stats.record_failure('PlexNotFound', 0.3)

        assert stats.errors_by_type == {'PlexNotFound': 3}

    def test_record_failure_tracks_multiple_error_types(self, stats):
        """record_failure tracks multiple different error types."""
        stats.record_failure('PlexNotFound', 0.1)
        stats.record_failure('PermanentError', 0.2)
        stats.record_failure('PlexNotFound', 0.3)
        stats.record_failure('TransientError', 0.4)

        assert stats.errors_by_type == {
            'PlexNotFound': 2,
            'PermanentError': 1,
            'TransientError': 1,
        }

    def test_record_failure_with_to_dlq_true(self, stats):
        """record_failure with to_dlq=True increments jobs_to_dlq."""
        stats.record_failure('PermanentError', 0.5, to_dlq=True)

        assert stats.jobs_to_dlq == 1
        assert stats.jobs_failed == 1

    def test_record_failure_with_to_dlq_false(self, stats):
        """record_failure with to_dlq=False does not increment jobs_to_dlq."""
        stats.record_failure('TransientError', 0.5, to_dlq=False)

        assert stats.jobs_to_dlq == 0
        assert stats.jobs_failed == 1

    def test_record_failure_to_dlq_default_false(self, stats):
        """record_failure defaults to_dlq to False."""
        stats.record_failure('TestError', 0.5)

        assert stats.jobs_to_dlq == 0


class TestSyncStatsSuccessRate:
    """Tests for success_rate property."""

    def test_success_rate_zero_jobs(self, stats):
        """success_rate returns 0.0 when no jobs processed."""
        assert stats.success_rate == 0.0

    def test_success_rate_all_success(self, stats):
        """success_rate returns 100.0 when all jobs succeed."""
        stats.record_success(0.1)
        stats.record_success(0.2)
        stats.record_success(0.3)

        assert stats.success_rate == 100.0

    def test_success_rate_all_failure(self, stats):
        """success_rate returns 0.0 when all jobs fail."""
        stats.record_failure('Error1', 0.1)
        stats.record_failure('Error2', 0.2)

        assert stats.success_rate == 0.0

    def test_success_rate_mixed(self, stats):
        """success_rate calculates correct percentage for mixed results."""
        stats.record_success(0.1)
        stats.record_success(0.2)
        stats.record_failure('Error', 0.3)
        stats.record_failure('Error', 0.4)

        assert stats.success_rate == 50.0

    def test_success_rate_decimal(self, stats):
        """success_rate handles non-integer percentages."""
        stats.record_success(0.1)
        stats.record_success(0.2)
        stats.record_failure('Error', 0.3)

        assert stats.success_rate == pytest.approx(66.666666, rel=1e-4)


class TestSyncStatsAvgProcessingTime:
    """Tests for avg_processing_time property."""

    def test_avg_processing_time_zero_jobs(self, stats):
        """avg_processing_time returns 0.0 when no jobs processed."""
        assert stats.avg_processing_time == 0.0

    def test_avg_processing_time_single_job(self, stats):
        """avg_processing_time returns correct value for single job."""
        stats.record_success(1.5)

        assert stats.avg_processing_time == 1.5

    def test_avg_processing_time_multiple_jobs(self, stats):
        """avg_processing_time calculates correct average."""
        stats.record_success(1.0)
        stats.record_success(2.0)
        stats.record_success(3.0)

        assert stats.avg_processing_time == pytest.approx(2.0, rel=1e-6)

    def test_avg_processing_time_includes_failures(self, stats):
        """avg_processing_time includes time from failed jobs."""
        stats.record_success(1.0)
        stats.record_failure('Error', 2.0)

        assert stats.avg_processing_time == pytest.approx(1.5, rel=1e-6)


class TestSyncStatsToDict:
    """Tests for to_dict method."""

    def test_to_dict_returns_all_fields(self, stats):
        """to_dict returns dict with all stats fields."""
        stats.record_success(0.5, confidence='high')
        stats.record_failure('PlexNotFound', 0.3, to_dlq=True)

        result = stats.to_dict()

        assert 'jobs_processed' in result
        assert 'jobs_succeeded' in result
        assert 'jobs_failed' in result
        assert 'jobs_to_dlq' in result
        assert 'total_processing_time' in result
        assert 'session_start' in result
        assert 'errors_by_type' in result
        assert 'high_confidence_matches' in result
        assert 'low_confidence_matches' in result

    def test_to_dict_returns_correct_values(self, stats):
        """to_dict returns correct field values."""
        stats.record_success(0.5, confidence='low')
        stats.record_failure('TestError', 0.3, to_dlq=True)

        result = stats.to_dict()

        assert result['jobs_processed'] == 2
        assert result['jobs_succeeded'] == 1
        assert result['jobs_failed'] == 1
        assert result['jobs_to_dlq'] == 1
        assert result['total_processing_time'] == pytest.approx(0.8, rel=1e-6)
        assert result['errors_by_type'] == {'TestError': 1}
        assert result['high_confidence_matches'] == 0
        assert result['low_confidence_matches'] == 1

    def test_to_dict_json_serializable(self, stats):
        """to_dict returns JSON-serializable dict."""
        stats.record_success(0.5)
        stats.record_failure('Error', 0.3)

        result = stats.to_dict()

        # Should not raise
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_to_dict_empty_stats(self, stats):
        """to_dict works on empty stats."""
        result = stats.to_dict()

        assert result['jobs_processed'] == 0
        assert result['jobs_succeeded'] == 0
        assert result['jobs_failed'] == 0
        assert result['errors_by_type'] == {}


class TestSyncStatsSaveToFile:
    """Tests for save_to_file method."""

    def test_save_to_file_creates_json_file(self, stats, stats_file):
        """save_to_file creates JSON file at specified path."""
        stats.record_success(0.5)

        stats.save_to_file(stats_file)

        assert os.path.exists(stats_file)

    def test_save_to_file_writes_valid_json(self, stats, stats_file):
        """save_to_file writes valid JSON."""
        stats.record_success(0.5)
        stats.save_to_file(stats_file)

        with open(stats_file, 'r') as f:
            data = json.load(f)

        assert data['jobs_processed'] == 1
        assert data['jobs_succeeded'] == 1

    def test_save_to_file_creates_parent_directories(self, tmp_path):
        """save_to_file creates parent directories if needed."""
        from worker.stats import SyncStats

        nested_path = str(tmp_path / "nested" / "dir" / "stats.json")
        stats = SyncStats()
        stats.record_success(0.5)

        stats.save_to_file(nested_path)

        assert os.path.exists(nested_path)

    def test_save_to_file_merges_with_existing(self, stats, stats_file):
        """save_to_file merges cumulative totals with existing file."""
        # First save
        stats.record_success(1.0)
        stats.record_failure('Error1', 0.5)
        stats.save_to_file(stats_file)

        # Second save with new stats
        from worker.stats import SyncStats

        stats2 = SyncStats()
        stats2.record_success(2.0)
        stats2.record_failure('Error2', 0.3)
        stats2.save_to_file(stats_file)

        # Load and verify merged
        with open(stats_file, 'r') as f:
            data = json.load(f)

        assert data['jobs_processed'] == 4
        assert data['jobs_succeeded'] == 2
        assert data['jobs_failed'] == 2
        assert data['total_processing_time'] == pytest.approx(3.8, rel=1e-6)
        assert data['errors_by_type'] == {'Error1': 1, 'Error2': 1}

    def test_save_to_file_merges_error_types(self, stats, stats_file):
        """save_to_file correctly merges error type counts."""
        # First save
        stats.record_failure('PlexNotFound', 0.1)
        stats.record_failure('PlexNotFound', 0.2)
        stats.save_to_file(stats_file)

        # Second save with same and new error types
        from worker.stats import SyncStats

        stats2 = SyncStats()
        stats2.record_failure('PlexNotFound', 0.3)
        stats2.record_failure('PermanentError', 0.4)
        stats2.save_to_file(stats_file)

        with open(stats_file, 'r') as f:
            data = json.load(f)

        assert data['errors_by_type'] == {'PlexNotFound': 3, 'PermanentError': 1}

    def test_save_to_file_preserves_original_session_start(self, stats, stats_file):
        """save_to_file preserves original session_start from first save."""
        original_start = stats.session_start
        stats.record_success(0.5)
        stats.save_to_file(stats_file)

        # Wait and save again
        from worker.stats import SyncStats

        stats2 = SyncStats()  # Will have new session_start
        stats2.record_success(0.5)
        stats2.save_to_file(stats_file)

        with open(stats_file, 'r') as f:
            data = json.load(f)

        assert data['session_start'] == original_start

    def test_save_to_file_handles_corrupted_existing_file(self, stats, stats_file):
        """save_to_file handles corrupted existing file gracefully."""
        # Write invalid JSON
        with open(stats_file, 'w') as f:
            f.write("not valid json {{{")

        stats.record_success(0.5)
        stats.save_to_file(stats_file)

        # Should have written fresh stats
        with open(stats_file, 'r') as f:
            data = json.load(f)

        assert data['jobs_processed'] == 1


class TestSyncStatsLoadFromFile:
    """Tests for load_from_file classmethod."""

    def test_load_from_file_returns_stats(self, stats, stats_file):
        """load_from_file returns SyncStats instance."""
        from worker.stats import SyncStats

        stats.record_success(0.5)
        stats.save_to_file(stats_file)

        loaded = SyncStats.load_from_file(stats_file)

        assert isinstance(loaded, SyncStats)

    def test_load_from_file_returns_correct_values(self, stats, stats_file):
        """load_from_file returns stats with correct values."""
        from worker.stats import SyncStats

        stats.record_success(1.0, confidence='high')
        stats.record_success(0.5, confidence='low')
        stats.record_failure('TestError', 0.3, to_dlq=True)
        stats.save_to_file(stats_file)

        loaded = SyncStats.load_from_file(stats_file)

        assert loaded.jobs_processed == 3
        assert loaded.jobs_succeeded == 2
        assert loaded.jobs_failed == 1
        assert loaded.jobs_to_dlq == 1
        assert loaded.total_processing_time == pytest.approx(1.8, rel=1e-6)
        assert loaded.high_confidence_matches == 1
        assert loaded.low_confidence_matches == 1
        assert loaded.errors_by_type == {'TestError': 1}

    def test_load_from_file_missing_file_returns_empty_stats(self, tmp_path):
        """load_from_file returns empty stats when file doesn't exist."""
        from worker.stats import SyncStats

        missing_path = str(tmp_path / "nonexistent.json")

        loaded = SyncStats.load_from_file(missing_path)

        assert loaded.jobs_processed == 0
        assert loaded.jobs_succeeded == 0
        assert loaded.jobs_failed == 0
        assert loaded.errors_by_type == {}

    def test_load_from_file_corrupted_file_returns_empty_stats(self, tmp_path):
        """load_from_file returns empty stats when file is corrupted."""
        from worker.stats import SyncStats

        corrupted_path = str(tmp_path / "corrupted.json")
        with open(corrupted_path, 'w') as f:
            f.write("this is not json")

        loaded = SyncStats.load_from_file(corrupted_path)

        assert loaded.jobs_processed == 0
        assert loaded.errors_by_type == {}

    def test_load_from_file_partial_data_uses_defaults(self, tmp_path):
        """load_from_file uses defaults for missing fields."""
        from worker.stats import SyncStats

        partial_path = str(tmp_path / "partial.json")
        with open(partial_path, 'w') as f:
            json.dump({'jobs_processed': 10}, f)

        loaded = SyncStats.load_from_file(partial_path)

        assert loaded.jobs_processed == 10
        assert loaded.jobs_succeeded == 0  # Default
        assert loaded.errors_by_type == {}  # Default


class TestSyncStatsInitialization:
    """Tests for SyncStats initialization."""

    def test_default_values(self):
        """SyncStats initializes with correct default values."""
        from worker.stats import SyncStats

        stats = SyncStats()

        assert stats.jobs_processed == 0
        assert stats.jobs_succeeded == 0
        assert stats.jobs_failed == 0
        assert stats.jobs_to_dlq == 0
        assert stats.total_processing_time == 0.0
        assert stats.high_confidence_matches == 0
        assert stats.low_confidence_matches == 0
        assert stats.errors_by_type == {}

    def test_session_start_defaults_to_current_time(self):
        """SyncStats session_start defaults to current time."""
        from worker.stats import SyncStats

        before = time.time()
        stats = SyncStats()
        after = time.time()

        assert before <= stats.session_start <= after

    def test_errors_by_type_is_independent(self):
        """Each SyncStats instance has independent errors_by_type dict."""
        from worker.stats import SyncStats

        stats1 = SyncStats()
        stats2 = SyncStats()

        stats1.record_failure('Error1', 0.1)

        assert stats1.errors_by_type == {'Error1': 1}
        assert stats2.errors_by_type == {}
