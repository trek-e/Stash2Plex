---
phase: 14-gap-detection-engine
plan: 02
subsystem: reconciliation
tags:
  - gap-detection
  - orchestration
  - integration
dependency_graph:
  requires:
    - 14-01 (GapDetector core logic)
  provides:
    - GapDetectionEngine class for end-to-end gap detection
    - Integration with Stash GQL, Plex matcher, and persistent queue
    - Lighter pre-check strategy for missing detection
  affects:
    - Phase 15 will use GapDetectionEngine to trigger manual reconciliation
tech_stack:
  added: []
  patterns:
    - Lazy imports for Plex dependencies
    - Batch processing for large libraries
    - Deduplication across gap types and existing queue
    - Lighter pre-check strategy (sync_timestamps before matcher)
key_files:
  created:
    - reconciliation/engine.py
    - tests/reconciliation/test_engine.py
  modified:
    - reconciliation/__init__.py
    - reconciliation/detector.py (bug fix)
decisions:
  - "Lighter pre-check for missing detection: check sync_timestamps first, then matcher only for unknowns (avoids redundant Plex API calls)"
  - "Batch processing: 100 scenes per batch with progress logging every 50 scenes"
  - "Detection-only mode: queue parameter optional, enables gap analysis without enqueue"
metrics:
  duration_seconds: 360
  test_count: 13
  coverage_percentage: 96.12
  completed_date: 2026-02-14
---

# Phase 14 Plan 02: Gap Detection Engine Orchestration Summary

**One-liner:** Full gap detection orchestrator integrating GapDetector with Stash GQL, Plex matcher, and queue enqueue, using lighter pre-check and batch processing for large libraries

## Execution

**Type:** Standard execution (auto tasks)
**Status:** Complete
**Execution time:** 6 minutes

### Tasks Completed

1. **GapDetectionEngine orchestrator with Stash/Plex integration** - Implemented full pipeline with lazy imports, batch processing, and lighter pre-check strategy
2. **Engine tests with mocked Stash/Plex/Queue** - 13 comprehensive test cases covering all orchestration scenarios

### Commits

| Commit | Type | Description |
|--------|------|-------------|
| b79bbec | feat | Add GapDetectionEngine orchestrator |
| 261d01e | fix | Convert scene_id to int for sync_timestamps lookup (deviation) |
| 026a038 | test | Add comprehensive tests for GapDetectionEngine |

## Technical Implementation

### Architecture

**GapDetectionEngine** is the integration layer connecting pure detection logic to real infrastructure:

**Run flow:**
1. Fetch Stash scenes via GQL (with scope filtering: "all" or "recent" = last 24 hours)
2. Load sync_timestamps.json from disk
3. Connect to Plex and build two data structures:
   - `plex_items_metadata`: dict mapping file_path → {studio, performers, tags, details, date}
   - `matched_paths`: set of file paths with known Plex matches
4. Run three detector methods with prepared data
5. If queue provided, enqueue gaps with deduplication
6. Return GapDetectionResult summary

**Lighter pre-check strategy for missing detection:**
- If scene has sync_timestamp entry → mark as matched, skip matcher
- If scene NOT in sync_timestamps → run full matcher
- This avoids redundant Plex API calls for already-synced scenes

**Batch processing:**
- Process scenes in batches of 100 for memory efficiency
- Log progress every 50 scenes
- Handles PlexNotFound gracefully (expected for missing items)
- Handles PlexServerDown by aborting early with partial results

**Deduplication:**
- Against existing queue: `get_queued_scene_ids()` before enqueue
- Across gap types: track enqueued scene IDs to avoid duplicates when same scene appears in multiple gap lists

### Code Quality

- **Tests:** 13 engine tests + 31 detector tests = 44 total reconciliation tests
- **Full suite:** 954 tests pass, 96.12% project coverage (above 80% threshold)
- **No warnings:** Clean test run
- **All integration scenarios covered:** empty metadata, stale sync, missing, dedup, scope filtering, error handling

### Helper Methods

**_build_plex_data()** - Heavy lifting for Plex integration:
- Connects to Plex
- Initializes PlexCache and MatchCache
- Gets library sections from config
- Processes scenes in batches to build metadata and matched_paths

**_process_scene_batch()** - Implements lighter pre-check:
- For scenes with sync_timestamp: mark matched, skip matcher
- For scenes without sync_timestamp: run find_plex_items_with_confidence
- Extract Plex metadata for matched items

**_extract_plex_metadata()** - Converts Plex data shape:
- Maps Plex actors → performers list
- Maps Plex genres → tags list
- Maps Plex summary → details field
- Handles year/originallyAvailableAt → date field

**_enqueue_gaps()** - Enqueue with deduplication:
- Load existing queue scene IDs
- Track enqueued scene IDs this run (cross-gap-type dedup)
- Build job data for each gap
- Enqueue via sync_queue.operations.enqueue

**_build_job_data()** - Extract job data from scene:
- Matches Stash2Plex.py handle_task format (lines 885-911)
- Extracts path, title, details, date, rating100
- Extracts nested studio, performers, tags, poster/background URLs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed scene_id type mismatch in detector**
- **Found during:** Task 2 (engine tests failing)
- **Issue:** scene.get('id') returns string '1', but sync_timestamps dict uses int keys. Lookup failed with `if scene_id not in sync_timestamps` because '1' != 1 in Python.
- **Fix:** Convert scene_id to int before sync_timestamps lookup in all three detector methods (detect_empty_metadata, detect_stale_syncs, detect_missing). Also ensure GapResult receives int scene_id to match dataclass type annotation.
- **Files modified:** reconciliation/detector.py
- **Commit:** 261d01e
- **Rationale:** Blocking bug preventing all gap detection (stale_sync and missing detection always failed). Auto-fixed per Rule 1 (broken behavior).

## Verification

All success criteria met:

- [x] GapDetectionEngine.run() fetches Stash scenes and runs all three detectors
- [x] Detected gaps are enqueued as standard sync jobs (same format as existing handle_task)
- [x] Queue deduplication works: scenes already in queue are skipped
- [x] Cross-gap-type deduplication works: same scene in multiple gap lists is enqueued once
- [x] Lighter pre-check for missing detection: sync_timestamps checked before invoking matcher
- [x] Scope parameter works: "all" fetches everything, "recent" filters to last 24 hours
- [x] PlexServerDown is handled gracefully with partial results
- [x] Detection-only mode works when queue=None
- [x] All tests pass, 80% coverage maintained (96.12% achieved)
- [x] Engine is ready to be invoked by Phase 15's reconciliation task handler

Commands run:

```bash
# Task 1 verification
python3 -c "from reconciliation.engine import GapDetectionEngine, GapDetectionResult; print('OK')"  # OK

# Task 2 verification
python3 -m pytest tests/reconciliation/test_engine.py -v  # 13 passed
python3 -m pytest tests/reconciliation/ -v  # 44 passed (31 detector + 13 engine)

# Full test suite
python3 -m pytest --cov --cov-fail-under=80  # 954 passed, 96.12% coverage
```

## Impact

**Completes Phase 14 gap detection engine:**
- Pure detection logic (14-01) ✓
- Orchestration and integration (14-02) ✓
- Ready for Phase 15 manual reconciliation trigger

**Architectural benefits:**
- Clean separation: detector (pure logic) vs engine (infrastructure integration)
- Lighter pre-check optimization reduces Plex API calls for already-synced scenes
- Batch processing enables gap detection on large libraries (thousands of scenes)
- Deduplication prevents queue bloat from repeated gap detection runs

**Integration points:**
- Stash GQL: reuses exact batch fragment from Stash2Plex.py (lines 799-811)
- Plex matcher: uses find_plex_items_with_confidence with cache support
- Persistent queue: uses enqueue() from sync_queue.operations
- Sync timestamps: uses load_sync_timestamps() from sync_queue.operations

## Next Steps

Phase 15 will add:
1. Manual reconciliation task handler (invokes GapDetectionEngine.run())
2. Stash plugin task UI entry point
3. Progress reporting and summary output

Gap detection engine is now fully functional and ready for user-triggered reconciliation.

## Self-Check: PASSED

All files and commits verified:
- FOUND: reconciliation/engine.py
- FOUND: reconciliation/__init__.py
- FOUND: reconciliation/detector.py (modified)
- FOUND: tests/reconciliation/test_engine.py
- FOUND: b79bbec (feat commit)
- FOUND: 261d01e (fix commit)
- FOUND: 026a038 (test commit)

---

*Completed: 2026-02-14*
*Executor: Sonnet 4.5*
*Duration: 6 minutes (360 seconds)*
