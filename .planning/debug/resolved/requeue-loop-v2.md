---
status: resolved
trigger: "requeue-loop-v2 — infinite requeue loop persists after v1.5.14 fix"
created: 2026-02-26T00:00:00Z
updated: 2026-02-26T01:00:00Z
symptoms_prefilled: true
---

## Current Focus

hypothesis: CONFIRMED — v1.5.14 fix uses a 24h window on the queue row's enqueue timestamp to include completed items in the dedup set. After >24h, completed items fall out of that window, so reconciliation re-enqueues them endlessly. Fix: add a second dedup guard in _enqueue_gaps() that skips scenes with a recent sync_timestamp entry (not dependent on queue DB row age).
test: Implement fix in reconciliation/engine.py _enqueue_gaps() — check sync_timestamps before enqueue
expecting: Reconciliation will skip scenes that have been recently synced, even if their queue row timestamp is >24h old
next_action: Implement and verify fix

## Symptoms

expected: Worker should process queued jobs and stop when queue is empty
actual: Worker continues processing indefinitely. 358K+ processed items. Job IDs cycle — new scenes (55613-55630) mixed with old scenes (10750, 16989). GraphQL burst visible after Job 16989 completion, suggesting reconciliation is firing and re-enqueuing during worker processing.
errors: No errors — all jobs succeed. The bug is that completed jobs get re-enqueued.
reproduction: Happens during normal operation on v1.5.x. Auto-reconciliation fires on each plugin invocation (hook fire), re-enqueuing scenes the worker just completed.
timeline: Ongoing from before v1.5.14 fix. Stats show processed counter continuity (355855 → 358129), suggesting same running session — plugin may not have been restarted with new code.

## Eliminated

- hypothesis: "enqueue() itself lacks dedup — bug is at the put() level"
  evidence: All callers of enqueue() go through a dedup check before calling it (get_queued_scene_ids or in-memory set). The bug is that get_queued_scene_ids() omits completed items whose queue row timestamp is >24h old.
  timestamp: 2026-02-26T01:00:00Z

- hypothesis: "hooks/handlers.py on_scene_update bypasses dedup entirely"
  evidence: on_scene_update checks is_scene_pending() (in-memory set) before calling enqueue(). The in-memory set resets on process restart — but hook handlers don't trigger the requeue loop, reconciliation does.
  timestamp: 2026-02-26T01:00:00Z

## Evidence

- timestamp: 2026-02-26T01:00:00Z
  checked: sync_queue/operations.py get_queued_scene_ids()
  found: "v1.5.14 fix IS present — uses `status = 5 AND timestamp > cutoff_24h`. The `timestamp` column stores Unix float set by `_time.time()` at put() time (confirmed from persistqueue/sqlackqueue.py line 85). This is the ENQUEUE time, not the ack time."
  implication: After a 24h+ session, completed items' enqueue timestamps fall below the cutoff. They disappear from the dedup set. Reconciliation re-enqueues them.

- timestamp: 2026-02-26T01:00:00Z
  checked: All enqueue() callers — reconciliation/engine.py, Stash2Plex.py handle_bulk_sync(), hooks/handlers.py on_scene_update(), sync_queue/dlq_recovery.py recover_outage_jobs()
  found: "Four enqueue paths total. reconciliation/engine.py and handle_bulk_sync() use get_queued_scene_ids() for dedup. on_scene_update() uses in-memory _pending_scene_ids. dlq_recovery.py uses get_queued_scene_ids(). All have dedup but all are vulnerable to the 24h window expiry."
  implication: The dedup logic is sound but the 24h window is the failure point for all paths.

- timestamp: 2026-02-26T01:00:00Z
  checked: maybe_auto_reconcile() in Stash2Plex.py + reconciliation/scheduler.py
  found: "Reconciliation fires on every plugin invocation (hook or task). Scheduler uses check-on-invocation pattern. With reconcile_interval=hourly, it fires every hour. Each run calls get_queued_scene_ids() snapshot at the start of _enqueue_gaps() loop — and that snapshot only sees completed items within 24h window."
  implication: Even if reconciliation runs every hour, once items are >24h old in the queue DB, they re-enter the gap detection loop.

- timestamp: 2026-02-26T01:00:00Z
  checked: reconciliation/detector.py detect_stale_syncs, detect_missing, detect_empty_metadata
  found: "detect_stale_syncs guards against re-enqueue by checking if sync_timestamps[scene_id] >= updated_at_epoch — will not flag if already synced. detect_missing guards by skipping if scene_id in sync_timestamps. detect_empty_metadata does NOT use sync_timestamps — it only checks if Plex currently has no metadata, regardless of whether we just synced."
  implication: detect_empty_metadata is a second path where scenes get re-enqueued despite being synced — it re-detects because Plex may not yet have the metadata (Plex processing lag) or if Plex returned empty metadata from cache. This exacerbates the loop.

- timestamp: 2026-02-26T01:00:00Z
  checked: reconciliation/engine.py _enqueue_gaps() lines 493-544
  found: "The method calls get_queued_scene_ids(queue_path) once as a snapshot, then iterates gaps. The queue_path passed is os.path.join(data_dir, 'queue') — correct. No secondary check against sync_timestamps inside _enqueue_gaps()."
  implication: Adding a sync_timestamps check inside _enqueue_gaps() would provide a persistent (not time-windowed) guard against re-enqueue of already-synced scenes.

## Resolution

root_cause: "v1.5.14 fix used a 24h window on queue row enqueue-time (`timestamp` column, set by put()) to include completed items in the dedup set. After a session runs >24h, completed items fall outside this window. reconciliation/engine.py _enqueue_gaps() then sees no completed guard and re-enqueues them. Additionally, detect_empty_metadata can re-detect scenes because it does not check sync_timestamps at all — it only checks if Plex currently has empty metadata, independent of whether the scene was recently synced."

fix: "Two-part fix: (1) In _enqueue_gaps(), add a sync_timestamps check after the queue dedup check — skip any scene whose sync_timestamp is >= its Stash updated_at epoch. This provides a persistent, time-unlimited guard. (2) Extend the completed_window in get_queued_scene_ids() from 24h to 7 days (604800s) as a defense-in-depth measure."

verification: "All 1266 applicable tests pass. 15/15 reconciliation engine tests pass. 40/40 queue operations tests pass. Pre-existing 6 manager test failures are unrelated (persistqueue import in test environment). Fix verified against original symptom: scenes already in sync_timestamps with sync_ts >= updated_at are now skipped in _enqueue_gaps() regardless of queue row age."
files_changed:
  - reconciliation/engine.py
  - sync_queue/operations.py
