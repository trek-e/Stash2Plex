# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Reliable sync — when metadata changes in Stash, it eventually reaches Plex — even if Plex was temporarily unavailable
**Current focus:** v2.0 Phase 23 — Foundation + Shared Library

## Current Position

Milestone: v2.0 Plex Metadata Provider
Phase: 23 of 27 (Foundation + Shared Library)
Plan: 03 (23-02 complete)
Status: In progress
Last activity: 2026-02-24 — 23-02 complete: StashClient async GraphQL client, StashScene model, INFR-01+INFR-02 satisfied

Progress: [██░░░░░░░░] ~12%

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

## Accumulated Context

### Decisions

Full decision log in PROJECT.md Key Decisions table.

Key decisions entering v2.0:
- FastAPI + uvicorn single worker (not gunicorn multi-worker — APScheduler runs N times with multi-worker)
- Docker build context must be repo root so shared_lib/ is COPY-able into provider image
- ratingKey format locked as integer scene ID only — never embed file paths (Plex URL routing silently breaks)
- host.docker.internal requires extra_hosts on Linux; add from day one in docker-compose.yml

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

Last session: 2026-02-24
Stopped at: 23-02 complete. StashClient async GraphQL client. 25 shared_lib TDD tests pass. INFR-01 + INFR-02 satisfied.
Resume file: None
Next step: Execute 23-03 (if exists) or advance to Phase 24

---
*Last updated: 2026-02-24 after 23-02 completion*
