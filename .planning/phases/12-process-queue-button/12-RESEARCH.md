# Phase 12: Process Queue Button - Research

**Researched:** 2026-02-03
**Domain:** Stash plugin task execution, long-running operations, and batch queue processing
**Confidence:** HIGH

## Summary

This phase addresses a known limitation in Stash plugin architecture: plugin tasks run within the Stash task queue and have practical time constraints. When a user triggers a sync task with a large queue (hundreds of items), the current dynamic timeout (max 600 seconds/10 minutes) may be insufficient. The solution is a dedicated "Process Queue" task that processes until the queue is empty, not limited by the existing timeout.

The PlexSync codebase already contains most of the required infrastructure:
1. A standalone `process_queue.py` script exists for manual CLI processing
2. The worker/processor.py `SyncWorker` class handles job processing with retry logic
3. Queue management tasks (Phase 11) established the pattern for adding new tasks
4. The `log_progress()` function exists but is unused - it can report progress to Stash UI

The primary work is creating a new task mode (`process_queue`) that:
- Runs the existing worker loop directly (not as background daemon thread)
- Processes until queue is empty (no artificial timeout)
- Reports progress via `log_progress()` for Stash UI visibility
- Handles graceful interruption if Stash kills the process

**Primary recommendation:** Add a "Process Queue" task that runs the SyncWorker's job processing logic in the foreground (not as daemon thread), processing until the queue is empty, with periodic progress reporting via the existing `log_progress()` function.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| persist-queue | >=1.1.0 | SQLite-backed queue with ack/nack | Already in use, provides `queue.size` for progress tracking |
| worker/processor.py | N/A | SyncWorker class for job processing | Already implements retry, DLQ, circuit breaker logic |
| sync_queue/operations.py | N/A | get_stats(), get_pending(), ack_job() | Already provides queue operations |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| time | stdlib | Sleep between progress updates | Avoid tight loop on progress reporting |
| sys.stderr | stdlib | Stash plugin logging | Progress and status messages |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Foreground processing loop | Background thread with longer timeout | Thread dies when plugin exits; user can't see completion |
| Dedicated process_queue task | Modify existing "Sync Recent" to never timeout | Conflates two different use cases; "Sync Recent" should remain quick |
| In-plugin queue processing | External process_queue.py CLI | In-plugin keeps everything unified; external requires separate invocation |

**Installation:**
```bash
# No new dependencies - all infrastructure already exists
```

## Architecture Patterns

### Recommended Implementation Structure

The "Process Queue" task should reuse existing components:

```
Stash2Plex.py (entry point)
  |
  +-- handle_task() with mode='process_queue'
        |
        +-- handle_process_queue()
              |
              +-- Create SyncWorker (or reuse existing)
              +-- Run processing loop (NOT as daemon thread)
              +-- Report progress via log_progress()
              +-- Exit when queue is empty
```

### Pattern 1: Foreground Queue Processing with Progress

**What:** Process queue items in the main thread with progress updates to Stash UI
**When to use:** Long-running batch operations that need user visibility
**Example:**
```python
# Source: Derived from process_queue.py and Stash2Plex.py patterns
def handle_process_queue():
    """Process all pending queue items with progress reporting."""
    from sync_queue.operations import get_stats, get_pending, ack_job, nack_job, fail_job
    from sync_queue.manager import QueueManager
    from worker.processor import SyncWorker, TransientError, PermanentError

    data_dir = get_plugin_data_dir()
    queue_path = os.path.join(data_dir, 'queue')

    # Get initial stats
    stats = get_stats(queue_path)
    total = stats['pending'] + stats['in_progress']

    if total == 0:
        log_info("Queue is empty - nothing to process")
        return

    log_info(f"Processing {total} queued items...")

    # Initialize queue and worker
    queue_manager = QueueManager(data_dir)
    queue = queue_manager.get_queue()

    # Create worker for job processing (reuses all existing logic)
    dlq = DeadLetterQueue(data_dir)
    worker = SyncWorker(queue, dlq, config, data_dir=data_dir)

    processed = 0
    failed = 0
    start_time = time.time()

    while True:
        job = get_pending(queue, timeout=1)
        if job is None:
            # Queue empty - we're done
            break

        scene_id = job.get('scene_id', '?')
        try:
            worker._process_job(job)
            ack_job(queue, job)
            processed += 1
        except Exception as e:
            failed += 1
            fail_job(queue, job)
            log_warn(f"Scene {scene_id} failed: {e}")

        # Report progress every 5 items or every 10 seconds
        if processed % 5 == 0:
            remaining = queue.size
            progress = (processed / total) * 100 if total > 0 else 100
            log_progress(progress)
            log_info(f"Progress: {processed}/{total} processed, {remaining} remaining")

    elapsed = time.time() - start_time
    log_info(f"Queue processing complete: {processed} succeeded, {failed} failed in {elapsed:.1f}s")
```

### Pattern 2: Progress Reporting to Stash UI

**What:** Use the `\x01p\x02` prefix to send progress percentage to Stash task queue UI
**When to use:** Long-running tasks where user wants visual progress indicator
**Example:**
```python
# Source: Stash2Plex.py log_progress function
def log_progress(p): print(f"\x01p\x02{p}")

# Usage - p should be a float 0-100
log_progress(0)    # 0% complete
log_progress(50)   # 50% complete
log_progress(100)  # 100% complete
```

**Important notes:**
- Stash expects a numeric value (0-100)
- Updates should be throttled (every few items or every few seconds)
- Progress is shown in Stash's Task Queue UI
- Combine with log_info() for detailed status in logs

### Pattern 3: Batch Mode vs Normal Mode

**What:** Distinguish between normal hook/task mode (daemon worker) and batch processing mode (foreground)
**When to use:** Support both quick operations and bulk processing
**Example:**
```python
# Source: Conceptual pattern from existing handle_task structure
def handle_task(task_args: dict, stash=None):
    mode = task_args.get('mode', 'recent')

    # Queue management tasks (Phase 11)
    if mode == 'queue_status': ...
    if mode == 'clear_queue': ...

    # NEW: Batch processing mode (Phase 12)
    if mode == 'process_queue':
        handle_process_queue()
        return

    # Normal sync modes use daemon worker
    # ... existing sync logic
```

### Pattern 4: Resilient Batch Processing

**What:** Handle errors gracefully, continue processing remaining items
**When to use:** Processing large queues where some failures are expected
**Example:**
```python
# Source: process_queue.py error handling pattern
while True:
    job = get_pending(queue, timeout=1)
    if job is None:
        break

    try:
        worker._process_job(job)
        ack_job(queue, job)
    except TransientError as e:
        # Prepare for retry with backoff metadata
        job = worker._prepare_for_retry(job, e)
        max_retries = worker._get_max_retries_for_error(e)
        if job.get('retry_count', 0) >= max_retries:
            fail_job(queue, job)
            dlq.add(job, e, job.get('retry_count', 0))
        else:
            worker._requeue_with_metadata(job)
    except PermanentError as e:
        fail_job(queue, job)
        dlq.add(job, e, job.get('retry_count', 0))
    except Exception as e:
        # Unknown error - nack for retry
        nack_job(queue, job)
```

### Anti-Patterns to Avoid

- **Starting daemon thread and waiting:** Daemon threads die when plugin exits; process directly instead
- **No progress reporting:** Users won't know if task is working or stuck
- **Processing without error handling:** One bad item shouldn't stop the entire batch
- **Ignoring circuit breaker:** If Plex is down, don't retry every item - respect circuit breaker state
- **Tight progress update loop:** Reporting every item adds overhead; batch updates every 5-10 items

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Job processing logic | New processing loop | `SyncWorker._process_job()` | Already handles retries, DLQ, validation, metadata updates |
| Retry with backoff | Custom retry logic | `SyncWorker._prepare_for_retry()` | Already calculates delays, tracks retry count |
| Queue statistics | Manual SQL queries | `get_stats(queue_path)` | Already implemented with proper status mapping |
| Progress display | Custom UI | `log_progress(percentage)` | Already exists, formats for Stash UI |
| Error classification | if/else on error types | TransientError/PermanentError classes | Already defined with proper inheritance |

**Key insight:** The `process_queue.py` script already demonstrates the pattern. The task is to integrate this into the plugin as a task mode, not to build new processing infrastructure.

## Common Pitfalls

### Pitfall 1: Background Thread Dying on Plugin Exit
**What goes wrong:** Processing runs in daemon thread; when plugin exits after timeout, daemon dies and items remain unprocessed
**Why it happens:** Current architecture assumes quick operations; daemon threads are for continuous background work
**How to avoid:** For "Process Queue" task, run processing in foreground (main thread), not as daemon
**Warning signs:** Queue size unchanged after task "completes"; timeout message despite task finishing

### Pitfall 2: No Circuit Breaker Respect
**What goes wrong:** Processing continues even when Plex is down, failing every item
**Why it happens:** Foreground loop doesn't check circuit breaker state
**How to avoid:** Check `circuit_breaker.can_execute()` before each job; if OPEN, wait and retry or abort
**Warning signs:** All items failing with same error; rapid DLQ growth; Plex error messages

### Pitfall 3: Memory Growth in Long Batches
**What goes wrong:** Processing hundreds of items accumulates state, leading to memory issues
**Why it happens:** PlexClient or caches not properly managed for long sessions
**How to avoid:** Reuse existing worker instance which manages client lifecycle; consider periodic cache clearing for very large batches
**Warning signs:** Slowdown over time; memory errors; connection pool exhaustion

### Pitfall 4: Missing Progress Updates
**What goes wrong:** User doesn't know if task is working, assumes it's stuck, cancels
**Why it happens:** Progress updates forgotten or too infrequent
**How to avoid:** Call `log_progress()` every 5-10 items; also log_info() for text status
**Warning signs:** Users reporting task "hangs"; premature cancellations; support requests

### Pitfall 5: Not Handling Stash Task Cancellation
**What goes wrong:** User cancels task in Stash UI but processing continues until natural completion
**Why it happens:** No mechanism to check for cancellation signal
**How to avoid:** Accept that Stash may kill process; ensure each item is self-contained; rely on ack/nack for crash recovery
**Warning signs:** "Zombie" tasks in Stash UI; orphaned worker processes

### Pitfall 6: Duplicate Processing with Normal Worker
**What goes wrong:** "Process Queue" task runs while normal daemon worker also runs, causing race conditions
**Why it happens:** Both trying to get_pending() from same queue
**How to avoid:** "Process Queue" task mode should NOT start the normal daemon worker; check if already running before starting
**Warning signs:** Duplicate log messages; ack errors; items processed twice

## Code Examples

Verified patterns from existing codebase:

### Complete Process Queue Handler
```python
# Source: Derived from process_queue.py + Stash2Plex.py patterns
def handle_process_queue():
    """
    Process all pending queue items until empty.

    Unlike normal task modes that use a daemon worker with timeout,
    this runs in foreground and processes until the queue is empty.
    Useful for resuming after timeout or processing large backlogs.
    """
    global config

    try:
        data_dir = get_plugin_data_dir()
        queue_path = os.path.join(data_dir, 'queue')

        # Check initial queue state
        from sync_queue.operations import get_stats, get_pending, ack_job, fail_job
        stats = get_stats(queue_path)
        total = stats['pending'] + stats['in_progress']

        if total == 0:
            log_info("Queue is empty - nothing to process")
            return

        log_info(f"Starting batch processing of {total} items...")
        log_progress(0)

        # Initialize infrastructure
        from sync_queue.manager import QueueManager
        from sync_queue.dlq import DeadLetterQueue
        from worker.processor import SyncWorker, TransientError, PermanentError
        from plex.device_identity import configure_plex_device_identity

        # Configure device identity before Plex operations
        configure_plex_device_identity(data_dir)

        queue_manager = QueueManager(data_dir)
        queue = queue_manager.get_queue()
        dlq = DeadLetterQueue(data_dir)

        # Create worker instance (handles Plex client, caches, circuit breaker)
        worker = SyncWorker(queue, dlq, config, data_dir=data_dir)

        processed = 0
        failed = 0
        start_time = time.time()
        last_progress_time = start_time

        while True:
            # Check circuit breaker before processing
            if not worker.circuit_breaker.can_execute():
                log_warn("Circuit breaker OPEN - Plex may be unavailable")
                log_info(f"Processed {processed} items before circuit break")
                break

            # Get next job (1 second timeout to allow checking for empty queue)
            job = get_pending(queue, timeout=1)
            if job is None:
                break  # Queue is empty

            scene_id = job.get('scene_id', '?')
            retry_count = job.get('retry_count', 0)

            try:
                worker._process_job(job)
                ack_job(queue, job)
                worker.circuit_breaker.record_success()
                processed += 1

            except TransientError as e:
                worker.circuit_breaker.record_failure()
                job = worker._prepare_for_retry(job, e)
                max_retries = worker._get_max_retries_for_error(e)

                if job.get('retry_count', 0) >= max_retries:
                    log_warn(f"Scene {scene_id}: max retries exceeded, moving to DLQ")
                    fail_job(queue, job)
                    dlq.add(job, e, job.get('retry_count', 0))
                    failed += 1
                else:
                    # Re-queue for retry (will be picked up in next iteration)
                    worker._requeue_with_metadata(job)
                    log_debug(f"Scene {scene_id}: transient error, will retry")

            except PermanentError as e:
                log_warn(f"Scene {scene_id}: permanent error: {e}")
                fail_job(queue, job)
                dlq.add(job, e, retry_count)
                failed += 1

            except Exception as e:
                log_error(f"Scene {scene_id}: unexpected error: {e}")
                fail_job(queue, job)
                dlq.add(job, e, retry_count)
                failed += 1

            # Report progress every 5 items or every 10 seconds
            now = time.time()
            if processed % 5 == 0 or (now - last_progress_time) >= 10:
                progress = (processed / total) * 100 if total > 0 else 100
                remaining = queue.size
                log_progress(progress)
                elapsed = now - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                log_info(f"Progress: {processed}/{total} ({progress:.0f}%), "
                        f"{remaining} remaining, {rate:.1f} items/sec")
                last_progress_time = now

        # Final summary
        elapsed = time.time() - start_time
        log_progress(100)
        log_info(f"Batch processing complete: {processed} succeeded, {failed} failed in {elapsed:.1f}s")

        # Show any DLQ additions
        dlq_count = dlq.get_count()
        if dlq_count > 0:
            log_warn(f"DLQ contains {dlq_count} items requiring review")

    except Exception as e:
        log_error(f"Process queue error: {e}")
        import traceback
        traceback.print_exc()
```

### Task YAML Configuration
```yaml
# Source: Stash2Plex.yml task pattern
- name: Process Queue
  description: Process all pending queue items until empty (no timeout limit)
  defaultArgs:
    mode: process_queue
```

### Progress Reporting Pattern
```python
# Source: Stash2Plex.py log functions
def log_progress(p):
    """Report progress percentage to Stash UI (0-100)."""
    print(f"\x01p\x02{p}")

# Usage throughout processing loop:
total = 100
for i, item in enumerate(items):
    process(item)
    if i % 5 == 0:  # Every 5 items
        log_progress((i / total) * 100)
log_progress(100)  # Completion
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed 30s timeout | Dynamic timeout (2s/item, max 600s) | v1.1.4 | Better for variable queue sizes |
| No resume mechanism | "Sync Recent" resumes remaining items | v1.1 | Partial solution for timeouts |
| External CLI script | In-plugin task mode | Phase 12 | Unified user experience |
| No progress visibility | log_progress() to Stash UI | Phase 12 | Users see task progress |

**Deprecated/outdated:**
- `process_queue.py` CLI script: Will remain for debugging but primary use shifts to in-plugin task
- Waiting for daemon thread with arbitrary timeout: Replaced by dedicated foreground processing mode

## Open Questions

Things that couldn't be fully resolved:

1. **Stash Task Cancellation Signal**
   - What we know: Stash can cancel tasks from UI; process gets killed
   - What's unclear: Whether there's a graceful signal (SIGTERM) or just SIGKILL
   - Recommendation: Design for crash recovery (ack/nack pattern handles this); don't rely on cancellation signal

2. **Concurrent Process Queue Tasks**
   - What we know: User could accidentally trigger "Process Queue" twice
   - What's unclear: How Stash handles duplicate tasks; if queue locking is needed
   - Recommendation: Log warning if queue is being processed; SQLite locking handles concurrent access

3. **Very Large Queues (1000+ items)**
   - What we know: Each item takes ~2 seconds; 1000 items = ~30 minutes
   - What's unclear: Whether Stash has any ultimate task timeout; memory constraints
   - Recommendation: Monitor for issues in production; add periodic stats logging; consider adding max_items parameter if needed

4. **Progress Bar Accuracy**
   - What we know: log_progress(percentage) updates Stash UI
   - What's unclear: How frequently Stash polls/updates the display; visual smoothness
   - Recommendation: Update every 5 items or 10 seconds; test in actual Stash UI

## Sources

### Primary (HIGH confidence)
- [PlexSync codebase] - Stash2Plex.py, process_queue.py, worker/processor.py (existing implementation)
- [PlexSync codebase] - sync_queue/operations.py, dlq.py (queue infrastructure)
- [Phase 11 Research] - .planning/phases/11-queue-management-ui/11-RESEARCH.md (task patterns)

### Secondary (MEDIUM confidence)
- [Stash Plugin Docs](https://dogmadragon.github.io/Stash-Docs/docs/In-app-Manual/Plugins/) - Task configuration
- [Stash Issue #4207](https://github.com/stashapp/stash/issues/4207) - Task queue behavior and limitations
- [CommunityScripts Plugin Development](https://deepwiki.com/stashapp/CommunityScripts/6.2-plugin-development) - Python plugin best practices
- [Stash Wiki Scheduled Tasks](https://stash.wiki/en/script/scheduled-tasks) - Timeout configuration

### Tertiary (LOW confidence)
- [AI Tagger Plugin](https://deepwiki.com/stashapp/CommunityScripts/2.1-ai-tagger) - Batch processing patterns
- WebSearch results on Stash plugin development (2026) - Limited official documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All infrastructure already exists in codebase
- Architecture: HIGH - Pattern proven in process_queue.py, just needs integration
- Pitfalls: MEDIUM - Based on daemon thread behavior knowledge + queue processing experience

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (30 days) - Core patterns stable; Stash plugin system unchanged
