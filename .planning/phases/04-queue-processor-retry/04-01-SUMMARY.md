---
phase: 04-queue-processor-retry
plan: 01
subsystem: worker
tags: [backoff, jitter, retry, exponential]

# Dependency graph
requires:
  - phase: 03-plex-api-client
    provides: PlexNotFound exception for error-specific backoff
provides:
  - calculate_delay function with full jitter
  - get_retry_params for error-type-specific backoff configuration
affects: [04-02, 04-03, 04-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [full-jitter-backoff, seeded-random-for-testing]

key-files:
  created: [worker/backoff.py, tests/test_backoff.py]
  modified: []

key-decisions:
  - "Use seeded random.Random for deterministic testing"
  - "PlexNotFound gets 30s base, 600s cap, 12 retries (~2hr window)"
  - "Standard errors get 5s base, 80s cap, 5 retries"

patterns-established:
  - "Full jitter: random.uniform(0, min(cap, base * 2^retry))"
  - "Lazy import of PlexNotFound to avoid circular dependencies"

# Metrics
duration: 2min
completed: 2026-01-24
---

# Phase 4 Plan 1: Exponential Backoff with Full Jitter Summary

**Delay calculator with full jitter preventing thundering herd, error-specific params for PlexNotFound vs standard errors**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-24T17:12:26Z
- **Completed:** 2026-01-24T17:14:11Z
- **Tasks:** 1 (TDD cycle: RED/GREEN/REFACTOR)
- **Files modified:** 2

## Accomplishments
- `calculate_delay()` with full jitter formula distributes retries randomly within exponential window
- `get_retry_params()` returns different base/cap/max_retries for PlexNotFound vs other errors
- Seeded random enables deterministic testing
- 15 unit tests covering bounds, cap enforcement, and error type detection

## Task Commits

TDD task produced 2 commits:

1. **Task: Exponential Backoff (RED)** - `cd9ce27` (test)
2. **Task: Exponential Backoff (GREEN)** - `262cfd9` (feat)

_REFACTOR phase: No refactoring needed - code was clean._

## Files Created/Modified
- `worker/backoff.py` - Delay calculation functions with full jitter
- `tests/test_backoff.py` - 15 unit tests (158 lines)

## Decisions Made
- Used `random.Random(seed)` for testable jitter instead of module-level random
- PlexNotFound ~2 hour retry window (30s base, 600s cap, 12 retries) because library scanning can take hours
- Standard errors shorter window (5s base, 80s cap, 5 retries) per config default
- Lazy import of PlexNotFound to avoid circular imports (consistent with existing codebase pattern)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed Python 3.9 type hint syntax**
- **Found during:** GREEN phase
- **Issue:** Used `int | None` syntax which requires Python 3.10+
- **Fix:** Changed to `Optional[int]` from typing module
- **Files modified:** worker/backoff.py
- **Verification:** Tests pass on Python 3.9.6
- **Committed in:** 262cfd9 (GREEN phase commit)

---

**Total deviations:** 1 auto-fixed (blocking)
**Impact on plan:** Necessary for compatibility with project's Python version. No scope creep.

## Issues Encountered
None beyond the type hint syntax fix documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Backoff calculator ready for circuit breaker integration (04-02)
- `get_retry_params()` can be called by worker processor for error-type-specific delays
- Pattern of seeded random established for any future randomized functionality

---
*Phase: 04-queue-processor-retry*
*Completed: 2026-01-24*
