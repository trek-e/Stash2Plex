---
phase: 01-persistent-queue-foundation
plan: 02
subsystem: queue
tags: [dead-letter-queue, sqlite, error-handling, dlq]

# Dependency graph
requires:
  - phase: 01-01
    provides: "Queue infrastructure with persist-queue"
provides:
  - Dead letter queue for permanently failed jobs
  - Error context storage (error type, message, stack trace)
  - DLQ query API for manual review
  - Retention management with configurable cleanup
affects: [01-03, retry-logic, error-monitoring]

# Tech tracking
tech-stack:
  added: []
  patterns: [Separate DLQ SQLite database, pickle for job persistence, index-optimized queries]

key-files:
  created:
    - queue/dlq.py
  modified:
    - queue/__init__.py

key-decisions:
  - "Separate DLQ database (dlq.db) from main queue for long retention"
  - "Store full job_data as pickled BLOB for complete error context"
  - "Indexes on failed_at and scene_id for efficient queries"
  - "30-day default retention period for DLQ cleanup"
  - "get_recent returns summary without job_data, get_by_id unpickles for details"

patterns-established:
  - "Context manager pattern for SQLite connections"
  - "Pickle serialization for complex job data structures"
  - "Two-tier query API: summary listings vs full details"

# Metrics
duration: 1min
completed: 2026-01-24
---

# Phase 1 Plan 2: Dead Letter Queue Summary

**Persistent storage for permanently failed jobs with full error context, enabling manual review and debugging**

## Performance

- **Duration:** 1 min
- **Started:** 2026-01-24T14:58:31Z
- **Completed:** 2026-01-24T14:59:59Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created DeadLetterQueue class with SQLite-backed storage
- Implemented dead_letters table with job data, error details, timestamps
- Added indexes on failed_at and scene_id for efficient queries
- Built complete DLQ API: add, get_recent, get_by_id, get_count, delete_older_than
- Exported DeadLetterQueue from queue package
- Verified integration: job storage, querying, and full retrieval working

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement DeadLetterQueue class** - `d1132e1` (feat)
2. **Task 2: Update queue module exports and add integration test** - `befaf3a` (feat)

## Files Created/Modified

- `queue/dlq.py` - DeadLetterQueue class with full error context storage
- `queue/__init__.py` - Added DeadLetterQueue export

## Decisions Made

**DLQ database separation:**
- Store DLQ in separate dlq.db file from main queue
- Allows long retention (30+ days) without affecting queue cleanup
- Located in same data_dir as main queue for consistency

**Job data storage:**
- Pickle full job dict as BLOB for complete error context
- Includes original pqid, scene_id, and all metadata
- Enables replay or manual intervention if needed

**Query optimization:**
- Created indexes on failed_at (for recent queries) and scene_id (for per-scene debugging)
- get_recent returns summary only (no unpickling) for fast listings
- get_by_id unpickles full job_data for detailed investigation

**Retention strategy:**
- Default 30-day retention in delete_older_than method
- Balances debugging needs with database size
- Method logs cleanup count for observability

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - implementation was straightforward.

## User Setup Required

None - DLQ automatically creates database and schema on first use.

## Next Phase Readiness

**Ready for Phase 1 Plan 3 (Hook handler and worker):**
- DLQ operational and can receive failed jobs
- Full error context preserved for debugging
- Query API available for status checks
- Worker can move permanently failed jobs to DLQ

**Future integration points:**
- Worker needs to call dlq.add() when jobs fail permanently
- Could add Stash notification for DLQ entries (deferred to later phase)
- Could add retry mechanism for DLQ entries (deferred to later phase)

**Blockers/concerns:**
None

---
*Phase: 01-persistent-queue-foundation*
*Completed: 2026-01-24*
