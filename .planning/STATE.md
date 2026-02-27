# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Reliable sync — when metadata changes in Stash, it eventually reaches Plex — even if Plex was temporarily unavailable
**Current focus:** v2.0 Phase 24 — Provider HTTP Skeleton

## Current Position

Milestone: v2.0 Plex Metadata Provider
Phase: 24 of 27 (Provider HTTP Skeleton)
Plan: 03 (24-02 complete — phase 24 done)
Status: In progress
Last activity: 2026-02-26 — 24-02 complete: Docker infrastructure (Dockerfile, docker-compose.yml, .dockerignore) for provider containerization

Progress: [████░░░░░░] ~20%

## Performance Metrics

**v1.5 Summary (previous milestone):**
- 12 plans across 6 phases
- 51 commits, 13,660 lines added
- Average plan duration: ~3.7 minutes

**v2.0:**
| Phase | Plan | Duration | Tasks | Notes |
|-------|------|----------|-------|-------|
| 23 | 01 | 5 min | 2 | shared_lib + PathMapper |
| 23 | 02 | 3 min | 2 | StashClient async GraphQL client, 12 TDD tests |
| 24 | 01 | 8 min | 2 | FastAPI provider package with Plex manifest, stub routes, structured logging |
| 24 | 02 | 2 min | 2 | Docker infrastructure: Dockerfile, docker-compose.yml, .dockerignore |

## Accumulated Context

### Decisions

Full decision log in PROJECT.md Key Decisions table.

Key decisions entering v2.0:
- FastAPI + uvicorn single worker (not gunicorn multi-worker — APScheduler runs N times with multi-worker)
- Docker build context must be repo root so shared_lib/ is COPY-able into provider image
- ratingKey format locked as integer scene ID only — never embed file paths (Plex URL routing silently breaks)
- host.docker.internal requires extra_hosts on Linux; add from day one in docker-compose.yml

Key decisions from 24-01:
- python-json-logger v4 uses pythonjsonlogger.json import path — same as v3 spec, compatible
- get_settings() uses lru_cache(maxsize=1); ValidationError caught to print named S2P_FIELD vars and exit(1)
- Health endpoint reads stash_reachable from request.app.state (set in lifespan) — avoids global module state between test runs
- Plex protocol envelope pattern: all responses wrapped in MediaProvider or MediaContainer dicts
- docs_url=None, redoc_url=None — machine-to-machine protocol, no Swagger UI

Key decisions from 24-02:
- Build context is repo root (.) so both shared_lib/ and provider/ are COPY-able in one build invocation
- shared_lib/ COPY placed before provider/ — shared_lib changes less frequently, maximizes layer cache hits
- requirements.txt copied separately before application code — pip layer only rebuilds on dependency changes
- Exec-form CMD ["uvicorn", ...] not shell form — SIGTERM reaches uvicorn directly for lifespan graceful shutdown
- extra_hosts: host.docker.internal:host-gateway — Linux gets automatic host IP resolution (macOS already has it)
- curl installed in Dockerfile for healthcheck CMD compatibility

Key decisions from 23-01:
- stash_pattern is a re.sub replacement template (\1, \2), not a match regex — _template_to_match_pattern derives the stash match regex at init time
- plex_pattern is a match regex — _pattern_to_repl_template derives a replacement template for the reverse direction
- asyncio_mode = strict in pytest.ini (explicit @pytest.mark.asyncio required, does not affect existing sync tests)
- count=1 in re.sub() prevents multiple substitutions on paths with repeated segments
- [Phase 23]: str|int union for scene_id parameter — coerced to str(scene_id) before GraphQL variables, satisfying both plugin (int from hooks) and provider (str from API) call sites
- [Phase 23]: StashConnectionError covers both ConnectError and TimeoutException — both mean server unavailable from caller perspective
- [Phase 23]: find_scene_by_path returns None on no match (not raises) — symmetric with PathMapper.plex_to_stash returning None

### Pending Todos

None.

### Blockers/Concerns

- [Phase 25] Exact Match endpoint payload format (filename field) needs live Plex validation — design path mapping to degrade gracefully when filename is absent
- [Phase 25] Stash GraphQL field names for scene paths used in stash_client.py (files { path }, paths { screenshot preview }) need verification against live instance — FindScenesByPath EQUALS modifier especially
- [Phase 26] Image URL auth: whether Plex can fetch Stash images directly or provider must proxy needs testing
- [Phase 27] Genre array Plex bug (only first genre imported) is active as of February 2026 — monitor for fix

## Session Continuity

Last session: 2026-02-27
Stopped at: Resumed and reviewed status. No new work — ready for Phase 25.
Resume file: .planning/phases/24-provider-http-skeleton/.continue-here.md
Next step: Phase 25 — Match endpoint implementation (discuss or plan)

---
*Last updated: 2026-02-27*
