---
status: resolved
trigger: "false outage stuck queue — 3 interrelated bugs"
created: 2026-02-23
updated: 2026-02-23
---

## Current Focus

hypothesis: All three root causes confirmed and fixed
test: Implemented fixes, verified 316 tests pass (91 reconciliation + 225 worker)
expecting: Deployment verification by user
next_action: archive

## Symptoms

expected: No outage shown (Plex is reachable), queue items processed by background worker, reconciliation gaps enqueued
actual: False "ONGOING (2d 14h)" outage, worker killed after 10s, gaps found but not enqueued
errors: "WARN Worker thread did not stop within 10s — current job may be reprocessed"
reproduction: Run queue_status task (false outage), add scenes (stuck in queue), batch sync works fine manually
started: Ongoing, discovered during v1.5 outage resilience milestone

## Eliminated

- hypothesis: H3 — reconciliation blocked by false outage (circuit breaker gate in engine)
  evidence: reconciliation/engine.py run() has NO circuit breaker check. The engine connects to Plex directly via _connect_to_plex(). The enqueue blockage is purely the quality gate in _enqueue_gaps().
  timestamp: 2026-02-23

## Evidence

- timestamp: 2026-02-23
  checked: outage_history.py record_outage_end() + circuit_breaker.py _close()
  found: Outage end is ONLY recorded when circuit_breaker._close() fires. _close() is ONLY called on HALF_OPEN -> CLOSED success transition. If the circuit is loaded from disk as CLOSED (process restart after circuit naturally healed), no _close() fires, so outage_history.json retains ended_at=None forever.
  implication: ROOT CAUSE BUG 1 — orphaned outage record displayed as "ONGOING (2d 14h)"

- timestamp: 2026-02-23
  checked: Stash2Plex.py wait loop (lines 1614+) — _worker_lock_fd guard and queue.size
  found: Wait loop guards on `_worker_lock_fd is not None`. Inside loop, uses `queue.size` (pending only). When worker dequeues an item (moves to in_progress state), queue.size drops to 0 even though the job is still running. Wait loop exits immediately. Then shutdown() calls worker.stop() with 10s join timeout. If the in-progress job takes >8s, warning fires.
  implication: ROOT CAUSE BUG 2 — wait loop exits too early because it ignores in_progress items

- timestamp: 2026-02-23
  checked: reconciliation/engine.py _enqueue_gaps() quality gate (line 523)
  found: `if not has_meaningful_metadata(job_data): skip` silently skips scenes with no studio/performers/tags/date/details. The 8 "Missing from Plex" scenes all lack Stash metadata. They get detected as gaps but are silently not enqueued. No log message explains this to the user.
  implication: ROOT CAUSE BUG 3 — user sees "8 gaps, 0 enqueued" with no explanation

## Resolution

root_cause: |
  BUG 1 (FALSE OUTAGE "ONGOING 2d 14h"):
  Orphaned outage_history.json record with ended_at=None. Created when circuit breaker opened. Not closed because the circuit breaker _close() method (which calls record_outage_end) never fired — the process restarted with circuit_breaker.json already showing CLOSED, so no HALF_OPEN->CLOSED transition occurred.

  BUG 2 (WORKER KILLED AFTER 10s WARNING):
  Wait loop in main() used queue.size (pending count only). When worker dequeued the job (moved to in_progress), queue.size fell to 0, loop exited, shutdown() fired. Worker had 10s to finish. Jobs taking >8s (image uploads, slow Plex) triggered the warning. Worker was killed mid-job.

  BUG 3 (RECONCILIATION ENQUEUED: 0):
  Quality gate in _enqueue_gaps() silently skips scenes without meaningful metadata (no studio/performers/tags/date/details). The 8 "Missing from Plex" scenes are all raw/untagged. This behavior is correct (syncing empty metadata would clear Plex values) but produced confusing "0 enqueued" output with no explanation.

fix: |
  BUG 1 FIX (Stash2Plex.py handle_queue_status):
  Cross-reference circuit_breaker.json when displaying outage records. If circuit is CLOSED but an outage record has ended_at=None (orphaned), display it as "resolved — circuit closed" instead of "ONGOING". No data mutation — purely display-level fix.

  BUG 2 FIX (Stash2Plex.py main wait loop):
  Use get_stats(queue_path) instead of queue.size to check both pending AND in_progress counts. Wait loop now correctly waits while any job is in flight (not just pending). Fallback to queue.size on error.

  BUG 3 FIX (reconciliation/engine.py + Stash2Plex.py):
  _enqueue_gaps() now returns a 3-tuple (enqueued, skipped_already_queued, skipped_no_metadata). GapDetectionResult gets new skipped_no_metadata field. handle_reconcile() logs "Skipped (no Stash metadata yet): N — add studio/performers/tags/date/details to allow sync". Users now understand why gaps are detected but not enqueued.

verification: |
  - 91 reconciliation tests pass (python -m pytest tests/reconciliation/)
  - 225 worker tests pass (python -m pytest tests/worker/)
  - Both modified files pass AST syntax check
  - Pre-existing test failures (mocker/plexapi) unchanged — not our fault

files_changed:
  - Stash2Plex.py: Bug 1 fix (queue_status outage display) + Bug 2 fix (wait loop uses pending+in_progress)
  - reconciliation/engine.py: Bug 3 fix (quality gate transparency — new skipped_no_metadata field + logging)
