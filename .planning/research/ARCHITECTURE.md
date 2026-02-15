# Architecture Research: Outage Resilience Integration

**Domain:** Outage resilience for event-driven Stash plugin architecture
**Researched:** 2026-02-15
**Confidence:** HIGH

## Executive Summary

PlexSync's outage resilience features must integrate with a **non-daemon, event-driven architecture** where the plugin exits after each invocation. The check-on-invocation pattern (proven in v1.4 reconciliation) extends naturally to recovery detection. New components focus on state persistence and health tracking, while existing components (circuit breaker, backoff, queue) require minimal modification.

**Key architectural decisions:**
1. **Recovery detection uses check-on-invocation pattern** — same as auto-reconciliation scheduler
2. **Circuit breaker state persists to disk** — survives process restarts
3. **Health check is stateless** — no background monitoring needed
4. **Recovery trigger is explicit** — check on next hook invocation, not async polling

## Current Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Entry Point (Stash2Plex.py)               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ main() → initialize() → maybe_auto_reconcile()      │    │
│  │   ↓                                                  │    │
│  │ handle_hook() or handle_task()                      │    │
│  └──────────────┬──────────────────────────────────────┘    │
│                 │                                            │
├─────────────────┴────────────────────────────────────────────┤
│                    Event Handlers Layer                      │
│  ┌──────────────────┐          ┌──────────────────────┐     │
│  │ hooks/handlers   │          │ Task Dispatch        │     │
│  │ - Scene update   │          │ - reconcile_all      │     │
│  │ - Validation     │          │ - process_queue      │     │
│  │ - Enqueue (<100ms)│         │ - queue_status       │     │
│  └────────┬─────────┘          └──────────┬───────────┘     │
│           │                               │                 │
├───────────┴───────────────────────────────┴──────────────────┤
│                    Processing Layer                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              worker/processor.py                     │    │
│  │  • Daemon thread during invocation                  │    │
│  │  • Circuit breaker (in-memory)                      │    │
│  │  • Exponential backoff with jitter                  │    │
│  │  • Dies when process exits                          │    │
│  └───────────────────┬─────────────────────────────────┘    │
│                      │                                       │
├──────────────────────┴───────────────────────────────────────┤
│                    State Persistence Layer                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Queue (SQLite)│  │ Sync Timestamps│  │ Reconciliation│    │
│  │ persist-queue│  │ (JSON)         │  │ State (JSON)  │    │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘

External Services:
┌──────────┐                    ┌──────────┐
│  Stash   │ ←── GraphQL ────   │   Plex   │
│  (GQL)   │                    │ (plexapi) │
└──────────┘                    └──────────┘
```

### Key Constraint: Invocation Lifecycle

**NOT a long-running daemon:**
- Plugin invoked per-event (hook fires, task selected)
- Process exits after handling event
- Worker thread runs during invocation, dies on exit
- State survives via disk persistence (SQLite queue, JSON files)

**Check-on-invocation pattern** (proven in v1.4 reconciliation):
1. On every plugin invocation: read JSON state file
2. Check if action is due (time-based, condition-based)
3. If due: execute action, update state
4. Continue with normal processing

## Outage Resilience Architecture

### System Overview with Resilience Features

```
┌─────────────────────────────────────────────────────────────┐
│                    Entry Point (Stash2Plex.py)               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ main() → initialize()                                │    │
│  │   ↓                                                  │    │
│  │ maybe_auto_reconcile()  ← EXISTING                  │    │
│  │ maybe_recovery_trigger() ← NEW (check-on-invocation)│    │
│  │   ↓                                                  │    │
│  │ handle_hook() or handle_task()                      │    │
│  └──────────────┬──────────────────────────────────────┘    │
│                 │                                            │
├─────────────────┴────────────────────────────────────────────┤
│                    Event Handlers Layer                      │
│  ┌──────────────────┐          ┌──────────────────────┐     │
│  │ hooks/handlers   │          │ Task Dispatch        │     │
│  │ (no changes)     │          │ + health_check ← NEW │     │
│  └────────┬─────────┘          └──────────┬───────────┘     │
│           │                               │                 │
├───────────┴───────────────────────────────┴──────────────────┤
│                    Processing Layer                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              worker/processor.py                     │    │
│  │  • Circuit breaker (NOW PERSISTED) ← MODIFIED       │    │
│  │  • Exponential backoff (no change)                  │    │
│  │  • Worker loop checks CB before processing          │    │
│  └───────────────────┬─────────────────────────────────┘    │
│                      │                                       │
├──────────────────────┴───────────────────────────────────────┤
│                    Resilience Components (NEW)               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │       resilience/recovery_detector.py                │    │
│  │  • RecoveryDetector: check if Plex recovered         │    │
│  │  • Uses plex/client.py health check                 │    │
│  │  • Lightweight: single HTTP request                 │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │       resilience/recovery_scheduler.py               │    │
│  │  • RecoveryScheduler: check-on-invocation pattern    │    │
│  │  • Loads recovery_state.json                        │    │
│  │  • Decides if health check is due                   │    │
│  │  • Records last check time, last failure time       │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │       plex/health.py (NEW)                           │    │
│  │  • check_plex_health(): /:/ping endpoint            │    │
│  │  • Returns (is_healthy: bool, latency_ms: float)    │    │
│  │  • Reuses PlexClient with short timeout             │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                    State Persistence Layer                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Queue (SQLite)│  │ CB State (JSON)│  │ Recovery State│    │
│  │ (existing)   │  │ ← NEW          │  │ (JSON) ← NEW  │    │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ Sync Timestamps│  │ Reconciliation│                      │
│  │ (existing)   │  │ State (existing)│                     │
│  └──────────────┘  └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

## Component Integration Points

### New Components

#### 1. `resilience/recovery_detector.py` (NEW)

**Responsibility:** Detect Plex recovery after an outage

**Interface:**
```python
class RecoveryDetector:
    def __init__(self, config: Stash2PlexConfig, data_dir: str):
        self.config = config
        self.data_dir = data_dir
        self._scheduler = RecoveryScheduler(data_dir)

    def check_recovery(self) -> tuple[bool, str]:
        """Check if Plex has recovered from outage.

        Returns:
            (recovered: bool, reason: str)
            - (True, "Plex is healthy") if recovered
            - (False, "Circuit breaker not OPEN") if no outage detected
            - (False, "Plex still down") if health check fails
        """
```

**Integration:**
- Called from `maybe_recovery_trigger()` in `Stash2Plex.py`
- Uses `plex/health.py` for health checking
- Reads/writes `recovery_state.json` via `RecoveryScheduler`
- Loads circuit breaker state to check if recovery is relevant

**Data flow:**
1. Load circuit breaker state (if OPEN → proceed, else skip)
2. Check scheduler: is health check due?
3. If due: run health check via `plex/health.py`
4. If healthy: return True (trigger recovery actions)
5. Update scheduler state with check result

---

#### 2. `resilience/recovery_scheduler.py` (NEW)

**Responsibility:** Track recovery check timing (check-on-invocation pattern)

**Interface:**
```python
@dataclass
class RecoveryState:
    """Persisted state for recovery checking."""
    last_failure_time: float = 0.0      # When circuit breaker last opened
    last_check_time: float = 0.0        # Last health check attempt
    last_check_result: bool = False     # Last health check result
    consecutive_successes: int = 0      # Successes since last failure

class RecoveryScheduler:
    STATE_FILE = 'recovery_state.json'

    def is_check_due(self, now: float, check_interval: float) -> bool:
        """Check if health check should run based on interval.

        Args:
            now: Current time (time.time())
            check_interval: Seconds between checks (default: 60)

        Returns:
            True if check should run
        """

    def record_check(self, result: bool, now: float) -> None:
        """Record health check result."""
```

**Integration:**
- Used by `RecoveryDetector`
- Persists to `data_dir/recovery_state.json`
- Pattern matches `reconciliation/scheduler.py` (proven design)

---

#### 3. `plex/health.py` (NEW)

**Responsibility:** Lightweight Plex health checking

**Interface:**
```python
def check_plex_health(
    client: PlexClient,
    timeout: float = 5.0
) -> tuple[bool, float]:
    """Check if Plex server is responding.

    Uses /:/ping endpoint (lightweight, no auth needed).

    Args:
        client: PlexClient instance
        timeout: Request timeout in seconds

    Returns:
        (is_healthy: bool, latency_ms: float)
    """
```

**Integration:**
- Called by `RecoveryDetector.check_recovery()`
- Uses existing `plex/client.py` PlexClient
- Independent of circuit breaker (uses fresh client with short timeout)

**Implementation notes:**
- Uses `requests.get(f"{plex_url}/:/ping", timeout=timeout)`
- Success: HTTP 200 and response contains "pong"
- Measures latency: `time.perf_counter()` before/after
- Returns `(False, 0.0)` on timeout/connection error

---

### Modified Components

#### 4. `worker/circuit_breaker.py` (MODIFIED)

**Current state:** In-memory only (state lost on process restart)

**Changes:**
```python
class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
        state_file: Optional[str] = None  # ← NEW: path to JSON state
    ):
        # ... existing fields ...
        self._state_file = state_file

        # Load persisted state if file provided
        if self._state_file and os.path.exists(self._state_file):
            self._load_state()

    def _save_state(self) -> None:
        """Persist state to disk (atomic write)."""
        if not self._state_file:
            return

        state_data = {
            'state': self._state.value,
            'failure_count': self._failure_count,
            'success_count': self._success_count,
            'opened_at': self._opened_at,
        }
        # Atomic write: .tmp → rename
        tmp = self._state_file + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state_data, f)
        os.replace(tmp, self._state_file)

    def _load_state(self) -> None:
        """Load state from disk."""
        with open(self._state_file) as f:
            data = json.load(f)
        self._state = CircuitState(data['state'])
        self._failure_count = data['failure_count']
        self._success_count = data['success_count']
        self._opened_at = data['opened_at']
```

**Integration:**
- Modified in `worker/processor.py` `SyncWorker.__init__()`:
  ```python
  cb_state_file = os.path.join(data_dir, 'circuit_breaker.json')
  self.circuit_breaker = CircuitBreaker(
      failure_threshold=5,
      recovery_timeout=60.0,
      success_threshold=1,
      state_file=cb_state_file  # ← NEW
  )
  ```
- Save state on every transition: `record_success()`, `record_failure()`, `_open()`, `_close()`

**Why persist:**
- Circuit breaker OPEN state survives process restart
- Recovery detector can check "is CB OPEN?" without needing worker running
- Prevents repeated retry exhaustion after plugin restart

---

#### 5. `Stash2Plex.py` (MODIFIED)

**Changes:** Add recovery check after reconciliation check

```python
def maybe_recovery_trigger():
    """Check if Plex has recovered from outage and trigger queue drain.

    Called on every plugin invocation. Uses check-on-invocation pattern:
    1. Load circuit breaker state
    2. If OPEN: check if Plex is healthy again
    3. If recovered: close circuit breaker, log recovery
    4. Worker will drain queue on next job processing

    This is lightweight (reads one JSON file) and only runs health
    check when circuit is OPEN.
    """
    if not config or not queue_manager:
        return

    try:
        data_dir = get_plugin_data_dir()
        from resilience.recovery_detector import RecoveryDetector

        detector = RecoveryDetector(config, data_dir)
        recovered, reason = detector.check_recovery()

        if recovered:
            log_info(f"Plex recovery detected: {reason}")
            # Circuit breaker state already updated by detector
            # Worker will resume processing on next queue poll
        else:
            log_trace(f"Recovery check: {reason}")

    except Exception as e:
        log_warn(f"Recovery check failed: {e}")

def main():
    # ... existing initialization ...

    # Auto-reconciliation check (runs on every invocation)
    maybe_auto_reconcile()

    # Recovery trigger check (runs on every invocation)
    maybe_recovery_trigger()  # ← NEW

    # ... rest of main() unchanged ...
```

**Integration:**
- Runs after `maybe_auto_reconcile()`, before event handling
- Reuses `get_plugin_data_dir()` for state files
- No impact on hook handler latency (check is <10ms when CB is CLOSED)

---

#### 6. Task Dispatch (MODIFIED)

**Changes:** Add `health_check` task mode

```python
_MANAGEMENT_HANDLERS = {
    # ... existing handlers ...
    'health_check': lambda args: handle_health_check(),  # ← NEW
}

def handle_health_check():
    """Manual Plex health check task.

    Reports:
    - Current circuit breaker state
    - Plex connectivity (via /:/ping)
    - Last recovery check time
    - Queue size (items waiting)
    """
    try:
        data_dir = get_plugin_data_dir()

        # 1. Circuit breaker state
        cb_state_path = os.path.join(data_dir, 'circuit_breaker.json')
        if os.path.exists(cb_state_path):
            with open(cb_state_path) as f:
                cb_data = json.load(f)
            cb_state = cb_data.get('state', 'UNKNOWN')
            log_info(f"Circuit breaker: {cb_state}")
        else:
            log_info("Circuit breaker: CLOSED (no state file)")

        # 2. Plex health check
        from plex.client import PlexClient
        from plex.health import check_plex_health

        client = PlexClient(
            url=config.plex_url,
            token=config.plex_token
        )
        is_healthy, latency_ms = check_plex_health(client)
        if is_healthy:
            log_info(f"Plex health: OK ({latency_ms:.0f}ms)")
        else:
            log_warn("Plex health: UNREACHABLE")

        # 3. Recovery state
        from resilience.recovery_scheduler import RecoveryScheduler
        scheduler = RecoveryScheduler(data_dir)
        state = scheduler.load_state()
        if state.last_check_time > 0:
            last_check = datetime.fromtimestamp(state.last_check_time)
            log_info(f"Last recovery check: {last_check.strftime('%Y-%m-%d %H:%M:%S')}")
            log_info(f"Consecutive successes: {state.consecutive_successes}")
        else:
            log_info("No recovery checks recorded")

        # 4. Queue size
        queue = queue_manager.get_queue()
        pending = queue.size
        log_info(f"Queue size: {pending} items")

        if pending > 0 and cb_state == 'OPEN':
            log_warn(f"{pending} items waiting in queue while circuit breaker is OPEN")
        elif pending > 0:
            log_info(f"{pending} items will be processed by worker")

    except Exception as e:
        log_error(f"Health check failed: {e}")
        import traceback
        traceback.print_exc()
```

**Integration:**
- Add to `Stash2Plex.yml` task list: `health_check` mode
- UI-accessible: user can trigger from Stash Tasks panel
- Reports current system state without modifying anything

---

## Data Flow Changes

### Recovery Detection Flow (NEW)

```
[Hook Invocation]
    ↓
[main() → maybe_recovery_trigger()]
    ↓
[RecoveryScheduler.is_check_due()?]
    │
    ├─ NO → skip (log_trace)
    │
    └─ YES → [Load circuit_breaker.json]
              │
              ├─ CB is CLOSED → skip (no outage)
              │
              └─ CB is OPEN → [check_plex_health()]
                               │
                               ├─ HEALTHY → [Close circuit breaker]
                               │             [Save CB state]
                               │             [Log recovery]
                               │             [Worker resumes on next poll]
                               │
                               └─ UNHEALTHY → [Update recovery_state.json]
                                              [Log still down]
```

**Key properties:**
- **Lightweight:** Only health check when CB is OPEN (rare)
- **Stateless health check:** Single HTTP ping, no side effects
- **Explicit trigger:** No background polling, check on next hook
- **Survives restarts:** CB state persists, recovery detection picks up where it left off

---

### Circuit Breaker State Persistence (MODIFIED)

**Before (v1.4):**
```
[Worker Loop]
    ↓
[Process job] → [Error] → [circuit_breaker.record_failure()]
                           ↓
                         [In-memory state update]
                         [State lost on process exit]
```

**After (v1.5+):**
```
[Worker Loop]
    ↓
[Process job] → [Error] → [circuit_breaker.record_failure()]
                           ↓
                         [In-memory state update]
                         [Save to circuit_breaker.json] ← NEW
                           ↓
                         [Atomic write (tmp → rename)]
```

**On worker restart:**
```
[SyncWorker.__init__()]
    ↓
[CircuitBreaker(state_file=...)]
    ↓
[Load circuit_breaker.json] ← NEW
    ↓
[Restore state (OPEN/CLOSED/HALF_OPEN)]
```

**Integration with recovery:**
```
[maybe_recovery_trigger()]
    ↓
[Load circuit_breaker.json]
    ↓
[Check: state == 'OPEN'?]
    │
    └─ YES → [Run health check]
              [If healthy: update state to CLOSED]
```

---

## File Structure

### New Files

```
resilience/
├── __init__.py
├── recovery_detector.py      # RecoveryDetector class
├── recovery_scheduler.py     # RecoveryScheduler + RecoveryState dataclass
└── README.md                 # Component documentation

plex/
└── health.py                 # check_plex_health() function

tests/resilience/
├── __init__.py
├── test_recovery_detector.py
├── test_recovery_scheduler.py
└── test_integration.py

tests/plex/
└── test_health.py
```

### Modified Files

```
worker/
└── circuit_breaker.py        # Add state_file parameter, save/load methods

Stash2Plex.py                 # Add maybe_recovery_trigger(), health_check task

Stash2Plex.yml                # Add health_check task mode
```

### State Files (Runtime)

```
data/
├── circuit_breaker.json      # Circuit breaker state (NEW)
│   {
│     "state": "OPEN",
│     "failure_count": 5,
│     "success_count": 0,
│     "opened_at": 1739583412.5
│   }
│
├── recovery_state.json       # Recovery check state (NEW)
│   {
│     "last_failure_time": 1739583412.5,
│     "last_check_time": 1739583472.3,
│     "last_check_result": false,
│     "consecutive_successes": 0
│   }
│
├── reconciliation_state.json # Existing (unchanged)
├── sync_timestamps.json      # Existing (unchanged)
└── queue/                    # Existing (unchanged)
    └── [SQLite files]
```

---

## Build Order (Dependency-Based)

### Phase 1: Circuit Breaker Persistence (Foundation)

**Goal:** Make circuit breaker state survive restarts

**Tasks:**
1. Add `state_file` parameter to `CircuitBreaker.__init__()`
2. Implement `_save_state()` and `_load_state()` methods
3. Call `_save_state()` in `record_success()`, `record_failure()`, `_open()`, `_close()`
4. Update `SyncWorker.__init__()` to pass `state_file` path
5. Write tests: state persistence, atomic writes, corrupt file handling

**Deliverable:** Circuit breaker state persists to `circuit_breaker.json`

**Dependencies:** None (self-contained)

---

### Phase 2: Health Check (Independent)

**Goal:** Lightweight Plex connectivity check

**Tasks:**
1. Create `plex/health.py`
2. Implement `check_plex_health(client, timeout)` using `/:/ping`
3. Write tests: healthy server, unreachable server, timeout, latency measurement
4. Add `health_check` task to task dispatch
5. Update `Stash2Plex.yml` with new task mode

**Deliverable:** Manual health check task available in Stash UI

**Dependencies:** None (uses existing `PlexClient`)

---

### Phase 3: Recovery Scheduler (State Management)

**Goal:** Track recovery check timing

**Tasks:**
1. Create `resilience/recovery_scheduler.py`
2. Define `RecoveryState` dataclass
3. Implement `RecoveryScheduler` (pattern matches `ReconciliationScheduler`)
4. Add `is_check_due()`, `record_check()`, `load_state()`, `save_state()`
5. Write tests: check-on-invocation logic, state persistence

**Deliverable:** Recovery scheduler manages check timing

**Dependencies:** None (standalone state manager)

---

### Phase 4: Recovery Detector (Integration)

**Goal:** Detect Plex recovery after outage

**Tasks:**
1. Create `resilience/recovery_detector.py`
2. Implement `RecoveryDetector.check_recovery()`
3. Integrate with `RecoveryScheduler` (check timing)
4. Integrate with `plex/health.py` (health checking)
5. Integrate with circuit breaker state loading
6. Write tests: recovery detected, still down, no outage, scheduler skips

**Deliverable:** Recovery detection logic complete

**Dependencies:**
- Phase 1 (circuit breaker persistence)
- Phase 2 (health check)
- Phase 3 (recovery scheduler)

---

### Phase 5: Entry Point Integration (Wiring)

**Goal:** Wire recovery detection into plugin lifecycle

**Tasks:**
1. Add `maybe_recovery_trigger()` to `Stash2Plex.py`
2. Call from `main()` after `maybe_auto_reconcile()`
3. Handle exceptions gracefully (log, don't crash plugin)
4. Write integration tests: full recovery flow, multiple invocations

**Deliverable:** Recovery detection runs on every plugin invocation

**Dependencies:**
- Phase 4 (recovery detector)

---

### Phase 6: Documentation & Testing

**Goal:** Production-ready resilience features

**Tasks:**
1. Write `resilience/README.md` documenting architecture
2. Add recovery detection examples to main README
3. Write end-to-end tests: outage → recovery → queue drain
4. Performance testing: check-on-invocation overhead (<10ms)
5. Update Stash plugin UI with health check instructions

**Deliverable:** Documented, tested, production-ready

**Dependencies:**
- Phase 5 (all components integrated)

---

## Architectural Patterns

### Pattern 1: Check-on-Invocation

**What:** On every plugin invocation, check if an action is due based on persisted state

**When to use:** Event-driven systems without long-running daemons

**Implementation:**
```python
def maybe_do_action():
    """Lightweight check that only runs action when due."""
    # 1. Load state (cheap: single JSON read)
    state = load_state_from_disk()

    # 2. Check condition (time-based, state-based)
    if not is_action_due(state):
        return  # Skip, action not needed yet

    # 3. Execute action (expensive operation)
    result = do_expensive_action()

    # 4. Update state (persist result)
    state.last_run = time.time()
    save_state_to_disk(state)
```

**Trade-offs:**
- **Pro:** No background threads/processes needed
- **Pro:** Survives process restarts (state is durable)
- **Pro:** Minimal overhead when action not due (<10ms)
- **Con:** Relies on invocations happening (quiet systems = delayed actions)
- **Con:** Not suitable for strict timing requirements (best-effort)

**PlexSync usage:**
- Auto-reconciliation (v1.4): check every invocation, run if interval elapsed
- Recovery detection (v1.5): check every invocation, run if CB is OPEN

---

### Pattern 2: Persisted Circuit Breaker

**What:** Circuit breaker state survives process restarts

**When to use:** Non-daemon systems that need resilience across invocations

**Implementation:**
```python
class CircuitBreaker:
    def __init__(self, state_file: Optional[str] = None):
        self._state_file = state_file
        if state_file and os.path.exists(state_file):
            self._load_state()

    def record_failure(self):
        # Update in-memory state
        self._failure_count += 1
        if self._failure_count >= self._threshold:
            self._open()

        # Persist to disk (atomic)
        self._save_state()

    def _save_state(self):
        if not self._state_file:
            return

        # Atomic write: tmp → rename
        tmp = self._state_file + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self._get_state_dict(), f)
        os.replace(tmp, self._state_file)
```

**Trade-offs:**
- **Pro:** Circuit state survives crashes
- **Pro:** Recovery detection can check "is circuit OPEN?" without worker running
- **Pro:** Prevents retry exhaustion after restart
- **Con:** Small disk I/O overhead on every state change (~1ms)
- **Con:** State file management (cleanup, corruption handling)

**PlexSync usage:**
- Circuit breaker in `worker/processor.py` persists OPEN/CLOSED state
- Recovery detector loads state to check if recovery check is relevant

---

### Pattern 3: Stateless Health Check

**What:** Health check with no side effects, no persistent state

**When to use:** Detecting external service availability without tracking history

**Implementation:**
```python
def check_plex_health(client: PlexClient, timeout: float = 5.0) -> tuple[bool, float]:
    """Single HTTP request, no state changes."""
    start = time.perf_counter()
    try:
        response = requests.get(f"{client._url}/:/ping", timeout=timeout)
        elapsed = (time.perf_counter() - start) * 1000
        is_healthy = response.status_code == 200 and 'pong' in response.text
        return (is_healthy, elapsed)
    except Exception:
        return (False, 0.0)
```

**Trade-offs:**
- **Pro:** No state management complexity
- **Pro:** Idempotent (run multiple times = same result)
- **Pro:** Fast (single HTTP request)
- **Con:** No historical tracking (separate scheduler needed for that)
- **Con:** Each check is independent (doesn't know about previous checks)

**PlexSync usage:**
- `plex/health.py` provides stateless health check
- `RecoveryScheduler` provides timing/history tracking (separate concerns)

---

## Anti-Patterns

### Anti-Pattern 1: Background Polling Thread

**What people might do:** Create a background thread that polls Plex health every N seconds

```python
# DON'T DO THIS
class HealthMonitor:
    def __init__(self):
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

    def _poll_loop(self):
        while self.running:
            check_plex_health()
            time.sleep(60)
```

**Why it's wrong:**
- Plugin exits after each invocation — thread dies with process
- Wastes resources polling when plugin isn't running
- Creates race conditions between poll thread and worker thread
- Doesn't survive process restarts

**Do this instead:** Use check-on-invocation pattern
- Check on every plugin invocation
- Use scheduler to decide if check is due
- No background threads needed

---

### Anti-Pattern 2: Immediate Queue Drain on Recovery

**What people might do:** Force-drain queue immediately when recovery detected

```python
# DON'T DO THIS
if plex_recovered:
    log_info("Plex recovered, draining queue NOW")
    while queue.size > 0:
        job = queue.get()
        process_job(job)  # Blocks plugin execution
```

**Why it's wrong:**
- Blocks hook handler (violates <100ms target)
- Plugin may timeout before queue drains
- Competes with existing worker thread
- No backpressure control

**Do this instead:** Let worker drain naturally
- Close circuit breaker on recovery
- Worker resumes processing on next poll cycle
- Existing rate limiting applies (0.15s between jobs)
- No special queue drain logic needed

---

### Anti-Pattern 3: Manual Circuit Breaker Reset Task

**What people might do:** Add task to manually reset circuit breaker

```python
# DON'T DO THIS
def handle_reset_circuit_breaker():
    """Force circuit breaker to CLOSED state."""
    circuit_breaker.reset()
    log_info("Circuit breaker manually reset")
```

**Why it's wrong:**
- Bypasses protection mechanism
- If Plex still down, circuit reopens immediately
- Confusing UX (users don't understand when to use)
- Health check + auto-recovery handles this correctly

**Do this instead:** Let recovery detection handle it
- User runs "Health Check" task to see current state
- Recovery detection automatically closes circuit when Plex healthy
- No manual reset needed

---

## Integration Considerations

### Stash Plugin Constraints

**No long-running processes:**
- Plugin invoked per-event, exits after handling
- Worker thread runs during invocation, dies on exit
- State must persist to disk to survive restarts

**No startup hooks:**
- Can't run code on Stash startup (Issue #5118)
- Initialization happens on first hook/task invocation
- Recovery check runs on first invocation after Plex comes back

**Task timeouts:**
- Manual tasks have implicit timeout (~2 minutes)
- Hook handlers should complete in <100ms
- Recovery check must be lightweight (<50ms when CB CLOSED)

---

### Performance Considerations

**Check-on-invocation overhead:**
- CB state load: ~1ms (single JSON read)
- Scheduler check: ~0.5ms (timestamp comparison)
- Total overhead when CB CLOSED: <2ms
- Health check only runs when CB OPEN (rare)

**Health check performance:**
- Plex `/:/ping` endpoint: ~20-100ms typical
- Timeout: 5 seconds (prevents hanging plugin)
- Frequency: max 1/minute when CB OPEN (scheduler throttles)

**Disk I/O patterns:**
- CB state saves: on every state transition (rare: ~5/outage)
- Recovery state saves: on every health check (~1/minute during outage)
- All saves are atomic (tmp → rename)

---

### Error Handling Strategy

**Graceful degradation:**
- If recovery check fails: log warning, continue processing
- If CB state corrupt: default to CLOSED (safe)
- If health check times out: treat as "Plex still down"

**No cascading failures:**
- Recovery detection errors don't block hook handlers
- Health check errors don't crash worker
- State file corruption doesn't prevent plugin startup

---

## Sources

**Circuit Breaker Pattern:**
- [Circuit Breaker - Martin Fowler](https://martinfowler.com/bliki/CircuitBreaker.html) — HIGH confidence: authoritative pattern definition
- [Python Circuit Breaker Implementation](https://pypi.org/project/pybreaker/) — MEDIUM confidence: production implementation patterns
- [Circuit Breaker State Persistence](https://github.com/resilience4j/resilience4j#circuit-breaker) — MEDIUM confidence: Java library with persistence examples

**Health Check Patterns:**
- [Plex API Endpoints](https://github.com/Arcanemagus/plex-api/wiki/Plex.tv#ping) — HIGH confidence: `/:/ping` endpoint verified
- [Health Check Pattern - Microsoft](https://learn.microsoft.com/en-us/azure/architecture/patterns/health-endpoint-monitoring) — HIGH confidence: health check best practices
- [Health Checks for Microservices](https://www.baeldung.com/spring-boot-health-indicators) — MEDIUM confidence: health check design patterns

**Event-Driven Architecture:**
- [Event-Driven Architecture Patterns](https://aws.amazon.com/event-driven-architecture/) — MEDIUM confidence: event-driven patterns for non-daemon systems
- [Stash Plugin Architecture](https://github.com/stashapp/stash/blob/develop/pkg/plugin/README.md) — HIGH confidence: plugin lifecycle and constraints verified

**State Persistence Patterns:**
- [Atomic File Writes in Python](https://docs.python.org/3/library/os.html#os.replace) — HIGH confidence: `os.replace()` atomicity guarantees
- [JSON State Persistence Best Practices](https://realpython.com/python-json/) — MEDIUM confidence: JSON serialization patterns
- [Check-on-Invocation Pattern](https://martinfowler.com/articles/patterns-of-distributed-systems/check-on-invocation.html) — MEDIUM confidence: pattern description (similar to polling but event-triggered)

**Existing PlexSync Patterns:**
- `reconciliation/scheduler.py` (lines 47-150) — HIGH confidence: proven check-on-invocation implementation
- `worker/circuit_breaker.py` (lines 24-140) — HIGH confidence: existing circuit breaker implementation
- `worker/backoff.py` (lines 60-91) — HIGH confidence: error-specific retry parameters

---

*Architecture research for: PlexSync outage resilience integration*
*Researched: 2026-02-15*
*Key Insight: Check-on-invocation pattern (proven in v1.4) extends naturally to recovery detection. Circuit breaker persistence enables recovery detection without worker running.*
