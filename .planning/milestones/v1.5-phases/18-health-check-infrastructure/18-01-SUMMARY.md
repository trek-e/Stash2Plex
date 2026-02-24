---
phase: 18-health-check-infrastructure
plan: 01
subsystem: plex
tags: [health-check, tdd, infrastructure]
dependency_graph:
  requires: [plex.client, plex.exceptions, shared.log]
  provides: [plex.health.check_plex_health]
  affects: []
tech_stack:
  added: []
  patterns: [TDD, deep-health-check, /identity-endpoint]
key_files:
  created: [plex/health.py, tests/plex/test_health.py]
  modified: []
decisions: []
metrics:
  tasks_completed: 1/1
  tests_added: 12
  files_created: 2
  duration_minutes: 1.82
  completed: 2026-02-15
---

# Phase 18 Plan 01: Deep Plex Health Check Summary

**One-liner:** Deep health check using `/identity` endpoint to validate full Plex API readiness (database + HTTP)

## What Was Built

Created `plex/health.py` with `check_plex_health()` function that performs deep health validation via the `/identity` endpoint. Unlike simple TCP or HTTP checks, this endpoint requires database access, ensuring Plex is fully operational before reporting healthy status.

### Function Signature

```python
def check_plex_health(plex_client: PlexClient, timeout: float = 5.0) -> Tuple[bool, float]
```

**Returns:**
- `(True, latency_ms)` if server responds to `/identity` within timeout
- `(False, 0.0)` if server is unreachable, times out, or returns any error

### Key Implementation Details

1. **Deep Health Check Pattern**: Uses `server.query('/identity')` which requires database access, preventing false positives during Plex's multi-stage startup (port open → HTTP → database → API ready)

2. **Short Default Timeout**: 5.0 seconds (not 30s like normal operations) to avoid blocking worker thread during outages

3. **Precise Latency Measurement**: Uses `time.perf_counter()` for sub-millisecond precision

4. **Broad Exception Handling**: Catches `Exception` (not specific types) since any failure means "not healthy"

5. **Debug-Level Logging**: Failures logged at debug level since outages are expected and would be noisy at info level. Caller decides appropriate log level.

## Test Coverage

**12 tests, 100% coverage of health.py:**

### Success Cases (3 tests)
- Successful health check returns (True, latency_ms) with latency > 0
- Latency measurement is accurate (validates ~100ms response time)
- Custom timeout parameter passed through to server.query

### Failure Cases (6 tests)
- ConnectionError → (False, 0.0)
- TimeoutError → (False, 0.0)
- requests.exceptions.Timeout → (False, 0.0)
- Server 503 (database loading) → (False, 0.0)
- Generic Exception → (False, 0.0)
- OSError (network unreachable) → (False, 0.0)

### Edge Cases (3 tests)
- Default timeout is 5.0 seconds (verified via mock assertion)
- Failure latency is exactly 0.0, never negative
- `/identity` endpoint is used (not `/` or other endpoints)

## Deviations from Plan

None - plan executed exactly as written. TDD workflow followed: RED (failing tests) → GREEN (passing implementation) → no refactoring needed.

## Integration Points

**Provides:**
- `plex.health.check_plex_health()` - used by:
  - Manual health check task (Phase 18-02, next plan)
  - Worker loop integration (future phase)
  - Circuit breaker health detection (future phase)

**Depends on:**
- `plex.client.PlexClient` - server property provides PlexServer instance
- `shared.log.create_logger()` - Stash logging protocol with component prefix

**No breaking changes** - pure addition, no modifications to existing code.

## Commits

| Commit | Type | Description |
|--------|------|-------------|
| 685513b | test | Add failing tests for check_plex_health (14 test cases) |
| 7ac882d | feat | Implement check_plex_health function (79 lines) |

## Verification

**All success criteria met:**

- ✅ plex/health.py exists with check_plex_health() function
- ✅ All test cases pass: success, connection error, timeout, 503, custom timeout
- ✅ Function signature: `check_plex_health(plex_client, timeout=5.0) -> Tuple[bool, float]`
- ✅ server.query('/identity') is called (not TCP connect or HTTP GET /)
- ✅ Existing test suite passes: 1036 tests, 85.35% coverage (no regressions)

```bash
# Verification commands
$ python3 -m pytest tests/plex/test_health.py -v
# 12 passed in 0.65s

$ python3 -m pytest tests/ -x -q
# 1036 passed in 9.99s, 85.35% coverage
```

## Next Steps

Phase 18-02: Manual Health Check Task - expose `check_plex_health()` as a Stash task for troubleshooting.

---

## Self-Check: PASSED

**Files verified:**
- ✅ plex/health.py exists
- ✅ tests/plex/test_health.py exists

**Commits verified:**
- ✅ 685513b found (test commit)
- ✅ 7ac882d found (feat commit)

**Function signature verified:**
- ✅ Uses server.query('/identity', timeout=timeout)
- ✅ Default timeout is 5.0 seconds

**Test suite verified:**
- ✅ 12 new tests, all passing
- ✅ 1036 total tests, 85.35% coverage
- ✅ No regressions
