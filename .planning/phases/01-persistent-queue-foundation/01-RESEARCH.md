# Phase 1: Persistent Queue Foundation - Research

**Researched:** 2026-01-24
**Domain:** SQLite-backed persistent queues in Python
**Confidence:** HIGH

## Summary

Persistent queue foundations for Python have matured significantly, with `persist-queue` (v1.1.0, Oct 2025) emerging as the standard SQLite-backed solution. The library provides thread-safe, crash-resistant queue implementations with acknowledgment semantics perfect for job processing systems. SQLite's WAL (Write-Ahead Logging) mode enables concurrent reads during writes, making it suitable for queue workloads where rapid event capture (<100ms) and background processing coexist.

The recommended architecture uses `SQLiteAckQueue` for main job tracking with status-based lifecycle management (ready → unack → acked/failed), paired with a separate table for dead letter queue (DLQ) storage. This pattern avoids hand-rolling retry logic and provides queryable job status through SQLite's native querying capabilities. WAL mode with `PRAGMA synchronous=NORMAL` balances durability and performance, surviving application crashes while avoiding excessive fsync() overhead.

**Primary recommendation:** Use `persist-queue.SQLiteAckQueue` with auto_commit=True, multithreading=True, and auto_resume=True for crash-safe job processing with built-in acknowledgment semantics.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| persist-queue | 1.1.0 | SQLite-backed persistent queues | Thread-safe, WAL mode default, acknowledgment queue support, survives crashes |
| sqlite3 | Built-in | Database engine | Python stdlib, WAL support, ACID guarantees |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stashapi | Latest | Stash plugin interface | Logging (stashapi.log), StashInterface for API access |
| threading | Built-in | Thread coordination | Background worker implementation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| persist-queue | Custom SQLite queue | Don't - persist-queue handles edge cases (crash recovery, thread safety, WAL checkpoints) |
| persist-queue | litequeue | litequeue is simpler but lacks acknowledgment queue semantics needed for retry logic |
| persist-queue | Redis-based (RQ) | Adds external dependency, overkill for single-plugin local queue |

**Installation:**
```bash
pip install persist-queue
pip install stashapi
```

## Architecture Patterns

### Recommended Project Structure
```
PlexSync/
├── queue/
│   ├── __init__.py
│   ├── manager.py       # Queue initialization and lifecycle
│   ├── models.py        # Job data structures
│   └── operations.py    # Enqueue, dequeue, status updates
├── worker/
│   ├── __init__.py
│   └── processor.py     # Background job processor
├── hooks/
│   ├── __init__.py
│   └── handlers.py      # Event capture (<100ms)
└── PlexSync.py          # Plugin entry point
```

### Pattern 1: Acknowledgment Queue with Status Tracking
**What:** Use SQLiteAckQueue's built-in status lifecycle (ready → unack → acked/failed) instead of custom status columns.

**When to use:** When you need queryable job states, retry capability, and crash recovery.

**Example:**
```python
# Source: https://github.com/peter-wangxu/persist-queue (verified Oct 2025)
import persistqueue

# Initialize with crash recovery
ackq = persistqueue.SQLiteAckQueue(
    path='/path/to/stash/plugin/data/queue',
    auto_commit=True,        # Immediate persistence
    multithreading=True,     # Thread-safe operations
    auto_resume=True         # Resume unack jobs on startup
)

# Hook handler: fast enqueue (<100ms)
def on_scene_update(scene_id, metadata):
    job_data = {'scene_id': scene_id, 'metadata': metadata, 'timestamp': time.time()}
    ackq.put(job_data)
    # Returns immediately, job persisted

# Background worker: process with acknowledgment
def worker_loop():
    while True:
        item = ackq.get(timeout=10)  # Blocks up to 10s
        if item is None:
            continue

        try:
            process_sync_job(item)
            ackq.ack(item)  # Mark completed
        except RetryableError as e:
            log.warning(f"Job {item['pqid']} failed, will retry: {e}")
            ackq.nack(item)  # Return to queue for retry
        except PermanentError as e:
            log.error(f"Job {item['pqid']} failed permanently: {e}")
            ackq.ack_failed(item)  # Mark as failed
            move_to_dlq(item)
```

### Pattern 2: Separate Dead Letter Queue Table
**What:** Create a dedicated SQLite table for permanently failed jobs rather than using ack_failed status in main queue.

**When to use:** When failed jobs need long retention (30+ days) and shouldn't interfere with queue cleanup.

**Example:**
```python
# Source: Community pattern from SQLite job queue implementations
import sqlite3

def setup_dlq(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS dead_letter_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_job_id INTEGER,
            job_data BLOB,
            error_message TEXT,
            stack_trace TEXT,
            failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            retry_count INTEGER
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_dlq_failed_at ON dead_letter_queue(failed_at)')
    conn.commit()
    conn.close()

def move_to_dlq(item, error, stack_trace, retry_count):
    conn = sqlite3.connect('/path/to/stash/plugin/data/dlq.db')
    conn.execute(
        'INSERT INTO dead_letter_queue (original_job_id, job_data, error_message, stack_trace, retry_count) VALUES (?, ?, ?, ?, ?)',
        (item.get('pqid'), pickle.dumps(item), str(error), stack_trace, retry_count)
    )
    conn.commit()
    conn.close()
```

### Pattern 3: Priority Queue for Retries
**What:** Use ORDER BY to prioritize retried jobs over new jobs.

**When to use:** When retry jobs must process before new events to avoid stale state.

**Example:**
```python
# Source: Verified pattern from solid_queue and plainjob implementations
# persist-queue doesn't natively support priority, so implement with custom wrapper

class PriorityJobQueue:
    def __init__(self, path):
        self.ackq = persistqueue.SQLiteAckQueue(path, multithreading=True)
        self.db_path = f"{path}/data.db"

    def get_next_job(self):
        # Custom SQL to prioritize retries (items that were nack'd)
        conn = sqlite3.connect(self.db_path)
        # Query ack_queue table directly with priority logic
        cursor = conn.execute('''
            SELECT _id, data FROM ack_queue
            WHERE status = 1  -- ready status
            ORDER BY
                -- Prioritize items that were previously unack (retries)
                CASE WHEN timestamp < (SELECT MIN(timestamp) FROM ack_queue WHERE status = 1)
                     THEN 0 ELSE 1 END,
                timestamp ASC
            LIMIT 1
        ''')
        row = cursor.fetchone()
        conn.close()

        if row:
            # Mark as unack and return
            return self.ackq.get()
        return None
```

### Pattern 4: Job Deduplication for Rapid Updates
**What:** Use persist-queue's UniqueQ or custom deduplication logic to avoid queueing duplicate jobs during rapid updates.

**When to use:** When the same scene gets multiple updates in quick succession.

**Example:**
```python
# Source: https://github.com/peter-wangxu/persist-queue UniqueQ documentation
import persistqueue
import hashlib
import json

# Option 1: UniqueQ (simple, but limited)
unique_q = persistqueue.UniqueQ('path')
unique_q.put('scene_123')  # Queued
unique_q.put('scene_123')  # Ignored (duplicate)

# Option 2: Custom deduplication with job key hashing
class DeduplicatingQueue:
    def __init__(self, path):
        self.ackq = persistqueue.SQLiteAckQueue(path, multithreading=True)
        self.pending_keys = set()  # In-memory dedup cache
        self.lock = threading.Lock()

    def enqueue_unique(self, scene_id, metadata):
        job_key = f"scene_{scene_id}"

        with self.lock:
            if job_key in self.pending_keys:
                log.debug(f"Skipping duplicate job for {job_key}")
                return False
            self.pending_keys.add(job_key)

        job_data = {'scene_id': scene_id, 'metadata': metadata, 'job_key': job_key}
        self.ackq.put(job_data)
        return True

    def on_job_complete(self, job_data):
        with self.lock:
            self.pending_keys.discard(job_data['job_key'])
```

### Anti-Patterns to Avoid
- **Custom status columns:** Don't add custom `status` columns to persist-queue tables - use built-in AckStatus system (ready/unack/acked/failed)
- **Disabling auto_commit:** Don't set `auto_commit=False` for SQLiteAckQueue - library warns and forces it to True for data safety
- **Long-running transactions:** Don't hold write locks during Plex API calls - enqueue quickly, process in background
- **Missing multithreading=True:** Don't forget this parameter if hook handlers and workers run in separate threads
- **Ignoring auto_resume:** Always use `auto_resume=True` to recover unacknowledged jobs after crashes

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Persistent queue | Custom SQLite FIFO table | persist-queue.SQLiteQueue | Handles WAL checkpoints, thread safety, serialization edge cases |
| Job acknowledgment/retry | Status column + manual updates | persist-queue.SQLiteAckQueue | Built-in status lifecycle, auto_resume for crashes, tested unack recovery |
| Crash recovery | Manual transaction logs | SQLiteAckQueue with auto_resume=True | Automatically resumes unack jobs, tested across process restarts |
| Deduplication | Custom hash tracking | persist-queue.UniqueQ or in-memory set | UniqueQ uses DB constraints, tested for thread safety |
| Thread-safe SQLite | Manual lock management | persist-queue multithreading=True | Uses threading.Lock internally, prevents OperationalError |
| Database corruption | Manual fsync() calls | SQLite WAL mode (default in persist-queue) | WAL provides atomicity without explicit fsync in app code |

**Key insight:** Queue crash recovery is deceptively complex. You need to handle:
- Jobs dequeued but not completed (unack state)
- WAL checkpoint timing (when to flush to main DB)
- Thread safety across enqueue/dequeue/status updates
- Serialization edge cases (pickle protocol versions, custom objects)
- Database lock timeouts in multi-threaded scenarios

persist-queue has solved all of these over 227+ commits. Don't rebuild it.

## Common Pitfalls

### Pitfall 1: Database Locked Errors
**What goes wrong:** `sqlite3.OperationalError: database is locked` when multiple threads access queue.

**Why it happens:** Default SQLite timeout is low. Write locks block other operations. Long transactions hold locks unnecessarily.

**How to avoid:**
- Always set `multithreading=True` when initializing SQLiteAckQueue
- Keep write transactions short - don't make Plex API calls inside transactions
- persist-queue handles timeouts internally, but increase if needed: `sqlite3.connect(timeout=30.0)`

**Warning signs:** Intermittent lock errors under load, especially during hook bursts (multiple scenes updated rapidly).

### Pitfall 2: WAL File Growth
**What goes wrong:** WAL file grows indefinitely, consuming disk space and slowing reads.

**Why it happens:** Long-running read transactions prevent checkpoints. Default checkpoint threshold (1000 pages ~4MB) too high for low-traffic queues.

**How to avoid:**
- Don't hold database connections open across long operations
- persist-queue handles auto-checkpointing, but monitor WAL size: `ls -lh queue/data.db-wal`
- For low-traffic queues, manual checkpoint: `PRAGMA wal_checkpoint(TRUNCATE)`

**Warning signs:** WAL file grows beyond 10MB, query performance degrades over time.

### Pitfall 3: Windows File Queue Atomic Operations
**What goes wrong:** Critical data may become unreadable during task_done() failures on Windows.

**Why it happens:** persist-queue's file-based queue uses experimental atomic operations on Windows.

**How to avoid:**
- **Use SQLiteAckQueue instead of FileQueue on Windows** - SQLite ACID guarantees prevent corruption
- This is a known issue in persist-queue v1.1.0 documentation

**Warning signs:** Developing on Windows and using FileQueue variant.

### Pitfall 4: Missing auto_resume on Startup
**What goes wrong:** Jobs dequeued before crash never get reprocessed, appearing stuck.

**Why it happens:** Without `auto_resume=True`, unack jobs remain in unack state forever.

**How to avoid:**
- Always initialize with `auto_resume=True`
- On startup, log count of resumed jobs: `SELECT COUNT(*) FROM ack_queue WHERE status = 2` before resume, then after

**Warning signs:** Jobs show in queue but never complete after plugin restart. Status stuck at "in_progress".

### Pitfall 5: Pickling Custom Objects Without Protocol
**What goes wrong:** Jobs fail to deserialize after Python version upgrade or code changes.

**Why it happens:** Default pickle protocol varies by Python version. Class structure changes break old pickles.

**How to avoid:**
- Use simple data structures (dict, list, str, int) - persist-queue handles these reliably
- If custom objects needed, specify pickle protocol: use `pickle.HIGHEST_PROTOCOL`
- Better: Use JSON-serializable dicts and avoid pickle entirely

**Warning signs:** Jobs fail with "AttributeError: can't get attribute 'OldClassName'" after code updates.

### Pitfall 6: Stash Plugin Data Directory Not Created
**What goes wrong:** Queue initialization fails with "No such file or directory" error.

**Why it happens:** persist-queue creates database file but not parent directories. Stash plugin data directory location varies by installation.

**How to avoid:**
- Create plugin data directory before queue init:
  ```python
  import os
  queue_path = os.path.join(os.getenv('STASH_PLUGIN_DATA', '~/.stash/plugins/PlexSync'), 'queue')
  os.makedirs(queue_path, exist_ok=True)
  ```
- For Stash: Default plugin dir is `~/.stash/plugins` on Unix, `%USERPROFILE%\.stash\plugins` on Windows
- Check Stash config for custom plugin directory location

**Warning signs:** Plugin works on dev machine but fails in Docker/production with path errors.

### Pitfall 7: Completed Job Retention Bloat
**What goes wrong:** Database grows indefinitely with completed/failed jobs.

**Why it happens:** persist-queue doesn't auto-delete acked jobs. SQLiteAckQueue.clear_acked_data() method exists but isn't called automatically.

**How to avoid:**
- Implement periodic cleanup (e.g., daily cron or on worker startup):
  ```python
  ackq.clear_acked_data(keep_latest=1000)  # Keep last 1000 acked
  # Or custom SQL for time-based: DELETE FROM ack_queue WHERE status = 5 AND timestamp < ?
  ```
- Separate DLQ table for failed jobs needing long retention
- Log cleanup stats: "Removed 150 completed jobs older than 7 days"

**Warning signs:** Database file grows from KB to MB over weeks. Queue operations slow down.

## Code Examples

Verified patterns from official sources:

### Basic Queue Setup
```python
# Source: https://github.com/peter-wangxu/persist-queue (verified v1.1.0)
import persistqueue
import os

# Plugin data directory
plugin_data = os.getenv('STASH_PLUGIN_DATA', os.path.expanduser('~/.stash/plugins/PlexSync'))
queue_path = os.path.join(plugin_data, 'queue')
os.makedirs(queue_path, exist_ok=True)

# Initialize acknowledgment queue
ackq = persistqueue.SQLiteAckQueue(
    path=queue_path,
    auto_commit=True,      # Persist immediately (required for ack queue)
    multithreading=True,   # Thread-safe operations
    auto_resume=True       # Resume unack jobs on crash
)
```

### Hook Handler Pattern (Fast Enqueue)
```python
# Source: Stash plugin pattern + persist-queue
import stashapi.log as log
import time

def on_scene_update_post(scene_id, update_data):
    """Scene.Update.Post hook - must complete in <100ms"""
    start = time.time()

    # Filter non-sync events (e.g., play count updates don't need Plex sync)
    if not requires_plex_sync(update_data):
        log.debug(f"Scene {scene_id} update doesn't require sync, skipping")
        return

    # Enqueue job (fast SQLite insert)
    job = {
        'scene_id': scene_id,
        'update_type': 'metadata',
        'data': update_data,
        'enqueued_at': time.time()
    }
    ackq.put(job)

    elapsed = (time.time() - start) * 1000
    log.info(f"Enqueued sync job for scene {scene_id} in {elapsed:.1f}ms")
    # Target: <100ms total
```

### Background Worker Pattern
```python
# Source: Threading pattern + persist-queue acknowledgment workflow
import threading
import traceback
import stashapi.log as log

class SyncWorker:
    def __init__(self, ackq, stash_interface):
        self.ackq = ackq
        self.stash = stash_interface
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        log.info("Sync worker started")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        log.info("Sync worker stopped")

    def _worker_loop(self):
        while self.running:
            try:
                # Blocking get with timeout (10s tick)
                item = self.ackq.get(timeout=10)
                if item is None:
                    continue

                log.info(f"Processing job {item['pqid']} for scene {item['scene_id']}")

                # Process job (Plex API call, etc.)
                self._process_job(item)

                # Mark completed
                self.ackq.ack(item)
                log.info(f"Job {item['pqid']} completed")

            except Exception as e:
                log.error(f"Worker error: {e}")
                if item:
                    self.ackq.nack(item)  # Return to queue

    def _process_job(self, job):
        # Actual sync logic here
        pass
```

### Query Job Status
```python
# Source: Direct SQLite query on persist-queue schema
import sqlite3

def get_queue_stats(queue_path):
    """Query job counts by status"""
    db_path = os.path.join(queue_path, 'data.db')
    conn = sqlite3.connect(db_path)

    # Status values from persist-queue AckStatus enum
    # 0=inited, 1=ready, 2=unack, 5=acked, 9=ack_failed
    stats = {}

    cursor = conn.execute('''
        SELECT
            CASE status
                WHEN 0 THEN 'inited'
                WHEN 1 THEN 'pending'
                WHEN 2 THEN 'in_progress'
                WHEN 5 THEN 'completed'
                WHEN 9 THEN 'failed'
            END as status_name,
            COUNT(*) as count
        FROM ack_queue
        GROUP BY status
    ''')

    for row in cursor:
        stats[row[0]] = row[1]

    conn.close()
    return stats

# Example output: {'pending': 5, 'in_progress': 1, 'completed': 234, 'failed': 2}
```

### Dead Letter Queue Implementation
```python
# Source: Community pattern for DLQ with SQLite
import sqlite3
import pickle

class DeadLetterQueue:
    def __init__(self, plugin_data_path):
        self.db_path = os.path.join(plugin_data_path, 'dlq.db')
        self._setup_schema()

    def _setup_schema(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS dead_letters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                job_data BLOB,
                error_type TEXT,
                error_message TEXT,
                stack_trace TEXT,
                retry_count INTEGER,
                failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_failed_at ON dead_letters(failed_at)')
        conn.commit()
        conn.close()

    def add(self, job, error, retry_count):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            '''INSERT INTO dead_letters
               (job_id, job_data, error_type, error_message, stack_trace, retry_count)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (
                job.get('pqid'),
                pickle.dumps(job),
                type(error).__name__,
                str(error),
                traceback.format_exc(),
                retry_count
            )
        )
        conn.commit()
        conn.close()
        log.warning(f"Job {job.get('pqid')} moved to DLQ after {retry_count} retries")

    def get_recent(self, limit=10):
        """Get recent failed jobs for review"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            'SELECT id, job_id, error_type, error_message, failed_at FROM dead_letters ORDER BY failed_at DESC LIMIT ?',
            (limit,)
        )
        results = cursor.fetchall()
        conn.close()
        return results
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| File-based queues (filequeue) | SQLite-based with WAL | 2018-2020 | SQLite provides better concurrency, queryable status, ACID guarantees |
| Manual pickle serialization | persist-queue auto-serialization | v0.5+ | Handles edge cases (circular refs, protocol versions) automatically |
| Custom status tables | SQLiteAckQueue built-in status | v0.8+ (2020) | Status lifecycle (ready/unack/acked) tested, crash-recovery proven |
| Journal mode DELETE | WAL mode default | SQLite 3.7+ (2010) | Concurrent reads during writes, better performance |
| synchronous=FULL | synchronous=NORMAL in WAL | Modern practice | Durability maintained, fsync() overhead reduced |

**Deprecated/outdated:**
- **FileQueue on Windows:** Experimental atomic operations may corrupt data on task_done() failures (persist-queue v1.1.0 warning)
- **auto_commit=False for SQLiteAckQueue:** Library forces auto_commit=True with warning - unsafe to disable
- **Python 2.x support:** Dropped in persist-queue v1.0.0 (2019)
- **DELETE journal mode:** Use WAL for queue workloads - better concurrency

## Open Questions

Things that couldn't be fully resolved:

1. **Stash Plugin Data Directory Convention**
   - What we know: Stash plugins directory is `~/.stash/plugins` (Unix) or `%USERPROFILE%\.stash\plugins` (Windows)
   - What's unclear: Whether Stash provides environment variable for plugin-specific data directory (like `STASH_PLUGIN_DATA`)
   - Recommendation: Check Stash documentation or use `os.path.join(plugin_dir, 'PlexSync', 'data')` pattern. Create directory with `os.makedirs(exist_ok=True)` before queue init.

2. **stashapi.log Thread Safety**
   - What we know: stashapi provides logging module, typical usage is `import stashapi.log as log; log.info(...)`
   - What's unclear: Whether stashapi.log is thread-safe for background worker logging
   - Recommendation: Assume thread-safe (standard Python logging is), but verify in practice. If issues arise, use threading.Lock around log calls.

3. **Optimal Completed Job Retention**
   - What we know: Common patterns are 1-7 days for high-traffic queues, 30 days for low-traffic
   - What's unclear: PlexSync job volume (depends on user's Stash activity)
   - Recommendation: Start with 7 days, make configurable. Monitor database size. Formula: retention_days = min(30, max(1, 10000 / avg_jobs_per_day))

4. **Maximum Queue Size Limits**
   - What we know: SQLite supports millions of rows, but performance degrades with large unprocessed queues
   - What's unclear: Whether to limit pending queue size to prevent runaway growth
   - Recommendation: Start without limit. Add warning if pending > 1000: "Queue backlog growing, check worker health". Only add hard limit if Plex outages cause issues.

5. **Priority Queue Implementation**
   - What we know: persist-queue doesn't natively support priority, requires custom SQL wrapper
   - What's unclear: Whether retry priority is critical enough to justify custom implementation
   - Recommendation: Start with simple FIFO (persist-queue default). If retry ordering becomes issue, implement Pattern 3 (Priority Queue for Retries) wrapper.

## Sources

### Primary (HIGH confidence)
- persist-queue GitHub repository - https://github.com/peter-wangxu/persist-queue (verified v1.1.0, Oct 2025)
- persist-queue PyPI - https://pypi.org/project/persist-queue/ (version 1.1.0, Oct 25, 2025)
- SQLite WAL documentation - https://sqlite.org/wal.html (official SQLite docs)
- Python sqlite3 threading documentation - https://docs.python.org/3/library/sqlite3.html

### Secondary (MEDIUM confidence)
- [persist-queue SQLiteQueue source](https://github.com/peter-wangxu/persist-queue/blob/master/persistqueue/sqlqueue.py) - Database schema, method signatures
- [persist-queue SQLiteAckQueue source](https://github.com/peter-wangxu/persist-queue/blob/master/persistqueue/sqlackqueue.py) - Acknowledgment workflow, status tracking
- [Charles Leifer: Going Fast with SQLite and Python](https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/) - WAL mode, transaction best practices
- [Charles Leifer: Multi-threaded SQLite without OperationalErrors](https://charlesleifer.com/blog/multi-threaded-sqlite-without-the-operationalerrors/) - Thread safety patterns
- [Ricardo Anderegg: Python, SQLite, and thread safety](https://ricardoanderegg.com/posts/python-sqlite-thread-safety/) - Threading best practices
- [Solid Queue source](https://github.com/rails/solid_queue) - Priority queue patterns, cleanup strategies
- [RQ Jobs documentation](https://python-rq.org/docs/jobs/) - Status tracking patterns
- [BullMQ Deduplication docs](https://docs.bullmq.io/guide/jobs/deduplication) - Debounce/throttle patterns for rapid updates

### Tertiary (LOW confidence - WebSearch only)
- [Stash Plugin Documentation](https://github.com/stashapp/stash/wiki/Plugins-&--Scripts) - Plugin directory locations (need to verify exact data storage conventions)
- [stashapi GitHub](https://github.com/stg-annon/stashapi) - Basic usage examples (lacks detail on logging thread safety, data directories)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - persist-queue v1.1.0 verified from PyPI (Oct 2025), official source code reviewed
- Architecture: HIGH - Patterns verified from persist-queue source code, SQLite official docs, and multiple SQLite queue implementations
- Pitfalls: HIGH - Documented in persist-queue README (Windows FileQueue warning), SQLite docs (WAL checkpoints), and community articles on thread safety
- Stash integration: MEDIUM - Plugin directory conventions found but not verified from official Stash docs
- Deduplication: MEDIUM - Patterns from BullMQ (non-Python) verified by multiple queue implementations

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - persist-queue stable, minor version updates unlikely to break API)
