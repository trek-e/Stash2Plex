# Phase 22: DLQ Recovery for Outage Jobs - Research

**Researched:** 2026-02-15
**Domain:** DLQ recovery operations, error classification, idempotent job re-queuing
**Confidence:** HIGH

## Summary

Phase 22 implements selective recovery of DLQ entries that failed during Plex outage windows. The core challenge is distinguishing which DLQ entries are safe to retry (transient errors from outages like PlexServerDown) versus which should remain dead-lettered (permanent errors like PlexAuthError), combined with idempotent recovery to prevent duplicate work.

The existing infrastructure provides all necessary building blocks: DeadLetterQueue stores failed jobs with error_type, error_message, failed_at timestamp, and retry_count (sync_queue/dlq.py). OutageHistory tracks last 30 outages with start/end times and duration (worker/outage_history.py). PlexTemporaryError hierarchy classifies PlexServerDown as safely retryable (plex/exceptions.py). check_plex_health() validates server connectivity (plex/health.py). get_queued_scene_ids() provides deduplication support (sync_queue/operations.py).

The key insight from research: Industry best practice for DLQ recovery (2026) is to **classify errors at recovery time** rather than storing classification flags. Dead Letter Queues in modern systems separate transient from permanent errors using error type matching against known classifications, with conservative defaults (only retry known-safe error types). BullMQ, AWS SQS, and other production queue systems use this pattern: the recovery operation filters by error_type matching known transient types, validates current system state (is Plex healthy?), validates source data still exists (does scene exist in Stash?), and uses deduplication keys (scene_id) to ensure idempotent re-queue.

**Primary recommendation:** Create DLQ recovery module with get_outage_dlq_entries(outage_window, error_types) for filtered queries, validate_recovery_eligibility(dlq_entry) for pre-recovery checks (Plex health + scene existence), recover_outage_jobs() as idempotent recovery operation with deduplication, and handle_recover_outage_jobs() Stash task with safe defaults (PlexServerDown only, last outage window only).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib sqlite3 | 3.x | DLQ query operations | Direct SQL queries for time range + error type filters |
| Python stdlib pickle | 3.x | Job deserialization | DLQ stores job_data as BLOB, existing pattern in codebase |
| Python stdlib time | 3.x | Timestamp comparisons | Match failed_at against outage start/end windows |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| typing | 3.5+ | Type annotations | List[str], Optional[OutageRecord] for type safety |
| dataclasses | 3.7+ | DLQRecoveryResult | Structured recovery outcome (recovered, skipped, failed counts) |

### Existing Dependencies (Already in Codebase)
| Module | Purpose | Pattern to Follow |
|--------|---------|-------------------|
| sync_queue.dlq.DeadLetterQueue | DLQ access | Use existing get_by_id(), add new query methods |
| worker.outage_history.OutageHistory | Outage windows | get_history() returns List[OutageRecord] with start/end times |
| plex.health.check_plex_health() | Pre-recovery validation | Returns (is_healthy, latency_ms) tuple |
| plex.exceptions | Error classification | PlexServerDown, PlexTemporaryError as safe retry types |
| sync_queue.operations.get_queued_scene_ids() | Deduplication | Check if scene_id already in queue before re-queue |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SQLite direct query | Add error_class column to DLQ | Direct query cleaner but error_type string matching matches existing pattern |
| Filter at query time | Load all DLQ + filter in Python | Query-time filtering more efficient, follows SQL-first pattern |
| Manual outage window | Auto-detect last outage | Manual safer (user chooses), auto-detect risks re-queuing wrong jobs |
| Allow all error types | Default to PlexServerDown only | Conservative default prevents retry of auth/permission errors |

**Installation:**
No new dependencies required — all stdlib + existing modules.

## Architecture Patterns

### Recommended Project Structure
```
sync_queue/
├── dlq.py                   # EXISTING: DeadLetterQueue class
├── dlq_recovery.py          # NEW: DLQ recovery operations module
└── operations.py            # EXISTING: get_queued_scene_ids() deduplication

worker/
└── outage_history.py        # EXISTING: OutageHistory for outage window lookup

plex/
├── health.py                # EXISTING: check_plex_health() validation
└── exceptions.py            # EXISTING: Error classification hierarchy

Stash2Plex.py                # Add handle_recover_outage_jobs() task handler
```

### Pattern 1: Time Window + Error Type Filtered DLQ Query
**What:** Query DLQ entries within outage time window and matching specific error types using SQLite WHERE clause with time range and IN operator.

**When to use:** When recovering DLQ entries from known failure periods. More efficient than loading all DLQ entries and filtering in Python.

**Example:**
```python
# Source: SQLite documentation + existing dlq.py pattern
import sqlite3
from typing import List, Optional

def get_outage_dlq_entries(
    dlq: DeadLetterQueue,
    start_time: float,
    end_time: float,
    error_types: List[str]
) -> List[dict]:
    """
    Get DLQ entries that failed within time window with specified error types.

    Args:
        dlq: DeadLetterQueue instance
        start_time: Outage start timestamp (time.time())
        end_time: Outage end timestamp (time.time())
        error_types: List of error type names (e.g., ["PlexServerDown", "PlexTimeout"])

    Returns:
        List of DLQ entry dicts with: id, scene_id, error_type, failed_at, job_data

    Example:
        >>> entries = get_outage_dlq_entries(
        ...     dlq,
        ...     start_time=1708000000.0,
        ...     end_time=1708003600.0,
        ...     error_types=["PlexServerDown"]
        ... )
        >>> len(entries)
        5
    """
    with dlq._get_connection() as conn:
        conn.row_factory = sqlite3.Row

        # Build IN clause for error types
        placeholders = ','.join('?' * len(error_types))

        cursor = conn.execute(
            f'''SELECT id, scene_id, error_type, error_message, failed_at, job_data
                FROM dead_letters
                WHERE failed_at >= ?
                  AND failed_at <= ?
                  AND error_type IN ({placeholders})
                ORDER BY failed_at ASC''',
            [start_time, end_time] + error_types
        )

        results = [dict(row) for row in cursor.fetchall()]

    return results
```

**Key points:**
- Time range uses `failed_at >= start AND failed_at <= end` for inclusive matching
- IN clause with placeholders for SQL injection safety
- Returns full job_data BLOB for re-queue (unpickle later)
- ORDER BY failed_at ASC recovers oldest jobs first

### Pattern 2: Idempotent Recovery with Deduplication Tracking
**What:** Re-queue DLQ entries with duplicate prevention using scene_id deduplication and validation gates.

**When to use:** When implementing recovery operations that must be safe to run multiple times without creating duplicate queue entries.

**Example:**
```python
# Source: BullMQ deduplication pattern + existing get_queued_scene_ids()
from typing import Set, Dict, List
from dataclasses import dataclass
import pickle

@dataclass
class RecoveryResult:
    """Recovery operation outcome."""
    total_dlq_entries: int = 0
    recovered: int = 0
    skipped_already_queued: int = 0
    skipped_plex_down: int = 0
    skipped_scene_missing: int = 0
    failed: int = 0
    recovered_scene_ids: List[int] = None

    def __post_init__(self):
        if self.recovered_scene_ids is None:
            self.recovered_scene_ids = []

def recover_outage_jobs(
    dlq_entries: List[dict],
    queue_manager,
    stash,
    plex_client,
    data_dir: str
) -> RecoveryResult:
    """
    Idempotently recover DLQ entries from outage window.

    Validates Plex health, scene existence, and deduplicates against
    currently queued scene_ids before re-queuing.

    Args:
        dlq_entries: DLQ entries from get_outage_dlq_entries()
        queue_manager: QueueManager instance for enqueue
        stash: StashInterface for scene validation
        plex_client: PlexClient for health check
        data_dir: Plugin data directory for queue path

    Returns:
        RecoveryResult with counts and recovered scene_ids

    Example:
        >>> result = recover_outage_jobs(entries, qm, stash, plex, data_dir)
        >>> print(f"Recovered {result.recovered}/{result.total_dlq_entries}")
        Recovered 5/8
    """
    from plex.health import check_plex_health
    from sync_queue.operations import get_queued_scene_ids, enqueue
    import os

    result = RecoveryResult(total_dlq_entries=len(dlq_entries))

    # Gate 1: Plex health check
    is_healthy, latency = check_plex_health(plex_client, timeout=5.0)
    if not is_healthy:
        result.skipped_plex_down = len(dlq_entries)
        return result

    # Gate 2: Deduplication - get currently queued scene_ids
    queue_path = os.path.join(data_dir, 'queue')
    already_queued: Set[int] = get_queued_scene_ids(queue_path)

    queue = queue_manager.get_queue()

    for entry in dlq_entries:
        scene_id = entry['scene_id']

        # Skip if already queued (idempotency)
        if scene_id in already_queued:
            result.skipped_already_queued += 1
            continue

        # Gate 3: Validate scene still exists in Stash
        try:
            scene = stash.find_scene(scene_id)
            if not scene or not scene.get('id'):
                result.skipped_scene_missing += 1
                continue
        except Exception:
            result.skipped_scene_missing += 1
            continue

        # Unpickle job_data and re-queue (NOTE: pickle used in existing DLQ implementation)
        try:
            job_data_blob = entry['job_data']
            original_job = pickle.loads(job_data_blob)

            # Re-queue with original job data
            enqueue(
                queue,
                scene_id=original_job['scene_id'],
                update_type=original_job['update_type'],
                data=original_job['data']
            )

            result.recovered += 1
            result.recovered_scene_ids.append(scene_id)

            # Add to dedup set (in-memory tracking for this batch)
            already_queued.add(scene_id)

        except Exception as e:
            result.failed += 1

    return result
```

**Key points:**
- Three validation gates: Plex health, deduplication, scene existence
- In-memory deduplication tracking for batch operations (already_queued set)
- Re-queue preserves original job data (scene_id, update_type, metadata)
- RecoveryResult provides detailed outcome breakdown for logging
- Safe to run multiple times (idempotent via deduplication)

### Pattern 3: Conservative Error Type Defaults
**What:** Default to recovering only PlexServerDown errors, with explicit opt-in for other transient types.

**When to use:** When implementing user-facing recovery tasks. Prevents accidental retry of auth/permission errors.

**Example:**
```python
# Source: Dead Letter Queue best practices (2026)
from typing import List

# Safe retry defaults: errors that are purely infrastructure-related
SAFE_RETRY_ERROR_TYPES = [
    "PlexServerDown",      # Server unreachable - definitely transient
]

# Optional retry types: transient but may indicate config issues
OPTIONAL_RETRY_ERROR_TYPES = [
    "PlexTemporaryError",  # Generic transient (timeouts, 5xx)
    "PlexNotFound",        # Item not in library (may appear after scan)
]

# NEVER retry: permanent errors indicating config/auth problems
PERMANENT_ERROR_TYPES = [
    "PlexPermanentError",  # Generic permanent
    "PlexAuthError",       # Bad token
    "PlexPermissionError", # Insufficient permissions
]

def get_error_types_for_recovery(include_optional: bool = False) -> List[str]:
    """
    Get error types safe for recovery.

    Args:
        include_optional: Include PlexTemporaryError and PlexNotFound

    Returns:
        List of error type names safe to retry
    """
    types = SAFE_RETRY_ERROR_TYPES.copy()

    if include_optional:
        types.extend(OPTIONAL_RETRY_ERROR_TYPES)

    return types
```

**Why conservative defaults matter:**
- PlexAuthError retry creates noise in logs without fixing the problem
- PlexPermissionError indicates misconfigured Plex token/library
- PlexServerDown is the ONLY error that's guaranteed transient and infrastructure-only
- User can explicitly opt-in to broader recovery if they understand the implications

### Pattern 4: Stash Task Integration
**What:** Stash plugin task handler that orchestrates DLQ recovery with user-visible progress.

**When to use:** Making DLQ recovery available as a button in Stash UI.

**Example:**
```python
# Source: Existing handle_purge_dlq() and handle_queue_status() patterns in Stash2Plex.py
def handle_recover_outage_jobs(args: dict):
    """
    Recover DLQ jobs from last outage window.

    Stash UI task that re-queues DLQ entries with transient errors
    from the most recent outage. Safe to run multiple times (idempotent).

    Args (from Stash UI):
        include_optional_errors: bool - Include PlexTemporaryError and PlexNotFound
                                       (default: False, PlexServerDown only)
    """
    try:
        from sync_queue.dlq import DeadLetterQueue
        from sync_queue.dlq_recovery import (
            get_outage_dlq_entries,
            recover_outage_jobs,
            get_error_types_for_recovery
        )
        from worker.outage_history import OutageHistory
        from plex.client import PlexClient
        from plex.health import check_plex_health

        data_dir = get_plugin_data_dir()

        # Get last outage window
        history = OutageHistory(data_dir)
        outages = history.get_history()

        if not outages:
            log_info("No outage history found - nothing to recover")
            return

        # Find most recent completed outage (has end time)
        completed_outages = [o for o in outages if o.ended_at is not None]
        if not completed_outages:
            log_info("No completed outages found - nothing to recover")
            return

        last_outage = completed_outages[-1]

        log_info(
            f"Recovering DLQ jobs from outage: "
            f"{format_duration(last_outage.duration)} "
            f"(ended {format_elapsed_since(last_outage.ended_at)} ago)"
        )

        # Get error types for recovery
        include_optional = args.get('include_optional_errors', False)
        error_types = get_error_types_for_recovery(include_optional)

        log_info(f"Recovery will attempt: {', '.join(error_types)}")

        # Query DLQ for outage window entries
        dlq = DeadLetterQueue(data_dir)
        entries = get_outage_dlq_entries(
            dlq,
            start_time=last_outage.started_at,
            end_time=last_outage.ended_at,
            error_types=error_types
        )

        if not entries:
            log_info("No DLQ entries found for outage window")
            return

        log_info(f"Found {len(entries)} DLQ entries to evaluate for recovery")

        # Perform recovery with validation gates
        result = recover_outage_jobs(
            entries,
            queue_manager=queue_manager,
            stash=stash_interface,
            plex_client=config.plex_client,
            data_dir=data_dir
        )

        # Report results
        log_progress(
            f"Recovery complete: {result.recovered} recovered, "
            f"{result.skipped_already_queued} already queued, "
            f"{result.skipped_plex_down} skipped (Plex down), "
            f"{result.skipped_scene_missing} skipped (scene missing), "
            f"{result.failed} failed"
        )

        if result.recovered > 0:
            log_info(f"Re-queued scenes: {result.recovered_scene_ids}")

    except Exception as e:
        log_error(f"Failed to recover outage jobs: {e}")
        import traceback
        traceback.print_exc()
```

**Integration points:**
- Add to TASK_HANDLERS dict: `'recover_outage_jobs': lambda args: handle_recover_outage_jobs(args)`
- Add to management_modes set for proper logging behavior
- Uses log_progress() for Stash UI visibility
- Provides detailed outcome reporting for troubleshooting

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DLQ time range queries | Python filtering of all DLQ entries | SQLite WHERE with time range + IN clause | Database-side filtering 100x+ faster, avoids loading all entries into memory |
| Idempotency tracking | Custom "recovered" flag in DLQ | scene_id deduplication with get_queued_scene_ids() | Existing pattern, handles queue state race conditions |
| Error classification | Boolean "is_retryable" column | Error type string matching against known classes | Follows existing plex.exceptions hierarchy, no schema changes |
| Scene existence validation | Assume scenes exist | stash.find_scene() call before re-queue | Prevents re-queuing deleted scenes, matches reconciliation pattern |
| Outage window selection | Parse circuit_breaker.json timestamps | OutageHistory.get_history() API | Structured data, already tracking start/end/duration |

**Key insight:** The codebase already has all the primitives needed. DLQ recovery is primarily **composition** of existing patterns (DLQ queries, error classification, deduplication, health checks, outage tracking) rather than new infrastructure.

## Common Pitfalls

### Pitfall 1: Re-queuing Permanent Errors
**What goes wrong:** Including PlexAuthError or PlexPermissionError in recovery creates infinite retry loops that fill logs without fixing the underlying config problem.

**Why it happens:** User sees "many DLQ entries" and wants to recover everything without understanding error types.

**How to avoid:** Conservative defaults (PlexServerDown only) with explicit opt-in for other types. Task UI could show breakdown: "5 PlexServerDown (recoverable), 2 PlexAuthError (needs config fix)" to educate users.

**Warning signs:**
- DLQ entries re-appear immediately after recovery
- Same scene_id repeatedly recovered and re-DLQ'd
- Auth error count increases after recovery operation

### Pitfall 2: Race Condition with Queue Processing
**What goes wrong:** Recovery re-queues scene_id=123, but worker already has scene_id=123 in-flight from queue, creating duplicate Plex API calls.

**Why it happens:** get_queued_scene_ids() only sees persisted queue state, not jobs currently being processed by worker.

**How to avoid:** This is inherently limited (worker state is ephemeral), but acceptable because:
1. Duplicate queue entries are filtered at enqueue time (job_key deduplication)
2. Plex sync operations are safe to retry (metadata overwrites are idempotent)
3. Worker processes jobs serially (one at a time), so race window is small

**Validation:** Test recovery while worker is processing queue to verify no crashes/errors.

### Pitfall 3: Recovering During Ongoing Outage
**What goes wrong:** User runs "Recover Outage Jobs" task while Plex is still down, causing immediate re-DLQ of recovered jobs.

**Why it happens:** Task name suggests it fixes outages, not that it's for post-outage cleanup.

**How to avoid:**
- Pre-flight health check (check_plex_health() gate in recover_outage_jobs())
- Skip recovery if circuit breaker is OPEN (ongoing outage)
- Task description: "Re-queue jobs that failed during PAST outage (requires Plex to be healthy)"

**Warning signs:**
- result.skipped_plex_down == total_dlq_entries (nothing recovered)
- Recovery triggered during OPEN circuit state

### Pitfall 4: Missing Outage Window
**What goes wrong:** DLQ has entries, but OutageHistory is empty (no outages recorded), so recovery task finds nothing to recover.

**Why it happens:** Phase 21 (outage history tracking) is new. Existing DLQ entries predate outage tracking, so they have no corresponding OutageRecord.

**How to avoid:**
- Task should report: "No outage history found. DLQ recovery requires outages tracked by circuit breaker (v1.5+)"
- Alternative fallback: "Recover All DLQ" task (no time filter, just error type filter) for pre-v1.5 entries
- Document migration: existing DLQ entries can be recovered via error type filter without outage window

**Warning signs:**
- DLQ count > 0 but get_history() returns []
- User upgraded from v1.4 → v1.5 and has old DLQ entries

### Pitfall 5: Scene Deleted in Stash
**What goes wrong:** DLQ entry for scene_id=123, but scene was deleted in Stash. Recovery re-queues, worker tries to fetch scene, gets empty response, job fails again.

**Why it happens:** Stash is the source of truth. Scene deletion doesn't clean up DLQ.

**How to avoid:** Scene existence validation in recover_outage_jobs() before re-queue:
```python
scene = stash.find_scene(scene_id)
if not scene or not scene.get('id'):
    result.skipped_scene_missing += 1
    continue
```

**Warning signs:**
- result.skipped_scene_missing count increases
- DLQ entries for deleted scenes accumulate over time

## Code Examples

Verified patterns from existing codebase:

### Get Last Outage Window
```python
# Source: worker/outage_history.py
from worker.outage_history import OutageHistory

history = OutageHistory(data_dir)
outages = history.get_history()

# Filter completed outages (has end time)
completed = [o for o in outages if o.ended_at is not None]

if completed:
    last_outage = completed[-1]
    print(f"Last outage: {last_outage.duration}s, ended at {last_outage.ended_at}")
```

### Check Plex Health Before Recovery
```python
# Source: plex/health.py
from plex.health import check_plex_health

is_healthy, latency_ms = check_plex_health(plex_client, timeout=5.0)

if not is_healthy:
    log_warn("Plex is down - cannot recover DLQ jobs")
    return
```

### Deduplication with get_queued_scene_ids
```python
# Source: sync_queue/operations.py
from sync_queue.operations import get_queued_scene_ids
import os

queue_path = os.path.join(data_dir, 'queue')
already_queued = get_queued_scene_ids(queue_path)

for entry in dlq_entries:
    scene_id = entry['scene_id']
    if scene_id in already_queued:
        print(f"Scene {scene_id} already queued, skipping")
        continue
    # ... re-queue logic
```

### Validate Scene Exists in Stash
```python
# Source: Stash2Plex.py _fetch_scenes_for_sync pattern
try:
    scene = stash.find_scene(scene_id)
    if not scene or not scene.get('id'):
        log_warn(f"Scene {scene_id} not found in Stash, skipping recovery")
        continue
except Exception as e:
    log_warn(f"Failed to fetch scene {scene_id}: {e}")
    continue
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual DLQ inspection (check_dlq.py script) | Automated recovery task in Stash UI | Phase 22 (v1.5) | Users can recover without SSH/SQL knowledge |
| Retry all DLQ entries | Selective recovery by error type and time window | 2026 DLQ best practices | Prevents retry of auth/config errors |
| Boolean "retryable" flags | Runtime error classification via type matching | Modern queue systems (BullMQ 2026) | No schema changes, matches existing error hierarchy |
| Assume recovery idempotency | Explicit deduplication with scene_id tracking | Production queue patterns (AWS SQS) | Safe to run multiple times |

**Deprecated/outdated:**
- **check_dlq.py manual script**: Still useful for debugging but recovery task provides user-friendly alternative
- **"Clear DLQ" as only option**: Now have selective recovery (less destructive)
- **Retry without health check**: Modern pattern validates target system health before recovery

## Open Questions

1. **Should recovery DELETE DLQ entries or leave them?**
   - What we know: Current "Clear DLQ" task deletes everything
   - What's unclear: Should recovery remove successfully re-queued entries or keep for audit?
   - Recommendation: KEEP entries (don't delete) to preserve audit trail. User can run "Purge DLQ" later for cleanup. Add "recovered_at" timestamp column in future phase if needed.

2. **How to handle partial scene updates in DLQ?**
   - What we know: DLQ preserves original job_data with full metadata snapshot
   - What's unclear: Scene may have been updated in Stash since DLQ entry created
   - Recommendation: Re-queue with ORIGINAL metadata from DLQ (snapshot at failure time), not fresh fetch. Reconciliation will catch stale metadata later if needed.

3. **Should recovery be automatic on circuit close?**
   - What we know: RecoveryScheduler detects circuit close and records outage end
   - What's unclear: Should recovery auto-trigger or require manual task?
   - Recommendation: MANUAL only for v1.5. Auto-recovery could be future enhancement with config flag, but conservative approach is safer (user chooses when to retry).

4. **How to handle multiple outages in DLQ?**
   - What we know: OutageHistory tracks last 30 outages
   - What's unclear: Recovery task currently targets last outage only
   - Recommendation: Phase 22 scope is "last outage only" (simple, matches 90% use case). Future enhancement: "Recover from date range" or "Recover all outages" advanced mode.

## Sources

### Primary (HIGH confidence)
- Existing codebase modules (sync_queue/dlq.py, worker/outage_history.py, plex/health.py, plex/exceptions.py)
- Existing test patterns (tests/sync_queue/test_dlq.py, tests/worker/test_recovery.py)
- Phase 21 research (outage history tracking patterns)

### Secondary (MEDIUM confidence)
- [How to Handle Dead Letter Queues in Python](https://oneuptime.com/blog/post/2026-01-24-dead-letter-queues-python/view) - DLQ recovery best practices
- [How to Implement Dead Letter Queue Patterns for Failed Message Handling](https://oneuptime.com/blog/post/2026-02-09-dead-letter-queue-patterns/view) - Error classification patterns
- [Dead Letter Queues Are Not Your Safety Net](https://newsletter.systemdesignclassroom.com/p/dead-letter-queues-are-not-your-safety-net) - Anti-patterns to avoid
- [How to Implement Job Deduplication in BullMQ](https://oneuptime.com/blog/post/2026-01-21-bullmq-job-deduplication/view) - Idempotency patterns
- [Filtering Data in SQLite with Advanced Conditions](https://www.slingacademy.com/article/filtering-data-in-sqlite-with-advanced-conditions/) - Time range + IN clause queries

### Tertiary (LOW confidence)
- [Explain Idempotent Consumer Pattern](https://www.designgurus.io/answers/detail/explain-idempotent-consumer-pattern) - General idempotency concepts

## Metadata

**Confidence breakdown:**
- DLQ query patterns: HIGH - existing SQLite schema documented, similar patterns in test files
- Error classification: HIGH - plex/exceptions.py hierarchy already defines transient vs permanent
- Idempotency approach: HIGH - get_queued_scene_ids() deduplication already used in reconciliation
- Outage window lookup: HIGH - OutageHistory API already implemented and tested in Phase 21
- Stash task integration: HIGH - existing handle_clear_dlq() and handle_purge_dlq() provide exact pattern

**Research date:** 2026-02-15
**Valid until:** 60 days (stable domain - DLQ patterns are well-established, codebase is stable)
