"""
Background worker for processing sync jobs.

Implements reliable job processing with acknowledgment workflow:
- Acknowledges successful jobs
- Retries transient failures with exponential backoff
- Moves permanently failed jobs to DLQ
- Circuit breaker pauses processing during Plex outages
"""

import time
import threading
from typing import Optional, TYPE_CHECKING

try:
    from queue.operations import get_pending, ack_job, nack_job, fail_job, enqueue
    from queue.dlq import DeadLetterQueue
except ImportError:
    get_pending = ack_job = nack_job = fail_job = enqueue = None
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
    - Transient failure: exponential backoff retry with metadata in job
    - Permanent failure or max retries: fail_job + DLQ
    - Circuit breaker: pauses processing after consecutive failures
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
            max_retries: Maximum retry attempts before moving to DLQ (default for standard errors)
        """
        self.queue = queue
        self.dlq = dlq
        self.config = config
        self.max_retries = max_retries
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._plex_client: Optional['PlexClient'] = None

        # DLQ status logging interval
        self._jobs_since_dlq_log = 0
        self._dlq_log_interval = 10  # Log DLQ status every 10 jobs

        # Circuit breaker for resilience during Plex outages
        from worker.circuit_breaker import CircuitBreaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            success_threshold=1
        )

    def start(self):
        """Start the background worker thread"""
        if self.running:
            print("[PlexSync Worker] Already running")
            return

        # Cleanup old DLQ entries
        retention_days = getattr(self.config, 'dlq_retention_days', 30)
        self.dlq.delete_older_than(days=retention_days)

        # Log DLQ status on startup
        self._log_dlq_status()

        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        print("[PlexSync Worker] Started")

    def _log_dlq_status(self):
        """Log DLQ status if jobs present."""
        count = self.dlq.get_count()
        if count > 0:
            print(f"[PlexSync Worker] WARNING: DLQ contains {count} failed jobs requiring review")
            recent = self.dlq.get_recent(limit=5)
            for entry in recent:
                print(
                    f"  DLQ #{entry['id']}: scene {entry['scene_id']} - "
                    f"{entry['error_type']}: {entry['error_message'][:80]}"
                )

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

    def _prepare_for_retry(self, job: dict, error: Exception) -> dict:
        """
        Add retry metadata to job before re-enqueueing.

        Stores retry_count, next_retry_at, and last_error_type in job dict
        so retry state survives worker restart (crash-safe).

        Args:
            job: Job dict to update
            error: The exception that caused the retry

        Returns:
            Updated job dict with retry metadata
        """
        from worker.backoff import calculate_delay, get_retry_params

        base, cap, max_retries = get_retry_params(error)
        retry_count = job.get('retry_count', 0) + 1
        delay = calculate_delay(retry_count - 1, base, cap)  # -1 because we just incremented

        job['retry_count'] = retry_count
        job['next_retry_at'] = time.time() + delay
        job['last_error_type'] = type(error).__name__
        return job

    def _is_ready_for_retry(self, job: dict) -> bool:
        """
        Check if job's backoff delay has elapsed.

        Args:
            job: Job dict with optional next_retry_at field

        Returns:
            True if job is ready for processing (no delay or delay elapsed)
        """
        next_retry_at = job.get('next_retry_at', 0)
        return time.time() >= next_retry_at

    def _get_max_retries_for_error(self, error: Exception) -> int:
        """
        Get max retries based on error type.

        PlexNotFound errors get more retries (12) to allow for library scanning.
        Other transient errors use the standard max_retries (5).

        Args:
            error: The exception that triggered the retry

        Returns:
            Maximum number of retries for this error type
        """
        from worker.backoff import get_retry_params
        _, _, max_retries = get_retry_params(error)
        return max_retries

    def _requeue_with_metadata(self, job: dict):
        """
        Re-enqueue job with updated retry metadata.

        persist-queue's nack() doesn't support modifying job data,
        so we ack the current job and enqueue a fresh copy with
        updated metadata.

        Args:
            job: Job dict with retry metadata already added
        """
        # Extract original job fields for re-enqueue
        scene_id = job.get('scene_id')
        update_type = job.get('update_type')
        data = job.get('data', {})

        # Create new job with all metadata preserved
        new_job = {
            'scene_id': scene_id,
            'update_type': update_type,
            'data': data,
            'enqueued_at': job.get('enqueued_at', time.time()),
            'job_key': job.get('job_key', f"scene_{scene_id}"),
            # Preserve retry metadata
            'retry_count': job.get('retry_count', 0),
            'next_retry_at': job.get('next_retry_at', 0),
            'last_error_type': job.get('last_error_type'),
        }

        # Ack the old job (removes from queue)
        ack_job(self.queue, job)
        # Enqueue fresh copy with metadata
        self.queue.put(new_job)

    def _worker_loop(self):
        """Main worker loop - runs in background thread"""
        from worker.circuit_breaker import CircuitState

        while self.running:
            try:
                # Check circuit breaker first - pause if Plex is down
                if not self.circuit_breaker.can_execute():
                    print(f"[PlexSync Worker] Circuit OPEN, sleeping {self.config.poll_interval}s")
                    time.sleep(self.config.poll_interval)
                    continue

                # Get next pending job (10 second timeout)
                item = get_pending(self.queue, timeout=10)
                if item is None:
                    # Timeout, continue loop
                    continue

                # Check if backoff delay has elapsed
                if not self._is_ready_for_retry(item):
                    # Put back in queue - not ready yet
                    nack_job(self.queue, item)
                    time.sleep(0.1)  # Small delay to avoid tight loop
                    continue

                pqid = item.get('pqid')
                scene_id = item.get('scene_id')
                retry_count = item.get('retry_count', 0)
                print(f"[PlexSync Worker] Processing job {pqid} for scene {scene_id} (attempt {retry_count + 1})")

                try:
                    # Process the job
                    self._process_job(item)

                    # Success: acknowledge job and record with circuit breaker
                    ack_job(self.queue, item)
                    self.circuit_breaker.record_success()
                    print(f"[PlexSync Worker] Job {pqid} completed")

                    # Periodic DLQ status logging
                    self._jobs_since_dlq_log += 1
                    if self._jobs_since_dlq_log >= self._dlq_log_interval:
                        self._log_dlq_status()
                        self._jobs_since_dlq_log = 0

                except TransientError as e:
                    # Record failure with circuit breaker
                    self.circuit_breaker.record_failure()
                    if self.circuit_breaker.state == CircuitState.OPEN:
                        print("[PlexSync Worker] Circuit breaker OPENED - pausing processing")

                    # Prepare job for retry with backoff metadata
                    job = self._prepare_for_retry(item, e)
                    max_retries = self._get_max_retries_for_error(e)
                    job_retry_count = job.get('retry_count', 0)

                    if job_retry_count >= max_retries:
                        print(f"[PlexSync Worker] Job {pqid} exceeded max retries ({max_retries}), moving to DLQ")
                        fail_job(self.queue, item)
                        self.dlq.add(job, e, job_retry_count)
                    else:
                        delay = job.get('next_retry_at', 0) - time.time()
                        print(f"[PlexSync Worker] Job {pqid} failed (attempt {job_retry_count}/{max_retries}), retry in {delay:.1f}s: {e}")
                        self._requeue_with_metadata(job)

                except PermanentError as e:
                    # Permanent error: move to DLQ immediately (doesn't count against circuit)
                    print(f"[PlexSync Worker] Job {pqid} permanent failure, moving to DLQ: {e}")
                    fail_job(self.queue, item)
                    self.dlq.add(item, e, item.get('retry_count', 0))

                except Exception as e:
                    # Unknown error: treat as transient with circuit breaker
                    self.circuit_breaker.record_failure()
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
