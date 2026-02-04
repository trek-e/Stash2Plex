---
phase: 11-queue-management-ui
plan: 01
subsystem: plugin-tasks
tags: [queue, dlq, stash-ui, tasks]
dependency-graph:
  requires: [phase-10-reliability]
  provides: [queue-management-ui, queue-status-task, clear-queue-task, clear-dlq-task, purge-dlq-task]
  affects: [phase-12-process-queue-button]
tech-stack:
  added: []
  patterns: [task-handler-dispatch, stateless-queue-operations]
key-files:
  created: []
  modified:
    - sync_queue/operations.py
    - Stash2Plex.yml
    - Stash2Plex.py
decisions:
  - key: queue-ops-stateless
    choice: "Direct SQLite operations for clear_pending_items"
    rationale: "Matches existing get_stats pattern, avoids persist-queue API complexity"
metrics:
  duration: "1m 50s"
  completed: "2026-02-04"
---

# Phase 11 Plan 01: Queue Management UI Tasks Summary

**One-liner:** Four new Stash UI tasks for queue management (status, clear queue, clear DLQ, purge old DLQ)

## What Was Built

Added queue management capabilities directly accessible from Stash UI Tasks menu:

1. **View Queue Status** - Shows queue and DLQ statistics in Stash logs
2. **Clear Pending Queue** - Removes pending items (preserves in-progress/completed)
3. **Clear Dead Letter Queue** - Removes all DLQ items
4. **Purge Old DLQ Entries** - Removes DLQ entries older than 30 days

### Implementation Details

**sync_queue/operations.py:**
- Added `clear_pending_items(queue_path: str) -> int` function
- Deletes items with status 0 (inited) or 1 (ready)
- Preserves in-progress (2), completed (5), and failed (9) items
- Returns count of deleted items

**Stash2Plex.yml:**
- Added 4 new task definitions with appropriate modes
- WARNING prefix in descriptions for destructive operations
- Total tasks: 6 (2 original + 4 new)

**Stash2Plex.py:**
- Added 4 handler functions before handle_task()
- Updated handle_task() dispatcher to route new modes
- Queue management tasks work without Stash connection (early return pattern)

## Commits

| Commit | Description |
|--------|-------------|
| 2bece29 | feat(11-01): add clear_pending_items function to queue operations |
| c3d3f70 | feat(11-01): add queue management task definitions |
| acdf489 | feat(11-01): add queue management handlers and dispatcher |

## Files Modified

| File | Changes |
|------|---------|
| sync_queue/operations.py | +38 lines - clear_pending_items function |
| Stash2Plex.yml | +17 lines - 4 new task definitions |
| Stash2Plex.py | +133 lines - 4 handlers + dispatcher logic |

## Verification Results

All verification checks passed:
- YAML validation: 6 tasks in Stash2Plex.yml
- Python imports: operations.py and Stash2Plex.py import without error
- Function existence: 4 handler functions found
- Mode dispatch: 4 mode branches in handle_task()

## Deviations from Plan

None - plan executed exactly as written.

## Success Criteria Status

- [x] sync_queue/operations.py has clear_pending_items function
- [x] Stash2Plex.yml has 6 tasks (2 original + 4 queue management)
- [x] Stash2Plex.py has 4 handler functions
- [x] handle_task dispatches to correct handler based on mode
- [x] All Python files import without error
- [x] YAML file is valid

## Next Phase Readiness

**Ready for Phase 12: Process Queue Button**
- Queue management infrastructure in place
- Handler dispatch pattern established for new task modes
- No blockers identified
