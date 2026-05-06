# PlexSync Domain Context

Stash2Plex is a Stash plugin that syncs scene metadata from Stash (a self-hosted video library manager) to Plex Media Server. It uses a producer-consumer pattern with a SQLite-backed persistent queue to ensure reliable delivery through process crashes, Plex outages, and network failures.

**Architecture summary**: Stash invokes the plugin per-event (not long-running). Hooks capture events and enqueue jobs. A worker thread processes jobs, updates Plex, and retries failures with exponential backoff. A reconciliation system detects and fills gaps that hooks missed.

---

## Core Domain Terms

### Scene
A video file tracked by Stash with associated metadata: title, studio, performers, tags, summary, date, rating, and file paths. The primary unit of synchronisation.

### Scene Update Event
A `Scene.Update.Post` webhook fired by Stash when a scene's metadata changes. The trigger for the hook-capture path. Must be handled in <100ms to avoid Stash hook timeouts.

### Sync Job
A dict placed on the Queue describing one unit of work: `scene_id`, `update_type` ("metadata"), `data` (path + metadata fields), `enqueued_at`, `job_key`, and optionally retry metadata (`retry_count`, `next_retry_at`, `last_error_type`).

### Job Key
`scene_{scene_id}` — the stable identifier used for dedup across sessions. Stored in the job dict.

### Queue
The SQLite-backed `SQLiteAckQueue` (via `persist-queue`) that stores Sync Jobs durably. Jobs are acknowledged on success, nacked for retry, or failed to the DLQ.

### QueueManager
The module (`sync_queue/manager.py`) that owns the Queue lifecycle and all dedup logic. The single seam between job producers (hooks, reconciliation, bulk-sync) and the Queue.

- **`try_enqueue(scene_id, update_type, data) → EnqueueResult`** — the enqueue seam. Two-tier dedup: in-memory `_pending_scene_ids` set (O(1), zero I/O) as Tier 1; SQLite `get_queued_scene_ids` scan as Tier 2 on set miss.
- **`reenqueue(old_job, new_job)`** — retry-path bypass: acks the old job and enqueues new one with updated retry metadata, without touching dedup (scene stays in-flight).
- **`ack / nack / fail`** — drain the in-memory pending set when a job leaves the Queue.

### EnqueueResult
`dataclass(enqueued: bool, job: Optional[dict], reason: Optional[str])`. Returned by `try_enqueue`. `reason` is `"already_pending"` or `"recently_completed"` on duplicate detection.

### Pending Scene Set
`QueueManager._pending_scene_ids` — an in-memory `set[int]` of scene IDs currently in the Queue. The O(1) fast path for dedup in the hook-handler hot path. Populated by `try_enqueue`, drained by `ack/nack/fail`. Does not survive process restart (Tier 2 catches cross-session cases).

### Dead Letter Queue (DLQ)
`dlq.db` — a separate SQLite store for jobs that exhausted all retries. Preserves error context (error type, retry count) for manual review or future recovery.

### Sync Timestamp
A per-scene float timestamp (`sync_timestamps.json`) recording when a scene was last successfully synced. Used by the worker to skip stale queue entries and by reconciliation to detect stale-sync gaps.

### Metadata Quality Gate
A filter in both the hook handler and reconciliation enqueue path: skip scenes with no meaningful Stash metadata (no studio, performers, tags, details, or date). Prevents clearing existing Plex values during the stash-box identification race window. Implemented as `has_meaningful_metadata(data: dict) -> bool` in `validation/quality.py` — the single source of truth. `rating100` is explicitly excluded: a rating alone would trigger sync and clear all other Plex fields. Both `hooks/handlers.py` and `reconciliation/detector.py` import from this module; do not inline the rule.

---

## Reliability Terms

### TransientError
A retry-able failure (network timeout, temporary Plex error). Gets exponential backoff with full jitter, up to 5 retries.

### PermanentError
A non-retry-able failure (missing file path, bad job data). Goes straight to the DLQ without retry.

### PlexNotFound
A `PlexNotFound` exception meaning the scene's file isn't in the Plex library yet (not yet scanned). Gets extended retry params: 12 retries, longer delays (30s base, 600s cap) to allow time for Plex scanning. When `skip_not_found` is enabled, `PlexNotFound` acks immediately and returns `'skipped'` instead of retrying — designed for users with a deliberate partial Plex library.

### skip_not_found
Config toggle (`bool`, default `false`). When `true`, `PlexNotFound` is treated as an expected permanent condition: the job is acked without retry and without a DLQ entry. Use for setups where Plex holds a deliberate subset of the Stash library (e.g. offline/travel collection). Wired in `_handle_job` (`worker/processor.py`) and exposed in `Stash2PlexConfig` + `Stash2Plex.yml`.

### PlexServerDown
Plex is unreachable. Does not count against retry limit — nacked back to queue. Circuit Breaker opens to pause processing during outages.

### Circuit Breaker
`worker/circuit_breaker.py` — three-state (CLOSED / OPEN / HALF_OPEN) rate-limiter that pauses all job processing when Plex is down, preventing retry exhaustion during outages. `CircuitBreaker.load_status(state_file) → dict` is a classmethod for reading CB state without instantiation — used by status/health handlers that have no live `CircuitBreaker` instance. Callers must use this seam; raw `json.load` on `circuit_breaker.json` is forbidden.

### Exponential Backoff
`worker/backoff.py` — calculates retry delays with full jitter. Parameters differ by error type (TransientError vs PlexNotFound).

### Retry Metadata
Fields stored in the Sync Job dict across retries: `retry_count`, `next_retry_at` (epoch float), `last_error_type`. Persisted in the SQLiteAckQueue so they survive process restart.

---

## Worker Architecture Terms

### _handle_job
`SyncWorker._handle_job(item, recently_synced, sync_timestamps) → str` — the single ack/retry/DLQ pipeline for one dequeued job. Both `_worker_loop` (background) and `run_batch` (foreground) call this method; retry and DLQ logic lives in exactly one place. Return values: `'success'`, `'skipped'`, `'retrying'`, `'failed'`, `'server_down'`.

### run_batch
`SyncWorker.run_batch(progress_callback=None, job_delay_secs=0.15) → dict` — synchronous foreground drain of the entire queue. Used by `handle_process_queue` (the "Process Queue" task). Inherits both dedup mechanisms from `_handle_job`. Backoff sleep is capped at 5s (vs 30s in background loop) for progress-bar responsiveness.

### Worker Exclusion Lock
`SyncWorker._lock_fd` — an `fcntl` `LOCK_EX | LOCK_NB` lock on `worker.lock` that prevents concurrent queue draining. Owned entirely by `SyncWorker` (not the entry point). Acquired via `try_start_exclusive(resume_orphaned=True) → bool` (returns `False` if another process holds the lock), released via `_release_lock()` called by `stop()` and error paths. The entry point (`Stash2Plex.py`) checks `worker._lock_fd is not None` to determine if the worker is active.

### try_start_exclusive
`SyncWorker.try_start_exclusive(resume_orphaned=True) → bool` — acquires the exclusion lock, resumes any orphaned in-progress items, and starts the worker thread. Returns `False` without starting if the lock is already held (another process is draining). Replaces the former module-global `_worker_lock_fd` pattern in `Stash2Plex.py`.

---

## Reconciliation Terms

### Gap
A scene in Stash that is out of sync with Plex. Three gap types:
- **Empty metadata gap** — scene has Stash metadata but Plex item has none.
- **Stale-sync gap** — scene's `updated_at` is newer than its Sync Timestamp.
- **Missing gap** — scene has no Sync Timestamp and no Plex match (raises `PlexNotFound`).

### GapDetector
`reconciliation/detector.py` — detects gaps by comparing Stash scenes against Plex items and Sync Timestamps. Three methods: `detect_empty_metadata`, `detect_stale_syncs`, `detect_missing`.

### GapDetectionEngine
`reconciliation/engine.py` — orchestrates GapDetector across all (or recent) scenes and enqueues detected gaps via QueueManager. Applies timestamp guard (skip if already synced with current data) and Metadata Quality Gate before enqueueing.

### ReconciliationScheduler
`reconciliation/scheduler.py` — check-on-invocation scheduler. No daemons: reads JSON state on each plugin invocation, checks if reconciliation is due, runs if needed. State includes `last_run_at`, `last_scenes_checked`, `last_gaps_found`, `last_enqueued`.

### Scope
Reconciliation filter: `"all"` (all scenes), `"recent"` (last 24h), `"7days"` (last 7 days).

---

## Stash Plugin Context

### Hook Invocation
Stash calls the plugin synchronously per event. The plugin must return in <100ms. The hook handler enqueues the job and returns immediately; the worker processes asynchronously in a daemon thread.

### Identification Event
A `Scene.Update.Post` hook where `input_data` contains `stash_ids` — fired when stash-box completes identification of a scene. This is the canonical moment when a scene acquires real metadata. Both the Plex library scan trigger (`trigger_plex_scan_for_scene`) and the metadata sync enqueue happen here, not at `Scene.Create.Post`. `Scene.Create.Post` is deliberately a no-op: no metadata exists at file-scan time.

### Scene.Create.Post
Fired when Stash scans a new file into the library. Treated as a no-op by the plugin — no Plex scan, no enqueue. Metadata and Plex sync are deferred to the Identification Event. The PlexNotFound retry window (12×, up to 600s) covers any gap between the Plex scan trigger and the metadata sync job succeeding.

### Task Invocation
Stash calls the plugin for explicit user-triggered tasks: `sync_all`, `reconcile_all`, `queue_status`, `process_queue`, `recover_outage_jobs`, etc. These run to completion (no daemon thread needed).

### Check-on-Invocation Scheduling
Stash plugins exit after each invocation — there is no persistent process to run cron jobs. Scheduling is simulated by checking state files on each invocation and running if the interval has elapsed.

---

## Key Invariants

- **Stash is authoritative**: empty/null fields in sync data clear existing Plex values. This is intentional — Stash is the source of truth.
- **LOCKED**: Missing fields clear Plex values. This decision is locked; proposals to change it should be treated as a breaking change.
- **<100ms hook budget**: Hook handlers must return in <100ms. The Pending Scene Set provides O(1) dedup with zero I/O to meet this constraint.
- **Retry metadata lives in the job dict**: not in worker state. Survives process restart because the job is persisted in SQLiteAckQueue.
- **`persist-queue` nack cannot modify job data**: `reenqueue()` exists specifically to work around this — ack the old job, enqueue a new one with updated metadata.
- **Release branch is `v1.x.x`** (not `v1.5.x` or version-specific). Tags `v1.6.*` trigger the release workflow. The workflow builds the zip, updates `index.yml` (version + date + sha256 + resets `path: Stash2Plex.zip`), commits to `v1.x.x`, then mirrors `index.yml` + `Stash2Plex.zip` to `main`. Stash resolves `path: Stash2Plex.zip` relative to `main/` — this must remain a relative path, never an absolute URL.
- **Feature work uses PRs**: new features are developed on `feature/*` branches and merged to `main` via squash-merge PR. Fixes targeting a release also need a direct commit to `v1.x.x`. Issues are tracked in GitHub Issues; triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.
- **`_handle_job` is the single retry/DLQ seam**: do not add retry or DLQ logic anywhere else in the worker. Both `_worker_loop` and `run_batch` delegate to it.
- **`CircuitBreaker.load_status` is the single CB state-read seam**: status and health handlers must use it; do not open `circuit_breaker.json` directly.
- **`Scene.Create.Post` is a no-op**: do not add logic here. All Plex interaction for new scenes belongs in the Identification Event handler.
