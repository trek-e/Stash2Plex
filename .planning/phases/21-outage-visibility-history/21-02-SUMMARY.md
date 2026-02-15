---
phase: 21-outage-visibility-history
plan: 02
subsystem: ui, worker
tags: [outage-tracking, visibility, ui-integration, circuit-breaker, recovery]

dependency_graph:
  requires:
    - Plan 21-01 (OutageHistory manager)
  provides:
    - Outage recording in circuit breaker lifecycle
    - Enhanced queue status display with circuit/recovery/outage info
    - Outage Summary Report task
  affects:
    - handle_queue_status (enhanced with 3 new sections)
    - maybe_check_recovery (passes outage_history to RecoveryScheduler)

tech_stack:
  added: []
  patterns:
    - Event-driven outage recording (circuit state transitions)
    - Formatted time display in UI (format_duration, format_elapsed_since)
    - Optional dependency injection (outage_history defaults to None)

key_files:
  created:
    - None
  modified:
    - worker/circuit_breaker.py (added outage_history parameter and recording)
    - worker/recovery.py (added outage_history parameter and recording)
    - worker/processor.py (creates OutageHistory instance)
    - Stash2Plex.py (enhanced handle_queue_status, new handle_outage_summary)
    - Stash2Plex.yml (registered Outage Summary Report task)
    - tests/test_circuit_breaker.py (4 new tests)
    - tests/worker/test_recovery.py (4 new tests)
    - tests/test_main.py (6 new tests)

decisions:
  - title: "Outage recording on circuit transitions (not state loading)"
    rationale: "Loading persisted OPEN state is not a new outage - only record on actual _open() call"
    alternatives: ["Record on every state load (would create duplicate outages)"]
  - title: "jobs_affected passed as 0 for now"
    rationale: "Counting DLQ entries during outage window deferred to Phase 22 (DLQ recovery)"
    alternatives: ["Implement DLQ counting now (scope creep)"]
  - title: "outage_history defaults to None for backward compatibility"
    rationale: "Existing tests pass unchanged, no breaking changes"
    alternatives: ["Require outage_history parameter (breaking change)"]
  - title: "Enhanced queue status adds 3 new sections (not separate command)"
    rationale: "Single command shows comprehensive system status, users want holistic view"
    alternatives: ["Separate tasks for circuit status, recovery status, outage history"]

metrics:
  duration_minutes: 6.25
  tests_added: 14
  test_coverage: 85.38
  lines_added: 323
  commits: 3
  files_modified: 8
  completed: 2026-02-15
---

# Phase 21 Plan 02: Status UI Integration Summary

**One-liner:** Wired OutageHistory into circuit breaker lifecycle and exposed outage data through enhanced queue status and new outage summary report task

## Objective Achievement

Successfully integrated OutageHistory into the circuit breaker and recovery scheduler lifecycle, completing all three VISB requirements (01, 03, 04) for outage visibility in Stash UI.

**Core capabilities:**
- CircuitBreaker._open() records outage start automatically
- RecoveryScheduler.record_health_check() records outage end on recovery
- Enhanced "View Queue Status" shows circuit state, recovery timing, and recent outages
- New "Outage Summary Report" task displays MTTR, MTBF, availability, and last 10 outages
- All changes backward compatible (outage_history defaults to None)

## Implementation Details

### Task 1: Wiring Outage Recording

**CircuitBreaker changes:**
- Added optional `outage_history` parameter to `__init__`
- `_open()` calls `outage_history.record_outage_start(self._opened_at)` after state transition
- Does NOT record on `_load_state()` (loading persisted OPEN state is not a new outage)

**RecoveryScheduler changes:**
- Added optional `outage_history` parameter to `__init__`
- `record_health_check()` calls `outage_history.record_outage_end(state.last_recovery_time)` when circuit transitions to CLOSED
- Only records on actual recovery (HALF_OPEN -> CLOSED transition), not on health check success during OPEN state

**SyncWorker changes:**
- Creates `OutageHistory` instance from `data_dir` in `__init__`
- Passes `outage_history=self._outage_history` to CircuitBreaker constructor
- Passes `outage_history=self._outage_history` to all RecoveryScheduler instantiations

**Backward compatibility:** All existing tests pass unchanged. Default `outage_history=None` means no recording happens if not provided.

### Task 2: Enhanced Queue Status and Outage Summary

**Enhanced handle_queue_status():**
Added 3 new sections after existing "Reconciliation Status":

1. **Circuit Breaker Status:**
   - Shows state: CLOSED / OPEN / HALF_OPEN
   - If OPEN: shows "Opened: {elapsed} ago" and duration
   - If HALF_OPEN: shows "Testing recovery..."

2. **Recovery Status:**
   - Shows "Last health check: {elapsed} ago"
   - If circuit OPEN: shows "Next check: in {seconds}s"
   - Shows "Last recovery: {elapsed} ago" if any recoveries
   - Shows "Total recoveries: {count}"

3. **Recent Outages:**
   - Shows last 3 outages with durations
   - Shows "ONGOING ({duration})" if current outage exists
   - Shows "No outages recorded" if empty

**New handle_outage_summary():**
Comprehensive outage metrics report:
- Total outages tracked, completed count
- Total downtime (formatted)
- MTTR (Mean Time To Repair)
- MTBF (Mean Time Between Failures, if >= 2 outages)
- Availability percentage (if MTBF > 0)
- Current ongoing outage status
- Last 10 outages with timestamps, durations, jobs_affected count

**Registration:**
- Added to `_MANAGEMENT_HANDLERS` dict: `'outage_summary': lambda args: handle_outage_summary()`
- Added to `management_modes` set
- Registered in Stash2Plex.yml as "Outage Summary Report" task

**maybe_check_recovery() update:**
- Creates `OutageHistory` instance from `data_dir`
- Passes `outage_history=outage_history` to `RecoveryScheduler` constructor

### Task 3: Tests

**Circuit breaker tests (4 new):**
- `test_open_records_outage_start`: Verifies `record_outage_start()` called with `opened_at` timestamp
- `test_open_without_outage_history`: Backward compatibility (outage_history=None doesn't raise)
- `test_outage_history_parameter_stored`: Parameter stored correctly
- `test_no_outage_record_on_state_load`: Loading persisted OPEN state doesn't re-record outage

**Recovery tests (4 new):**
- `test_recovery_records_outage_end`: Verifies `record_outage_end()` called on HALF_OPEN -> CLOSED transition
- `test_recovery_without_outage_history`: Backward compatibility (outage_history=None doesn't raise)
- `test_no_outage_end_when_circuit_stays_open`: No recording when circuit stays OPEN
- `test_no_outage_end_when_circuit_stays_half_open`: No recording when circuit stays HALF_OPEN

**Main handler tests (6 new):**
- `test_handle_outage_summary_no_outages`: Empty history logs "No outages recorded"
- `test_handle_outage_summary_with_outages`: Metrics displayed correctly
- `test_handle_queue_status_includes_circuit_breaker_section`: All 3 sections present
- `test_outage_summary_in_management_handlers`: Dispatch table registration verified
- `test_outage_summary_in_management_modes`: management_modes set inclusion verified
- Updated `test_runs_health_check_when_circuit_open`: Verifies `outage_history` passed to RecoveryScheduler

**Test results:** 1182 passed (14 new), coverage 85.38% (above 80% threshold)

## Verification Results

**Phase requirements met:**

✓ **VISB-01:** Queue status shows circuit breaker state and recovery timing
- Circuit Breaker Status section: state, opened time, duration
- Recovery Status section: last check, next check, last recovery, total recoveries
- Recent Outages section: last 3 outages with durations

✓ **VISB-03:** Outage history tracks last 30 outages
- CircuitBreaker._open() calls record_outage_start()
- RecoveryScheduler.record_health_check() calls record_outage_end() on recovery
- MAX_OUTAGES = 30 (circular buffer from Plan 21-01)

✓ **VISB-04:** Outage summary report task
- handle_outage_summary() shows MTTR, MTBF, availability
- Task registered in Stash2Plex.yml
- Dispatch table entry in _MANAGEMENT_HANDLERS

**Full test suite:**
```
$ pytest --tb=short -q
===================== 1182 passed, 153 warnings in 10.01s ======================
Coverage: 85.38% (above 80% threshold)
```

## Deviations from Plan

None - plan executed exactly as written. All three tasks completed successfully:
1. Outage recording wired into circuit breaker and recovery lifecycle
2. Queue status enhanced, outage summary task created and registered
3. All tests added and passing

## Next Steps

Phase 21 is now complete (2 of 2 plans). Ready to proceed to Phase 22 (DLQ Recovery) which will:
- Add jobs_affected counting to outage records (currently passed as 0)
- Implement DLQ recovery workflow to drain failed jobs after outages
- Add DLQ metrics to outage summary report

## Self-Check: PASSED

All claims verified:
- ✓ worker/circuit_breaker.py modified (outage_history parameter, record_outage_start call)
- ✓ worker/recovery.py modified (outage_history parameter, record_outage_end call)
- ✓ worker/processor.py modified (OutageHistory creation, passed to components)
- ✓ Stash2Plex.py modified (enhanced handle_queue_status, new handle_outage_summary, maybe_check_recovery update)
- ✓ Stash2Plex.yml modified (Outage Summary Report task registered)
- ✓ Commit 4c6e11e (Task 1 - wiring)
- ✓ Commit f161578 (Task 2 - UI integration)
- ✓ Commit 26627b4 (Task 3 - tests)
- ✓ 14 tests added, 1182 total tests pass
- ✓ Coverage 85.38% (above 80% threshold)
- ✓ All phase requirements (VISB-01, VISB-03, VISB-04) verified
