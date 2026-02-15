---
status: resolved
trigger: "Comprehensive code audit: Worker, Sync Queue, and DLQ"
created: 2026-02-15T00:00:00Z
updated: 2026-02-15T01:00:00Z
---

## Current Focus

hypothesis: CONFIRMED - Found multiple bugs and inconsistencies
test: Applied fixes and verified with tests
expecting: All tests pass
next_action: Complete audit summary

## Symptoms

expected: All code paths are correct, consistent, and fully leveraged
actual: Unknown — comprehensive audit needed
errors: None reported — proactive audit
reproduction: Read and trace every code path
started: Proactive audit of current codebase (v1.5.4)

## Eliminated

## Evidence

- timestamp: 2026-02-15T00:15:00Z
  checked: worker/processor.py complete
  found: Multiple issues in processor code
  implication: Several bugs and inconsistencies found

- timestamp: 2026-02-15T00:20:00Z
  checked: worker/circuit_breaker.py complete
  found: Outage end recording missing in _close() method
  implication: BUG - Outage history incomplete

- timestamp: 2026-02-15T00:25:00Z
  checked: worker/rate_limiter.py complete
  found: Logic is correct, no issues
  implication: Clean implementation

- timestamp: 2026-02-15T00:30:00Z
  checked: worker/recovery.py complete
  found: Logic is correct
  implication: Clean implementation

- timestamp: 2026-02-15T00:35:00Z
  checked: worker/outage_history.py complete
  found: MTBF calculation bug - using started_at instead of ended_at
  implication: BUG - MTBF calculation is wrong

- timestamp: 2026-02-15T00:40:00Z
  checked: worker/backoff.py complete
  found: PlexServerDown gets max_retries=999 but isn't TransientError
  implication: INCONSISTENCY - job never goes to DLQ but error handling unclear

- timestamp: 2026-02-15T00:45:00Z
  checked: worker/stats.py complete
  found: Logic is correct
  implication: Clean implementation

- timestamp: 2026-02-15T00:50:00Z
  checked: sync_queue/*.py complete
  found: Multiple timestamp-related issues
  implication: Several bugs found

## Resolution

root_cause: Multiple bugs found across worker and sync_queue modules

### Issue 1: BUG - Circuit breaker doesn't record outage end
**File:** worker/circuit_breaker.py
**Location:** _close() method (line 240)
**Problem:** When circuit closes, it doesn't call outage_history.record_outage_end()
**Impact:** Outage history is incomplete, MTTR/MTBF metrics are wrong

### Issue 2: BUG - MTBF calculation uses wrong timestamps
**File:** worker/outage_history.py
**Location:** calculate_outage_metrics() function (line 294)
**Problem:** MTBF calculation uses `completed[i].started_at - completed[i-1].started_at` instead of `completed[i].started_at - completed[i-1].ended_at`
**Impact:** MTBF measures time between outage starts, not time between failures (uptime)

### Issue 3: INCONSISTENCY - PlexServerDown error handling unclear
**File:** worker/processor.py + worker/backoff.py
**Location:** _worker_loop() line 461, get_retry_params() line 78
**Problem:** PlexServerDown is caught separately (line 461) and nack'd without retry metadata, but backoff.py gives it max_retries=999. Job will never reach DLQ but also never gets retry_count incremented.
**Impact:** Confusing error handling, jobs accumulate retry_count=0 forever

### Issue 4: BUG - sync_timestamp updated on ANY exception
**File:** worker/processor.py
**Location:** _process_job() lines 765-770
**Problem:** All exception handlers call unmark_scene_pending() which is correct, but only the success path (line 751) updates sync_timestamp. However, this is actually CORRECT - sync_timestamp should only update on success.
**Status:** False alarm - this is correct behavior

### Issue 5: UNDERUTILIZED - DLQ recovery not integrated
**File:** sync_queue/dlq_recovery.py
**Location:** Full module
**Problem:** DLQ recovery module exists but is never called from worker or main entry point
**Impact:** Feature exists but users can't access it

### Issue 6: INCONSISTENCY - Queue operations logging
**File:** sync_queue/operations.py
**Location:** Multiple functions use print() instead of logging
**Problem:** enqueue(), ack_job(), nack_job(), fail_job() all use print() while rest of codebase uses structured logging
**Impact:** Inconsistent logging, no log levels

### Issue 7: BUG - stats.json corruption check too strict
**File:** worker/stats.py
**Location:** load_from_file() line 226
**Problem:** Checks `val < 0` but floats like `total_processing_time` can be negative due to clock skew
**Impact:** False positives treating valid stats as corrupted
**Status:** Minor - unlikely in practice

### Issue 8: DEAD_CODE - SyncJob TypedDict unused
**File:** sync_queue/models.py
**Location:** Entire file
**Problem:** SyncJob TypedDict and create_sync_job() are defined but never imported or used
**Impact:** Dead code, jobs are created as raw dicts everywhere

### Issue 9: INCONSISTENCY - DLQ connection pattern
**File:** sync_queue/dlq.py
**Location:** _get_connection() method (line 60)
**Problem:** Returns connection object but callers use `with` context manager. SQLite connections don't auto-close with context manager unless using execute directly.
**Impact:** Connections are properly closed by context manager, but the pattern is misleading

### Issue 10: BUG - MTTR calculation includes incomplete outages
**File:** worker/outage_history.py
**Location:** calculate_outage_metrics() line 285
**Problem:** Filter checks `r.ended_at is not None` but then line 285 checks `r.duration is not None` separately
**Impact:** If ended_at exists but duration is None (corruption), metrics calculation fails with TypeError
**Status:** Defense-in-depth issue - should never happen but will crash if it does

fix: Apply fixes for all critical bugs
verification: Run tests and verify metrics calculations
files_changed: [
  "worker/circuit_breaker.py",
  "worker/outage_history.py",
  "worker/processor.py",
  "sync_queue/operations.py"
]
