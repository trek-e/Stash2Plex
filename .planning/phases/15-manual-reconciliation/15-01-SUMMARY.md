---
phase: 15-manual-reconciliation
plan: 01
subsystem: reconciliation
tags:
  - ui-integration
  - task-handler
  - gap-detection
  - testing
dependency_graph:
  requires:
    - reconciliation/engine.py (GapDetectionEngine)
    - reconciliation/detector.py (GapDetector)
  provides:
    - Stash2Plex.yml tasks (Reconcile Library All/Recent)
    - Stash2Plex.py handler (handle_reconcile)
  affects:
    - Stash plugin UI (task menu)
    - Queue infrastructure (enqueue gaps)
tech_stack:
  added:
    - Stash task integration (defaultArgs mode dispatch)
  patterns:
    - Task handler pattern (handle_* functions)
    - Mode dispatch routing
    - Management modes (no queue-wait polling)
key_files:
  created:
    - tests/reconciliation/test_reconcile_task.py (303 lines, 10 tests)
  modified:
    - Stash2Plex.yml (+8 lines, 2 task entries)
    - Stash2Plex.py (+67 lines, handle_reconcile + dispatch)
decisions: []
metrics:
  duration: 203s
  completed_at: 2026-02-14
---

# Phase 15 Plan 01: Manual Reconciliation Trigger Summary

Users can now trigger reconciliation on-demand via Stash plugin tasks with configurable scope (all scenes or recent 24 hours), logging gap counts by type.

## Execution Summary

**Tasks completed:** 2 of 2
**Duration:** 3 minutes 23 seconds
**Status:** Complete

### Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add reconciliation tasks to plugin YAML and handler | 523a9f2 | Stash2Plex.yml, Stash2Plex.py |
| 2 | Add tests for reconciliation task handler | 300e3b8 | tests/reconciliation/test_reconcile_task.py |

## What Was Built

### Stash Plugin Tasks

Added two new tasks to Stash2Plex.yml that appear in the Stash plugin task menu:

1. **Reconcile Library (All)** - Detect and queue metadata gaps for all scenes
   - Mode: `reconcile_all`
   - Scope: All scenes in Stash library

2. **Reconcile Library (Recent)** - Detect and queue metadata gaps for recently updated scenes
   - Mode: `reconcile_recent`
   - Scope: Scenes updated in last 24 hours

### Task Handler

Added `handle_reconcile(scope)` function to Stash2Plex.py that:

1. **Validates dependencies** - Checks for stash_interface, config, and queue_manager
2. **Creates GapDetectionEngine** - Initializes with stash, config, data_dir, and queue
3. **Runs gap detection** - Calls engine.run(scope="all"|"recent")
4. **Logs progress summary** - Shows gap counts by type:
   - Empty metadata count
   - Stale sync count
   - Missing from Plex count
   - Total gaps found
   - Enqueued count
   - Skipped (already queued) count
5. **Handles errors** - Logs non-fatal errors as warnings

### Mode Dispatch

Wired `reconcile_all` and `reconcile_recent` modes into `handle_task()` dispatcher, routing to `handle_reconcile()` with appropriate scope parameter.

### Management Modes

Added reconcile modes to `management_modes` set, ensuring:
- No queue-wait polling after task completes
- Task returns immediately after enqueuing gaps
- User can trigger "Process Queue" separately if desired

### Test Coverage

Created 10 comprehensive test cases covering:

1. **Scope dispatch** - Verify 'all' and 'recent' scopes route correctly
2. **Log output** - Verify gap counts appear in stderr with correct format
3. **Error handling** - Test missing stash/config/queue scenarios
4. **Detection-only mode** - Verify behavior when queue unavailable
5. **Engine errors** - Verify non-fatal errors logged as warnings
6. **Mode routing** - Test handle_task dispatches to handle_reconcile
7. **Management modes** - Verify reconcile modes treated as management tasks

All 964 tests pass with 90.78% coverage maintained.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

All verification criteria met:

- ✅ `python3 -m pytest tests/reconciliation/test_reconcile_task.py -v` - All 10 tests pass
- ✅ `python3 -m pytest tests/reconciliation/ -v` - All 54 reconciliation tests pass
- ✅ `python3 -m pytest --cov --cov-fail-under=80` - Full suite passes with 90.78% coverage
- ✅ `grep 'Reconcile Library' Stash2Plex.yml` - Two task entries visible
- ✅ `grep 'reconcile' Stash2Plex.py` - Handler function and dispatch visible

## Technical Notes

### Log Output Format

Reconciliation summary follows this format:

```
=== Reconciliation Summary ===
Scenes checked: 100
Gaps found: 10
  Empty metadata: 3
  Stale sync: 2
  Missing from Plex: 5
Enqueued: 8
Skipped (already queued): 2
```

### Detection-Only Mode

When queue is unavailable (queue_manager is None), reconciliation runs in detection-only mode:
- Logs warning: "No queue available - running in detection-only mode"
- Still detects gaps and logs summary
- Does not enqueue gaps
- Final message: "Detection-only mode (no items enqueued)"

### Error Handling

- Missing stash_interface: Logs error and returns early
- Missing config: Logs error and returns early
- Engine errors: Non-fatal errors logged as warnings after summary
- Exceptions: Caught and logged with full traceback

## Integration Points

### Upstream Dependencies
- Phase 14: GapDetectionEngine from reconciliation/engine.py
- Phase 14: GapDetector from reconciliation/detector.py

### Downstream Impact
- Users can now trigger reconciliation from Stash plugin task menu
- Reconciliation enqueues gaps for worker processing
- Queue worker processes enqueued gaps asynchronously

### User Workflow
1. User selects "Reconcile Library (All)" or "Reconcile Library (Recent)" from Stash task menu
2. Plugin logs reconciliation progress and gap summary
3. Gaps are enqueued (but not processed inline)
4. User can optionally trigger "Process Queue" to sync gaps to Plex

## Self-Check: PASSED

All files and commits verified:

**Files:**
- ✅ FOUND: Stash2Plex.yml
- ✅ FOUND: Stash2Plex.py
- ✅ FOUND: tests/reconciliation/test_reconcile_task.py

**Commits:**
- ✅ FOUND: 523a9f2 (Task 1 - feat: add reconciliation tasks and handler)
- ✅ FOUND: 300e3b8 (Task 2 - test: add reconciliation task handler tests)
