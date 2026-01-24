"""
Background worker for processing sync jobs.

Implements reliable job processing with acknowledgment workflow:
- Acknowledges successful jobs
- Nacks transient failures for retry
- Moves permanently failed jobs to DLQ
"""

import time
import threading
from typing import Optional

try:
    from queue.operations import get_pending, ack_job, nack_job, fail_job
    from queue.dlq import DeadLetterQueue
except ImportError:
    get_pending = ack_job = nack_job = fail_job = None
    DeadLetterQueue = None


class TransientError(Exception):
    """Retry-able errors (network, timeout, 5xx)"""
    pass


class PermanentError(Exception):
    """Non-retry-able errors (4xx except 429, validation)"""
    pass


class SyncWorker:
    """
    Background worker that processes sync jobs from the queue.

    Runs in a daemon thread and processes jobs with proper acknowledgment:
    - Success: ack_job
    - Transient failure: nack_job (retry up to max_retries)
    - Permanent failure or max retries: fail_job + DLQ
    """

    def __init__(self, queue, dlq: 'DeadLetterQueue', max_retries: int = 5):
        """
        Initialize sync worker.

        Args:
            queue: SQLiteAckQueue instance
            dlq: DeadLetterQueue for permanently failed jobs
            max_retries: Maximum retry attempts before moving to DLQ
        """
        self.queue = queue
        self.dlq = dlq
        self.max_retries = max_retries
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._retry_counts: dict[int, int] = {}  # pqid -> retry count

    def start(self):
        """Start the background worker thread"""
        if self.running:
            print("[PlexSync Worker] Already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        print("[PlexSync Worker] Started")

    def stop(self):
        """Stop the background worker thread"""
        if not self.running:
            return

        print("[PlexSync Worker] Stopping...")
        self.running = False

        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                print("[PlexSync Worker] WARNING: Thread did not stop cleanly")

        print("[PlexSync Worker] Stopped")

    def _worker_loop(self):
        """Main worker loop - runs in background thread"""
        while self.running:
            try:
                # Get next pending job (10 second timeout)
                item = get_pending(self.queue, timeout=10)
                if item is None:
                    # Timeout, continue loop
                    continue

                pqid = item.get('pqid')
                scene_id = item.get('scene_id')
                print(f"[PlexSync Worker] Processing job {pqid} for scene {scene_id}")

                try:
                    # Process the job (stub for now, real implementation in Phase 3)
                    self._process_job(item)

                    # Success: acknowledge job
                    ack_job(self.queue, item)
                    self._retry_counts.pop(pqid, None)
                    print(f"[PlexSync Worker] Job {pqid} completed")

                except TransientError as e:
                    # Transient error: retry up to max_retries
                    retry_count = self._retry_counts.get(pqid, 0) + 1
                    self._retry_counts[pqid] = retry_count

                    if retry_count >= self.max_retries:
                        print(f"[PlexSync Worker] Job {pqid} exceeded max retries, moving to DLQ")
                        fail_job(self.queue, item)
                        self.dlq.add(item, e, retry_count)
                        self._retry_counts.pop(pqid, None)
                    else:
                        print(f"[PlexSync Worker] Job {pqid} failed (attempt {retry_count}/{self.max_retries}), will retry: {e}")
                        nack_job(self.queue, item)

                except PermanentError as e:
                    # Permanent error: move to DLQ immediately
                    print(f"[PlexSync Worker] Job {pqid} permanent failure, moving to DLQ: {e}")
                    fail_job(self.queue, item)
                    self.dlq.add(item, e, self._retry_counts.get(pqid, 0))
                    self._retry_counts.pop(pqid, None)

                except Exception as e:
                    # Unknown error: treat as transient
                    print(f"[PlexSync Worker] Job {pqid} unexpected error (treating as transient): {e}")
                    nack_job(self.queue, item)

            except Exception as e:
                # Worker loop error: log and continue
                print(f"[PlexSync Worker] Worker loop error: {e}")
                time.sleep(1)  # Avoid tight loop on persistent errors

    def _process_job(self, job: dict):
        """
        Process a sync job (stub for Phase 3).

        This will be implemented in Phase 3 when we add the Plex API client.
        For now, just log what would be done.

        Args:
            job: Job dict with scene_id, update_type, data

        Raises:
            TransientError: For retry-able errors
            PermanentError: For permanent failures
        """
        scene_id = job.get('scene_id')
        update_type = job.get('update_type')
        print(f"[PlexSync Worker] STUB: Would sync scene {scene_id} ({update_type}) to Plex")
        # Phase 3 will implement:
        # - Fetch scene metadata from Stash
        # - Validate required fields
        # - Find/create Plex item
        # - Update Plex metadata
        # - Handle Plex API errors (raise TransientError or PermanentError)
        pass
