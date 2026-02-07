"""
Unit tests for plex/exceptions.py.

Tests the exception hierarchy and translate_plex_exception function:
- Exception class hierarchy (TransientError/PermanentError)
- PlexAPI exception translation
- Requests exception translation
- Python builtin exception translation
- HTTP status code handling
"""

import pytest
from unittest.mock import MagicMock

from plex.exceptions import (
    PlexTemporaryError,
    PlexPermanentError,
    PlexNotFound,
    translate_plex_exception,
)
from worker.processor import TransientError, PermanentError


# =============================================================================
# Exception Hierarchy Tests
# =============================================================================

class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_plex_temporary_error_is_transient(self):
        """PlexTemporaryError is a subclass of TransientError."""
        assert issubclass(PlexTemporaryError, TransientError)

    def test_plex_permanent_error_is_permanent(self):
        """PlexPermanentError is a subclass of PermanentError."""
        assert issubclass(PlexPermanentError, PermanentError)

    def test_plex_not_found_is_transient(self):
        """PlexNotFound is a subclass of TransientError."""
        assert issubclass(PlexNotFound, TransientError)

    def test_plex_temporary_error_instance(self):
        """PlexTemporaryError instance is TransientError instance."""
        error = PlexTemporaryError("Connection failed")
        assert isinstance(error, TransientError)

    def test_plex_permanent_error_instance(self):
        """PlexPermanentError instance is PermanentError instance."""
        error = PlexPermanentError("Invalid token")
        assert isinstance(error, PermanentError)

    def test_plex_not_found_instance(self):
        """PlexNotFound instance is TransientError instance."""
        error = PlexNotFound("Item not found")
        assert isinstance(error, TransientError)

    def test_exception_messages_preserved(self):
        """Exception messages are preserved correctly."""
        temp_error = PlexTemporaryError("Temp message")
        perm_error = PlexPermanentError("Perm message")
        not_found = PlexNotFound("Not found message")

        assert str(temp_error) == "Temp message"
        assert str(perm_error) == "Perm message"
        assert str(not_found) == "Not found message"


# =============================================================================
# PlexAPI Exception Translation Tests
# =============================================================================

class TestPlexAPIExceptionTranslation:
    """Tests for PlexAPI exception translation."""

    def test_unauthorized_becomes_permanent(self):
        """plexapi Unauthorized -> PlexPermanentError."""
        from plexapi.exceptions import Unauthorized

        original = Unauthorized("Invalid token")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexPermanentError)
        assert "Authentication failed" in str(result)

    def test_not_found_becomes_plex_not_found(self):
        """plexapi NotFound -> PlexNotFound."""
        from plexapi.exceptions import NotFound

        original = NotFound("Section not found")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexNotFound)
        assert "not found" in str(result).lower()

    def test_bad_request_becomes_permanent(self):
        """plexapi BadRequest -> PlexPermanentError."""
        from plexapi.exceptions import BadRequest

        original = BadRequest("Invalid parameter")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexPermanentError)
        assert "Bad request" in str(result)


# =============================================================================
# Requests Exception Translation Tests
# =============================================================================

class TestRequestsExceptionTranslation:
    """Tests for requests library exception translation."""

    def test_connection_error_becomes_temporary(self):
        """requests.ConnectionError with server-down indicator -> PlexServerDown."""
        import requests.exceptions
        from plex.exceptions import PlexServerDown

        original = requests.exceptions.ConnectionError("Connection refused")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexServerDown)
        assert isinstance(result, PlexTemporaryError)  # PlexServerDown is a subclass
        assert "server is down" in str(result).lower()

    def test_timeout_becomes_temporary(self):
        """requests.Timeout -> PlexTemporaryError."""
        import requests.exceptions

        original = requests.exceptions.Timeout("Read timed out")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "Timeout error" in str(result)


# =============================================================================
# Python Builtin Exception Translation Tests
# =============================================================================

class TestBuiltinExceptionTranslation:
    """Tests for Python builtin exception translation."""

    def test_builtin_connection_error(self):
        """ConnectionError -> PlexTemporaryError."""
        original = ConnectionError("Connection reset by peer")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "Connection error" in str(result)

    def test_builtin_timeout_error(self):
        """TimeoutError -> PlexTemporaryError."""
        original = TimeoutError("Operation timed out")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "Connection error" in str(result)

    def test_os_error(self):
        """OSError -> PlexTemporaryError."""
        original = OSError("Network unreachable")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "Connection error" in str(result)


# =============================================================================
# HTTP Status Code Translation Tests
# =============================================================================

class TestHTTPStatusCodeTranslation:
    """Tests for HTTP status code handling via response attribute."""

    def _create_exception_with_status(self, status_code):
        """Helper to create exception with response.status_code."""
        exc = Exception(f"HTTP {status_code}")
        exc.response = MagicMock()
        exc.response.status_code = status_code
        return exc

    def test_401_becomes_permanent(self):
        """status_code=401 -> PlexPermanentError."""
        original = self._create_exception_with_status(401)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexPermanentError)
        assert "401" in str(result)

    def test_404_becomes_not_found(self):
        """status_code=404 -> PlexNotFound."""
        original = self._create_exception_with_status(404)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexNotFound)
        assert "404" in str(result)

    def test_429_becomes_temporary(self):
        """status_code=429 (rate limit) -> PlexTemporaryError."""
        original = self._create_exception_with_status(429)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "429" in str(result)

    def test_500_becomes_temporary(self):
        """status_code=500 (server error) -> PlexTemporaryError."""
        original = self._create_exception_with_status(500)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "500" in str(result)

    def test_502_becomes_temporary(self):
        """status_code=502 (bad gateway) -> PlexTemporaryError."""
        original = self._create_exception_with_status(502)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "502" in str(result)

    def test_503_becomes_temporary(self):
        """status_code=503 (service unavailable) -> PlexTemporaryError."""
        original = self._create_exception_with_status(503)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "503" in str(result)

    def test_504_becomes_temporary(self):
        """status_code=504 (gateway timeout) -> PlexTemporaryError."""
        original = self._create_exception_with_status(504)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "504" in str(result)

    def test_400_becomes_permanent(self):
        """status_code=400 (bad request) -> PlexPermanentError."""
        original = self._create_exception_with_status(400)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexPermanentError)
        assert "400" in str(result)

    def test_403_becomes_permanent(self):
        """status_code=403 (forbidden) -> PlexPermanentError."""
        original = self._create_exception_with_status(403)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexPermanentError)
        assert "403" in str(result)

    @pytest.mark.parametrize("status,expected_type", [
        (401, PlexPermanentError),
        (404, PlexNotFound),
        (429, PlexTemporaryError),
        (500, PlexTemporaryError),
        (502, PlexTemporaryError),
        (503, PlexTemporaryError),
    ])
    def test_http_status_translation_parametrized(self, status, expected_type):
        """Parametrized test for HTTP status code translation."""
        original = self._create_exception_with_status(status)
        result = translate_plex_exception(original)

        assert isinstance(result, expected_type)


# =============================================================================
# Default Handling Tests
# =============================================================================

class TestDefaultHandling:
    """Tests for unknown/default exception handling."""

    def test_unknown_error_becomes_temporary(self):
        """Unknown exceptions default to PlexTemporaryError (safer)."""
        original = RuntimeError("Something unexpected")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)
        assert "Unknown Plex error" in str(result)

    def test_value_error_becomes_temporary(self):
        """ValueError defaults to PlexTemporaryError."""
        original = ValueError("Invalid value")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)

    def test_type_error_becomes_temporary(self):
        """TypeError defaults to PlexTemporaryError."""
        original = TypeError("Wrong type")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)

    def test_exception_without_response_attribute(self):
        """Exception without response attribute -> PlexTemporaryError."""
        original = Exception("Generic error")
        # No response attribute
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)

    def test_exception_with_none_response(self):
        """Exception with None response -> PlexTemporaryError."""
        original = Exception("Error with None response")
        original.response = None
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)

    def test_exception_with_response_no_status_code(self):
        """Exception with response but no status_code -> PlexTemporaryError."""
        original = Exception("Error with incomplete response")
        original.response = MagicMock(spec=[])  # No status_code attribute
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases in exception translation."""

    def test_preserves_original_message(self):
        """Original error message is included in translated exception."""
        original = ConnectionError("Very specific error message")
        result = translate_plex_exception(original)

        assert "Very specific error message" in str(result)

    def test_empty_error_message(self):
        """Handles empty error message gracefully."""
        original = Exception("")
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)

    def test_none_like_values(self):
        """Handles exceptions with None-like values."""
        original = Exception(None)
        result = translate_plex_exception(original)

        assert isinstance(result, PlexTemporaryError)

    def test_nested_exception(self):
        """Handles nested/chained exceptions."""
        inner = ConnectionError("Inner error")
        outer = Exception("Outer error")
        outer.__cause__ = inner

        result = translate_plex_exception(outer)

        # Outer exception is what's translated
        assert isinstance(result, PlexTemporaryError)
