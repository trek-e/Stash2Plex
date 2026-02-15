# Stack Research: Outage Resilience

**Domain:** Outage Resilience for Stash-to-Plex Sync Plugin (v1.5)
**Researched:** 2026-02-15
**Confidence:** HIGH

## Recommended Stack

### Core Technologies (NEW for v1.5)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| json (stdlib) | 2.0.9 | Circuit breaker state persistence | Already validated in reconciliation scheduler (reconciliation/scheduler.py). Atomic write pattern (write to .tmp, os.replace) prevents corruption on crashes. Human-readable for debugging. Zero dependencies. |
| diskcache | >=5.6.0 | Alternative state persistence (optional) | Already in requirements.txt (5.6.3 installed). Thread-safe, process-safe, dict-like API. Use if multi-process scenarios emerge or atomic transactions needed beyond JSON pattern. NOT required for initial implementation. |

### Existing Technologies (REUSE for v1.5)

| Technology | Version | Purpose | Why Reuse |
|------------|---------|---------|-----------|
| plexapi | >=4.17.0 | Health check via server.query('/identity') | v4.18.0 installed. No dedicated ping/health methods exist in plexapi. Use server.query('/identity') or try PlexServer init with timeout to detect connectivity. Lightweight XML response validates Plex is reachable. |
| threading.Timer | stdlib | Check-on-invocation recovery trigger | Pattern validated in reconciliation/scheduler.py. Use is_due() pattern on each plugin invocation to check if queue drain should be attempted after circuit breaker recovery. |
| time.time() | stdlib | Timestamps for recovery detection | Used in circuit_breaker.py for OPEN→HALF_OPEN timeout. Reuse for state persistence timestamps (circuit_opened_at, last_health_check). |

### Supporting Libraries (DO NOT ADD)

| Library | Version | Purpose | Why NOT Recommended |
|---------|---------|---------|---------------------|
| pybreaker | >=1.0.0 | Circuit breaker with Redis persistence | **AVOID** - Requires Redis server (external dependency). PlexSync circuit_breaker.py already implements 3-state pattern (CLOSED/OPEN/HALF_OPEN) in 140 lines. Adding external dependency contradicts single-file plugin deployment model. Use JSON persistence for existing circuit breaker instead. |
| APScheduler | >=3.11.0 | Advanced scheduling | **NOT NEEDED** - Overkill for outage resilience. Check-on-invocation pattern (validated in reconciliation/scheduler.py) handles recovery triggers without timers/daemons. Plugin is invoked per-event, not long-running. |
| redis-py | >=5.0.0 | Circuit breaker state storage | **AVOID** - Requires Redis server. Stash plugin users won't have Redis. JSON file persistence (stdlib) sufficient for state across restarts. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest | Test circuit breaker persistence | Already in use (999 tests). Add tests for circuit breaker state save/load, recovery detection, health check logic. |
| pytest-mock | Mock plexapi server.query('/identity') | Already in use. Mock server.query to simulate Plex outages, recoveries, partial failures. |

## Installation

```bash
# NO NEW DEPENDENCIES REQUIRED
# All capabilities available in existing stack:
# - json (stdlib) for circuit breaker state persistence
# - plexapi >=4.17.0 (already installed) for health checks
# - threading.Timer (stdlib) for check-on-invocation pattern
# - diskcache >=5.6.0 (already installed) as optional alternative

# Existing requirements.txt unchanged:
# persist-queue>=1.1.0
# stashapi
# plexapi>=4.17.0
# tenacity>=9.0.0
# pydantic>=2.0.0
# diskcache>=5.6.0
```

## Alternatives Considered

| Category | Recommended | Alternative | When to Use Alternative |
|----------|-------------|-------------|-------------------------|
| State Persistence | json (stdlib) | diskcache | If multi-process scenarios emerge (unlikely for Stash plugin). diskcache adds thread-safety guarantees beyond JSON, but atomic write pattern (write to .tmp, os.replace) already prevents corruption. Use JSON unless complexity justifies dict-like API. |
| State Persistence | json (stdlib) | shelve (stdlib) | **AVOID** - shelve with writeback=True caches all entries in memory (memory consumption), slow close(). JSON is simpler and sufficient for small state (5-10 fields). |
| Circuit Breaker Lib | Custom (circuit_breaker.py) | pybreaker | If Redis infrastructure exists (not typical for Stash users). pybreaker supports CircuitRedisStorage but requires redis-py + Redis server. Custom implementation is 140 lines, no dependencies, already validated. |
| Health Check | plexapi server.query('/identity') | HTTP request with requests library | If plexapi removed from requirements (unlikely). server.query() wraps HTTP requests with proper auth, timeout handling, XML parsing. Reuse existing dependency. |
| Recovery Trigger | Check-on-invocation (is_due pattern) | Threading.Timer with daemon thread | If plugin becomes long-running (contradicts Stash plugin model). Check-on-invocation validated in reconciliation/scheduler.py. Each plugin invocation checks if recovery attempt should occur (elapsed time since circuit opened). |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| pybreaker library | Requires Redis server (CircuitRedisStorage). Adds external dependency for persistence when JSON file suffices. Circuit breaker already implemented in worker/circuit_breaker.py (140 lines, 3-state, no deps). | Extend existing CircuitBreaker class with save_state()/load_state() methods using JSON. |
| shelve for state | Complexity for small state. shelve is dict-like persistent storage but overkill for 5-10 fields. writeback=True caches all entries in memory, slow close(). | json with atomic write pattern (write to .tmp, os.replace). Pattern validated in reconciliation/scheduler.py save_state(). |
| requests library for health check | Duplicate dependency when plexapi already wraps HTTP requests. plexapi.server.query('/identity') handles auth (X-Plex-Token header), timeout, XML parsing. | plexapi.server.query('/identity') or catch PlexServer init timeout. |
| External cron for recovery trigger | Breaks single-file plugin deployment. Requires system-level config. Stash scheduled tasks only support JavaScript (not Python). | Check-on-invocation pattern: on each plugin invocation, load circuit breaker state, check if recovery_timeout elapsed, attempt health check if OPEN→HALF_OPEN transition due. |
| APScheduler for recovery trigger | Overkill for simple time-based check. Adds dependency (not in requirements.txt). Stash plugins are NOT long-running daemons — invoked per-event, then exit. | Check-on-invocation: scheduler.is_due() pattern from reconciliation/scheduler.py. Load state, check elapsed time, trigger recovery attempt if due. |
| Redis for state storage | Requires Redis server installation and configuration. Stash plugin users won't have Redis. State persistence needs are minimal (circuit breaker state across process restarts). | JSON file with atomic write. Sufficient for state: circuit state enum, opened_at timestamp, failure/success counts. |

## Stack Patterns by Variant

### Circuit Breaker State Persistence

**Pattern: JSON file with atomic write**
```python
# In worker/circuit_breaker.py (NEW methods)

import json
import os

STATE_FILE = 'circuit_breaker_state.json'

def save_state(self, data_dir: str) -> None:
    """Save circuit breaker state to JSON file atomically."""
    state = {
        'state': self._state.value,  # 'closed', 'open', 'half_open'
        'opened_at': self._opened_at,
        'failure_count': self._failure_count,
        'success_count': self._success_count,
    }
    state_path = os.path.join(data_dir, STATE_FILE)
    tmp_path = state_path + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, state_path)  # Atomic on POSIX

def load_state(self, data_dir: str) -> None:
    """Load circuit breaker state from JSON file."""
    state_path = os.path.join(data_dir, STATE_FILE)
    if os.path.exists(state_path):
        with open(state_path, 'r') as f:
            data = json.load(f)
        self._state = CircuitState(data['state'])
        self._opened_at = data['opened_at']
        self._failure_count = data['failure_count']
        self._success_count = data['success_count']
```

**Why this pattern:**
- Atomic write (os.replace) prevents corruption on crashes
- Human-readable JSON for debugging circuit breaker stuck states
- Minimal state (4 fields) — JSON overhead negligible
- Pattern validated in reconciliation/scheduler.py (save_state, load_state)

### Health Check Implementation

**Pattern: plexapi server.query('/identity') with timeout**
```python
# In worker/processor.py or new worker/health.py

def check_plex_health(plex_client: PlexClient, timeout: float = 5.0) -> bool:
    """
    Check if Plex server is reachable.

    Returns:
        True if Plex responds to /identity request within timeout.
    """
    try:
        # PlexServer.query() method makes raw API requests
        plex_client.server.query('/identity', timeout=timeout)
        return True
    except Exception as e:
        log_debug(f"Plex health check failed: {e}")
        return False
```

**Why this approach:**
- /identity endpoint is lightweight (returns server UUID, version, platform XML)
- plexapi.server.query() handles auth (X-Plex-Token), timeout, HTTP errors
- No additional dependencies beyond existing plexapi
- Alternative: catch PlexServer init timeout, but query() is more explicit

**Source:** [PlexAPI Server Documentation](https://python-plexapi.readthedocs.io/en/latest/modules/server.html) — server.query() method, timeout parameter

### Recovery Trigger (Check-on-Invocation)

**Pattern: Reuse reconciliation/scheduler.py is_due() logic**
```python
# In worker/circuit_breaker.py (extend existing state property)

@property
def should_attempt_recovery(self) -> bool:
    """
    Check if recovery attempt should be made.

    Returns True if circuit is OPEN and recovery_timeout has elapsed.
    This is checked on each plugin invocation (check-on-invocation pattern).
    """
    if self._state == CircuitState.OPEN and self._opened_at is not None:
        elapsed = time.time() - self._opened_at
        return elapsed >= self._recovery_timeout
    return False
```

**Integration in processor.py:**
```python
# In SyncWorker._process_jobs() or startup
def check_recovery_trigger(self):
    """
    Check if circuit breaker recovery should be attempted.

    Called on each plugin invocation. If recovery timeout elapsed,
    attempts health check to transition OPEN → HALF_OPEN.
    """
    if self.circuit_breaker.should_attempt_recovery:
        log_info("Circuit breaker recovery timeout elapsed, checking Plex health...")
        if check_plex_health(self.plex_client):
            log_info("Plex health check passed, transitioning to HALF_OPEN")
            # Circuit breaker state property automatically transitions OPEN → HALF_OPEN
            # on next can_execute() call when timeout elapsed
            self.circuit_breaker.state  # Trigger state property to transition
        else:
            log_debug("Plex health check failed, circuit remains OPEN")
```

**Why this pattern:**
- Stash plugins invoked per-event (Scene.Update, Task.Start) — check on each invocation
- No daemon thread/timer needed (contradicts Stash plugin lifecycle)
- Pattern validated in reconciliation/scheduler.py (is_due checks elapsed time)
- Gracefully handles rapid plugin invocations (checks elapsed time, avoids spam)

### Queue Drain After Recovery

**Pattern: Trigger process_queue task on circuit close**
```python
# In worker/circuit_breaker.py (_close method)

def _close(self) -> None:
    """Transition to CLOSED state and trigger queue drain."""
    self._state = CircuitState.CLOSED
    self._opened_at = None
    self._failure_count = 0
    self._success_count = 0

    # NEW: Log recovery for observability
    log_info("Circuit breaker closed after recovery, queue drain will resume")

    # Save state to persist across restarts
    if hasattr(self, '_data_dir') and self._data_dir:
        self.save_state(self._data_dir)
```

**Queue drain logic (in SyncWorker):**
```python
# In worker/processor.py (_process_jobs loop)
def _process_jobs(self):
    """Process jobs from queue, respecting circuit breaker state."""
    while self.running:
        if not self.circuit_breaker.can_execute():
            # Circuit OPEN — check if recovery should be attempted
            if self.circuit_breaker.should_attempt_recovery:
                self.check_recovery_trigger()
            time.sleep(1.0)  # Backoff while circuit open
            continue

        # Circuit CLOSED or HALF_OPEN — process queue
        try:
            job = self.queue.get(timeout=1.0)
            if job:
                self._process_job(job)
        except Empty:
            time.sleep(1.0)
```

**Why this approach:**
- Worker loop already checks can_execute() before processing jobs
- Add recovery check when circuit OPEN (check_recovery_trigger)
- Queue drain resumes automatically when circuit transitions CLOSED
- No manual trigger needed — worker loop handles queue processing

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| json@2.0.9 (stdlib) | Python 3.9+ | Built-in. No compatibility concerns. Plugin already requires Python 3.9+ (PythonDepManager). |
| plexapi@4.18.0 | Python 3.9+ | server.query() method exists in 4.17.0+. /identity endpoint is core Plex API (stable across versions). |
| diskcache@5.6.0 | Python 3.9+ | Already in requirements.txt. Optional for state persistence if JSON pattern insufficient. |
| threading.Timer (stdlib) | Python 3.9+ | Built-in. Used in reconciliation scheduler (validated pattern). |

## Integration Considerations

### Circuit Breaker State Persistence

**When to save state:**
- On state transitions: CLOSED→OPEN, OPEN→HALF_OPEN, HALF_OPEN→CLOSED, HALF_OPEN→OPEN
- After record_success() / record_failure() that change counts
- Use atomic write pattern (write to .tmp, os.replace) to prevent corruption

**State file location:**
- Use plugin data_dir (passed to SyncWorker)
- Same directory as stats.json, reconciliation_state.json, sync_timestamps.json
- File: circuit_breaker_state.json

**Load state timing:**
- Load in SyncWorker.__init__() after circuit breaker creation
- Before worker thread starts (ensure state loaded before first can_execute())

### Plex Health Check

**Timeout considerations:**
- Use short timeout (5 seconds) for health checks
- Distinguish from sync operation timeouts (30-60 seconds)
- Health check is lightweight — /identity returns ~200 bytes XML

**When to health check:**
- On recovery trigger (circuit OPEN, recovery_timeout elapsed)
- NOT on every can_execute() call (avoid health check spam)
- NOT on CLOSED→OPEN transition (failure already occurred)

**Error handling:**
- Catch all exceptions (requests.RequestException, plexapi.exceptions.*)
- Health check failure keeps circuit OPEN (does NOT reopen circuit)
- Log at DEBUG level (avoid log spam during prolonged outages)

### Recovery Trigger Pattern

**Check-on-invocation mechanics:**
- Each plugin invocation loads circuit breaker state (if persisted)
- Check should_attempt_recovery in worker loop (when circuit OPEN)
- Elapsed time check prevents spam (recovery_timeout default: 60 seconds)

**Integration with existing patterns:**
- Reconciliation scheduler uses same pattern (is_due checks elapsed time)
- No conflicts with existing worker loop (add recovery check in OPEN branch)

**Graceful handling of rapid invocations:**
- If plugin invoked rapidly while circuit OPEN, recovery check occurs max once per recovery_timeout
- State property transition (OPEN→HALF_OPEN) happens automatically on elapsed timeout

### Performance Impact

**State persistence overhead:**
- JSON serialize/deserialize: <1ms for 4 fields
- Atomic write (write to .tmp, os.replace): <5ms
- Save on state transitions (infrequent: ~5-10 per outage cycle)
- Negligible impact compared to Plex API calls (100-500ms)

**Health check overhead:**
- /identity request: ~50-200ms when Plex healthy
- Timeout on failure: 5 seconds (configurable)
- Frequency: once per recovery_timeout (default 60s) when circuit OPEN
- Does NOT block hook handlers (worker runs in daemon thread)

**Queue drain performance:**
- No change from existing behavior
- Worker loop already polls queue with 1 second timeout
- Recovery check adds <1ms when circuit OPEN

## Sources

### Circuit Breaker State Persistence
- [Python JSON Documentation](https://docs.python.org/3/library/json.html) — HIGH confidence: stdlib, version 2.0.9, basic serialization
- [pybreaker PyPI](https://pypi.org/project/pybreaker/) — HIGH confidence: Redis persistence, CircuitRedisStorage, not recommended for PlexSync
- [DiskCache Documentation](https://grantjenks.com/docs/diskcache/) — HIGH confidence: thread-safe dict-like persistence, already in requirements.txt
- [shelve — Python Object Persistence](https://docs.python.org/3/library/shelve.html) — HIGH confidence: stdlib, not recommended (complexity, memory consumption)
- [DiskCache vs persist-queue comparison](https://github.com/grantjenks/python-diskcache) — MEDIUM confidence: feature comparison, use cases
- Existing codebase: `reconciliation/scheduler.py` save_state()/load_state() pattern (JSON + atomic write) — validated

### Plex Health Check
- [PlexAPI Server Documentation](https://python-plexapi.readthedocs.io/en/latest/modules/server.html) — HIGH confidence: server.query() method, timeout parameter, no dedicated health/ping methods
- [Plex API Documentation — Server Identity](https://plexapi.dev/api-reference/server/get-server-capabilities) — MEDIUM confidence: /identity endpoint structure
- [Plex Healthcheck Gist](https://gist.github.com/dimo414/aaaee1c639d292a64b72f4644606fbf0) — LOW confidence: community pattern, not official docs
- [pms-docker healthcheck.sh](https://github.com/plexinc/pms-docker/blob/master/root/healthcheck.sh) — MEDIUM confidence: official Docker healthcheck uses /identity endpoint
- Existing codebase: `worker/circuit_breaker.py` (3-state pattern validated, 999 tests) — HIGH confidence

### Recovery Trigger Pattern
- Existing codebase: `reconciliation/scheduler.py` is_due() pattern — HIGH confidence: validated check-on-invocation pattern
- [Event-Driven Architecture Patterns (Solace)](https://solace.com/event-driven-architecture-patterns/) — MEDIUM confidence: recovery patterns, DLQ pattern
- [How to Handle Event-Driven Architecture Failures (TechTarget)](https://www.techtarget.com/searchapparchitecture/tip/How-to-handle-typical-event-driven-architecture-failures) — MEDIUM confidence: recovery mechanisms, event replay
- [Rebuilding Read Models and Dead-Letter Queues](https://event-driven.io/en/rebuilding_read_models_skipping_events/) — MEDIUM confidence: DLQ recovery trigger patterns

---
*Stack research for: PlexSync Outage Resilience Features (v1.5)*
*Researched: 2026-02-15*
*Key Recommendation: NO NEW DEPENDENCIES — extend existing circuit breaker with JSON state persistence, plexapi health checks, check-on-invocation recovery triggers*
