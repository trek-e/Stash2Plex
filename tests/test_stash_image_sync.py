"""
Tests for issue #8: Stash image (poster/background) fetch reachability and
diagnosability.

Covers:
- resolve_stash_asset_url(): re-points a Stash-reported asset URL at the
  plugin's own known-good stash_url (scheme/host/port), preserving path,
  query and fragment.
- redact_url_credentials(): strips credential-bearing query parameters from
  a URL before it is written to a log line.
- _fetch_stash_image(): requests the rewritten URL, and names the attempted
  URL (redacted) in every failure log line.
- extract_config_from_input(): user-set stash_url/stash_api_key settings
  take precedence over values derived from server_connection, with blank
  settings treated as unset.
"""

import urllib.error
import pytest
from unittest.mock import Mock, MagicMock, patch


@pytest.fixture
def processor_worker(mock_queue, mock_dlq, mock_config, tmp_path, mock_queue_manager):
    """SyncWorker instance for exercising _fetch_stash_image directly."""
    from worker.processor import SyncWorker

    mock_config.plex_connect_timeout = 10.0
    mock_config.plex_read_timeout = 30.0
    mock_config.preserve_plex_edits = False
    mock_config.strict_matching = False
    mock_config.dlq_retention_days = 30
    mock_config.skip_not_found = False

    return SyncWorker(
        queue_manager=mock_queue_manager,
        dlq=mock_dlq,
        config=mock_config,
        data_dir=str(tmp_path),
    )


@pytest.fixture
def partial_worker(mock_queue, mock_dlq, mock_config, tmp_path, mock_queue_manager):
    """SyncWorker instance for exercising _upload_image directly."""
    from worker.processor import SyncWorker

    mock_config.plex_connect_timeout = 10.0
    mock_config.plex_read_timeout = 30.0
    mock_config.preserve_plex_edits = False
    mock_config.strict_matching = False
    mock_config.dlq_retention_days = 30

    return SyncWorker(
        queue_manager=mock_queue_manager,
        dlq=mock_dlq,
        config=mock_config,
        data_dir=str(tmp_path),
    )


# =============================================================================
# resolve_stash_asset_url()
# =============================================================================

class TestResolveStashAssetUrl:
    def test_rewrites_host_and_port_preserving_path_query_fragment(self):
        from worker.processor import resolve_stash_asset_url

        result = resolve_stash_asset_url(
            "http://stash-internal:9999/screenshot.jpg?t=123#frag",
            "http://192.168.1.5:8080",
        )

        assert result == "http://192.168.1.5:8080/screenshot.jpg?t=123#frag"

    def test_returns_unchanged_when_stash_url_none(self):
        from worker.processor import resolve_stash_asset_url

        url = "http://stash-internal:9999/screenshot.jpg"
        assert resolve_stash_asset_url(url, None) == url

    def test_returns_unchanged_when_stash_url_empty(self):
        from worker.processor import resolve_stash_asset_url

        url = "http://stash-internal:9999/screenshot.jpg"
        assert resolve_stash_asset_url(url, "") == url

    def test_joins_relative_asset_path_onto_stash_url(self):
        from worker.processor import resolve_stash_asset_url

        result = resolve_stash_asset_url("/screenshot.jpg", "http://192.168.1.5:9999")

        assert result == "http://192.168.1.5:9999/screenshot.jpg"

    def test_leaves_already_matching_host_alone(self):
        from worker.processor import resolve_stash_asset_url

        url = "http://192.168.1.5:9999/screenshot.jpg"
        result = resolve_stash_asset_url(url, "http://192.168.1.5:9999")

        assert result == url


# =============================================================================
# redact_url_credentials()
# =============================================================================

class TestRedactUrlCredentials:
    def test_redacts_apikey_query_param(self):
        from worker.processor import redact_url_credentials

        result = redact_url_credentials(
            "http://stash:9999/screenshot.jpg?apikey=SUPERSECRET"
        )

        assert "SUPERSECRET" not in result
        assert "apikey=" in result

    def test_leaves_url_without_credentials_unchanged(self):
        from worker.processor import redact_url_credentials

        url = "http://stash:9999/screenshot.jpg?t=123"
        assert redact_url_credentials(url) == url


# =============================================================================
# _fetch_stash_image() — regression + diagnosability
# =============================================================================

class TestFetchStashImageRewriteAndLogging:
    def test_fetch_requests_rewritten_url(self, processor_worker):
        """Core regression: the plugin must request the base URL it knows
        works, not the (possibly unreachable) URL Stash reported."""
        processor_worker.config.stash_url = "http://192.168.1.5:9999"

        mock_response = MagicMock()
        mock_response.read.return_value = b"image-bytes"
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            processor_worker._fetch_stash_image(
                "http://0.0.0.0:9999/screenshot.jpg?t=1"
            )

        req = mock_open.call_args[0][0]
        assert req.full_url == "http://192.168.1.5:9999/screenshot.jpg?t=1"

    def test_url_error_log_names_attempted_url(self, processor_worker, capsys):
        processor_worker.config.stash_url = None

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            processor_worker._fetch_stash_image("http://stash:9999/screenshot.jpg")

        captured = capsys.readouterr()
        assert "http://stash:9999/screenshot.jpg" in captured.err

    def test_generic_error_log_names_attempted_url(self, processor_worker, capsys):
        processor_worker.config.stash_url = None

        with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            processor_worker._fetch_stash_image("http://stash:9999/screenshot.jpg")

        captured = capsys.readouterr()
        assert "http://stash:9999/screenshot.jpg" in captured.err

    def test_upload_failure_log_names_attempted_url(self, partial_worker, capsys):
        mock_plex_item = MagicMock()
        mock_plex_item.uploadPoster.side_effect = Exception("Upload failed")
        partial_worker.config.stash_url = None
        partial_worker._fetch_stash_image = MagicMock(return_value=b"fake image data")

        result = Mock()
        result.add_success = Mock()
        result.add_warning = Mock()

        partial_worker._upload_image(
            mock_plex_item,
            "http://stash:9999/poster.jpg",
            mock_plex_item.uploadPoster,
            "poster",
            result,
            False,
        )

        captured = capsys.readouterr()
        assert "http://stash:9999/poster.jpg" in captured.err

    def test_apikey_query_param_redacted_in_failure_log(self, processor_worker, capsys):
        processor_worker.config.stash_url = None

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            processor_worker._fetch_stash_image(
                "http://stash:9999/screenshot.jpg?apikey=SUPERSECRET"
            )

        captured = capsys.readouterr()
        assert "SUPERSECRET" not in captured.err
        assert "http://stash:9999/screenshot.jpg" in captured.err


# =============================================================================
# extract_config_from_input() — user-set overrides
# =============================================================================

class TestConfigPrecedence:
    def test_user_stash_url_setting_beats_derived(self):
        from Stash2Plex import extract_config_from_input

        input_data = {
            "server_connection": {
                "Scheme": "http",
                "Host": "0.0.0.0",
                "Port": 9999,
            }
        }

        with patch(
            "Stash2Plex.fetch_plugin_settings_direct",
            return_value={"stash_url": "http://192.168.1.50:9999/"},
        ), patch("Stash2Plex.fetch_plugin_settings", return_value={}):
            result = extract_config_from_input(input_data, existing_stash=Mock())

        # Trailing slash normalized away.
        assert result["stash_url"] == "http://192.168.1.50:9999"

    def test_blank_stash_url_setting_does_not_override_derived(self):
        from Stash2Plex import extract_config_from_input

        input_data = {
            "server_connection": {
                "Scheme": "http",
                "Host": "192.168.1.50",
                "Port": 9999,
            }
        }

        with patch(
            "Stash2Plex.fetch_plugin_settings_direct",
            return_value={"stash_url": "   "},
        ), patch("Stash2Plex.fetch_plugin_settings", return_value={}):
            result = extract_config_from_input(input_data, existing_stash=Mock())

        assert result["stash_url"] == "http://192.168.1.50:9999"

    def test_blank_stash_url_setting_falls_back_to_normalised_derived(self):
        """A wildcard bind address is still normalised on the fallback path.

        The derived value comes from build_stash_base_url (issue #11), so a
        blank override falls back to the loopback-normalised URL, not the raw
        0.0.0.0 that Stash reported.
        """
        from Stash2Plex import extract_config_from_input

        input_data = {
            "server_connection": {
                "Scheme": "http",
                "Host": "0.0.0.0",
                "Port": 9999,
            }
        }

        with patch(
            "Stash2Plex.fetch_plugin_settings_direct",
            return_value={"stash_url": "   "},
        ), patch("Stash2Plex.fetch_plugin_settings", return_value={}):
            result = extract_config_from_input(input_data, existing_stash=Mock())

        assert result["stash_url"] == "http://127.0.0.1:9999"

    def test_user_stash_api_key_beats_derived_and_is_never_logged(self, capsys):
        from Stash2Plex import extract_config_from_input

        input_data = {
            "server_connection": {
                "Scheme": "http",
                "Host": "127.0.0.1",
                "Port": 9999,
                "ApiKey": "derived-key-secret",
            }
        }

        with patch(
            "Stash2Plex.fetch_plugin_settings_direct",
            return_value={"stash_api_key": "user-key-supersecret"},
        ), patch("Stash2Plex.fetch_plugin_settings", return_value={}):
            result = extract_config_from_input(input_data, existing_stash=Mock())

        assert result["stash_api_key"] == "user-key-supersecret"

        captured = capsys.readouterr()
        assert "user-key-supersecret" not in captured.out
        assert "user-key-supersecret" not in captured.err
        assert "derived-key-secret" not in captured.out
        assert "derived-key-secret" not in captured.err
