"""
Unit tests for plex/health.py.

Tests the check_plex_health function including:
- Successful health check with latency measurement
- Connection errors returning (False, 0.0)
- Timeout errors returning (False, 0.0)
- Server errors (503) returning (False, 0.0)
- Custom timeout parameter passed through
"""

import pytest
from unittest.mock import MagicMock, patch
import time

from plex.health import check_plex_health
from plex.client import PlexClient


# =============================================================================
# Success Cases
# =============================================================================

class TestHealthCheckSuccess:
    """Tests for successful health check scenarios."""

    def test_successful_health_check_returns_true_with_latency(self, mocker):
        """Successful health check returns (True, latency_ms) where latency > 0."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.return_value = MagicMock()  # Identity response

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert healthy is True
        assert latency > 0.0
        assert isinstance(latency, float)
        mock_plex_server.query.assert_called_once_with('/identity', timeout=5.0)

    def test_health_check_measures_latency_accurately(self, mocker):
        """Health check latency measurement is accurate within reasonable bounds."""
        mock_plex_server = MagicMock()

        # Simulate 100ms response time
        def slow_query(*args, **kwargs):
            time.sleep(0.1)
            return MagicMock()

        mock_plex_server.query = slow_query

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert healthy is True
        # Should be around 100ms, allow for some variance
        assert 90.0 <= latency <= 150.0

    def test_health_check_with_custom_timeout(self, mocker):
        """Custom timeout parameter is passed to server.query."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.return_value = MagicMock()

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client, timeout=10.0)

        assert healthy is True
        assert latency > 0.0
        mock_plex_server.query.assert_called_once_with('/identity', timeout=10.0)


# =============================================================================
# Failure Cases
# =============================================================================

class TestHealthCheckFailures:
    """Tests for health check failure scenarios."""

    def test_connection_error_returns_false_zero(self, mocker):
        """ConnectionError returns (False, 0.0)."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.side_effect = ConnectionError("Connection refused")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert healthy is False
        assert latency == 0.0

    def test_timeout_error_returns_false_zero(self, mocker):
        """TimeoutError returns (False, 0.0)."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.side_effect = TimeoutError("Request timed out")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert healthy is False
        assert latency == 0.0

    def test_requests_timeout_returns_false_zero(self, mocker):
        """requests.exceptions.Timeout returns (False, 0.0)."""
        import requests.exceptions

        mock_plex_server = MagicMock()
        mock_plex_server.query.side_effect = requests.exceptions.Timeout("Read timed out")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert healthy is False
        assert latency == 0.0

    def test_server_503_returns_false_zero(self, mocker):
        """Server 503 error (database loading) returns (False, 0.0)."""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        mock_exception = Exception("503 Server Error")
        mock_exception.response = mock_response

        mock_plex_server = MagicMock()
        mock_plex_server.query.side_effect = mock_exception

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert healthy is False
        assert latency == 0.0

    def test_generic_exception_returns_false_zero(self, mocker):
        """Any exception from server.query returns (False, 0.0)."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.side_effect = RuntimeError("Unexpected error")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert healthy is False
        assert latency == 0.0

    def test_os_error_returns_false_zero(self, mocker):
        """OSError (network unreachable) returns (False, 0.0)."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.side_effect = OSError("Network unreachable")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert healthy is False
        assert latency == 0.0


# =============================================================================
# Edge Cases
# =============================================================================

class TestHealthCheckEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_default_timeout_is_five_seconds(self, mocker):
        """Default timeout parameter is 5.0 seconds (not 30s like normal operations)."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.return_value = MagicMock()

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        check_plex_health(client)

        # Verify 5.0s timeout is used by default
        mock_plex_server.query.assert_called_once_with('/identity', timeout=5.0)

    def test_zero_latency_on_failure_not_negative(self, mocker):
        """Failure cases return exactly 0.0, never negative latency."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.side_effect = ConnectionError("Connection refused")

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        healthy, latency = check_plex_health(client)

        assert latency == 0.0
        assert latency >= 0.0  # Never negative

    def test_health_check_uses_identity_endpoint(self, mocker):
        """Health check uses /identity endpoint, not other endpoints."""
        mock_plex_server = MagicMock()
        mock_plex_server.query.return_value = MagicMock()

        mocker.patch(
            'plexapi.server.PlexServer',
            return_value=mock_plex_server
        )

        client = PlexClient(
            url="http://localhost:32400",
            token="test-token",
        )

        check_plex_health(client)

        # Verify /identity is called, not / or other endpoints
        call_args = mock_plex_server.query.call_args
        assert call_args[0][0] == '/identity'
