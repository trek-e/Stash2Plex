"""
Integration tests for Plex components.

Tests PlexClient, matcher, exception translation, and SyncWorker integration
using mocked PlexAPI to avoid requiring a real Plex server.

Note: This project has a queue/ module that shadows Python's stdlib queue.
Tests must be carefully structured to avoid triggering plexapi imports that
would cascade to urllib3 which requires stdlib queue.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys


class TestMatcher(unittest.TestCase):
    """Test find_plex_item_by_path matching strategies.

    These tests work because plex.matcher only uses TYPE_CHECKING imports
    for plexapi types and doesn't trigger the full import chain.

    Note: The matcher now uses title search + filename verification, not
    the old Media__Part__file filter which didn't work reliably.
    """

    def _create_mock_item_with_file(self, filepath):
        """Create a mock Plex item with a file at the given path."""
        mock_item = MagicMock()
        mock_part = MagicMock()
        mock_part.file = filepath
        mock_media = MagicMock()
        mock_media.parts = [mock_part]
        mock_item.media = [mock_media]
        return mock_item

    def test_single_match_by_filename(self):
        """Single item matching filename returns that item."""
        from plex.matcher import find_plex_item_by_path

        mock_library = MagicMock()
        mock_item = self._create_mock_item_with_file('/media/movies/film.mp4')
        # Title search returns item that has matching filename
        mock_library.search.return_value = [mock_item]
        mock_library.all.return_value = [mock_item]

        result = find_plex_item_by_path(mock_library, '/media/movies/film.mp4')

        assert result == mock_item

    def test_no_match_returns_none(self):
        """No matching item returns None."""
        from plex.matcher import find_plex_item_by_path

        mock_library = MagicMock()
        mock_library.search.return_value = []
        mock_library.all.return_value = []

        result = find_plex_item_by_path(mock_library, '/nonexistent/file.mp4')

        assert result is None

    def test_fallback_to_all_scan_when_title_search_fails(self):
        """Falls back to library.all() when title search returns no matches."""
        from plex.matcher import find_plex_item_by_path

        mock_library = MagicMock()
        mock_item = self._create_mock_item_with_file('/different/path/movie.mp4')
        # Title search returns empty, all() returns item with matching filename
        mock_library.search.return_value = []
        mock_library.all.return_value = [mock_item]

        result = find_plex_item_by_path(mock_library, '/different/path/movie.mp4')

        assert result == mock_item

    def test_ambiguous_filename_returns_none(self):
        """Multiple items with same filename returns None (ambiguous)."""
        from plex.matcher import find_plex_item_by_path

        mock_library = MagicMock()
        mock_item1 = self._create_mock_item_with_file('/path1/common_name.mp4')
        mock_item2 = self._create_mock_item_with_file('/path2/common_name.mp4')
        # Title search returns multiple items with same filename
        mock_library.search.return_value = [mock_item1, mock_item2]
        mock_library.all.return_value = [mock_item1, mock_item2]

        result = find_plex_item_by_path(mock_library, '/path/common_name.mp4')

        # Should return None due to ambiguity
        assert result is None

    def test_path_prefix_params_accepted(self):
        """Path prefix parameters are accepted (for API compatibility)."""
        from plex.matcher import find_plex_item_by_path

        mock_library = MagicMock()
        mock_item = self._create_mock_item_with_file('/plex/media/movies/film.mp4')
        mock_library.search.return_value = [mock_item]
        mock_library.all.return_value = [mock_item]

        # Should not raise - parameters accepted for API compatibility
        result = find_plex_item_by_path(
            mock_library,
            '/stash/media/movies/film.mp4',
            plex_path_prefix='/plex/media',
            stash_path_prefix='/stash/media',
        )
        # Note: path prefixes are currently unused, matcher uses filename matching


class TestExceptionHierarchy(unittest.TestCase):
    """Test exception hierarchy without triggering plexapi imports.

    Tests the exception classes themselves (subclassing relationships)
    rather than the translate_plex_exception function which needs plexapi.
    """

    def test_plex_temporary_error_is_transient(self):
        """PlexTemporaryError subclasses TransientError."""
        from worker.processor import TransientError
        from plex.exceptions import PlexTemporaryError

        exc = PlexTemporaryError("test error")
        assert isinstance(exc, TransientError)

    def test_plex_permanent_error_is_permanent(self):
        """PlexPermanentError subclasses PermanentError."""
        from worker.processor import PermanentError
        from plex.exceptions import PlexPermanentError

        exc = PlexPermanentError("test error")
        assert isinstance(exc, PermanentError)

    def test_plex_not_found_is_transient(self):
        """PlexNotFound subclasses TransientError (item may appear after scan)."""
        from worker.processor import TransientError
        from plex.exceptions import PlexNotFound

        exc = PlexNotFound("item not found")
        assert isinstance(exc, TransientError)


class TestExceptionTranslation(unittest.TestCase):
    """Test translate_plex_exception without real plexapi imports.

    These tests mock the plexapi module before importing translate_plex_exception
    to avoid triggering urllib3's queue import.
    """

    def _setup_mocks(self):
        """Create properly typed mock modules for plexapi and requests."""
        # Create mock plexapi.exceptions with real exception types
        mock_plexapi_exceptions = type(sys)('plexapi.exceptions')
        mock_plexapi_exceptions.Unauthorized = type('Unauthorized', (Exception,), {})
        mock_plexapi_exceptions.NotFound = type('NotFound', (Exception,), {})
        mock_plexapi_exceptions.BadRequest = type('BadRequest', (Exception,), {})

        mock_plexapi = type(sys)('plexapi')
        mock_plexapi.exceptions = mock_plexapi_exceptions

        # Create mock requests.exceptions with real exception types
        mock_requests_exceptions = type(sys)('requests.exceptions')
        mock_requests_exceptions.ConnectionError = type('ConnectionError', (Exception,), {})
        mock_requests_exceptions.Timeout = type('Timeout', (Exception,), {})

        mock_requests = type(sys)('requests')
        mock_requests.exceptions = mock_requests_exceptions

        return {
            'plexapi': mock_plexapi,
            'plexapi.exceptions': mock_plexapi_exceptions,
            'requests': mock_requests,
            'requests.exceptions': mock_requests_exceptions,
        }

    def test_connection_error_becomes_temporary(self):
        """ConnectionError with server-down indicator -> PlexServerDown."""
        with patch.dict('sys.modules', self._setup_mocks()):
            from plex.exceptions import translate_plex_exception, PlexTemporaryError, PlexServerDown

            exc = ConnectionError("Connection refused")
            result = translate_plex_exception(exc)

            assert isinstance(result, PlexServerDown)
            assert isinstance(result, PlexTemporaryError)  # PlexServerDown is a subclass
            assert "server is down" in str(result).lower()

    def test_timeout_error_becomes_temporary(self):
        """TimeoutError translates to PlexTemporaryError."""
        with patch.dict('sys.modules', self._setup_mocks()):
            from plex.exceptions import translate_plex_exception, PlexTemporaryError

            exc = TimeoutError("Read timed out")
            result = translate_plex_exception(exc)

            assert isinstance(result, PlexTemporaryError)
            assert "Connection error" in str(result)

    def test_unknown_error_defaults_to_temporary(self):
        """Unknown errors default to PlexTemporaryError (safer)."""
        with patch.dict('sys.modules', self._setup_mocks()):
            from plex.exceptions import translate_plex_exception, PlexTemporaryError

            exc = RuntimeError("Something unexpected")
            result = translate_plex_exception(exc)

            assert isinstance(result, PlexTemporaryError)
            assert "Unknown Plex error" in str(result)


class TestSyncWorkerIntegration(unittest.TestCase):
    """Test SyncWorker._process_job with mocked PlexClient.

    These tests mock internal methods to avoid triggering plexapi imports.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.plex_url = 'http://localhost:32400'
        self.mock_config.plex_token = 'test_token_12345'
        self.mock_config.plex_connect_timeout = 5.0
        self.mock_config.plex_read_timeout = 30.0
        self.mock_config.plex_library = None  # Search all libraries
        self.mock_config.strict_matching = False

    def test_process_job_missing_path_raises_permanent(self):
        """Job without file path raises PermanentError."""
        from worker.processor import SyncWorker, PermanentError

        worker = SyncWorker(
            queue=Mock(),
            dlq=Mock(),
            config=self.mock_config,
        )

        job = {
            'scene_id': '123',
            'update_type': 'metadata',
            'data': {},  # Missing 'path'
        }

        with self.assertRaises(PermanentError) as ctx:
            worker._process_job(job)

        assert "missing file path" in str(ctx.exception)

    def test_process_job_calls_plex_client(self):
        """_process_job calls _get_plex_client and searches libraries."""
        from worker.processor import SyncWorker
        from plex.exceptions import PlexNotFound

        worker = SyncWorker(
            queue=MagicMock(),
            dlq=MagicMock(),
            config=self.mock_config,
        )

        # Mock the _get_plex_client method to avoid plexapi import
        mock_client = MagicMock()
        mock_section = MagicMock()
        mock_section.search.return_value = []  # No items found
        mock_section.all.return_value = []  # No items on full scan either
        mock_client.server.library.sections.return_value = [mock_section]
        worker._get_plex_client = MagicMock(return_value=mock_client)

        job = {
            'scene_id': '123',
            'update_type': 'metadata',
            'data': {'path': '/nonexistent/file.mp4'},
        }

        with self.assertRaises(PlexNotFound) as ctx:
            worker._process_job(job)

        # Verify the client was used
        worker._get_plex_client.assert_called_once()
        mock_client.server.library.sections.assert_called_once()
        assert "Could not find Plex item" in str(ctx.exception)

    def test_process_job_updates_metadata(self):
        """Job updates Plex item metadata successfully."""
        from worker.processor import SyncWorker

        # Ensure overwrite mode so existing title gets replaced
        self.mock_config.preserve_plex_edits = False

        worker = SyncWorker(
            queue=MagicMock(),
            dlq=MagicMock(),
            config=self.mock_config,
        )

        # Create mock item with proper file structure for matcher
        mock_item = MagicMock()
        mock_item.title = ""  # Empty so title can be set
        mock_item.key = "/library/metadata/123"
        mock_part = MagicMock()
        mock_part.file = "/media/movies/film.mp4"
        mock_media = MagicMock()
        mock_media.parts = [mock_part]
        mock_item.media = [mock_media]
        mock_item.actors = []
        mock_item.genres = []
        mock_item.collections = []

        mock_section = MagicMock()
        mock_section.search.return_value = [mock_item]
        mock_section.all.return_value = [mock_item]

        mock_client = MagicMock()
        mock_client.server.library.sections.return_value = [mock_section]
        worker._get_plex_client = MagicMock(return_value=mock_client)

        job = {
            'scene_id': '123',
            'update_type': 'metadata',
            'data': {
                'path': '/media/movies/film.mp4',
                'title': 'New Title',
                'studio': 'Test Studio',
            },
        }

        # Should not raise
        worker._process_job(job)

        # Verify edit was called (may be called twice: once for metadata, once for collections)
        assert mock_item.edit.call_count >= 1
        # Get the first call's kwargs (the metadata call)
        call_kwargs = mock_item.edit.call_args_list[0].kwargs
        assert call_kwargs.get('title.value') == 'New Title'
        assert call_kwargs.get('studio.value') == 'Test Studio'
        mock_item.reload.assert_called()

    def test_worker_init_accepts_config(self):
        """SyncWorker.__init__ accepts config parameter."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=Mock(),
            dlq=Mock(),
            config=self.mock_config,
        )

        assert worker.config == self.mock_config
        assert worker._plex_client is None  # Lazy init


class TestPlexClientStructure(unittest.TestCase):
    """Test PlexClient structure without triggering plexapi imports."""

    def test_client_has_lazy_init_attribute(self):
        """PlexClient initializes with None server (lazy init)."""
        # We can test the structure without triggering the actual connection
        import inspect
        from plex.client import PlexClient

        # Check __init__ signature
        sig = inspect.signature(PlexClient.__init__)
        params = list(sig.parameters.keys())
        assert 'url' in params
        assert 'token' in params
        assert 'connect_timeout' in params
        assert 'read_timeout' in params

    def test_client_has_server_property(self):
        """PlexClient has server property for lazy initialization."""
        from plex.client import PlexClient
        assert hasattr(PlexClient, 'server')
        # server should be a property
        assert isinstance(inspect.getattr_static(PlexClient, 'server'), property)


# Import inspect at module level for the last test
import inspect


if __name__ == '__main__':
    unittest.main()
