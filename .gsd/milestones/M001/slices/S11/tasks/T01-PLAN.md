# T01: 24-provider-http-skeleton 01

**Slice:** S11 — **Milestone:** M001

## Description

Create the FastAPI provider application with configuration, structured logging, Plex protocol routes (manifest + stubs), and health endpoint.

Purpose: Establish the complete Python application that implements the Plex Custom Metadata Provider HTTP protocol, with proper config management and observability. This is the application code that Plan 02 will containerize.

Output: A runnable `provider/` package with all routes, config, logging, and models — ready for Docker packaging.

## Must-Haves

- [ ] "GET / returns a valid MediaProvider manifest with identifier tv.plex.agents.stash2plex, type 1 (Movie), and Match + Metadata features"
- [ ] "POST /library/metadata/matches returns 200 with empty Metadata array (stub)"
- [ ] "GET /library/metadata/{ratingKey} returns 200 with empty Metadata array (stub)"
- [ ] "GET /health returns status, version, uptime_seconds, stash_reachable, and plex_registered fields"
- [ ] "ProviderSettings loads S2P_-prefixed env vars and optional YAML config with env-first precedence"
- [ ] "Missing S2P_STASH_URL or S2P_STASH_API_KEY causes a clear error message and exit"
- [ ] "Structured JSON logging is active with ts, level, msg fields"

## Files

- `provider/__init__.py`
- `provider/config.py`
- `provider/logging_config.py`
- `provider/models.py`
- `provider/main.py`
- `provider/routes/__init__.py`
- `provider/routes/manifest.py`
- `provider/routes/match.py`
- `provider/routes/metadata.py`
- `provider/routes/health.py`
- `provider/requirements.txt`
