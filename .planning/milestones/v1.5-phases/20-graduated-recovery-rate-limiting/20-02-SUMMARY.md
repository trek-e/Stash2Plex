---
phase: 20-graduated-recovery-rate-limiting
plan: 02
subsystem: worker
tags: [rate-limiting, worker-loop, recovery-state, persistence, integration]
dependency_graph:
  requires: [worker/rate_limiter.py, worker/recovery.py, worker/circuit_breaker.py, worker/processor.py]
  provides: [graduated-queue-drain, cross-restart-continuity]
  affects: [worker-loop, recovery-detection]
tech_stack:
  added: []
  patterns: [cross-restart-resume, recovery-period-cleanup, chunked-sleep-for-interruption]
key_files:
  created:
    - tests/worker/test_processor.py (17 new tests in 2 test classes)
  modified:
    - worker/recovery.py
    - worker/processor.py
decisions:
  - "RecoveryState extended with recovery_started_at field (default 0.0)"
  - "clear_recovery_period() method added to RecoveryScheduler for cleanup"
  - "Rate limiter initialized in SyncWorker.__init__ with cross-restart resume"
  - "Sleep in 0.5s chunks during rate limiting for quick interruption by stop()"
  - "Recovery period state persists to recovery_state.json for cross-restart continuity"
  - "Normal operation (circuit CLOSED, no recovery) has zero overhead from rate limiter"
metrics:
  duration_minutes: 4.8
  completed_date: 2026-02-15
  task_count: 2
  test_count: 17
  file_count: 3
  commits:
    - 65530fb # Task 1: integration
    - 099d79e # Task 2: tests
---

# Phase 20 Plan 02: Worker Loop Integration Summary

**One-liner:** RecoveryRateLimiter fully integrated into worker loop with cross-restart recovery period continuity via recovery_state.json persistence

## Overview

Wired the RecoveryRateLimiter (from Plan 01) into the SyncWorker's main processing loop and extended recovery state persistence to enable cross-restart continuity of the graduated ramp. The worker now enforces rate limiting during recovery periods, detects circuit transitions to start/stop recovery, and persists recovery state so plugin restarts don't reset the graduated queue drain.

## What Was Built

### Core Integration Points

1. **RecoveryState Extension**
   - Added `recovery_started_at: float = 0.0` field to RecoveryState dataclass
   - Field persists to recovery_state.json (atomic write pattern with os.replace)
   - Set when circuit transitions HALF_OPEN->CLOSED in `record_health_check()`
   - Added `clear_recovery_period()` method to RecoveryScheduler for cleanup

2. **SyncWorker Initialization**
   - Added `_rate_limiter = RecoveryRateLimiter()` initialization
   - Added `_was_in_recovery = False` flag for tracking recovery period lifecycle
   - Cross-restart resume: loads recovery_state.json, checks `recovery_started_at > 0`
   - If recovery was active, calls `start_recovery_period(now=recovery_started_at)` to resume from prior position
   - Logs "Resuming recovery rate limiting from prior session" when resuming

3. **Worker Loop Rate Limiting**
   - Added rate limit check after circuit breaker check, before job fetch
   - Calls `should_wait()` to get wait time (0.0 = proceed, >0 = wait)
   - Sleeps in 0.5s chunks for quick interruption by `stop()`
   - Logs debug message with wait time and current rate when rate limiting active
   - Uses `continue` to skip job fetch and loop back (re-check circuit state + rate limit)

4. **Recovery Period Detection**
   - Captures circuit state BEFORE `record_success()` to detect transition
   - When `previous_state == HALF_OPEN` and `new_state == CLOSED`:
     - Calls `_rate_limiter.start_recovery_period()`
     - Sets `_was_in_recovery = True`
     - Persists `recovery_started_at = time.time()` to recovery_state.json
     - Logs "Recovery period started: graduated rate limiting enabled"

5. **Job Result Recording**
   - After successful job: `_rate_limiter.record_result(success=True)`
   - After TransientError: `_rate_limiter.record_result(success=False)`
   - After PlexServerDown: `_rate_limiter.record_result(success=False)`
   - PermanentError does NOT record (data problem, not Plex health)
   - Results feed into error rate monitoring for adaptive backoff

6. **Recovery Period Cleanup**
   - Checks `is_in_recovery_period()` on each loop iteration
   - When `is_in_recovery_period() == False` and `_was_in_recovery == True`:
     - Sets `_was_in_recovery = False`
     - Calls `scheduler.clear_recovery_period()` to reset persisted state
     - Logs "Recovery period complete: normal processing speed resumed"

### Implementation Details

**File:** `worker/recovery.py` (11 lines changed)
- RecoveryState: added `recovery_started_at: float = 0.0` field
- RecoveryScheduler.record_health_check: sets `state.recovery_started_at = time.time()` on recovery
- RecoveryScheduler.clear_recovery_period: loads state, sets `recovery_started_at = 0.0`, saves

**File:** `worker/processor.py` (76 lines added)
- SyncWorker.__init__: rate limiter initialization + cross-restart resume
- _worker_loop: rate limit check, recovery detection, result recording, cleanup

**File:** `tests/worker/test_processor.py` (283 lines added, 17 new tests)
- TestRateLimiterIntegration: 12 tests for worker loop integration
- TestRecoveryStateExtension: 5 tests for extended recovery state

## Test Coverage

**Total:** 1136 tests (1119 existing + 17 new), 85% coverage

### New Tests

**TestRateLimiterIntegration (12 tests):**
1. `test_rate_limiter_initialized` - Worker has _rate_limiter attribute
2. `test_was_in_recovery_flag_initialized` - Worker has _was_in_recovery flag
3. `test_no_rate_limiting_in_normal_operation` - Circuit CLOSED + no recovery = no wait
4. `test_cross_restart_resume_from_recovery_state` - Worker resumes from recovery_state.json
5. `test_recovery_period_starts_on_half_open_to_closed_transition` - Transition triggers start
6. `test_job_success_records_result` - Success calls record_result(success=True)
7. `test_transient_error_records_failure` - TransientError calls record_result(success=False)
8. `test_plex_server_down_records_failure` - PlexServerDown calls record_result(success=False)
9. `test_recovery_started_at_persists_to_json` - recovery_started_at saved to file
10. `test_recovery_period_cleanup_when_ramp_completes` - Cleanup when recovery ends
11. `test_rate_limiter_should_wait_during_recovery` - Tokens control job pacing
12. `test_error_rate_monitoring_triggers_backoff` - High error rate triggers backoff

**TestRecoveryStateExtension (5 tests):**
1. `test_recovery_state_has_recovery_started_at_field` - Field exists with default 0.0
2. `test_recovery_started_at_persists_to_json` - Field saves to JSON
3. `test_recovery_started_at_loads_from_json` - Field loads from JSON
4. `test_record_health_check_sets_recovery_started_at_on_recovery` - Set on transition
5. `test_clear_recovery_period_resets_recovery_started_at` - Cleanup method works

### Full Suite Results

```
1136 tests passed (17 new + 1119 existing)
Total coverage: 85% (above 80% threshold)
worker/recovery.py: 100% coverage
worker/rate_limiter.py: 96% coverage (4 lines missed - logging/edge cases)
worker/processor.py: 66% coverage (unchanged from before integration)
```

## Deviations from Plan

None - plan executed exactly as written.

## Key Decisions Made

1. **RecoveryState Extension**
   - Added `recovery_started_at` field with default 0.0 for backward compatibility
   - 0.0 means "not in recovery" (standard sentinel value)
   - Field automatically serialized/deserialized by dataclass + asdict pattern

2. **Cross-Restart Resume**
   - Load recovery_state.json in `__init__`, not in worker loop
   - Pass `recovery_started_at` as `now` parameter to `start_recovery_period()`
   - This resumes at the correct position in the ramp (not from start)

3. **Sleep Chunking**
   - Sleep in 0.5s chunks during rate limiting (not full wait_time)
   - Allows `stop()` to interrupt worker within 1s
   - Pattern: `while remaining > 0 and self.running: sleep(min(remaining, 0.5))`

4. **Recovery Period Lifecycle**
   - Track with `_was_in_recovery` flag (not just checking `is_in_recovery_period()`)
   - Detect transition from recovery->normal on each loop iteration
   - Clean up persisted state when transition detected

5. **Normal Operation Overhead**
   - `should_wait()` returns 0.0 immediately when not in recovery
   - `record_result()` still tracks results but doesn't trigger backoff
   - Zero impact on performance during normal operation (circuit CLOSED, no recovery)

## Files Changed

### Modified Files

1. **worker/recovery.py** (11 lines added)
   - RecoveryState: +1 field (recovery_started_at)
   - record_health_check: +1 line (set recovery_started_at on recovery)
   - clear_recovery_period: +9 lines (new method)

2. **worker/processor.py** (76 lines added)
   - __init__: +14 lines (rate limiter init + cross-restart resume)
   - _worker_loop rate limit check: +14 lines
   - _worker_loop cleanup check: +7 lines
   - _worker_loop success handling: +14 lines (capture state, detect transition, start recovery)
   - _worker_loop PlexServerDown handler: +3 lines (record result)
   - _worker_loop TransientError handler: +3 lines (record result)

3. **tests/worker/test_processor.py** (283 lines added)
   - TestRateLimiterIntegration: +12 tests
   - TestRecoveryStateExtension: +5 tests

## Integration Points

### Dependencies (Existing)
- `worker/rate_limiter.py`: RecoveryRateLimiter class (from Plan 01)
- `worker/recovery.py`: RecoveryScheduler, RecoveryState (extended)
- `worker/circuit_breaker.py`: CircuitBreaker, CircuitState (state detection)
- `worker/processor.py`: SyncWorker (integrated)

### Provides (New)
- Graduated queue drain during recovery periods
- Cross-restart recovery period continuity
- Error rate monitoring with adaptive backoff
- Zero-overhead rate limiting when not in recovery

### Future Work
- Phase 21-22: End-to-end testing with simulated Plex outages
- v1.5 release: Integration with full plugin lifecycle

## Behavior Flow

### Normal Operation (No Recovery)
1. Circuit: CLOSED, recovery_started_at: 0.0
2. should_wait() → 0.0 (no delay)
3. Process job → record_result(success=True)
4. Job completes normally

### Recovery Detected
1. Circuit: OPEN → health check succeeds → HALF_OPEN
2. Job succeeds → circuit HALF_OPEN->CLOSED transition
3. Detect transition, start recovery period:
   - _rate_limiter.start_recovery_period()
   - _was_in_recovery = True
   - recovery_started_at = time.time() → recovery_state.json
4. Log: "Recovery period started: graduated rate limiting enabled"

### During Recovery Period
1. should_wait() → delay (based on current rate + tokens)
2. Sleep in 0.5s chunks until delay expires
3. Process job → record_result(success/failure)
4. Error rate monitoring:
   - If error_rate > 30%: rate_multiplier = 0.5 (adaptive backoff)
   - If error_rate < 10% after 60s: rate_multiplier = 1.0 (restore)

### Recovery Period Ends
1. is_in_recovery_period() returns False (elapsed > 300s)
2. Detect transition: _was_in_recovery == True, is_in_recovery_period() == False
3. Cleanup:
   - _was_in_recovery = False
   - recovery_started_at → 0.0 in recovery_state.json
4. Log: "Recovery period complete: normal processing speed resumed"

### Plugin Restart During Recovery
1. Worker starts, loads recovery_state.json
2. Finds recovery_started_at > 0
3. Resumes: start_recovery_period(now=recovery_started_at)
4. Log: "Resuming recovery rate limiting from prior session"
5. Rate limiting continues from current position in ramp

## Performance Notes

- Rate limiting check is O(1) when not in recovery (single timestamp check)
- Token bucket operations are O(1) during recovery
- Error rate calculation is O(n) where n = results in 60s window (typically <100)
- No performance impact on normal operation (circuit CLOSED, no recovery)
- Cross-restart resume avoids restarting ramp from beginning

## Testing Notes

All tests use deterministic time injection or mocks:
```python
# Cross-restart resume test
state.recovery_started_at = time.time() - 60.0  # Started 60s ago
worker = SyncWorker(queue, dlq, config, data_dir)
assert worker._rate_limiter.is_in_recovery_period() is True
```

Mock circuit breaker used for state transitions:
```python
mock_breaker.state = CircuitState.HALF_OPEN
def transition_to_closed():
    mock_breaker.state = CircuitState.CLOSED
mock_breaker.record_success.side_effect = transition_to_closed
```

## Self-Check: PASSED

### Modified Files Exist
```
✓ worker/recovery.py exists (149 lines, +11 from before)
✓ worker/processor.py exists (1144 lines, +76 from before)
✓ tests/worker/test_processor.py exists (1700 lines, +283 from before)
```

### Commits Exist
```
✓ 65530fb: feat(20-02): integrate RecoveryRateLimiter into worker loop
✓ 099d79e: test(20-02): add integration tests for rate limiter in worker loop
```

### Verification Commands
```
✓ pytest tests/worker/test_processor.py::TestRateLimiterIntegration -v — all 12 tests pass
✓ pytest tests/worker/test_processor.py::TestRecoveryStateExtension -v — all 5 tests pass
✓ pytest tests/worker/test_processor.py tests/worker/test_recovery.py — all 107 tests pass
✓ pytest --tb=short — full suite passes (1136 tests, 85% coverage)
```

All verification steps passed successfully.
