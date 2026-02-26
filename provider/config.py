"""Provider configuration using pydantic-settings with env var and YAML file support.

Env vars (S2P_ prefix) take precedence over YAML config file values.
Required: S2P_STASH_URL, S2P_STASH_API_KEY — missing either causes an immediate exit.
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pydantic
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

logger = logging.getLogger(__name__)

_YAML_CONFIG_PATH = "/config/provider.yml"

try:
    from pydantic_settings import YamlConfigSettingsSource as _YamlSource

    _yaml_available = True
except ImportError:
    _yaml_available = False


class ProviderSettings(BaseSettings):
    """Stash2Plex provider configuration.

    Precedence (highest to lowest):
    1. S2P_-prefixed environment variables
    2. YAML config file at /config/provider.yml
    3. Defaults defined below
    """

    model_config = SettingsConfigDict(
        env_prefix="S2P_",
        yaml_file=_YAML_CONFIG_PATH,
        yaml_file_encoding="utf-8",
    )

    # Required — no defaults; validation will fail and cause a clean exit
    stash_url: str
    stash_api_key: str

    # Optional with sensible defaults
    plex_url: str = "http://host.docker.internal:32400"
    plex_token: str = ""  # Empty = skip Plex registration
    provider_port: int = 9090
    log_level: str = "info"

    # Path mapping rules — populated from YAML config (not env-settable as a list)
    path_rules: list[dict[str, Any]] = []

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Return sources in priority order: env > YAML > init (defaults)."""
        if _yaml_available:
            try:
                yaml_source = _YamlSource(settings_cls)
                return (env_settings, yaml_source, init_settings)
            except Exception:
                # YAML source failed to initialise — fall through to env-only
                logger.debug("YAML config source unavailable; using env vars only")
        return (env_settings, init_settings)


@lru_cache(maxsize=1)
def get_settings() -> ProviderSettings:
    """Return the cached ProviderSettings instance.

    Exits with a helpful error message if required settings are missing.
    """
    try:
        return ProviderSettings()
    except pydantic.ValidationError as exc:
        missing: list[str] = []
        for error in exc.errors():
            if error.get("type") == "missing":
                loc = error.get("loc", ())
                if loc:
                    # Convert field name to env var name
                    field = str(loc[0])
                    missing.append(f"S2P_{field.upper()}")

        if missing:
            names = ", ".join(missing)
            print(
                f"\nMissing required configuration: {names}\n"
                f"Set these as environment variables or add them to {_YAML_CONFIG_PATH}\n"
                f"Example:\n"
                f"  export S2P_STASH_URL=http://localhost:9898\n"
                f"  export S2P_STASH_API_KEY=your-api-key\n",
                file=sys.stderr,
            )
        else:
            print(
                f"\nConfiguration error:\n{exc}\n",
                file=sys.stderr,
            )
        sys.exit(1)
    except FileNotFoundError:
        # YAML file not found — this should be handled by pydantic-settings silently,
        # but if it bubbles up, fall back to env-only
        logger.debug("YAML config file not found at %s; using env vars only", _YAML_CONFIG_PATH)
        try:
            # Try again without the YAML file by using env settings only
            settings = ProviderSettings.model_construct()
            # Re-raise to trigger proper error handling
            return ProviderSettings()
        except Exception:
            pass
        raise
