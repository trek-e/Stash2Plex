"""
DLQ Recovery Operations Module

Enables selective recovery of DLQ entries that failed during Plex outage windows.
Uses three-gate validation (Plex health, deduplication, scene existence) to safely
re-enqueue jobs that failed due to temporary Plex unavailability.

Three components:
1. Error type classification (safe vs. optional vs. permanent)
2. Time-windowed DLQ queries (get entries from outage window)
3. Idempotent recovery with three-gate validation
"""

import pickle
import sqlite3
from dataclasses import dataclass, field
from typing import List, TYPE_CHECKING

from plex.health import check_plex_health
from sync_queue.operations import get_queued_scene_ids, enqueue

if TYPE_CHECKING:
    from sync_queue.dlq import DeadLetterQueue
    from persistqueue import SQLiteAckQueue
    from plex.client import PlexClient

__all__ = [
    "SAFE_RETRY_ERROR_TYPES",
    "OPTIONAL_RETRY_ERROR_TYPES",
    "PERMANENT_ERROR_TYPES",
    "get_error_types_for_recovery",
    "get_outage_dlq_entries",
    "recover_outage_jobs",
    "RecoveryResult",
]

# =============================================================================
# Error Type Classification
# =============================================================================

# Conservative default - only retry errors that are definitively safe
SAFE_RETRY_ERROR_TYPES = ["PlexServerDown"]

# Optional retry errors - may be worth retrying depending on context
# PlexTemporaryError: timeouts, 5xx errors, rate limits
# PlexNotFound: item may appear after library scan completes
OPTIONAL_RETRY_ERROR_TYPES = ["PlexTemporaryError", "PlexNotFound"]

# Permanent errors - never retry these
# Auth failures, permission errors, permanent API errors
PERMANENT_ERROR_TYPES = ["PlexPermanentError", "PlexAuthError", "PlexPermissionError"]


def get_error_types_for_recovery(include_optional: bool = False) -> List[str]:
    """
    Get list of error types safe to recover from DLQ.

    Args:
        include_optional: If True, include optional retry types (PlexTemporaryError, PlexNotFound).
                         If False, only return safe types (PlexServerDown).

    Returns:
        List of error type strings (matching type(error).__name__ from plex/exceptions.py)

    Examples:
        >>> get_error_types_for_recovery(include_optional=False)
        ['PlexServerDown']
        >>> get_error_types_for_recovery(include_optional=True)
        ['PlexServerDown', 'PlexTemporaryError', 'PlexNotFound']
    """
    error_types = SAFE_RETRY_ERROR_TYPES.copy()
    if include_optional:
        error_types.extend(OPTIONAL_RETRY_ERROR_TYPES)
    return error_types


# =============================================================================
# Time-Windowed DLQ Queries
# =============================================================================


def get_outage_dlq_entries(
    dlq: "DeadLetterQueue",
    start_time: float,
    end_time: float,
    error_types: List[str]
) -> List[dict]:
    """
    Query DLQ for entries within time window and matching error types.

    CRITICAL: DLQ failed_at column uses SQLite CURRENT_TIMESTAMP (text format
    like "2026-02-15 19:17:49"), while start_time/end_time are Unix floats.
    Query converts Unix floats using datetime(?, 'unixepoch') for comparison.

    Args:
        dlq: DeadLetterQueue instance
        start_time: Unix timestamp for window start (inclusive)
        end_time: Unix timestamp for window end (inclusive)
        error_types: List of error type strings to match (e.g., ["PlexServerDown"])

    Returns:
        List of dicts with: id, scene_id, error_type, error_message, failed_at, job_data
        Results ordered by failed_at ASC (oldest first)
        Empty list if no matches

    Examples:
        >>> from sync_queue.dlq import DeadLetterQueue
        >>> dlq = DeadLetterQueue("/data")
        >>> entries = get_outage_dlq_entries(dlq, 1700000000.0, 1700003600.0, ["PlexServerDown"])
        >>> print(f"Found {len(entries)} entries from outage window")
    """
    if not error_types:
        return []

    # Build SQL query with time window and error type filter
    # CRITICAL: Use datetime(?, 'unixepoch') to convert Unix timestamps to SQLite format
    placeholders = ','.join('?' * len(error_types))
    query = f'''
        SELECT id, scene_id, error_type, error_message, failed_at, job_data
        FROM dead_letters
        WHERE failed_at >= datetime(?, 'unixepoch')
          AND failed_at <= datetime(?, 'unixepoch')
          AND error_type IN ({placeholders})
        ORDER BY failed_at ASC
    '''

    params = [start_time, end_time] + error_types

    with dlq._get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]

    return results


# =============================================================================
# Recovery Result Dataclass
# =============================================================================


@dataclass
class RecoveryResult:
    """
    Result of DLQ recovery operation.

    Tracks total entries processed and breakdown of results:
    - recovered: Successfully re-enqueued
    - skipped_already_queued: Scene already in queue (deduplication)
    - skipped_plex_down: Plex unhealthy (pre-flight gate)
    - skipped_scene_missing: Scene deleted from Stash
    - failed: Enqueue operation failed

    Fields:
        total_dlq_entries: Total number of DLQ entries attempted
        recovered: Number successfully re-enqueued
        skipped_already_queued: Skipped due to deduplication
        skipped_plex_down: Skipped due to Plex health check failure
        skipped_scene_missing: Skipped due to scene missing from Stash
        failed: Failed to enqueue
        recovered_scene_ids: List of scene_ids that were successfully recovered
    """
    total_dlq_entries: int = 0
    recovered: int = 0
    skipped_already_queued: int = 0
    skipped_plex_down: int = 0
    skipped_scene_missing: int = 0
    failed: int = 0
    recovered_scene_ids: List[int] = field(default_factory=list)


# =============================================================================
# Recovery Operations
# =============================================================================


def recover_outage_jobs(
    dlq_entries: List[dict],
    queue: "SQLiteAckQueue",
    stash,
    plex_client: "PlexClient",
    data_dir: str
) -> RecoveryResult:
    """
    Recover DLQ entries with three-gate validation.

    Gate 1: Plex health check - abort if Plex is unhealthy
    Gate 2: Deduplication - skip entries already in queue
    Gate 3: Scene existence - skip entries for deleted scenes

    Idempotent: safe to run multiple times with same entries. Second run will
    skip all entries (already queued from first run).

    Args:
        dlq_entries: List of DLQ entry dicts from get_outage_dlq_entries()
        queue: SQLiteAckQueue instance
        stash: StashInterface instance (for find_scene())
        plex_client: PlexClient instance (for health check)
        data_dir: Queue data directory (for get_queued_scene_ids())

    Returns:
        RecoveryResult with counts and recovered scene_ids

    Examples:
        >>> from sync_queue.dlq_recovery import recover_outage_jobs, get_outage_dlq_entries
        >>> entries = get_outage_dlq_entries(dlq, start, end, ["PlexServerDown"])
        >>> result = recover_outage_jobs(entries, queue, stash, plex_client, data_dir)
        >>> print(f"Recovered {result.recovered} jobs, skipped {result.skipped_already_queued}")
    """
    result = RecoveryResult(total_dlq_entries=len(dlq_entries))

    # Gate 1: Pre-flight Plex health check
    # If Plex is unhealthy, skip all entries immediately
    is_healthy, _ = check_plex_health(plex_client)
    if not is_healthy:
        result.skipped_plex_down = len(dlq_entries)
        return result

    # Gate 2: Get currently queued scene_ids for deduplication
    queue_path = queue.path
    already_queued = get_queued_scene_ids(queue_path)

    # Process each DLQ entry
    for entry in dlq_entries:
        scene_id = entry['scene_id']

        # Skip if already in queue (deduplication)
        if scene_id in already_queued:
            result.skipped_already_queued += 1
            continue

        # Gate 3: Check scene still exists in Stash
        scene = stash.find_scene(scene_id)
        if scene is None:
            result.skipped_scene_missing += 1
            continue

        # Deserialize job_data and re-enqueue
        try:
            job = pickle.loads(entry['job_data'])
            update_type = job.get('update_type', 'metadata')
            data = job.get('data', {})

            enqueue(queue, scene_id, update_type, data)

            # Track success
            result.recovered += 1
            result.recovered_scene_ids.append(scene_id)

            # Add to in-memory dedup set (prevent duplicates within same batch)
            already_queued.add(scene_id)

        except Exception:
            # Enqueue failed - increment failed count
            result.failed += 1
            continue

    return result
