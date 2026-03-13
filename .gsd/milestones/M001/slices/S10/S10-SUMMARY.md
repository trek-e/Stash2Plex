---
id: S10
parent: M001
milestone: M001
provides:
  - shared_lib Python package at repo root (importable by plugin and provider)
  - PathRule Pydantic model: name, plex_pattern, stash_pattern, case_insensitive
  - PathMapper class with bidirectional plex_to_stash / stash_to_plex translation
  - from_env classmethod parses PATH_RULES JSON env var into validated rules
  - "_template_to_match_pattern: derives stash match regex from replacement template"
  - "_pattern_to_repl_template: derives replacement template from plex match regex"
  - httpx, pytest-asyncio, respx installed in venv (ready for Phase 23-02)
  - StashClient async GraphQL client (find_scene_by_id, find_scene_by_path)
  - StashScene Pydantic model with flattened fields (studio_name, performer_names, tag_names, screenshot_url, preview_url)
  - StashFile Pydantic model
  - Custom exceptions: StashConnectionError, StashQueryError, StashSceneNotFound
  - Complete shared_lib public API via __init__.py (PathMapper + StashClient)
  - INFR-01 fully satisfied — both shared_lib modules importable
  - INFR-02 satisfied — async GraphQL client with typed returns
requires: []
affects: []
key_files: []
key_decisions:
  - "stash_pattern is a re.sub replacement template (\\1, \\2), not a match regex — _template_to_match_pattern derives the stash match regex from it at init time"
  - "plex_pattern is a match regex (^/plex/(.*)}) — _pattern_to_repl_template derives the stash-to-plex replacement template from it at init time"
  - "asyncio_mode = strict chosen over auto to avoid side effects on 22+ existing sync tests"
  - "count=1 in re.sub() prevents multiple substitutions on paths with repeated segments (Pitfall 2 from research)"
  - "str|int union for scene_id parameter — coerced to str(scene_id) before GraphQL variables, satisfying both plugin (int from hooks) and provider (str from API) call sites"
  - "Timeout as separate connect vs total: httpx.Timeout(total, connect=5.0) — connect hardcoded at 5s, total configurable (default 10s)"
  - "StashConnectionError covers both ConnectError and TimeoutException — both mean 'server unavailable' from caller perspective"
  - "find_scene_by_path returns None on no match (not raises) — caller checks None, symmetric with PathMapper.plex_to_stash returning None"
  - "FindScenes path filter uses EQUALS modifier — needs live Stash validation in Phase 25 per STATE.md concern"
patterns_established:
  - "Pattern: bidirectional mapping via template/pattern derivation — one rule, two directions, no duplicate config"
  - "Pattern: pre-compile-at-init for regex engines — PathMapper.__init__ compiles all regex patterns once"
  - "Pattern: _normalize() method strips backslashes before matching — all path comparison in forward-slash space"
  - "Pattern: flat Pydantic models from nested GraphQL — _parse_scene() helper centralizes flattening logic, models never have nested dicts"
  - "Pattern: async client with explicit close() — no context manager to keep plugin usage simple (asyncio.run per call or close after batch)"
  - "Pattern: _gql() private method handles all transport concerns (headers, errors, JSON parsing) — public methods only deal with domain logic"
observability_surfaces: []
drill_down_paths: []
duration: 3min
verification_result: passed
completed_at: 2026-02-24
blocker_discovered: false
---
# S10: Foundation Shared Library

**# Phase 23 Plan 01: Foundation + Shared Library — Path Mapper Summary**

## What Happened

# Phase 23 Plan 01: Foundation + Shared Library — Path Mapper Summary

**Bidirectional regex path mapper (PathRule + PathMapper) with 13-test TDD suite; httpx/respx/pytest-asyncio installed for Phase 23-02**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-24T05:12:22Z
- **Completed:** 2026-02-24T05:17:15Z
- **Tasks:** 2 (plus RED/GREEN/REFACTOR sub-phases)
- **Files modified:** 6

## Accomplishments

- Created `shared_lib/` package at repo root — importable by plugin via sys.path and provider via Docker COPY
- Implemented `PathMapper` with fully bidirectional path translation: `plex_to_stash` and `stash_to_plex`
- Solved the bidirectional derivation problem: `stash_pattern` is a replacement template, match regex is derived via `_template_to_match_pattern`; plex replacement template derived via `_pattern_to_repl_template`
- 13 TDD tests covering: simple prefix swap, nested paths, no-match returns None, multi-rule first-match-wins, priority order, backslash normalization, case_insensitive flag, from_env JSON parsing, invalid JSON raises, bidirectional round-trip
- Installed httpx, pytest-asyncio, respx for Phase 23-02 (stash_client tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create shared_lib package and install dev dependencies** - `3489aee` (chore)
2. **Task 2 RED: Add failing tests for bidirectional path mapper** - `398f475` (test)
3. **Task 2 GREEN: Implement bidirectional path mapper** - `ee4ecab` (feat)

_Note: TDD task has three commits (chore setup → test RED → feat GREEN). Refactor skipped — implementation was clean._

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `shared_lib/__init__.py` — Package marker with docstring distinguishing from existing `shared/` package
- `shared_lib/path_mapper.py` — PathRule Pydantic model + PathMapper class with bidirectional translation helpers
- `tests/shared_lib/__init__.py` — Empty test package marker
- `tests/shared_lib/test_path_mapper.py` — 13 TDD tests covering all spec behaviors
- `requirements-dev.txt` — Added httpx>=0.27.0, pytest-asyncio>=0.25.0, respx>=0.22.0
- `pytest.ini` — Added --cov=shared_lib and asyncio_mode = strict

## Decisions Made

- `stash_pattern` field is treated as a `re.sub` replacement template (`\1`, `\2`), not as a match regex. The match regex for stash paths is derived at init time via `_template_to_match_pattern`, which replaces `\N` backreferences with `(.*?)` capture groups and escapes literal portions.
- `plex_pattern` is a standard match regex (`^/plex/media/(.*)`). For stash→plex substitution, a replacement template is derived via `_pattern_to_repl_template`, which strips anchors and replaces capturing groups with numbered backreferences.
- `asyncio_mode = strict` chosen (not `auto`) to avoid unintended effects on 22+ existing sync tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stash_pattern field used as regex caused PatternError**

- **Found during:** Task 2 GREEN (first implementation attempt)
- **Issue:** Initial implementation tried to compile `stash_pattern` (e.g., `/stash/media/\1`) as a regex pattern via `re.compile()`. Python raised `re.PatternError: invalid group reference 1 at position 14` because `\1` references a non-existent capture group in a match pattern context.
- **Fix:** Implemented `_template_to_match_pattern()` helper to derive a proper match regex from the stash_pattern replacement template, and `_pattern_to_repl_template()` to derive a replacement template from the plex_pattern regex. These are computed once at `__init__` time.
- **Files modified:** `shared_lib/path_mapper.py`
- **Verification:** All 13 tests pass including `test_stash_to_plex_simple_prefix_swap` and `test_bidirectional_roundtrip`
- **Committed in:** `ee4ecab` (GREEN phase feat commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** The fix resolved an architectural gap in the research example code where stash_pattern was described as both a replacement template and a match regex simultaneously — contradictory requirements. The derivation approach makes the rule design simpler for users (write one template, not two patterns) while maintaining full bidirectionality.

## Issues Encountered

- Coverage threshold failure (80%) is pre-existing — running only shared_lib tests gives 3% total because plex/worker/validation have 0% in this isolated run. The plan's verify command (`pytest tests/shared_lib/`) correctly shows 13/13 pass. Not a new issue.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `shared_lib/` package is importable. `from shared_lib.path_mapper import PathMapper, PathRule` works from repo root.
- httpx, respx, pytest-asyncio installed — Phase 23-02 (stash_client.py) can proceed immediately.
- `asyncio_mode = strict` configured — async tests require `@pytest.mark.asyncio` decorator.
- Path mapper is the complete PATH-01, PATH-02, INFR-01 implementation. No blockers for Phase 23-02.

## Self-Check: PASSED

Files verified:
- FOUND: shared_lib/__init__.py
- FOUND: shared_lib/path_mapper.py
- FOUND: tests/shared_lib/__init__.py
- FOUND: tests/shared_lib/test_path_mapper.py
- FOUND: .planning/phases/23-foundation-shared-library/23-01-SUMMARY.md

Commits verified:
- FOUND: 3489aee (chore: create shared_lib package and install dev dependencies)
- FOUND: 398f475 (test: add failing tests for bidirectional path mapper)
- FOUND: ee4ecab (feat: implement bidirectional path mapper)

---
*Phase: 23-foundation-shared-library*
*Completed: 2026-02-24*

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
