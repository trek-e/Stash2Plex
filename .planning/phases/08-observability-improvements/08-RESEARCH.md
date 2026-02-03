# Phase 8: Observability Improvements - Research

**Researched:** 2026-02-03
**Domain:** Structured Logging, Metrics, Error Reporting
**Confidence:** HIGH

## Summary

This phase improves visibility into PlexSync's sync operations by enhancing the existing Stash plugin logging format with optional JSON structured output, adding statistics tracking for sync operations, and implementing DLQ summary logging with error categorization.

The codebase already has:
- Stash plugin log format functions (`log_trace`, `log_info`, `log_warn`, `log_error`) using `\x01{level}\x02[PlexSync ...] {msg}` format
- Timing utilities (`@timed` decorator, `OperationTimer` context manager in `plex/timing.py`)
- Cache statistics tracking (`get_stats()` on PlexCache and MatchCache)
- Error categorization via exception hierarchy (TransientError, PermanentError, PlexNotFound)
- DLQ with error_type storage and `get_recent()` for summaries

The implementation should extend these patterns rather than replace them.

**Primary recommendation:** Build on existing patterns - add a lightweight SyncStats dataclass for metrics, extend existing log functions with optional JSON mode, and enhance DLQ with error type aggregation.

## Standard Stack

The established approach for this domain:

### Core (Already in Project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python logging | stdlib | Log message handling | Already used via `logging.getLogger()` |
| dataclasses | stdlib | Stats data models | Lightweight, no dependencies |
| time.perf_counter | stdlib | Timing measurements | Already used in timing.py |

### Supporting (Optional - NOT recommended for this project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-json-logger | 3.x | JSON log formatting | NOT NEEDED - Stash plugin format required |
| structlog | 25.x | Structured logging | NOT NEEDED - overkill for Stash plugin |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom JSON | structlog | Stash plugin format requires custom output anyway; structlog adds dependency overhead |
| dataclass | TypedDict | dataclass provides better defaults, validation hints, and repr |
| File stats | SQLite stats | File is simpler; SQLite overkill for simple counters |

**Note:** The project must maintain Stash plugin log format (`\x01{level}\x02[component] message`). JSON format should be *within* the message content, not replacing the wrapper format.

**Installation:** No new dependencies required.

## Architecture Patterns

### Recommended Project Structure
```
worker/
    processor.py          # Existing - add stats integration
    stats.py              # NEW - SyncStats dataclass and persistence
plex/
    timing.py             # Existing - already has timing utilities
sync_queue/
    dlq.py                # Existing - add error aggregation method
PlexSync.py               # Existing - add stats summary on shutdown
```

### Pattern 1: Statistics Dataclass with Session Tracking
**What:** Use a simple dataclass to track sync metrics in memory, with optional file persistence
**When to use:** For lightweight metrics that don't need external tooling
**Example:**
```python
from dataclasses import dataclass, field
from typing import Dict
import time

@dataclass
class SyncStats:
    """Session statistics for sync operations."""
    # Counters
    jobs_processed: int = 0
    jobs_succeeded: int = 0
    jobs_failed: int = 0
    jobs_to_dlq: int = 0

    # Timing
    total_processing_time: float = 0.0
    session_start: float = field(default_factory=time.time)

    # Error breakdown by type
    errors_by_type: Dict[str, int] = field(default_factory=dict)

    # Match confidence tracking
    high_confidence_matches: int = 0
    low_confidence_matches: int = 0

    def record_success(self, processing_time: float):
        self.jobs_processed += 1
        self.jobs_succeeded += 1
        self.total_processing_time += processing_time

    def record_failure(self, error_type: str, processing_time: float, to_dlq: bool = False):
        self.jobs_processed += 1
        self.jobs_failed += 1
        self.total_processing_time += processing_time
        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
        if to_dlq:
            self.jobs_to_dlq += 1

    @property
    def success_rate(self) -> float:
        if self.jobs_processed == 0:
            return 0.0
        return self.jobs_succeeded / self.jobs_processed * 100

    @property
    def avg_processing_time(self) -> float:
        if self.jobs_processed == 0:
            return 0.0
        return self.total_processing_time / self.jobs_processed
```

### Pattern 2: JSON-within-Stash Format
**What:** Embed JSON content within Stash plugin log format for structured data
**When to use:** When logs need to be both human-readable in Stash UI and machine-parseable
**Example:**
```python
import json
import sys

def log_stats_json(stats: SyncStats, component: str = "PlexSync Stats"):
    """Log stats in JSON format while maintaining Stash plugin format."""
    stats_dict = {
        "processed": stats.jobs_processed,
        "succeeded": stats.jobs_succeeded,
        "failed": stats.jobs_failed,
        "to_dlq": stats.jobs_to_dlq,
        "success_rate": f"{stats.success_rate:.1f}%",
        "avg_time_ms": f"{stats.avg_processing_time * 1000:.0f}",
        "errors_by_type": stats.errors_by_type,
    }
    # Stash plugin format with JSON content
    print(f"\x01i\x02[{component}] {json.dumps(stats_dict)}", file=sys.stderr)
```

### Pattern 3: DLQ Error Aggregation
**What:** Add method to DLQ for getting error type breakdown
**When to use:** For periodic DLQ summary logging
**Example:**
```python
# Add to DeadLetterQueue class in dlq.py
def get_error_summary(self) -> Dict[str, int]:
    """Get count of DLQ entries grouped by error type."""
    with self._get_connection() as conn:
        cursor = conn.execute(
            'SELECT error_type, COUNT(*) as count FROM dead_letters GROUP BY error_type'
        )
        return {row[0]: row[1] for row in cursor.fetchall()}
```

### Pattern 4: Batch Summary Logging
**What:** Log summary after processing a batch of jobs (follow existing cache stats pattern)
**When to use:** Every N jobs or on significant events
**Example:**
```python
# Existing pattern from processor.py - extend it
def _log_batch_summary(self):
    """Log periodic summary of sync operations."""
    stats = self._stats
    dlq_summary = self.dlq.get_error_summary()

    # Human-readable summary
    log_info(
        f"Sync summary: {stats.jobs_succeeded}/{stats.jobs_processed} succeeded "
        f"({stats.success_rate:.1f}%), avg {stats.avg_processing_time*1000:.0f}ms"
    )

    # DLQ summary if items present
    if dlq_summary:
        total = sum(dlq_summary.values())
        breakdown = ", ".join(f"{count} {err_type}" for err_type, count in dlq_summary.items())
        log_warn(f"DLQ contains {total} items: {breakdown}")
```

### Anti-Patterns to Avoid
- **Replacing Stash log format:** The `\x01{level}\x02[component]` format is required for Stash UI integration - don't replace it
- **Heavy dependencies:** Don't add structlog/OpenTelemetry for a plugin - keep it lightweight
- **Metric databases:** Don't add Prometheus/SQLite for metrics - simple file or in-memory is sufficient
- **Overly frequent logging:** Follow existing pattern of logging every 10 jobs, not every job

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Timing measurement | Custom stopwatch | Existing `OperationTimer` | Already in `plex/timing.py`, tested |
| Error type tracking | String parsing | Existing `error_type` in DLQ | Already stored on DLQ add() |
| Cache stats | Manual counters | Existing `get_stats()` | PlexCache and MatchCache already track hits/misses |
| Exception hierarchy | New error types | Existing TransientError/PermanentError | Already have error classification in `plex/exceptions.py` |

**Key insight:** The codebase already has 80% of the observability infrastructure - this phase is about surfacing and formatting that data, not building new collection mechanisms.

## Common Pitfalls

### Pitfall 1: Breaking Stash UI Integration
**What goes wrong:** Changing log format breaks Stash's ability to parse log levels
**Why it happens:** Assuming JSON format can replace Stash's custom format
**How to avoid:** Keep `\x01{level}\x02[component] message` format, put JSON inside `message`
**Warning signs:** Logs appear but without color/level in Stash UI

### Pitfall 2: Stats Reset on Process Restart
**What goes wrong:** Losing accumulated stats when Stash restarts plugin process
**Why it happens:** Stash plugin runs as subprocess, stats are in memory
**How to avoid:** Option to persist stats to simple JSON file, reload on startup
**Warning signs:** Stats always show small numbers despite running for days

### Pitfall 3: Log Volume Explosion
**What goes wrong:** JSON logging of every operation floods Stash logs
**Why it happens:** Logging at TRACE/DEBUG level with verbose JSON
**How to avoid:** JSON stats only at INFO level, only on batch boundaries (every 10 jobs)
**Warning signs:** Stash log file grows rapidly, UI sluggish

### Pitfall 4: Incomplete Error Context
**What goes wrong:** Errors logged but can't diagnose root cause from logs alone
**Why it happens:** Logging error type without actionable context
**How to avoid:** Include: scene_id, file path attempted, error type, suggested action
**Warning signs:** Need to reproduce errors to understand them

### Pitfall 5: DLQ Summary Missing Error Types
**What goes wrong:** DLQ summary just shows count, not breakdown by error
**Why it happens:** Not utilizing the error_type column already in DLQ schema
**How to avoid:** Group by error_type in summary query
**Warning signs:** "5 items in DLQ" without knowing what kind of errors

## Code Examples

Verified patterns from the existing codebase:

### Existing Stash Plugin Log Format (from PlexSync.py)
```python
# This is the REQUIRED format - do not change
def log_trace(msg): print(f"\x01t\x02[PlexSync] {msg}", file=sys.stderr)
def log_debug(msg): print(f"\x01d\x02[PlexSync] {msg}", file=sys.stderr)
def log_info(msg): print(f"\x01i\x02[PlexSync] {msg}", file=sys.stderr)
def log_warn(msg): print(f"\x01w\x02[PlexSync] {msg}", file=sys.stderr)
def log_error(msg): print(f"\x01e\x02[PlexSync] {msg}", file=sys.stderr)
```

### Existing Timing Utilities (from plex/timing.py)
```python
from plex.timing import OperationTimer

# Already available - use for job timing
with OperationTimer("sync job") as timer:
    process_job(job)
# timer.elapsed contains duration in seconds
```

### Existing Cache Stats Pattern (from processor.py)
```python
def _log_cache_stats(self):
    """Log cache hit/miss statistics."""
    library_cache, match_cache = self._get_caches()
    if library_cache is not None:
        stats = library_cache.get_stats()
        total = stats.get('hits', 0) + stats.get('misses', 0)
        if total > 0:
            hit_rate = stats['hits'] / total * 100
            log_debug(f"Library cache: {hit_rate:.1f}% hit rate")
```

### Existing DLQ Error Storage (from dlq.py)
```python
# Already storing error_type on DLQ add
def add(self, job: dict, error: Exception, retry_count: int):
    conn.execute(
        '''INSERT INTO dead_letters
           (job_id, scene_id, job_data, error_type, error_message, stack_trace, retry_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (
            job.get('pqid'),
            job.get('scene_id'),
            pickle.dumps(job),
            type(error).__name__,  # <-- error_type already captured
            str(error),
            traceback.format_exc(),
            retry_count
        )
    )
```

### Existing Periodic Logging Pattern (from processor.py)
```python
# Follow this pattern for stats logging interval
self._jobs_since_dlq_log += 1
if self._jobs_since_dlq_log >= self._dlq_log_interval:  # Every 10 jobs
    self._log_dlq_status()
    self._log_cache_stats()
    self._jobs_since_dlq_log = 0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Plain text logs | JSON structured logs | ~2023 | Machine-parseable, but Stash requires custom format |
| Manual counters | Dataclass-based stats | Python 3.7+ | Cleaner code, better defaults |
| In-memory only | Optional persistence | N/A | Survive process restarts |

**Deprecated/outdated:**
- Using external logging services (Prometheus, Datadog) for plugin - overkill, adds complexity
- Heavy structured logging libraries (structlog) - unnecessary for Stash plugin context

## Open Questions

Things that couldn't be fully resolved:

1. **JSON format adoption**
   - What we know: JSON is standard for observability, but Stash UI needs custom format
   - What's unclear: Whether users actually want/need JSON-parseable logs
   - Recommendation: Implement as opt-in config option (`log_format: "json"` or `"text"`), default to text

2. **Stats persistence strategy**
   - What we know: In-memory stats reset on process restart
   - What's unclear: How long Stash plugin processes typically live
   - Recommendation: Persist to simple JSON file, reload on startup, merge cumulative totals

3. **Match confidence histogram granularity**
   - What we know: Currently binary HIGH/LOW confidence
   - What's unclear: Whether finer granularity (percentage scores) would be useful
   - Recommendation: Track HIGH/LOW counts as specified; defer percentage scores to future phase

## Sources

### Primary (HIGH confidence)
- Existing codebase analysis: `worker/processor.py`, `plex/timing.py`, `sync_queue/dlq.py`, `plex/cache.py`
- Python standard library documentation: `dataclasses`, `json`, `time`

### Secondary (MEDIUM confidence)
- [Python Logging Best Practices - Better Stack](https://betterstack.com/community/guides/logging/python/python-logging-best-practices/)
- [JSON Logging Guide - Better Stack](https://betterstack.com/community/guides/logging/json-logging/)
- [structlog Documentation](https://www.structlog.org/en/stable/standard-library.html)
- [Python json-logger](https://github.com/madzak/python-json-logger)

### Tertiary (LOW confidence)
- Web search results for Python observability patterns 2026

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Based on existing codebase patterns
- Architecture: HIGH - Extending proven patterns already in use
- Pitfalls: HIGH - Based on Stash plugin constraints and existing code

**Research date:** 2026-02-03
**Valid until:** 60 days (patterns are stable, no external dependencies)

---

## Implementation Recommendations

Based on CONTEXT.md decisions and codebase analysis:

### 1. Logging Format (Claude's Discretion)
**Recommendation:** NO JSON format by default, but provide JSON batch summaries at INFO level
- Rationale: Stash UI integration is primary; JSON within message is sufficient for diagnosis
- Format: `\x01i\x02[PlexSync Stats] {"processed": 50, "succeeded": 48, ...}`

### 2. Batch Summary Frequency
**Recommendation:** Every 10 jobs (matching existing `_dlq_log_interval`)
- Rationale: Consistent with established pattern, proven not to flood logs

### 3. Metrics to Track
**Recommendation:** Both counts AND timing
- Counts: `jobs_processed`, `jobs_succeeded`, `jobs_failed`, `jobs_to_dlq`
- Timing: `avg_processing_time`, `total_processing_time`
- Match confidence: `high_confidence_matches`, `low_confidence_matches`

### 4. Stats Storage
**Recommendation:** Session-only with cumulative totals in JSON file
- Location: `{data_dir}/stats.json`
- On startup: Load cumulative totals, start new session
- On batch log: Update file with merged cumulative stats

### 5. Error Categorization
**Recommendation:** By cause (matching existing exception hierarchy)
- Categories: `TransientError`, `PermanentError`, `PlexNotFound`, `Unknown`
- Already have this via `type(error).__name__` in DLQ

### 6. Actionable Hints
**Recommendation:** Yes, include hints for common errors
- `PlexNotFound`: "Check if file exists in Plex library, try library scan"
- `PlexPermanentError`: "Check Plex authentication token"
- `TransientError`: "Will retry automatically; if persists, check Plex connectivity"

### 7. Error Deduplication
**Recommendation:** Count-based deduplication in DLQ summary
- Instead of listing each error: "5 items in DLQ: 3 PlexNotFound, 2 PermanentError"
- Detailed list available via existing `get_recent()` method
