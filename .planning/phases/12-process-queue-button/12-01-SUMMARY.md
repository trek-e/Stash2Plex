---
phase: 12-process-queue-button
plan: 01
subsystem: queue
tags: [stash-plugin, foreground-processing, circuit-breaker, progress-ui, dlq]

# Dependency graph
requires:
  - phase: 11-queue-management-ui
    provides: Queue management task infrastructure (View Status, Clear Queue, Clear DLQ, Purge DLQ)
provides:
  - handle_process_queue() function for foreground batch processing
  - Process Queue task in Stash UI menu
  - Progress reporting via log_progress() for Stash task UI
  - Circuit breaker integration for Plex availability checks
affects: [13-dynamic-timeout]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Foreground processing loop (not daemon-bound)
    - Progress reporting every 5 items or 10 seconds
    - Local worker instance to avoid global state conflicts

key-files:
  created: []
  modified:
    - Stash2Plex.py
    - Stash2Plex.yml

key-decisions:
  - "Use local worker instance (worker_local) to avoid conflicts with global daemon worker"
  - "Progress reporting threshold: every 5 items OR every 10 seconds (whichever first)"
  - "Circuit breaker checked before each job, not just at start"

patterns-established:
  - "Foreground task pattern: initialize local infrastructure, process in while True loop, report progress"

# Metrics
duration: 2min
completed: 2026-02-04
---

# Phase 12 Plan 01: Process Queue Button Summary

**Foreground queue processor with progress UI feedback, circuit breaker respect, and DLQ integration for stuck queue recovery**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-04T03:08:11Z
- **Completed:** 2026-02-04T03:10:17Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Added handle_process_queue() function with foreground processing loop
- Integrated progress reporting via log_progress() for Stash task UI visibility
- Circuit breaker checked before each job to stop if Plex unavailable
- Error classification with TransientError/PermanentError/generic handling
- Failed items properly routed to DLQ with retry count tracking
- New "Process Queue" task in Stash UI menu

## Task Commits

Each task was committed atomically:

1. **Task 1: Add handle_process_queue function** - `5e32c31` (feat)
2. **Task 2: Add task definition and wire dispatcher** - `c6a151d` (feat)
3. **Task 3: Add missing import and verify integration** - No separate commit (time import was part of Task 1, verification only)

## Files Created/Modified
- `Stash2Plex.py` - Added time import, handle_process_queue() function, dispatcher wiring
- `Stash2Plex.yml` - Added Process Queue task definition (7 tasks total)

## Decisions Made
- Used local variables (queue_manager_local, dlq_local, worker_local) to avoid conflicts with global daemon worker
- Progress reporting every 5 items OR every 10 seconds, whichever comes first
- Circuit breaker checked before each job (not just at start) for responsive Plex availability detection

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Process Queue task is fully functional and appears in Stash UI
- Ready for Phase 13: Dynamic Queue Timeout
- No blockers or concerns

---
*Phase: 12-process-queue-button*
*Completed: 2026-02-04*
