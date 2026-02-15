# Phase 20: Graduated Recovery & Rate Limiting - Research

**Researched:** 2026-02-15
**Domain:** Rate limiting, graduated recovery, thundering herd prevention
**Confidence:** MEDIUM-HIGH

## Summary

Phase 20 implements graduated rate limiting during queue drain after Plex recovery to prevent overwhelming the just-recovered server. The research reveals this is a well-understood problem in distributed systems called the "thundering herd" or "retry storm" pattern, with established mitigation strategies.

The key insight: after circuit transitions OPEN→CLOSED (Plex recovered), the worker loop will immediately try to process ALL pending queue items at full speed. With a large backlog (e.g., 500 jobs accumulated during a long outage), this creates a stampede that can re-crash the recovering server, creating a failure loop.

**Primary recommendation:** Implement token bucket rate limiting with graduated rate increase during recovery period, combined with error rate monitoring that backs off if failures spike. Use simple time-based implementation (not external library) for minimal complexity and maximum control.

## Standard Stack

### Core

No external libraries needed. All implementations can use Python standard library with minimal dependencies already present in the codebase.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `time` | stdlib | Time tracking, rate calculations | Built-in, zero dependencies |
| `json` | stdlib | State persistence | Already used for circuit_breaker.json, recovery_state.json |
| `dataclasses` | stdlib | State modeling | Already used in RecoveryState |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pyrate-limiter` | 4.0+ | Production-grade leaky bucket | If complex multi-rate limiting needed later |
| `token-bucket` | latest | Falcon framework token bucket | If need burst control with gradual refill |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom token bucket | PyrateLimiter library | Library adds SQLite/Redis backends (overkill), multiprocessing support (not needed), and complexity. Custom implementation gives exact control for recovery use case. |
| Time-based rate limiting | Decorator-based (ratelimit package) | Decorators work for function-level limits but recovery rate limiting needs dynamic adjustment based on circuit state and error rates. Custom state machine is cleaner. |

**Installation:**
No new dependencies required — use Python stdlib.

## Architecture Patterns

### Recommended Project Structure

```
worker/
├── processor.py           # Existing: _worker_loop processes queue
├── circuit_breaker.py     # Existing: State machine (CLOSED/OPEN/HALF_OPEN)
├── recovery.py            # Existing: RecoveryScheduler tracks recovery
├── backoff.py             # Existing: Exponential backoff with jitter
├── rate_limiter.py        # NEW: RecoveryRateLimiter class
└── stats.py               # Existing: Job statistics tracking
```

### Pattern 1: Recovery Period State Machine

**What:** After circuit transitions OPEN→CLOSED, enter "recovery period" (5-10 minutes) with graduated rate limiting.

**When to use:** Every time circuit closes after being OPEN (Plex just recovered).

**State transitions:**
```
CLOSED (normal) ──failure──> OPEN (outage) ──recovery──> HALF_OPEN (testing) ──success──> CLOSED (normal)
                                                                                                  │
                                                                                                  v
                                                                                          RECOVERY_PERIOD
                                                                                          (5-10 minutes)
                                                                                                  │
                                                                                                  v
                                                                                             NORMAL_RATE
```

**Example:**
```python
# Source: Industry best practice (AWS, Azure patterns)
# Recovery period tracks:
# - recovery_started_at: time.time() when circuit closed
# - current_rate: tokens/second allowed (starts low, ramps up)
# - error_rate_window: track failures/successes to detect problems

class RecoveryPeriod:
    """Tracks recovery period state after circuit closes."""
    recovery_started_at: float
    initial_rate: float = 5.0      # Jobs/sec (conservative start)
    target_rate: float = 20.0      # Jobs/sec (normal speed)
    ramp_duration: float = 300.0   # 5 minutes to full speed

    def current_rate(self) -> float:
        elapsed = time.time() - self.recovery_started_at
        if elapsed >= self.ramp_duration:
            return self.target_rate  # Full speed
        # Linear ramp: 5 → 20 over 5 minutes
        progress = elapsed / self.ramp_duration
        return self.initial_rate + (self.target_rate - self.initial_rate) * progress
```

### Pattern 2: Token Bucket for Burst Control

**What:** Token bucket algorithm allows controlled bursts while maintaining average rate.

**When to use:** During recovery period to prevent instantaneous queue drain.

**How it works:**
- Bucket holds tokens (max capacity)
- Tokens added at controlled rate (jobs/second)
- Each job consumes 1 token
- If no tokens available, job waits

**Example:**
```python
# Source: Token bucket algorithm (standard CS algorithm)
class TokenBucket:
    def __init__(self, rate: float, capacity: float):
        self.rate = rate          # Tokens added per second
        self.capacity = capacity  # Max tokens in bucket
        self.tokens = capacity    # Current tokens
        self.last_update = time.time()

    def refill(self):
        """Add tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def wait_time(self) -> float:
        """Time until next token available."""
        self.refill()
        if self.tokens >= 1:
            return 0.0
        shortage = 1 - self.tokens
        return shortage / self.rate
```

### Pattern 3: Error Rate Monitoring with Adaptive Backoff

**What:** Monitor error rate during recovery period. If failures spike, back off rate to prevent re-crashing Plex.

**When to use:** Every job during recovery period.

**Example:**
```python
# Source: Adaptive backoff patterns from AWS Builders Library
class ErrorRateMonitor:
    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self.recent_results = []  # List of (timestamp, success_bool)

    def record(self, success: bool):
        self.recent_results.append((time.time(), success))
        # Keep only recent window
        if len(self.recent_results) > self.window_size:
            self.recent_results.pop(0)

    def error_rate(self) -> float:
        """Calculate error rate in recent window."""
        if not self.recent_results:
            return 0.0
        failures = sum(1 for _, success in self.recent_results if not success)
        return failures / len(self.recent_results)

    def should_backoff(self, threshold: float = 0.3) -> bool:
        """Back off if error rate exceeds threshold."""
        return self.error_rate() > threshold
```

### Pattern 4: Integration with Existing Worker Loop

**What:** Minimal changes to processor.py _worker_loop — add rate limit check before processing job.

**Example:**
```python
# In worker/processor.py _worker_loop
while self.running:
    # ... existing circuit breaker check ...

    # NEW: Check rate limit during recovery period
    if self._rate_limiter.should_wait():
        wait_time = self._rate_limiter.wait_time()
        log_debug(f"Recovery rate limit: waiting {wait_time:.1f}s")
        time.sleep(min(wait_time, 1.0))  # Sleep in chunks for quick stop()
        continue

    # Get next pending job (existing code)
    item = get_pending(self.queue, timeout=2)
    # ... rest of processing ...

    # After job completes, record result for error monitoring
    self._rate_limiter.record_result(success=True)
```

### Anti-Patterns to Avoid

- **Aggressive recovery:** Starting at normal speed → creates thundering herd, defeats purpose
- **Static rate limits:** Fixed 5 jobs/sec throughout recovery → too slow for large backlogs, wastes recovery opportunity
- **No error monitoring:** Ramping up on schedule even if failures increase → can re-crash Plex
- **Per-job rate limiting:** Applying decorator to _process_job → breaks queue acknowledgment timing, tight coupling
- **External library dependency:** PyrateLimiter with Redis → adds complexity, Stash plugins are short-lived (no shared state needed)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token bucket math | Custom arithmetic | Existing TokenBucket pattern | Off-by-one errors in refill logic, float precision issues, tested pattern exists |
| Jitter calculation | `random.random() * delay` | `worker.backoff.calculate_delay` | Already handles full jitter correctly, prevents thundering herd |
| Time-based state persistence | Custom JSON writer | Existing patterns from circuit_breaker.py | Atomic writes (tmp + replace), error handling, file locking already solved |

**Key insight:** Most of the hard problems (exponential backoff with jitter, state persistence with atomicity, circuit breaker state machine) are ALREADY solved in the codebase from Phases 17-19. Phase 20 adds rate limiting on top of this foundation, not replacing it.

## Common Pitfalls

### Pitfall 1: Race Condition Between Circuit Close and Rate Limiter Init

**What goes wrong:** Circuit closes (Plex recovered), but rate limiter doesn't know — processes jobs at full speed before recovery period state is set.

**Why it happens:** Circuit breaker and rate limiter are separate components. Circuit closes in circuit_breaker.py, rate limiter initialized in processor.py.

**How to avoid:** Hook into circuit breaker state transitions. When circuit transitions from HALF_OPEN→CLOSED (successful recovery), immediately initialize recovery period in rate limiter.

**Warning signs:** Logs show circuit closed, but no "entering recovery period" message. Jobs process at full speed immediately after recovery.

**Example solution:**
```python
# In worker/processor.py, after circuit breaker records success
self.circuit_breaker.record_success()
if previous_state == CircuitState.HALF_OPEN and self.circuit_breaker.state == CircuitState.CLOSED:
    # Circuit just closed - start recovery period
    self._rate_limiter.start_recovery_period()
    log_info("Recovery period started: graduated rate limiting enabled")
```

### Pitfall 2: Recovery Period Persists Across Plugin Restarts Incorrectly

**What goes wrong:** Plugin restarts mid-recovery-period (5 minutes in). On restart, recovery period either:
- (A) Resets to 0 (restarts 5-minute window) → wastes time with slow rates
- (B) Doesn't persist (skips recovery) → thundering herd risk

**Why it happens:** State persistence is tricky. recovery_started_at is a timestamp, but must be interpreted correctly across restarts.

**How to avoid:** Persist recovery_started_at to recovery_state.json. On load, calculate elapsed time. If elapsed < ramp_duration, continue ramping from current position. If elapsed >= ramp_duration, recovery is done (normal rate).

**Warning signs:** After plugin restart during recovery, rate limiter behavior doesn't match expectations (too fast or too slow).

**Example solution:**
```python
def load_recovery_period(self) -> Optional[RecoveryPeriod]:
    """Load recovery period state, respecting elapsed time."""
    state = self._load_state()
    if state.recovery_started_at == 0.0:
        return None  # No active recovery

    elapsed = time.time() - state.recovery_started_at
    if elapsed >= self.ramp_duration:
        # Recovery period finished
        return None

    # Recovery in progress, continue from current position
    return RecoveryPeriod(recovery_started_at=state.recovery_started_at)
```

### Pitfall 3: Stash Plugin Short-Lived Nature Breaks Rate Limiting

**What goes wrong:** Stash plugins are NOT long-running daemons — they're invoked per-event and exit. Worker thread is daemon, stops when plugin exits. Token bucket state (tokens accumulated) resets on every invocation.

**Why it happens:** Fundamental Stash plugin architecture. Each hook invocation is a separate process.

**How to avoid:** Recognize the constraint:
- Rate limiting only works WITHIN a single worker session (while worker thread is running)
- Recovery period must span multiple invocations → persist to recovery_state.json
- Token bucket state does NOT persist → recalculate on worker start based on recovery_started_at

This is actually OKAY: during normal operation, hooks are infrequent (user actions). During recovery, worker loop runs continuously as daemon thread processing backlog. Rate limiting applies to the continuous processing session.

**Warning signs:** Rate limiting seems to "reset" between separate hook invocations. This is expected — rate limiting is for queue drain sessions, not individual hook calls.

### Pitfall 4: Error Rate Monitoring Window Too Small

**What goes wrong:** Error rate monitor uses window_size=10 jobs. If backlog is 500 jobs and 15 fail early, error rate spikes to 15/10 = 150% → backs off aggressively → queue drain takes hours.

**Why it happens:** Fixed window size doesn't scale with backlog size.

**How to avoid:** Use time-based window instead of count-based. Monitor errors in last 60 seconds, not last 10 jobs. This gives consistent behavior regardless of backlog size.

**Warning signs:** Small batches of failures cause excessive backoff during large queue drains.

**Example solution:**
```python
class ErrorRateMonitor:
    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self.results = []  # (timestamp, success_bool)

    def record(self, success: bool):
        now = time.time()
        self.results.append((now, success))
        # Remove old results outside window
        cutoff = now - self.window_seconds
        self.results = [(t, s) for t, s in self.results if t >= cutoff]

    def error_rate(self) -> float:
        if not self.results:
            return 0.0
        failures = sum(1 for _, s in self.results if not s)
        return failures / len(self.results)
```

### Pitfall 5: Normal Operation Penalized by Leftover Rate Limits

**What goes wrong:** Recovery period ends, but rate limiter continues limiting jobs → normal operations are slower than before outage.

**Why it happens:** Rate limiter doesn't cleanly exit recovery mode. Checks "am I in recovery?" on every job → adds latency.

**How to avoid:** After ramp_duration elapses, permanently exit recovery mode until next circuit open. Set recovery_started_at = 0.0, clear rate limiter state. Check is_in_recovery_period() early and cheaply.

**Warning signs:** Logs show "recovery period ended" but jobs still process slower than pre-outage baseline.

## Code Examples

Verified patterns from research and existing codebase:

### Check Recovery Period Status

```python
# Source: Pattern from existing recovery.py RecoveryScheduler
def is_in_recovery_period(self, ramp_duration: float = 300.0) -> bool:
    """Check if we're in recovery period after circuit close."""
    if self.recovery_started_at == 0.0:
        return False  # Not in recovery

    elapsed = time.time() - self.recovery_started_at
    return elapsed < ramp_duration
```

### Calculate Current Rate During Ramp

```python
# Source: Linear scaling pattern (AWS Builders Library)
def current_rate(self, now: Optional[float] = None) -> float:
    """Get current allowed rate (jobs/sec) during recovery ramp."""
    if not self.is_in_recovery_period():
        return self.target_rate  # Full speed

    if now is None:
        now = time.time()

    elapsed = now - self.recovery_started_at
    progress = elapsed / self.ramp_duration  # 0.0 → 1.0

    # Linear ramp: initial_rate → target_rate
    return self.initial_rate + (self.target_rate - self.initial_rate) * progress
```

### Token Bucket Wait Time Calculation

```python
# Source: Token bucket algorithm (Falconry implementation pattern)
def wait_time_until_next_job(self) -> float:
    """Calculate seconds to wait before processing next job."""
    if not self.is_in_recovery_period():
        return 0.0  # No rate limiting outside recovery

    # Refill tokens based on elapsed time
    now = time.time()
    elapsed = now - self.last_update
    self.tokens = min(self.capacity, self.tokens + elapsed * self.current_rate())
    self.last_update = now

    if self.tokens >= 1.0:
        self.tokens -= 1.0
        return 0.0  # Can process now

    # Need to wait for next token
    shortage = 1.0 - self.tokens
    return shortage / self.current_rate()
```

### Integration Point in Worker Loop

```python
# Source: Existing processor.py _worker_loop pattern + rate limiting
# In worker/processor.py _worker_loop, after circuit breaker check

# Check rate limit during recovery period
if hasattr(self, '_rate_limiter'):
    wait_time = self._rate_limiter.wait_time_until_next_job()
    if wait_time > 0:
        # Sleep in small chunks so stop() can interrupt quickly
        for _ in range(int(wait_time * 2)):
            if not self.running:
                return
            time.sleep(0.5)
        # Small remainder sleep
        remainder = wait_time % 0.5
        if remainder > 0 and self.running:
            time.sleep(remainder)
        continue
```

### Error Rate Adaptive Backoff

```python
# Source: Adaptive backoff pattern from Tenacity library patterns
def maybe_backoff_rate(self):
    """If error rate is high during recovery, slow down ramp."""
    if not self.is_in_recovery_period():
        return

    error_rate = self.error_monitor.error_rate()
    if error_rate > 0.3:  # 30% failure rate
        # Reduce current rate by 50% for next minute
        log_warn(f"High error rate during recovery ({error_rate:.1%}), backing off")
        self.current_rate_multiplier = 0.5
        self.backoff_until = time.time() + 60.0
    elif error_rate < 0.1 and time.time() > self.backoff_until:
        # Error rate improved, restore normal ramp
        self.current_rate_multiplier = 1.0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed retry delays | Exponential backoff with jitter | 2010s (AWS paper) | Prevents thundering herd on mass retry |
| Immediate full-speed recovery | Graduated rate limiting | 2015+ (distributed systems) | Prevents re-crashing recovered services |
| Count-based error windows | Time-based error windows | 2020+ (observability era) | Scales better with variable throughput |
| External rate limit libraries | Simple token bucket | 2025 for this use case | Libraries solve different problem (API endpoints), custom fits queue drain |

**Deprecated/outdated:**
- **Simple sleep(N) between jobs:** Wastes time when server is healthy, doesn't adapt to recovery state
- **Retry storm without jitter:** Causes synchronized retries, defeats rate limiting
- **Global rate limits without circuit awareness:** Limits normal operations unnecessarily

## Open Questions

1. **What initial_rate and target_rate values are safe?**
   - What we know: Current code has `time.sleep(0.15)` after successful jobs ≈ 6.67 jobs/sec max
   - What's unclear: Is this the actual Plex limit, or arbitrary throttle? What does Plex documentation say?
   - Recommendation: Start conservative (5 jobs/sec initial, 20 jobs/sec target) with config option to tune. Monitor logs during recovery for "too slow" vs "failures spike" feedback.

2. **Should ramp be linear, exponential, or step-based?**
   - What we know: Linear is simplest. Step-based (5→10→15→20) is easier to reason about. Exponential is fastest but hardest to tune.
   - What's unclear: Which provides best balance of safety vs speed for Plex recovery?
   - Recommendation: Start with linear (simplest math, predictable behavior). Can upgrade to step-based if user feedback shows linear is too cautious.

3. **What error_rate threshold triggers backoff?**
   - What we know: Normal operation has ~9-10% failure rate (per v1.4 stats). 30% seems reasonable threshold.
   - What's unclear: During recovery, is higher error rate expected? Should threshold be dynamic?
   - Recommendation: Use 30% threshold (3x normal) with config override. Log error rates during recovery to gather data for future tuning.

4. **Should recovery period apply to HALF_OPEN→CLOSED or only large backlogs?**
   - What we know: HALF_OPEN→CLOSED means "one test request succeeded", not necessarily "server fully healthy"
   - What's unclear: Is graduated recovery overkill if backlog is small (e.g., 5 jobs)?
   - Recommendation: Always apply recovery period after circuit close (consistent behavior). If backlog is small, recovery completes quickly anyway. Avoids "sometimes fast, sometimes slow" confusion.

## Sources

### Primary (HIGH confidence)

- [Existing codebase patterns] - worker/circuit_breaker.py, worker/recovery.py, worker/backoff.py (state persistence, circuit breaker, exponential backoff)
- [Token Bucket Algorithm](https://en.wikipedia.org/wiki/Token_bucket) - Standard CS algorithm, well-documented
- [AWS Builders Library: Avoiding Insurmountable Queue Backlogs](https://aws.amazon.com/builders-library/avoiding-insurmountable-queue-backlogs/) - Recovery period patterns

### Secondary (MEDIUM confidence)

- [Microsoft Azure: Retry Storm Antipattern](https://learn.microsoft.com/en-us/azure/architecture/antipatterns/retry-storm/) - Thundering herd prevention
- [Thundering Herd Problem: Preventing the Stampede](https://distributed-computing-musings.com/2025/08/thundering-herd-problem-preventing-the-stampede/) - 2025 overview of mitigation techniques
- [Circuit Breaker Pattern: Comprehensive Guide for 2025](https://www.shadecoder.com/topics/the-circuit-breaker-pattern-a-comprehensive-guide-for-2025) - Gradual recovery best practices
- [Token Bucket Algorithm Explained with Python](https://medium.com/@mojimich2015/token-bucket-algorithm-rate-limiting-explained-with-python-go-73a9f192fda3) - Implementation patterns
- [PyrateLimiter Documentation](https://pyratelimiter.readthedocs.io/) - Leaky bucket implementation reference
- [Falconry token-bucket GitHub](https://github.com/falconry/token-bucket) - Token bucket for Python web apps

### Tertiary (LOW confidence)

- [Building Resilient Python Applications with Tenacity](https://www.amitavroy.com/articles/building-resilient-python-applications-with-tenacity-smart-retries-for-a-fail-proof-architecture) - Adaptive backoff patterns
- [Mastering Exponential Backoff in Distributed Systems](https://betterstack.com/community/guides/monitoring/exponential-backoff/) - Monitoring integration
- [RateLimitQueue Documentation](https://ratelimitqueue.readthedocs.io/) - Queue-based rate limiting patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new dependencies needed, Python stdlib sufficient
- Architecture: MEDIUM-HIGH - Token bucket is well-understood, integration points clear, but adaptive backoff thresholds need tuning
- Pitfalls: HIGH - Well-documented in distributed systems literature, plus existing codebase provides patterns to follow

**Research date:** 2026-02-15
**Valid until:** 60 days (rate limiting is stable domain, token bucket algorithm unchanged since 1980s)
