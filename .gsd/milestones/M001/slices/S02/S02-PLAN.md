# S02: Manual Reconciliation

**Goal:** Wire the GapDetectionEngine into the Stash plugin task system so users can trigger reconciliation on-demand.
**Demo:** Wire the GapDetectionEngine into the Stash plugin task system so users can trigger reconciliation on-demand.

## Must-Haves


## Tasks

- [x] **T01: 15-manual-reconciliation 01**
  - Wire the GapDetectionEngine into the Stash plugin task system so users can trigger reconciliation on-demand.

Purpose: This is the user-facing entry point for reconciliation -- Phase 14 built the engine, this phase exposes it through the Stash UI task menu with scope control and progress logging.
Output: Two new Stash tasks ("Reconcile Library (All)" and "Reconcile Library (Recent)"), a handler function, and tests.

## Files Likely Touched

- `Stash2Plex.yml`
- `Stash2Plex.py`
- `tests/reconciliation/test_reconcile_task.py`
