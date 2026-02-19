---
status: resolved
trigger: "Every processed job logs as 'Job None completed' instead of showing a meaningful identifier"
created: 2026-02-19T00:00:00Z
updated: 2026-02-19T00:02:00Z
---

## Current Focus

hypothesis: CONFIRMED — jobs enqueued by v1.0/v1.1 lack `pqid` field; `item.get('pqid')` returns None
test: Verified via git history (v1.0.0, v1.1.5 had no pqid in enqueue()), and live test of dequeue cycle
expecting: Fix: use scene_id as fallback when pqid is absent
next_action: Apply fix to processor.py line 414 and nearby debug log on line 409

## Symptoms

expected: Job logs should include a meaningful identifier (scene ID or queue item ID) — e.g. "Job 10750 completed"
actual: Every job logs as "Job None completed" regardless of the actual job being processed
errors: No errors — the sync succeeds, but the log line always has None where an ID should be
reproduction: Run any sync batch — every job completion line shows "Job None completed"
started: Visible in current production logs. Unknown when it started showing None.

## Eliminated

- hypothesis: persist-queue strips pqid on dequeue
  evidence: Live test shows pqid round-trips correctly through enqueue/get()
  timestamp: 2026-02-19

- hypothesis: pqid not set in current enqueue()
  evidence: enqueue() in operations.py clearly sets pqid via itertools.count
  timestamp: 2026-02-19

## Evidence

- timestamp: 2026-02-19
  checked: git history for v1.0.0 and v1.1.5 enqueue() implementations
  found: v1.0.0 and v1.1.5 enqueue() did NOT include pqid field in job dict
  implication: Jobs from these old versions persist in SQLite queue DB; when auto-resumed on restart, dequeued dicts have no pqid key

- timestamp: 2026-02-19
  checked: git log for 9541ac7 (pqid fix commit)
  found: pqid was added in commit 9541ac7 at v1.2.5, AFTER v1.0 and v1.1 were released to production
  implication: Production database has old jobs without pqid; auto_resume=True resurfaces them on every startup

- timestamp: 2026-02-19
  checked: processor.py line 414 — pqid assignment
  found: `pqid = item.get('pqid')` with no fallback — returns None for old jobs
  implication: All log lines using pqid (lines 422, 425, 457, 505, 511, 532, 538, 545, 554) show "None"

- timestamp: 2026-02-19
  checked: persist-queue _find_item_id for ack behavior on old jobs
  found: Old jobs (no pqid key) fall through to cache identity search, so ack DOES work correctly
  implication: Job processing is functionally correct; only logging is broken

## Resolution

root_cause: Jobs enqueued by v1.0/v1.1 (before commit 9541ac7) have no `pqid` field. SQLiteAckQueue persists job dicts as pickled blobs; these old blobs are auto-resumed on every plugin restart (auto_resume=True). When dequeued, `item.get('pqid')` returns None. All worker loop log lines that use `pqid` show "None".
fix: |
  In processor.py _worker_loop:
  1. Moved `scene_id = item.get('scene_id')` above `pqid` extraction
  2. Changed `pqid = item.get('pqid')` to `pqid = item.get('pqid') or scene_id`
  3. Fixed debug log on line 409 to use same fallback pattern
  Now logs show scene ID (e.g., "Job 10750 completed") for old jobs, and pqid for new ones.
verification: 225 worker tests pass, 1109 total tests pass. Fix confirmed correct via git history and live enqueue/dequeue test.
files_changed:
  - worker/processor.py
