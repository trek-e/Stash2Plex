---
phase: 23-foundation-shared-library
plan: 02
subsystem: infra
tags: [shared_lib, pydantic, graphql, httpx, respx, async, tdd, stash-client]

# Dependency graph
requires:
  - phase: 23-01
    provides: shared_lib package, httpx/respx/pytest-asyncio installed, asyncio_mode=strict
provides:
  - StashClient async GraphQL client (find_scene_by_id, find_scene_by_path)
  - StashScene Pydantic model with flattened fields (studio_name, performer_names, tag_names, screenshot_url, preview_url)
  - StashFile Pydantic model
  - Custom exceptions: StashConnectionError, StashQueryError, StashSceneNotFound
  - Complete shared_lib public API via __init__.py (PathMapper + StashClient)
  - INFR-01 fully satisfied — both shared_lib modules importable
  - INFR-02 satisfied — async GraphQL client with typed returns
affects:
  - 24-provider (Docker COPY shared_lib/ into provider image — StashClient used by provider)
  - 25-matching (provider uses StashClient.find_scene_by_path for match requests; path filter needs live validation)
  - 26-plugin (plugin calls StashClient via asyncio.run() for scene data)

# Tech tracking
tech-stack:
  added: []  # httpx/respx/pytest-asyncio already installed in 23-01
  patterns:
    - httpx.AsyncClient with configurable timeout (total + connect separate)
    - Pydantic BaseModel for typed GraphQL response models with flattened nested fields
    - _parse_scene() module-level helper flattens raw GraphQL dict to StashScene
    - Custom exception hierarchy mirroring plex/exceptions.py pattern
    - respx.mock context manager for httpx mocking in async tests
    - str|int union type for scene_id — always coerced to str before GraphQL

key-files:
  created:
    - shared_lib/stash_client.py
    - tests/shared_lib/test_stash_client.py
  modified:
    - shared_lib/__init__.py

key-decisions:
  - "str|int union for scene_id parameter — coerced to str(scene_id) before GraphQL variables, satisfying both plugin (int from hooks) and provider (str from API) call sites"
  - "Timeout as separate connect vs total: httpx.Timeout(total, connect=5.0) — connect hardcoded at 5s, total configurable (default 10s)"
  - "StashConnectionError covers both ConnectError and TimeoutException — both mean 'server unavailable' from caller perspective"
  - "find_scene_by_path returns None on no match (not raises) — caller checks None, symmetric with PathMapper.plex_to_stash returning None"
  - "FindScenes path filter uses EQUALS modifier — needs live Stash validation in Phase 25 per STATE.md concern"

patterns-established:
  - "Pattern: flat Pydantic models from nested GraphQL — _parse_scene() helper centralizes flattening logic, models never have nested dicts"
  - "Pattern: async client with explicit close() — no context manager to keep plugin usage simple (asyncio.run per call or close after batch)"
  - "Pattern: _gql() private method handles all transport concerns (headers, errors, JSON parsing) — public methods only deal with domain logic"

requirements-completed: [INFR-01, INFR-02]

# Metrics
duration: 3min
completed: 2026-02-24
---

# Phase 23 Plan 02: Foundation + Shared Library — Stash Client Summary

**Async Stash GraphQL client with httpx and typed Pydantic models (StashScene, StashFile), 12-test TDD suite using respx mocks; shared_lib public API finalized**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-24T05:20:19Z
- **Completed:** 2026-02-24T05:22:29Z
- **Tasks:** 2 (Task 1 TDD RED+GREEN, Task 2 import verification)
- **Files modified:** 3

## Accomplishments

- Implemented `StashClient` with `find_scene_by_id` (str|int) and `find_scene_by_path` — both return typed Pydantic models
- `StashScene` model with five flattened nested fields: `studio_name`, `performer_names`, `tag_names`, `screenshot_url`, `preview_url`
- Custom exception hierarchy — `StashConnectionError`, `StashQueryError`, `StashSceneNotFound` — mirroring `plex/exceptions.py` pattern
- 12 TDD tests covering: success path, not found, int scene_id coercion, path found/not found, connection error, timeout error, GraphQL errors, API key header, missing optional fields, close(), URL trailing slash
- Updated `shared_lib/__init__.py` to expose complete public API — both `PathMapper`+`PathRule` and all `StashClient` exports
- INFR-01 and INFR-02 requirements fully satisfied

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Add failing tests for async Stash GraphQL client** - `0724694` (test)
2. **Task 1 GREEN: Implement async Stash GraphQL client** - `a235283` (feat)
3. **Task 2: Expose complete shared_lib public API in __init__.py** - `73c1367` (feat)

_Note: Refactor phase skipped — implementation was clean on first pass._

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `shared_lib/stash_client.py` — Async GraphQL client, StashScene/StashFile models, custom exceptions, GraphQL queries
- `tests/shared_lib/test_stash_client.py` — 12 async TDD tests with respx mocks
- `shared_lib/__init__.py` — Updated to expose full public API (PathMapper + StashClient symbols)

## Decisions Made

- `str|int` union type for `scene_id` — coerced to `str(scene_id)` before GraphQL variables. Plugin passes int from hooks; provider may pass str from API. One parameter handles both.
- `find_scene_by_path` returns `None` on no match (does not raise). Symmetric with `PathMapper.plex_to_stash` returning `None`. Callers check None, consistent API surface.
- `StashConnectionError` covers both `ConnectError` and `TimeoutException` — both mean the server is unavailable from the caller's perspective. No need for a separate `StashTimeoutError`.
- Path filter in `_FIND_SCENES_BY_PATH` uses `EQUALS` modifier. Added docstring noting this needs live Stash validation in Phase 25 (per existing STATE.md concern).
- Timeout configured as `httpx.Timeout(timeout, connect=5.0)` — connect hardcoded at 5 seconds, total timeout configurable (default 10 seconds). Prevents hanging on slow DNS/TCP.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. Implementation was straightforward. All 12 tests passed on first run of GREEN phase. respx mocking worked as expected with asyncio_mode=strict.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `shared_lib/stash_client.py` is complete and tested. Phase 24 (provider) and Phase 25 (matching) can import `StashClient` directly.
- `from shared_lib import StashClient, StashScene, PathMapper` works from repo root.
- `from shared_lib import StashClient, StashScene, PathMapper` works from Docker COPY of shared_lib/.
- Phase 25 live validation concern still applies: path filter EQUALS modifier needs testing against a real Stash instance before provider deployment.
- All 25 shared_lib tests pass (13 path_mapper + 12 stash_client).

## Self-Check: PASSED

Files verified:
- FOUND: shared_lib/stash_client.py
- FOUND: tests/shared_lib/test_stash_client.py
- FOUND: shared_lib/__init__.py (updated)
- FOUND: .planning/phases/23-foundation-shared-library/23-02-SUMMARY.md

Commits verified:
- FOUND: 0724694 (test: add failing tests for async Stash GraphQL client)
- FOUND: a235283 (feat: implement async Stash GraphQL client)
- FOUND: 73c1367 (feat: expose complete shared_lib public API in __init__.py)

---
*Phase: 23-foundation-shared-library*
*Completed: 2026-02-24*
