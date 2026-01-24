"""
Background worker for processing sync jobs.

Implements reliable job processing with acknowledgment workflow:
- Acknowledges successful jobs
- Nacks transient failures for retry
- Moves permanently failed jobs to DLQ
"""

import time
import threading
from typing import Optional, TYPE_CHECKING

try:
    from queue.operations import get_pending, ack_job, nack_job, fail_job
    from queue.dlq import DeadLetterQueue
except ImportError:
    get_pending = ack_job = nack_job = fail_job = None
    DeadLetterQueue = None

if TYPE_CHECKING:
    from validation.config import PlexSyncConfig
    from plex.client import PlexClient


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

    def __init__(
        self,
        queue,
        dlq: 'DeadLetterQueue',
        config: 'PlexSyncConfig',
        max_retries: int = 5,
    ):
        """
        Initialize sync worker.

        Args:
            queue: SQLiteAckQueue instance
            dlq: DeadLetterQueue for permanently failed jobs
            config: PlexSyncConfig with Plex URL, token, and timeouts
            max_retries: Maximum retry attempts before moving to DLQ
        """
        self.queue = queue
        self.dlq = dlq
        self.config = config
        self.max_retries = max_retries
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._retry_counts: dict[int, int] = {}  # pqid -> retry count
        self._plex_client: Optional['PlexClient'] = None

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

    def _get_plex_client(self) -> 'PlexClient':
        """
        Get PlexClient with lazy initialization.

        Creates PlexClient on first use to avoid connecting to Plex
        until we actually need to process a job.

        Returns:
            PlexClient instance configured with URL, token, and timeouts
        """
        if self._plex_client is None:
            from plex.client import PlexClient
            self._plex_client = PlexClient(
                url=self.config.plex_url,
                token=self.config.plex_token,
                connect_timeout=self.config.plex_connect_timeout,
                read_timeout=self.config.plex_read_timeout,
            )
        return self._plex_client

    def _process_job(self, job: dict):
        """
        Process a sync job by updating Plex metadata.

        Finds the Plex item matching the job's file path and updates
        its metadata based on the update_type.

        Args:
            job: Job dict with scene_id, update_type, data
                - scene_id: Stash scene ID
                - update_type: Type of update (e.g., 'metadata')
                - data: Dict containing 'path' and metadata fields

        Raises:
            TransientError: For retry-able errors (network, timeout)
            PermanentError: For permanent failures (missing path, bad data)
        """
        # Import Plex exceptions lazily to avoid circular import
        from plex.exceptions import (
            PlexTemporaryError,
            PlexPermanentError,
            PlexNotFound,
            translate_plex_exception,
        )
        from plex.matcher import find_plex_item_by_path

        scene_id = job.get('scene_id')
        update_type = job.get('update_type')
        data = job.get('data', {})
        file_path = data.get('path')

        if not file_path:
            raise PermanentError(f"Job {scene_id} missing file path")

        try:
            # Get Plex client (lazy init)
            client = self._get_plex_client()

            # Search all library sections to find the item
            plex_item = None
            for section in client.server.library.sections():
                plex_item = find_plex_item_by_path(section, file_path)
                if plex_item:
                    break

            if not plex_item:
                raise PlexNotFound(f"Could not find Plex item for path: {file_path}")

            # Update metadata based on update_type
            if update_type == 'metadata':
                self._update_metadata(plex_item, data)
            else:
                print(f"[PlexSync Worker] Unknown update_type: {update_type}")

        except (PlexTemporaryError, PlexPermanentError, PlexNotFound):
            # Re-raise already classified exceptions
            raise
        except Exception as e:
            # Translate unknown Plex/network errors to our hierarchy
            raise translate_plex_exception(e)

    def _update_metadata(self, plex_item, data: dict):
        """
        Update Plex item metadata from sync job data.

        Uses plex_item.edit() to update metadata fields, then reloads
        the item to confirm changes.

        Args:
            plex_item: Plex Video item to update
            data: Dict containing metadata fields (title, studio, etc.)
        """
        # Build edits dict for plex_item.edit()
        edits = {}
        if 'title' in data:
            edits['title.value'] = data['title']
        if 'studio' in data:
            edits['studio.value'] = data['studio']
        if 'summary' in data:
            edits['summary.value'] = data['summary']
        if 'tagline' in data:
            edits['tagline.value'] = data['tagline']
        # Add more fields as needed in future phases

        if edits:
            plex_item.edit(**edits)
            plex_item.reload()
            print(f"[PlexSync Worker] Updated metadata for: {plex_item.title}")
