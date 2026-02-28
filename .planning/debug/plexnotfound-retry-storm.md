---
status: awaiting_human_verify
trigger: "PlexNotFound errors cause aggressive retry storm — same scene retried 3-5 times within 2 seconds instead of being deferred with backoff."
created: 2026-02-28T00:00:00Z
updated: 2026-02-28T00:10:00Z
---

## Current Focus

hypothesis: CONFIRMED — batch path (process_queue) lacks _is_ready_for_retry() check, so re-enqueued jobs are immediately re-dequeued and re-processed in the same tight loop
test: Traced code path: process_queue() in Stash2Plex.py re-enqueues with _requeue_with_metadata() but never checks backoff before pulling next job
expecting: Fix = add _is_ready_for_retry() guard before processing each job in the batch loop (and add failed scene to processed_scenes set to prevent repeat-processing within the same batch run)
next_action: Apply fix to process_queue() in Stash2Plex.py

## Symptoms

expected: When a scene gets PlexNotFound (file not yet scanned by Plex), it should be deferred/nacked with exponential backoff and retried later — not immediately retried 3-5 times in rapid succession.
actual: Logs show Scene 55650 retried 3 times, Scene 55651 retried 4 times, Scene 55652 retried 5 times — all within a 2-second window (11:05:16 to 11:05:18). This wastes resources and floods logs.
errors: PlexNotFound: Could not find Plex item for path: [various paths] — repeated 3-5x per scene
reproduction: Trigger sync for newly added scenes that Plex hasn't scanned yet. The PlexNotFound errors are retried immediately instead of being deferred.
started: Observed now (v1.5.17). The v1.5.17 fix prevented circuit breaker tripping on PlexNotFound but didn't address the aggressive retry behavior itself.

## Eliminated

- hypothesis: tenacity retry on plex/client.py or plex/matcher.py retries on PlexNotFound
  evidence: _get_retriable_exceptions() only retries ConnectionError, TimeoutError, OSError, requests ConnectionError/Timeout. PlexNotFound is not in that list.
  timestamp: 2026-02-28T00:05:00Z

- hypothesis: background worker _worker_loop retries PlexNotFound aggressively
  evidence: _worker_loop has _is_ready_for_retry() check (lines 403-411) and nacks without processing if backoff hasn't elapsed. Proper backoff IS implemented in worker loop.
  timestamp: 2026-02-28T00:05:00Z

- hypothesis: duplicate queue entries (dedup regression from v1.5.7)
  evidence: processed_scenes set in batch and _recently_synced set in worker loop both deduplicate, but ONLY on success — failed scenes can still be reprocessed.
  timestamp: 2026-02-28T00:05:00Z

## Evidence

- timestamp: 2026-02-28T00:01:00Z
  checked: worker/processor.py _worker_loop (lines 403-411)
  found: nack_job(self.queue, item); time.sleep(0.1) path is taken when _is_ready_for_retry() returns False. The backoff check exists and works.
  implication: Background worker loop correctly skips jobs that aren't ready for retry yet.

- timestamp: 2026-02-28T00:02:00Z
  checked: Stash2Plex.py process_queue() batch loop (lines 848-924)
  found: The batch while loop does get_pending(queue, timeout=1), processes, and on PlexNotFound calls _requeue_with_metadata(job) — but then immediately loops back to get_pending() with NO backoff check. There is no _is_ready_for_retry() call anywhere in the batch path.
  implication: A job re-enqueued with next_retry_at=time.time()+30 is pulled out of the queue again within milliseconds, because get_pending() doesn't know about next_retry_at — that field is stored inside the job dict payload, invisible to the queue.

- timestamp: 2026-02-28T00:03:00Z
  checked: Stash2Plex.py batch path, processed_scenes set (line 846, 876-877)
  found: processed_scenes.add(scene_id) only happens on success (line 877). On PlexNotFound, the scene is NOT added to processed_scenes. So after re-enqueueing the scene, the loop will pull it back out and process it again — same scene, same job, same PlexNotFound.
  implication: 3-5 retries within 2 seconds = queue drain speed. Each re-enqueue creates a new queue item that is pulled in the next loop iteration before get_pending() returns None (empty).

- timestamp: 2026-02-28T00:04:00Z
  checked: worker/backoff.py get_retry_params() for PlexNotFound
  found: Returns (30.0, 600.0, 12) — 30 second base delay. The next_retry_at is set correctly in the job payload. But the batch loop never reads it.
  implication: The backoff IS calculated correctly. The metadata is stored in the job. But nobody checks it in the batch path.

## Resolution

root_cause: process_queue() batch loop in Stash2Plex.py has no _is_ready_for_retry() check. After _requeue_with_metadata() puts a PlexNotFound job back in the queue with a 30s backoff timestamp, the next loop iteration immediately dequeues and re-processes it because the SQLiteAckQueue has no knowledge of next_retry_at (it's inside the job payload). This causes the 3-5 rapid retries per scene observed in logs. The background worker correctly implements this check (lines 403-411 of processor.py), but the batch path was never updated to match.

fix: Two-part fix in process_queue() in Stash2Plex.py:
  1. After get_pending() returns a job, check worker_local._is_ready_for_retry(job). If not ready, nack the job and sleep 0.1s to avoid tight spin. Continue loop.
  2. On PlexNotFound success path (job re-enqueued), add scene_id to processed_scenes so same scene can't be re-pulled in this batch run.
  Also added nack_job to the existing sync_queue.operations import line (was importing get_stats, get_pending, ack_job, fail_job — now includes nack_job).

verification: 142 previously-passing tests still pass, zero new failures. 6 pre-existing test_manager.py failures and 1 pre-existing persistqueue integration error unaffected.
files_changed: [Stash2Plex.py]
