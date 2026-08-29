"""
Regression tests for GitHub issue #11 — Stash bound to a wildcard address.

When Stash listens on 0.0.0.0 (or ::), the `server_connection.Host` handed to
the plugin is that wildcard. A wildcard is a valid *bind* address but not a
valid *connect* address: on Windows connect() to 0.0.0.0 fails with
WinError 10049, so every plugin callback to the Stash API dies and all
UI-configured settings silently revert to defaults.
"""

import pytest
from unittest.mock import patch


class TestNormalizeStashHost:
    """Unit tests for the host-normalisation seam."""

    @pytest.mark.parametrize("wildcard,expected", [
        ("0.0.0.0", "127.0.0.1"),
        ("::", "::1"),
        ("[::]", "::1"),
        ("", "127.0.0.1"),
        (None, "127.0.0.1"),
    ])
    def test_wildcard_hosts_become_loopback(self, wildcard, expected):
        from Stash2Plex import normalize_stash_host
        assert normalize_stash_host(wildcard) == expected

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "192.168.1.50", "stash", "::1"])
    def test_routable_hosts_pass_through(self, host):
        from Stash2Plex import normalize_stash_host
        assert normalize_stash_host(host) == host


class TestBuildStashBaseUrl:
    """Unit tests for the shared base-URL builder."""

    def test_normalises_wildcard_host(self):
        from Stash2Plex import build_stash_base_url
        conn = {"Scheme": "http", "Host": "0.0.0.0", "Port": 9999}
        assert build_stash_base_url(conn) == "http://127.0.0.1:9999"

    def test_brackets_ipv6_literal(self):
        from Stash2Plex import build_stash_base_url
        conn = {"Scheme": "http", "Host": "::", "Port": 9999}
        assert build_stash_base_url(conn) == "http://[::1]:9999"

    def test_preserves_already_bracketed_ipv6(self):
        from Stash2Plex import build_stash_base_url
        conn = {"Scheme": "http", "Host": "[::1]", "Port": 9999}
        assert build_stash_base_url(conn) == "http://[::1]:9999"

    def test_defaults_when_keys_absent(self):
        from Stash2Plex import build_stash_base_url
        assert build_stash_base_url({}) == "http://127.0.0.1:9999"

    def test_accepts_lowercase_keys(self):
        from Stash2Plex import build_stash_base_url
        conn = {"scheme": "https", "host": "0.0.0.0", "port": 443}
        assert build_stash_base_url(conn) == "https://127.0.0.1:443"


class TestExtractConfigNormalisesHost:
    """extract_config_from_input must never hand a wildcard stash_url downstream."""

    def test_stash_url_uses_loopback_for_wildcard_host(self):
        from Stash2Plex import extract_config_from_input
        input_data = {
            "server_connection": {"Scheme": "http", "Host": "0.0.0.0", "Port": 9999}
        }
        with patch('Stash2Plex.fetch_plugin_settings_direct', return_value={}), \
             patch('Stash2Plex.get_stash_interface', return_value=None):
            config_dict = extract_config_from_input(input_data)
        assert config_dict['stash_url'] == "http://127.0.0.1:9999"

    def test_stash_url_preserved_for_routable_host(self):
        from Stash2Plex import extract_config_from_input
        input_data = {
            "server_connection": {"Scheme": "http", "Host": "192.168.1.50", "Port": 9999}
        }
        with patch('Stash2Plex.fetch_plugin_settings_direct', return_value={}), \
             patch('Stash2Plex.get_stash_interface', return_value=None):
            config_dict = extract_config_from_input(input_data)
        assert config_dict['stash_url'] == "http://192.168.1.50:9999"


class TestFetchPluginSettingsDirectNormalisesHost:
    """The direct GraphQL config fetch is the call that raised WinError 10049."""

    def test_graphql_url_uses_loopback_for_wildcard_host(self):
        from Stash2Plex import fetch_plugin_settings_direct
        captured = {}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"data":{"configuration":{"plugins":{"Stash2Plex":{}}}}}'

        def _fake_urlopen(req, timeout=None):
            captured['url'] = req.full_url
            return _Resp()

        with patch('urllib.request.urlopen', _fake_urlopen):
            fetch_plugin_settings_direct({"Scheme": "http", "Host": "0.0.0.0", "Port": 9999})

        assert captured['url'] == "http://127.0.0.1:9999/graphql"


class TestDirectStashInterfaceNormalisesHost:
    """The stdlib GraphQL client builds its own URL and needs the same fix."""

    def test_endpoint_uses_loopback_for_wildcard_host(self):
        from Stash2Plex import DirectStashInterface
        iface = DirectStashInterface({"Scheme": "http", "Host": "0.0.0.0", "Port": 9999})
        assert iface._url == "http://127.0.0.1:9999/graphql"

    def test_endpoint_preserved_for_routable_host(self):
        from Stash2Plex import DirectStashInterface
        iface = DirectStashInterface({"Scheme": "http", "Host": "stash", "Port": 9999})
        assert iface._url == "http://stash:9999/graphql"
