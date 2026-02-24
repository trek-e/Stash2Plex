# Phase 18: Health Check Infrastructure - Research

**Researched:** 2026-02-15
**Domain:** Health check infrastructure for outage resilience in event-driven plugin
**Confidence:** HIGH

## Summary

Phase 18 implements health check infrastructure to validate Plex connectivity and prevent false positives during server recovery. The research reveals that PlexSync already has a mature circuit breaker with state persistence (Phase 17) and check-on-invocation scheduling pattern (reconciliation scheduler). Health checks integrate naturally into this existing architecture without new dependencies.

**Critical insight from pitfall research:** Simple health checks (TCP connect, HTTP 200) create false positives during Plex's multi-stage startup sequence (port open → HTTP responding → database loading → API ready). Deep health checks using real API calls (server.query('/identity')) prevent premature circuit closure.

**Primary recommendation:** Implement stateless health check using plexapi's server.query('/identity') endpoint with short timeout (5s), integrated into circuit breaker recovery detection via check-on-invocation pattern. Combine passive monitoring (job results via existing circuit breaker) with active probes (periodic checks during OPEN state) for hybrid monitoring.

## Standard Stack

### Core (NO NEW DEPENDENCIES)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| plexapi | >=4.17.0 (4.18.0 installed) | Health check via server.query('/identity') | PlexSync already uses plexapi for all Plex communication. No dedicated health/ping methods exist in plexapi. server.query() provides raw API access for lightweight endpoint probing. /identity endpoint validates database access (not just port connectivity). |
| json (stdlib) | 2.0.9 | Circuit breaker state persistence (Phase 17) | Already implemented in Phase 17 with atomic write pattern. Health check status can be added to existing circuit_breaker.json state. Zero dependencies. |
| time (stdlib) | - | Timestamps for health check intervals | Already used in circuit breaker for OPEN→HALF_OPEN timeout. Reuse for health check backoff intervals. |

### Supporting (ALREADY PRESENT)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| worker/backoff.py | - | Exponential backoff with jitter | Reuse for health check interval backoff during extended outages (5s → 10s → 20s → 60s cap). Already implements calculate_delay() with full jitter to prevent thundering herd. |
| worker/circuit_breaker.py | - | 3-state circuit breaker with persistence | Already enhanced in Phase 17 with state_file parameter, file locking (_save_state_locked), and atomic writes. Health checks integrate into OPEN→HALF_OPEN transition logic. |
| reconciliation/scheduler.py | - | Check-on-invocation pattern | Proven pattern for "check if action due on each invocation." Reuse for recovery detection: on each hook, check if circuit OPEN + health check interval elapsed. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| server.query('/identity') | requests.get(f"{plex_url}") for root endpoint | Root endpoint may respond before database loads (false positive during Plex startup sequence). /identity requires database access, validates server is truly ready. Recommendation: Use /identity. |
| Active health checks during OPEN | Passive-only (job results) | Passive detects failure fast but recovery detection requires coincidental hook invocation. Active probes during OPEN state detect recovery even when queue is idle. Recommendation: Hybrid (both). |
| Health check in worker loop | Separate background thread | Worker already runs in daemon thread during plugin invocation. Adding health check to worker loop avoids thread management complexity. Separate thread would die on plugin exit (non-daemon architecture). Recommendation: Worker loop integration. |
| Exponential backoff for health intervals | Fixed 60s interval | Fixed interval wastes resources during long outages (8hr Plex backup = 480 unnecessary health checks). Exponential backoff (5s → 10s → 20s → 60s cap) reduces load on recovering server. Recommendation: Backoff. |

**Installation:**
```bash
# NO NEW DEPENDENCIES REQUIRED
# All health check capabilities available in existing stack
```

## Architecture Patterns

### Recommended Project Structure
```
plex/
├── client.py           # Existing: PlexClient wrapper
├── health.py           # NEW: Health check functions
└── exceptions.py       # Existing: Exception hierarchy

worker/
├── circuit_breaker.py  # Phase 17: State persistence (EXISTING)
├── processor.py        # NEW: Integrate health check into worker loop
└── backoff.py          # Existing: Exponential backoff logic

.planning/phases/18-health-check-infrastructure/
├── 18-RESEARCH.md      # This file
└── 18-PLAN.md          # Tasks for implementation
```

### Pattern 1: Deep Health Check (Sentinel Request)

**What:** Health check makes a real API request to validate database access, not just port connectivity.

**When to use:** Detecting Plex recovery after outages, especially during multi-stage startup sequence.

**Example:**
```python
# plex/health.py (NEW FILE)
# Source: .planning/research/STACK.md + PlexAPI server.query() docs

def check_plex_health(plex_client: PlexClient, timeout: float = 5.0) -> tuple[bool, float]:
    """
    Check if Plex server is responding to API requests.

    Uses server.query('/identity') which requires database access.
    This prevents false positives during Plex startup when port is open
    but database is still loading.

    Args:
        plex_client: PlexClient instance
        timeout: Request timeout in seconds (default: 5.0)

    Returns:
        Tuple of (is_healthy: bool, latency_ms: float)
        - is_healthy: True if server responds successfully
        - latency_ms: Response latency in milliseconds (0.0 on failure)

    Example:
        >>> client = PlexClient(url="http://plex:32400", token="...")
        >>> healthy, latency = check_plex_health(client, timeout=5.0)
        >>> if healthy:
        ...     log_info(f"Plex healthy ({latency:.0f}ms)")
    """
    import time
    from plex.exceptions import PlexTemporaryError

    start = time.perf_counter()
    try:
        # Use plexapi's server.query() for raw API access
        # /identity endpoint: lightweight, validates DB access
        plex_client.server.query('/identity', timeout=timeout)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return (True, elapsed_ms)

    except Exception as e:
        # Any error = server not healthy (connection refused, timeout, 503, etc.)
        log_debug(f"Plex health check failed: {e}")
        return (False, 0.0)
```

**Why this pattern:**
- /identity endpoint requires database access (not just HTTP server responding)
- Prevents false positives during Plex startup sequence:
  1. Port 32400 binds (TCP connect succeeds)
  2. HTTP server starts (GET / returns 200)
  3. Database loads (several minutes on large libraries)
  4. /identity endpoint responds (server truly ready)
- Lightweight: ~200 bytes XML response, <100ms on healthy server
- No authentication required for /identity (public endpoint)

### Pattern 2: Hybrid Health Monitoring (Active + Passive)

**What:** Combine passive monitoring (job results trigger circuit breaker) with active probes (periodic checks during OPEN state).

**When to use:** Systems that need fast failure detection AND fast recovery detection.

**Example:**
```python
# worker/processor.py (MODIFY EXISTING)
# Integrate health check into worker loop

def _worker_loop(self):
    """Worker loop with hybrid health monitoring."""
    last_health_check = 0.0
    health_check_interval = 60.0  # Initial interval

    while self.running:
        # Check circuit breaker state
        current_state = self.circuit_breaker.state  # Property handles OPEN→HALF_OPEN

        if current_state == CircuitState.OPEN:
            # Active health check during OPEN state
            now = time.time()
            if now - last_health_check >= health_check_interval:
                from plex.health import check_plex_health

                healthy, latency = check_plex_health(self.plex_client, timeout=5.0)
                last_health_check = now

                if healthy:
                    log_info(f"Plex health check passed ({latency:.0f}ms)")
                    # Circuit breaker property already transitioned to HALF_OPEN
                    # Next job will test recovery via normal processing
                else:
                    log_debug("Plex health check failed, circuit remains OPEN")
                    # Increase interval for backoff (5s → 10s → 20s → 60s cap)
                    health_check_interval = min(health_check_interval * 2, 60.0)

            time.sleep(1.0)  # Wait while circuit open
            continue

        # Circuit CLOSED or HALF_OPEN - process jobs (passive monitoring)
        try:
            job = self.queue.get(timeout=1.0)
            if job:
                self._process_job(job)  # Success/failure updates circuit breaker
        except Empty:
            time.sleep(1.0)
```

**Trade-offs:**
- **Pro:** Fast failure detection (passive: job fails immediately)
- **Pro:** Fast recovery detection (active: probes every 60s even when idle)
- **Pro:** Backoff during long outages (reduces wasted probes)
- **Con:** Additional health check traffic (1 req/min during outages)

### Pattern 3: Health Check with Exponential Backoff

**What:** Space out health checks during extended outages to avoid hammering recovering server.

**When to use:** Systems with unpredictable outage duration (minutes to hours).

**Example:**
```python
# worker/processor.py (MODIFY EXISTING)
# Reuse existing backoff logic from worker/backoff.py

def _calculate_health_check_interval(self, consecutive_failures: int) -> float:
    """
    Calculate health check interval with exponential backoff.

    Args:
        consecutive_failures: Number of consecutive health check failures

    Returns:
        Interval in seconds (5s → 10s → 20s → 60s cap)
    """
    from worker.backoff import calculate_delay

    # Base: 5s, Cap: 60s, Jitter for thundering herd prevention
    base_delay = 5.0
    max_delay = 60.0

    # Use retry_count as consecutive_failures (0-indexed)
    delay = calculate_delay(
        retry_count=consecutive_failures,
        base=base_delay,
        cap=max_delay,
        jitter_seed=None  # Random jitter in production
    )

    return delay
```

**Why this pattern:**
- Reuses existing backoff logic (no duplication)
- Prevents health check storms during long outages
- Jitter prevents thundering herd if multiple workers exist
- Cap at 60s ensures recovery detected within reasonable time

### Anti-Patterns to Avoid

- **Shallow health check (TCP connect only):** Port may be open but Plex database still loading. Use deep check (API request) to validate true readiness. See Pitfall 2 in .planning/research/PITFALLS.md.

- **Immediate circuit closure on first health check success:** Server may be partially initialized. Circuit breaker already has success_threshold (default: 1). For production, consider increasing to 2-3 consecutive successes before closing.

- **Health check polling in separate background thread:** Plugin exits after each invocation. Background threads die with process. Integrate health check into worker loop (already a daemon thread).

- **Fixed health check interval during extended outages:** Wastes resources and hammers recovering server. Use exponential backoff (5s → 60s cap).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Health check HTTP requests | Custom socket/HTTP client | plexapi server.query() with timeout | plexapi already handles auth (X-Plex-Token), timeout, connection pooling, XML parsing. Custom implementation would duplicate 100+ lines and miss edge cases (redirects, auth errors, SSL). |
| Exponential backoff | Custom delay calculation | worker/backoff.py calculate_delay() | Existing backoff.py already implements full jitter for thundering herd prevention. Custom implementation would lack jitter or duplicate 20 lines of tested code. |
| Circuit breaker state transitions | Manual state management | worker/circuit_breaker.py state property | Circuit breaker already handles OPEN→HALF_OPEN transition based on recovery_timeout. Health check should trigger via existing state machine, not bypass it. |
| Health check scheduling | Custom timer/thread | Check-on-invocation pattern from reconciliation/scheduler.py | Stash plugins are NOT daemons. Custom timer would die on plugin exit. Check-on-invocation pattern proven in reconciliation scheduler (v1.4). |

**Key insight:** PlexSync has mature infrastructure (circuit breaker persistence, backoff, check-on-invocation). Health checks integrate into existing patterns, no novel implementations needed.

## Common Pitfalls

### Pitfall 1: False Positive Health Checks During Plex Startup

**What goes wrong:** Health check detects Plex port 32400 is open, declares server healthy, circuit breaker closes, and queue processing resumes. But Plex database is still loading, returning 503 for all metadata requests. Queue drains with failures, circuit reopens immediately.

**Why it happens:** Plex startup has multiple stages:
1. Process starts, binds port 32400 (TCP connect succeeds)
2. HTTP server starts, returns 200 for basic endpoints
3. Database loads (minutes on large libraries)
4. API endpoints return 200 with valid data

Shallow health checks (TCP, HTTP /) succeed at stage 2, but server isn't functionally ready until stage 4.

**How to avoid:**
- Use deep health check: server.query('/identity') requires database access
- This endpoint won't respond until database fully loaded
- Alternative: Add grace period (30s wait after health check success before closing circuit)

**Warning signs:**
- Health checks report "healthy" but sync requests fail with 503
- Circuit breaker rapidly cycles HALF_OPEN → CLOSED → OPEN
- Burst of 503 errors immediately after circuit closes
- Plex logs show requests arriving before "Database opened" message

**Source:** .planning/research/PITFALLS.md (Pitfall 2)

---

### Pitfall 2: Health Check Interval Wastes Resources During Long Outages

**What goes wrong:** Health check polls Plex every 60 seconds during 8-hour outage (Plex backup window). 480 failed health checks waste resources and clutter logs.

**Why it happens:** Fixed interval doesn't adapt to outage duration. Short interval is appropriate for quick blips (30s network hiccup) but wasteful for planned maintenance (8hr backup).

**How to avoid:**
- Use exponential backoff: 5s → 10s → 20s → 40s → cap at 60s
- First check after 5s (fast recovery for quick blips)
- Later checks at 60s (appropriate for extended outages)
- Reuse existing worker/backoff.py calculate_delay()

**Warning signs:**
- Log spam: 480+ "Plex health check failed" during long outage
- Worker thread consuming CPU during idle period
- Health check traffic visible in Plex server logs during maintenance

**Source:** .planning/research/FEATURES.md (Health check backoff section)

---

### Pitfall 3: Race Condition Between Health Check and Circuit Breaker State

**What goes wrong:** Health check runs in worker thread, reads circuit_breaker.json (state: OPEN). Simultaneously, hook invocation processes job failure, updates circuit breaker state to CLOSED. Health check overwrites state file, reverting to OPEN. Circuit stuck.

**Why it happens:** Multiple processes (plugin invocations) can run concurrently. Circuit breaker state file is shared. Without synchronization, last write wins.

**How to avoid:**
- Circuit breaker already uses file locking (_save_state_locked with fcntl.LOCK_EX | fcntl.LOCK_NB)
- Phase 17 implemented non-blocking advisory locking
- Health check should NOT directly modify circuit breaker state
- Instead: health check returns (is_healthy: bool), circuit breaker state property handles OPEN→HALF_OPEN transition based on recovery_timeout

**Warning signs:**
- Circuit breaker state file shows rapid updates (multiple writes per second)
- State transitions logged multiple times within same second
- Circuit appears "stuck" in OPEN state despite health checks passing

**Source:** worker/circuit_breaker.py (Phase 17 implementation with file locking)

---

### Pitfall 4: Health Check Timeouts Block Worker Thread

**What goes wrong:** Health check uses long timeout (30s default from PlexClient). During Plex outage, health check blocks worker thread for 30s per attempt. Worker can't process jobs or respond to shutdown signals.

**Why it happens:** plexapi's default timeout is 30s (read_timeout parameter). Health check should use shorter timeout (5s) because it's just a liveness probe, not a real operation.

**How to avoid:**
- Pass explicit timeout=5.0 to server.query()
- Health checks should be fast (fail quickly if server down)
- Sync operations can use longer timeouts (30s) because they're real work
- Document timeout semantics: health=5s, connect=5s, read=30s

**Warning signs:**
- Worker thread unresponsive during outages
- "Process Queue" task takes 30+ seconds to report circuit OPEN
- Thread dumps show worker blocked in socket.recv()

**Source:** plex/client.py (PlexClient timeout parameters)

## Code Examples

Verified patterns from existing codebase and research:

### Example 1: Deep Health Check with server.query('/identity')

```python
# plex/health.py (NEW FILE)
"""
Plex health check using lightweight API endpoint.

Validates server is reachable and database is loaded.
"""

import time
from typing import Tuple
from plex.client import PlexClient
from shared.log import create_logger

_, log_debug, _, _, _ = create_logger("Health")


def check_plex_health(
    plex_client: PlexClient,
    timeout: float = 5.0
) -> Tuple[bool, float]:
    """
    Check if Plex server is responding to API requests.

    Uses server.query('/identity') which:
    - Requires database access (not just port open)
    - Returns server UUID, version, platform
    - Lightweight (~200 bytes XML)
    - No authentication required

    Args:
        plex_client: PlexClient instance
        timeout: Request timeout in seconds (default: 5.0)

    Returns:
        Tuple of (is_healthy: bool, latency_ms: float)
        - is_healthy: True if server responds successfully
        - latency_ms: Response latency in milliseconds (0.0 on failure)

    Example:
        >>> client = PlexClient(url="http://plex:32400", token="...")
        >>> healthy, latency = check_plex_health(client)
        >>> if healthy:
        ...     log_info(f"Plex is healthy ({latency:.0f}ms)")
    """
    start = time.perf_counter()

    try:
        # Use plexapi's server.query() for raw API access
        # /identity endpoint is public (no auth) and lightweight
        plex_client.server.query('/identity', timeout=timeout)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return (True, elapsed_ms)

    except Exception as e:
        # Any error means server not healthy:
        # - ConnectionError: Port not reachable
        # - Timeout: Server not responding within timeout
        # - 503: Database loading (Plex startup sequence)
        # - Other: Authentication, SSL, etc.
        log_debug(f"Plex health check failed: {type(e).__name__}: {e}")
        return (False, 0.0)
```

**Source:** .planning/research/STACK.md (Health Check Implementation pattern)

---

### Example 2: Manual Health Check Task

```python
# Stash2Plex.py (ADD TO TASK DISPATCH)
"""Add health_check task mode for manual Plex connectivity test."""

_MANAGEMENT_HANDLERS = {
    # ... existing handlers ...
    'health_check': lambda args: handle_health_check(),
}

def handle_health_check():
    """
    Manual Plex health check task.

    Reports:
    - Current circuit breaker state (CLOSED/OPEN/HALF_OPEN)
    - Plex connectivity via /identity endpoint
    - Last health check timestamp (if active monitoring enabled)
    - Queue size (pending jobs)

    This is a read-only diagnostic task. It does NOT modify
    circuit breaker state or trigger recovery.
    """
    try:
        log_info("=== Plex Health Check ===")

        # 1. Circuit breaker state
        data_dir = get_plugin_data_dir()
        cb_state_path = os.path.join(data_dir, 'circuit_breaker.json')

        if os.path.exists(cb_state_path):
            with open(cb_state_path) as f:
                cb_data = json.load(f)
            cb_state = cb_data.get('state', 'UNKNOWN')
            cb_opened_at = cb_data.get('opened_at')

            log_info(f"Circuit Breaker State: {cb_state.upper()}")
            if cb_state == 'open' and cb_opened_at:
                elapsed = time.time() - cb_opened_at
                log_info(f"Circuit opened {elapsed:.0f}s ago")
        else:
            log_info("Circuit Breaker State: CLOSED (no state file)")

        # 2. Plex health check
        from plex.client import PlexClient
        from plex.health import check_plex_health

        client = PlexClient(
            url=config.plex_url,
            token=config.plex_token,
            connect_timeout=5.0,
            read_timeout=5.0  # Short timeout for health check
        )

        log_info("Testing Plex connectivity...")
        is_healthy, latency_ms = check_plex_health(client, timeout=5.0)

        if is_healthy:
            log_info(f"✓ Plex is HEALTHY (responded in {latency_ms:.0f}ms)")
        else:
            log_warn("✗ Plex is UNREACHABLE")
            log_info("Verify Plex URL and network connectivity")

        # 3. Queue size
        if queue_manager:
            queue = queue_manager.get_queue()
            pending = queue.size
            log_info(f"Queue: {pending} items pending")

            if pending > 0 and cb_state == 'open':
                log_warn(f"⚠ {pending} jobs waiting while circuit breaker is OPEN")
                log_info("Queue processing will resume when Plex recovers")

        log_info("=== Health Check Complete ===")

    except Exception as e:
        log_error(f"Health check failed: {e}")
        import traceback
        traceback.print_exc()
```

**Source:** .planning/research/ARCHITECTURE.md (Task Dispatch section)

---

### Example 3: Worker Loop Integration with Active Health Checks

```python
# worker/processor.py (MODIFY _worker_loop)
"""Integrate active health checks into worker loop during OPEN state."""

def _worker_loop(self):
    """
    Worker loop with hybrid health monitoring.

    - Passive: Job results update circuit breaker (existing)
    - Active: Periodic health checks during OPEN state (new)
    """
    last_health_check = 0.0
    health_check_interval = 5.0  # Initial interval (5s)
    consecutive_health_failures = 0

    while self.running:
        # Get circuit breaker state (property handles OPEN→HALF_OPEN transition)
        current_state = self.circuit_breaker.state

        if current_state == CircuitState.OPEN:
            # Circuit is OPEN - do NOT process jobs
            # Instead, run periodic health checks to detect recovery

            now = time.time()
            if now - last_health_check >= health_check_interval:
                from plex.health import check_plex_health

                log_debug("Running active health check (circuit OPEN)...")
                is_healthy, latency_ms = check_plex_health(
                    self.plex_client,
                    timeout=5.0
                )
                last_health_check = now

                if is_healthy:
                    log_info(f"Plex health check passed ({latency_ms:.0f}ms)")
                    log_info("Circuit breaker will test recovery on next job")
                    consecutive_health_failures = 0
                    health_check_interval = 5.0  # Reset interval
                    # Circuit breaker state property already transitioned to HALF_OPEN
                    # Next iteration will process a test job
                else:
                    log_debug(f"Plex health check failed (attempt #{consecutive_health_failures + 1})")
                    consecutive_health_failures += 1

                    # Exponential backoff: 5s → 10s → 20s → 40s → cap at 60s
                    from worker.backoff import calculate_delay
                    health_check_interval = calculate_delay(
                        retry_count=consecutive_health_failures,
                        base=5.0,
                        cap=60.0,
                        jitter_seed=None  # Random jitter
                    )
                    log_debug(f"Next health check in {health_check_interval:.1f}s")

            time.sleep(1.0)  # Wait while circuit open
            continue

        # Circuit CLOSED or HALF_OPEN - process jobs normally
        # (Existing worker loop logic continues here)
        try:
            job = self.queue.get(timeout=1.0)
            if job:
                self._process_job(job)
                # _process_job calls circuit_breaker.record_success/failure
                # This is passive monitoring (job results update circuit breaker)
        except Empty:
            time.sleep(1.0)
```

**Source:** .planning/research/ARCHITECTURE.md (Worker Loop Integration section)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No health monitoring | Hybrid active+passive health checks | 2026 (Phase 18) | Faster recovery detection when queue idle. Prevents false positives during Plex startup. |
| In-memory circuit breaker state | Persisted circuit breaker state with file locking | Phase 17 (v1.5) | State survives plugin restarts. Recovery detection works across process boundaries. |
| Fixed health check intervals | Exponential backoff (5s → 60s cap) | Phase 18 | Reduces resource waste during long outages. Less load on recovering server. |
| Shallow health checks (TCP/HTTP) | Deep health checks (API request) | Industry best practice 2024-2026 | Prevents false positives during multi-stage server startup. See AWS health check patterns. |

**Deprecated/outdated:**
- **Manual "Process Queue" as only recovery trigger:** Users had to manually detect Plex recovery and trigger queue drain. Phase 18 adds automatic recovery detection via active health checks.
- **Circuit breaker without persistence:** Pre-Phase 17, circuit breaker state was in-memory only. Process restart would reset circuit to CLOSED even if Plex still down, causing retry exhaustion on startup.
- **Passive-only monitoring:** Relying solely on job failures to detect Plex outages. No active probes to detect recovery when queue is idle.

## Open Questions

1. **Should health check interval adapt to time-of-day patterns?**
   - What we know: Plex outages may have patterns (nightly backup window = 8hr outage at 2am)
   - What's unclear: Whether adaptive scheduling (slower checks during known maintenance windows) adds value over simple exponential backoff
   - Recommendation: Start with exponential backoff (simple, proven). Add time-aware scheduling in Phase 19+ if users report long outages have patterns.

2. **Should health checks run when circuit is CLOSED (always-on monitoring)?**
   - What we know: Passive monitoring (job results) detects failures immediately when processing jobs
   - What's unclear: Whether always-on active health checks add value (detect issues before job processing) vs. cost (unnecessary traffic)
   - Recommendation: Active checks only during OPEN state (Phase 18 scope). Consider always-on monitoring in Phase 19+ if users report delayed failure detection.

3. **Should manual health check task report more diagnostics (library scanning status, disk space)?**
   - What we know: Manual task currently reports: circuit state, connectivity, queue size
   - What's unclear: Whether users need deeper diagnostics (Plex server status, library scan progress, disk space, CPU)
   - Recommendation: Start simple (Phase 18: connectivity only). Add diagnostics in Phase 20+ based on user feedback.

## Sources

### Primary (HIGH confidence)

- **plexapi server.query() documentation** - [Python PlexAPI Server Documentation](https://python-plexapi.readthedocs.io/en/latest/modules/server.html) - server.query() method, timeout parameter, no dedicated health/ping methods exist
- **PlexSync existing code (verified implementations)**:
  - plex/client.py (lines 108-158) - PlexClient._get_server() with retry, timeout configuration
  - worker/circuit_breaker.py (lines 59-244) - CircuitBreaker with state persistence, file locking (_save_state_locked)
  - worker/backoff.py (lines 17-90) - calculate_delay() exponential backoff with full jitter, get_retry_params()
  - reconciliation/scheduler.py (lines 47-150) - ReconciliationScheduler with check-on-invocation pattern (is_due, load_state, save_state)
- **.planning/research/STACK.md** (researched 2026-02-15) - Recommended stack for outage resilience, health check patterns using plexapi
- **.planning/research/ARCHITECTURE.md** (researched 2026-02-15) - Component integration, health check in worker loop, check-on-invocation pattern
- **.planning/research/PITFALLS.md** (researched 2026-02-15) - False positive health checks (Pitfall 2), race conditions (Pitfall 1), thundering herd (Pitfall 3)

### Secondary (MEDIUM confidence)

- **Plex Docker healthcheck** - [pms-docker healthcheck.sh](https://github.com/plexinc/pms-docker/blob/master/root/healthcheck.sh) - Official Docker image uses /identity endpoint for liveness checks
- **Active vs Passive Health Checks** - [F5 NGINX Health Check Comparison](https://www.f5.com/company/blog/nginx/active-or-passive-health-checks-which-is-right-for-you) - When to use each, resource implications, hybrid approach
- **Health Check Best Practices** - [10 Essential Best Practices for API Gateway Health Checks](https://api7.ai/blog/10-best-practices-of-api-gateway-health-checks) - Probe frequency, timeout configuration, deep vs shallow checks
- **AWS Health Check Patterns** - [Implementing health checks — AWS Builders Library](https://aws.amazon.com/builders-library/implementing-health-checks/) - Dependency health check false positives during initialization, fail-open pattern

### Tertiary (LOW confidence)

- **Plex API /identity endpoint structure** - [Plex API Documentation](https://plexapi.dev/api-reference/server/get-server-capabilities) - Community-maintained docs, not official Plex documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All components already present in PlexSync (plexapi, json, time, worker/backoff.py, circuit_breaker.py). No new dependencies.
- Architecture: HIGH - Patterns verified in existing code (circuit breaker persistence in Phase 17, check-on-invocation in reconciliation scheduler). Health check integration point is worker loop (already daemon thread).
- Pitfalls: HIGH - False positive health checks documented with real-world Plex startup sequence. Race conditions addressed in Phase 17 with file locking. Thundering herd prevention via backoff.py jitter.

**Research date:** 2026-02-15
**Valid until:** 2026-04-15 (60 days - stable patterns, no fast-moving dependencies)

**Key takeaway for planner:** Health check infrastructure reuses mature PlexSync patterns (circuit breaker persistence, check-on-invocation, exponential backoff). No novel implementations needed. Critical requirement is deep health check (server.query('/identity')) to prevent false positives during Plex startup. Hybrid monitoring (active+passive) provides fast failure detection and fast recovery detection.
