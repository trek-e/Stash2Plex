---
phase: 21-outage-visibility-history
plan: 01
subsystem: worker
tags: [tdd, outage-tracking, metrics, persistence]

dependency_graph:
  requires: []
  provides:
    - OutageHistory manager with circular buffer
    - Time formatting helpers (format_duration, format_elapsed_since)
    - Outage metrics calculation (MTTR, MTBF, availability)
  affects:
    - Plan 21-02 (will integrate into circuit breaker and status UI)

tech_stack:
  added:
    - collections.deque for circular buffer
    - dataclasses for OutageRecord serialization
  patterns:
    - Atomic persistence (tmp + os.replace)
    - Check-on-invocation state loading
    - Deterministic testing via 'now' parameter

key_files:
  created:
    - worker/outage_history.py (310 lines)
    - tests/worker/test_outage_history.py (449 lines)
  modified: []

decisions:
  - title: "Circular buffer with maxlen=30"
    rationale: "Automatic oldest-record eviction keeps memory bounded, simple implementation"
    alternatives: ["Manual cleanup", "Database storage"]
  - title: "Module-level formatting functions"
    rationale: "Reusable by status UI handlers, testable independently"
    alternatives: ["Class methods on OutageHistory"]
  - title: "MTBF requires >= 2 outages"
    rationale: "Cannot calculate time-between-failures with single data point"
    alternatives: ["Return None instead of 0.0"]
  - title: "Availability defaults to 100% when MTBF=0"
    rationale: "Avoids division by zero, semantically correct (no uptime span measured)"
    alternatives: ["Return None or NaN"]

metrics:
  duration_minutes: 2.6
  tests_added: 33
  test_coverage: 97
  lines_added: 759
  commits: 2
  files_created: 2
  completed: 2026-02-15
---

# Phase 21 Plan 01: OutageHistory Manager with Metrics Summary

**One-liner:** Circular buffer outage tracker with MTTR/MTBF/availability metrics and atomic JSON persistence

## Objective Achievement

Built OutageHistory manager following TDD methodology (RED-GREEN). Provides outage tracking foundation for Phase 21's visibility and reporting features.

**Core capabilities:**
- OutageRecord dataclass with started_at, ended_at, duration, jobs_affected
- OutageHistory manager with deque(maxlen=30) automatic eviction
- Atomic persistence to outage_history.json (tmp + os.replace pattern)
- record_outage_start/end methods with cross-restart resume
- format_duration: human-readable time (e.g., "1m 5s", "2h 30m")
- format_elapsed_since: relative time strings (e.g., "5m ago")
- calculate_outage_metrics: MTTR, MTBF, availability percentage

## Implementation Details

### OutageRecord Structure

```python
@dataclass
class OutageRecord:
    started_at: float
    ended_at: Optional[float] = None
    duration: Optional[float] = None
    jobs_affected: int = 0
```

### OutageHistory Manager

- **Initialization:** Loads from outage_history.json if exists, creates empty deque(maxlen=30) otherwise
- **record_outage_start:** Appends new record, saves to disk
- **record_outage_end:** Updates most recent ongoing outage (ended_at=None), calculates duration, saves
- **Persistence:** Atomic writes (tmp file + os.replace) following circuit_breaker.py pattern
- **Corruption handling:** Graceful fallback to empty deque on JSON errors

### Time Formatting

**format_duration(seconds):**
- Shows at most 2 units for brevity
- Examples: 65 → "1m 5s", 3661 → "1h 1m", 86401 → "1d 0h"
- Negative values return "0s"

**format_elapsed_since(timestamp, now):**
- Returns "{duration} ago"
- Accepts optional 'now' parameter for deterministic testing

### Metrics Calculation

**calculate_outage_metrics(history):**
- **MTTR:** Mean Time To Repair (average downtime)
- **MTBF:** Mean Time Between Failures (requires >= 2 outages, else 0.0)
- **Availability:** (MTBF / (MTBF + MTTR)) * 100, defaults to 100% when MTBF=0
- **total_downtime:** Sum of all completed outage durations
- **outage_count:** Number of completed outages
- **Ongoing outages excluded:** Only records with ended_at != None count

## Test Coverage

**33 new tests across 7 categories:**
1. OutageRecord creation (2 tests)
2. format_duration edge cases (7 tests)
3. format_elapsed_since behavior (3 tests)
4. OutageHistory basic operations (7 tests)
5. Persistence and cross-restart resume (5 tests)
6. Metrics calculation (7 tests)
7. Integration lifecycle (2 tests)

**Coverage:** 97% on worker/outage_history.py (3 lines missed: error log paths)

## Deviations from Plan

None - plan executed exactly as written. TDD flow followed strictly:
1. RED: Wrote 33 failing tests (commit 40f4856)
2. GREEN: Implemented to pass all tests (commit 1662a81)
3. REFACTOR: Not needed (implementation clean on first pass)

## Verification Results

```
$ pytest tests/worker/test_outage_history.py -v
================================ 33 passed in 0.79s ================================

$ pytest --tb=short -q
===================== 1169 passed, 143 warnings in 10.29s ======================
Coverage: 85.32% (above 80% threshold)
```

## Next Steps

Plan 21-02 will:
1. Wire OutageHistory into CircuitBreaker (record_outage_start on OPEN transition, record_outage_end on recovery)
2. Add handle_queue_status task (uses format_duration, format_elapsed_since)
3. Add handle_outage_summary task (uses calculate_outage_metrics)
4. Extend processor.py to initialize OutageHistory and call recording methods

## Self-Check: PASSED

All claims verified:
- ✓ worker/outage_history.py created (310 lines)
- ✓ tests/worker/test_outage_history.py created (449 lines)
- ✓ Commit 40f4856 (RED phase - failing tests)
- ✓ Commit 1662a81 (GREEN phase - implementation)
- ✓ All exports present: OutageRecord, OutageHistory, format_duration, format_elapsed_since, calculate_outage_metrics
- ✓ 33 tests pass, 1169 total tests pass
- ✓ Coverage 85.32% (above 80% threshold)
