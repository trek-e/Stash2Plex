---
status: resolved
trigger: "Stash2Plex worker processes jobs endlessly — 355K+ processed items and climbing. Scene IDs cycle from high numbers back to low, confirming items are being re-enqueued after successful completion."
created: 2026-02-26T00:00:00Z
updated: 2026-02-26T00:30:00Z
---

## Current Focus

hypothesis: CONFIRMED — get_queued_scene_ids() only checked status IN (0,1,2), completely missing completed items (status=5). Concurrent reconciliation and bulk sync runs re-enqueued all recently-completed scenes because they appeared as "not in queue" to the dedup check.
test: Implemented fix and verified with 9 new unit tests including explicit regression test for the infinite-requeue scenario.
expecting: Fix verified — all 1276 tests pass (2 pre-existing errors unrelated).
next_action: COMPLETE

## Symptoms

expected: Worker should process queued sync jobs and stop when queue is empty
actual: Worker processes jobs infinitely — 355K+ processed, scene IDs cycle back around indicating re-enqueue. Jobs 453-555+ observed in a 23-second window, all completing successfully. The processed counter keeps climbing (339470→339560 succeeded, 16295 failed stays constant). Match cache hit rate 99.7% confirms these are repeat scenes.
errors: No errors — every job succeeds. The bug is that completed jobs somehow get re-queued.
reproduction: Appears to happen during a "Sync All" or large batch operation on the 1.5.x branch
started: Observed live on 1.5.x branch, current version v1.5.10

## Eliminated

- hypothesis: ack_job not called after success (auto_resume reclaim)
  evidence: processor.py line 437 calls ack_job(self.queue, item) on success path, before recording scene in _recently_synced. ack IS called.
  timestamp: 2026-02-26T00:01:00Z

- hypothesis: Worker run loop itself re-enqueues
  evidence: The run() loop at line 328 only calls get_pending(), processes, and ack/nack/fail. It does not enqueue new items. The re-enqueue source must be EXTERNAL to the worker loop.
  timestamp: 2026-02-26T00:01:00Z

## Evidence

- timestamp: 2026-02-26T00:00:30Z
  checked: worker/processor.py run() loop (lines 328-509)
  found: Worker loop properly acks jobs on success (line 437), uses _recently_synced set for in-session dedup (lines 419-422, 459-460). The worker itself does NOT enqueue anything — it only dequeues and processes.
  implication: The infinite requeue source is NOT in the worker. It must be in the enqueue/batch path.

- timestamp: 2026-02-26T00:00:45Z
  checked: sync_queue/operations.py get_queued_scene_ids() (lines 250-292)
  found: Dedup function queries "WHERE status IN (0, 1, 2)" — only pending and in-progress items. Completed items (status=5) are NOT included in dedup check.
  implication: CRITICAL — If batch enqueue calls get_queued_scene_ids() to check for duplicates, it will NOT see completed items. After ack (status=5), the same scene_id can be re-enqueued because the dedup check doesn't see it as "already in queue."

- timestamp: 2026-02-26T00:01:00Z
  checked: sync_queue/operations.py enqueue() (lines 30-63)
  found: enqueue() has NO dedup logic itself — it unconditionally puts the job on the queue. All dedup must happen at the caller level.
  implication: If a caller enqueues without checking, duplicates will be created freely.

- timestamp: 2026-02-26T00:20:00Z
  checked: Stash2Plex.py handle_bulk_sync() (lines 1427-1501) and reconciliation/engine.py _enqueue_gaps() (lines 470-544)
  found: Both callers call get_queued_scene_ids() for dedup. Both miss completed items. The maybe_auto_reconcile() function (line 1613) runs on EVERY plugin invocation — each hook or task fires it. When reconciliation runs while the worker is still processing (or has just completed a batch), all processed scenes are status=5 and invisible to dedup. The _is_already_synced() secondary guard also fails because sync_timestamps are loaded once at batch start, before the worker writes them.
  implication: COMPLETE LOOP CONFIRMED — Process scene → status=5 (invisible to dedup) → auto-reconcile fires on next hook → re-enqueued → repeat. With 15K scenes and hooks firing frequently, this produces 355K+ processed items.

## Resolution

root_cause: get_queued_scene_ids() queried "WHERE status IN (0, 1, 2)" — completely missing completed items (status=5). Both handle_bulk_sync() in Stash2Plex.py and _enqueue_gaps() in reconciliation/engine.py call this function for dedup before enqueue. When auto-reconciliation fires (triggered on every plugin invocation via maybe_auto_reconcile()) while a batch is running or just finished, all recently-completed scenes appear "not in queue" to the dedup check, so they are all re-enqueued. This cycle repeats on every subsequent hook invocation, producing an infinite requeue loop. The SQLiteAckQueue schema has a `timestamp` column (float, set at row insertion time) that enables scoped lookups.
fix: Modified get_queued_scene_ids() in sync_queue/operations.py to also include status=5 (completed) rows where timestamp > time.time() - completed_window (default 86400 seconds / 24 hours). This covers all scenes touched in a recent batch, preventing re-enqueue by a concurrent run, while still allowing legitimate re-sync of stale scenes (those enqueued more than 24 hours ago will not block re-sync).
verification: 9 new unit tests in tests/sync_queue/test_operations.py, including a direct regression test (test_prevents_infinite_requeue_scenario). Full test suite: 1276 passed, 2 pre-existing errors unrelated.
files_changed:
  - sync_queue/operations.py (get_queued_scene_ids function — added completed_window parameter and OR status=5 clause)
  - tests/sync_queue/test_operations.py (added TestGetQueuedSceneIds class with 9 tests)
