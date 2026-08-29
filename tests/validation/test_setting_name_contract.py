"""
Regression tests for GitHub issue #7 — UI timeout settings had no effect.

Stash2Plex.yml declares the plugin settings that Stash renders in its UI and
persists. Those names are the plugin's public configuration contract. If a
declared setting does not map onto a Stash2PlexConfig field, pydantic's default
extra="ignore" drops it silently and the user's value is lost with no warning.
"""

import pytest
import yaml
from pathlib import Path

from validation.config import (
    Stash2PlexConfig,
    validate_config,
    accepted_setting_names,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Long enough to satisfy the plex_token length check; irrelevant to these tests.
VALID_TOKEN = "test-token-1234"


def declared_settings() -> set[str]:
    doc = yaml.safe_load((REPO_ROOT / "Stash2Plex.yml").read_text())
    return set((doc.get("settings") or {}).keys())


def base_config(**overrides) -> dict:
    cfg = {"plex_url": "http://localhost:32400", "plex_token": VALID_TOKEN}
    cfg.update(overrides)
    return cfg


class TestYamlSettingContract:
    """Every setting Stash shows the user must reach the config model."""

    def test_every_declared_setting_is_accepted_by_the_config_model(self):
        unreachable = declared_settings() - accepted_setting_names()
        assert unreachable == set(), (
            f"Stash2Plex.yml declares setting(s) {sorted(unreachable)} that "
            f"Stash2PlexConfig silently ignores, so the user's value is lost."
        )


class TestTimeoutSettingsFromStash:
    """The exact payload shape Stash hands the plugin must take effect."""

    def test_stash_facing_names_populate_the_timeout_fields(self):
        """The issue #7 reproduction: connect_timeout=15, read_timeout=120."""
        config, err = validate_config(base_config(connect_timeout=15, read_timeout=120))
        assert err is None
        assert config.plex_connect_timeout == 15.0
        assert config.plex_read_timeout == 120.0

    def test_internal_names_still_work(self):
        config, err = validate_config(
            base_config(plex_connect_timeout=12, plex_read_timeout=90)
        )
        assert err is None
        assert config.plex_connect_timeout == 12.0
        assert config.plex_read_timeout == 90.0

    def test_defaults_when_unset(self):
        config, err = validate_config(base_config())
        assert err is None
        assert config.plex_connect_timeout == 5.0
        assert config.plex_read_timeout == 30.0

    @pytest.mark.parametrize("raw,expected", [(15, 15.0), (15.5, 15.5), ("15", 15.0)])
    def test_accepts_the_numeric_shapes_stash_may_send(self, raw, expected):
        config, err = validate_config(base_config(connect_timeout=raw))
        assert err is None
        assert config.plex_connect_timeout == expected


class TestTimeoutClamping:
    """An out-of-range value must not take the whole plugin down."""

    def test_over_maximum_read_timeout_is_clamped_not_rejected(self):
        config, err = validate_config(base_config(read_timeout=300))
        assert err is None, "an out-of-range timeout must not break startup"
        assert config.plex_read_timeout == 120.0

    def test_under_minimum_connect_timeout_is_clamped_not_rejected(self):
        config, err = validate_config(base_config(connect_timeout=0))
        assert err is None
        assert config.plex_connect_timeout == 1.0

    def test_over_maximum_connect_timeout_is_clamped(self):
        config, err = validate_config(base_config(connect_timeout=999))
        assert err is None
        assert config.plex_connect_timeout == 30.0

    def test_non_numeric_timeout_falls_back_to_default(self):
        config, err = validate_config(base_config(read_timeout="not a number"))
        assert err is None
        assert config.plex_read_timeout == 30.0


class TestUnknownSettingWarning:
    """Silently dropping a setting is what hid this bug; say something."""

    def test_warns_naming_the_ignored_setting(self, monkeypatch):
        import validation.config as cfgmod

        warnings = []
        monkeypatch.setattr(cfgmod, "log_warn", lambda msg: warnings.append(msg))

        validate_config(base_config(totally_made_up_setting=1))

        assert any("totally_made_up_setting" in w for w in warnings)

    def test_does_not_warn_for_recognised_settings(self, monkeypatch):
        import validation.config as cfgmod

        warnings = []
        monkeypatch.setattr(cfgmod, "log_warn", lambda msg: warnings.append(msg))

        validate_config(base_config(connect_timeout=15, read_timeout=120))

        assert warnings == []


class TestAcceptedSettingNames:
    """Unit tests for the introspection seam the contract test relies on."""

    def test_includes_field_names(self):
        assert "plex_connect_timeout" in accepted_setting_names()
        assert "plex_url" in accepted_setting_names()

    def test_includes_aliases(self):
        assert "connect_timeout" in accepted_setting_names()
        assert "read_timeout" in accepted_setting_names()
