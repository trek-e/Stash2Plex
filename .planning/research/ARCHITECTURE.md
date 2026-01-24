# Architecture Patterns: Reliable Stash-to-Plex Sync Plugin

**Domain:** Stash plugin with Plex integration
**Researched:** 2026-01-24
**Confidence:** MEDIUM-HIGH (verified patterns, Stash-specific implementation needs validation)

## Recommended Architecture

The PlexSync plugin should adopt a **Layered Hook-Queue-Worker architecture** that separates event capture from retry logic and API execution. This pattern maintains compatibility with Stash's hook-based plugin system while adding reliability.

```
┌─────────────────────────────────────────────────────────┐
│                    Stash Core                           │
│         (Scene.Update.Post, Scene.Create.Post)          │
└────────────────────┬────────────────────────────────────┘
                     │ Hook trigger
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Hook Handler (Event Capture)               │
│  - Validate hook context                                │
│  - Extract scene metadata via GraphQL                   │
│  - Enqueue sync job                                     │
│  - Return immediately (non-blocking)                    │
└────────────────────┬────────────────────────────────────┘
                     │ Writes to
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Persistent Queue (SQLite)                  │
│  - sync_queue table (job_id, scene_id, metadata, etc)  │
│  - dlq_queue table (failed jobs for manual review)     │
│  - WAL mode for concurrent access                      │
└────────────────────┬────────────────────────────────────┘
                     │ Worker reads from
                     ▼
┌─────────────────────────────────────────────────────────┐
│           Queue Processor (Background Worker)           │
│  - Poll queue for pending jobs                          │
│  - Orchestrate retry logic                              │
│  - Update job status                                    │
│  - Move to DLQ after max retries                        │
└────────────────────┬────────────────────────────────────┘
                     │ Delegates to
                     ▼
┌─────────────────────────────────────────────────────────┐
│               Plex API Client (with Retry)              │
│  - Exponential backoff with jitter                      │
│  - HTTP status code handling (503, 429, etc)            │
│  - Matching logic (find scene in Plex)                  │
│  - Metadata update via Plex API                         │
└─────────────────────────────────────────────────────────┘
```

### Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| **Separate hook handler from worker** | Stash hooks must return quickly; async work happens in background |
| **SQLite-based queue** | No external dependencies, survives crashes, supports concurrent access |
| **Exponential backoff with jitter** | Industry standard for retry (prevents thundering herd) |
| **Dead Letter Queue** | Failed jobs preserved for manual review instead of infinite retries |

## Component Boundaries

| Component | Responsibility | Communicates With | State |
|-----------|---------------|-------------------|-------|
| **Hook Handler** | Capture Stash events, enqueue jobs | Stash (GraphQL), Persistent Queue | Stateless |
| **Persistent Queue** | Store pending/failed jobs, manage job lifecycle | Hook Handler (writes), Queue Processor (reads/updates) | Persistent (SQLite) |
| **Queue Processor** | Poll queue, orchestrate retries, manage job status | Persistent Queue, Plex API Client | Stateless (all state in queue) |
| **Plex API Client** | Match scenes, update Plex metadata, handle Plex-specific errors | Queue Processor (caller), Plex server (HTTP) | Stateless |
| **Config Manager** | Load plugin settings (Plex URL, auth, retry policy) | All components (read-only) | Persistent (config file or Stash plugin settings) |

### Component Details

#### 1. Hook Handler (Event Capture)

**Purpose:** Non-blocking event capture that responds to Stash hooks.

**Interface:**
```python
def on_scene_update_post(hook_context: dict) -> None:
    """
    Called by Stash when Scene.Update.Post fires.
    - Validates hook context
    - Queries scene metadata via Stash GraphQL
    - Enqueues sync job
    - Returns immediately (Stash expects quick response)
    """
```

**Responsibilities:**
- Parse `hookContext` from Stash (contains scene ID, trigger type)
- Query Stash GraphQL for scene metadata (title, performers, tags, file path)
- Input sanitization (validate/clean metadata before queueing)
- Enqueue job to Persistent Queue
- Log event capture (for debugging)

**Does NOT:**
- Call Plex API directly (delegated to worker)
- Retry logic (delegated to Queue Processor)
- Block on I/O (must return quickly to Stash)

#### 2. Persistent Queue (Storage Layer)

**Purpose:** Durable storage for sync jobs, survives plugin crashes and Stash restarts.

**Technology:** SQLite with WAL mode (allows concurrent reads during writes)

**Schema:**
```sql
-- Main queue
CREATE TABLE sync_queue (
    job_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL,
    scene_metadata TEXT NOT NULL,  -- JSON blob
    status TEXT NOT NULL,  -- 'pending', 'in_progress', 'completed', 'failed'
    retry_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Dead Letter Queue (failed jobs)
CREATE TABLE dlq_queue (
    job_id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL,
    scene_metadata TEXT NOT NULL,
    failure_reason TEXT,
    retry_count INTEGER,
    moved_to_dlq_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_status_retry ON sync_queue(status, next_retry_at);
```

**Operations:**
- `enqueue(job)` - Add new job (from Hook Handler)
- `get_pending_jobs()` - Retrieve jobs ready for processing
- `update_job_status(job_id, status, retry_count)` - Update after attempt
- `move_to_dlq(job_id, reason)` - Move failed job to DLQ

**Why SQLite:**
- No external dependencies (Python stdlib `sqlite3`)
- Survives crashes (durability)
- WAL mode allows concurrent access (worker reads while hook writes)
- Lightweight (single file, no server process)

#### 3. Queue Processor (Background Worker)

**Purpose:** Poll queue, orchestrate retries, manage job lifecycle.

**Execution Model:**
- **Option A (Recommended):** Scheduled task via Stash Task Scheduler (like FileMonitor plugin)
- **Option B:** Long-running background thread (if Stash supports)

**Processing Loop:**
```python
while True:
    jobs = queue.get_pending_jobs(limit=10)
    for job in jobs:
        if job.retry_count >= MAX_RETRIES:
            queue.move_to_dlq(job.id, "Max retries exceeded")
            continue

        try:
            plex_client.sync_scene(job.scene_metadata)
            queue.update_job_status(job.id, 'completed')
        except PlexTemporaryError as e:  # 503, network issues
            backoff_delay = calculate_backoff(job.retry_count)
            queue.update_job_status(
                job.id,
                'pending',
                retry_count=job.retry_count + 1,
                next_retry_at=now() + backoff_delay
            )
        except PlexPermanentError as e:  # 404, auth errors
            queue.move_to_dlq(job.id, str(e))

    sleep(POLL_INTERVAL)
```

**Retry Policy:**
- Exponential backoff: `base_delay * (2 ^ retry_count)` with jitter
- Example: 5s → 10s → 20s → 40s → 80s
- Max retries: 5 attempts before moving to DLQ
- Jitter: ±25% randomness to prevent synchronized retries

**Why This Design:**
- Separation of concerns: retry logic isolated from event capture and API calls
- Idempotent: can be restarted without duplicating work
- Observable: all state in database (can inspect queue externally)

#### 4. Plex API Client (Integration Layer)

**Purpose:** Handle Plex-specific logic (matching, metadata updates, error handling).

**Interface:**
```python
class PlexClient:
    def sync_scene(self, scene_metadata: dict) -> None:
        """
        1. Find matching Plex item (by file path or metadata)
        2. Update Plex metadata (title, tags, etc)
        3. Trigger Plex refresh for updated item

        Raises:
        - PlexTemporaryError (503, timeouts) - should retry
        - PlexPermanentError (404, auth) - should NOT retry
        """
```

**Retry Logic (at this layer):**
- Use `tenacity` library for immediate retries (sub-second transient failures)
- Decorator: `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.1))`
- Quick retries (100ms, 200ms, 400ms) for network blips
- **Different from Queue Processor retries:** This handles transient errors (connection reset), Queue Processor handles service unavailability (Plex down for minutes)

**Error Handling:**
```python
# Temporary errors (should retry at Queue Processor level)
- 503 Service Unavailable (Plex maintenance)
- 429 Too Many Requests (rate limiting)
- Network timeouts
- Connection refused

# Permanent errors (move to DLQ immediately)
- 401 Unauthorized (bad auth token)
- 404 Not Found (item doesn't exist in Plex)
- 400 Bad Request (malformed payload)
```

**Matching Logic:**
- **Primary:** Match by file path (Stash scene file path → Plex library item)
- **Secondary:** Fuzzy match by filename + metadata (title, year)
- **Fallback:** Manual match via configuration (scene_id → plex_item_id mapping)

#### 5. Config Manager

**Purpose:** Centralized configuration access.

**Configuration Sources (priority order):**
1. Plugin YAML settings (Stash native plugin config)
2. External config file (`plexsync_config.json` in plugin directory)
3. Environment variables (for Docker deployments)

**Configuration Schema:**
```json
{
  "plex_url": "http://localhost:32400",
  "plex_token": "XXXX",
  "queue_poll_interval": 30,
  "retry_policy": {
    "max_retries": 5,
    "base_delay": 5,
    "max_delay": 300
  },
  "matching": {
    "strategy": "filepath",  // or "fuzzy", "manual"
    "fuzzy_threshold": 0.8
  }
}
```

## Data Flow

### Happy Path: Scene Update → Plex Sync

```
1. User updates scene in Stash
   ↓
2. Stash fires Scene.Update.Post hook
   ↓
3. Hook Handler receives hook context
   - Queries Stash GraphQL for scene metadata
   - Validates/sanitizes metadata
   - Enqueues job to SQLite queue (status='pending')
   - Returns to Stash (hook completes)
   ↓
4. Queue Processor polls queue (runs every 30s)
   - Finds pending job with retry_count=0
   - Passes job to Plex API Client
   ↓
5. Plex API Client processes job
   - Matches scene in Plex by file path
   - Updates Plex metadata via HTTP API
   - Triggers Plex refresh
   - Returns success
   ↓
6. Queue Processor updates job status to 'completed'
```

### Failure Path: Plex Unavailable (503)

```
1. Scene update → Hook Handler → Job enqueued (same as above)
   ↓
2. Queue Processor polls, finds pending job
   ↓
3. Plex API Client attempts sync
   - HTTP request to Plex returns 503 Service Unavailable
   - Raises PlexTemporaryError
   ↓
4. Queue Processor catches PlexTemporaryError
   - Calculates backoff: retry_count=0 → delay=5s
   - Updates job: status='pending', retry_count=1, next_retry_at=(now+5s)
   ↓
5. Queue Processor continues polling (skips this job until next_retry_at)
   ↓
6. After 5 seconds, job becomes eligible again
   - retry_count=1 → delay=10s (if fails again)
   - retry_count=2 → delay=20s
   - ...
   - retry_count=5 → moved to DLQ
```

### Late Update Path: Stash Metadata Arrives After Initial Sync

```
1. Scene added to Stash (file scan)
   - Metadata not yet populated (performers, tags unknown)
   - Hook fires with partial metadata
   - Job enqueued with partial data
   ↓
2. Queue Processor syncs partial metadata to Plex
   ↓
3. User adds metadata in Stash (tags, performers, etc)
   - Scene.Update.Post fires again
   - Hook Handler enqueues NEW job with full metadata
   ↓
4. Queue Processor syncs full metadata to Plex
   - Overwrites partial metadata (Plex refresh)
```

**Note:** This "re-sync on every update" approach handles late updates naturally. No special logic needed.

## Patterns to Follow

### Pattern 1: Exponential Backoff with Jitter

**What:** Increase wait time exponentially after each failure, with random jitter.

**Why:** Prevents "thundering herd" when multiple jobs retry simultaneously after Plex comes back online.

**When:** All retry scenarios (Plex unavailable, rate limiting, network issues).

**Implementation:**
```python
import random

def calculate_backoff(retry_count: int, base_delay: int = 5, max_delay: int = 300) -> int:
    """
    Exponential backoff: base_delay * (2 ^ retry_count)
    Capped at max_delay, with ±25% jitter
    """
    delay = min(base_delay * (2 ** retry_count), max_delay)
    jitter = random.uniform(-0.25, 0.25) * delay
    return delay + jitter

# Example: retry_count=0 → ~5s, retry_count=2 → ~20s, retry_count=5 → 160-240s
```

**Reference:** [Webhook Retry Best Practices - Svix](https://www.svix.com/resources/webhook-best-practices/retries/)

### Pattern 2: Dead Letter Queue (DLQ)

**What:** After max retries, move failed jobs to separate table instead of discarding.

**Why:**
- Audit trail (know what failed)
- Manual intervention (user can inspect, fix config, retry)
- No infinite retry loops

**When:** Job exceeds `MAX_RETRIES` or encounters permanent error (401, 404).

**Implementation:**
```python
def move_to_dlq(job_id: str, reason: str):
    job = queue.get_job(job_id)
    dlq_queue.insert({
        'job_id': job.id,
        'scene_id': job.scene_id,
        'scene_metadata': job.metadata,
        'failure_reason': reason,
        'retry_count': job.retry_count
    })
    queue.delete_job(job_id)
```

**Reference:** [Webhook Retry Patterns - Carrier Integration](https://www.carrierintegrationsoftware.com/webhook-retry-patterns-for-carrier-integration-building-resilient-event-processing-at-scale/)

### Pattern 3: Separate Event Capture from Processing

**What:** Hook handler enqueues job and returns immediately; background worker processes queue.

**Why:**
- Stash hooks expect quick response (don't block on Plex API call)
- Allows retry logic without re-triggering hooks
- Enables backpressure (queue can grow if Plex is slow)

**When:** Always (fundamental to this architecture).

**Implementation:**
```python
# Hook handler (fast path)
def on_scene_update_post(hook_context):
    scene_id = hook_context['id']
    metadata = fetch_scene_metadata(scene_id)  # GraphQL query to Stash
    queue.enqueue({
        'scene_id': scene_id,
        'metadata': metadata
    })
    # Return immediately (hook completes in <100ms)

# Worker (slow path, runs in background)
def process_queue():
    while True:
        jobs = queue.get_pending()
        for job in jobs:
            plex_client.sync(job.metadata)  # Can take seconds, may fail
        sleep(30)
```

**Reference:** [How to Implement Webhook Retry Logic - Latenode](https://latenode.com/blog/integration-api-management/webhook-setup-configuration/how-to-implement-webhook-retry-logic)

### Pattern 4: Idempotent Operations

**What:** Syncing the same scene multiple times produces same result.

**Why:**
- Safe to retry (no duplicate data)
- Handles late updates (re-sync with new metadata)
- Simplifies error recovery (just retry, don't track "already synced")

**When:** All Plex API operations.

**Implementation:**
```python
# Plex metadata update is naturally idempotent
# Setting tags to ['tag1', 'tag2'] multiple times = same result
# No need to check "did we already sync this scene?"
```

**Reference:** [Lambda Retry And Idempotency - Dashbird](https://dashbird.io/knowledge-base/aws-lambda/retries-and-idempotency/)

### Pattern 5: Persistent Queue with WAL Mode

**What:** Use SQLite with Write-Ahead Logging for concurrent access.

**Why:**
- Hook handler can write (enqueue) while worker reads (process)
- Durability (survives crashes)
- No external dependencies (Python stdlib)

**When:** Persistence layer for job queue.

**Implementation:**
```python
import sqlite3

conn = sqlite3.connect('plexsync.db')
conn.execute('PRAGMA journal_mode=WAL')  # Enable WAL mode
conn.execute('PRAGMA synchronous=NORMAL')  # Balance durability/performance
```

**Reference:** [persist-queue - PyPI](https://pypi.org/project/persist-queue/)

## Anti-Patterns to Avoid

### Anti-Pattern 1: Synchronous API Call in Hook Handler

**What:** Calling Plex API directly from hook handler (current PlexSync behavior).

**Why bad:**
- Blocks Stash hook (slow response)
- No retry on failure (sync lost if Plex is down)
- No visibility into failures (silent failure)

**Consequences:**
- Poor user experience (Stash UI hangs during scene updates)
- Data loss (metadata changes not synced when Plex unavailable)

**Instead:** Use queue-based architecture (Pattern 3).

**Detection:** If hook handler takes >1 second, you're doing it wrong.

### Anti-Pattern 2: Infinite Retries Without DLQ

**What:** Retry forever on failure without moving to DLQ.

**Why bad:**
- Permanent errors (404, 401) retry forever (wasted resources)
- No visibility into stuck jobs
- Queue fills with un-processable jobs

**Instead:** Use max retry limit + DLQ (Pattern 2).

**Detection:** Jobs with retry_count > 10 that never complete.

### Anti-Pattern 3: Fixed Delay Retry (No Backoff)

**What:** Wait same amount (e.g., 30s) between each retry.

**Why bad:**
- Thundering herd when Plex recovers (all jobs retry simultaneously)
- Slower recovery (early retries too slow, late retries too fast)

**Instead:** Use exponential backoff with jitter (Pattern 1).

**Detection:** All retry attempts happen at same interval.

### Anti-Pattern 4: No Input Sanitization

**What:** Pass Stash metadata directly to Plex API without validation.

**Why bad:**
- Security risk (Stash metadata could contain malicious input)
- Plex API errors (invalid characters, too-long strings)
- Silent failures (Plex rejects bad data, no error logged)

**Instead:** Validate/sanitize metadata in Hook Handler before queueing.

**Prevention:**
```python
def sanitize_metadata(metadata):
    return {
        'title': clean_string(metadata.get('title', 'Unknown')),
        'tags': [clean_tag(t) for t in metadata.get('tags', [])[:50]],  # Limit tags
        'performers': [clean_string(p) for p in metadata.get('performers', [])]
    }
```

### Anti-Pattern 5: Storing State in Memory

**What:** Using in-memory queue (Python `queue.Queue`) instead of persistent queue.

**Why bad:**
- State lost on plugin restart or Stash crash
- No durability (pending jobs disappear)

**Instead:** Use persistent queue (SQLite) (Pattern 5).

**Detection:** Jobs disappear after plugin restart.

## Build Order and Dependencies

Suggested implementation order to minimize risk and enable incremental testing:

### Phase 1: Persistent Queue Foundation
**Build:**
- SQLite schema (sync_queue, dlq_queue tables)
- Queue operations (enqueue, get_pending, update_status, move_to_dlq)
- Config manager (load settings from file/YAML)

**Test:**
- Unit tests for queue operations
- Persistence across process restarts
- Concurrent access (simulate hook writes during worker reads)

**Why First:** Foundation for everything else; testable in isolation.

### Phase 2: Hook Handler (Event Capture)
**Build:**
- Parse Stash hook context
- Query Stash GraphQL for scene metadata
- Input sanitization (validate/clean metadata)
- Enqueue job to persistent queue
- Return quickly to Stash

**Test:**
- Mock Stash GraphQL responses
- Verify jobs enqueued correctly
- Measure response time (<100ms)

**Depends On:** Phase 1 (queue)

**Why Second:** Enables end-to-end flow (event → queue), still testable without Plex.

### Phase 3: Plex API Client (Integration Layer)
**Build:**
- Plex authentication (use token from config)
- Scene matching logic (file path → Plex item)
- Metadata update via Plex API
- Error handling (temporary vs permanent errors)
- Immediate retry with tenacity (sub-second retries)

**Test:**
- Mock Plex API responses (200, 503, 404)
- Verify error classification (temporary vs permanent)
- Integration test against real Plex instance

**Depends On:** None (testable independently)

**Why Third:** Can test against real/mock Plex before wiring up retry logic.

### Phase 4: Queue Processor (Retry Orchestration)
**Build:**
- Polling loop (get pending jobs)
- Exponential backoff calculation
- Retry orchestration (call Plex client, update job status)
- DLQ movement (after max retries)

**Test:**
- Simulate failures (mock Plex client returning errors)
- Verify retry logic (backoff timing, max retries)
- Verify DLQ movement

**Depends On:** Phase 1 (queue), Phase 3 (Plex client)

**Why Fourth:** Integration point; needs both queue and Plex client working.

### Phase 5: Integration and Deployment
**Build:**
- Wire up components (hook handler → queue → processor → Plex client)
- Stash plugin YAML configuration
- Background worker scheduling (via Stash Task Scheduler or thread)
- Logging and observability

**Test:**
- End-to-end test (trigger hook in Stash → verify Plex update)
- Failure scenarios (Plex down, network issues)
- Performance test (handle 100+ queued jobs)

**Depends On:** All previous phases

**Why Last:** Full integration; validates entire system.

### Dependency Graph

```
Phase 1: Persistent Queue ─┬─→ Phase 2: Hook Handler ─┐
                           │                           ├─→ Phase 4: Queue Processor ─→ Phase 5: Integration
Phase 3: Plex API Client ──┴───────────────────────────┘
```

**Critical Path:** Phase 1 → Phase 2 → Phase 4 → Phase 5 (can build Phase 3 in parallel)

## Stash Plugin Constraints

Based on research into Stash plugin architecture:

### Plugin Execution Model
- **Hooks:** Stash calls plugin when events fire (Scene.Update.Post, etc)
- **Task Scheduler:** Plugins can register scheduled tasks (like FileMonitor plugin)
- **GraphQL Access:** Plugins interact with Stash via GraphQL API (queries and mutations)
- **File System Access:** Plugins can read/write files in plugin directory

### Persistence Options
**Available:**
- File-based storage (JSON, SQLite) in plugin directory
- Stash database (via GraphQL mutations - tags, custom fields)

**Not Available:**
- External database (PostgreSQL, Redis)
- External message queue (RabbitMQ, Kafka)

**Recommendation:** Use SQLite in plugin directory (balances durability and simplicity).

### Background Processing Options
**Option A (Recommended):** Scheduled task via Stash Task Scheduler
- How FileMonitor plugin works (runs as background service)
- Appears in task queue briefly, then runs in background
- Can be started/stopped via Stash UI

**Option B:** Background thread in Python
- Starts when plugin loads
- Runs continuously (polling loop)
- Complexity: must handle plugin reload/unload gracefully

**Recommendation:** Start with Option A (task scheduler) for consistency with existing plugins.

### Hook Response Time
- Hooks should return quickly (Stash expects <1 second response)
- No blocking I/O in hook handlers
- Use queue to defer slow work (Plex API calls)

## Scalability Considerations

This is a single-user plugin, but worth considering:

| Concern | Current Scale | At 1K Scenes | At 10K Scenes |
|---------|--------------|--------------|---------------|
| **Queue Size** | <10 jobs | <100 jobs (if batch update) | <1000 jobs (unlikely all update at once) |
| **Queue Processor** | Poll every 30s | Poll every 10s (faster processing) | Add batch processing (process 10 jobs per poll) |
| **SQLite Performance** | WAL mode sufficient | Add indexes on status/retry_at | May need cleanup job (delete old completed jobs) |
| **Plex API Rate Limiting** | Unlikely to hit | May need to slow down (429 handling) | Add rate limiter (max 10 req/sec) |

**Recommendation:** Current architecture scales to 10K+ scenes without modification. If rate limiting becomes issue, add sleep between Plex API calls.

## Implementation Notes

### Recommended Libraries
- **Queue:** `persist-queue` (or DIY with sqlite3 + WAL mode)
- **Retry:** `tenacity` (for immediate retries in Plex client)
- **HTTP:** `requests` (already in PlexSync dependencies)
- **Config:** `json` (stdlib) or `pyyaml` (if using Stash plugin YAML)

### Migration from Current PlexSync
Current PlexSync is synchronous (hook → Plex API). Migration path:

1. **Phase 1-2:** Add queue + hook handler (enqueue jobs), keep old sync code as fallback
2. **Phase 3-4:** Add Plex client + queue processor, test alongside old code
3. **Phase 5:** Remove old synchronous code, full queue-based architecture

This allows gradual rollout and easy rollback if issues arise.

## Sources

### Stash Plugin Architecture
- [Plugin Development - DeepWiki](https://deepwiki.com/stashapp/CommunityScripts/6.2-plugin-development)
- [CommunityScripts - GitHub](https://github.com/stashapp/CommunityScripts)
- [FileMonitor Plugin](https://github.com/stashapp/CommunityScripts/blob/main/plugins/FileMonitor/README.md)

### Retry Patterns and Webhook Best Practices
- [Webhook Retry Best Practices - Svix](https://www.svix.com/resources/webhook-best-practices/retries/)
- [How to Implement Webhook Retry Logic - Latenode](https://latenode.com/blog/integration-api-management/webhook-setup-configuration/how-to-implement-webhook-retry-logic)
- [Webhook Retry Patterns for Carrier Integration](https://www.carrierintegrationsoftware.com/webhook-retry-patterns-for-carrier-integration-building-resilient-event-processing-at-scale/)
- [Mastering Webhook Retry Logic - Sparkco](https://sparkco.ai/blog/mastering-webhook-retry-logic-strategies-and-best-practices)

### Python Retry Libraries
- [tenacity - GitHub](https://github.com/jd/tenacity)
- [backoff - GitHub](https://github.com/litl/backoff)
- [Tenacity Retries: Exponential Backoff Decorators 2026](https://johal.in/tenacity-retries-exponential-backoff-decorators-2026/)
- [Building Resilient Python Applications with Tenacity](https://www.amitavroy.com/articles/building-resilient-python-applications-with-tenacity-smart-retries-for-a-fail-proof-architecture)

### Python Persistence and Queue Libraries
- [persist-queue - GitHub](https://github.com/peter-wangxu/persist-queue)
- [persist-queue - PyPI](https://pypi.org/project/persist-queue/)
- [litequeue - GitHub](https://github.com/litements/litequeue)
- [Build a Shared-Nothing Distributed Queue with SQLite](https://dev.to/hexshift/build-a-shared-nothing-distributed-queue-with-sqlite-and-python-3p1)
- [Lean SQLite Store: Python MVCC Time Travel JSON1 FTS5 RBU 2026](https://johal.in/lean-sqlite-store-python-mvcc-time-travel-json1-fts5-rbu-2026-2/)

### Separation of Concerns and Architecture Patterns
- [Event-Driven Architecture in Python - TO THE NEW](https://www.tothenew.com/blog/design-implement-a-event-driven-architecture-in-python/)
- [Lambda Retry And Idempotency - Dashbird](https://dashbird.io/knowledge-base/aws-lambda/retries-and-idempotency/)
- [Plugin Architecture Design Pattern](https://devleader.substack.com/p/plugin-architecture-design-pattern)

### Plex Integration
- Plex API 503 errors occur during maintenance, database migrations, and backups (temporary conditions that should trigger retries)
- [Plex Forums - 503 Service Unavailable discussions](https://forums.plex.tv/t/503-service-unavailable/768874)
