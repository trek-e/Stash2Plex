# Phase 24: Provider HTTP Skeleton - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

A running FastAPI Docker container that Plex can reach and register as a custom metadata agent (tv.plex.agents.stash2plex). No match/metadata logic yet — stub endpoints return empty valid responses. Phase delivers: Dockerfile, docker-compose.yml, FastAPI app with manifest/health/stub routes, YAML config with env var overrides, structured logging.

</domain>

<decisions>
## Implementation Decisions

### Docker deployment model
- Own docker-compose.yml at repo root (not inside provider/)
- Build context is repo root so shared_lib/ is COPY-able
- Bridge networking with extra_hosts for host.docker.internal on Linux
- Default port: 9090
- Local build only (no registry publishing for Phase 24)
- python:3.12-slim base image, single-stage Dockerfile
- restart: unless-stopped
- Target topology: same machine (Plex, Stash, provider all on one box)

### Configuration approach
- Environment variables with S2P_ prefix (S2P_STASH_URL, S2P_STASH_API_KEY, S2P_PLEX_URL, S2P_PLEX_TOKEN, S2P_LOG_LEVEL)
- Optional YAML config file mounted at /config/provider.yml — env vars override config file values
- Required to start: S2P_STASH_URL + S2P_STASH_API_KEY (fail fast with clear error if missing)
- Optional with defaults: PLEX_URL (http://host.docker.internal:32400), PLEX_TOKEN (empty — skip registration), PROVIDER_PORT (9090), LOG_LEVEL (info)
- Path mapping rules defined in the YAML config file as a list
- Validate Stash connectivity at startup — warn if unreachable but start anyway

### Plex agent registration
- Manual setup: user adds provider URL in Plex agent settings
- Agent identifier: tv.plex.agents.stash2plex
- Declare both Match + Metadata features from Phase 24 (endpoints stub until Phases 25-26)
- Stub /match returns 200 with empty matches array
- Stub /metadata returns 200 with null metadata

### Logging & health
- Structured JSON log format ({"ts":..., "level":..., "msg":..., ...})
- Default log level: info
- Log all incoming Plex requests at info level (path, timing)
- /health endpoint returns: status, version, stash reachability, plex registration state, uptime
- Startup banner showing version, port, connectivity status, path rule count
- Docker healthcheck in docker-compose.yml (curl /health, 30s interval)
- Version included in /health response (no separate endpoint)

### Claude's Discretion
- Media types to declare in manifest (likely Movie only based on Stash content model)
- Exact YAML config file schema structure
- FastAPI project structure within provider/
- Startup connectivity check implementation (timeout, retry)
- Exact JSON log field names and structure

</decisions>

<specifics>
## Specific Ideas

- Startup banner style: version + connection status summary with checkmarks (similar to the mockup discussed)
- Config validation error should name the missing variables and link to setup docs
- Path mapping rules in config should follow the same pattern/naming as shared_lib PathMapper (plex_pattern, stash_pattern, name)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 24-provider-http-skeleton*
*Context gathered: 2026-02-25*
