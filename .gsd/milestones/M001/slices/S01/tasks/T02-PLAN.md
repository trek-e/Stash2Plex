# T02: 14-gap-detection-engine 02

**Slice:** S01 — **Milestone:** M001

## Description

Wire the GapDetector (from Plan 01) into a GapDetectionEngine that orchestrates end-to-end gap detection: fetch Stash scenes, match against Plex, run detectors, and enqueue discovered gaps.

Purpose: This is the integration layer that connects the pure detection logic to real infrastructure (Stash GQL, Plex matcher, persistent queue). After this plan, the gap detection engine is fully functional and ready for Phase 15's manual reconciliation trigger.

Output: Working GapDetectionEngine class in `reconciliation/engine.py` with tests.

## Must-Haves

- [ ] "Gap engine fetches all Stash scenes via GQL and runs all three gap detectors"
- [ ] "Detected gaps are enqueued as standard sync jobs through the existing persistent queue"
- [ ] "Gap engine uses lighter pre-check for missing detection: sync_timestamps first, then matcher only for unknowns"
- [ ] "Gap engine deduplicates against items already in queue before enqueuing"
- [ ] "Gap engine returns a summary with counts by gap type"

## Files

- `reconciliation/detector.py`
- `reconciliation/engine.py`
- `tests/reconciliation/test_engine.py`
