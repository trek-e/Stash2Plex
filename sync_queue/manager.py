"""
Queue manager for persistent job storage with built-in deduplication.

Owns the SQLiteAckQueue lifecycle and an in-memory pending-scene set so
callers never need to implement their own dedup logic.
"""

import os
import time
from typing import Optional

from sync_queue.operations import (
    EnqueueResult,
    _job_counter,
    ack_job,
    clear_pending_items,
    fail_job,
    get_pending,
    get_queued_scene_ids,
    get_stats,
    nack_job,
    resume_orphaned_items,
)

try:
    from persistqueue.sqlackqueue import SQLiteAckQueue as _SQLiteAckQueue
except ImportError:
    _SQLiteAckQueue = None  # Will fail at runtime with clear error


class QueueManager:
    """
    Manages SQLite-backed persistent queue with built-in scene deduplication.

    Dedup strategy (two-tier, fast path first):
      1. In-memory _pending_scene_ids set — O(1), no I/O. Populated at
         try_enqueue time, drained at ack/nack/fail time.
      2. SQLite get_queued_scene_ids — used on set miss to catch scenes that
         entered the queue before this process started (cross-session guard).

    Callers use try_enqueue() instead of raw enqueue() and get an EnqueueResult
    telling them whether the job was actually added and why not if it wasn't.
    """

    def __init__(self, data_dir: Optional[str] = None):
        """
        Initialize queue manager.

        Args:
            data_dir: Directory for queue storage. Defaults to
                     $STASH_PLUGIN_DATA or ~/.stash/plugins/Stash2Plex/data
        """
        if _SQLiteAckQueue is None:
            raise ImportError(
                "persist-queue not installed. "
                "Run: pip install persist-queue>=1.1.0"
            )

        if data_dir is None:
            stash_data = os.getenv('STASH_PLUGIN_DATA')
            if stash_data:
                data_dir = stash_data
            else:
                home = os.path.expanduser('~')
                data_dir = os.path.join(home, '.stash', 'plugins', 'Stash2Plex', 'data')

        self.data_dir = data_dir
        self.queue_path = os.path.join(data_dir, 'queue')

        os.makedirs(self.queue_path, exist_ok=True)

        self._queue = self._init_queue()

        # In-memory dedup set — mirrors what's currently pending in the queue.
        # Populated by try_enqueue, drained by ack/nack/fail.
        # Resets on process restart (acceptable — cross-session dedup falls
        # through to the SQLite check on the next try_enqueue call).
        self._pending_scene_ids: set[int] = set()

        print(f"Queue initialized at {self.queue_path}")

    def _init_queue(self):
        """
        Create SQLiteAckQueue with production settings.

        auto_resume is set to False to prevent race conditions where a new
        plugin process resets another process's in-progress items back to
        pending.  Crash recovery is handled by the worker's cross-session dedup:
        if a scene was never synced (no sync_timestamp), it stays in queue
        and will be picked up naturally; if it WAS synced, the stale entry
        is acked and skipped.
        """
        return _SQLiteAckQueue(
            path=self.queue_path,
            auto_commit=True,      # Required for AckQueue - immediate persistence
            multithreading=True,   # Thread-safe operations
            auto_resume=False      # Prevent cross-process race conditions
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def try_enqueue(self, scene_id: int, update_type: str, data: dict) -> EnqueueResult:
        """
        Enqueue a sync job, skipping duplicates already pending or recently completed.

        Two-tier dedup:
          1. In-memory set (fast path, no I/O)
          2. SQLite scan (cross-session guard, only on set miss)

        Args:
            scene_id: Stash scene ID
            update_type: Job type (e.g. "metadata")
            data: Payload to sync to Plex

        Returns:
            EnqueueResult with enqueued=True and the job dict, or
            enqueued=False with reason "already_pending" or "recently_completed".
        """
        scene_id = int(scene_id)

        # Tier 1: in-memory set (zero I/O — fast path for hook handlers)
        if scene_id in self._pending_scene_ids:
            return EnqueueResult(enqueued=False, job=None, reason="already_pending")

        # Tier 2: SQLite cross-session check (catches scenes enqueued before
        # this process started, including recently-completed rows)
        pending_only = get_queued_scene_ids(self.queue_path, completed_window=0)
        if scene_id in pending_only:
            return EnqueueResult(enqueued=False, job=None, reason="already_pending")

        recently_completed = get_queued_scene_ids(self.queue_path, completed_window=604800.0)
        if scene_id in recently_completed:
            return EnqueueResult(enqueued=False, job=None, reason="recently_completed")

        job = {
            'job_id': next(_job_counter),
            'scene_id': scene_id,
            'update_type': update_type,
            'data': data,
            'enqueued_at': time.time(),
            'job_key': f"scene_{scene_id}",
        }
        self._queue.put(job)
        self._pending_scene_ids.add(scene_id)

        return EnqueueResult(enqueued=True, job=job, reason=None)

    def get_pending(self, timeout: float = 0) -> Optional[dict]:
        """Get next pending job (non-blocking by default)."""
        return get_pending(self._queue, timeout=timeout)

    def ack(self, job: dict) -> None:
        """Acknowledge successful completion; removes scene from pending set."""
        ack_job(self._queue, job)
        scene_id = job.get('scene_id')
        if scene_id is not None:
            self._pending_scene_ids.discard(int(scene_id))

    def nack(self, job: dict) -> None:
        """Return job to queue for retry; removes scene from pending set."""
        nack_job(self._queue, job)
        scene_id = job.get('scene_id')
        if scene_id is not None:
            self._pending_scene_ids.discard(int(scene_id))

    def fail(self, job: dict) -> None:
        """Mark job as permanently failed; removes scene from pending set."""
        fail_job(self._queue, job)
        scene_id = job.get('scene_id')
        if scene_id is not None:
            self._pending_scene_ids.discard(int(scene_id))

    def reenqueue(self, old_job: dict, new_job: dict) -> None:
        """
        Ack the current job and put a retry copy, bypassing dedup.

        Used by the worker retry path: persist-queue's nack() doesn't support
        modifying job data, so retries are ack+reput with updated metadata.
        The scene stays in _pending_scene_ids because it's still in flight.
        """
        ack_job(self._queue, old_job)
        self._queue.put(new_job)

    def resume_orphaned(self) -> int:
        """Reset orphaned in-progress items back to pending. Returns count resumed."""
        return resume_orphaned_items(self.queue_path)

    def get_stats(self) -> dict:
        """Return queue statistics by status bucket."""
        return get_stats(self.queue_path)

    def clear_pending(self) -> int:
        """Delete all pending and in-progress items. Returns count deleted."""
        deleted = clear_pending_items(self.queue_path)
        self._pending_scene_ids.clear()
        return deleted

    def get_queued_scene_ids(self, completed_window: float = 604800.0) -> set[int]:
        """Return scene_ids currently in queue (pending, in-progress, recently completed)."""
        return get_queued_scene_ids(self.queue_path, completed_window=completed_window)

    def get_queue(self) -> '_SQLiteAckQueue':
        """Return the raw SQLiteAckQueue for callers that need direct queue access."""
        return self._queue

    def shutdown(self) -> None:
        """Clean shutdown of queue manager."""
        print("Queue manager shutting down")
