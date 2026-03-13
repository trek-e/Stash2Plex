# T01: 14-gap-detection-engine 01

**Slice:** S01 — **Milestone:** M001

## Description

Build the gap detection engine core: a GapDetector class with three detection methods (empty metadata, stale sync, missing items) using TDD.

Purpose: This is the foundation of Phase 14. The detector is pure business logic with defined inputs/outputs -- it takes scene data dicts, sync timestamps, and Plex item metadata and returns lists of gap results. No external API calls in this plan; all dependencies are injected as data.

Output: Working, fully tested GapDetector class in `reconciliation/detector.py`.

## Must-Haves

- [ ] "Empty metadata detector identifies scenes where Plex has no meaningful metadata but Stash does"
- [ ] "Stale sync detector identifies scenes where Stash updated_at is newer than sync_timestamps entry"
- [ ] "Missing item detector identifies scenes with no recorded sync and no Plex match"
- [ ] "Detector skips scenes where sync timestamp is newer than Stash updated_at (intentional empty per LOCKED decision)"
- [ ] "Detector handles edge cases: no sync timestamps file, empty Stash library, scenes without files"

## Files

- `reconciliation/__init__.py`
- `reconciliation/detector.py`
- `tests/reconciliation/__init__.py`
- `tests/reconciliation/test_detector.py`
