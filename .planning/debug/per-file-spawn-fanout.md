---
slug: per-file-spawn-fanout
status: resolved
trigger: |
  Why is the plugin spawning 10-15 instances on a SINGLE file (during
  sprite/preview generation, before identify completes) when CONTEXT.md
  says non-identify hooks return immediately? The instant identification
  completes, all instances close.
created: 2026-05-17
updated: 2026-05-18
goal: find_root_cause_only
related: spawn-storm-bulk-import (released as v1.6.13 — bounded peak but did not address per-file fan-out)
resolution: |
  Released as v1.6.14 (two-fix commit on v1.x.x).

  Fix 1 — ReconciliationScheduler TOCTOU (reconciliation/scheduler.py):
    Added claim_if_due(interval, is_startup, now) that acquires LOCK_EX on
    the state lock file, re-reads last_run_time under the exclusive lock,
    writes the claim timestamp immediately if still due, and returns True.
    Concurrent callers that arrive during a slow scan see the updated
    timestamp and return False without launching a scan.
    maybe_auto_reconcile() (Stash2Plex.py) now calls claim_if_due() instead
    of is_startup_due()/is_due() so the check-and-claim is atomic.

  Fix 2 — handle_process_queue() missing exclusion lock (Stash2Plex.py +
           worker/processor.py):
    Added SyncWorker.try_acquire_drain_lock() — the shared ownership
    primitive that acquires fcntl LOCK_EX|LOCK_NB on worker.lock without
    starting a background thread. try_start_exclusive() now delegates to it
    then calls start(). handle_process_queue() calls try_acquire_drain_lock()
    before run_batch(); losers log one line and return; the winner drains the
    full queue and calls _release_lock() in a try/finally.

  Together with v1.6.13's ProcessGuard cap, this eliminates the 10-15
  concurrent process fan-out (6.3 GB RAM, 33-min CPU times) observed during
  single-file sprite/preview generation.
---

# Debug: per-file-spawn-fanout

## Symptoms

- **Expected**: A single file being processed by Stash (file scan + sprite
  gen + preview gen + identification) should produce, at most, ONE
  plugin invocation that does work (the identification hook). All other
  hook fires for that file should fast-exit via the strict-identification
  gate (`Scene.Update.Post` AND `stash_ids` present).
- **Actual**: 10-15 concurrent `Stash2Plex.py` processes alive at once
  for a SINGLE file in sprite/preview generation. Each holds 500-870 MB
  RAM and burns 80%+ CPU. Multi-minute CPU times (up to 33 minutes seen
  in a single live `ps` snapshot). They all exit the instant Stash
  identification completes for that scene.
- **Live evidence** (user-supplied `ps`/htop snapshot, 2026-05-17):
  - 15 visible `python3 Stash2Plex.py` PIDs simultaneously
  - RAM: 60M (×4 — likely just-started fast-exiters), 485M, 499M, 515M,
    518M, 520M, 524M, 528M, 534M, 870M
  - CPU TIME (cumulative): 0:25, 1:18, 1:30, 5:07, 6:22, 6:31, 7:42,
    11:04, 12:34, 13:27, 14:23, 15:14, 18:54, 33:04, 33:49
  - CPU%: 79-89% per process
- **Smoking gun**: 33-minute TIME values prove these are NOT just 5ms
  fast-exits losing the slot lottery. They are actively doing heavy work.
- **Hint from observed behavior**: "the instant it is identified it
  closes them all" — strongly suggests they are stuck on something
  scene-specific that only resolves when identification fires (most
  likely PlexNotFound retry loops on a not-yet-in-Plex file).
- **Reproduction**: Trigger sprite/preview generation in Stash on a single
  scene; observe `ps -eo pid,rss,etime,time,cmd | grep Stash2Plex`.

## Working theories (verified one or both before proposing fix)

### Theory A (primary): Queue drainers stacking up in PlexNotFound backoff loops

- During sprite/preview gen, file is not yet identified → not yet scanned
  into Plex → any sync job for it raises `PlexNotFound`.
- `PlexNotFound` has extended retry params (12 retries, 30s base, 600s
  cap — per CONTEXT.md). A drainer pinning that scene will sleep for
  many minutes before retrying.
- Each Stash hook fire during sprite gen triggers `drain_trigger.py` to
  spawn `Stash2Plex.py --task=process_queue`. Even with the cooldown,
  multiple drainers can stack up if the cooldown's TOCTOU race allows
  several past simultaneously (the same race we just fixed in v1.6.13
  for hook fan-out — does the cooldown also gate task spawns the same
  way?).
- Each drainer acquires the queue, pulls the same scene's job(s), hits
  PlexNotFound, enters backoff sleep. They DO NOT exit; they DO hold
  full plugin state in RAM (500MB+ each, consistent with observation).
- When identification completes → `trigger_plex_scan_for_scene` runs →
  Plex finds the file → next retry succeeds → all stacked drainers
  complete and exit. Matches "closes them all the instant it is
  identified" exactly.
- BUT — the `worker.lock` (`fcntl LOCK_EX | LOCK_NB`) in
  `SyncWorker.try_start_exclusive` is SUPPOSED to allow only one
  drainer at a time. If 15 drainers are alive simultaneously, either:
  - (a) the lock is not actually acquired by the daemonized drainer
        thread (only by the daemon thread, not the main process)
  - (b) `try_start_exclusive` succeeds for the first and the rest exit,
        but BEFORE they exit they did full module import + GQL config
        fetch + reconciliation check, which is enough to take a while
        and accumulate RAM/CPU
  - (c) they're NOT all drainers — they're a mix of drainers, identify
        hooks, and reconciliation runs

### Theory B (secondary): ReconciliationScheduler TOCTOU race

- `ReconciliationScheduler` is "check-on-invocation" (per CONTEXT.md):
  reads JSON state, decides if reconciliation is due, runs if so.
- If the "is_due" check is a plain JSON read + later JSON write (no
  lock), the same TOCTOU race that bit `drain_trigger.py` could bite
  here: 15 concurrent plugin invocations all read `last_run_at`, all
  see reconciliation as due, all start a full scan in parallel.
- A full scan over 39k scenes via Stash GraphQL would easily explain
  500-870 MB RAM and multi-minute CPU. (User's library has 39k+ scenes;
  see CONTEXT.md `Scope 'missing_metadata': limiting to newest 500
  scenes (of 39057)`.)
- The reconciliation scope cap (`STASH2PLEX_RECONCILE_MAX_SCENES=500`)
  bounds each individual scan, but does not prevent N parallel scans.

### Theory C (compounding): Identification gate bypass for `process_queue` task

- The strict-identification gate (`type==Scene.Update.Post AND
  input.stash_ids_present`) only applies to HOOK invocations.
- Task invocations (`process_queue`, `reconcile_all`, etc.) by design
  bypass the gate — they MUST do work.
- If `drain_trigger.py` is spawning `process_queue` tasks during sprite
  gen, those processes legitimately run to completion (and they
  legitimately load the world). The gate does not protect against this.
- Question: does sprite gen actually fire `drain_trigger.py`? It should
  only fire from identify hooks per v1.6.10. Need to confirm.

## Current Focus

- hypothesis: **CONFIRMED COMPOUND ROOT CAUSE** — see Resolution below.
- next_action: patch `maybe_auto_reconcile()` to claim-and-record before
  running (not after), eliminating the TOCTOU window. Separately review
  whether `process_queue` spawned by identify hooks should skip
  `maybe_auto_reconcile()` entirely.

## Evidence

### Live ps snapshot (2026-05-17, user-supplied)

15 simultaneous Stash2Plex.py processes during single-file preview gen:

| RSS | CPU TIME | CPU% | PID |
|---|---|---|---|
| 520M | 7:42 | 89.5 | 3457468 |
| 59.6M | 0:25 | 87.5 | 3544662 |
| 520M | 6:22 | 87.1 | 3466882 |
| 528M | 12:34 | 86.3 | 3414004 |
| 518M | 14:23 | 85.8 | 3412479 |
| 499M | 33:04 | 84.5 | 3350736 |
| 515M | 15:14 | 84.1 | 3398652 |
| 870M | 6:31 | 83.7 | 3474276 |
| 60.6M | 1:30 | 82.4 | 3530291 |
| 534M | 13:27 | 82.1 | 3414206 |
| 524M | 18:54 | 82.1 | 3387360 |
| 485M | 33:49 | 81.8 | 3350046 |
| 528M | 11:04 | 81.2 | 3433360 |
| 60.7M | 5:07 | 81.1 | 3506871 |
| 60.5M | 1:18 | 79.7 | 3537343 |

Total RAM in snapshot: ~6.3 GB (and this is for ONE file — bulk import
would multiply this).

### Observed termination behavior

User reports: "the instant it is identified it closes them all" —
all 15 processes terminate together once Stash identification fires
for the in-progress scene.

### Source analysis (2026-05-18)

#### E1 — Identify hook fires `drain_trigger.py` on EVERY identification event

`Stash2Plex.py` line 694:
```python
_trigger_async_queue_drain(server_connection)
```
Called unconditionally after `on_scene_update()`, even when `enqueued=False`
(comment: "False can mean 'already_pending'; that still needs a drainer if
none is active"). Every `Scene.Update.Post` with `stash_ids` spawns a
`Stash2Plex.py` with `{"args": {"mode": "process_queue"}}`.

#### E2 — The drain trigger cooldown is a TOCTOU race

`sync_queue/drain_trigger.py` lines 69–73:
```python
marker = os.path.join(self.data_dir, 'hook_autodrain.last')
now = time.time()
last = self._read_last_trigger(marker)
if now - last < cooldown:
    return ...  # skip
```
The read (`_read_last_trigger`) and write (`_write_last_trigger`, line 125)
are **not atomic**. Multiple concurrent identification hooks all read the
marker simultaneously (before any of them writes back), all see `elapsed >=
cooldown`, all proceed to spawn. Default cooldown is 8 seconds
(`STASH2PLEX_HOOK_AUTODRAIN_COOLDOWN_SECS`). The ProcessGuard check at
lines 77–83 is a second gate, but it has the same TOCTOU shape: all callers
read `live_count()`, all see count < cap, all spawn.

#### E3 — The spawned `process_queue` process is NOT a hook invocation

`drain_trigger.py` line 89-91 sends:
```python
payload = {
    'server_connection': server_connection or {},
    'args': {'mode': 'process_queue'},
}
```
In `main()` at line 1525:
```python
is_hook = "hookContext" in args  # → False
```
`is_hook` is **False** for all `process_queue` spawns. This has three
consequences:
1. The strict-identification gate (lines 1536–1544) is **never reached**.
2. `initialize()` is called with `start_worker=True` — the background
   worker thread is started.
3. Lines 1596–1598 execute `maybe_check_recovery()` and **`maybe_auto_reconcile()`**
   on **every single spawned drainer**.

#### E4 — `maybe_auto_reconcile()` is a pure TOCTOU: all drainers race into a full reconciliation scan

`maybe_auto_reconcile()` (Stash2Plex.py lines 1076–1120):
```python
scheduler = ReconciliationScheduler(data_dir)
if scheduler.is_startup_due():         # reads JSON with LOCK_SH (shared)
    ReconciliationRunner(...).run(...)  # does the full scan
    return                             # record_run() not called yet
if scheduler.is_due(config.reconcile_interval):
    ReconciliationRunner(...).run(...)
    return
```
`record_run()` is called **inside `ReconciliationRunner.run()`** AFTER the
scan completes (via `reconciliation/scheduler.py` line 149). The
`load_state()` used by `is_startup_due()` and `is_due()` acquires
`LOCK_SH` (shared lock, line 70 of scheduler.py), which means **all
concurrent readers succeed simultaneously**.

Race:
1. 15 `process_queue` processes all start within milliseconds of each other.
2. All call `maybe_auto_reconcile()`.
3. All call `scheduler.is_startup_due()` → `load_state()` with LOCK_SH.
4. If `last_run_time == 0.0` (first run since Stash start, or state file
   absent): all 15 return `True`.
5. All 15 spawn `ReconciliationRunner(...).run(scope="recent")`.
6. Each runner queries Stash GQL for recent scenes (up to 500), holds all
   results in RAM, does gap detection. This is the 500–870 MB RSS and
   multi-minute CPU explained.

Even if `last_run_time > 0`, the same race exists for `is_due()`: all
readers see the old timestamp simultaneously; all decide the interval has
elapsed; all run. The LOCK_SH on `load_state` is correct for read
concurrency but incorrect here — the "check then act" needs to be an
atomic claim.

#### E5 — `worker.lock` does NOT prevent the reconciliation fan-out

`try_start_exclusive()` (`worker/processor.py` lines 185–191) acquires
`fcntl LOCK_EX | LOCK_NB` on `worker.lock`. The first `process_queue`
process wins this lock and starts its background worker thread. The 14
losers return `False` and set `worker._lock_fd = None`.

HOWEVER: `maybe_auto_reconcile()` is called at line 1597, **before**
`handle_task()` at line 1608. And `maybe_auto_reconcile()` calls
`ReconciliationRunner` directly — it does NOT go through the worker or
check `_lock_fd`. The worker exclusion lock has zero effect on the
reconciliation path.

The 14 processes that lost `try_start_exclusive()` still proceed to
call `maybe_auto_reconcile()` and each starts a full reconciliation scan.

#### E6 — PlexNotFound backoff explains the "exits when identified" observation

For the single process that WON `worker.lock`: its background worker
thread dequeues the scene's job, calls `_process_job()`, and the scene
is not yet in Plex → `PlexNotFound` → `backoff.get_retry_params()` →
`(30.0, 600.0, 12)` (lines 84–86 of `worker/backoff.py`). The job is
requeued with `next_retry_at = time.time() + delay` (up to 600s). The
worker thread sits in the backoff-sleep loop at processor.py lines
647–670.

When identification fires → Plex scan runs → Plex indexes the file →
next retry attempt succeeds. This is why the single drainer process
also stays alive for up to 33 minutes.

For the 14 processes that lost `worker.lock`: they are each running a
full reconciliation scan via `ReconciliationRunner` in `maybe_auto_reconcile()`.
When identification fires and the scene appears in Plex, any reconciliation
scan that queries that scene will now find it and proceed to enqueue a
job, completing its work. If the scan was already complete (waiting for
queue drain), those processes exit naturally. This matches "closes them
all the instant it is identified."

### Summary of process accounting (15 PIDs)

| Count | What they are | Why alive | RAM | CPU |
|---|---|---|---|---|
| 1 | Won `worker.lock` — draining queue | PlexNotFound backoff sleep for the scene | ~520M | 80%+ (backoff loop) |
| ~11 | Lost `worker.lock` — running `maybe_auto_reconcile()` | Full reconciliation scan (recent scope, up to 500 scenes GQL) | 485–870M | 80%+ (GQL + gap detection) |
| ~3–4 | Blocked by ProcessGuard or still in startup | Short-lived, 60M RSS | low | transient |

## Eliminated

### Theory A (partial) — PlexNotFound backoff for queue drainers

**Partially confirmed but not the primary driver.** At most ONE process
holds `worker.lock` and can actually drain the queue; only that one process
is stuck in PlexNotFound backoff. The other 11–12 long-lived processes are
in `maybe_auto_reconcile()`, not in the queue drainer.

The PlexNotFound story does explain the single process with 33+ min CPU and
the "exits when scene is identified" behavior, but it cannot explain why 11
other processes are at 500–870 MB RSS. Those 11 are reconciliation scans.

### Theory B (ReconciliationScheduler TOCTOU) — CONFIRMED as PRIMARY cause

Confirmed. `load_state()` uses LOCK_SH (allows simultaneous readers).
`record_run()` is called only after the scan finishes, not before starting.
The check-then-act is unprotected: all concurrent callers enter the scanner
simultaneously.

### Theory C (process_queue bypasses identification gate) — CONFIRMED as MECHANISM

Confirmed. `process_queue` spawns from `drain_trigger.py` are not hooks
(`is_hook=False`). They legitimately bypass the identification gate, reach
`maybe_auto_reconcile()`, and all execute it concurrently. This is by
design for the queue-draining purpose but was never designed to handle the
case of N simultaneous drainers all calling reconciliation.

## Resolution

### ROOT CAUSE

**Compound: N concurrent `process_queue` spawns each independently racing
into `maybe_auto_reconcile()` with no mutual exclusion.**

The causal chain:

1. Stash fires rapid hook events during sprite/preview generation for a
   single file. Each `Scene.Update.Post` with `stash_ids` is an
   identification event (or appears to be if stash_ids were already set
   on the scene from a prior import). `handle_hook()` calls
   `_trigger_async_queue_drain()` every time. **`Stash2Plex.py` line 694.**

2. `drain_trigger.py` has a TOCTOU race: the cooldown marker is read and
   written non-atomically. Multiple callers all see `elapsed >= cooldown`
   and all spawn. The ProcessGuard pre-spawn check has the same shape.
   Result: N `process_queue` child processes start within milliseconds.
   **`drain_trigger.py` lines 69–83.**

3. Each spawned `process_queue` process executes `main()` with `is_hook=False`.
   This causes `maybe_auto_reconcile()` to run on every one of them.
   **`Stash2Plex.py` lines 1596–1598.**

4. `maybe_auto_reconcile()` calls `scheduler.is_startup_due()` →
   `load_state()` with `LOCK_SH`. All concurrent callers acquire the
   shared lock simultaneously and all read `last_run_time == 0.0` (or
   an old timestamp). All decide reconciliation is due and launch
   `ReconciliationRunner.run(scope="recent")`.
   **`Stash2Plex.py` lines 1101–1106; `reconciliation/scheduler.py` lines
   62–75 (LOCK_SH allows concurrent readers).**

5. Each `ReconciliationRunner.run()` performs a Stash GQL query (up to 500
   scenes with full metadata), loads results into memory, and runs gap
   detection. This is the 485–870 MB RSS and multi-minute CPU per process.
   All N scans run in parallel with no coordination.

6. `record_run()` (which would update `last_run_time`) is only called after
   each individual scan finishes. By the time the first finishes and writes
   the state, all others have already passed the check and are deep inside
   their own scans.
   **`reconciliation/scheduler.py` line 170; called from runner, not before
   the check.**

7. The single process that won `worker.lock` additionally holds its
   background worker thread in the PlexNotFound backoff loop (up to 600s),
   explaining the longest-lived process. When the scene is finally
   identified and scanned into Plex, the next retry succeeds and that
   process exits too.

**Fix direction (one line):** In `maybe_auto_reconcile()`, claim the
reconciliation slot with an exclusive lock write before running the check —
not after — so concurrent callers see an in-progress marker and skip. The
simplest form is: attempt to atomically write `last_run_time = now` to the
state file (with LOCK_EX) before deciding to run; if the write shows another
process already claimed it (timestamp changed), skip.

---

### Refined diagnosis (2026-05-18, post second ps + log)

#### New evidence supplied

- Second ps snapshot: 11 processes still alive, RSS unchanged at 60M–857M,
  CPU TIME still growing (now 17:48 max, up from prior snapshot). States
  mix of R (still actively burning 90%+ CPU) and S (sleeping). Processes
  do NOT exit — they stay open and idle once logs go quiet. User cannot
  determine from outside whether they are still doing useful work.

- Plex log from the burst window: `mode=process_queue` → `Worker Started` →
  `Starting batch processing of 18350 items...` → job completions at 2-3
  seconds per hit. `DLQ contains 23728 failed jobs`. This is `run_batch()`
  executing (not the background worker thread — the synchronous foreground
  drain path).

#### E7 — `handle_process_queue()` calls `run_batch()` with NO exclusion lock

`Stash2Plex.py` line 956: creates a fresh `SyncWorker(queue_manager, dlq, config, data_dir=data_dir)`.
`Stash2Plex.py` line 970: calls `worker_local.run_batch(...)` directly.

There is **no call to `try_start_exclusive()`** anywhere in
`handle_process_queue()`. The `worker.lock` that was designed to allow only
one active drainer is entirely bypassed for the `process_queue` task path.

In contrast, the background daemon path (`initialize()` with
`start_worker=True`) calls `try_start_exclusive()` (processor.py lines
185–211, LOCK_EX | LOCK_NB), which serialises background workers correctly.
The foreground `run_batch()` path has no such protection.

#### E8 — `SQLiteAckQueue` is multi-process safe by design, so all 11 workers dequeue independently

`sync_queue/manager.py` line 96: `multithreading=True` (thread-safe).
`persistqueue.SQLiteAckQueue` uses SQLite WAL mode and row-level locking on
`get_pending()`. Each `get_pending()` call from any process atomically dequeues
a distinct item (SQLite's `BEGIN IMMEDIATE` or equivalent). There is no cross-
process mutual exclusion at the queue level — items are simply divided up
among all concurrent callers.

With 11 concurrent `run_batch()` invocations and 18,350 items:
- Each worker independently dequeues and processes ~1,670 items
- At 2-3 seconds/job (cache hit path): ~55-80 minutes wall time per worker
- CPU TIME snapshots growing steadily are consistent with active processing,
  not idle waiting

The processes are NOT idle. They are legitimately dividing the queue backlog
across 11 concurrent workers and each processing its share until empty.

#### E9 — `handle_reconcile()` has a compounding self-drain that doubles load

`Stash2Plex.py` line 1014: `handle_process_queue()` is called at the end of
EVERY `handle_reconcile()` invocation:
```python
log_info("Reconciliation complete — auto-draining queue now")
handle_process_queue()
```

So each of the ~11 reconciliation runners that survived through `maybe_auto_reconcile()`:
1. Runs a full GQL scan (E4, up to 500 scenes)
2. Enqueues any gaps found
3. Then calls `handle_process_queue()` → `run_batch()` to drain what it enqueued

This is why the RSS stays at 500-857M after the reconciliation scan ends —
the process transitions from reconciliation into queue-draining without releasing
memory. The processes are not idle; they have switched tasks.

#### Reconciliation of hypotheses (a/b/c)

The correct answer is **(c) both compounding**:

**Phase 1 (first minutes): Reconciliation fan-out (primary initial cost)**
- 11+ concurrent `process_queue` spawns all call `maybe_auto_reconcile()`.
- All pass the TOCTOU LOCK_SH check simultaneously (E4 in prior diagnosis).
- All run `ReconciliationRunner.run(scope="recent")` — full GQL scan, 500 scenes.
- This drives the initial 485–870 MB RSS and early multi-minute CPU times.

**Phase 2 (dominant sustained cost): Parallel `run_batch()` without exclusion**
- Each reconciliation runner finishes its scan and immediately calls
  `handle_process_queue()` → `run_batch()` (E9).
- PLUS: the original `process_queue` task in each process also calls
  `handle_process_queue()` directly (from `handle_task()` → `_MANAGEMENT_HANDLERS`).
- Result: 11 concurrent `run_batch()` instances drain 18,350 items in parallel.
- With no exclusion lock on `run_batch()`, all 11 work simultaneously and
  legitimately. SQLite safely partitions items (E8). CPU stays high, RSS
  stays high, processes stay alive for 55-80+ minutes.

**Phase 1 cause:** `maybe_auto_reconcile()` TOCTOU (LOCK_SH permits concurrent readers).
**Phase 2 cause:** `handle_process_queue()` never acquires `worker.lock` before calling `run_batch()`.
**Amplifier:** `handle_reconcile()` calls `handle_process_queue()` inline after every scan (E9),
making each of the N reconciliation runners also a full queue drainer.

#### Updated fix direction

Two independent fixes required; either alone is insufficient:

**Fix 1 — `maybe_auto_reconcile()` TOCTOU (addresses Phase 1):**
In `reconciliation/scheduler.py`, upgrade `load_state()` from `LOCK_SH` to
`LOCK_EX` for the claim-and-record path, or: write `last_run_time = now`
(with LOCK_EX) before the `is_due()` check, so concurrent callers see the
updated timestamp and skip. Callers that lose the exclusive write see the
updated `last_run_time` and bail out. This eliminates the N-parallel-scan
fan-out at the reconciliation layer.

**Fix 2 — `handle_process_queue()` missing exclusion lock (addresses Phase 2):**
In `handle_process_queue()` (Stash2Plex.py lines 936–975), acquire
`try_start_exclusive()` before calling `run_batch()`. Callers that lose the
lock should exit immediately (return without error). The one winner drains
the full queue; the N-1 losers fast-exit. The queue is still fully drained —
just by one process instead of eleven in parallel.

Note: Fix 2 alone would still allow N parallel reconciliation scans (just
without the follow-on queue drain fan-out); Fix 1 is also needed to prevent
the GQL scan cost. Fix 1 alone would prevent the initial reconciliation wave
but would not prevent future `process_queue` fan-outs from other trigger sources.
