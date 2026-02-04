---
phase: 13
plan: 01
subsystem: worker
tags: [timeout, stats, queue-processing, ux]

dependency-graph:
  requires: [phase-7-stats]
  provides: [dynamic-timeout-calculation]
  affects: [hook-processing, queue-reliability]

tech-stack:
  added: []
  patterns:
    - statistical-blending
    - time-estimation

key-files:
  created: []
  modified:
    - worker/stats.py
    - Stash2Plex.py

decisions:
  - id: timeout-blending
    choice: Blend measured and default for small samples (1-4 jobs)
    rationale: Gradually trust measured data as sample size grows

metrics:
  duration: 81s
  completed: 2026-02-04
---

# Phase 13 Plan 01: Dynamic Queue Timeout Summary

Dynamic timeout calculation using measured processing times with blending for cold start and improved timeout messaging.

## What Was Built

### SyncStats.get_estimated_timeout() Method

Added to `worker/stats.py`:

```python
DEFAULT_TIME_PER_ITEM: float = 2.0  # Conservative default for cold start

def get_estimated_timeout(
    self,
    item_count: int,
    buffer_factor: float = 1.5,
    min_timeout: float = 30.0,
    max_timeout: float = 600.0
) -> float:
```

**Logic:**
- 0 jobs processed: Uses default 2.0s/item (cold start)
- 1-4 jobs processed: Blends measured with default (weight = jobs/5)
- 5+ jobs processed: Uses measured avg_processing_time
- Applies 1.5x buffer factor for safety margin
- Clamps result to [30s, 600s] range

### Dynamic Timeout in Stash2Plex.py

Replaced static formula `max(30, min(initial_size * 2, 600))` with:

```python
stats = SyncStats.load_from_file(stats_path)
max_wait = stats.get_estimated_timeout(initial_size)
```

**Improved logging:**
- Shows whether using measured average or default estimate
- Timeout message includes estimated remaining time
- Guides users to 'Process Queue' task for continuation

## Commits

| Hash | Type | Description |
|------|------|-------------|
| d9f875c | feat | add get_estimated_timeout method to SyncStats |
| f3a93d4 | feat | use dynamic timeout from SyncStats in Stash2Plex |

## Requirements Coverage

| Req | Status | Implementation |
|-----|--------|----------------|
| TIME-01 | Done | SyncStats tracks avg_processing_time, get_estimated_timeout uses it |
| TIME-02 | Done | Calculates items x avg_time x buffer_factor |
| TIME-03 | N/A | Stash doesn't expose timeout limits (confirmed by research) |
| TIME-04 | Done | max_timeout=600 handles Stash limit cap |
| TIME-05 | Done | Timeout message guides to 'Process Queue' task |

## Verification Results

```
All timeout calculation tests passed
- Cold start: 10 items -> 30s (minimum)
- Cold start: 100 items -> 300s
- Cold start: 300 items -> 600s (maximum)
- With history (1.0s avg): 10 items -> 30s (clamped from 15s)

Default timeout for 50 items: 150s
Integration pattern present in 2 files
Process Queue mentioned in timeout message
All files compile OK
```

## Deviations from Plan

None - plan executed exactly as written.

## Success Criteria Met

- [x] SyncStats.get_estimated_timeout() method exists and calculates correctly
- [x] Cold start returns conservative estimate (uses 2.0s default)
- [x] With history, uses measured avg_processing_time
- [x] Timeout clamped between 30s and 600s
- [x] Stash2Plex.py uses get_estimated_timeout() instead of static formula
- [x] Timeout message mentions "Process Queue" for continuation
- [x] All Python files compile without errors

## Next Phase Readiness

Phase 13 complete. This completes the v1.2 Queue UI Improvements milestone.

**v1.2 Milestone Summary:**
- Phase 11: Queue Management UI (queue status, clear queue, DLQ management)
- Phase 12: Process Queue Button (foreground processing, progress reporting)
- Phase 13: Dynamic Queue Timeout (measured timing, improved messaging)
