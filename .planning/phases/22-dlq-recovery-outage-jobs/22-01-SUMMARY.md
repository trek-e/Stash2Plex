---
phase: 22-dlq-recovery-outage-jobs
plan: 01
subsystem: sync_queue
tags: [dlq, recovery, outage-handling, tdd]

dependency_graph:
  requires:
    - sync_queue/dlq.py (DLQ database access)
    - sync_queue/operations.py (enqueue, get_queued_scene_ids)
    - plex/health.py (check_plex_health pre-flight gate)
    - plex/exceptions.py (error type classification)
  provides:
    - sync_queue/dlq_recovery.py (DLQ recovery operations)
  affects:
    - None (new module, no side effects on existing code)

tech_stack:
  added:
    - dataclasses (RecoveryResult)
    - sqlite3.Row (dict conversion for query results)
  patterns:
    - Three-gate validation (health → dedup → scene existence)
    - Time-windowed SQLite queries with Unix timestamp conversion
    - Idempotent recovery (safe for multiple runs)
    - In-memory deduplication (batch-level)

key_files:
  created:
    - sync_queue/dlq_recovery.py (258 lines, 98% coverage)
    - tests/sync_queue/test_dlq_recovery.py (580 lines, 23 tests)
  modified: []

decisions:
  - Conservative default: only PlexServerDown errors recovered by default
  - Optional retry types: PlexTemporaryError and PlexNotFound (user opt-in)
  - Permanent errors never recovered: PlexAuthError, PlexPermanentError, PlexPermissionError
  - Three-gate validation order: Plex health (abort early) → dedup (set-based) → scene existence (per-entry)
  - In-memory batch deduplication prevents duplicate scene_ids within same recovery run
  - Empty error_types list returns empty result (no-op)

metrics:
  duration: 320 seconds (5.33 minutes)
  completed: 2026-02-15
  test_count: 23 tests added
  coverage: 98% module coverage
  commits: 2 (RED: test-only, GREEN: implementation)
---

# Phase 22 Plan 01: DLQ Recovery Module Summary

**One-liner:** TDD implementation of DLQ recovery with error classification, time-windowed queries, and three-gate idempotent recovery

## What Was Built

Created `sync_queue/dlq_recovery.py` with three components:

1. **Error Type Classification**
   - `SAFE_RETRY_ERROR_TYPES = ["PlexServerDown"]` (conservative default)
   - `OPTIONAL_RETRY_ERROR_TYPES = ["PlexTemporaryError", "PlexNotFound"]` (user opt-in)
   - `PERMANENT_ERROR_TYPES = ["PlexAuthError", "PlexPermanentError", "PlexPermissionError"]` (never recover)
   - `get_error_types_for_recovery(include_optional)` for dynamic filtering

2. **Time-Windowed DLQ Queries**
   - `get_outage_dlq_entries(dlq, start_time, end_time, error_types)` queries DLQ SQLite database
   - Handles timestamp format mismatch: DLQ stores text timestamps ("2026-02-15 19:17:49"), query parameters are Unix floats
   - Uses `datetime(?, 'unixepoch')` for proper comparison
   - Returns list of dicts with: id, scene_id, error_type, error_message, failed_at, job_data
   - Results ordered by failed_at ASC (oldest first)

3. **Idempotent Recovery**
   - `recover_outage_jobs(dlq_entries, queue, stash, plex_client, data_dir)` with three-gate validation:
     - **Gate 1:** Plex health check (abort if unhealthy)
     - **Gate 2:** Deduplication via `get_queued_scene_ids()` (skip already queued)
     - **Gate 3:** Scene existence check via `stash.find_scene()` (skip deleted scenes)
   - Returns `RecoveryResult` dataclass with counts:
     - `recovered` (successfully re-enqueued)
     - `skipped_already_queued` (deduplication)
     - `skipped_plex_down` (health check failure)
     - `skipped_scene_missing` (scene deleted from Stash)
     - `failed` (enqueue operation failed)
     - `recovered_scene_ids` (list of successfully recovered scene_ids)
   - In-memory batch deduplication prevents duplicate scene_ids within same run
   - Idempotent: safe to run multiple times (second run skips all entries already queued)

## Test Coverage

**23 tests across 3 test classes:**

1. **TestErrorClassification (7 tests):**
   - Safe/optional/permanent error type constants validation
   - `get_error_types_for_recovery()` with include_optional=False/True
   - Permanent errors never appear in recovery lists

2. **TestGetOutageDLQEntries (8 tests):**
   - Empty DLQ returns empty list
   - Entries outside time window excluded
   - Entries with wrong error type excluded
   - Matching entries returned with all fields
   - Results ordered by failed_at ASC
   - Multiple error types in filter
   - Boundary tests: exact start_time and end_time included

3. **TestRecoverOutageJobs (8 tests):**
   - RecoveryResult dataclass field validation
   - Plex unhealthy skips all entries (Gate 1)
   - All entries already queued skipped (Gate 2)
   - Scene missing from Stash skipped (Gate 3)
   - Successful recovery with enqueue call verification
   - Duplicate scene_id in batch (in-memory dedup)
   - Mixed results (recovered + multiple skip reasons)
   - Enqueue failure increments failed count
   - Idempotent: run twice skips all on second run

**Coverage:** 98% (only missing line 113: empty error_types early return)

## Deviations from Plan

None - plan executed exactly as written.

## Technical Highlights

1. **Timestamp Format Mismatch Handling:**
   - Plan explicitly warned about DLQ's `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` (text) vs. Unix floats
   - Implementation uses `datetime(?, 'unixepoch')` in WHERE clause for proper comparison
   - Tests verify boundary conditions (exact start/end time)

2. **Three-Gate Validation Order:**
   - Gate 1 (Plex health) aborts early if Plex unhealthy → avoids unnecessary DB queries
   - Gate 2 (deduplication) uses set lookup → O(1) per-entry check
   - Gate 3 (scene existence) uses StashInterface → only for non-queued scenes

3. **Idempotency:**
   - First run: entries recovered, added to queue
   - Second run: all entries already in queue → skipped_already_queued count matches total
   - Test `test_idempotent_run_twice` verifies this behavior

4. **In-Memory Batch Deduplication:**
   - `already_queued` set updated after each successful enqueue
   - Prevents duplicate scene_ids within same batch (e.g., multiple DLQ entries for same scene)
   - Test `test_duplicate_scene_id_in_batch` verifies first entry recovered, second skipped

## Integration Points

**Imports from existing modules:**
- `plex.health.check_plex_health` - pre-flight gate
- `sync_queue.operations.get_queued_scene_ids` - deduplication
- `sync_queue.operations.enqueue` - re-queue jobs
- `sync_queue.dlq.DeadLetterQueue._get_connection()` - SQLite access

**Will be used by (Phase 22 Plan 02):**
- Task execution handlers (manual recovery task)
- Outage window detection → automatic recovery trigger

## What's Next

Phase 22 Plan 02 will integrate this module with:
1. Manual recovery task (user-triggered via Stash UI)
2. Automatic recovery after outage windows (using OutageHistory)
3. UI for selecting error types (safe vs. safe+optional)
4. Recovery metrics tracking and reporting

## Self-Check: PASSED

**Created files exist:**
- FOUND: sync_queue/dlq_recovery.py
- FOUND: tests/sync_queue/test_dlq_recovery.py

**Commits exist:**
- FOUND: e807b81 (test(22-01): add failing test for DLQ recovery module)
- FOUND: 1a12598 (feat(22-01): implement DLQ recovery module)

**Test results:**
- 23/23 tests passing
- No regressions in full suite (1205 tests total)
- Module coverage: 98%
- Overall coverage: 86% (above 80% threshold)
