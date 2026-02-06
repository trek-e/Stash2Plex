"""
Unit tests for plex/client.py.

Tests the PlexClient wrapper including:
- Initialization and timeout configuration
- Lazy connection behavior
- Retry logic for network errors
- Exception translation
- Library section retrieval
"""

import pytest
from unittest.mock import MagicMock, patch

from plex.client import PlexClient, _get_retriable_exceptions
from plex.exceptions import PlexPermanentError, PlexTemporaryError, PlexNotFound


# =============================================================================
# Initialization Tests
# =============================================================================

class TestPlexClientInit:
    """Tests for PlexClient initialization."""

    def test_init_stores_connection_params(self):
        """Connection parameters are stored correctly."""
        client = PlexClient(
            url="http://192.168.1.100:32400",
            token="abc123xyz",
        )

        assert client._url == "http://192.168.1.100:32400"
        assert client._token == "abc123xyz"

    def test_default_timeouts(self):
        """Default timeout values are applied."""
        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        assert client._connect_timeout == 5.0
        assert client._read_timeout == 30.0

    def test_custom_timeouts(self):
        """Custom timeout values are stored."""
        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
            connect_timeout=10.0,
            read_timeout=60.0,
        )

        assert client._connect_timeout == 10.0
        assert client._read_timeout == 60.0

    def test_server_initially_none(self):
        """Server is not connected on initialization."""
        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        assert client._server is None


# =============================================================================
# Lazy Connection Tests
# =============================================================================

class TestPlexClientLazyConnection:
    """Tests for lazy connection behavior."""

    def test_server_property_connects_lazily(self, mocker):
        """Accessing .server triggers PlexServer connection."""
        mock_plex_server = MagicMock()
        mock_plex_server.friendlyName = "Test Server"

        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        # Server should be None before access
        assert client._server is None

        # Access server property
        server = client.server

        # Now it should be connected
        mock_plex_server_class.assert_called_once()
        assert server == mock_plex_server

    def test_server_property_caches_connection(self, mocker):
        """Repeated .server access returns cached instance."""
        mock_plex_server = MagicMock()
        mock_plex_server.friendlyName = "Test Server"

        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        # Access server property twice
        server1 = client.server
        server2 = client.server

        # Should only connect once
        mock_plex_server_class.assert_called_once()
        assert server1 is server2

    def test_connection_passes_timeout(self, mocker):
        """Timeout parameter is passed to PlexServer."""
        mock_plex_server = MagicMock()
        mock_plex_server.friendlyName = "Test Server"

        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
            read_timeout=45.0,
        )

        _ = client.server

        call_kwargs = mock_plex_server_class.call_args[1]
        assert call_kwargs['baseurl'] == "http://localhost:32400"
        assert call_kwargs['token'] == "test-token"
        assert call_kwargs['timeout'] == 45.0
        assert 'session' in call_kwargs  # Connection pooling session


# =============================================================================
# Retry Behavior Tests
# =============================================================================

class TestPlexClientRetry:
    """Tests for retry behavior on network errors."""

    def test_retries_on_connection_error(self, mocker):
        """ConnectionError triggers retry attempts."""
        mock_plex_server = MagicMock()
        mock_plex_server.friendlyName = "Test Server"

        # First two calls raise ConnectionError, third succeeds
        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            side_effect=[
                ConnectionError("Connection refused"),
                ConnectionError("Connection refused"),
                mock_plex_server,
            ]
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        server = client.server

        assert mock_plex_server_class.call_count == 3
        assert server == mock_plex_server

    def test_retries_on_timeout(self, mocker):
        """TimeoutError triggers retry attempts."""
        mock_plex_server = MagicMock()
        mock_plex_server.friendlyName = "Test Server"

        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            side_effect=[
                TimeoutError("Request timed out"),
                mock_plex_server,
            ]
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        server = client.server

        assert mock_plex_server_class.call_count == 2
        assert server == mock_plex_server

    def test_retries_on_os_error(self, mocker):
        """OSError (network unreachable) triggers retry attempts."""
        mock_plex_server = MagicMock()
        mock_plex_server.friendlyName = "Test Server"

        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            side_effect=[
                OSError("Network unreachable"),
                mock_plex_server,
            ]
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        server = client.server

        assert mock_plex_server_class.call_count == 2
        assert server == mock_plex_server

    def test_no_retry_on_auth_error(self, mocker):
        """Unauthorized errors are not retried."""
        from plexapi.exceptions import Unauthorized

        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            side_effect=Unauthorized("Invalid token")
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="invalid-token",
        )

        with pytest.raises(PlexPermanentError) as exc_info:
            _ = client.server

        # Should only try once, no retry
        mock_plex_server_class.assert_called_once()
        assert "Authentication failed" in str(exc_info.value)

    def test_max_retries_exhausted(self, mocker):
        """After max retries, raises the error."""
        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            side_effect=ConnectionError("Connection refused")
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        with pytest.raises(ConnectionError):
            _ = client.server

        # 3 attempts (initial + 2 retries)
        assert mock_plex_server_class.call_count == 3

    def test_retries_on_requests_connection_error(self, mocker):
        """requests.exceptions.ConnectionError triggers retry."""
        import requests.exceptions

        mock_plex_server = MagicMock()
        mock_plex_server.friendlyName = "Test Server"

        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            side_effect=[
                requests.exceptions.ConnectionError("Failed to connect"),
                mock_plex_server,
            ]
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        server = client.server

        assert mock_plex_server_class.call_count == 2
        assert server == mock_plex_server

    def test_retries_on_requests_timeout(self, mocker):
        """requests.exceptions.Timeout triggers retry."""
        import requests.exceptions

        mock_plex_server = MagicMock()
        mock_plex_server.friendlyName = "Test Server"

        mock_plex_server_class = mocker.patch(
            'plexapi.server.PlexServer',
            side_effect=[
                requests.exceptions.Timeout("Read timed out"),
                mock_plex_server,
            ]
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        server = client.server

        assert mock_plex_server_class.call_count == 2


# =============================================================================
# get_library Tests
# =============================================================================

class TestPlexClientGetLibrary:
    """Tests for get_library method."""

    def test_get_library_returns_section(self, mocker):
        """get_library returns library section by name."""
        mock_section = MagicMock()
        mock_section.title = "Movies"

        mock_plex_server = MagicMock()
        mock_plex_server.library.section.return_value = mock_section

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        library = client.get_library("Movies")

        mock_plex_server.library.section.assert_called_once_with("Movies")
        assert library == mock_section

    def test_get_library_translates_not_found(self, mocker):
        """Non-existent section raises PlexNotFound."""
        from plexapi.exceptions import NotFound

        mock_plex_server = MagicMock()
        mock_plex_server.library.section.side_effect = NotFound("Section not found")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        with pytest.raises(PlexNotFound) as exc_info:
            client.get_library("NonExistent")

        assert "not found" in str(exc_info.value).lower()


# =============================================================================
# Exception Translation Tests
# =============================================================================

class TestPlexClientExceptionTranslation:
    """Tests for exception translation in client operations."""

    def test_connection_error_becomes_temporary(self, mocker):
        """ConnectionError on library access becomes PlexTemporaryError."""
        mock_plex_server = MagicMock()
        mock_plex_server.library.section.side_effect = ConnectionError("Network error")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        with pytest.raises(PlexTemporaryError):
            client.get_library("Movies")

    def test_auth_error_becomes_permanent(self, mocker):
        """Unauthorized on library access becomes PlexPermanentError."""
        from plexapi.exceptions import Unauthorized

        mock_plex_server = MagicMock()
        mock_plex_server.library.section.side_effect = Unauthorized("Bad token")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        with pytest.raises(PlexPermanentError):
            client.get_library("Movies")


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestRetrieableExceptions:
    """Tests for _get_retriable_exceptions helper."""

    def test_returns_tuple_of_exceptions(self):
        """Returns tuple of retriable exception types."""
        exceptions = _get_retriable_exceptions()

        assert isinstance(exceptions, tuple)
        assert ConnectionError in exceptions
        assert TimeoutError in exceptions
        assert OSError in exceptions

    def test_includes_requests_exceptions(self):
        """Includes requests library exceptions."""
        import requests.exceptions

        exceptions = _get_retriable_exceptions()

        assert requests.exceptions.ConnectionError in exceptions
        assert requests.exceptions.Timeout in exceptions

    def test_class_method_caches_result(self, mocker):
        """PlexClient._get_retriable_exceptions caches result."""
        # Reset the class cache
        PlexClient._retriable_exceptions = None

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        result1 = client._get_retriable_exceptions()
        result2 = client._get_retriable_exceptions()

        # Should return same cached tuple
        assert result1 is result2
