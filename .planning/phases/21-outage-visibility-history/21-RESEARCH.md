# Phase 21: Outage Visibility & History - Research

**Researched:** 2026-02-15
**Domain:** Outage tracking, status display enhancement, metrics reporting
**Confidence:** HIGH

## Summary

Phase 21 adds visibility and historical tracking to the outage resilience system built in Phases 17-20. The challenge is enhancing the existing "View Queue Status" task with circuit breaker state, tracking outage history in a space-efficient manner, and creating a comprehensive outage summary report.

The existing infrastructure provides all the raw data needed: CircuitBreaker tracks state/opened_at in circuit_breaker.json, RecoveryScheduler tracks last_recovery_time/recovery_count in recovery_state.json, and RecoveryRateLimiter tracks recovery_started_at. The missing piece is outage history — a persistent log of past outages with start/end times, duration, and jobs affected.

The key insight from research: Use `collections.deque` with `maxlen=30` for a fixed-size circular buffer. This provides automatic FIFO overflow (oldest entries automatically drop when limit reached), O(1) append performance, built-in serialization to JSON via list(), and matches the "last 30 outages" requirement exactly.

**Primary recommendation:** Create OutageHistory manager with deque-backed storage in outage_history.json, record outage start when circuit opens (from CircuitBreaker), record outage end when circuit closes (from RecoveryScheduler), enhance handle_queue_status() to display circuit state and recovery timing, and create handle_outage_summary() task for detailed metrics (MTTR, MTBF, total downtime).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib collections.deque | 3.x | Fixed-size circular buffer | Built-in, O(1) append, automatic FIFO overflow, industry standard for ring buffers |
| Python stdlib json | 3.x | State persistence | Same pattern as CircuitBreaker, RecoveryScheduler |
| Python stdlib datetime | 3.x | Time formatting | Human-readable timestamps and duration formatting |
| Python stdlib time | 3.x | Timing calculations | time.time() for timestamps |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| dataclasses | 3.7+ | OutageRecord structure | Structured outage data (start, end, duration, jobs_affected) |
| typing | 3.5+ | Type annotations | Optional[float], List[OutageRecord] for type safety |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| deque(maxlen=30) | Manual list pruning | deque is built-in, automatic, O(1) vs manual pruning on every write |
| JSON persistence | SQLite | JSON is simpler, matches existing patterns, adequate for 30 records |
| datetime.timedelta str | humanize library | stdlib-only keeps zero dependencies, sufficient for "5m 30s" formatting |
| Metrics in memory | Calculated on demand | Pre-calculated metrics simpler but on-demand avoids state staleness |

**Installation:**
No new dependencies required — all stdlib.

## Architecture Patterns

### Recommended Project Structure
```
worker/
├── outage_history.py        # NEW: OutageHistory manager class
├── circuit_breaker.py        # EXISTING: Record outage start on _open()
├── recovery.py               # EXISTING: Record outage end on recovery complete
└── processor.py              # EXISTING: Track jobs_affected count

data/
└── outage_history.json       # NEW: Persisted circular buffer of last 30 outages
```

### Pattern 1: Circular Buffer with collections.deque
**What:** Fixed-size ring buffer using `deque(maxlen=30)` stores last 30 outages with automatic FIFO overflow.

**When to use:** When tracking bounded historical data (e.g., "last N events"). Prevents unbounded growth, simpler than manual pruning, built-in to stdlib.

**Example:**
```python
# Source: Python docs - collections.deque
from collections import deque
from dataclasses import dataclass, asdict
import json
import time

@dataclass
class OutageRecord:
    """Single outage event record."""
    started_at: float                # time.time() when circuit opened
    ended_at: float | None = None    # time.time() when circuit closed (None = ongoing)
    duration: float | None = None    # Seconds of downtime (None = ongoing)
    jobs_affected: int = 0            # Jobs moved to DLQ during outage

class OutageHistory:
    """Manages circular buffer of last 30 outages."""

    STATE_FILE = 'outage_history.json'
    MAX_OUTAGES = 30

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.state_path = os.path.join(data_dir, self.STATE_FILE)
        self._history: deque = deque(maxlen=self.MAX_OUTAGES)
        self._load_state()

    def _load_state(self) -> None:
        """Load history from disk."""
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r') as f:
                    data = json.load(f)
                # Reconstruct deque from list
                self._history = deque(
                    [OutageRecord(**record) for record in data],
                    maxlen=self.MAX_OUTAGES
                )
        except (json.JSONDecodeError, TypeError, KeyError):
            self._history = deque(maxlen=self.MAX_OUTAGES)

    def _save_state(self) -> None:
        """Save history to disk atomically."""
        tmp_path = self.state_path + '.tmp'
        with open(tmp_path, 'w') as f:
            # Convert deque to list of dicts for JSON
            json.dump([asdict(r) for r in self._history], f, indent=2)
        os.replace(tmp_path, self.state_path)

    def record_outage_start(self, started_at: float) -> None:
        """Record circuit breaker opening (outage start)."""
        record = OutageRecord(started_at=started_at)
        self._history.append(record)  # Oldest auto-dropped if len=30
        self._save_state()

    def record_outage_end(self, ended_at: float, jobs_affected: int = 0) -> None:
        """Record circuit breaker closing (outage end)."""
        if len(self._history) == 0:
            return  # No ongoing outage

        # Update most recent outage (should be ongoing)
        latest = self._history[-1]
        if latest.ended_at is None:
            latest.ended_at = ended_at
            latest.duration = ended_at - latest.started_at
            latest.jobs_affected = jobs_affected
            self._save_state()
```

### Pattern 2: Human-Readable Duration Formatting
**What:** Convert timedelta/seconds to readable format like "5m 30s" or "2h 15m" without external dependencies.

**When to use:** Status displays for user consumption. Avoid raw timestamps (1708019400.0) in favor of relative time or duration strings.

**Example:**
```python
# Source: Python datetime docs, common pattern in monitoring tools
import datetime

def format_duration(seconds: float) -> str:
    """Format duration in human-readable form.

    Examples:
        format_duration(65) -> "1m 5s"
        format_duration(3661) -> "1h 1m"
        format_duration(86401) -> "1d 0h"
    """
    if seconds < 0:
        return "0s"

    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or len(parts) == 0:
        parts.append(f"{secs}s")

    # Show at most 2 units for brevity
    return " ".join(parts[:2])

def format_elapsed_since(timestamp: float) -> str:
    """Format elapsed time since timestamp.

    Examples:
        format_elapsed_since(time.time() - 30) -> "30s ago"
        format_elapsed_since(time.time() - 3661) -> "1h 1m ago"
    """
    elapsed = time.time() - timestamp
    return f"{format_duration(elapsed)} ago"
```

### Pattern 3: Enhanced Status Display
**What:** Extend existing handle_queue_status() to show circuit state, recovery timing, and health check status.

**When to use:** Users need visibility into circuit breaker state and recent outages without running separate tasks.

**Example:**
```python
# Source: Existing handle_queue_status() in Stash2Plex.py
def handle_queue_status():
    """Display current queue and DLQ statistics."""
    data_dir = get_plugin_data_dir()

    # Existing queue stats...
    log_info("=== Queue Status ===")
    # ... existing code ...

    # NEW: Circuit breaker status
    log_info("=== Circuit Breaker Status ===")
    from worker.circuit_breaker import CircuitBreaker, CircuitState
    cb_file = os.path.join(data_dir, 'circuit_breaker.json')

    if os.path.exists(cb_file):
        with open(cb_file, 'r') as f:
            cb_data = json.load(f)
        state = cb_data.get('state', 'closed').upper()
        log_info(f"State: {state}")

        if state == "OPEN" and cb_data.get('opened_at'):
            elapsed = time.time() - cb_data['opened_at']
            log_info(f"Opened: {format_elapsed_since(cb_data['opened_at'])}")
            log_info(f"Duration: {format_duration(elapsed)}")
    else:
        log_info("State: CLOSED")

    # NEW: Recovery status
    from worker.recovery import RecoveryScheduler
    scheduler = RecoveryScheduler(data_dir)
    state = scheduler.load_state()

    if state.last_check_time > 0:
        log_info(f"Last health check: {format_elapsed_since(state.last_check_time)}")

    if state.last_recovery_time > 0:
        log_info(f"Last recovery: {format_elapsed_since(state.last_recovery_time)}")
        log_info(f"Total recoveries: {state.recovery_count}")
```

### Pattern 4: Outage Metrics (MTTR, MTBF, Availability)
**What:** Calculate industry-standard reliability metrics from outage history for summary reports.

**When to use:** Operational visibility into system reliability patterns. MTTR identifies slow recoveries, MTBF identifies frequent instability.

**Example:**
```python
# Source: Industry standard SRE metrics (Atlassian, Google SRE)
from typing import List, Dict

def calculate_outage_metrics(history: List[OutageRecord]) -> Dict[str, float]:
    """Calculate MTTR, MTBF, and availability from outage history.

    MTTR (Mean Time To Repair): Average duration of outages
    MTBF (Mean Time Between Failures): Average time between outage starts
    Availability: (MTBF / (MTBF + MTTR)) * 100

    Returns:
        Dict with keys: mttr, mtbf, availability, total_downtime, outage_count
    """
    completed = [o for o in history if o.ended_at is not None]

    if len(completed) == 0:
        return {
            'mttr': 0.0,
            'mtbf': 0.0,
            'availability': 100.0,
            'total_downtime': 0.0,
            'outage_count': 0
        }

    # MTTR: average outage duration
    total_downtime = sum(o.duration for o in completed)
    mttr = total_downtime / len(completed)

    # MTBF: average time between outage starts
    if len(completed) >= 2:
        time_span = completed[-1].started_at - completed[0].started_at
        mtbf = time_span / (len(completed) - 1)
    else:
        mtbf = 0.0

    # Availability: uptime percentage
    if mtbf > 0:
        availability = (mtbf / (mtbf + mttr)) * 100.0
    else:
        availability = 100.0

    return {
        'mttr': mttr,
        'mtbf': mtbf,
        'availability': availability,
        'total_downtime': total_downtime,
        'outage_count': len(completed)
    }
```

### Pattern 5: Outage Summary Report Task
**What:** New Stash UI task displays detailed outage statistics and recent outage list.

**When to use:** Users need comprehensive outage history for debugging or capacity planning.

**Example:**
```python
# Source: Existing task patterns in Stash2Plex.py (handle_health_check, handle_queue_status)
def handle_outage_summary():
    """Display comprehensive outage statistics and history."""
    try:
        data_dir = get_plugin_data_dir()
        from worker.outage_history import OutageHistory

        history = OutageHistory(data_dir)
        records = list(history._history)

        log_info("=== Outage Summary Report ===")

        if len(records) == 0:
            log_info("No outages recorded")
            return

        # Calculate metrics
        metrics = calculate_outage_metrics(records)

        log_info(f"Total outages tracked: {len(records)}")
        log_info(f"Completed outages: {metrics['outage_count']}")
        log_info(f"Total downtime: {format_duration(metrics['total_downtime'])}")

        if metrics['outage_count'] > 0:
            log_info(f"MTTR (mean time to repair): {format_duration(metrics['mttr'])}")

        if metrics['mtbf'] > 0:
            log_info(f"MTBF (mean time between failures): {format_duration(metrics['mtbf'])}")
            log_info(f"Availability: {metrics['availability']:.2f}%")

        # Recent outages list
        log_info("=== Recent Outages ===")
        for i, record in enumerate(reversed(records[-10:])):  # Last 10
            dt = datetime.datetime.fromtimestamp(record.started_at)
            started = dt.strftime('%Y-%m-%d %H:%M:%S')

            if record.ended_at:
                status = f"{format_duration(record.duration)}"
                if record.jobs_affected > 0:
                    status += f", {record.jobs_affected} jobs affected"
            else:
                status = "ONGOING"

            log_info(f"{len(records) - i}. {started} - {status}")

        log_info("=== End Report ===")

    except Exception as e:
        log_error(f"Failed to generate outage summary: {e}")
        import traceback
        traceback.print_exc()

# Add to task dispatch table
_MANAGEMENT_HANDLERS = {
    # ... existing handlers ...
    'outage_summary': lambda args: handle_outage_summary(),
}
```

### Anti-Patterns to Avoid

- **Recording outages in DLQ:** DLQ is for failed jobs, not outage events. Outage history is separate concern.
- **Calculating metrics on every write:** Calculate on-demand in report task, not on every state save (wasteful).
- **Unbounded history growth:** Always use fixed-size buffer. "Last 30" is reasonable, prevents JSON bloat.
- **Recording every circuit state change:** Only record OPEN (outage start) and CLOSED after OPEN (outage end). HALF_OPEN is transient.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Circular buffer | Manual list pruning/rotation | collections.deque(maxlen=N) | Built-in, O(1) append, automatic overflow, well-tested |
| Duration formatting | String concatenation | datetime.timedelta or simple divmod | Handles edge cases (0s, negative, large values) |
| Time math | Manual timestamp arithmetic | time.time() subtraction | Simpler, less error-prone than datetime arithmetic for durations |
| JSON atomicity | Direct write | tmp file + os.replace() | Prevents corruption from interrupted writes (existing pattern) |

**Key insight:** Python stdlib provides all needed primitives. deque(maxlen) is purpose-built for fixed-size ring buffers — automatic, efficient, serializable.

## Common Pitfalls

### Pitfall 1: Recording Outage Start/End Without Race Protection
**What goes wrong:** Concurrent plugin invocations could record duplicate outage starts or miss outage ends.

**Why it happens:** CircuitBreaker uses file locking for state transitions, but OutageHistory needs coordination too.

**How to avoid:** Record outage start in CircuitBreaker._open() (already atomic via _save_state_locked), record outage end in RecoveryScheduler.record_health_check() when circuit closes (single writer). Don't record from multiple locations.

**Warning signs:** Duplicate outages with same started_at, outages with ended_at=None that should be closed.

### Pitfall 2: Storing Raw Timestamps in Display Output
**What goes wrong:** Users see "1708019400.0" instead of "2024-02-15 10:30:00" or "5m ago".

**Why it happens:** time.time() returns Unix timestamp (float seconds since epoch).

**How to avoid:** Convert timestamps to datetime for absolute times (datetime.fromtimestamp()), use format_elapsed_since() for relative times ("5m ago"), use format_duration() for time spans.

**Warning signs:** Log output contains large floating point numbers, users report timestamps are "unreadable".

### Pitfall 3: Calculating MTBF with Single Outage
**What goes wrong:** Division by zero or nonsensical MTBF from insufficient data.

**Why it happens:** MTBF requires at least 2 outages to calculate time between failures.

**How to avoid:** Check `len(completed) >= 2` before calculating MTBF, return 0.0 or "N/A" for insufficient data.

**Warning signs:** ZeroDivisionError, negative MTBF, MTBF from first outage.

### Pitfall 4: Not Handling Ongoing Outages in Metrics
**What goes wrong:** Metrics exclude current outage, giving false impression of stability.

**Why it happens:** Ongoing outages have ended_at=None and duration=None.

**How to avoid:** Calculate current outage duration as `time.time() - started_at`, include in display but exclude from MTTR (not yet resolved).

**Warning signs:** Circuit OPEN but "Total outages: 0", metrics show 100% availability during active outage.

### Pitfall 5: Jobs Affected Count Synchronization
**What goes wrong:** jobs_affected doesn't match actual DLQ additions during outage.

**Why it happens:** Multiple plugin invocations during outage, each adding to DLQ independently.

**How to avoid:** Track jobs_affected separately (count DLQ additions during outage window), update when outage ends, or calculate from DLQ timestamps (jobs added between started_at and ended_at).

**Warning signs:** jobs_affected=0 for outages with DLQ items, count doesn't match DLQ error summary.

## Code Examples

Verified patterns from existing codebase:

### Enhanced Queue Status Display
```python
# Source: Stash2Plex.py handle_queue_status()
# Add after reconciliation status section

# Circuit Breaker Status (VISB-01)
log_info("=== Circuit Breaker Status ===")
cb_file = os.path.join(data_dir, 'circuit_breaker.json')

if os.path.exists(cb_file):
    with open(cb_file, 'r') as f:
        cb_data = json.load(f)
    state = cb_data.get('state', 'closed').upper()
    log_info(f"State: {state}")

    if state == "OPEN":
        if cb_data.get('opened_at'):
            elapsed = time.time() - cb_data['opened_at']
            log_info(f"Opened: {format_elapsed_since(cb_data['opened_at'])}")
        failure_count = cb_data.get('failure_count', 0)
        if failure_count > 0:
            log_info(f"Consecutive failures before opening: {failure_count}")
    elif state == "HALF_OPEN":
        log_info("Testing recovery...")
else:
    log_info("State: CLOSED")

# Recovery Timing (VISB-01)
from worker.recovery import RecoveryScheduler
scheduler = RecoveryScheduler(data_dir)
recovery_state = scheduler.load_state()

if recovery_state.last_check_time > 0:
    log_info(f"Last health check: {format_elapsed_since(recovery_state.last_check_time)}")

if recovery_state.last_recovery_time > 0:
    log_info(f"Last recovery: {format_elapsed_since(recovery_state.last_recovery_time)}")
    log_info(f"Total recoveries: {recovery_state.recovery_count}")
```

### Recording Outage Start (in CircuitBreaker)
```python
# Source: worker/circuit_breaker.py CircuitBreaker._open()
# Add after existing _open() logic

def _open(self) -> None:
    """Transition to OPEN state."""
    self._state = CircuitState.OPEN
    self._opened_at = time.time()
    self._failure_count = 0
    self._success_count = 0
    log_info(f"Circuit breaker OPENED after {self._failure_threshold} consecutive failures")
    self._save_state_locked()

    # NEW: Record outage start in history
    if hasattr(self, '_outage_history'):
        self._outage_history.record_outage_start(self._opened_at)
```

### Recording Outage End (in RecoveryScheduler)
```python
# Source: worker/recovery.py RecoveryScheduler.record_health_check()
# Add when circuit closes after recovery

if circuit_breaker.state == CircuitState.CLOSED:
    # Recovery complete!
    state.last_recovery_time = time.time()
    state.recovery_count += 1
    state.consecutive_successes = 0
    log_info(f"Recovery detected: Plex is back online (recovery #{state.recovery_count})")

    # NEW: Record outage end in history
    if hasattr(self, '_outage_history'):
        # Count jobs affected (from DLQ during outage window)
        jobs_affected = self._count_jobs_during_outage(opened_at, state.last_recovery_time)
        self._outage_history.record_outage_end(state.last_recovery_time, jobs_affected)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No outage tracking | Persistent outage history | Phase 21 (v1.5) | Users can see outage patterns, MTTR trends |
| Circuit state in logs only | Circuit state in status UI | Phase 21 (v1.5) | Users don't need to grep logs for current state |
| Manual calculation of downtime | Automated MTTR/MTBF metrics | Phase 21 (v1.5) | Operational visibility into reliability |
| List-based history | deque(maxlen) circular buffer | Phase 21 (v1.5) | Bounded memory, automatic overflow |

**Deprecated/outdated:**
- None — this is net-new functionality building on Phase 17-20 foundation.

## Open Questions

1. **Jobs affected count calculation**
   - What we know: DLQ tracks failed_at timestamp for each entry
   - What's unclear: Best approach — count at outage end from DLQ timestamps, or track incrementally during outage?
   - Recommendation: Calculate at outage end from DLQ (simpler, no concurrency issues). Query DLQ for entries with `failed_at` between `started_at` and `ended_at`.

2. **Health check timing display**
   - What we know: RecoveryState.last_check_time tracks when last check ran
   - What's unclear: Should we show "next scheduled check" (last_check_time + 5s)?
   - Recommendation: Yes, but only when circuit is OPEN. Show "Next check: in 2s" for user expectation setting.

3. **Outage start on plugin restart during outage**
   - What we know: Circuit state persists, so circuit is OPEN on restart
   - What's unclear: Does this create duplicate outage records?
   - Recommendation: No — CircuitBreaker._load_state() doesn't call _open(), so no record_outage_start(). Only state transitions call _open(). This is correct behavior.

## Sources

### Primary (HIGH confidence)
- Existing codebase: worker/circuit_breaker.py, worker/recovery.py, worker/stats.py (state persistence patterns)
- Existing codebase: Stash2Plex.py handle_queue_status() (display pattern)
- Python documentation: collections.deque maxlen parameter (official docs)
- Python documentation: datetime.timedelta formatting (official docs)

### Secondary (MEDIUM confidence)
- [Circular buffer - Wikipedia](https://en.wikipedia.org/wiki/Circular_buffer) - Ring buffer data structure
- [Python's deque: Implement Efficient Queues and Stacks – Real Python](https://realpython.com/python-deque/) - deque best practices
- [Incident Management - MTBF, MTTR, MTTA, and MTTF - Atlassian](https://www.atlassian.com/incident-management/kpis/common-metrics) - Industry standard metrics
- [MTTR, MTBF, MTTA & MTTF — Metrics, examples, challenges, and tips - Hyperping](https://hyperping.com/blog/mttr-guide) - Reliability metrics calculations

### Tertiary (LOW confidence)
- None — all findings verified with official docs or existing codebase patterns.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib, verified in codebase
- Architecture: HIGH - Extends existing patterns (RecoveryScheduler, handle_queue_status)
- Pitfalls: HIGH - Based on concurrency patterns from Phase 17-20
- Metrics calculations: MEDIUM - Industry standard formulas, but interpretation may vary

**Research date:** 2026-02-15
**Valid until:** 30 days (stable domain — outage tracking patterns unlikely to change)
