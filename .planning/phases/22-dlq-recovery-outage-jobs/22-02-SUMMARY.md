---
phase: 22-dlq-recovery-outage-jobs
plan: 02
subsystem: ui
tags: [task-handler, dlq-recovery, outage-handling, ui-integration]

dependency_graph:
  requires:
    - sync_queue/dlq_recovery.py (recovery operations from 22-01)
    - worker/outage_history.py (outage window detection)
    - sync_queue/dlq.py (DLQ database access)
    - plex/client.py (PlexClient instantiation)
  provides:
    - Stash2Plex.py::handle_recover_outage_jobs() (UI task handler)
    - Stash2Plex.yml::"Recover Outage Jobs" task (Stash UI registration)
  affects:
    - Stash2Plex.py::_MANAGEMENT_HANDLERS (dispatch table)
    - Stash2Plex.py::management_modes (no-wait set for recovery task)

tech_stack:
  added: []
  patterns:
    - Management task handler pattern (no queue drain wait)
    - Conservative defaults (PlexServerDown errors only)
    - Detailed results logging (recovered, skipped by reason, failed)
    - Error path handling (no outages, no completed outages, empty DLQ)

key_files:
  created: []
  modified:
    - Stash2Plex.py (handle_recover_outage_jobs function, dispatch, management_modes)
    - Stash2Plex.yml (task registration)
    - tests/test_main.py (8 new tests)

decisions:
  - Conservative default hardcoded: always use include_optional=False (no user confusion)
  - Task placed in management_modes set: no queue drain wait (recovery itself enqueues jobs)
  - Task description emphasizes "PlexServerDown errors only" for user clarity
  - Handler follows exact pattern of handle_outage_summary (consistency)

metrics:
  duration: 251 seconds (4.18 minutes)
  completed: 2026-02-15
  test_count: 8 tests added (1213 total, up from 1205)
  coverage: 86% overall (above 80% threshold)
  commits: 2 (feat: handler implementation, test: comprehensive tests)
---

# Phase 22 Plan 02: Task Integration & Recovery UI Summary

**One-liner:** Wire DLQ recovery module into Stash UI as "Recover Outage Jobs" task with handler, dispatch, tests, and detailed logging

## What Was Built

Integrated the DLQ recovery module (from Plan 01) into Stash UI as a user-accessible task:

### 1. Task Handler (Stash2Plex.py)

**handle_recover_outage_jobs()** added after handle_outage_summary() with:

- **Outage history validation:**
  - Loads OutageHistory, checks for records
  - Filters to completed outages only (ended_at != None)
  - Uses last completed outage for recovery window
  - Logs error and returns early if no usable outage found

- **DLQ query:**
  - Uses conservative default: `get_error_types_for_recovery(include_optional=False)` → ["PlexServerDown"]
  - Queries DLQ for entries in outage time window
  - Logs filter and entry count

- **Recovery orchestration:**
  - Creates PlexClient instance (same pattern as handle_health_check)
  - Calls `recover_outage_jobs()` with queue, stash, plex_client, data_dir
  - Logs detailed results breakdown:
    - Recovered count
    - Skipped counts by reason (already queued, Plex down, scene missing)
    - Failed count
    - List of recovered scene_ids (if any)

- **Error handling:**
  - try/except wrapper with traceback logging
  - Early returns for invalid states (no queue, no config)
  - All error paths logged via log_info or log_error

### 2. Dispatch Integration (Stash2Plex.py)

- **_MANAGEMENT_HANDLERS:** Added `'recover_outage_jobs': lambda args: handle_recover_outage_jobs()`
- **management_modes set:** Added `'recover_outage_jobs'` (no queue drain wait - recovery itself enqueues)

### 3. UI Registration (Stash2Plex.yml)

Added task after "Outage Summary Report":

```yaml
- name: Recover Outage Jobs
  description: Re-queue DLQ jobs that failed during last Plex outage (PlexServerDown errors only, requires Plex to be healthy)
  defaultArgs:
    mode: recover_outage_jobs
```

Description emphasizes conservative behavior and prerequisites.

### 4. Comprehensive Tests (tests/test_main.py)

**8 new tests in TestOutageUIHandlers class:**

1. **test_recover_outage_jobs_in_management_handlers:** Dispatch table registration
2. **test_recover_outage_jobs_in_management_modes:** management_modes set inclusion
3. **test_handle_recover_outage_jobs_no_outages:** Empty history edge case
4. **test_handle_recover_outage_jobs_no_completed_outages:** Only ongoing outages (no ended_at)
5. **test_handle_recover_outage_jobs_no_dlq_entries:** Empty DLQ for outage window
6. **test_handle_recover_outage_jobs_successful_recovery:** Full recovery flow with result verification
7. **test_handle_recover_outage_jobs_uses_conservative_defaults:** Verifies include_optional=False, PlexServerDown filter logged
8. **test_recover_outage_jobs_task_registered_in_yml:** Verifies task exists in Stash2Plex.yml with correct mode

All tests use mocking to isolate handler logic from dependencies.

## Test Coverage

**Test results:**
- 8/8 new tests passing
- Full suite: 1213 tests (up from 1205 in Plan 01)
- Overall coverage: 86% (above 80% threshold)
- DLQ recovery module: 98% coverage (from Plan 01)

**Combined DLQ recovery test coverage (Plan 01 + 02):**
- 38 tests total across both plans (23 from 22-01, 8 from 22-02, 7 related recovery tests)
- All tests passing with no regressions

## Deviations from Plan

None - plan executed exactly as written.

## Technical Highlights

### 1. Conservative Default Hardcoded

Plan specified `include_optional=False` as default. Implementation hardcodes this (no args parameter) to prevent user confusion and ensure safe behavior always. Users cannot accidentally recover optional error types.

### 2. Management Modes Placement

Added to `management_modes` set because recovery task enqueues jobs (doesn't drain queue). This prevents the main() function from waiting for queue drain after task completes.

### 3. PlexClient Instantiation Pattern

Follows exact pattern from `handle_health_check()`:
- Uses config.plex_url and config.plex_token
- Sets connect_timeout=5.0s (health check)
- Sets read_timeout=30.0s (normal operations)

### 4. Detailed Results Logging

Handler logs comprehensive breakdown:
```
Recovery complete: 2 recovered, 0 already queued, 0 skipped (Plex down), 0 skipped (scene missing), 0 failed
Re-queued scene IDs: [101, 102]
```

Provides clear visibility into recovery outcomes and skip reasons.

### 5. Error Path Completeness

All edge cases handled:
- No outage history → log + return
- No completed outages → log + return
- No DLQ entries → log + return
- No queue manager → log_error + return
- No config → log_error + return
- Exception during recovery → log_error + traceback

## Integration Points

**Uses from existing modules:**
- `worker.outage_history.OutageHistory` - get_history() for outage window
- `worker.outage_history.format_duration`, `format_elapsed_since` - human-readable timestamps
- `sync_queue.dlq_recovery.get_error_types_for_recovery` - conservative filter
- `sync_queue.dlq_recovery.get_outage_dlq_entries` - time-windowed query
- `sync_queue.dlq_recovery.recover_outage_jobs` - recovery orchestration
- `sync_queue.dlq.DeadLetterQueue` - DLQ database access
- `plex.client.PlexClient` - Plex connectivity

**Accessed by:**
- Stash UI (user clicks "Recover Outage Jobs" task)
- _MANAGEMENT_HANDLERS dispatch (routes mode to handler)

## What Users Get

1. **UI Task:** "Recover Outage Jobs" appears in Stash task list
2. **Safe Defaults:** Only PlexServerDown errors recovered (no user input needed)
3. **Clear Feedback:** Detailed logs show exactly what happened (recovered, skipped, failed)
4. **Idempotent:** Safe to run multiple times (deduplication prevents double-recovery)
5. **Prerequisites Documented:** Description warns "requires Plex to be healthy"

## Phase 22 Complete

This completes Phase 22 (DLQ Recovery for Outage Jobs):
- **Plan 01:** Core DLQ recovery module (23 tests, 98% coverage)
- **Plan 02:** UI integration and task handler (8 tests, full integration)

**Combined deliverables:**
- Time-windowed DLQ queries with error type filtering
- Three-gate idempotent recovery (health → dedup → scene existence)
- User-facing task in Stash UI with conservative defaults
- Comprehensive test coverage (31 tests across both plans)

Users can now manually recover jobs that failed during Plex outages with a single click.

## Self-Check: PASSED

**Modified files exist:**
- FOUND: Stash2Plex.py
- FOUND: Stash2Plex.yml
- FOUND: tests/test_main.py

**Commits exist:**
- FOUND: 85323d1 (feat(22-02): add recover_outage_jobs task handler and UI registration)
- FOUND: 061448a (test(22-02): add 8 tests for recover_outage_jobs handler)

**Test results:**
- 8/8 new tests passing
- Full suite: 1213/1213 tests passing
- No regressions
- Coverage: 86% (above 80% threshold)

**Verification commands:**
- `grep "recover_outage_jobs" Stash2Plex.py Stash2Plex.yml` → Found in handler, dispatch, management_modes, yml task
- `pytest tests/test_main.py -k "recover"` → 15/15 tests passing (8 new + 7 related)
- `pytest tests/sync_queue/test_dlq_recovery.py tests/test_main.py -k "recover or dlq_recovery"` → 38/38 tests passing
