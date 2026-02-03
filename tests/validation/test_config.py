"""
Tests for PlexSyncConfig Pydantic model and validate_config helper.

Tests validation rules for URL format, token length, range constraints,
boolean coercion, default values, and error handling.
"""

import pytest
from pydantic import ValidationError

from validation.config import PlexSyncConfig, validate_config


class TestPlexSyncConfig:
    """Tests for PlexSyncConfig Pydantic model."""

    # =========================================================================
    # Required field tests
    # =========================================================================

    def test_valid_config_with_required_fields(self, valid_config_dict):
        """Config with required fields is valid."""
        config = PlexSyncConfig(**valid_config_dict)
        assert config.plex_url == valid_config_dict["plex_url"]
        assert config.plex_token == valid_config_dict["plex_token"]

    def test_plex_url_required(self):
        """plex_url is required."""
        config, error = validate_config({"plex_token": "valid-token-here"})
        assert config is None
        assert "plex_url" in error

    def test_plex_token_required(self):
        """plex_token is required."""
        config, error = validate_config({"plex_url": "http://localhost:32400"})
        assert config is None
        assert "plex_token" in error

    # =========================================================================
    # URL validation tests
    # =========================================================================

    @pytest.mark.parametrize("invalid_url", [
        "ftp://server",
        "file:///path",
        "server.com",
        "localhost:32400",
    ])
    def test_plex_url_must_be_http(self, invalid_url):
        """plex_url must start with http:// or https://."""
        config, error = validate_config({
            "plex_url": invalid_url,
            "plex_token": "valid-token-here"
        })
        assert config is None
        assert "http" in error.lower() or "plex_url" in error.lower()

    def test_plex_url_http_accepted(self):
        """HTTP URL is accepted."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="valid-token-here"
        )
        assert config.plex_url == "http://localhost:32400"

    def test_plex_url_https_accepted(self):
        """HTTPS URL is accepted."""
        config = PlexSyncConfig(
            plex_url="https://plex.example.com",
            plex_token="valid-token-here"
        )
        assert config.plex_url == "https://plex.example.com"

    def test_plex_url_trailing_slash_removed(self):
        """Trailing slash is normalized from plex_url."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400/",
            plex_token="valid-token-here"
        )
        assert config.plex_url == "http://localhost:32400"
        assert not config.plex_url.endswith("/")

    def test_plex_url_multiple_trailing_slashes_removed(self):
        """Multiple trailing slashes are normalized."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400///",
            plex_token="valid-token-here"
        )
        assert not config.plex_url.endswith("/")

    # =========================================================================
    # Token validation tests
    # =========================================================================

    def test_plex_token_too_short_rejected(self):
        """Token shorter than 10 chars is rejected."""
        config, error = validate_config({
            "plex_url": "http://localhost:32400",
            "plex_token": "short"
        })
        assert config is None
        assert "token" in error.lower() or "short" in error.lower()

    def test_plex_token_min_length_accepted(self):
        """10 char token is accepted (minimum length)."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="1234567890"  # Exactly 10 chars
        )
        assert config.plex_token == "1234567890"

    def test_plex_token_long_accepted(self):
        """Long tokens are accepted."""
        long_token = "a" * 100
        config = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token=long_token
        )
        assert config.plex_token == long_token

    # =========================================================================
    # Range validation tests (use parametrize)
    # =========================================================================

    @pytest.mark.parametrize("retries,valid", [
        (1, True),
        (5, True),
        (20, True),
        (0, False),
        (21, False),
    ])
    def test_max_retries_range(self, retries, valid):
        """max_retries must be 1-20."""
        config_dict = {
            "plex_url": "http://localhost:32400",
            "plex_token": "valid-token-here",
            "max_retries": retries
        }
        config, error = validate_config(config_dict)
        assert (config is not None) == valid
        if valid:
            assert config.max_retries == retries
        else:
            assert "max_retries" in error

    @pytest.mark.parametrize("interval,valid", [
        (0.1, True),
        (1.0, True),
        (60.0, True),
        (0.05, False),
        (61.0, False),
    ])
    def test_poll_interval_range(self, interval, valid):
        """poll_interval must be 0.1-60.0."""
        config_dict = {
            "plex_url": "http://localhost:32400",
            "plex_token": "valid-token-here",
            "poll_interval": interval
        }
        config, error = validate_config(config_dict)
        assert (config is not None) == valid
        if valid:
            assert config.poll_interval == interval
        else:
            assert "poll_interval" in error

    @pytest.mark.parametrize("timeout,valid", [
        (1.0, True),
        (15.0, True),
        (30.0, True),
        (0.5, False),
        (31.0, False),
    ])
    def test_plex_connect_timeout_range(self, timeout, valid):
        """plex_connect_timeout must be 1.0-30.0."""
        config_dict = {
            "plex_url": "http://localhost:32400",
            "plex_token": "valid-token-here",
            "plex_connect_timeout": timeout
        }
        config, error = validate_config(config_dict)
        assert (config is not None) == valid
        if valid:
            assert config.plex_connect_timeout == timeout
        else:
            assert "plex_connect_timeout" in error

    @pytest.mark.parametrize("timeout,valid", [
        (5.0, True),
        (60.0, True),
        (120.0, True),
        (4.0, False),
        (121.0, False),
    ])
    def test_plex_read_timeout_range(self, timeout, valid):
        """plex_read_timeout must be 5.0-120.0."""
        config_dict = {
            "plex_url": "http://localhost:32400",
            "plex_token": "valid-token-here",
            "plex_read_timeout": timeout
        }
        config, error = validate_config(config_dict)
        assert (config is not None) == valid
        if valid:
            assert config.plex_read_timeout == timeout
        else:
            assert "plex_read_timeout" in error

    @pytest.mark.parametrize("days,valid", [
        (1, True),
        (30, True),
        (365, True),
        (0, False),
        (366, False),
    ])
    def test_dlq_retention_days_range(self, days, valid):
        """dlq_retention_days must be 1-365."""
        config_dict = {
            "plex_url": "http://localhost:32400",
            "plex_token": "valid-token-here",
            "dlq_retention_days": days
        }
        config, error = validate_config(config_dict)
        assert (config is not None) == valid
        if valid:
            assert config.dlq_retention_days == days
        else:
            assert "dlq_retention_days" in error

    # =========================================================================
    # Boolean field tests
    # =========================================================================

    def test_strict_matching_accepts_bool_true(self):
        """strict_matching accepts True boolean."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="valid-token-here",
            strict_matching=True
        )
        assert config.strict_matching is True

    def test_strict_matching_accepts_bool_false(self):
        """strict_matching accepts False boolean."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="valid-token-here",
            strict_matching=False
        )
        assert config.strict_matching is False

    @pytest.mark.parametrize("string_value,expected", [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
    ])
    def test_strict_matching_accepts_string(self, string_value, expected):
        """strict_matching accepts string representations of booleans."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="valid-token-here",
            strict_matching=string_value
        )
        assert config.strict_matching == expected

    def test_preserve_plex_edits_accepts_bool(self):
        """preserve_plex_edits accepts boolean values."""
        config_true = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="valid-token-here",
            preserve_plex_edits=True
        )
        assert config_true.preserve_plex_edits is True

        config_false = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="valid-token-here",
            preserve_plex_edits=False
        )
        assert config_false.preserve_plex_edits is False

    @pytest.mark.parametrize("string_value,expected", [
        ("true", True),
        ("yes", True),
        ("false", False),
        ("no", False),
    ])
    def test_preserve_plex_edits_accepts_string(self, string_value, expected):
        """preserve_plex_edits accepts string representations."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="valid-token-here",
            preserve_plex_edits=string_value
        )
        assert config.preserve_plex_edits == expected

    def test_invalid_boolean_rejected(self):
        """Invalid boolean string raises error."""
        with pytest.raises(ValidationError) as exc_info:
            PlexSyncConfig(
                plex_url="http://localhost:32400",
                plex_token="valid-token-here",
                strict_matching="maybe"
            )
        errors = exc_info.value.errors()
        assert any("strict_matching" in str(e.get("loc", [])) for e in errors)

    # =========================================================================
    # Default value tests
    # =========================================================================

    def test_defaults_applied(self):
        """Default values are applied when only required fields provided."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400",
            plex_token="valid-token-here"
        )
        # Check all defaults
        assert config.enabled is True
        assert config.max_retries == 5
        assert config.poll_interval == 1.0
        assert config.strict_mode is False
        assert config.plex_connect_timeout == 5.0
        assert config.plex_read_timeout == 30.0
        assert config.dlq_retention_days == 30
        assert config.plex_library is None
        assert config.strict_matching is True
        assert config.preserve_plex_edits is False
        assert config.stash_url is None
        assert config.stash_api_key is None
        assert config.stash_session_cookie is None


class TestValidateConfig:
    """Tests for validate_config helper function."""

    def test_validate_config_success(self, valid_config_dict):
        """Valid dict returns (config, None)."""
        config, error = validate_config(valid_config_dict)
        assert config is not None
        assert error is None
        assert isinstance(config, PlexSyncConfig)

    def test_validate_config_failure(self):
        """Invalid dict returns (None, error_string)."""
        config, error = validate_config({})
        assert config is None
        assert error is not None
        assert isinstance(error, str)

    def test_validate_config_multiple_errors(self):
        """Multiple validation issues are reported in error."""
        config, error = validate_config({
            "plex_url": "invalid",  # Bad URL
            "plex_token": "short",  # Too short
            "max_retries": 0  # Out of range
        })
        assert config is None
        assert error is not None
        # Error should contain multiple issues separated by semicolons
        # At minimum should mention the URL issue
        assert "plex_url" in error.lower() or "http" in error.lower()

    def test_validate_config_url_error_message(self):
        """URL validation error provides useful message."""
        config, error = validate_config({
            "plex_url": "not-a-url",
            "plex_token": "valid-token-here"
        })
        assert config is None
        assert "plex_url" in error.lower() or "http" in error.lower()

    def test_validate_config_token_error_message(self):
        """Token validation error provides useful message."""
        config, error = validate_config({
            "plex_url": "http://localhost:32400",
            "plex_token": "tiny"
        })
        assert config is None
        assert "token" in error.lower() or "plex_token" in error.lower()

    def test_validate_config_extra_fields_ignored(self):
        """Extra fields not in model are ignored."""
        config, error = validate_config({
            "plex_url": "http://localhost:32400",
            "plex_token": "valid-token-here",
            "unknown_field": "value"
        })
        assert config is not None
        assert error is None


class TestPlexSyncConfigLogConfig:
    """Tests for log_config method."""

    def test_log_config_masks_token(self, mocker, valid_config_dict):
        """log_config masks token in log output."""
        mock_log = mocker.patch("validation.config.log")
        config = PlexSyncConfig(**valid_config_dict)
        config.log_config()

        # Check that log.info was called
        mock_log.info.assert_called_once()

        # Get the log message
        log_message = mock_log.info.call_args[0][0]

        # Full token should not be in the message
        assert valid_config_dict["plex_token"] not in log_message

        # Should contain masked token (first 4 + **** + last 4)
        assert "****" in log_message
