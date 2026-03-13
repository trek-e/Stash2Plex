---
status: awaiting_human_verify
trigger: "Queue balloons to 4000+ items despite only ~20 new additions. PlexNotFound failures (27,658) recycling endlessly."
created: 2026-03-07T00:00:00Z
updated: 2026-03-07T00:00:00Z
---

## Current Focus

hypothesis: PlexNotFound items that are NOT ready for retry get nacked back into the queue, but nack makes them immediately available again. This creates a hot loop where jobs are dequeued, fail _is_ready_for_retry(), get nacked, dequeued again — thousands of times per second. The queue never shrinks because nacked items are immediately re-deliverable.
test: Trace the code path for a PlexNotFound job that has next_retry_at in the future
expecting: The item is nacked at line 409, immediately re-delivered by get_pending, fails _is_ready_for_retry again — infinite loop with only 0.1s sleep between iterations
next_action: Confirm this is the mechanism by tracing the exact code path

## Symptoms

expected: Queue should drain to near-zero. Only ~20 new items added in 24 hours.
actual: Queue balloons to 4000+ items. Timeout after 600s with 4627 remaining. 27,658 PlexNotFound errors.
errors: "PlexNotFound": 27658, "PlexTemporaryError": 65. WARN Timeout after 600s with 4627 items remaining.
reproduction: Run any queue processing - PlexNotFound items keep cycling.
started: Ongoing. v1.5.18 fixed batch path but worker path still affected.

## Eliminated

## Evidence

- timestamp: 2026-03-07T00:01:00Z
  checked: worker/processor.py lines 403-411 — _is_ready_for_retry backoff check
  found: When job is not ready for retry, it is nack_job'd (line 409) and loop continues with 0.1s sleep. But nack puts the item right back into the queue as status=ready. The SAME item will be returned by get_pending on the very next iteration.
  implication: This creates a hot loop for every item with future next_retry_at. With 4000+ items all having PlexNotFound backoff delays (30s-600s), the worker spins dequeuing and nacking the same items thousands of times.

- timestamp: 2026-03-07T00:02:00Z
  checked: PlexNotFound handler at lines 490-510
  found: PlexNotFound uses _requeue_with_metadata (ack old + put new) which correctly preserves next_retry_at. But the PROBLEM is that after requeue, the item immediately goes back to status=ready in the queue. The 0.1s sleep at line 410 is the only throttle.
  implication: With N items all waiting for retry, the worker does N * (dequeue + nack) cycles per 0.1s, generating massive churn. 27,658 PlexNotFound errors = items being re-processed after their backoff elapses, but between those windows they're being uselessly dequeued and nacked thousands of times.

- timestamp: 2026-03-07T00:03:00Z
  checked: backoff.py — PlexNotFound params are (30.0, 600.0, 12)
  found: 12 retries with 30s base delay. Items wait 30-600 seconds between retries. During ALL that wait time, the item sits in the queue being dequeued and nacked on every loop iteration.
  implication: A single PlexNotFound item generates ~300 useless dequeue/nack cycles per 30s wait (at 0.1s sleep). With 4000 items, the worker is completely saturated with nack churn and can never make progress on items that ARE ready.

## Resolution

root_cause: The _is_ready_for_retry() backoff guard at line 404 nacks items that aren't ready yet, but SQLiteAckQueue's nack() immediately makes them available again (status=ready). This creates a hot loop where the worker endlessly dequeues and nacks the same items. With thousands of PlexNotFound items all waiting for backoff delays (30-600s), the worker is completely saturated cycling through not-ready items and can never drain the queue. The queue "balloons" because new items keep arriving while the worker spins uselessly on existing ones.
fix: Added consecutive-not-ready tracking. After cycling through all not-ready items (50 or queue.size threshold), the worker sleeps until the earliest next_retry_at (clamped 1-30s) instead of spinning. Sleep uses 0.5s chunks for stop() responsiveness. Counter resets when a ready item is found or after sleeping.
verification: 142 tests pass (1 pre-existing error from persistqueue import). 25 worker/backoff/retry tests pass.
files_changed: [worker/processor.py]
