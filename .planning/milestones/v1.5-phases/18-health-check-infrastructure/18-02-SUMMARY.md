---
phase: 18-health-check-infrastructure
plan: 02
subsystem: worker,ui
tags: [health-check, circuit-breaker, backoff, manual-task]
dependency_graph:
  requires: [plex.health, worker.backoff, worker.circuit_breaker]
  provides: [manual-health-check-task, active-health-probes]
  affects: [worker.processor, Stash2Plex]
tech_stack:
  added: []
  patterns: [hybrid-monitoring, exponential-backoff, lazy-imports]
key_files:
  created: []
  modified: [Stash2Plex.py, Stash2Plex.yml, worker/processor.py, tests/worker/test_processor.py]
decisions:
  - "Health checks do NOT directly modify circuit breaker state to avoid race conditions"
  - "Health check failures during OPEN state logged at debug level (expected/noisy)"
  - "Health check timeout is 5s (not 30s read_timeout) to avoid blocking worker thread"
metrics:
  tasks_completed: 2/2
  tests_added: 7
  files_modified: 4
  duration_minutes: 5.6
  completed: 2026-02-15
---

# Phase 18 Plan 02: Manual Health Check Task + Active Health Probes Summary

**One-liner:** Manual health check task for troubleshooting + active health probes in worker loop with exponential backoff for automatic recovery detection

## What Was Built

Implemented hybrid health monitoring with two components:

### 1. Manual Health Check Task (Stash UI)

Added "Health Check" task to Stash2Plex.yml for on-demand diagnostics:

- **Circuit Breaker State**: Reads `circuit_breaker.json` and reports CLOSED/OPEN/HALF_OPEN
  - If OPEN: shows elapsed time since circuit opened
  - Handles missing file (reports CLOSED) and corrupted file (reports UNKNOWN)
- **Plex Connectivity**: Calls `check_plex_health()` with 5s timeout
  - Reports healthy with latency or unreachable with troubleshooting hint
- **Queue Status**: Shows pending job count
  - Warns if jobs are waiting while circuit is open

Function signature: `handle_health_check()` (no arguments)

Added to `_MANAGEMENT_HANDLERS` dispatch table and `management_modes` set (worker drain skipped).

### 2. Active Health Probes in Worker Loop

Integrated health checks into `SyncWorker._worker_loop()` during OPEN circuit state:

**State Variables** (added to `__init__`):
- `_last_health_check: float = 0.0` - Timestamp of last probe
- `_health_check_interval: float = 5.0` - Initial 5s interval
- `_consecutive_health_failures: int = 0` - Failure counter for backoff

**Worker Loop Behavior** (during `can_execute() == False`):

1. **Interval Check**: Only probe if `now - _last_health_check >= _health_check_interval`
2. **Health Probe**: Call `check_plex_health(client, timeout=5.0)` using `_get_plex_client()`
3. **On Success** (is_healthy=True):
   - Log: "Plex health check passed (Xms), recovery possible"
   - Reset: `_consecutive_health_failures = 0`, `_health_check_interval = 5.0`
   - **NO direct circuit breaker modification** (avoids race condition)
4. **On Failure** (is_healthy=False):
   - Increment: `_consecutive_health_failures += 1`
   - Backoff: `calculate_delay(retry_count=failures, base=5.0, cap=60.0, jitter_seed=None)`
   - Log: "Plex health check failed (attempt #N), next check in X.Xs" (debug level)

**Exponential Backoff Progression**:
- Attempt 1: 0-10s (5 * 2^1 = 10)
- Attempt 2: 0-20s (5 * 2^2 = 20)
- Attempt 3: 0-40s (5 * 2^3 = 40)
- Attempt 4+: 0-60s (capped, with jitter)

## Test Coverage

**7 new tests in `tests/worker/test_processor.py::TestActiveHealthProbes`:**

1. `test_health_check_state_initialized` - Verifies `_last_health_check`, `_health_check_interval`, `_consecutive_health_failures` initialization
2. `test_health_check_interval_timing` - Validates interval elapsed logic
3. `test_successful_health_check_resets_state` - Confirms reset to 5s interval and 0 failures on success
4. `test_failed_health_check_uses_backoff` - Validates `calculate_delay` called with correct params
5. `test_consecutive_failures_increment` - Verifies failure counter increments
6. `test_backoff_calculation_parameters` - Validates 5s base, 60s cap across retry counts
7. `test_health_check_timeout_value` - Confirms 5s timeout constant (not config.read_timeout)

**All tests pass**: 1043 total tests, 84.84% coverage (no regressions)

## Design Decisions

### Health Check Does NOT Modify Circuit Breaker State

**Rationale**: Research pitfall #3 warned about race conditions when multiple systems modify circuit breaker state concurrently.

**Implementation**:
- Active health probes are **informational only**
- Circuit breaker's own `recovery_timeout` (60s) handles OPEN → HALF_OPEN transition
- Health check success logged at info level to notify recovery is possible
- Next `can_execute()` call will naturally transition to HALF_OPEN if timeout elapsed

This design keeps state management centralized in the circuit breaker, avoiding race conditions.

### Debug-Level Logging for Health Check Failures

Health check failures during OPEN state are **expected** and would be noisy at info level. Logged at debug level instead. Successes still logged at info level (signal recovery).

### 5s Timeout (Not config.read_timeout)

Health checks use hardcoded 5.0s timeout to avoid blocking the worker thread during outages. Normal operations use 30s `config.plex_read_timeout`, but health probes prioritize responsiveness.

## Integration Points

**Uses**:
- `plex.health.check_plex_health()` - Deep health validation via `/identity` endpoint
- `worker.backoff.calculate_delay()` - Exponential backoff with full jitter
- `worker.circuit_breaker.can_execute()` - OPEN state detection
- `plex.client.PlexClient` (via `_get_plex_client()`) - Lazy-initialized client

**Provides**:
- Manual "Health Check" task in Stash UI for troubleshooting
- Automatic recovery detection during Plex outages
- Hybrid monitoring (passive job results + active health probes)

**No breaking changes** - pure additions to existing infrastructure.

## Deviations from Plan

None - plan executed exactly as written.

Active health probes complement passive monitoring (job success/failure tracking) without replacing it, creating a hybrid monitoring system that detects recovery faster while conserving resources via backoff during extended outages.

## Commits

| Commit | Type | Description |
|--------|------|-------------|
| cb9b7d5 | feat | Add manual health check task to Stash UI |
| 2b43181 | feat | Integrate active health probes into worker loop with backoff |

## Verification

**All success criteria met**:

- ✅ "Health Check" task appears in Stash2Plex.yml
- ✅ `handle_health_check()` reports circuit state + connectivity + queue size
- ✅ Worker loop actively probes Plex during OPEN state
- ✅ Health check interval follows exponential backoff (5s → 10s → 20s → 40s → 60s cap)
- ✅ All tests pass: 1043 tests, 84.84% coverage
- ✅ No regressions in existing test suite

```bash
# Verification commands
$ grep "Health Check" Stash2Plex.yml
  - name: Health Check

$ grep "health_check" Stash2Plex.py | head -3
def handle_health_check():
    'health_check': lambda args: handle_health_check(),
    management_modes = {..., 'health_check'}

$ grep "check_plex_health" worker/processor.py
                        from plex.health import check_plex_health
                        is_healthy, latency_ms = check_plex_health(client, timeout=5.0)

$ grep "calculate_delay" worker/processor.py
                            from worker.backoff import calculate_delay
                            self._health_check_interval = calculate_delay(...)

$ python3 -m pytest tests/ -x -q
====================== 1043 passed, 145 warnings in 9.64s ======================
```

## Next Steps

Phase 19: Circuit Breaker Recovery Logic - implement HALF_OPEN → CLOSED transition logic based on successful health checks and job completions.

---

## Self-Check: PASSED

**Files verified**:
- ✅ Stash2Plex.py modified
- ✅ Stash2Plex.yml modified
- ✅ worker/processor.py modified
- ✅ tests/worker/test_processor.py modified

**Commits verified**:
- ✅ cb9b7d5 found (Task 1: manual health check)
- ✅ 2b43181 found (Task 2: active health probes)

**Functionality verified**:
- ✅ handle_health_check() function present in Stash2Plex.py
- ✅ Health Check task in Stash2Plex.yml
- ✅ _health_check_* state variables in SyncWorker.__init__
- ✅ check_plex_health import in worker loop during OPEN state
- ✅ calculate_delay integration for backoff
- ✅ 1043 tests pass, 84.84% coverage
