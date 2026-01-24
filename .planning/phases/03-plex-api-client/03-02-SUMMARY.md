---
phase: 03-plex-api-client
plan: 02
subsystem: api
tags: [plexapi, tenacity, retry, timeout, path-matching]

# Dependency graph
requires:
  - phase: 03-01
    provides: PlexTemporaryError, PlexPermanentError, PlexNotFound, translate_plex_exception
provides:
  - PlexClient wrapper with lazy initialization and timeouts
  - find_plex_item_by_path with 3-strategy fallback matching
  - tenacity retry for connection-level failures
affects: [03-03, worker]

# Tech tracking
tech-stack:
  added: [plexapi>=4.17.0, tenacity>=9.0.0]
  patterns: [lazy-import, exponential-backoff-with-jitter, fallback-matching]

key-files:
  created:
    - plex/client.py
    - plex/matcher.py
  modified:
    - plex/__init__.py
    - requirements.txt

key-decisions:
  - "Lazy imports for plexapi/requests to avoid queue module shadowing stdlib"
  - "Retry decorator applied inside method, not at class level, for lazy exception loading"
  - "Return None on ambiguous filename matches instead of guessing"
  - "Use read_timeout as PlexServer timeout (PlexAPI uses single timeout, not tuple)"

patterns-established:
  - "Lazy import pattern: Import plexapi/requests inside functions to avoid conflict with queue/ module"
  - "Fallback matching: Exact path -> filename-only -> case-insensitive"

# Metrics
duration: 3min
completed: 2026-01-24
---

# Phase 3 Plan 2: PlexClient Wrapper with Path Matching Summary

**PlexClient with tenacity retry (100-400ms backoff, 3 attempts) and 3-strategy file path matcher**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-24T16:20:29Z
- **Completed:** 2026-01-24T16:23:45Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- PlexClient wrapper with explicit timeout configuration (no infinite hangs)
- Tenacity retry decorator for connection errors with exponential backoff and jitter
- 3-strategy file path matching: exact path, filename-only, case-insensitive
- Lazy imports to avoid queue module shadowing Python's stdlib queue

## Task Commits

Each task was committed atomically:

1. **Task 1: Create PlexClient wrapper** - `a2a1c0c` (feat)
2. **Task 2: Create file path matcher** - `12a42a4` (feat)
3. **Task 3: Update plex module exports** - `9f62ab7` (chore)

## Files Created/Modified

- `plex/client.py` - PlexClient class with lazy PlexServer init, timeout config, @retry decorator
- `plex/matcher.py` - find_plex_item_by_path with 3 fallback strategies
- `plex/__init__.py` - Updated exports for PlexClient and find_plex_item_by_path
- `requirements.txt` - Added plexapi>=4.17.0 and tenacity>=9.0.0

## Decisions Made

1. **Lazy imports for plexapi/requests** - The project has a `queue/` directory that shadows Python's stdlib `queue` module. When urllib3 (dependency of requests) imports, it looks for `queue.LifoQueue` and fails. Solution: lazy import requests/plexapi inside methods rather than at module level.

2. **Retry decorator inside method** - Applied @retry decorator to inner `connect()` function rather than `_get_server()` method to ensure exceptions tuple is built after lazy import.

3. **Return None on ambiguous matches** - When filename matching returns multiple results, return None and log warning instead of guessing. This prevents incorrect metadata being applied to wrong items.

4. **Single timeout value for PlexAPI** - PlexAPI accepts a single `timeout` parameter (unlike requests' tuple). Use read_timeout as the primary timeout since connection is typically fast.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing plexapi and tenacity dependencies**
- **Found during:** Task 1 (PlexClient creation)
- **Issue:** plexapi and tenacity not in requirements.txt or installed
- **Fix:** Added to requirements.txt and installed with pip3
- **Files modified:** requirements.txt
- **Verification:** Import succeeded after install
- **Committed in:** a2a1c0c (Task 1 commit)

**2. [Rule 1 - Bug] Fixed queue module shadowing Python stdlib**
- **Found during:** Task 1 verification
- **Issue:** Module-level `import requests.exceptions` triggered urllib3 which tried to import stdlib queue, but found project's queue/ directory instead. AttributeError: module 'queue' has no attribute 'LifoQueue'
- **Fix:** Changed to lazy imports - moved requests/plexapi imports inside functions, used TYPE_CHECKING for type hints
- **Files modified:** plex/client.py
- **Verification:** All imports now succeed without queue conflict
- **Committed in:** a2a1c0c (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes necessary for basic operation. Lazy import pattern is now established for any future imports of requests-dependent libraries.

## Issues Encountered

None - plan executed as specified after auto-fixes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- PlexClient ready for integration with worker process_job function
- File path matching ready for Plex item lookup
- Exception hierarchy complete for error routing
- Phase 3 Plan 3 (metadata update integration) can proceed

---
*Phase: 03-plex-api-client*
*Completed: 2026-01-24*
