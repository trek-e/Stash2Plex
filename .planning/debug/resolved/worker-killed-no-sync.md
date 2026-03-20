---
status: resolved
trigger: "worker-killed-no-sync"
created: 2026-03-19T00:00:00Z
updated: 2026-03-19T01:00:00Z
---

## Current Focus

hypothesis: CONFIRMED — fix applied and verified
test: All 1174 tests pass after fix
expecting: Hook invocations no longer resume orphaned items; orphaned items recovered on task runs
next_action: archive

## Symptoms

expected: Worker processes queued jobs within 10s window, matches scenes in Plex, pushes metadata
actual: Worker starts, runs 10s, gets killed with "Worker thread did not stop within 10s — current job may be reprocessed". No job processing log lines. Items cycle as orphaned in-progress.
errors: WARN "Worker thread did not stop within 10s — current job may be reprocessed"
reproduction: Any scene create/update hook triggers consistently
started: After recent fixes — commits ed44192, d191a61, ff3e9ee, f226659, f464d3b, ad25896

## Eliminated

(none — root cause found on first confirmed hypothesis)

## Evidence

- timestamp: 2026-03-19T00:00:00Z
  checked: log output patterns
  found: "Resumed 1 orphaned in-progress item(s)" on EVERY invocation; no "Processing job" lines; GraphQL findScenes returns bytes:54 (empty); worker always killed at 10s
  implication: Worker is not dequeuing any items at all, or immediately blocking after start

- timestamp: 2026-03-19T00:30:00Z
  checked: QueueManager._init_queue(), sync_queue/operations.py resume_orphaned_items(), persistqueue/sqlackqueue.py _pop()/_init()
  found: auto_resume=False (set in ff3e9ee) → queue.total counts only status<2; resume_orphaned_items() does raw SQL UPDATE status=2→1 but does NOT update queue.total; _pop() SELECT WHERE status<2 would find the item, but it gets processed first due to lowest _id (FIFO)
  implication: The orphaned item IS dequeued, but library.all() in _process_job() takes >10s for large libraries or unscanned scenes, causing the 10-second hook kill to fire mid-processing

- timestamp: 2026-03-19T00:45:00Z
  checked: main() hook exit path in Stash2Plex.py
  found: For is_hook=True, main() calls initialize() then goes directly to shutdown() → worker.stop() → thread.join(timeout=10). The orphaned item (status=2 → reset to 1 by resume_orphaned_items) has the lowest _id and is always picked up first. If its _process_job() calls library.all() (scene not yet in Plex), it blocks >10s. All 50+ other jobs (scenes already in Plex, would complete in <5s) wait behind it.
  implication: Every hook invocation: orphaned item resumes, takes >10s, killed, stays orphaned. 50+ newer jobs are permanently blocked.

## Resolution

root_cause: |
  Commit ff3e9ee changed auto_resume=False to prevent cross-process races, and resume_orphaned_items()
  was added to handle crash recovery. However, resume_orphaned_items() is called on EVERY invocation
  including hook invocations, which have only a 10-second window before the worker is killed.

  An orphaned item (e.g., a new scene not yet scanned into Plex) gets reset from status=2→1 by
  resume_orphaned_items() on every hook invocation. Because it has the lowest _id (FIFO), it is always
  dequeued first. _process_job() for a scene not yet in Plex falls through to library.all() (full library
  scan), which exceeds 10 seconds. The worker is then killed mid-job → item returns to status=2.
  Next hook invocation: same cycle. All 50+ newer jobs (scenes already in Plex, would complete in <5s)
  are permanently blocked because they wait behind the orphaned item.

fix: |
  Added resume_orphaned: bool = True parameter to initialize(). For hook invocations, main() passes
  resume_orphaned=not is_hook (False for hooks, True for tasks). Hook invocations skip
  resume_orphaned_items() entirely. Orphaned items accumulate at status=2 (invisible to queue._pop()
  which selects status<2) and are safely recovered on the next task invocation, which has a 30-153
  second timeout — enough time to process even slow library.all() calls.

verification: |
  All 1174 tests pass (89.28% coverage). The fix is structurally correct: hook invocations call
  initialize(config_dict, resume_orphaned=False), which skips the resume_orphaned_items() call.
  Task invocations call initialize(config_dict, resume_orphaned=True) (default), which resumes
  orphaned items as before. Orphaned items at status=2 are not visible to the queue's _pop()
  (SELECT WHERE status < 2), so they cannot block fresh hook jobs.

files_changed:
  - Stash2Plex.py: initialize() signature + docstring, conditional resume_orphaned block, main() call site
