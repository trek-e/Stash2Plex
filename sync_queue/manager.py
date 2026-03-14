"""
Queue manager for persistent job storage.

Handles queue initialization, lifecycle management, and shutdown.
"""

import os
from typing import Optional
try:
    from persistqueue.sqlackqueue import SQLiteAckQueue as _SQLiteAckQueue
except ImportError:
    _SQLiteAckQueue = None  # Will fail at runtime with clear error


class QueueManager:
    """
    Manages SQLite-backed persistent queue lifecycle.

    Stores queue in Stash plugin data directory. Queue survives
    process restarts. Stale in-progress items from crashed processes
    are handled by the worker's cross-session dedup logic rather than
    auto_resume (which caused race conditions across concurrent processes).
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

        # Determine data directory
        if data_dir is None:
            # Try environment variable first
            stash_data = os.getenv('STASH_PLUGIN_DATA')
            if stash_data:
                data_dir = stash_data
            else:
                # Fallback to default location
                home = os.path.expanduser('~')
                data_dir = os.path.join(home, '.stash', 'plugins', 'Stash2Plex', 'data')

        self.data_dir = data_dir
        self.queue_path = os.path.join(data_dir, 'queue')

        # Create directory if needed
        os.makedirs(self.queue_path, exist_ok=True)

        # Initialize queue
        self._queue = self._init_queue()

        print(f"Queue initialized at {self.queue_path}")

    def _init_queue(self):
        """
        Create SQLiteAckQueue with production settings.

        auto_resume is set to False to prevent race conditions where a new
        plugin process resets another process's in-progress items back to
        pending.  Crash recovery (re-processing items left in status=2 from
        a killed process) is handled by the worker's cross-session dedup:
        if a scene was never synced (no sync_timestamp), it stays in queue
        and will be picked up naturally; if it WAS synced, the stale entry
        is acked and skipped.

        Returns:
            Configured SQLiteAckQueue instance
        """
        return _SQLiteAckQueue(
            path=self.queue_path,
            auto_commit=True,      # Required for AckQueue - immediate persistence
            multithreading=True,   # Thread-safe operations
            auto_resume=False      # Prevent cross-process race conditions
        )

    def get_queue(self) -> 'persistqueue.SQLiteAckQueue':
        """
        Get the queue instance.

        Returns:
            SQLiteAckQueue for job operations
        """
        return self._queue

    def shutdown(self):
        """
        Clean shutdown of queue manager.

        Logs final statistics and closes connections.
        """
        # Queue doesn't require explicit close, but log stats
        print("Queue manager shutting down")

        # Note: persist-queue handles cleanup automatically
        # No explicit close() needed for SQLiteAckQueue
