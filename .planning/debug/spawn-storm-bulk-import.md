---
slug: spawn-storm-bulk-import
status: resolved
trigger: |
  under heavy load when large number of files are imported the plugin
  spawns too many instances of itself need to limit that to a reasonable
  number (3-5, not sure don't want to consume 64GB of RAM like it was
  doing and it had pegged the CPU on a 24 core cpu)
created: 2026-05-17
updated: 2026-05-17
goal: find_and_fix
---

# Debug: spawn-storm-bulk-import

## Symptoms

- **Expected behavior**: Under bulk import (large number of files imported
  into Stash), the plugin should process events with bounded concurrency —
  user wants no more than ~3-5 concurrent plugin instances active at once.
- **Actual behavior**: Plugin spawns "too many instances of itself" —
  consumed 64 GB of RAM and pegged CPU on a 24-core machine.
- **Error messages**: None reported by the user; the symptom is resource
  exhaustion (RAM/CPU), not a thrown error.
- **Timeline**: Occurs under heavy load when a large number of files are
  imported. Present since drain-trigger / fire-and-forget enqueue semantics
  were introduced.
- **Reproduction**: Bulk import a large set of files into Stash so that
  many `Scene.Update.Post` identification events fire in rapid succession.

## Working theory (verified)

Two compounding fan-out sources:

1. **Stash hook concurrency (primary):** Stash fires `Scene.Update.Post` for
   every identified scene in a bulk import. Each hook is a fresh Python
   process. With N identifications in parallel, N concurrent `Stash2Plex.py`
   processes are started. No prior mechanism bounded this.

2. **`drain_trigger` cooldown TOCTOU race (secondary):** The cooldown is
   read-then-write with no lock. All N concurrent hook processes read
   `hook_autodrain.last` before any writes it — they all see `last=0` and all
   pass the cooldown check, spawning an additional `Stash2Plex.py` each.
   This doubles the process count during burst (N hook processes + up to N
   drain-trigger processes).

3. **Python startup cost on rejected processes:** The existing `fcntl LOCK_EX`
   in `SyncWorker.try_start_exclusive` does serialize drain *work*, but the
   losing processes still paid full Python interpreter + module import + GQL
   config fetch cost before determining they lost the race. With N=hundreds,
   that is hundreds of full Python processes alive simultaneously.

## Current Focus

- hypothesis: CONFIRMED — see root cause below.
- next_action: (completed — fix applied)

## Evidence

### Source analysis

- `sync_queue/drain_trigger.py` `QueueDrainTrigger.trigger()`:
  - Cooldown check is a plain file read (`hook_autodrain.last`) followed by a
    write after spawn. No lock on the read-check-write sequence.
  - `subprocess.Popen` is called synchronously with `start_new_session=True`
    (detached). One Popen per hook process that passes the cooldown check.
  - Under a concurrent burst all N hooks read `last=0` and all spawn.

- `worker/processor.py` `SyncWorker.try_start_exclusive()`:
  - Uses `fcntl LOCK_EX | LOCK_NB` to ensure only one drainer actually does
    queue work.
  - Does NOT prevent processes from starting up. Rejected processes fully load
    Python, import all modules, fetch plugin config from Stash GraphQL, create
    `QueueManager` and `DeadLetterQueue` objects — then exit.

- `Stash2Plex.py` `main()`:
  - Had no concurrency gate before this fix. All processes from Stash
    (hook invocations) and from drain-trigger (Popen calls) proceeded through
    full initialization regardless of how many peers existed.

### Impact model

For a bulk import of 200 files with identify:
- Stash spawns up to 200 concurrent `Stash2Plex.py` hook processes
- Each hook process that passes the cooldown race spawns 1 more drain process
- With 8s cooldown and short overlap windows: up to ~200 hook + ~200 drain
- Each process uses ~200-400 MB during startup (Python + deps + GQL)
- Peak: ~400 processes * ~250 MB = ~100 GB — consistent with the observed 64 GB

## Eliminated

- Worker loop bug: `SyncWorker._worker_loop` correctly serializes queue drain
  via fcntl; the issue is not in how work is processed, it's in how many
  processes start up before reaching that check.
- Stash configuration: no Stash-side concurrency setting exists for Python
  plugins; the fan-out is inherent to per-event hook invocations.

## Resolution

### Root cause

Two compounding issues: (1) no process-level concurrency cap anywhere in the
plugin entry path, and (2) the drain-trigger cooldown check has a TOCTOU
race under concurrent hook execution, defeating its burst-limiting intent.

### Fix applied

**New module: `sync_queue/process_guard.py`**

`ProcessGuard` — a slot-based process concurrency limiter backed by a
directory of per-slot `fcntl` lockfiles (`data/proc_slots/proc_slot.N`).
Each process acquires one slot on entry; `fcntl` locks are released
automatically by the OS on process exit (including crash/OOM-kill).
`live_count()` uses non-blocking trylock to count occupied slots without
subprocesses. Default cap: 5 (configurable via
`STASH2PLEX_MAX_CONCURRENT_PROCESSES` env var).

**`Stash2Plex.py` `main()` — slot acquisition gate**

After the fast-exit for non-identification hooks (those still return
immediately with zero overhead), identification-hook and task invocations
now try to acquire a process slot before any expensive work (module imports,
config fetch, worker init). If no slot is available, the process logs one
trace line and exits with `{"output": "ok"}` in under 5 ms — paying only
the cost of stdlib fcntl, no Python deps loaded, no Stash GQL calls made.

**`sync_queue/drain_trigger.py` — capacity pre-check**

Before calling `subprocess.Popen`, `QueueDrainTrigger.trigger()` calls
`ProcessGuard.live_count()`. If already at cap, it returns
`QueueDrainTriggerResult(False, reason='at_capacity (N/M)')` without
spawning. This prevents the second wave of drain-trigger processes that
would be immediately rejected by the guard anyway, saving one Python
startup per hook at capacity.

**Tests: `tests/sync_queue/test_process_guard.py`**

14 unit tests + 5 drain-trigger capacity tests = 19 new tests. Full suite
of 1105 tests passes with no regressions.

### Files changed

- `sync_queue/process_guard.py` (new)
- `sync_queue/drain_trigger.py` (added ProcessGuard capacity pre-check)
- `Stash2Plex.py` (added slot acquisition gate in `main()`)
- `tests/sync_queue/test_process_guard.py` (new, 19 tests)
