# Phase 19: Recovery Detection & Automation - Research

**Researched:** 2026-02-15
**Domain:** Recovery detection scheduler, circuit breaker state management, automatic queue drain
**Confidence:** HIGH

## Summary

Phase 19 implements automatic recovery detection when Plex comes back online after an outage. The challenge is bridging the gap between Phase 18's informational-only health checks and actual circuit breaker state transitions, then triggering automatic queue drain without manual intervention.

The existing ReconciliationScheduler (v1.4) already demonstrates the check-on-invocation pattern needed here. The architecture is: on every plugin invocation, check if recovery detection is due (lightweight JSON read), probe Plex health if circuit is OPEN, transition circuit breaker state based on health check results, and let the existing worker loop drain the queue automatically when circuit closes.

**Primary recommendation:** Create RecoveryScheduler mirroring ReconciliationScheduler's check-on-invocation pattern. On every plugin invocation, if circuit is OPEN, check if recovery probe is due, run health check, and actively transition circuit breaker state based on consecutive health check successes. Wire into main() before maybe_auto_reconcile() so recovery detection runs first.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib json | 3.x | State persistence | Same pattern as ReconciliationScheduler, CircuitBreaker |
| Python stdlib time | 3.x | Timing intervals | time.time() timestamps for check-on-invocation |
| Python stdlib os | 3.x | File path operations | data_dir path handling |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| dataclasses | 3.7+ | State structure | RecoveryState dataclass following ReconciliationState pattern |
| typing | 3.5+ | Type annotations | Optional[float], Tuple[bool, float] for health check results |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON persistence | sqlite | JSON is simpler, matches existing scheduler pattern, adequate for single-value state |
| check-on-invocation | APScheduler | Requires long-running daemon; Stash plugins are invoked per-event then exit |
| Manual state transitions | Timer-based HALF_OPEN | Existing recovery_timeout already does this; we just need consecutive success tracking |

**Installation:**
No new dependencies required — all stdlib.

## Architecture Patterns

### Recommended Project Structure
```
worker/
├── recovery.py               # NEW: RecoveryScheduler class
├── circuit_breaker.py        # EXISTING: CircuitBreaker with state property
└── processor.py              # EXISTING: SyncWorker with health probes

data/
└── recovery_state.json       # NEW: Persisted recovery scheduler state
```

### Pattern 1: Check-on-Invocation Recovery Detection
**What:** On every plugin invocation (hook or task), check if recovery detection is due, probe Plex health if circuit is OPEN, transition circuit breaker based on consecutive successes.

**When to use:** Stash plugins are NOT long-running daemons — invoked per-event, then exit. This is the ONLY way to implement "automatic" recovery without a persistent background process.

**Example:**
```python
# Source: Existing ReconciliationScheduler pattern
from reconciliation.scheduler import ReconciliationScheduler

class RecoveryScheduler:
    """Manages recovery detection scheduling via persisted state.

    NOT a timer/thread. On each plugin invocation, call should_check_recovery()
    to determine if health probe is due based on interval and last check time.
    """

    STATE_FILE = 'recovery_state.json'

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.state_path = os.path.join(data_dir, self.STATE_FILE)

    def should_check_recovery(self, circuit_state: CircuitState, now: Optional[float] = None) -> bool:
        """Check if recovery probe is due.

        Args:
            circuit_state: Current circuit breaker state
            now: Current time (default: time.time()). For testing.

        Returns:
            True if recovery probe should run now.
        """
        # Only probe when circuit is OPEN
        if circuit_state != CircuitState.OPEN:
            return False

        if now is None:
            now = time.time()

        state = self.load_state()
        elapsed = now - state.last_check_time

        # Check every 5 seconds minimum (matches worker health check interval)
        return elapsed >= 5.0
```

### Pattern 2: Consecutive Success Threshold for Recovery
**What:** Circuit breaker transitions OPEN → HALF_OPEN → CLOSED based on consecutive successful health checks, not just a single success.

**When to use:** Prevents flapping from intermittent connectivity. Industry standard is 1-3 consecutive successes (Kubernetes uses 1, Azure Load Balancer uses 2, we use 1 to match existing circuit breaker success_threshold).

**Example:**
```python
# Source: Circuit breaker recovery pattern (Microsoft Learn, Google Cloud)
@dataclass
class RecoveryState:
    """Persisted state for recovery scheduling."""
    last_check_time: float = 0.0          # time.time() of last health check
    consecutive_successes: int = 0        # Consecutive successful health checks
    consecutive_failures: int = 0         # Consecutive failed health checks
    last_recovery_time: float = 0.0       # When circuit last closed after outage
    recovery_count: int = 0               # Total number of recoveries detected

def record_health_check(self, success: bool, latency_ms: float, circuit_breaker: CircuitBreaker) -> None:
    """Record health check result and transition circuit breaker if threshold met.

    Args:
        success: Whether health check passed
        latency_ms: Health check latency in milliseconds
        circuit_breaker: CircuitBreaker instance to transition
    """
    state = self.load_state()
    state.last_check_time = time.time()

    if success:
        state.consecutive_successes += 1
        state.consecutive_failures = 0

        # Transition to HALF_OPEN if needed (circuit breaker's own timeout does this)
        # Then record success with circuit breaker
        if circuit_breaker.state == CircuitState.HALF_OPEN:
            circuit_breaker.record_success()  # May transition to CLOSED

            if circuit_breaker.state == CircuitState.CLOSED:
                # Recovery complete!
                state.last_recovery_time = time.time()
                state.recovery_count += 1
                state.consecutive_successes = 0
                log_info(f"Recovery complete after {state.consecutive_successes} consecutive health checks")
    else:
        state.consecutive_failures += 1
        state.consecutive_successes = 0

        # Record failure with circuit breaker if in HALF_OPEN
        if circuit_breaker.state == CircuitState.HALF_OPEN:
            circuit_breaker.record_failure()  # Reopens circuit

    self.save_state(state)
```

### Pattern 3: Integration with Existing Worker Loop
**What:** Worker loop continues to run health checks during OPEN state (Phase 18), but RecoveryScheduler provides the orchestration and state management for check-on-invocation.

**When to use:** Worker loop is daemon thread (can exit any time). RecoveryScheduler ensures recovery detection runs even when worker isn't running (e.g., during hook-only invocations).

**Example:**
```python
# Source: Stash2Plex.py main() function
def maybe_check_recovery():
    """Check if recovery detection is due and run it if so.

    Called on every plugin invocation (hook or task) BEFORE maybe_auto_reconcile().
    Checks if circuit is OPEN and recovery probe is due, then probes Plex health
    and transitions circuit breaker state based on consecutive successes.
    """
    if not config or not worker:
        return

    try:
        data_dir = get_plugin_data_dir()
        from worker.recovery import RecoveryScheduler

        scheduler = RecoveryScheduler(data_dir)
        circuit_state = worker.circuit_breaker.state

        if scheduler.should_check_recovery(circuit_state):
            from plex.health import check_plex_health
            from plex.client import PlexClient

            client = PlexClient(
                url=config.plex_url,
                token=config.plex_token,
                connect_timeout=5.0,
                read_timeout=5.0
            )

            is_healthy, latency_ms = check_plex_health(client, timeout=5.0)
            scheduler.record_health_check(is_healthy, latency_ms, worker.circuit_breaker)

            if is_healthy and worker.circuit_breaker.state == CircuitState.CLOSED:
                log_info(f"Plex recovered, queue will drain automatically ({worker.queue.size} jobs pending)")

    except Exception as e:
        log_debug(f"Recovery check failed: {e}")

# In main():
maybe_check_recovery()    # NEW: Recovery detection first
maybe_auto_reconcile()    # EXISTING: Then auto-reconciliation
```

### Anti-Patterns to Avoid

- **Direct circuit breaker state modification in health checks:** Phase 18 decision was health checks are informational-only. RecoveryScheduler should use circuit_breaker.record_success() and record_failure(), not modify _state directly. This preserves transition logging and state persistence.

- **Recovery detection in worker loop only:** Worker is daemon thread and may not be running during hook-only invocations. Recovery detection MUST run in main() check-on-invocation pattern to ensure coverage.

- **Single health check success triggers recovery:** Use consecutive success threshold (even if threshold=1) to align with circuit breaker's existing success_threshold design.

- **Tight polling loop during OPEN:** Respect minimum interval (5s) to avoid resource waste. Phase 18's exponential backoff in worker loop already handles long outages.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Scheduler for non-daemon plugin | APScheduler, threading.Timer | Check-on-invocation pattern | Stash plugins invoked per-event then exit; no long-running process |
| State file corruption handling | Custom JSON recovery | Copy ReconciliationScheduler pattern | Already handles JSONDecodeError, TypeError, KeyError with defaults |
| Circuit breaker state transitions | Manual state = CLOSED | circuit_breaker.record_success() | Preserves transition logging, state persistence, file locking |
| Health check with timeout | requests.get() with timeout | plex.health.check_plex_health() | Phase 18 already implemented deep health check with /identity endpoint |

**Key insight:** ReconciliationScheduler (v1.4) and CircuitBreaker (Phase 17) already solved the hard problems (check-on-invocation, state persistence, file locking, transition logging). RecoveryScheduler is a thin orchestration layer combining these existing components.

## Common Pitfalls

### Pitfall 1: Worker Loop vs Main Loop Recovery Detection
**What goes wrong:** Implementing recovery detection only in worker loop means it doesn't run during hook-only invocations (e.g., scene update events when worker hasn't started yet).

**Why it happens:** Phase 18 added health checks to worker loop, natural to assume that's the only place recovery detection happens.

**How to avoid:** Implement recovery detection in main() check-on-invocation pattern (like ReconciliationScheduler), called on EVERY plugin invocation regardless of whether worker is running.

**Warning signs:** Recovery only happens after manually running "Process Queue" task; hooks don't trigger recovery detection.

### Pitfall 2: Race Condition Between Worker Health Checks and Recovery Scheduler
**What goes wrong:** Worker loop runs health checks every 5s during OPEN state (Phase 18). RecoveryScheduler also runs health checks. Both might try to transition circuit breaker simultaneously.

**Why it happens:** Two independent code paths (worker loop + main loop) both calling check_plex_health() and modifying circuit breaker state.

**How to avoid:**
1. Worker loop health checks remain informational-only (Phase 18 design decision preserved)
2. RecoveryScheduler is the ONLY code path that calls circuit_breaker.record_success() during recovery
3. File locking in circuit_breaker._save_state_locked() prevents corruption if both run simultaneously

**Warning signs:** Circuit breaker state transitions logged twice in quick succession; corrupted circuit_breaker.json file.

### Pitfall 3: Recovery Detection During CLOSED State
**What goes wrong:** Running health checks when circuit is already CLOSED wastes resources and adds latency to every plugin invocation.

**Why it happens:** Forgot to check circuit state before running recovery detection.

**How to avoid:** should_check_recovery() MUST return False when circuit_state != CircuitState.OPEN. Only probe when actually in outage.

**Warning signs:** Health check latency shows up in every hook invocation; logs show health checks when circuit is CLOSED.

### Pitfall 4: Not Handling HALF_OPEN State Correctly
**What goes wrong:** Circuit transitions OPEN → HALF_OPEN (via recovery_timeout), but RecoveryScheduler doesn't recognize HALF_OPEN as "in recovery" and doesn't call record_success().

**Why it happens:** Checking only for circuit_state == CircuitState.OPEN, missing HALF_OPEN.

**How to avoid:**
1. should_check_recovery() returns True for OPEN (before timeout) OR checks if already HALF_OPEN
2. record_health_check() handles both states: success in HALF_OPEN calls circuit_breaker.record_success()

**Warning signs:** Circuit stuck in HALF_OPEN state; recovery never completes even when Plex is healthy.

## Code Examples

Verified patterns from existing codebase:

### Check-on-Invocation Pattern (from ReconciliationScheduler)
```python
# Source: reconciliation/scheduler.py
class ReconciliationScheduler:
    STATE_FILE = 'reconciliation_state.json'

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.state_path = os.path.join(data_dir, self.STATE_FILE)

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

    def save_state(self, state: ReconciliationState) -> None:
        """Save reconciliation state to disk atomically."""
        tmp_path = self.state_path + '.tmp'
        try:
            with open(tmp_path, 'w') as f:
                json.dump(asdict(state), f, indent=2)
            os.replace(tmp_path, self.state_path)
        except OSError as e:
            log_debug(f"Failed to save reconciliation state: {e}")

    def is_due(self, interval: str, now: Optional[float] = None) -> bool:
        """Check if auto-reconciliation is due based on interval and last run time."""
        if interval == 'never':
            return False

        interval_secs = INTERVAL_SECONDS.get(interval, 0)
        if interval_secs == 0:
            return False

        if now is None:
            now = time.time()

        state = self.load_state()
        elapsed = now - state.last_run_time
        return elapsed >= interval_secs
```

### Circuit Breaker State Transitions (from CircuitBreaker)
```python
# Source: worker/circuit_breaker.py
def record_success(self) -> None:
    """Record a successful execution.

    In CLOSED state: resets failure count.
    In HALF_OPEN state: increments success count, closes if threshold reached.
    """
    if self._state == CircuitState.HALF_OPEN:
        self._success_count += 1
        if self._success_count >= self._success_threshold:
            self._close()
        else:
            # Success recorded but threshold not yet reached
            self._save_state_locked()
    else:
        # CLOSED state - just reset failure count
        self._failure_count = 0
        self._save_state_locked()

def _close(self) -> None:
    """Transition to CLOSED state."""
    self._state = CircuitState.CLOSED
    self._opened_at = None
    self._failure_count = 0
    self._success_count = 0
    log_info("Circuit breaker CLOSED after successful recovery")  # RECV-03: Recovery notification
    self._save_state_locked()

@property
def state(self) -> CircuitState:
    """Current circuit state (may transition to HALF_OPEN if timeout elapsed)."""
    if self._state == CircuitState.OPEN and self._opened_at is not None:
        if time.time() - self._opened_at >= self._recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            self._success_count = 0
            log_info(f"Circuit breaker entering HALF_OPEN state after {self._recovery_timeout}s timeout")
            self._save_state_locked()
    return self._state
```

### Health Check Integration (from plex/health.py)
```python
# Source: plex/health.py
def check_plex_health(plex_client: "PlexClient", timeout: float = 5.0) -> Tuple[bool, float]:
    """Check Plex server health via /identity endpoint.

    Returns:
        Tuple of (is_healthy, latency_ms):
        - (True, latency_ms) if server responded successfully
        - (False, 0.0) if server is unreachable or returned error
    """
    try:
        start = time.perf_counter()
        plex_client.server.query('/identity', timeout=timeout)
        end = time.perf_counter()

        latency_ms = (end - start) * 1000.0
        log_debug(f"Health check passed (latency: {latency_ms:.1f}ms)")
        return (True, latency_ms)

    except Exception as exc:
        log_debug(f"Health check failed: {type(exc).__name__}: {exc}")
        return (False, 0.0)
```

### Main Entry Point Integration (from Stash2Plex.py)
```python
# Source: Stash2Plex.py (pattern to follow for maybe_check_recovery)
def maybe_auto_reconcile():
    """Check if auto-reconciliation is due and run it if so.

    Called on every plugin invocation (hook or task). Checks:
    1. If this is the first invocation since Stash startup -> run recent scope
    2. If reconcile_interval has elapsed -> run configured scope

    This is a lightweight check (reads one JSON file) that only triggers
    the heavier gap detection when reconciliation is actually due.
    """
    if not config or config.reconcile_interval == 'never':
        return

    if not stash_interface or not queue_manager:
        return

    try:
        data_dir = get_plugin_data_dir()
        from reconciliation.scheduler import ReconciliationScheduler

        scheduler = ReconciliationScheduler(data_dir)

        # Check startup trigger first (AUTO-02)
        if scheduler.is_startup_due():
            log_info("Auto-reconciliation: startup trigger (recent scenes)")
            _run_auto_reconcile(scheduler, scope="recent", is_startup=True)
            return

        # Check interval trigger (AUTO-01)
        if scheduler.is_due(config.reconcile_interval):
            # Map config scope to engine scope (AUTO-03)
            scope_map = {'all': 'all', '24h': 'recent', '7days': 'recent_7days'}
            engine_scope = scope_map.get(config.reconcile_scope, 'recent')
            log_info(f"Auto-reconciliation: interval trigger ({config.reconcile_interval}, scope: {config.reconcile_scope})")
            _run_auto_reconcile(scheduler, scope=engine_scope, is_startup=False)
            return

    except Exception as e:
        log_warn(f"Auto-reconciliation check failed: {e}")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual "Process Queue" after outage | Automatic recovery detection with check-on-invocation | Phase 19 (v1.5) | Zero user interaction required for recovery |
| Worker loop health checks informational-only | RecoveryScheduler actively transitions circuit breaker | Phase 19 (v1.5) | Health checks now trigger actual state transitions |
| Single health check success = recovered | Consecutive success threshold | Phase 19 (v1.5) | Prevents flapping from intermittent connectivity |
| Timer-based HALF_OPEN transition only | Hybrid: recovery_timeout + health check probing | Phase 18-19 (v1.5) | Faster recovery detection (proactive vs reactive) |

**Deprecated/outdated:**
- Manual recovery workflow (user runs "Process Queue" after noticing Plex is back online) — Phase 19 makes this automatic

## Design Decisions

### Decision 1: RecoveryScheduler in Main Loop, Not Worker Loop
**Rationale:** Worker loop is daemon thread and may not be running during hook-only invocations. Recovery detection MUST run on every plugin invocation to ensure automatic recovery regardless of worker state.

**Alternative considered:** Only run recovery detection in worker loop (simpler, already has health checks).

**Why rejected:** Misses hook-only invocations; recovery only happens when "Process Queue" task is manually run.

**Confidence:** HIGH — check-on-invocation is proven pattern in ReconciliationScheduler.

### Decision 2: Consecutive Success Threshold = 1
**Rationale:** Match CircuitBreaker's existing success_threshold=1 default. Prevents premature recovery but doesn't require multiple successes.

**Alternative considered:** Require 2-3 consecutive successes (Azure Load Balancer, Google Cloud pattern).

**Why rejected:** CircuitBreaker already has HALF_OPEN → CLOSED transition with success_threshold=1. Adding second threshold would be redundant. Can make configurable later if needed.

**Confidence:** MEDIUM — Could increase to 2-3 for more stable recovery, but 1 matches existing circuit breaker design.

### Decision 3: Worker Health Checks Remain Informational-Only
**Rationale:** Preserve Phase 18 design decision. RecoveryScheduler is single source of truth for state transitions during recovery. Prevents race conditions.

**Alternative considered:** Let worker health checks call circuit_breaker.record_success() directly.

**Why rejected:** Two code paths modifying circuit breaker state = race condition risk. File locking helps but cleaner to have single orchestrator.

**Confidence:** HIGH — Phase 18 explicitly documented this as design decision to avoid race conditions.

### Decision 4: Recovery Detection Interval = 5s (No Backoff in Main Loop)
**Rationale:** Worker loop already implements exponential backoff for health checks during OPEN state. Main loop recovery detection just needs to check "is it time to probe?" — actual probing is infrequent enough (5s minimum).

**Alternative considered:** Implement exponential backoff in RecoveryScheduler too.

**Why rejected:** Adds complexity without clear benefit. Worker loop handles long outages with backoff. Main loop checks are lightweight (just "is circuit OPEN and 5s elapsed?").

**Confidence:** MEDIUM — Could add backoff if recovery checks become resource-intensive, but current design is simpler.

## Open Questions

1. **Should RecoveryScheduler track outage history?**
   - What we know: Phase 21 (Outage Visibility) will add outage tracking for UI display
   - What's unclear: Whether RecoveryScheduler should start collecting this data now or defer to Phase 21
   - Recommendation: Defer to Phase 21. RecoveryScheduler's job is detection+transition, not history tracking. Keep it focused.

2. **What happens if circuit transitions HALF_OPEN → CLOSED between maybe_check_recovery() and worker loop iteration?**
   - What we know: Worker loop checks can_execute() before processing jobs, which reads circuit.state property
   - What's unclear: Whether there's a race between RecoveryScheduler closing circuit and worker loop reading state
   - Recommendation: Not a problem. circuit.state property is thread-safe read. Worker will see CLOSED on next iteration and resume processing. File locking prevents state corruption.

3. **Should recovery notification include queue size in log message?**
   - What we know: RECV-03 requires "recovery notification logged when circuit closes"
   - What's unclear: How much detail to include (just "recovered" vs "recovered, X jobs pending")
   - Recommendation: Include queue size. Helps users understand recovery impact. Use circuit_breaker._close() log + follow-up log in maybe_check_recovery().

## Sources

### Primary (HIGH confidence)
- Existing codebase: `reconciliation/scheduler.py` - Check-on-invocation pattern implementation
- Existing codebase: `worker/circuit_breaker.py` - State persistence, transition logging, recovery_timeout
- Existing codebase: `plex/health.py` - Deep health check with /identity endpoint
- Existing codebase: `Stash2Plex.py` - Main entry point integration pattern (maybe_auto_reconcile)

### Secondary (MEDIUM confidence)
- [Circuit Breaker Pattern - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker) - Health check probes during OPEN state, HALF_OPEN transition patterns
- [Circuit Breaker Pattern: How It Works, Benefits, Best Practices](https://www.groundcover.com/blog/learn/performance/circuit-breaker-pattern) - Recovery testing and state transitions
- [How to Configure Circuit Breaker Patterns](https://oneuptime.com/blog/post/2026-02-02-circuit-breaker-patterns/view) - 2026 best practices for circuit breaker configuration
- [Azure Load Balancer health probes](https://learn.microsoft.com/en-us/azure/load-balancer/load-balancer-custom-probe-overview) - Consecutive success thresholds for health probes
- [Google Cloud Health checks overview](https://cloud.google.com/load-balancing/docs/health-check-concepts) - Two consecutive responses required for healthy status
- [Kubernetes Health Check - How-To and Best Practices](https://www.apptio.com/blog/kubernetes-health-check/) - successThreshold and failureThreshold patterns

### Tertiary (LOW confidence, informational)
- [GitHub - MichielMe/fastscheduler](https://github.com/MichielMe/fastscheduler) - Python scheduler with JSON persistence (not used, but validates JSON state pattern)
- [threading — Thread-based parallelism — Python docs](https://docs.python.org/3/library/threading.html) - Daemon thread behavior and queue patterns
- [An Intro to Threading in Python – Real Python](https://realpython.com/intro-to-python-threading/) - Producer-consumer patterns with daemon threads

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib, matches existing patterns exactly
- Architecture: HIGH - ReconciliationScheduler pattern proven in v1.4, circuit breaker transitions proven in Phase 17
- Pitfalls: HIGH - Directly extracted from Phase 18 design notes and existing codebase analysis

**Research date:** 2026-02-15
**Valid until:** 2026-03-15 (30 days for stable patterns)
