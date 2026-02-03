"""
Tests for error classification functions and partial sync result tracking.

Tests classify_http_error and classify_exception for correct routing
of errors to retry (TransientError) or DLQ (PermanentError).
Also tests FieldUpdateWarning and PartialSyncResult for granular error handling.
"""

import pytest
from unittest.mock import MagicMock

from validation.errors import (
    classify_http_error,
    classify_exception,
    FieldUpdateWarning,
    PartialSyncResult,
)
from worker.processor import TransientError, PermanentError


class TestClassifyHttpError:
    """Tests for classify_http_error function."""

    # =========================================================================
    # Transient (retry-able) codes
    # =========================================================================

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_transient_codes_return_transient_error(self, status_code):
        """Known transient status codes return TransientError."""
        result = classify_http_error(status_code)
        assert result is TransientError

    def test_429_rate_limit_is_transient(self):
        """429 Too Many Requests is transient (retry after backoff)."""
        assert classify_http_error(429) is TransientError

    def test_500_internal_server_error_is_transient(self):
        """500 Internal Server Error is transient."""
        assert classify_http_error(500) is TransientError

    def test_502_bad_gateway_is_transient(self):
        """502 Bad Gateway is transient."""
        assert classify_http_error(502) is TransientError

    def test_503_service_unavailable_is_transient(self):
        """503 Service Unavailable is transient."""
        assert classify_http_error(503) is TransientError

    def test_504_gateway_timeout_is_transient(self):
        """504 Gateway Timeout is transient."""
        assert classify_http_error(504) is TransientError

    # =========================================================================
    # Permanent (non-retry-able) codes
    # =========================================================================

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 405, 410, 422])
    def test_permanent_codes_return_permanent_error(self, status_code):
        """Known permanent status codes return PermanentError."""
        result = classify_http_error(status_code)
        assert result is PermanentError

    def test_400_bad_request_is_permanent(self):
        """400 Bad Request is permanent (data issue)."""
        assert classify_http_error(400) is PermanentError

    def test_401_unauthorized_is_permanent(self):
        """401 Unauthorized is permanent (auth config issue)."""
        assert classify_http_error(401) is PermanentError

    def test_403_forbidden_is_permanent(self):
        """403 Forbidden is permanent (permission issue)."""
        assert classify_http_error(403) is PermanentError

    def test_404_not_found_is_permanent(self):
        """404 Not Found is permanent (item doesn't exist)."""
        assert classify_http_error(404) is PermanentError

    def test_405_method_not_allowed_is_permanent(self):
        """405 Method Not Allowed is permanent (API misuse)."""
        assert classify_http_error(405) is PermanentError

    def test_410_gone_is_permanent(self):
        """410 Gone is permanent (item removed)."""
        assert classify_http_error(410) is PermanentError

    def test_422_unprocessable_is_permanent(self):
        """422 Unprocessable Entity is permanent (validation failure)."""
        assert classify_http_error(422) is PermanentError

    # =========================================================================
    # Unknown codes - default classification
    # =========================================================================

    @pytest.mark.parametrize("status_code", [418, 451, 499])
    def test_unknown_4xx_returns_permanent(self, status_code):
        """Unknown 4xx codes return PermanentError (client error)."""
        result = classify_http_error(status_code)
        assert result is PermanentError

    @pytest.mark.parametrize("status_code", [505, 511, 599])
    def test_unknown_5xx_returns_transient(self, status_code):
        """Unknown 5xx codes return TransientError (server error)."""
        result = classify_http_error(status_code)
        assert result is TransientError

    @pytest.mark.parametrize("status_code", [100, 200, 201, 301, 302])
    def test_unexpected_codes_return_transient(self, status_code):
        """Unexpected codes (1xx, 2xx, 3xx) return TransientError (safe fallback)."""
        result = classify_http_error(status_code)
        assert result is TransientError


class TestClassifyException:
    """Tests for classify_exception function."""

    # =========================================================================
    # Already classified exceptions
    # =========================================================================

    def test_already_transient_returns_transient(self):
        """TransientError input returns TransientError."""
        exc = TransientError("Already transient")
        result = classify_exception(exc)
        assert result is TransientError

    def test_already_permanent_returns_permanent(self):
        """PermanentError input returns PermanentError."""
        exc = PermanentError("Already permanent")
        result = classify_exception(exc)
        assert result is PermanentError

    # =========================================================================
    # Network errors - transient
    # =========================================================================

    def test_connection_error_is_transient(self):
        """ConnectionError is transient (network issue)."""
        exc = ConnectionError("Connection refused")
        result = classify_exception(exc)
        assert result is TransientError

    def test_timeout_error_is_transient(self):
        """TimeoutError is transient (network delay)."""
        exc = TimeoutError("Operation timed out")
        result = classify_exception(exc)
        assert result is TransientError

    def test_os_error_is_transient(self):
        """OSError is transient (system-level error)."""
        exc = OSError("Network is unreachable")
        result = classify_exception(exc)
        assert result is TransientError

    def test_connection_reset_error_is_transient(self):
        """ConnectionResetError (subclass of OSError) is transient."""
        exc = ConnectionResetError("Connection reset by peer")
        result = classify_exception(exc)
        assert result is TransientError

    def test_broken_pipe_error_is_transient(self):
        """BrokenPipeError (subclass of OSError) is transient."""
        exc = BrokenPipeError("Broken pipe")
        result = classify_exception(exc)
        assert result is TransientError

    # =========================================================================
    # Validation/data errors - permanent
    # =========================================================================

    def test_value_error_is_permanent(self):
        """ValueError is permanent (data validation issue)."""
        exc = ValueError("Invalid value")
        result = classify_exception(exc)
        assert result is PermanentError

    def test_type_error_is_permanent(self):
        """TypeError is permanent (type mismatch)."""
        exc = TypeError("Expected string")
        result = classify_exception(exc)
        assert result is PermanentError

    def test_key_error_is_permanent(self):
        """KeyError is permanent (missing data)."""
        exc = KeyError("missing_key")
        result = classify_exception(exc)
        assert result is PermanentError

    def test_attribute_error_is_permanent(self):
        """AttributeError is permanent (code/data issue)."""
        exc = AttributeError("No such attribute")
        result = classify_exception(exc)
        assert result is PermanentError

    # =========================================================================
    # Unknown exceptions - transient (safe fallback)
    # =========================================================================

    def test_unknown_exception_is_transient(self):
        """Unknown Exception type defaults to transient (safe fallback)."""
        exc = Exception("Unknown error")
        result = classify_exception(exc)
        assert result is TransientError

    def test_runtime_error_is_transient(self):
        """RuntimeError defaults to transient (unknown)."""
        exc = RuntimeError("Something went wrong")
        result = classify_exception(exc)
        assert result is TransientError

    # =========================================================================
    # HTTP response exceptions
    # =========================================================================

    def test_exception_with_response_uses_status_code(self):
        """Exception with response object uses classify_http_error."""
        # Create mock exception with response
        exc = Exception("HTTP error")
        exc.response = MagicMock()
        exc.response.status_code = 503

        result = classify_exception(exc)
        assert result is TransientError

    def test_exception_with_4xx_response_is_permanent(self):
        """Exception with 4xx response returns PermanentError."""
        exc = Exception("HTTP error")
        exc.response = MagicMock()
        exc.response.status_code = 404

        result = classify_exception(exc)
        assert result is PermanentError

    def test_exception_with_5xx_response_is_transient(self):
        """Exception with 5xx response returns TransientError."""
        exc = Exception("HTTP error")
        exc.response = MagicMock()
        exc.response.status_code = 500

        result = classify_exception(exc)
        assert result is TransientError

    def test_exception_with_none_response_is_transient(self):
        """Exception with response=None defaults to transient."""
        exc = Exception("HTTP error")
        exc.response = None

        result = classify_exception(exc)
        assert result is TransientError

    def test_exception_with_response_no_status_code_is_transient(self):
        """Exception with response but no status_code defaults to transient."""
        exc = Exception("HTTP error")
        exc.response = MagicMock(spec=[])  # No status_code attribute

        result = classify_exception(exc)
        assert result is TransientError


class TestClassifyHttpErrorLogging:
    """Tests for logging in classify_http_error."""

    def test_transient_code_logs_debug(self, mocker):
        """Transient codes log debug message."""
        mock_logger = mocker.patch("validation.errors.logger")
        classify_http_error(503)
        mock_logger.debug.assert_called_once()
        assert "503" in mock_logger.debug.call_args[0][0]
        assert "transient" in mock_logger.debug.call_args[0][0].lower()

    def test_permanent_code_logs_debug(self, mocker):
        """Permanent codes log debug message."""
        mock_logger = mocker.patch("validation.errors.logger")
        classify_http_error(404)
        mock_logger.debug.assert_called_once()
        assert "404" in mock_logger.debug.call_args[0][0]
        assert "permanent" in mock_logger.debug.call_args[0][0].lower()


class TestClassifyExceptionLogging:
    """Tests for logging in classify_exception."""

    def test_already_classified_logs_debug(self, mocker):
        """Already classified exception logs debug."""
        mock_logger = mocker.patch("validation.errors.logger")
        classify_exception(TransientError("test"))
        mock_logger.debug.assert_called_once()
        assert "TransientError" in mock_logger.debug.call_args[0][0]

    def test_network_error_logs_debug(self, mocker):
        """Network error classification logs debug."""
        mock_logger = mocker.patch("validation.errors.logger")
        classify_exception(ConnectionError("test"))
        mock_logger.debug.assert_called_once()
        assert "transient" in mock_logger.debug.call_args[0][0].lower()

    def test_validation_error_logs_debug(self, mocker):
        """Validation error classification logs debug."""
        mock_logger = mocker.patch("validation.errors.logger")
        classify_exception(ValueError("test"))
        mock_logger.debug.assert_called_once()
        assert "permanent" in mock_logger.debug.call_args[0][0].lower()


class TestFieldUpdateWarning:
    """Tests for FieldUpdateWarning dataclass."""

    def test_creation_with_all_fields(self):
        """FieldUpdateWarning stores all required fields."""
        warning = FieldUpdateWarning(
            field_name="performers",
            error_message="Connection timeout",
            error_type="TimeoutError"
        )
        assert warning.field_name == "performers"
        assert warning.error_message == "Connection timeout"
        assert warning.error_type == "TimeoutError"

    def test_str_representation(self):
        """FieldUpdateWarning __str__ returns field: message format."""
        warning = FieldUpdateWarning(
            field_name="poster",
            error_message="Upload failed",
            error_type="HTTPError"
        )
        assert str(warning) == "poster: Upload failed"

    def test_str_with_long_message(self):
        """FieldUpdateWarning __str__ includes full message."""
        long_msg = "A very long error message that explains what went wrong in detail"
        warning = FieldUpdateWarning(
            field_name="tags",
            error_message=long_msg,
            error_type="ValueError"
        )
        assert long_msg in str(warning)

    def test_equality(self):
        """Two FieldUpdateWarning with same values are equal."""
        w1 = FieldUpdateWarning("performers", "error", "TypeError")
        w2 = FieldUpdateWarning("performers", "error", "TypeError")
        assert w1 == w2

    def test_inequality(self):
        """Two FieldUpdateWarning with different values are not equal."""
        w1 = FieldUpdateWarning("performers", "error", "TypeError")
        w2 = FieldUpdateWarning("tags", "error", "TypeError")
        assert w1 != w2


class TestPartialSyncResult:
    """Tests for PartialSyncResult dataclass."""

    def test_default_values(self):
        """PartialSyncResult has sensible defaults."""
        result = PartialSyncResult()
        assert result.success is True
        assert result.warnings == []
        assert result.fields_updated == []

    def test_add_warning_creates_field_update_warning(self):
        """add_warning creates FieldUpdateWarning from exception."""
        result = PartialSyncResult()
        error = ValueError("Invalid data")

        result.add_warning("studio", error)

        assert len(result.warnings) == 1
        assert result.warnings[0].field_name == "studio"
        assert result.warnings[0].error_message == "Invalid data"
        assert result.warnings[0].error_type == "ValueError"

    def test_add_warning_multiple(self):
        """add_warning can be called multiple times."""
        result = PartialSyncResult()

        result.add_warning("performers", ValueError("error 1"))
        result.add_warning("tags", TypeError("error 2"))
        result.add_warning("poster", ConnectionError("error 3"))

        assert len(result.warnings) == 3
        assert result.warnings[0].field_name == "performers"
        assert result.warnings[1].field_name == "tags"
        assert result.warnings[2].field_name == "poster"

    def test_add_success_records_field(self):
        """add_success records field name in fields_updated."""
        result = PartialSyncResult()

        result.add_success("title")
        result.add_success("studio")

        assert "title" in result.fields_updated
        assert "studio" in result.fields_updated
        assert len(result.fields_updated) == 2

    def test_has_warnings_false_when_empty(self):
        """has_warnings is False with no warnings."""
        result = PartialSyncResult()
        assert result.has_warnings is False

    def test_has_warnings_true_with_warnings(self):
        """has_warnings is True when warnings exist."""
        result = PartialSyncResult()
        result.add_warning("performers", ValueError("error"))
        assert result.has_warnings is True

    def test_warning_summary_empty_when_no_warnings(self):
        """warning_summary returns empty string with no warnings."""
        result = PartialSyncResult()
        assert result.warning_summary == ""

    def test_warning_summary_single_warning(self):
        """warning_summary formats single warning correctly."""
        result = PartialSyncResult()
        result.add_warning("performers", ValueError("connection failed"))

        summary = result.warning_summary
        assert "1 warnings:" in summary
        assert "performers: connection failed" in summary

    def test_warning_summary_multiple_warnings(self):
        """warning_summary formats multiple warnings with semicolons."""
        result = PartialSyncResult()
        result.add_warning("performers", ValueError("error 1"))
        result.add_warning("tags", TypeError("error 2"))

        summary = result.warning_summary
        assert "2 warnings:" in summary
        assert "performers: error 1" in summary
        assert "tags: error 2" in summary
        assert "; " in summary  # Semicolon separator

    def test_success_can_be_set_false(self):
        """success can be explicitly set to False."""
        result = PartialSyncResult(success=False)
        assert result.success is False

    def test_mixed_success_and_warnings(self):
        """Result can have both successful fields and warnings."""
        result = PartialSyncResult()

        # Some fields succeed
        result.add_success("title")
        result.add_success("studio")

        # Some fields fail
        result.add_warning("performers", ValueError("error"))

        assert len(result.fields_updated) == 2
        assert len(result.warnings) == 1
        assert result.success is True  # Overall still success
        assert result.has_warnings is True

    def test_warning_from_exception_preserves_type(self):
        """add_warning preserves exception type name."""
        result = PartialSyncResult()

        class CustomError(Exception):
            pass

        result.add_warning("custom_field", CustomError("custom message"))

        assert result.warnings[0].error_type == "CustomError"
