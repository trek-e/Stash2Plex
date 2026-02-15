"""
Queue operations for job lifecycle management.

Stateless operations that work on queue instance passed in.
"""

import itertools
import json
import os
import pickle
import sqlite3
import time
from typing import Optional

from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("Queue")

# Simple counter for job IDs (resets on restart, used for log correlation only)
_job_counter = itertools.count(1)

try:
    import persistqueue
    from persistqueue.exceptions import Empty
except ImportError:
    persistqueue = None
    from queue import Empty  # fallback for tests


def enqueue(queue: 'persistqueue.SQLiteAckQueue', scene_id: int, update_type: str, data: dict) -> dict:
    """
    Enqueue a sync job.

    Args:
        queue: SQLiteAckQueue instance
        scene_id: Stash scene ID
        update_type: Type of update (e.g., "metadata", "image")
        data: Metadata to sync to Plex

    Returns:
        The enqueued job dict

    Example:
        >>> from persistqueue import SQLiteAckQueue
        >>> queue = SQLiteAckQueue('/tmp/queue')
        >>> job = enqueue(queue, scene_id=123, update_type='metadata',
        ...               data={'title': 'Example Scene'})
        >>> print(job['scene_id'])
        123
    """
    job = {
        'pqid': next(_job_counter),
        'scene_id': scene_id,
        'update_type': update_type,
        'data': data,
        'enqueued_at': time.time(),
        'job_key': f"scene_{scene_id}"
    }

    queue.put(job)
    log_trace(f"Enqueued sync job for scene {scene_id}")

    return job


def get_pending(queue: 'persistqueue.SQLiteAckQueue', timeout: float = 0) -> Optional[dict]:
    """
    Get next pending job from queue.

    Args:
        queue: SQLiteAckQueue instance
        timeout: Seconds to wait for job (0 = non-blocking)

    Returns:
        Job dict with 'pqid' field added by persist-queue, or None if timeout/empty
    """
    try:
        job = queue.get(timeout=timeout)
        return job
    except Empty:
        return None


def ack_job(queue: 'persistqueue.SQLiteAckQueue', job: dict):
    """
    Acknowledge successful job completion.

    Args:
        queue: SQLiteAckQueue instance
        job: Job dict (must have 'pqid' field from get_pending)
    """
    queue.ack(job)
    pqid = job.get('pqid', '?')
    log_trace(f"Job {pqid} completed")


def nack_job(queue: 'persistqueue.SQLiteAckQueue', job: dict):
    """
    Return job to queue for retry.

    Args:
        queue: SQLiteAckQueue instance
        job: Job dict (must have 'pqid' field from get_pending)
    """
    queue.nack(job)
    pqid = job.get('pqid', '?')
    log_trace(f"Job {pqid} returned to queue for retry")


def fail_job(queue: 'persistqueue.SQLiteAckQueue', job: dict):
    """
    Mark job as permanently failed.

    Args:
        queue: SQLiteAckQueue instance
        job: Job dict (must have 'pqid' field from get_pending)
    """
    queue.ack_failed(job)
    pqid = job.get('pqid', '?')
    log_debug(f"Job {pqid} marked as failed")


def get_stats(queue_path: str) -> dict:
    """
    Get queue statistics by status.

    Queries SQLite database directly for status counts.

    Args:
        queue_path: Path to queue directory (contains data.db)

    Returns:
        Dict with status counts: {
            'pending': int,
            'in_progress': int,
            'completed': int,
            'failed': int
        }

    Status codes from persist-queue AckStatus enum:
        0 = inited
        1 = ready (pending)
        2 = unack (in_progress)
        5 = acked (completed)
        9 = ack_failed (failed)
    """
    db_path = os.path.join(queue_path, 'data.db')

    # Return zeros if database doesn't exist yet
    if not os.path.exists(db_path):
        return {
            'pending': 0,
            'in_progress': 0,
            'completed': 0,
            'failed': 0
        }

    conn = sqlite3.connect(db_path)
    try:
        # Find the ack_queue table (persist-queue uses ack_queue_default by default)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ack_queue%'"
        )
        table = cursor.fetchone()
        if not table:
            # Table doesn't exist yet (no jobs enqueued)
            return {
                'pending': 0,
                'in_progress': 0,
                'completed': 0,
                'failed': 0
            }

        table_name = table[0]

        cursor = conn.execute(f'''
            SELECT status, COUNT(*) as count
            FROM {table_name}
            GROUP BY status
        ''')

        stats = {
            'pending': 0,
            'in_progress': 0,
            'completed': 0,
            'failed': 0
        }

        for row in cursor:
            status_code = row[0]
            count = row[1]

            # Map status codes to categories
            # 0 and 1 are both "pending" (ready to process)
            if status_code in (0, 1):
                stats['pending'] += count
            elif status_code == 2:
                stats['in_progress'] += count
            elif status_code == 5:
                stats['completed'] += count
            elif status_code == 9:
                stats['failed'] += count

        return stats

    finally:
        conn.close()


def clear_pending_items(queue_path: str) -> int:
    """
    Clear all pending and stale in-progress items from queue.

    Deletes items with status 0 (inited), 1 (ready), or 2 (unack/in-progress).
    Status 2 items are from previous sessions where the worker was killed
    mid-processing — they would be auto-resumed and reprocessed otherwise.
    Does NOT delete completed (5) or failed (9) items.

    Args:
        queue_path: Path to queue directory (contains data.db)

    Returns:
        Number of items deleted
    """
    db_path = os.path.join(queue_path, 'data.db')

    if not os.path.exists(db_path):
        return 0

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ack_queue%'"
        )
        table = cursor.fetchone()
        if not table:
            return 0

        table_name = table[0]
        cursor = conn.execute(
            f"DELETE FROM {table_name} WHERE status IN (0, 1, 2)"
        )
        deleted = cursor.rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_queued_scene_ids(queue_path: str) -> set:
    """
    Get scene_ids for all items currently in queue (pending or in-progress).

    Queries SQLite directly and deserializes job data to extract scene_ids.
    Used for deduplication before batch enqueue operations.

    Args:
        queue_path: Path to queue directory (contains data.db)

    Returns:
        Set of scene_id integers currently in queue
    """
    db_path = os.path.join(queue_path, 'data.db')
    if not os.path.exists(db_path):
        return set()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ack_queue%'"
        )
        table = cursor.fetchone()
        if not table:
            return set()

        table_name = table[0]
        cursor = conn.execute(
            f"SELECT data FROM {table_name} WHERE status IN (0, 1, 2)"
        )

        scene_ids = set()
        for row in cursor:
            try:
                job = pickle.loads(row[0])
                sid = job.get('scene_id')
                if sid is not None:
                    scene_ids.add(int(sid))
            except Exception:
                continue
        return scene_ids
    finally:
        conn.close()


def _get_sync_timestamps_path(data_dir: str) -> str:
    """Get path to sync timestamps JSON file."""
    return os.path.join(data_dir, 'sync_timestamps.json')


def load_sync_timestamps(data_dir: str) -> dict[int, float]:
    """
    Load sync timestamps from JSON file.

    Args:
        data_dir: Queue data directory (same as queue_path)

    Returns:
        Dict mapping scene_id -> last_synced_at timestamp
    """
    path = _get_sync_timestamps_path(data_dir)
    if not os.path.exists(path):
        return {}

    try:
        with open(path, 'r') as f:
            data = json.load(f)
            # JSON keys are strings, convert back to int
            return {int(k): v for k, v in data.items()}
    except (json.JSONDecodeError, IOError):
        return {}


def save_sync_timestamp(data_dir: str, scene_id: int, timestamp: float) -> None:
    """
    Save sync timestamp for a scene.

    Args:
        data_dir: Queue data directory
        scene_id: Scene ID that was synced
        timestamp: time.time() when sync completed
    """
    path = _get_sync_timestamps_path(data_dir)

    # Load existing timestamps
    timestamps = load_sync_timestamps(data_dir)

    # Update with new timestamp
    timestamps[scene_id] = timestamp

    # Write back atomically (write to temp, rename)
    temp_path = path + '.tmp'
    with open(temp_path, 'w') as f:
        json.dump(timestamps, f)
    os.replace(temp_path, path)
