---
phase: 20-graduated-recovery-rate-limiting
plan: 01
subsystem: worker
tags: [rate-limiting, graduated-recovery, token-bucket, error-monitoring, tdd]
dependency_graph:
  requires: [worker/circuit_breaker.py, worker/recovery.py, shared/log.py]
  provides: [RecoveryRateLimiter]
  affects: []
tech_stack:
  added: [token-bucket-algorithm, linear-interpolation]
  patterns: [graduated-rate-scaling, adaptive-backoff, time-injection-testing]
key_files:
  created:
    - worker/rate_limiter.py
    - tests/worker/test_rate_limiter.py
  modified: []
decisions:
  - "Token bucket capacity set to 1.0 for minimal burst (single job ahead)"
  - "Linear interpolation for rate scaling (simple, predictable behavior)"
  - "Error window of 60s for error rate calculation (recent behavior)"
  - "Backoff duration 60s before attempting recovery (reasonable cooldown)"
  - "Error rate recovery threshold 10% (well below 30% trigger for stability)"
  - "All time-dependent methods accept 'now' parameter for deterministic testing"
metrics:
  duration_minutes: 3.83
  completed_date: 2026-02-15
  task_count: 1
  test_count: 33
  file_count: 2
  commits:
    - f68a659 # RED: failing tests
    - bbe7f92 # GREEN: implementation
---

# Phase 20 Plan 01: RecoveryRateLimiter Implementation Summary

**One-liner:** Token bucket rate limiter with linear graduated scaling (5→20 jobs/sec over 5min) and adaptive backoff on error spikes

## Overview

Implemented `RecoveryRateLimiter` class to control queue drain rate after Plex recovery, preventing overwhelming a just-recovered server. Uses token bucket algorithm with graduated rate scaling and error rate monitoring.

## What Was Built

### Core Features

1. **Graduated Rate Scaling**
   - Linear interpolation from `initial_rate` (5.0) to `target_rate` (20.0) over `ramp_duration` (300s)
   - Formula: `rate = initial_rate + (target_rate - initial_rate) * (elapsed / ramp_duration)`
   - Returns `target_rate` when not in recovery period (unlimited)

2. **Token Bucket Algorithm**
   - Capacity of 1.0 token (allows single job burst)
   - Tokens refill at `current_rate()` per second
   - `should_wait()` consumes 1 token per job, returns wait time if tokens exhausted
   - No limiting outside recovery period (returns 0.0)

3. **Error Rate Monitoring**
   - Tracks success/failure results in sliding 60s window
   - Calculates `error_rate()` as failures/total
   - Triggers backoff when error rate > 30% (halves rate with `rate_multiplier=0.5`)
   - Recovers when error rate < 10% and backoff period (60s) expires

4. **Recovery Period Lifecycle**
   - `start_recovery_period()`: initiates recovery, resets state
   - `is_in_recovery_period()`: checks if currently in recovery
   - `end_recovery_period()`: clears recovery state
   - `recovery_started_at` timestamp enables cross-restart resume

### Implementation Details

**File:** `worker/rate_limiter.py` (102 statements, 91% coverage)

**Class:** `RecoveryRateLimiter`

**Key Methods:**
- `current_rate(now=None) -> float`: Graduated rate calculation
- `should_wait(now=None) -> float`: Token bucket check (0.0 = proceed, >0 = wait)
- `record_result(success: bool, now=None)`: Error tracking + adaptive backoff
- `error_rate(now=None) -> float`: Error rate in time window
- `start_recovery_period(now=None)`: Start recovery
- `end_recovery_period()`: End recovery
- `is_in_recovery_period(now=None) -> bool`: Check recovery status

**Constructor Params:**
- `initial_rate: float = 5.0` — Starting rate (jobs/sec)
- `target_rate: float = 20.0` — Full rate (jobs/sec)
- `ramp_duration: float = 300.0` — Ramp duration (seconds)
- `error_threshold: float = 0.3` — Error rate triggering backoff
- `error_window: float = 60.0` — Error rate calculation window (seconds)

**Internal State:**
- `recovery_started_at: float` — Recovery start timestamp (0.0 = not in recovery)
- `tokens: float` — Current token bucket level
- `rate_multiplier: float` — Backoff multiplier (0.5 during backoff, 1.0 normal)
- `backoff_until: float` — Backoff expiry timestamp
- `results: list` — (timestamp, success) tuples for error window

## Test Coverage

**File:** `tests/worker/test_rate_limiter.py` (33 tests, all passing)

### Test Categories

1. **Graduated Rate Calculation (7 tests)**
   - Rate at start (initial_rate)
   - Rate at midpoint (interpolated)
   - Rate at end (target_rate)
   - Rate after ramp (target_rate)
   - Linear interpolation validation
   - Custom config testing
   - Rate outside recovery (target_rate)

2. **Recovery Period Lifecycle (6 tests)**
   - `is_in_recovery_period()` not started
   - `is_in_recovery_period()` during recovery
   - `is_in_recovery_period()` after ramp
   - `start_recovery_period()` sets state
   - `end_recovery_period()` clears state
   - Cross-restart resume from existing timestamp

3. **Token Bucket (7 tests)**
   - `should_wait()` outside recovery (0.0)
   - `should_wait()` with token available (0.0)
   - `should_wait()` without tokens (>0)
   - Token refill over time
   - Burst capacity (1.0 token)
   - Rate changes accelerate refill
   - No limiting after recovery end

4. **Error Rate Monitoring (8 tests)**
   - `record_result()` success
   - `record_result()` failure
   - `error_rate()` calculation
   - Old results pruned from window
   - Backoff triggered above threshold
   - Backoff not triggered below threshold
   - Backoff reduces rate by 50%
   - Backoff recovery when error rate drops

5. **Edge Cases (5 tests)**
   - Constructor defaults
   - `now` parameter injection (all methods)
   - Empty error window (0.0 error rate)
   - Multiple `start_recovery_period()` calls reset
   - `recovery_started_at` defaults to 0.0

### Full Suite Results

```
1119 tests passed (33 new + 1086 existing)
Total coverage: 86% (above 80% threshold)
rate_limiter.py: 91% coverage (9 lines missed - logging/edge cases)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed backoff test assertions to account for graduated scaling**
- **Found during:** GREEN phase - tests failing after implementation
- **Issue:** Test `test_backoff_reduces_rate` and `test_backoff_recovery` expected static rate at different time points, but rate increases due to graduated scaling
- **Fix:** Updated test assertions to calculate expected rate at test time point: `expected = initial + (target - initial) * (elapsed / duration)`, then apply backoff multiplier. Changed from exact equality to tolerance-based assertions (`abs(rate - expected) < 0.01`)
- **Files modified:** `tests/worker/test_rate_limiter.py`
- **Commit:** bbe7f92 (same as GREEN commit - test fix was part of getting GREEN)

No other deviations - plan executed exactly as written.

## Key Decisions Made

1. **Token Bucket Capacity: 1.0**
   - Allows single job burst (minimal buffering)
   - Prevents queue buildup during rate limiting
   - Balances responsiveness vs. protection

2. **Linear Interpolation for Rate Scaling**
   - Simple, predictable behavior
   - Easy to reason about and test
   - Alternative (exponential) adds complexity without clear benefit

3. **Error Window: 60 seconds**
   - Captures recent behavior (not too short to be noisy, not too long to be stale)
   - Matches backoff duration (60s) for consistency

4. **Backoff Recovery Threshold: 10%**
   - Well below 30% trigger for stability
   - Prevents oscillation between backoff and full rate
   - Requires sustained recovery before restoring rate

5. **Time Injection via `now` Parameter**
   - All time-dependent methods accept optional `now` parameter
   - Enables deterministic testing (no real `time.time()` in tests)
   - Cleaner than mocking/patching time

## Files Changed

### Created Files

1. **worker/rate_limiter.py** (266 lines)
   - RecoveryRateLimiter class implementation
   - Graduated rate calculation with linear interpolation
   - Token bucket algorithm for throughput control
   - Error rate monitoring with adaptive backoff
   - Comprehensive docstrings and type hints

2. **tests/worker/test_rate_limiter.py** (406 lines)
   - 33 tests covering all behaviors
   - Deterministic time injection (no real time.time())
   - Test classes organized by feature area
   - Clear test names describing expected behavior

### Modified Files

None - all new code.

## Integration Points

### Dependencies (Existing)
- `shared/log.py`: Logging infrastructure
- `time` module: Time operations (with `now` parameter override)

### Provides (New)
- `RecoveryRateLimiter`: Rate limiting for post-recovery queue drain

### Future Integration
- Phase 20-02: Worker loop will use RecoveryRateLimiter during recovery
- Phase 20-02: Integration with `RecoveryState` for persistence

## Next Steps

1. **Phase 20-02: Worker Loop Integration**
   - Add `RecoveryRateLimiter` to worker processor
   - Call `should_wait()` before processing each job during recovery
   - Call `record_result()` after job completion
   - Handle recovery period lifecycle (start/end)

2. **Phase 20-03: Recovery State Persistence (if needed)**
   - Persist `recovery_started_at` timestamp across restarts
   - Load timestamp on worker startup to resume graduated rate

## Performance Notes

- Token bucket operations are O(1)
- Error rate calculation is O(n) where n = results in window (typically <100)
- Result list pruning happens on each `record_result()` call
- No thread safety needed (single worker thread per plugin invocation)

## Testing Notes

All tests use deterministic time injection:
```python
limiter = RecoveryRateLimiter()
limiter.start_recovery_period(now=1000.0)
rate = limiter.current_rate(now=1150.0)  # 150s elapsed
```

This pattern enables:
- No real delays in tests (instant)
- Reproducible behavior
- Easy testing of time-dependent edge cases

## Self-Check: PASSED

### Created Files Exist
```
✓ worker/rate_limiter.py exists (266 lines)
✓ tests/worker/test_rate_limiter.py exists (406 lines)
```

### Commits Exist
```
✓ f68a659: test(20-01): add failing tests for RecoveryRateLimiter
✓ bbe7f92: feat(20-01): implement RecoveryRateLimiter with graduated scaling and error monitoring
```

### Verification Commands
```
✓ pytest tests/worker/test_rate_limiter.py -v — all 33 tests pass
✓ pytest --tb=short — full suite passes (1119 tests, 86% coverage)
✓ python -c "from worker.rate_limiter import RecoveryRateLimiter; print('import OK')" — clean import
```

All verification steps passed successfully.
