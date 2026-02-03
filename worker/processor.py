"""
Background worker for processing sync jobs.

Implements reliable job processing with acknowledgment workflow:
- Acknowledges successful jobs
- Retries transient failures with exponential backoff
- Moves permanently failed jobs to DLQ
- Circuit breaker pauses processing during Plex outages
"""

import sys
import time
import threading
import logging
from typing import Optional, TYPE_CHECKING


# Stash plugin log levels
def log_trace(msg): print(f"\x01t\x02[PlexSync Worker] {msg}", file=sys.stderr)
def log_debug(msg): print(f"\x01d\x02[PlexSync Worker] {msg}", file=sys.stderr)
def log_info(msg): print(f"\x01i\x02[PlexSync Worker] {msg}", file=sys.stderr)
def log_warn(msg): print(f"\x01w\x02[PlexSync Worker] {msg}", file=sys.stderr)
def log_error(msg): print(f"\x01e\x02[PlexSync Worker] {msg}", file=sys.stderr)

try:
    from sync_queue.operations import get_pending, ack_job, nack_job, fail_job, enqueue, save_sync_timestamp
    from sync_queue.dlq import DeadLetterQueue
    from hooks.handlers import unmark_scene_pending
except ImportError:
    get_pending = ack_job = nack_job = fail_job = enqueue = save_sync_timestamp = None
    DeadLetterQueue = None
    unmark_scene_pending = None

logger = logging.getLogger('PlexSync.worker')

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
        data_dir: Optional[str] = None,
        max_retries: int = 5,
    ):
        """
        Initialize sync worker.

        Args:
            queue: SQLiteAckQueue instance
            dlq: DeadLetterQueue for permanently failed jobs
            config: PlexSyncConfig with Plex URL, token, and timeouts
            data_dir: Plugin data directory for sync timestamp updates
            max_retries: Maximum retry attempts before moving to DLQ (default for standard errors)
        """
        self.queue = queue
        self.dlq = dlq
        self.config = config
        self.data_dir = data_dir
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
            print("[PlexSync Worker] Already running", file=sys.stderr)
            return

        # Cleanup old DLQ entries
        retention_days = getattr(self.config, 'dlq_retention_days', 30)
        self.dlq.delete_older_than(days=retention_days)

        # Log DLQ status on startup
        self._log_dlq_status()

        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        log_info("Started")

    def _log_dlq_status(self):
        """Log DLQ status if jobs present."""
        count = self.dlq.get_count()
        if count > 0:
            log_warn(f" DLQ contains {count} failed jobs requiring review")
            recent = self.dlq.get_recent(limit=5)
            for entry in recent:
                print(
                    f"  DLQ #{entry['id']}: scene {entry['scene_id']} - "
                    f"{entry['error_type']}: {entry['error_message'][:80]}",
                    file=sys.stderr
                )

    def stop(self):
        """Stop the background worker thread"""
        if not self.running:
            return

        print("[PlexSync Worker] Stopping...", file=sys.stderr)
        self.running = False

        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                log_warn(" Thread did not stop cleanly", file=sys.stderr)

        print("[PlexSync Worker] Stopped", file=sys.stderr)

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
                    print(f"[PlexSync Worker] Circuit OPEN, sleeping {self.config.poll_interval}s", file=sys.stderr)
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
                    log_info(f"Job {pqid} completed")

                    # Periodic DLQ status logging
                    self._jobs_since_dlq_log += 1
                    if self._jobs_since_dlq_log >= self._dlq_log_interval:
                        self._log_dlq_status()
                        self._jobs_since_dlq_log = 0

                except TransientError as e:
                    # Record failure with circuit breaker
                    self.circuit_breaker.record_failure()
                    if self.circuit_breaker.state == CircuitState.OPEN:
                        print("[PlexSync Worker] Circuit breaker OPENED - pausing processing", file=sys.stderr)

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
                    print(f"[PlexSync Worker] Job {pqid} permanent failure, moving to DLQ: {e}", file=sys.stderr)
                    fail_job(self.queue, item)
                    self.dlq.add(item, e, item.get('retry_count', 0))

                except Exception as e:
                    # Unknown error: treat as transient with circuit breaker
                    self.circuit_breaker.record_failure()
                    print(f"[PlexSync Worker] Job {pqid} unexpected error (treating as transient): {e}")
                    nack_job(self.queue, item)

            except Exception as e:
                # Worker loop error: log and continue
                print(f"[PlexSync Worker] Worker loop error: {e}", file=sys.stderr)
                time.sleep(1)  # Avoid tight loop on persistent errors

    def _fetch_stash_image(self, url: str) -> Optional[bytes]:
        """
        Fetch image from Stash URL.

        Downloads the image bytes so we can upload directly to Plex,
        avoiding issues with Plex not being able to reach Stash's internal URL.

        Args:
            url: Stash image URL (screenshot, preview, etc.)

        Returns:
            Image bytes or None if fetch failed
        """
        import urllib.request
        import urllib.error

        try:
            # Build request with authentication from Stash connection
            req = urllib.request.Request(url)

            # Add API key header if available
            api_key = getattr(self.config, 'stash_api_key', None)
            if api_key:
                req.add_header('ApiKey', api_key)

            # Add session cookie if available
            session_cookie = getattr(self.config, 'stash_session_cookie', None)
            if session_cookie:
                req.add_header('Cookie', session_cookie)

            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except urllib.error.URLError as e:
            log_warn(f" Failed to fetch image from Stash: {e}")
            return None
        except Exception as e:
            log_warn(f" Image fetch error: {e}")
            return None

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
        from plex.exceptions import PlexTemporaryError, PlexPermanentError, PlexNotFound, translate_plex_exception
        from plex.matcher import find_plex_items_with_confidence, MatchConfidence

        scene_id = job.get('scene_id')
        data = job.get('data', {})
        file_path = data.get('path')

        if not file_path:
            raise PermanentError(f"Job {scene_id} missing file path")

        try:
            client = self._get_plex_client()

            # Get library section(s) to search
            if self.config.plex_library:
                # Search only the configured library
                try:
                    sections = [client.server.library.section(self.config.plex_library)]
                    print(f"[PlexSync Worker] Searching library: {self.config.plex_library}", file=sys.stderr)
                except Exception as e:
                    raise PermanentError(f"Library '{self.config.plex_library}' not found: {e}")
            else:
                # Search all libraries (slow)
                sections = client.server.library.sections()
                print(f"[PlexSync Worker] Searching all {len(sections)} libraries (set plex_library to speed up)")

            # Search library sections, collect ALL candidates
            all_candidates = []
            for section in sections:
                try:
                    confidence, item, candidates = find_plex_items_with_confidence(section, file_path)
                    all_candidates.extend(candidates)
                except PlexNotFound:
                    continue  # No match in this section, try next

            # Deduplicate candidates (same item might be in multiple sections)
            seen_keys = set()
            unique_candidates = []
            for c in all_candidates:
                if c.key not in seen_keys:
                    seen_keys.add(c.key)
                    unique_candidates.append(c)

            # Apply confidence scoring
            if len(unique_candidates) == 0:
                raise PlexNotFound(f"Could not find Plex item for path: {file_path}")
            elif len(unique_candidates) == 1:
                # HIGH confidence - single unique match
                plex_item = unique_candidates[0]
                self._update_metadata(plex_item, data)
            else:
                # LOW confidence - multiple matches
                paths = [c.media[0].parts[0].file if c.media and c.media[0].parts else c.key for c in unique_candidates]
                if self.config.strict_matching:
                    logger.warning(
                        f"[PlexSync] LOW CONFIDENCE SKIPPED: scene {scene_id}\n"
                        f"  Stash path: {file_path}\n"
                        f"  Plex candidates ({len(unique_candidates)}): {paths}"
                    )
                    raise PermanentError(f"Low confidence match skipped (strict_matching=true)")
                else:
                    plex_item = unique_candidates[0]
                    logger.warning(
                        f"[PlexSync] LOW CONFIDENCE SYNCED: scene {scene_id}\n"
                        f"  Chosen: {paths[0]}\n"
                        f"  Other candidates: {paths[1:]}"
                    )
                    self._update_metadata(plex_item, data)

            # Update sync timestamp after successful sync
            if self.data_dir is not None:
                save_sync_timestamp(self.data_dir, scene_id, time.time())

            # Remove from pending set (always, even on failure - will be re-added on retry)
            if unmark_scene_pending is not None:
                unmark_scene_pending(scene_id)

        except (PlexTemporaryError, PlexPermanentError, PlexNotFound):
            if unmark_scene_pending is not None:
                unmark_scene_pending(scene_id)  # Allow re-enqueue on next hook
            raise
        except Exception as e:
            if unmark_scene_pending is not None:
                unmark_scene_pending(scene_id)
            raise translate_plex_exception(e)

    def _update_metadata(self, plex_item, data: dict):
        """
        Update Plex item metadata from sync job data.

        Uses plex_item.edit() to update metadata fields, then reloads
        the item to confirm changes.

        Args:
            plex_item: Plex Video item to update
            data: Dict containing metadata fields (title, studio, details, etc.)
        """
        edits = {}

        # Map Stash fields to Plex fields
        # Stash 'details' -> Plex 'summary'
        summary = data.get('details') or data.get('summary')

        if self.config.preserve_plex_edits:
            # Only update fields that are None or empty string in Plex
            if data.get('title') and not plex_item.title:
                edits['title.value'] = data['title']
            if data.get('studio') and not plex_item.studio:
                edits['studio.value'] = data['studio']
            if summary and not plex_item.summary:
                edits['summary.value'] = summary
            if data.get('tagline') and not getattr(plex_item, 'tagline', None):
                edits['tagline.value'] = data['tagline']
            if data.get('date') and not getattr(plex_item, 'originallyAvailableAt', None):
                edits['originallyAvailableAt.value'] = data['date']
        else:
            # Stash always wins - overwrite all fields
            if data.get('title'):
                edits['title.value'] = data['title']
            if data.get('studio'):
                edits['studio.value'] = data['studio']
            if summary:
                edits['summary.value'] = summary
            if data.get('tagline'):
                edits['tagline.value'] = data['tagline']
            if data.get('date'):
                edits['originallyAvailableAt.value'] = data['date']

        if edits:
            print(f"[PlexSync Worker] Updating fields: {list(edits.keys())}")
            plex_item.edit(**edits)
            plex_item.reload()
            mode = "preserved" if self.config.preserve_plex_edits else "overwrite"
            print(f"[PlexSync Worker] Updated metadata ({mode} mode): {plex_item.title}")
        else:
            print(f"[PlexSync Worker] No metadata fields to update for: {plex_item.title}", file=sys.stderr)

        # Sync performers as actors
        performers = data.get('performers', [])
        if performers:
            try:
                # Get current actors
                current_actors = [actor.tag for actor in getattr(plex_item, 'actors', [])]
                new_performers = [p for p in performers if p not in current_actors]

                if new_performers:
                    # Build actor edit params - each actor needs actor[N].tag.tag format
                    actor_edits = {}
                    all_actors = current_actors + new_performers
                    for i, actor_name in enumerate(all_actors):
                        actor_edits[f'actor[{i}].tag.tag'] = actor_name

                    plex_item.edit(**actor_edits)
                    plex_item.reload()
                    print(f"[PlexSync Worker] Added {len(new_performers)} performers: {new_performers}")
                else:
                    print(f"[PlexSync Worker] Performers already in Plex: {performers}", file=sys.stderr)
            except Exception as e:
                log_warn(f" Failed to sync performers: {e}")

        # Sync poster image (download from Stash, save to temp file, upload to Plex)
        poster_url = data.get('poster_url')
        if poster_url:
            try:
                image_data = self._fetch_stash_image(poster_url)
                if image_data:
                    import tempfile
                    import os
                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                        f.write(image_data)
                        temp_path = f.name
                    try:
                        plex_item.uploadPoster(filepath=temp_path)
                        print(f"[PlexSync Worker] Uploaded poster ({len(image_data)} bytes)")
                    finally:
                        os.unlink(temp_path)
            except Exception as e:
                log_warn(f" Failed to upload poster: {e}")

        # Sync background/art image (download from Stash, save to temp file, upload to Plex)
        background_url = data.get('background_url')
        if background_url:
            try:
                image_data = self._fetch_stash_image(background_url)
                if image_data:
                    import tempfile
                    import os
                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                        f.write(image_data)
                        temp_path = f.name
                    try:
                        plex_item.uploadArt(filepath=temp_path)
                        print(f"[PlexSync Worker] Uploaded background ({len(image_data)} bytes)")
                    finally:
                        os.unlink(temp_path)
            except Exception as e:
                log_warn(f" Failed to upload background: {e}")

        # Sync tags as genres
        tags = data.get('tags', [])
        if tags:
            try:
                current_genres = [g.tag for g in getattr(plex_item, 'genres', [])]
                new_tags = [t for t in tags if t not in current_genres]

                if new_tags:
                    # Build genre edit params
                    genre_edits = {}
                    all_genres = current_genres + new_tags
                    for i, genre_name in enumerate(all_genres):
                        genre_edits[f'genre[{i}].tag.tag'] = genre_name

                    plex_item.edit(**genre_edits)
                    plex_item.reload()
                    print(f"[PlexSync Worker] Added {len(new_tags)} tags as genres: {new_tags}")
                else:
                    print(f"[PlexSync Worker] Tags already in Plex: {tags}", file=sys.stderr)
            except Exception as e:
                log_warn(f" Failed to sync tags: {e}")

        # Add to studio collection
        studio = data.get('studio')
        if studio:
            try:
                current_collections = [c.tag for c in getattr(plex_item, 'collections', [])]
                if studio not in current_collections:
                    # Build collection edit params
                    collection_edits = {}
                    all_collections = current_collections + [studio]
                    for i, coll_name in enumerate(all_collections):
                        collection_edits[f'collection[{i}].tag.tag'] = coll_name

                    plex_item.edit(**collection_edits)
                    plex_item.reload()
                    print(f"[PlexSync Worker] Added to collection: {studio}", file=sys.stderr)
                else:
                    print(f"[PlexSync Worker] Already in collection: {studio}", file=sys.stderr)
            except Exception as e:
                log_warn(f" Failed to add to collection: {e}")
