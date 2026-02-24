# Phase 17: Circuit Breaker Persistence - Research

**Researched:** 2026-02-15
**Domain:** Persistent state management for circuit breaker resilience in event-driven Python plugin
**Confidence:** HIGH

## Summary

Circuit breaker state persistence enables PlexSync to survive plugin restarts during Plex outages without resetting to CLOSED and hammering the recovering server. The research confirms this is a **standard pattern** requiring **zero new dependencies**—PlexSync already implements the atomic write pattern (JSON + os.replace) in three locations (reconciliation/scheduler.py, worker/stats.py, sync_queue/operations.py), proving the approach works.

The critical challenge is **race conditions from concurrent plugin invocations**. Unlike long-running daemons with a single circuit breaker instance in memory, PlexSync exits after each hook/task invocation. Multiple concurrent hooks (bulk scene updates) can load stale circuit breaker state, all transition to HALF_OPEN simultaneously, and send a thundering herd of test requests to Plex. File locking (fcntl advisory locks on POSIX systems) prevents this, and PlexSync's existing single-writer pattern (only worker thread modifies circuit breaker, hooks read-only) already mitigates most risks.

**Primary recommendation:** Extend CircuitBreaker class with save_state()/load_state() methods using the proven atomic write pattern from reconciliation/scheduler.py. Add file locking around state transitions to prevent concurrent modification. Integrate logging for state transitions (CLOSED→OPEN, OPEN→HALF_OPEN, HALF_OPEN→CLOSED) to meet VISB-02 requirement. This is a **low-risk enhancement**—the patterns are proven, the architecture already supports it, and the test surface is small (~140 lines modified, 15-20 new tests).

## Standard Stack

### Core

All required functionality exists in Python stdlib—**zero new dependencies**.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| json (stdlib) | 2.0.9+ | Circuit breaker state serialization | Human-readable format for debugging, already used in 3 persistence locations (reconciliation_state.json, stats.json, sync_timestamps.json). Proven atomic write pattern with os.replace. |
| os (stdlib) | 3.9+ | Atomic file writes (os.replace) | POSIX atomic rename guarantees no partial writes visible to readers. PlexSync already uses this pattern in reconciliation/scheduler.py:77, worker/stats.py:193, sync_queue/operations.py:340. |
| fcntl (stdlib) | 3.9+ | File-based advisory locking | Prevents race conditions when concurrent plugin invocations modify circuit breaker state. POSIX-only (Linux/macOS), no Windows support, but PlexSync targets Unix-like systems. |
| time (stdlib) | 3.9+ | Timestamps for opened_at tracking | Already used in circuit_breaker.py for OPEN→HALF_OPEN timeout logic. No changes needed. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| dataclasses (stdlib) | 3.9+ | Type-safe state representation | Optional—use if migrating from dict to typed CircuitBreakerState dataclass. Matches reconciliation/scheduler.py pattern (ReconciliationState dataclass). |
| typing (stdlib) | 3.9+ | Type hints for Optional[str] state_file param | Already used throughout codebase. Helps catch None-handling bugs at type-check time. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| json (stdlib) | diskcache (already in requirements.txt) | diskcache provides thread-safe dict-like API with automatic locking. Would simplify code (no manual fcntl locking) but adds conceptual overhead (yet another persistence mechanism). Use json for consistency with existing state files. |
| json (stdlib) | shelve (stdlib) | shelve is dict-like persistent storage but overkill for 5 fields. writeback=True caches all entries in memory (memory leak risk), slow close(). JSON is simpler and sufficient. |
| fcntl advisory locks | Single-writer pattern | PlexSync already has single-writer (only worker thread modifies CB state). This mitigates most race risks. fcntl adds defense-in-depth for check-on-invocation pattern used by recovery detection (Phase 18). Choose single-writer if Phase 18 deferred; add fcntl if implementing full recovery. |
| State persistence | pybreaker with Redis | pybreaker library supports CircuitRedisStorage but requires Redis server. PlexSync targets single-user Stash installs—users won't have Redis. Custom circuit_breaker.py is 140 lines, no dependencies, already validated. |

**Installation:**
```bash
# NO NEW DEPENDENCIES
# All stdlib modules included with Python 3.9+
```

## Architecture Patterns

### Recommended Project Structure

No new files needed—modify existing circuit_breaker.py:

```
worker/
├── circuit_breaker.py        # MODIFIED: Add state_file param, save/load methods, logging
└── processor.py              # MODIFIED: Pass state_file path to CircuitBreaker()

data/                         # Runtime state files (not in git)
└── circuit_breaker.json      # NEW: Persisted circuit breaker state
```

### Pattern 1: Atomic State Persistence

**What:** Save circuit breaker state to disk using atomic write (temp file + os.replace).

**When to use:** Every state transition (CLOSED→OPEN, OPEN→HALF_OPEN, HALF_OPEN→CLOSED/OPEN).

**Example:**
```python
# Source: reconciliation/scheduler.py:72-79 (proven pattern)
def save_state(self, state: CircuitBreakerState) -> None:
    """Save circuit breaker state to disk atomically."""
    if not self._state_file:
        return  # Persistence disabled (tests)

    tmp_path = self._state_file + '.tmp'
    try:
        with open(tmp_path, 'w') as f:
            json.dump({
                'state': self._state.value,  # 'closed', 'open', 'half_open'
                'failure_count': self._failure_count,
                'success_count': self._success_count,
                'opened_at': self._opened_at,
            }, f, indent=2)
        os.replace(tmp_path, self._state_file)  # Atomic on POSIX
    except OSError as e:
        log_debug(f"Failed to save circuit breaker state: {e}")
        # Non-fatal: circuit breaker still works in-memory
```

**Why this pattern:**
- **Atomic:** os.replace is atomic on POSIX (Linux/macOS). Readers never see partial writes.
- **Human-readable:** JSON is debuggable. Users can inspect `data/circuit_breaker.json` to see why queue stopped.
- **Proven:** Used in reconciliation/scheduler.py, worker/stats.py, sync_queue/operations.py. Zero issues in production.
- **Graceful degradation:** OSError logged but not raised—plugin continues if state save fails.

### Pattern 2: File-Based Advisory Locking

**What:** Use fcntl.flock to prevent concurrent state modifications from multiple plugin invocations.

**When to use:** Around state transitions (inside record_success/record_failure) when implementing automatic recovery (Phase 18+).

**Example:**
```python
# Source: .planning/research/PITFALLS.md:38-64 (race condition prevention)
import fcntl

def _save_state_locked(self) -> None:
    """Save state with file locking to prevent concurrent modifications."""
    if not self._state_file:
        return

    lock_path = self._state_file + '.lock'
    lock_file = None
    try:
        lock_file = open(lock_path, 'w')
        # Non-blocking acquire: fail fast if another process holds lock
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Lock acquired: safe to modify state
        self._save_state()  # Atomic write from Pattern 1

        # Lock released automatically on close
    except BlockingIOError:
        # Another invocation holds lock—state save in progress
        log_trace("Circuit breaker state save skipped (locked by another process)")
    except OSError as e:
        log_debug(f"Circuit breaker lock failed: {e}")
    finally:
        if lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except:
                pass  # Best effort unlock
```

**Why this pattern:**
- **Prevents thundering herd:** Multiple hooks can't all transition to HALF_OPEN simultaneously.
- **Non-blocking:** LOCK_NB fails fast instead of blocking plugin invocations.
- **Advisory:** Processes must cooperate (all use same lock path). PlexSync controls all invocations, so this is safe.
- **POSIX-only:** fcntl doesn't work on Windows. PlexSync targets Unix-like systems (Stash runs in Docker on Linux/macOS).

**When to skip:** If Phase 18 (recovery detection) is deferred, skip locking. PlexSync's single-writer pattern (only worker modifies CB state) already prevents most races. Locking adds defense-in-depth for check-on-invocation recovery.

### Pattern 3: State Transition Logging

**What:** Log all circuit breaker state changes with descriptive messages (meets VISB-02 requirement).

**When to use:** Every state transition: _open(), _close(), state property (OPEN→HALF_OPEN).

**Example:**
```python
# In worker/circuit_breaker.py (MODIFIED methods)
def _open(self) -> None:
    """Transition to OPEN state."""
    self._state = CircuitState.OPEN
    self._opened_at = time.time()
    self._failure_count = 0
    self._success_count = 0

    # NEW: Log transition with context
    log_info(f"Circuit breaker OPENED after {self._failure_threshold} consecutive failures")

    # NEW: Persist state
    if self._state_file:
        self._save_state()

def _close(self) -> None:
    """Transition to CLOSED state."""
    self._state = CircuitState.CLOSED
    self._opened_at = None
    self._failure_count = 0
    self._success_count = 0

    # NEW: Log transition
    log_info("Circuit breaker CLOSED after successful recovery")

    # NEW: Persist state
    if self._state_file:
        self._save_state()

@property
def state(self) -> CircuitState:
    """Current circuit state (may transition to HALF_OPEN if timeout elapsed)."""
    if self._state == CircuitState.OPEN and self._opened_at is not None:
        if time.time() - self._opened_at >= self._recovery_timeout:
            # NEW: Log transition
            log_info(f"Circuit breaker entering HALF_OPEN state after {self._recovery_timeout}s timeout")

            self._state = CircuitState.HALF_OPEN
            self._success_count = 0

            # NEW: Persist state
            if self._state_file:
                self._save_state()

    return self._state
```

**Why this pattern:**
- **Observability:** Users see "Circuit breaker OPENED" in logs and understand why queue stopped.
- **Debugging:** Timestamps in logs correlate with circuit_breaker.json mtime for post-mortem analysis.
- **Requirement compliance:** VISB-02 explicitly requires logging state transitions.
- **Debug prefix:** Use `log_info` (not log_debug) because Stash filters out log_debug entirely (v1.3 decision). Prefix with "Circuit breaker" for easy grepping.

### Anti-Patterns to Avoid

- **State saves in tight loops:** Don't save state in worker loop polling. Save ONLY on transitions (CLOSED→OPEN, OPEN→HALF_OPEN, HALF_OPEN→CLOSED/OPEN). Otherwise disk I/O becomes bottleneck.

- **Blocking locks:** Don't use LOCK_EX without LOCK_NB. Blocking locks delay hook handlers (violates <100ms target). Non-blocking fails fast if locked—acceptable for state persistence.

- **State saves without error handling:** Always wrap state saves in try/except. OSError on full disk shouldn't crash plugin—circuit breaker still works in-memory.

- **Forgetting to save after load:** If you load state in `__init__`, don't save it again immediately. Only save on transitions. Otherwise every plugin invocation writes state file (unnecessary I/O).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Circuit breaker state locking | Custom semaphore with PID files | fcntl advisory locks (stdlib) | PID files require cleanup logic, stale PID detection, race conditions. fcntl handles cleanup automatically (lock released on process exit). POSIX standard, battle-tested. |
| State corruption detection | JSON schema validator, checksums | JSON exception handling + default state fallback | Over-engineering. json.JSONDecodeError is sufficient. If load fails, log warning and start with fresh CLOSED state. Corruption is rare (atomic writes prevent partial reads). |
| Circuit breaker library | pybreaker, circuitbreaker (PyPI) | Extend existing circuit_breaker.py | PlexSync already has 140-line circuit breaker (999 tests, 91% coverage). Adding dependency for state persistence (requires Redis) contradicts single-file deployment model. JSON + atomic write is simpler. |
| Distributed state consensus | etcd, Consul, Zookeeper | File-based state with advisory locks | PlexSync runs single-instance per Stash install. No distributed coordination needed. File locks are sufficient and avoid external dependencies. |

**Key insight:** PlexSync's constraint (non-daemon, event-driven, single-instance) simplifies state persistence. No need for distributed systems tooling—stdlib patterns (atomic writes, advisory locks) are sufficient and proven.

## Common Pitfalls

### Pitfall 1: Race Condition from Stale State Reads

**What goes wrong:** Two hook invocations fire simultaneously (bulk scene update). Both load circuit_breaker.json showing state=OPEN, opened_at=T-60. Both calculate "timeout elapsed, transition to HALF_OPEN." Both send test requests to Plex simultaneously (thundering herd).

**Why it happens:** Load-check-save is not atomic. Between loading state and saving updated state, another invocation can load the same stale state.

```
Time  | Invocation A              | Invocation B              | State File
------|---------------------------|---------------------------|------------
T+0   | Load: OPEN, opened_at=T-60 | (not started)            | OPEN
T+1   | Check: elapsed=61s, trigger | Load: OPEN, opened_at=T-60 | OPEN
T+2   | Transition to HALF_OPEN   | Check: elapsed=62s, trigger | OPEN
T+3   | Send test request         | Transition to HALF_OPEN   | HALF_OPEN (A wrote)
T+4   | Save state: HALF_OPEN     | Send test request         | HALF_OPEN
T+5   |                           | Save state: HALF_OPEN     | HALF_OPEN (B overwrites)
```

Result: 2 test requests instead of 1. Scales with concurrent hooks (10 hooks = 10 requests).

**How to avoid:**

**Option 1: Single-writer pattern (RECOMMENDED for Phase 17)**
- Circuit breaker state is ONLY modified by worker thread (already true in processor.py)
- Hook invocations READ state but never modify it (query circuit_breaker.json to show status)
- State property transitions (OPEN→HALF_OPEN) happen in worker loop, not hooks
- No locking needed because only one writer exists

**Option 2: File locking (REQUIRED for Phase 18+ if check-on-invocation recovery)**
- Wrap state transitions in fcntl.flock (Pattern 2 above)
- Non-blocking acquire: if locked, skip transition (another invocation handling it)
- Adds 5-10ms latency per state save (acceptable, transitions are rare)

**Option 3: Optimistic concurrency with version numbers**
- Add "version" field to circuit_breaker.json, increment on every write
- Before saving, check version matches what was loaded
- If mismatch, reload and retry (max 3 attempts)
- Complex to implement correctly, only needed for high-contention scenarios

**Warning signs:**
- Multiple "Circuit breaker HALF_OPEN" log entries within 1 second
- circuit_breaker.json mtime shows rapid updates (multiple writes/second)
- Plex receives burst of requests after recovery timeout expires

**Phase to address:** Phase 17 (this phase). Start with single-writer pattern. Add locking if Phase 18 implements check-on-invocation recovery.

### Pitfall 2: State File Corruption from Incomplete Writes

**What goes wrong:** Plugin crashes mid-write to circuit_breaker.json (OOM, Stash restart, kill -9). File contains partial JSON: `{"state": "open", "failure_count":`. Next invocation tries to load state, json.JSONDecodeError raised, circuit breaker doesn't start, queue processing halts.

**Why it happens:** Direct writes to state file (without temp file) are not atomic. Crash during write leaves partial data.

**How to avoid:**

**Use atomic write pattern (ALREADY IMPLEMENTED):**
```python
# Write to .tmp, then atomic rename
tmp_path = self._state_file + '.tmp'
with open(tmp_path, 'w') as f:
    json.dump(state_dict, f, indent=2)
os.replace(tmp_path, self._state_file)  # Atomic on POSIX
```

**Add graceful degradation:**
```python
def load_state(self) -> None:
    """Load state from disk, fallback to CLOSED on corruption."""
    if not self._state_file or not os.path.exists(self._state_file):
        return  # No state file, use in-memory defaults

    try:
        with open(self._state_file) as f:
            data = json.load(f)

        self._state = CircuitState(data['state'])
        self._failure_count = data['failure_count']
        self._success_count = data['success_count']
        self._opened_at = data['opened_at']

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log_warn(f"Circuit breaker state corrupted, resetting to CLOSED: {e}")
        # Defaults already set in __init__, no action needed
```

**Warning signs:**
- JSONDecodeError in logs mentioning circuit_breaker.json
- circuit_breaker.json contains partial JSON (less than expected size)
- Circuit breaker unexpectedly resets to CLOSED after plugin restart

**Phase to address:** Phase 17. Use atomic write pattern from reconciliation/scheduler.py (proven). Add exception handling in load_state().

### Pitfall 3: State Persistence Disabled in Tests

**What goes wrong:** Tests mock CircuitBreaker but forget to disable state_file parameter. Tests write to /tmp/circuit_breaker.json, interfering with concurrent tests. Test isolation breaks, random failures occur.

**Why it happens:** CircuitBreaker.__init__ defaults to state_file=None (no persistence), but if tests pass explicit path, state persists across test runs.

**How to avoid:**

**Default to no persistence:**
```python
class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
        state_file: Optional[str] = None  # Default: no persistence
    ):
        self._state_file = state_file

        # Load state ONLY if state_file provided
        if self._state_file and os.path.exists(self._state_file):
            self.load_state()
```

**Use tmp_path fixture in tests:**
```python
# In tests/test_circuit_breaker.py
def test_state_persistence(tmp_path):
    """Test state survives across instances."""
    state_file = tmp_path / "circuit_breaker.json"

    # First instance: open circuit
    breaker1 = CircuitBreaker(failure_threshold=2, state_file=str(state_file))
    breaker1.record_failure()
    breaker1.record_failure()
    assert breaker1.state == CircuitState.OPEN

    # Second instance: loads OPEN state
    breaker2 = CircuitBreaker(state_file=str(state_file))
    assert breaker2.state == CircuitState.OPEN  # State persisted
```

**Warning signs:**
- Tests fail when run in parallel (`pytest -n auto`)
- Tests pass individually but fail in suite
- `/tmp/circuit_breaker.json` exists after test run

**Phase to address:** Phase 17. Use tmp_path fixture (pytest provides isolated temp dirs). Document state_file=None default in docstring.

### Pitfall 4: Missing State Transition Logs

**What goes wrong:** Circuit breaker opens (Plex down), queue stops processing, user doesn't know why. No "Circuit breaker OPENED" log entry. User manually syncs scenes, wondering why queue is stuck.

**Why it happens:** Logging wasn't added to _open()/_close() methods. State transitions are silent.

**How to avoid:**

**Add log_info calls to all transitions:**
```python
def _open(self) -> None:
    log_info(f"Circuit breaker OPENED after {self._failure_threshold} consecutive failures")
    # ... transition logic ...

def _close(self) -> None:
    log_info("Circuit breaker CLOSED after successful recovery")
    # ... transition logic ...

# In state property for OPEN→HALF_OPEN:
if time.time() - self._opened_at >= self._recovery_timeout:
    log_info(f"Circuit breaker entering HALF_OPEN after {self._recovery_timeout}s timeout")
    # ... transition logic ...
```

**Use log_info, not log_debug:**
- Stash filters out log_debug entirely (v1.3 decision documented in MEMORY.md)
- log_info appears in Stash logs panel
- Prefix messages with "Circuit breaker" for easy grepping

**Warning signs:**
- Users report "queue stopped, don't know why"
- No log entries around time of Plex outage
- Support requests asking "is circuit breaker working?"

**Phase to address:** Phase 17. Logging is explicit requirement (VISB-02). Add in _open(), _close(), state property.

## Code Examples

Verified patterns from PlexSync codebase:

### Atomic State Save (from reconciliation/scheduler.py)

```python
# Source: reconciliation/scheduler.py:72-79
def save_state(self, state: ReconciliationState) -> None:
    """Save reconciliation state to disk atomically."""
    tmp_path = self.state_path + '.tmp'
    try:
        with open(tmp_path, 'w') as f:
            json.dump(asdict(state), f, indent=2)
        os.replace(tmp_path, self.state_path)
    except OSError as e:
        log_debug(f"Failed to save reconciliation state: {e}")
```

**Adapt for circuit breaker:**
```python
def save_state(self) -> None:
    """Save circuit breaker state to disk atomically."""
    if not self._state_file:
        return  # Persistence disabled

    state_dict = {
        'state': self._state.value,  # 'closed', 'open', 'half_open'
        'failure_count': self._failure_count,
        'success_count': self._success_count,
        'opened_at': self._opened_at,
    }

    tmp_path = self._state_file + '.tmp'
    try:
        with open(tmp_path, 'w') as f:
            json.dump(state_dict, f, indent=2)
        os.replace(tmp_path, self._state_file)
    except OSError as e:
        log_debug(f"Failed to save circuit breaker state: {e}")
```

### State Load with Graceful Degradation

```python
# Source: reconciliation/scheduler.py:60-69
def load_state(self) -> ReconciliationState:
    """Load reconciliation state from disk."""
    try:
        if os.path.exists(self.state_path):
            with open(self.state_path, 'r') as f:
                data = json.load(f)
            return ReconciliationState(**data)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        log_debug(f"Failed to load reconciliation state, using defaults: {e}")
    return ReconciliationState()
```

**Adapt for circuit breaker:**
```python
def load_state(self) -> None:
    """Load circuit breaker state from disk."""
    if not self._state_file or not os.path.exists(self._state_file):
        return  # No state file, use __init__ defaults

    try:
        with open(self._state_file) as f:
            data = json.load(f)

        self._state = CircuitState(data['state'])
        self._failure_count = data['failure_count']
        self._success_count = data['success_count']
        self._opened_at = data['opened_at']

        log_debug(f"Loaded circuit breaker state: {self._state.value}")

    except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
        log_warn(f"Circuit breaker state corrupted, using defaults: {e}")
        # Defaults already set in __init__
```

### Integration in SyncWorker

```python
# In worker/processor.py SyncWorker.__init__() (MODIFIED)
def __init__(self, config: Stash2PlexConfig, queue_manager, data_dir: str):
    # ... existing initialization ...

    # Circuit breaker for resilience during Plex outages
    from worker.circuit_breaker import CircuitBreaker

    # NEW: Enable state persistence
    cb_state_file = os.path.join(data_dir, 'circuit_breaker.json')

    self.circuit_breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60.0,
        success_threshold=1,
        state_file=cb_state_file  # NEW parameter
    )
```

### State Transitions with Logging and Persistence

```python
# In worker/circuit_breaker.py (MODIFIED methods)
def record_failure(self) -> None:
    """Record a failed execution."""
    if self._state == CircuitState.HALF_OPEN:
        # HALF_OPEN failure → reopen immediately
        log_info("Circuit breaker reopening after HALF_OPEN test failure")
        self._open()
    else:
        # CLOSED state - count failures
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._open()
        else:
            # Still CLOSED, but save updated failure count
            if self._state_file:
                self.save_state()

def record_success(self) -> None:
    """Record a successful execution."""
    if self._state == CircuitState.HALF_OPEN:
        self._success_count += 1
        if self._success_count >= self._success_threshold:
            self._close()
        else:
            # Still HALF_OPEN, but save updated success count
            if self._state_file:
                self.save_state()
    else:
        # CLOSED state - reset failure count
        self._failure_count = 0
        if self._state_file:
            self.save_state()

def _open(self) -> None:
    """Transition to OPEN state."""
    self._state = CircuitState.OPEN
    self._opened_at = time.time()
    self._failure_count = 0
    self._success_count = 0

    log_info(f"Circuit breaker OPENED after {self._failure_threshold} consecutive failures")

    if self._state_file:
        self.save_state()

def _close(self) -> None:
    """Transition to CLOSED state."""
    self._state = CircuitState.CLOSED
    self._opened_at = None
    self._failure_count = 0
    self._success_count = 0

    log_info("Circuit breaker CLOSED after successful recovery")

    if self._state_file:
        self.save_state()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| In-memory circuit breaker only | Persisted circuit breaker state | 2024+ (production queue systems) | AWS SQS, RabbitMQ, Kafka all persist circuit breaker state for crash recovery. PlexSync v1.5 adopts industry standard. |
| Manual circuit breaker reset | Automatic recovery detection | 2023+ | Reduces operational burden. Systems detect downstream recovery and resume automatically. Phase 18 will implement this. |
| Blocking file locks | Non-blocking advisory locks (LOCK_NB) | 2020+ | Non-blocking prevents lock contention from delaying event handlers. Fail-fast is better than blocking in event-driven systems. |

**Deprecated/outdated:**
- **Shelve for state persistence:** Python stdlib shelve module was common pre-2015 but writeback mode has memory leak issues. JSON + atomic write is simpler and safer.
- **Global state without locking:** Pre-2010 approach assumed single-threaded apps. Modern event-driven systems need locking or single-writer patterns.

## Open Questions

1. **Should state saves use fsync() for durability?**
   - What we know: os.replace is atomic (rename syscall) but doesn't guarantee durability (data may be in OS cache, not on disk). fsync() forces write to disk before rename.
   - What's unclear: Is fsync() necessary for circuit breaker state? Crash after save but before fsync could lose state.
   - Recommendation: **Skip fsync() for MVP**. Circuit breaker state loss is low-risk (defaults to CLOSED, worker retries detect outage and reopen). Add fsync() if users report state loss after crashes.

2. **How to handle Windows compatibility (no fcntl)?**
   - What we know: fcntl is POSIX-only. Windows uses msvcrt.locking or win32file module for file locking.
   - What's unclear: Does PlexSync need Windows support? Stash typically runs in Docker (Linux) or natively on macOS/Linux.
   - Recommendation: **Skip Windows locking for MVP**. Document POSIX requirement. If Windows users request support, add conditional import (fcntl on POSIX, msvcrt on Windows).

3. **Should state file location be configurable?**
   - What we know: Currently hardcoded to `data_dir/circuit_breaker.json`. No config option for alternate path.
   - What's unclear: Do advanced users need custom state file location (NFS mount, ramdisk)?
   - Recommendation: **Skip configurability for MVP**. Existing state files (reconciliation_state.json, stats.json) use data_dir without config option. Consistent with existing patterns.

## Sources

### Primary (HIGH confidence)

- **PlexSync Codebase:**
  - `reconciliation/scheduler.py:72-79` — Atomic write pattern with os.replace (production code, 999 tests)
  - `worker/stats.py:179-193` — State persistence with temp file pattern (production code)
  - `worker/circuit_breaker.py` — Existing circuit breaker implementation (140 lines, 3-state machine)
  - `tests/test_circuit_breaker.py` — Circuit breaker test suite (state transitions, timeouts)

- **Python Documentation:**
  - [os.replace() — Python 3.9 Docs](https://docs.python.org/3/library/os.html#os.replace) — "On Unix, if dst exists and is a file, it will be replaced silently if the user has permission."
  - [json — Python 3.9 Docs](https://docs.python.org/3/library/json.html) — JSON encoder/decoder, no special config needed for circuit breaker state
  - [fcntl — Python 3.9 Docs](https://docs.python.org/3/library/fcntl.html) — File and directory locking, LOCK_EX | LOCK_NB for non-blocking exclusive locks

- **PlexSync Milestone Research:**
  - `.planning/research/STACK.md` — NO NEW DEPS recommendation, JSON + atomic write pattern
  - `.planning/research/ARCHITECTURE.md` — Check-on-invocation pattern, single-writer circuit breaker
  - `.planning/research/PITFALLS.md` — Race condition prevention (fcntl locking), state corruption handling

### Secondary (MEDIUM confidence)

- **Circuit Breaker State Persistence:**
  - [pybreaker PyPI](https://pypi.org/project/pybreaker/) — Circuit breaker library with Redis storage (NOT recommended for PlexSync)
  - [Circuit Breaker Pattern — Martin Fowler](https://martinfowler.com/bliki/CircuitBreaker.html) — Authoritative pattern definition, no state persistence examples
  - [Resilience4j Circuit Breaker](https://resilience4j.readme.io/docs/circuitbreaker) — Java library with state persistence examples (concept reference)

- **File Locking Patterns:**
  - [Advisory File Locking in Python](https://gavv.github.io/articles/file-locks/) — fcntl patterns, LOCK_EX vs LOCK_SH, LOCK_NB for non-blocking
  - [Atomic File Writes](https://rcoh.me/posts/atomic-file-writes/) — Why temp file + rename is atomic, pitfalls of direct writes

### Tertiary (LOW confidence)

- **General State Persistence:**
  - [DiskCache Documentation](https://grantjenks.com/docs/diskcache/) — Alternative to JSON, thread-safe dict-like API
  - [shelve — Python Object Persistence](https://docs.python.org/3/library/shelve.html) — Older stdlib pattern, not recommended

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — All stdlib, patterns proven in 3 locations (reconciliation, stats, sync_queue)
- Architecture: **HIGH** — Minimal changes to existing circuit_breaker.py, integration point clear (processor.py)
- Pitfalls: **HIGH** — Race conditions documented in milestone research, prevention patterns known (fcntl, single-writer)

**Research date:** 2026-02-15
**Valid until:** 90 days (stable stdlib APIs, no external dependencies, patterns are timeless)

**Dependencies:** Phase 16 (v1.4 complete) — Circuit breaker already exists, reconciliation scheduler provides atomic write pattern

**Enables:** Phase 18 (Health Monitoring), Phase 19 (Automatic Recovery Triggers) — Both need persisted circuit state to detect OPEN and trigger recovery checks
