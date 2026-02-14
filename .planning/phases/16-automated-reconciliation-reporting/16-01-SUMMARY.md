---
phase: 16-automated-reconciliation-reporting
plan: 01
subsystem: reconciliation
tags: [automation, scheduling, reporting]
dependency_graph:
  requires:
    - reconciliation/engine.py (gap detection)
    - reconciliation/detector.py (gap detection logic)
    - validation/config.py (plugin config)
  provides:
    - reconciliation/scheduler.py (auto-reconciliation scheduling)
    - Auto-reconciliation on startup and intervals
    - Enhanced queue status with reconciliation history
  affects:
    - Stash2Plex.py (main entry point)
    - Stash2Plex.yml (task definitions)
tech_stack:
  added:
    - reconciliation/scheduler.py (ReconciliationScheduler class)
    - reconciliation_state.json (persisted state)
  patterns:
    - Check-on-invocation pattern for non-daemon plugins
    - Atomic state persistence with tmp file + os.replace
    - Lightweight JSON state file for cross-invocation coordination
key_files:
  created:
    - reconciliation/scheduler.py (169 lines)
  modified:
    - validation/config.py (added reconcile_interval, reconcile_scope fields)
    - Stash2Plex.yml (added settings and 7-day task)
    - reconciliation/__init__.py (re-exported scheduler classes)
    - Stash2Plex.py (added maybe_auto_reconcile, _run_auto_reconcile, enhanced queue status)
    - reconciliation/engine.py (added recent_7days scope)
decisions:
  - Use check-on-invocation pattern instead of timer/thread (Stash plugins exit after each hook/task)
  - Startup trigger requires 1-hour gap to avoid rapid restart noise
  - Manual reconciliation resets auto timer (prevents duplicate runs)
  - 7-day scope maps to recent_7days engine mode (new intermediate window)
metrics:
  duration: 245s
  completed: 2026-02-14T06:33:38Z
---

# Phase 16 Plan 01: Automated Reconciliation Reporting Summary

**One-liner:** Auto-reconciliation scheduler with startup/interval triggers and queue status reporting

## What Was Built

Implemented automated reconciliation scheduling system that:
- Checks on every plugin invocation if auto-reconciliation is due (lightweight JSON read)
- Triggers reconciliation on Stash startup (if >1 hour since last run, scoped to recent scenes)
- Triggers reconciliation at configured intervals (never/hourly/daily/weekly)
- Supports configurable scopes (all/24h/7days) with new 7-day window option
- Displays reconciliation history in "View Queue Status" task (last run, gaps found by type, enqueued count)

## Tasks Completed

### Task 1: Add config settings and create reconciliation scheduler with state persistence
**Commit:** 95db3e3

Added two new config fields to Stash2PlexConfig:
- `reconcile_interval`: "never" (default), "hourly", "daily", "weekly"
- `reconcile_scope`: "all", "24h" (default), "7days"

Created ReconciliationScheduler class with:
- `is_due()`: Check if interval has elapsed
- `is_startup_due()`: Check if startup trigger should fire (never run OR >1 hour)
- `load_state()` / `save_state()`: Atomic persistence to reconciliation_state.json
- `record_run()`: Store run results (time, scope, gaps by type, enqueued count)

ReconciliationState dataclass tracks:
- `last_run_time`, `last_run_scope`, `last_gaps_found`, `last_gaps_by_type`
- `last_enqueued`, `last_scenes_checked`, `is_startup_run`, `run_count`

**Files modified:**
- validation/config.py (added fields with validators)
- Stash2Plex.yml (added UI settings)
- reconciliation/scheduler.py (created)
- reconciliation/__init__.py (re-exported)

### Task 2: Wire auto-reconciliation into plugin lifecycle and enhance queue status
**Commit:** ca54bbc

Added `maybe_auto_reconcile()` function:
- Called on every plugin invocation in main() (after disabled check, before hook/task handling)
- Lightweight check (reads one JSON file)
- Checks startup trigger first → interval trigger second
- Maps config scope to engine scope (all→all, 24h→recent, 7days→recent_7days)

Added `_run_auto_reconcile()` helper:
- Executes GapDetectionEngine.run()
- Records results via scheduler.record_run()
- Logs summary

Updated `handle_reconcile()`:
- Records manual runs in scheduler state (resets auto timer)

Enhanced `handle_queue_status()`:
- Displays "Reconciliation Status" section with last run details
- Shows gaps found by type (empty metadata, stale sync, missing)
- Indicates startup-triggered runs

Added 7-day scope support:
- `reconciliation/engine.py`: Added `recent_7days` scope (7-day lookback window)
- `Stash2Plex.yml`: Added "Reconcile Library (Last 7 Days)" task
- `Stash2Plex.py`: Added `reconcile_7days` mode dispatch
- Updated `management_modes` set

**Files modified:**
- Stash2Plex.py (added functions, wired lifecycle, enhanced status)
- Stash2Plex.yml (added 7-day task)
- reconciliation/engine.py (added recent_7days scope)

## Verification Results

All verification checks passed:

1. **Config validation:** All valid intervals (never/hourly/daily/weekly) and scopes (all/24h/7days) accepted
2. **Scheduler state persistence:** Default state loads correctly, last_run_time=0.0
3. **Full test suite:** 964 tests passed with 90% coverage (above 80% threshold)
4. **YAML valid:** Settings present in Stash2Plex.yml

## Deviations from Plan

None - plan executed exactly as written.

## Integration Points

**Upstream dependencies:**
- `reconciliation/engine.py`: Provides GapDetectionEngine.run() and GapDetectionResult
- `validation/config.py`: Provides Stash2PlexConfig model
- `sync_queue/operations.py`: Provides queue access for enqueue operations

**Downstream consumers:**
- Stash plugin settings UI (reconcile_interval, reconcile_scope)
- "View Queue Status" task (displays reconciliation history)
- Every plugin invocation triggers scheduler check (AUTO-01, AUTO-02)

## Architecture Notes

**Check-on-invocation pattern:**
Stash plugins are NOT long-running daemons. They are invoked per-event (hook or task) and exit when done. The scheduler uses a lightweight check pattern: each invocation reads reconciliation_state.json to determine if reconciliation is due.

**Startup trigger:**
Fires if last_run_time==0.0 (never run) OR elapsed time >=3600s (1 hour). This avoids rapid restart noise while ensuring new installs get an initial reconciliation.

**Manual runs reset timer:**
When a user manually triggers reconciliation, the scheduler state is updated. This prevents auto-reconciliation from running immediately after a manual run.

**7-day scope:**
New intermediate window between 24h (recent) and all. Useful for periodic reconciliation without full-library scans.

## Performance Impact

- **Per-invocation overhead:** 1 JSON read (~1ms) to check if reconciliation is due
- **Auto-reconciliation frequency:** User-configurable (never/hourly/daily/weekly)
- **Startup reconciliation:** Limited to recent scope (last 24h) to minimize initial load

## Self-Check: PASSED

**Created files exist:**
```
FOUND: reconciliation/scheduler.py
```

**Commits exist:**
```
FOUND: 95db3e3 (Task 1)
FOUND: ca54bbc (Task 2)
```

**Test coverage:**
```
PASSED: 964 tests, 90% coverage (above 80% threshold)
```
