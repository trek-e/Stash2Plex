---
phase: 24-provider-http-skeleton
plan: 01
subsystem: api
tags: [fastapi, pydantic-settings, python-json-logger, uvicorn, httpx, plex-protocol]

# Dependency graph
requires:
  - phase: 23-foundation-shared-library
    provides: shared_lib package (PathMapper, StashClient) — not yet imported in Phase 24 but provider package mirrors its path_rules structure
provides:
  - provider/ FastAPI application package with Plex Custom Metadata Provider HTTP protocol
  - ProviderSettings pydantic-settings class with S2P_ env prefix and YAML fallback
  - GET / manifest endpoint returning tv.plex.agents.stash2plex registration data
  - POST /library/metadata/matches stub endpoint (empty matches)
  - GET /library/metadata/{ratingKey} stub endpoint (empty metadata)
  - GET /health endpoint with status, version, uptime_seconds, stash_reachable, plex_registered
  - Structured JSON logging (ts/level/msg fields) via python-json-logger
affects: [25-match-endpoint, 26-metadata-endpoint, 24-02-docker]

# Tech tracking
tech-stack:
  added: [fastapi>=0.115.0, uvicorn>=0.30.0, pydantic-settings>=2.3.0, python-json-logger>=3.0.0, PyYAML>=6.0, httpx>=0.27.0]
  patterns: [pydantic-settings with env_prefix + YAML file source, FastAPI lifespan context manager, async httpx connectivity check, module-level lru_cache settings singleton]

key-files:
  created:
    - provider/__init__.py
    - provider/config.py
    - provider/logging_config.py
    - provider/models.py
    - provider/requirements.txt
    - provider/main.py
    - provider/routes/__init__.py
    - provider/routes/manifest.py
    - provider/routes/match.py
    - provider/routes/metadata.py
    - provider/routes/health.py
  modified: []

key-decisions:
  - "python-json-logger v4 (installed) uses pythonjsonlogger.json import path — same as v3 spec, compatible"
  - "get_settings() uses lru_cache(maxsize=1) for singleton; ValidationError caught to print named missing S2P_ vars and exit(1)"
  - "_check_stash_connectivity catches httpx.ConnectError + TimeoutException + generic Exception — warns but starts regardless"
  - "health endpoint reads stash_reachable from request.app.state set by lifespan — avoids global module state"
  - "docs_url=None, redoc_url=None on FastAPI app — machine-to-machine protocol, no UI needed"
  - "HTTP request logging via @app.middleware('http') using time.perf_counter for ms precision"

patterns-established:
  - "S2P_ env prefix pattern: all provider config vars use S2P_ prefix to avoid collisions"
  - "Startup pattern: lifespan loads config, configures logging, checks connectivity, logs banner — in that order"
  - "Plex protocol envelope pattern: all responses wrapped in {'MediaProvider': ...} or {'MediaContainer': ...}"
  - "Stub pattern: Phase 24 stubs return size=0, Metadata=[] — ready to be replaced in Phases 25-26"

requirements-completed: [PROV-01, INFR-04]

# Metrics
duration: 8min
completed: 2026-02-26
---

# Phase 24 Plan 01: Provider HTTP Skeleton Summary

**FastAPI provider package with Plex Custom Metadata Provider manifest, stub match/metadata endpoints, structured JSON logging, and pydantic-settings config with S2P_ env prefix**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-02-26T00:32:00Z
- **Completed:** 2026-02-26T00:40:23Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- Complete `provider/` Python package implementing the Plex Custom Metadata Provider HTTP protocol
- ProviderSettings with env-first precedence, YAML fallback at /config/provider.yml, and clear exit(1) error message for missing S2P_STASH_URL / S2P_STASH_API_KEY
- All four required routes passing FastAPI TestClient verification: GET /, POST /library/metadata/matches, GET /library/metadata/{ratingKey}, GET /health

## Task Commits

Each task was committed atomically:

1. **Task 1: Create provider package with config, logging, and models** - `232bf94` (feat)
2. **Task 2: Create FastAPI routes and main application with lifespan** - `eb219fa` (feat)

## Files Created/Modified

- `provider/__init__.py` - Package marker with `__version__ = "1.0.0"`
- `provider/config.py` - ProviderSettings pydantic-settings class, get_settings() lru_cache factory, friendly exit on missing config
- `provider/logging_config.py` - configure_logging() sets up JSON formatter with ts/level/msg field renames
- `provider/models.py` - MediaProviderResponse, MediaContainerResponse, MediaProviderType, MediaProviderFeature, MediaProviderScheme Pydantic models
- `provider/requirements.txt` - Pinned minimum versions for all provider dependencies
- `provider/main.py` - FastAPI app with lifespan, router mounts, Stash connectivity check, startup banner, HTTP request logging middleware
- `provider/routes/__init__.py` - Package marker
- `provider/routes/manifest.py` - GET / manifest with AGENT_ID = tv.plex.agents.stash2plex
- `provider/routes/match.py` - POST /library/metadata/matches stub returning empty MediaContainer
- `provider/routes/metadata.py` - GET /library/metadata/{ratingKey} stub returning empty MediaContainer
- `provider/routes/health.py` - GET /health with uptime_seconds, stash_reachable from app.state, plex_registered=False

## Decisions Made

- python-json-logger v4 (what pip installed) uses same `pythonjsonlogger.json` import path as v3 spec — fully compatible
- `get_settings()` uses `lru_cache(maxsize=1)` for a module-level singleton; `ValidationError` is caught to extract field names and print `S2P_FIELDNAME` style variable names before `sys.exit(1)`
- `_check_stash_connectivity` catches broad exceptions so a bad Stash URL never blocks startup — provider warns and starts anyway
- Health endpoint reads `stash_reachable` from `request.app.state` (set in lifespan) rather than a module global, avoiding state leakage between test runs
- `docs_url=None, redoc_url=None` — this is a machine-to-machine API, Swagger UI not needed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required (Docker packaging comes in Plan 02).

## Next Phase Readiness

- `provider/` package is fully importable and all routes return correct 200 responses with Plex protocol JSON envelopes
- Ready for Plan 02 Docker containerization (Dockerfile + docker-compose.yml)
- Phases 25-26 can replace match.py and metadata.py stub logic without touching the rest of the application

---
*Phase: 24-provider-http-skeleton*
*Completed: 2026-02-26*

## Self-Check: PASSED

All 11 created files found on disk. Both task commits (232bf94, eb219fa) verified in git log.
