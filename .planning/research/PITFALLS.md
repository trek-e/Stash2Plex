# Pitfalls Research: Outage Resilience Features

**Domain:** Adding Outage Resilience to Event-Driven Sync System
**Researched:** 2026-02-15
**Confidence:** HIGH

**Context:** PlexSync is an event-driven Stash plugin (NOT a daemon) adding automatic recovery when Plex returns, circuit breaker persistence, health monitoring, and DLQ recovery. The existing system has in-memory circuit breaker, 999-retry PlexServerDown, and check-on-invocation scheduling.

---

## Critical Pitfalls

Mistakes that cause cascading failures, data corruption, or require rewrites.

### Pitfall 1: Circuit Breaker Stale State Race Condition

**What goes wrong:**
Multiple plugin invocations read stale circuit breaker state from disk, all simultaneously transition to HALF_OPEN, and send a thundering herd of test requests to Plex. The recovering Plex server gets overwhelmed and crashes again, creating a metastable failure loop.

**Why it happens:**
Event-driven plugins are invoked per-hook (scene.update, task.process_queue), NOT long-running daemons. Each invocation loads circuit breaker state from JSON file, checks if it's due for transition (OPEN→HALF_OPEN after timeout), and saves updated state. But between load-check-save, other invocations can occur. Without distributed locking, multiple instances race:

```
Time  | Invocation A                | Invocation B                | Invocation C
------|----------------------------|----------------------------|----------------------------
T+0   | Load state: OPEN, opened_at=T-60 | (not started)         | (not started)
T+1   | Check: elapsed=61s > 60s timeout | Load state: OPEN, opened_at=T-60 | (not started)
T+2   | Transition to HALF_OPEN    | Check: elapsed=62s > 60s timeout | Load state: OPEN (stale)
T+3   | Send test request to Plex  | Transition to HALF_OPEN    | Check: stale, transition HALF_OPEN
T+4   | (writing state...)         | Send test request to Plex  | Send test request to Plex
T+5   | Write state: HALF_OPEN     | Write state: HALF_OPEN (overwrites A) | Write state: HALF_OPEN (overwrites B)
```

Result: 3 test requests sent simultaneously instead of 1.

**How to avoid:**

1. **File-based distributed lock with PID tracking:**
   ```python
   import fcntl
   import os

   class CircuitBreakerStateLock:
       def __init__(self, lock_path):
           self.lock_path = lock_path
           self.lock_file = None

       def acquire(self, timeout=5.0):
           """Acquire exclusive lock or timeout."""
           self.lock_file = open(self.lock_path, 'w')
           try:
               fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
               self.lock_file.write(f"{os.getpid()}\n")
               self.lock_file.flush()
               return True
           except BlockingIOError:
               # Lock held by another process
               return False

       def release(self):
           if self.lock_file:
               fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
               self.lock_file.close()
   ```

2. **Optimistic concurrency control with version numbers:**
   ```json
   {
     "state": "OPEN",
     "version": 42,
     "opened_at": 1707926400.0
   }
   ```
   Before writing, check version matches what was read. If mismatch, reload and retry logic.

3. **Single-writer pattern via daemon thread:**
   - Circuit breaker transitions happen ONLY in worker daemon thread (already exists)
   - Hook invocations READ circuit breaker state but don't modify it
   - State file becomes read-only for hooks, read-write for worker
   - **RECOMMENDED:** Aligns with existing architecture where worker already manages circuit breaker in memory

4. **Idempotent state transitions:**
   - Make HALF_OPEN→test request idempotent with cooldown
   - Track `last_test_request_at` timestamp
   - Only send test request if >10s since last attempt
   - Multiple invocations reading stale HALF_OPEN state won't duplicate test requests

**Warning signs:**
- Multiple "Circuit breaker transitioned to HALF_OPEN" log entries within same second
- Plex server receives burst of requests after recovery timeout expires
- Circuit breaker state file has multiple rapid writes (check mtime changes)
- Plex goes down again immediately after circuit opens→half-open transition

**Phase to address:**
**Phase 17 (Circuit Breaker Persistence)** — Add file locking BEFORE implementing state persistence. Test with concurrent plugin invocations (simulate rapid hook events).

---

### Pitfall 2: Health Check False Positive from Plex Restart Sequence

**What goes wrong:**
Health check detects Plex is "up" (port 32400 responds to TCP connect), declares server healthy, circuit breaker closes, and queue processing resumes. But Plex is still initializing its database and returns 503 Service Unavailable for all metadata requests. Queue drains with hundreds of failures, circuit breaker reopens immediately, retry counters increment wastefully.

**Why it happens:**
Plex server startup sequence has multiple stages:
1. Process starts, binds to port 32400 (TCP connect succeeds)
2. HTTP server starts, returns 503 for requests (database loading)
3. Database loads, server transitions to ready state
4. Metadata API endpoints start responding with 200

Simple health checks (TCP connect, HTTP GET `/`) succeed at stage 2-3 but server can't process real requests. This is a **partial availability** scenario - server appears healthy but isn't functionally ready.

**How to avoid:**

1. **Deep health check with sentinel request:**
   ```python
   def is_plex_healthy(plex_client, library_id):
       """Check if Plex can handle real metadata requests."""
       try:
           # Don't just ping, make a lightweight real request
           sections = plex_client.library.sections()
           target_section = plex_client.library.section(library_id)
           # If we can fetch library sections, server is truly ready
           return True
       except plexapi.exceptions.ServiceUnavailable:
           return False  # Server up but not ready
       except Exception:
           return False  # Server down or other error
   ```

2. **Health check with state verification:**
   ```python
   def verify_plex_ready(plex_client):
       """Verify Plex has finished database initialization."""
       try:
           # Check server identity (requires DB access)
           identity = plex_client.machineIdentifier
           # Check library accessibility
           libraries = plex_client.library.sections()
           # If both succeed, database is loaded
           return len(libraries) > 0
       except Exception as e:
           log_debug(f"Plex health check failed: {e}")
           return False
   ```

3. **Grace period after health check success:**
   ```python
   # Don't close circuit immediately on first success
   # Require N consecutive successful health checks
   success_threshold = 3  # Circuit breaker already supports this

   # Add grace period: wait 30s after "healthy" before resuming
   if circuit_breaker.state == CircuitState.HALF_OPEN:
       if health_check_success():
           time.sleep(30)  # Let Plex stabilize
           if health_check_success():  # Double-check
               circuit_breaker.record_success()
   ```

4. **Graduated recovery with canary requests:**
   ```python
   # When transitioning HALF_OPEN → CLOSED:
   # 1. Send 1 canary request, wait for success
   # 2. Send 5 requests, check 80% success rate
   # 3. Send 20 requests, check 90% success rate
   # 4. Fully open queue processing
   # Catches partial availability scenarios
   ```

**Warning signs:**
- Health checks report "healthy" but sync requests fail with 503
- Circuit breaker rapidly cycles HALF_OPEN → CLOSED → OPEN
- Burst of 503 errors immediately after circuit closes
- Plex logs show requests arriving before "Database opened" message

**Phase to address:**
**Phase 18 (Health Monitoring)** — Implement deep health check (sentinel request) NOT shallow check (TCP connect). Test against real Plex restart to verify initialization stages.

---

### Pitfall 3: Thundering Herd on Automatic Recovery Trigger

**What goes wrong:**
Plex comes back online after 2-hour outage. Automatic recovery triggers reconciliation, detecting 500+ stale scenes. All 500 sync jobs enqueue simultaneously, worker attempts to drain queue at maximum rate, Plex gets overwhelmed (CPU spikes, slow responses), and new failures occur. Circuit breaker reopens, recovery fails, and the cycle repeats creating metastable failure.

**Why it happens:**
Recovery assumes "Plex is healthy = can handle full load immediately." But recovering systems have reduced capacity:
- Database caches are cold (disk reads slower than memory)
- Connection pools are rebuilding
- OS buffers not warmed up
- Plex may be catching up on its own background tasks (library scanning, thumbnail generation)

The existing queue has 500+ jobs with `next_retry_at` timestamps in the past. When circuit closes, worker loop processes ALL ready jobs immediately (no artificial throttling).

**How to avoid:**

1. **Backpressure-aware recovery with rate limiting:**
   ```python
   class RecoveryManager:
       def __init__(self, max_recovery_rate=5):  # 5 jobs/sec during recovery
           self.max_recovery_rate = max_recovery_rate
           self.recovery_mode = False
           self.recovery_started_at = None

       def enter_recovery_mode(self):
           """Called when circuit transitions HALF_OPEN → CLOSED."""
           self.recovery_mode = True
           self.recovery_started_at = time.time()
           log_info(f"Entering recovery mode: max {self.max_recovery_rate} jobs/sec")

       def should_process_job(self):
           """Rate limit during recovery period (first 5 minutes)."""
           if not self.recovery_mode:
               return True

           elapsed = time.time() - self.recovery_started_at
           if elapsed > 300:  # 5 minutes
               self.recovery_mode = False
               log_info("Exiting recovery mode: normal rate resumed")
               return True

           # Throttle to max_recovery_rate
           time.sleep(1.0 / self.max_recovery_rate)
           return True
   ```

2. **Graduated queue draining with observation windows:**
   ```python
   # Phase 1 (0-2 min): Process 5 jobs/sec, monitor error rate
   # Phase 2 (2-5 min): If error rate <5%, increase to 10 jobs/sec
   # Phase 3 (5-10 min): If error rate <5%, increase to 20 jobs/sec
   # Phase 4 (10+ min): Resume normal rate (config.poll_interval)

   def calculate_recovery_rate(elapsed_seconds, error_rate):
       if error_rate > 0.05:  # >5% errors
           return 2  # Slow down
       elif elapsed_seconds < 120:
           return 5
       elif elapsed_seconds < 300:
           return 10
       elif elapsed_seconds < 600:
           return 20
       else:
           return None  # Normal rate
   ```

3. **Prioritize recent jobs over stale jobs:**
   ```python
   # Don't process queue FIFO during recovery
   # Sort by recency: jobs enqueued in last hour first
   # Old jobs (2+ hours) deferred to after recovery period

   def get_recovery_batch(queue, batch_size=10):
       all_pending = get_pending_jobs(queue)
       now = time.time()

       # Split by age
       recent = [j for j in all_pending if now - j['enqueued_at'] < 3600]
       stale = [j for j in all_pending if now - j['enqueued_at'] >= 3600]

       # Prioritize recent, limit stale
       batch = recent[:batch_size] + stale[:max(0, batch_size - len(recent))]
       return batch
   ```

4. **Adaptive concurrency limits (Little's Law):**
   ```python
   # Measure: avg_latency (time per sync) and error_rate
   # Calculate: optimal_concurrency = target_latency / avg_latency
   # Adjust: decrease if error_rate rising, increase if stable

   if error_rate > 0.1:  # 10% errors
       max_concurrent_jobs -= 1
   elif error_rate < 0.01 and avg_latency < target_latency:
       max_concurrent_jobs += 1
   ```

**Warning signs:**
- Circuit breaker repeatedly transitions CLOSED→OPEN during recovery
- Plex server CPU spikes to 100% when circuit closes
- First 50 jobs succeed, then failures start occurring
- Error rate increases over time during queue draining
- Plex web UI becomes unresponsive after recovery

**Phase to address:**
**Phase 19 (Automatic Recovery Triggers)** — Implement graduated recovery with rate limiting BEFORE automatic reconciliation. Test with large backlogs (500+ jobs) after simulated outage.

---

### Pitfall 4: DLQ Recovery Without Deduplication

**What goes wrong:**
User triggers "Recover DLQ" task to reprocess 200 failed jobs. Unknown to user, 150 of those jobs already succeeded on manual retry (via "Sync Scene" task) but stayed in DLQ due to timing/accounting bug. Recovery reprocesses all 200, creating 150 duplicate sync operations and corrupting Plex metadata.

**Why it happens:**
DLQ is write-only: jobs enter when max retries exhausted, but nothing removes them when manually resolved. No reconciliation between "job in DLQ" and "job actually failed in Plex." DLQ recovery assumes all DLQ items are valid retry candidates without verification.

**How to avoid:**

1. **Pre-recovery validation with Plex state check:**
   ```python
   def validate_dlq_item(dlq_item, plex_client, stash_client):
       """Check if DLQ item still needs recovery."""
       scene_id = dlq_item['scene_id']

       # Check 1: Does scene still exist in Stash?
       try:
           scene = stash_client.find_scene(scene_id)
           if not scene:
               log_info(f"Scene {scene_id} deleted from Stash, skip recovery")
               return False
       except Exception:
           return False

       # Check 2: Is Plex metadata already current?
       try:
           plex_item = plex_matcher.find_plex_item(scene)
           if plex_item and is_metadata_current(plex_item, scene):
               log_info(f"Scene {scene_id} already synced, skip recovery")
               return False
       except PlexNotFound:
           # Item not in Plex, needs sync
           return True

       # Check 3: Is scene already in active queue?
       if is_in_queue(scene_id):
           log_info(f"Scene {scene_id} already queued, skip recovery")
           return False

       return True  # Needs recovery
   ```

2. **Idempotent recovery with deduplication tracking:**
   ```python
   # Track recovered DLQ items to prevent double-recovery
   recovered_dlq_items = set()  # Persist to disk

   def recover_dlq_item(item):
       item_key = f"{item['scene_id']}_{item['update_type']}"

       if item_key in recovered_dlq_items:
           log_debug(f"Item {item_key} already recovered, skip")
           return

       if validate_dlq_item(item):
           enqueue(item)
           recovered_dlq_items.add(item_key)
           save_recovered_items(recovered_dlq_items)
   ```

3. **DLQ item expiration policy:**
   ```python
   # Remove DLQ items older than 30 days
   # Assumption: if not manually recovered in 30 days, likely not important
   def purge_stale_dlq_items(dlq, max_age_days=30):
       cutoff = time.time() - (max_age_days * 86400)

       stale_items = []
       for item in dlq.iterate():
           if item.get('failed_at', 0) < cutoff:
               stale_items.append(item)

       for item in stale_items:
           dlq.delete(item)
           log_info(f"Purged stale DLQ item: {item['scene_id']}")
   ```

4. **Reconciliation-aware DLQ recovery:**
   ```python
   # Before recovering DLQ, run gap detection
   # Only recover items that gap detection confirms are missing/stale

   def smart_dlq_recovery(dlq, gap_detector):
       gaps = gap_detector.detect_all_gaps()
       gap_scene_ids = {g['scene_id'] for g in gaps}

       for dlq_item in dlq.iterate():
           if dlq_item['scene_id'] in gap_scene_ids:
               enqueue(dlq_item)  # Confirmed gap
           else:
               log_debug(f"DLQ item {dlq_item['scene_id']} not in gaps, skip")
   ```

**Warning signs:**
- Same scene syncs twice after DLQ recovery
- Plex metadata shows duplicate tags/collections after recovery
- DLQ recovery logs show "Item already in queue" warnings
- Users report "DLQ recovery made things worse"

**Phase to address:**
**Phase 20 (DLQ Recovery UI)** — Add pre-recovery validation BEFORE implementing recovery task. Test with DLQ containing mix of valid failures and already-resolved items.

---

### Pitfall 5: Check-on-Invocation Race Condition with Concurrent Hooks

**What goes wrong:**
Two scene.update hooks fire simultaneously (user bulk-edits 50 scenes). Both invocations check reconciliation state: `last_run_time=T-86400, interval=daily`. Both calculate "24 hours elapsed, trigger reconciliation now." Both trigger reconciliation, scanning Plex library twice simultaneously, creating duplicate gap detection jobs.

**Why it happens:**
Check-on-invocation pattern reads state, makes decision, then acts. No atomicity between "check if due" and "mark as running." Multiple concurrent invocations see same state and all decide to act.

```python
# VULNERABLE CODE:
def on_hook(hook_event):
    scheduler = ReconciliationScheduler(data_dir)

    if scheduler.is_due(interval='daily'):  # Multiple invocations all see "true"
        trigger_reconciliation()  # All trigger simultaneously
        scheduler.record_run(...)  # Race: last write wins
```

**How to avoid:**

1. **Atomic check-and-set with file locking:**
   ```python
   import fcntl

   def try_trigger_reconciliation(scheduler, interval):
       """Atomically check if due and mark as running."""
       lock_path = os.path.join(scheduler.data_dir, 'reconciliation.lock')

       try:
           lock_file = open(lock_path, 'w')
           # Non-blocking acquire
           fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

           try:
               # Inside lock: check if still due
               if scheduler.is_due(interval):
                   # Mark as in-progress BEFORE releasing lock
                   state = scheduler.load_state()
                   state.last_run_time = time.time()  # Prevent other invocations
                   scheduler.save_state(state)

                   # Now safe to trigger (lock released)
                   trigger_reconciliation()
                   return True
               return False
           finally:
               fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
               lock_file.close()
       except BlockingIOError:
           # Another invocation holds lock, skip
           log_debug("Reconciliation already in progress, skip")
           return False
   ```

2. **Cooldown window with timestamp precision:**
   ```python
   def is_due_with_cooldown(scheduler, interval, cooldown_seconds=300):
       """Require 5-minute cooldown between runs to prevent races."""
       state = scheduler.load_state()
       now = time.time()

       # Check interval
       interval_secs = INTERVAL_SECONDS[interval]
       if now - state.last_run_time < interval_secs:
           return False

       # Check cooldown (prevents concurrent invocations)
       if now - state.last_run_time < interval_secs + cooldown_seconds:
           # We're in the window where multiple invocations might trigger
           # Add randomized delay to desynchronize
           time.sleep(random.uniform(0, 5))
           # Reload state (another invocation may have updated)
           state = scheduler.load_state()
           if now - state.last_run_time < interval_secs:
               return False  # Another invocation triggered

       return True
   ```

3. **Single-threaded reconciliation via worker queue:**
   ```python
   # Instead of triggering reconciliation directly from hooks:
   # 1. Hook checks if due
   # 2. If due, enqueue special "reconciliation" job
   # 3. Worker processes reconciliation jobs sequentially

   def on_hook(hook_event):
       if scheduler.is_due('daily'):
           enqueue_reconciliation_job()  # Worker deduplicates

   def worker_loop():
       job = queue.get()
       if job['type'] == 'reconciliation':
           # Only one worker, sequential processing
           run_reconciliation()
       elif job['type'] == 'sync':
           sync_scene(job['scene_id'])
   ```

4. **Idempotent reconciliation with run ID:**
   ```python
   # Track current reconciliation run ID
   # Multiple invocations enqueue gaps with same run_id
   # Deduplicate at queue level

   state.current_run_id = f"recon_{int(time.time())}"

   for gap in detected_gaps:
       job = {
           'scene_id': gap['scene_id'],
           'reconciliation_run_id': state.current_run_id
       }
       enqueue(job)  # Queue deduplicates by (scene_id, run_id)
   ```

**Warning signs:**
- Multiple "Starting reconciliation" log entries within seconds
- Gap detection runs twice, finding same gaps
- Reconciliation state file shows rapid updates (multiple mtimes/second)
- Queue receives duplicate jobs for same scenes

**Phase to address:**
**Phase 19 (Automatic Recovery Triggers)** — Add file locking for check-on-invocation BEFORE implementing automatic reconciliation. Test with concurrent hook events (bulk scene updates).

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip file locking for state persistence | Simpler code, no lock contention handling | Race conditions with concurrent invocations, duplicate reconciliation runs | NEVER (PlexSync has concurrent hooks) |
| Use shallow health check (TCP connect) | Fast response, simple implementation | False positives during Plex startup, premature queue draining | Only if combined with grace period or graduated recovery |
| Recover entire DLQ without validation | Simple "replay all" logic | Duplicate syncs if items already resolved manually | Only for small DLQs (<10 items) where duplicates are acceptable |
| Hard-code recovery rate limits | No adaptive logic needed | Can't handle varying Plex capacity (beefy server vs. RPi) | Acceptable for MVP if config-overrideable |
| Store circuit breaker state only in memory | No file I/O overhead | State lost on crash, circuit reopens unnecessarily | NEVER (defeats purpose of persistence) |
| Poll Plex health every 10 seconds during outage | Fast recovery detection | Wastes resources during long outages, Plex sees failed requests | Only if adaptive (slow down after N failures) |

---

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Plex Health Check | Assume port 32400 open = server ready | Make sentinel request to metadata API, verify DB loaded |
| Circuit Breaker Persistence | Write state file without atomic rename | Use temp file + fsync + rename pattern to prevent corruption |
| Automatic Recovery | Close circuit immediately on first health check success | Require N consecutive successes (half-open threshold) |
| DLQ Recovery | Replay all items blindly | Validate items still need recovery (check Plex current state) |
| Reconciliation Scheduling | Check interval based on wall-clock time | Use elapsed time since last run + cooldown to prevent races |
| Queue Draining | Process all ready jobs at max rate | Rate-limit during recovery period (graduated draining) |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Health check polling every second | Plex logs fill with /identity requests, CPU waste | Adaptive interval: 1s during HALF_OPEN, 60s during OPEN | >30 minute outages (1800+ unnecessary health checks) |
| No backpressure during recovery | Plex CPU spikes to 100%, queue draining stalls | Rate limit to 5-10 jobs/sec for first 5 minutes | Backlogs >100 jobs |
| File lock contention on every hook | Hook latency increases with concurrent events | Use lock only for reconciliation trigger, not every hook | >10 concurrent hook invocations |
| Unbounded DLQ growth | DLQ inspection becomes slow, memory issues | Expire items >30 days old, cap DLQ at 1000 items | DLQ >10,000 items |
| Gap detection on every startup | Stash startup delayed 30+ seconds | Only run if >1 hour since last startup | Libraries >5,000 scenes |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Circuit Breaker Persistence:** Persists state to disk, BUT no file locking → race conditions with concurrent invocations
- [ ] **Health Monitoring:** Checks Plex port 32400, BUT doesn't verify database loaded → false positives during startup
- [ ] **Automatic Recovery:** Triggers reconciliation when circuit closes, BUT no rate limiting → thundering herd
- [ ] **DLQ Recovery:** UI to replay failed jobs, BUT no pre-validation → duplicate syncs for already-resolved items
- [ ] **Reconciliation Scheduling:** Check-on-invocation pattern, BUT no atomic check-and-set → duplicate runs
- [ ] **Queue Draining:** Processes backlog after recovery, BUT FIFO order → starves recent jobs during recovery

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Thundering herd overwhelmed Plex | MEDIUM | 1. Manually pause queue processing 2. Restart Plex 3. Clear retry timestamps 4. Resume with rate limit |
| Stale circuit breaker state race | LOW | 1. Stop all plugin processes 2. Delete state file 3. Restart with lock enabled |
| DLQ duplicates corrupted metadata | HIGH | 1. Identify affected scenes (query DLQ timestamps) 2. Manually fix Plex metadata 3. Re-sync scenes |
| False positive health check | LOW | 1. Circuit opens automatically after failures 2. Implement deep health check 3. Deploy update |
| Concurrent reconciliation runs | MEDIUM | 1. Check for duplicate gaps in queue 2. Deduplicate by scene_id 3. Add file locking |
| Health check polling storm | LOW | 1. Increase poll interval in config 2. Restart plugin 3. Verify Plex CPU normal |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Circuit breaker race condition | Phase 17 (Circuit Breaker Persistence) | Test with 10 concurrent hook invocations, verify single HALF_OPEN transition |
| Health check false positive | Phase 18 (Health Monitoring) | Test against real Plex restart, verify circuit doesn't close during initialization |
| Thundering herd on recovery | Phase 19 (Automatic Recovery) | Simulate 500-job backlog, verify graduated draining with <5% error rate |
| DLQ recovery duplicates | Phase 20 (DLQ Recovery UI) | Create DLQ with resolved items, verify recovery validates before enqueue |
| Check-on-invocation race | Phase 19 (Automatic Recovery) | Trigger 5 concurrent hooks at reconciliation boundary, verify single run |
| Queue drain backpressure | Phase 19 (Automatic Recovery) | Monitor Plex CPU during 500-job recovery, verify <80% utilization |

---

## Sources

### Circuit Breaker Patterns & Persistence
- [Building Resilient Systems: Circuit Breakers and Retry Patterns](https://dasroot.net/posts/2026/01/building-resilient-systems-circuit-breakers-retry-patterns/)
- [How to Configure Circuit Breaker Patterns](https://oneuptime.com/blog/post/2026-02-02-circuit-breaker-patterns/view)
- [The Complete Guide to Resilience Patterns in Distributed Systems](https://technori.com/2026/02/24230-the-complete-guide-to-resilience-patterns-in-distributed-systems/gabriel/)
- [Circuit Breaker Pattern for Serverless Applications](https://resources.fenergo.com/engineering-at-fenergo/circuit-breaker-pattern-for-serverless-applications) — MemoryDB persistence for stateless functions
- [Distributed Circuit Breakers in Event-Driven Architectures on AWS](https://sodkiewiczm.medium.com/distributed-circuit-breakers-in-event-driven-architectures-on-aws-95774da2ce7e)

### Health Check Anti-Patterns
- [How to Implement Health Check Design](https://oneuptime.com/blog/post/2026-01-30-health-check-design/view)
- [Implementing health checks — AWS Builders Library](https://aws.amazon.com/builders-library/implementing-health-checks/) — Dependency health check false positives, fail-open pattern
- [Microservices Pattern: Health Check API](https://microservices.io/patterns/observability/health-check-api.html)

### Thundering Herd & Recovery Triggers
- [Mastering Exponential Backoff in Distributed Systems](https://betterstack.com/community/guides/monitoring/exponential-backoff/)
- [Retry Storm Antipattern — Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/antipatterns/retry-storm/)
- [Distributed Systems Horror Stories: The Thundering Herd Problem](https://encore.dev/blog/thundering-herd-problem)
- [The Thundering Herd Problem and Its Solutions](https://www.nottldr.com/SystemSage/the-thundering-herd-problem-and-its-solutions-0ie2hx3)

### Queue Backpressure & Recovery
- [Avoiding insurmountable queue backlogs — AWS Builders Library](https://aws.amazon.com/builders-library/avoiding-insurmountable-queue-backlogs/)
- [How to Implement Backpressure Handling in OpenTelemetry Pipelines](https://oneuptime.com/blog/post/2026-02-06-backpressure-handling-opentelemetry-pipelines/view)
- [Understanding Back Pressure in Message Queues](https://akashrajpurohit.com/blog/understanding-back-pressure-in-message-queues-a-guide-for-developers/)
- [Backpressure explained — the resisted flow of data through software](https://medium.com/@jayphelps/backpressure-explained-the-flow-of-data-through-software-2350b3e77ce7)

### DLQ & Poison Message Handling
- [Dead Letter Queue (DLQ): What It Is and How to Implement It in a Node.js Application](https://devdiaryacademy.medium.com/dead-letter-queue-dlq-what-it-is-and-how-to-implement-it-in-a-node-js-application-3c6d4b6a9400)
- [Message reprocessing: How to implement the dead letter queue](https://www.redpanda.com/blog/reliable-message-processing-with-dead-letter-queue)
- [Apache Kafka Dead Letter Queue: A Comprehensive Guide](https://www.confluent.io/learn/kafka-dead-letter-queue/)
- [Dead Letter Queues (DLQ): The Complete, Developer-Friendly Guide](https://swenotes.com/2025/09/25/dead-letter-queues-dlq-the-complete-developer-friendly-guide/)

### Cascade Failure Prevention
- [How to Avoid Cascading Failures in Distributed Systems](https://www.infoq.com/articles/anatomy-cascading-failure/)
- [Circuit Breakers: Preventing Cascade Failures in Distributed Systems](https://medium.com/towardsdev/circuit-breakers-preventing-cascade-failures-in-distributed-systems-7a3a921636c3)
- [What are Cascading Failures? — BMC Software](https://www.bmc.com/blogs/cascading-failures/)

### Event-Driven Architecture & State Persistence
- [Common Pitfalls in Event-Driven Architectures](https://medium.com/insiderengineering/common-pitfalls-in-event-driven-architectures-de84ad8f7f25)
- [Persistence in Event Driven Architectures](https://dzone.com/articles/persistence-in-event-driven-architectures)
- [Exploring event-driven architecture in microservices: patterns, pitfalls and best practices](https://www.researchgate.net/publication/388709044_Exploring_event-driven_architecture_in_microservices-_patterns_pitfalls_and_best_practices)

### Race Conditions & Distributed Locking
- [Handling Race Condition in Distributed System — GeeksforGeeks](https://www.geeksforgeeks.org/computer-networks/handling-race-condition-in-distributed-system/)
- [The Art of Staying in Sync: How Distributed Systems Avoid Race Conditions](https://medium.com/@alexglushenkov/the-art-of-staying-in-sync-how-distributed-systems-avoid-race-conditions-f59b58817e02)
- [Race Conditions in a Distributed System](https://medium.com/hippo-engineering-blog/race-conditions-in-a-distributed-system-ea6823ee2548)
- [Distributed Locking and Race Condition Prevention](https://dzone.com/articles/distributed-locking-and-race-condition-prevention)

### File Corruption & Atomic Writes
- [Storage resilience: atomic writes, safer temp cleanup, repair/restore tools](https://github.com/anomalyco/opencode/issues/7733) — Temp + fsync + rename pattern
- [Registry corruption (empty array) after crash during atomic rename](https://github.com/openclaw/openclaw/issues/1469) — Real-world JSON corruption

---

*Pitfalls research for: PlexSync outage resilience features (v1.5 milestone)*
*Researched: 2026-02-15*
*Focus: Event-driven architecture constraints, non-daemon process state management, concurrent invocation safety*
