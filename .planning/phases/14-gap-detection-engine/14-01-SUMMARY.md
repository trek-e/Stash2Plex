---
phase: 14-gap-detection-engine
plan: 01
subsystem: reconciliation
tags:
  - gap-detection
  - metadata-comparison
  - tdd
dependency_graph:
  requires: []
  provides:
    - GapDetector class with three detection methods
    - has_meaningful_metadata helper function
    - GapResult dataclass
  affects:
    - Future plan 14-02 will use GapDetector to orchestrate gap detection
tech_stack:
  added:
    - reconciliation package (new subsystem)
  patterns:
    - TDD workflow (RED-GREEN-REFACTOR)
    - Dataclass for result objects
    - Pure business logic with dependency injection
key_files:
  created:
    - reconciliation/__init__.py
    - reconciliation/detector.py
    - tests/reconciliation/__init__.py
    - tests/reconciliation/test_detector.py
  modified: []
decisions: []
metrics:
  duration_seconds: 225
  test_count: 31
  coverage_percentage: 100
  completed_date: 2026-02-14
---

# Phase 14 Plan 01: Gap Detection Engine Core Summary

**One-liner:** Pure business logic GapDetector class with three detection methods (empty metadata, stale sync, missing items) using meaningful metadata gate from handlers.py

## Execution

**Type:** TDD (RED-GREEN-REFACTOR)
**Status:** Complete
**Execution time:** 3.75 minutes

### Tasks Completed

1. **RED Phase** - Created 28 failing tests covering all three detection methods and edge cases
2. **GREEN Phase** - Implemented GapDetector with 100% passing tests, added 3 edge case tests for full coverage
3. **REFACTOR Phase** - Not needed; code was clean on first implementation

### Commits

| Commit | Type | Description |
|--------|------|-------------|
| 9a76a1e | test | Add failing tests for gap detection engine |
| ea533f5 | feat | Implement gap detection engine with 100% coverage |

## Technical Implementation

### Architecture

Created new `reconciliation` package with pure business logic detector. No external API calls - all dependencies injected as data.

**Three detection methods:**

1. **detect_empty_metadata** - Identifies scenes where Plex has no meaningful metadata but Stash does
   - Reuses the same quality gate logic from handlers.py lines 301-307
   - Checks if Plex item lacks ALL of: studio, performers, tags, details, date
   - Only reports gaps where Stash has at least one of those fields

2. **detect_stale_syncs** - Identifies scenes where Stash updated_at is newer than sync timestamp
   - Parses ISO datetime strings from Stash (handles Z -> +00:00 conversion)
   - Skips scenes where sync timestamp is newer (intentional empty per LOCKED decision)
   - Gracefully handles missing or invalid datetime values

3. **detect_missing** - Identifies scenes with no sync history and no known Plex match
   - Lighter pre-check strategy: sync_timestamps lookup first, then matched_paths check
   - Reports all missing scenes including those where file doesn't exist in Plex library
   - Caller (plan 14-02) will build matched_paths set from cache/matcher

**Helper function:**

- **has_meaningful_metadata(data: dict) -> bool** - Extracted from handlers.py inline check
  - Returns True if data has any of: studio, performers, tags, details, date
  - Reusable across detector and future code

**Result object:**

- **GapResult dataclass** - Contains scene_id, gap_type, scene_data, reason
  - scene_data is the full Stash scene dict (needed for downstream enqueue)

### Code Quality

- **Tests:** 31 tests, 100% coverage on reconciliation module
- **Full suite:** 941 tests pass, 96.42% total project coverage (above 80% threshold)
- **No warnings:** Clean test run with no new warnings
- **Edge cases:** Handles files without paths, invalid datetime formats, missing fields gracefully

## Deviations from Plan

None - plan executed exactly as written.

## Verification

All success criteria met:

- [x] GapDetector.detect_empty_metadata correctly identifies empty metadata gaps
- [x] GapDetector.detect_stale_syncs correctly identifies stale syncs
- [x] GapDetector.detect_missing correctly identifies missing items
- [x] has_meaningful_metadata works identically to handlers.py inline check
- [x] Edge case: scenes with sync timestamp newer than updated_at are skipped
- [x] Edge case: scenes without files are skipped
- [x] All tests pass, 80% coverage maintained (96.42% achieved)

Commands run:

```bash
python3 -m pytest tests/reconciliation/test_detector.py -v  # 31 passed
python3 -c "from reconciliation.detector import GapDetector, GapResult, has_meaningful_metadata; print('OK')"  # OK
python3 -m pytest --cov --cov-fail-under=80  # 941 passed, 96.42% coverage
```

## Impact

**Provides foundation for Phase 14:**
- Plan 14-02 will use GapDetector to orchestrate full gap detection workflow
- Detector is ready for integration with Stash GQL client, Plex matcher, and persistent queue

**Architectural benefits:**
- Pure business logic - easy to test, no mocking needed
- Dependency injection pattern - caller provides data, detector processes it
- Clean separation of concerns - detection logic isolated from data fetching

## Next Steps

Proceed to plan 14-02 to build the gap detection orchestrator that:
1. Fetches all Stash scenes via GQL
2. Loads sync_timestamps.json
3. Builds Plex metadata dict and matched_paths set
4. Calls GapDetector methods
5. Enqueues gaps through persistent queue

## Self-Check: PASSED

All files and commits verified:
- FOUND: reconciliation/__init__.py
- FOUND: reconciliation/detector.py
- FOUND: tests/reconciliation/__init__.py
- FOUND: tests/reconciliation/test_detector.py
- FOUND: 9a76a1e (test commit)
- FOUND: ea533f5 (feat commit)

---

*Completed: 2026-02-14*
*Executor: Sonnet 4.5*
*TDD Workflow: RED (9a76a1e) → GREEN (ea533f5)*
