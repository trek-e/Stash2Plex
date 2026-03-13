# T01: 15-manual-reconciliation 01

**Slice:** S02 — **Milestone:** M001

## Description

Wire the GapDetectionEngine into the Stash plugin task system so users can trigger reconciliation on-demand.

Purpose: This is the user-facing entry point for reconciliation -- Phase 14 built the engine, this phase exposes it through the Stash UI task menu with scope control and progress logging.
Output: Two new Stash tasks ("Reconcile Library (All)" and "Reconcile Library (Recent)"), a handler function, and tests.

## Must-Haves

- [ ] "User can trigger 'Reconcile Library' task from Stash plugin task menu"
- [ ] "User can choose reconciliation scope: all scenes or recent scenes (last 24 hours)"
- [ ] "Reconciliation logs progress summary showing gap counts by type (empty metadata: X, stale sync: Y, missing from Plex: Z)"
- [ ] "Reconciliation enqueues gaps without processing them inline"

## Files

- `Stash2Plex.yml`
- `Stash2Plex.py`
- `tests/reconciliation/test_reconcile_task.py`
