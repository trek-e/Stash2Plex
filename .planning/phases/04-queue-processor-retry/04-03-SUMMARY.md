---
phase: 04-queue-processor-retry
plan: 03
subsystem: worker
tags: [retry, backoff, circuit-breaker, crash-safe, exponential-backoff]

# Dependency graph
requires:
  - phase: 04-01
    provides: calculate_delay and get_retry_params for exponential backoff
  - phase: 04-02
    provides: CircuitBreaker state machine for resilience
provides:
  - Crash-safe retry orchestration with job metadata storage
  - Circuit breaker integration in worker loop
  - Backoff delay checking before processing
  - PlexNotFound-specific retry window (12 retries, 30s base)
affects: [04-04-graceful-shutdown]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Job metadata for crash-safe state (retry_count, next_retry_at)
    - Re-enqueue pattern for persist-queue metadata updates
    - Circuit breaker check at loop start

key-files:
  created:
    - tests/test_retry_orchestration.py
  modified:
    - worker/processor.py

key-decisions:
  - "Re-enqueue pattern: ack + put instead of nack for metadata updates"
  - "Small 0.1s delay after nack to avoid tight loop on not-ready jobs"
  - "Permanent errors don't count against circuit breaker"

patterns-established:
  - "Job metadata pattern: store retry_count, next_retry_at, last_error_type in job dict"
  - "Backoff readiness check: _is_ready_for_retry before processing"

# Metrics
duration: 3min
completed: 2026-01-24
---

# Phase 4 Plan 3: Retry Orchestration Summary

**Crash-safe retry with job metadata, exponential backoff delays, and circuit breaker integration for Plex outage resilience**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-24T17:17:29Z
- **Completed:** 2026-01-24T17:20:37Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Removed instance-level retry tracking in favor of crash-safe job metadata
- Integrated circuit breaker check at start of worker loop (pauses on Plex outage)
- Added backoff delay checking - jobs wait until next_retry_at before processing
- PlexNotFound errors get 12 retries with 30s base (vs 5 retries with 5s base)
- 19 integration tests covering retry orchestration flow

## Task Commits

Each task was committed atomically:

1. **Task 1+2: Crash-safe retry and circuit breaker** - `8168108` (feat)
2. **Task 3: Integration tests** - `6d48c06` (test)

## Files Created/Modified
- `worker/processor.py` - Refactored for crash-safe retry with circuit breaker
- `tests/test_retry_orchestration.py` - 19 integration tests (459 lines)

## Decisions Made
- **Re-enqueue pattern:** persist-queue's nack() doesn't support modifying job data, so we ack the old job and enqueue a new copy with updated metadata. This preserves retry state across restarts.
- **Small delay after not-ready nack:** Added 0.1s sleep after nacking a not-ready job to avoid tight loop.
- **Permanent errors don't affect circuit:** Only transient errors count against the circuit breaker threshold.

## Deviations from Plan

None - plan executed exactly as written. Tasks 1 and 2 were combined into a single commit since the circuit breaker integration was closely tied to the retry tracking refactor.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Retry orchestration complete and tested
- Ready for 04-04: graceful shutdown implementation
- Circuit breaker will pause processing during Plex outages
- Retry state survives worker crashes via job metadata

---
*Phase: 04-queue-processor-retry*
*Completed: 2026-01-24*
