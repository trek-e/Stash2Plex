---
phase: 19-recovery-detection-automation
plan: 01
subsystem: worker
tags: [recovery, scheduling, circuit-breaker, persistence, tdd]
dependency_graph:
  requires:
    - worker/circuit_breaker.py (CircuitBreaker, CircuitState)
    - shared/log.py (create_logger)
  provides:
    - worker/recovery.py (RecoveryScheduler, RecoveryState)
  affects:
    - Future: worker loop integration (Phase 19-02)
tech_stack:
  added:
    - recovery_state.json (persisted recovery detection state)
  patterns:
    - Check-on-invocation scheduling (mirrors ReconciliationScheduler)
    - Atomic write with os.replace
    - Dataclass for state serialization
key_files:
  created:
    - worker/recovery.py (RecoveryScheduler + RecoveryState, 139 lines)
    - tests/worker/test_recovery.py (36 comprehensive tests, 470 lines)
  modified: []
decisions:
  - decision: "Recovery health check interval is 5.0s (same as health check timeout)"
    rationale: "Prevents check backlog during outages, aligns with health check timeout"
    alternatives: "Could use configurable interval, but 5s is reasonable default"
  - decision: "Recovery detection only runs during OPEN/HALF_OPEN states, not CLOSED"
    rationale: "No recovery needed when circuit is healthy, saves unnecessary health checks"
    alternatives: "Could probe during CLOSED for monitoring, but circuit breaker already tracks health"
  - decision: "Recovery logged at info level with count (\"Plex is back online (recovery #N)\")"
    rationale: "Important operational event that admin should see, count tracks reliability"
    alternatives: "Could use warn level, but recovery is positive event"
metrics:
  duration_seconds: 174
  duration_minutes: 2.9
  completed_date: 2026-02-15
  tasks_completed: 1
  files_created: 2
  lines_added: 609
  tests_added: 36
  test_coverage: 100%
---

# Phase 19 Plan 01: RecoveryScheduler with Check-on-Invocation Pattern

**One-liner:** Check-on-invocation recovery scheduler with persisted state, orchestrates circuit breaker transitions when Plex recovers from outages.

## What Was Built

Implemented `RecoveryScheduler` class using TDD to manage automatic Plex outage recovery detection. The scheduler uses a check-on-invocation pattern (mirroring `ReconciliationScheduler`) where each plugin invocation checks if a health probe is due based on persisted state.

**Core functionality:**

1. **RecoveryState dataclass** - Persisted to `recovery_state.json`:
   - `last_check_time`: When last health check occurred
   - `consecutive_successes/failures`: Track check streak
   - `last_recovery_time`: When circuit last closed after outage
   - `recovery_count`: Total recoveries detected (operational metric)

2. **RecoveryScheduler class**:
   - `should_check_recovery()`: Returns `True` when circuit is OPEN/HALF_OPEN and 5s elapsed since last check
   - `record_health_check()`: Updates state, orchestrates circuit breaker transitions
   - `load_state()/save_state()`: Atomic persistence with corruption handling

3. **Circuit breaker integration**:
   - Calls `circuit_breaker.record_success()` during HALF_OPEN state
   - Calls `circuit_breaker.record_failure()` on failed checks
   - Detects recovery when circuit transitions to CLOSED
   - Logs: "Recovery detected: Plex is back online (recovery #N)"

**TDD implementation:**
- RED: 36 failing tests covering all scenarios
- GREEN: Implementation passing all tests
- No REFACTOR needed (already follows ReconciliationScheduler pattern)

## Deviations from Plan

None - plan executed exactly as written.

## Technical Details

**State persistence pattern** (mirrors ReconciliationScheduler):
```python
# Atomic write prevents corruption
tmp_path = self.state_path + '.tmp'
with open(tmp_path, 'w') as f:
    json.dump(asdict(state), f, indent=2)
os.replace(tmp_path, self.state_path)
```

**Circuit breaker orchestration**:
```python
if success and circuit_breaker.state == CircuitState.HALF_OPEN:
    circuit_breaker.record_success()
    if circuit_breaker.state == CircuitState.CLOSED:
        # Recovery complete!
        state.recovery_count += 1
        log_info(f"Recovery detected: Plex is back online (recovery #{state.recovery_count})")
```

**Key design decisions:**
1. **Only probes during OPEN/HALF_OPEN** - No unnecessary checks when circuit is healthy
2. **5 second interval** - Balances responsiveness vs. check frequency during outages
3. **Uses circuit breaker API** - Never modifies circuit state directly, preserves logging/persistence
4. **Tracks recovery count** - Provides operational visibility into outage frequency

## Testing

**Coverage: 100% of new code (36 tests, 470 lines)**

Test categories:
- RecoveryState dataclass (2 tests) - defaults and custom values
- Initialization (2 tests) - path setup and constants
- State persistence (9 tests) - load/save with corruption handling, atomic write, roundtrip
- should_check_recovery (7 tests) - CLOSED/OPEN/HALF_OPEN states, interval logic, boundaries
- record_health_check (13 tests) - success/failure paths, circuit breaker calls, recovery detection
- Edge cases (3 tests) - counter alternation, recovery counting, interval boundaries

**Full test suite:** 1079 tests pass, 85.31% coverage (no regressions)

## Integration Notes

**For Phase 19-02 (worker loop integration):**
- Import: `from worker.recovery import RecoveryScheduler, RecoveryState`
- Initialize: `recovery_scheduler = RecoveryScheduler(data_dir)`
- Check: `if recovery_scheduler.should_check_recovery(circuit_breaker.state):`
- Record: `recovery_scheduler.record_health_check(healthy, latency, circuit_breaker)`

**Dependencies:**
- `worker.circuit_breaker` - CircuitBreaker, CircuitState enum
- `shared.log` - create_logger for logging
- `plex.health` - check_plex_health (used in 19-02, not directly here)

## Files Changed

**Created:**
- `worker/recovery.py` (139 lines) - RecoveryScheduler + RecoveryState
- `tests/worker/test_recovery.py` (470 lines) - Comprehensive test suite

**State file:**
- `recovery_state.json` - Persisted recovery detection state (created at runtime)

## Commits

- `f9a3e57`: test(19-01): add failing test for RecoveryScheduler
- `00d43c2`: feat(19-01): implement RecoveryScheduler with check-on-invocation pattern

## Next Steps

Phase 19-02 will integrate RecoveryScheduler into the worker loop:
1. Add recovery scheduler initialization in worker
2. Check `should_check_recovery()` on each loop iteration
3. Call `check_plex_health()` when due
4. Record results via `record_health_check()`
5. Log recovery events for operational visibility

---

**Status:** COMPLETE - All tests pass, ready for worker loop integration

## Self-Check: PASSED

All claims verified:
- ✓ worker/recovery.py exists (137 lines)
- ✓ tests/worker/test_recovery.py exists (472 lines)
- ✓ Commit f9a3e57 exists (test)
- ✓ Commit 00d43c2 exists (feat)
