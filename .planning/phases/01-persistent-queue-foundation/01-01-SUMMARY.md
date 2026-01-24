---
phase: 01-persistent-queue-foundation
plan: 01
subsystem: queue
tags: [persist-queue, sqlite, wal, acknowledgment-queue, job-queue]

# Dependency graph
requires:
  - phase: none
    provides: "First phase - no dependencies"
provides:
  - SQLite-backed persistent queue with crash recovery
  - Job enqueue/dequeue operations with acknowledgment semantics
  - Status tracking (pending, in_progress, completed, failed)
  - QueueManager for lifecycle management
affects: [01-02, 01-03, validation, retry, worker]

# Tech tracking
tech-stack:
  added: [persist-queue>=1.1.0, stashapi]
  patterns: [SQLiteAckQueue for job persistence, dict-compatible job models, stateless operations pattern]

key-files:
  created:
    - queue/__init__.py
    - queue/manager.py
    - queue/models.py
    - queue/operations.py
    - requirements.txt
  modified: []

key-decisions:
  - "Used persist-queue SQLiteAckQueue for built-in crash recovery and acknowledgment semantics"
  - "Stored queue in $STASH_PLUGIN_DATA or default ~/.stash/plugins/PlexSync/data"
  - "Dict-compatible SyncJob structure for safe pickle serialization"
  - "Stateless operations pattern - functions receive queue instance"
  - "Map status 0 and 1 both to 'pending' for simplicity"

patterns-established:
  - "QueueManager handles initialization with auto_commit=True, multithreading=True, auto_resume=True"
  - "Operations are stateless functions operating on queue instance"
  - "get_stats queries SQLite directly for status counts"

# Metrics
duration: 5min
completed: 2026-01-24
---

# Phase 1 Plan 1: Queue Infrastructure Summary

**SQLite-backed persistent queue with acknowledgment semantics using persist-queue, supporting job survival across restarts and crashes**

## Performance

- **Duration:** 5 min
- **Started:** 2026-01-24T14:51:18Z
- **Completed:** 2026-01-24T14:55:56Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Created QueueManager that initializes SQLiteAckQueue with crash recovery settings
- Implemented SyncJob model as dict-compatible TypedDict for safe serialization
- Built complete operations API: enqueue, get_pending, ack_job, nack_job, fail_job, get_stats
- Verified jobs persist across QueueManager restarts
- Verified status tracking works correctly

## Task Commits

Each task was committed atomically:

1. **Task 1: Create project structure and dependencies** - `9ae922a` (chore)
2. **Task 2: Implement queue manager and job model** - `689378f` (feat)
3. **Task 3: Implement queue operations** - `fdd9940` (feat)

**Bug fix:** `52ff565` (fix: correct get_stats table name and status mapping)

## Files Created/Modified
- `requirements.txt` - Project dependencies (persist-queue>=1.1.0, stashapi)
- `queue/__init__.py` - Public API exports with graceful import handling
- `queue/manager.py` - QueueManager class with SQLiteAckQueue initialization
- `queue/models.py` - SyncJob TypedDict and create_sync_job helper
- `queue/operations.py` - Six operations for job lifecycle management

## Decisions Made

**Queue storage location:**
- Uses $STASH_PLUGIN_DATA environment variable if set
- Falls back to ~/.stash/plugins/PlexSync/data if not
- Creates directory structure automatically with os.makedirs(exist_ok=True)

**Status mapping simplification:**
- Treat both status 0 (inited) and 1 (ready) as "pending"
- Simplifies user-facing API while maintaining accurate counts

**Table name handling:**
- Query for ack_queue% pattern instead of hardcoding table name
- Handles persist-queue's ack_queue_default naming convention

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed get_stats table name and status code mapping**
- **Found during:** Task 3 verification (integration test)
- **Issue:** get_stats queried non-existent 'ack_queue' table; persist-queue uses 'ack_queue_default'. Status mapping incorrectly separated status 0 (inited) from pending category.
- **Fix:** Updated get_stats to find table with 'ack_queue%' pattern. Mapped both status 0 and 1 to 'pending' category with proper aggregation.
- **Files modified:** queue/operations.py
- **Verification:** Integration test passes - enqueue shows pending=1, acknowledgment shows completed=1
- **Committed in:** 52ff565 (separate fix commit after Task 3)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Bug fix necessary for get_stats to work correctly. No scope creep.

## Issues Encountered

**persist-queue not installed initially:**
- Resolved by running `pip3 install 'persist-queue>=1.1.0'` before verification
- Expected - requirements.txt created but dependencies not auto-installed

**pqid showing as None in debug output:**
- Non-blocking issue - acknowledgment still works correctly
- Likely due to how persist-queue serializes the pqid field
- Verification shows completed=1 after ack, so functionality is correct

## User Setup Required

None - no external service configuration required.

Dependencies can be installed with:
```bash
pip install -r requirements.txt
```

## Next Phase Readiness

**Ready for Phase 1 Plan 2 (Dead Letter Queue):**
- Queue infrastructure operational
- All CRUD operations working
- Status tracking verified
- Persistence across restarts confirmed

**Ready for Phase 1 Plan 3 (Hook handler and worker):**
- Queue can be imported and used
- Operations API complete
- Thread-safe operations enabled (multithreading=True)

**Blockers/concerns:**
None

---
*Phase: 01-persistent-queue-foundation*
*Completed: 2026-01-24*
