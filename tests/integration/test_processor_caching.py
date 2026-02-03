"""
Tests for cache integration in SyncWorker processor.

Verifies:
- Cache initialization when data_dir is provided
- No caching when data_dir is None
- Cache stats logging
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.integration
class TestSyncWorkerCacheInitialization:
    """Tests for SyncWorker cache initialization."""

    def test_caches_none_when_data_dir_none(self, mock_queue, mock_dlq, integration_config):
        """Caches are None when data_dir is not provided."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=None,
        )

        assert worker._library_cache is None
        assert worker._match_cache is None

    def test_caches_none_before_first_job(
        self, mock_queue, mock_dlq, integration_config, tmp_path
    ):
        """Caches are lazily initialized on first _get_caches() call."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=str(tmp_path),
        )

        # Before any processing, caches are None
        assert worker._library_cache is None
        assert worker._match_cache is None

    def test_get_caches_returns_none_tuple_without_data_dir(
        self, mock_queue, mock_dlq, integration_config
    ):
        """_get_caches() returns (None, None) when data_dir is None."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=None,
        )

        lib_cache, match_cache = worker._get_caches()

        assert lib_cache is None
        assert match_cache is None

    def test_get_caches_creates_caches_with_data_dir(
        self, mock_queue, mock_dlq, integration_config, tmp_path
    ):
        """_get_caches() creates cache instances when data_dir is set."""
        from worker.processor import SyncWorker
        from plex.cache import PlexCache, MatchCache

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=str(tmp_path),
        )

        lib_cache, match_cache = worker._get_caches()

        assert lib_cache is not None
        assert match_cache is not None
        assert isinstance(lib_cache, PlexCache)
        assert isinstance(match_cache, MatchCache)

    def test_get_caches_returns_same_instances(
        self, mock_queue, mock_dlq, integration_config, tmp_path
    ):
        """_get_caches() returns same cache instances on subsequent calls."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=str(tmp_path),
        )

        lib_cache1, match_cache1 = worker._get_caches()
        lib_cache2, match_cache2 = worker._get_caches()

        assert lib_cache1 is lib_cache2
        assert match_cache1 is match_cache2


@pytest.mark.integration
class TestSyncWorkerCacheStatsLogging:
    """Tests for cache stats logging."""

    def test_log_cache_stats_no_crash_without_caches(
        self, mock_queue, mock_dlq, integration_config, caplog
    ):
        """_log_cache_stats() works when caches are None."""
        from worker.processor import SyncWorker
        import logging

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=None,
        )

        # Should not raise
        worker._log_cache_stats()

    def test_log_cache_stats_no_crash_with_empty_caches(
        self, mock_queue, mock_dlq, integration_config, tmp_path, caplog
    ):
        """_log_cache_stats() works when caches have no hits/misses."""
        from worker.processor import SyncWorker
        import logging

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=str(tmp_path),
        )

        # Initialize caches (no activity yet)
        worker._get_caches()

        # Should not raise, should not log anything (0 total)
        worker._log_cache_stats()

    def test_log_cache_stats_logs_hit_rate(
        self, mock_queue, mock_dlq, integration_config, tmp_path, capsys
    ):
        """_log_cache_stats() logs hit rate when caches have activity."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=str(tmp_path),
        )

        lib_cache, match_cache = worker._get_caches()

        # Simulate some cache activity
        match_cache._hits = 8
        match_cache._misses = 2

        worker._log_cache_stats()

        captured = capsys.readouterr()
        assert "Match cache" in captured.err
        assert "80.0%" in captured.err
        assert "8 hits" in captured.err
        assert "2 misses" in captured.err


@pytest.mark.integration
class TestSyncWorkerCacheUsage:
    """Tests for cache usage in job processing."""

    def test_process_job_passes_caches_to_matcher(
        self, integration_worker, sample_sync_job
    ):
        """_process_job() passes caches to find_plex_items_with_confidence."""
        worker, mock_plex_item = integration_worker

        # Ensure mock_plex_item has file matching sample_sync_job
        mock_part = MagicMock()
        mock_part.file = sample_sync_job['data']['path']
        mock_media = MagicMock()
        mock_media.parts = [mock_part]
        mock_plex_item.media = [mock_media]
        mock_plex_item.key = '/library/metadata/123'

        # Capture the call to find_plex_items_with_confidence
        # Patch at source location since it's a lazy import
        with patch('plex.matcher.find_plex_items_with_confidence') as mock_find:
            # Configure mock to return a match
            from plex.matcher import MatchConfidence
            mock_find.return_value = (
                MatchConfidence.HIGH,
                mock_plex_item,
                [mock_plex_item],
            )

            with patch('hooks.handlers.unmark_scene_pending'):
                worker._process_job(sample_sync_job)

            # Verify caches were passed
            mock_find.assert_called()
            call_kwargs = mock_find.call_args.kwargs
            assert 'library_cache' in call_kwargs
            assert 'match_cache' in call_kwargs

    def test_process_job_works_without_data_dir(
        self, mock_queue, mock_dlq, integration_config, sample_sync_job, mock_plex_item
    ):
        """_process_job() works when data_dir is None (no caching)."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=integration_config,
            data_dir=None,  # No caching
        )

        # Setup mock Plex client
        mock_part = MagicMock()
        mock_part.file = sample_sync_job['data']['path']
        mock_media = MagicMock()
        mock_media.parts = [mock_part]
        mock_plex_item.media = [mock_media]
        mock_plex_item.key = '/library/metadata/123'

        mock_section = MagicMock()
        mock_section.search.return_value = [mock_plex_item]
        mock_section.all.return_value = [mock_plex_item]
        mock_section.title = "Test Library"

        mock_client = MagicMock()
        mock_client.server.library.sections.return_value = [mock_section]
        worker._plex_client = mock_client

        # Should not crash
        # Patch at source location since it's a lazy import
        with patch('hooks.handlers.unmark_scene_pending'):
            with patch('plex.matcher.find_plex_items_with_confidence') as mock_find:
                from plex.matcher import MatchConfidence
                mock_find.return_value = (
                    MatchConfidence.HIGH,
                    mock_plex_item,
                    [mock_plex_item],
                )
                worker._process_job(sample_sync_job)

            # Verify caches were None
            call_kwargs = mock_find.call_args.kwargs
            assert call_kwargs.get('library_cache') is None
            assert call_kwargs.get('match_cache') is None
