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
    """

    def test_exact_path_match(self):
        """Exact path match returns the item."""
        from plex.matcher import find_plex_item_by_path

        mock_library = Mock()
        mock_item = Mock()
        mock_library.search.return_value = [mock_item]

        result = find_plex_item_by_path(mock_library, '/media/movies/film.mp4')

        assert result == mock_item
        mock_library.search.assert_called_with(
            Media__Part__file='/media/movies/film.mp4'
        )

    def test_no_match_returns_none(self):
        """No matching item returns None."""
        from plex.matcher import find_plex_item_by_path

        mock_library = Mock()
        mock_library.search.return_value = []

        result = find_plex_item_by_path(mock_library, '/nonexistent/file.mp4')

        assert result is None

    def test_fallback_to_filename_match(self):
        """Falls back to filename match when exact path fails."""
        from plex.matcher import find_plex_item_by_path

        mock_library = Mock()
        mock_item = Mock()
        # First call (exact path) returns empty, second (filename) returns item
        mock_library.search.side_effect = [[], [mock_item]]

        result = find_plex_item_by_path(mock_library, '/different/path/movie.mp4')

        assert result == mock_item
        assert mock_library.search.call_count == 2

    def test_ambiguous_filename_returns_none(self):
        """Ambiguous filename match returns None instead of guessing."""
        from plex.matcher import find_plex_item_by_path

        mock_library = Mock()
        mock_item1 = Mock()
        mock_item2 = Mock()
        # Exact path returns empty, filename returns multiple
        mock_library.search.side_effect = [[], [mock_item1, mock_item2], []]

        result = find_plex_item_by_path(mock_library, '/path/common_name.mp4')

        # Should return None due to ambiguity
        assert result is None

    def test_path_prefix_mapping(self):
        """Path prefix mapping transforms Stash path to Plex path."""
        from plex.matcher import find_plex_item_by_path

        mock_library = Mock()
        mock_item = Mock()
        mock_library.search.return_value = [mock_item]

        result = find_plex_item_by_path(
            mock_library,
            '/stash/media/movies/film.mp4',
            plex_path_prefix='/plex/media',
            stash_path_prefix='/stash/media',
        )

        assert result == mock_item
        # Should search with transformed path
        mock_library.search.assert_called_with(
            Media__Part__file='/plex/media/movies/film.mp4'
        )


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
        """ConnectionError translates to PlexTemporaryError."""
        with patch.dict('sys.modules', self._setup_mocks()):
            from plex.exceptions import translate_plex_exception, PlexTemporaryError

            exc = ConnectionError("Connection refused")
            result = translate_plex_exception(exc)

            assert isinstance(result, PlexTemporaryError)
            assert "Connection error" in str(result)

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
            queue=Mock(),
            dlq=Mock(),
            config=self.mock_config,
        )

        # Mock the _get_plex_client method to avoid plexapi import
        mock_client = Mock()
        mock_section = Mock()
        mock_section.search.return_value = []  # No items found
        mock_client.server.library.sections.return_value = [mock_section]
        worker._get_plex_client = Mock(return_value=mock_client)

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

        worker = SyncWorker(
            queue=Mock(),
            dlq=Mock(),
            config=self.mock_config,
        )

        # Mock the _get_plex_client method
        mock_client = Mock()
        mock_item = Mock()
        mock_item.title = "Test Video"
        mock_section = Mock()
        mock_section.search.return_value = [mock_item]  # Item found
        mock_client.server.library.sections.return_value = [mock_section]
        worker._get_plex_client = Mock(return_value=mock_client)

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

        # Verify edit was called with correct fields
        mock_item.edit.assert_called_once()
        call_kwargs = mock_item.edit.call_args.kwargs
        assert call_kwargs.get('title.value') == 'New Title'
        assert call_kwargs.get('studio.value') == 'Test Studio'
        mock_item.reload.assert_called_once()

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
