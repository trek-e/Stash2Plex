# S01: Gap Detection Engine

**Goal:** Build the gap detection engine core: a GapDetector class with three detection methods (empty metadata, stale sync, missing items) using TDD.
**Demo:** Build the gap detection engine core: a GapDetector class with three detection methods (empty metadata, stale sync, missing items) using TDD.

## Must-Haves


## Tasks

- [x] **T01: 14-gap-detection-engine 01**
  - Build the gap detection engine core: a GapDetector class with three detection methods (empty metadata, stale sync, missing items) using TDD.

Purpose: This is the foundation of Phase 14. The detector is pure business logic with defined inputs/outputs -- it takes scene data dicts, sync timestamps, and Plex item metadata and returns lists of gap results. No external API calls in this plan; all dependencies are injected as data.

Output: Working, fully tested GapDetector class in `reconciliation/detector.py`.
- [x] **T02: 14-gap-detection-engine 02**
  - Wire the GapDetector (from Plan 01) into a GapDetectionEngine that orchestrates end-to-end gap detection: fetch Stash scenes, match against Plex, run detectors, and enqueue discovered gaps.

Purpose: This is the integration layer that connects the pure detection logic to real infrastructure (Stash GQL, Plex matcher, persistent queue). After this plan, the gap detection engine is fully functional and ready for Phase 15's manual reconciliation trigger.

Output: Working GapDetectionEngine class in `reconciliation/engine.py` with tests.

## Files Likely Touched

- `reconciliation/__init__.py`
- `reconciliation/detector.py`
- `tests/reconciliation/__init__.py`
- `tests/reconciliation/test_detector.py`
- `reconciliation/detector.py`
- `reconciliation/engine.py`
- `tests/reconciliation/test_engine.py`
