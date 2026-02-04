# Phase 13: Dynamic Queue Timeout - Research

**Researched:** 2026-02-03
**Domain:** Stash plugin timeout management, processing time tracking, dynamic timeout calculation
**Confidence:** MEDIUM

## Summary

This phase improves the existing dynamic timeout logic in `Stash2Plex.py` (lines 850-876) to use actual measured processing times rather than a fixed 2-second-per-item estimate. The current implementation uses `max_wait = max(30, min(initial_size * 2, 600))` which is crude and may be inaccurate.

Research into Stash plugin timeout limits revealed important findings:
1. **Stash does NOT expose timeout limit information** to plugins - there is no API to query maximum allowed execution time
2. **Stash scheduled tasks support optional timeout configuration** via YAML (`timeout: 10`), but this applies to cron-scheduled scripts, not plugin tasks triggered by hooks or UI
3. **Plugin tasks use Go's context.Context** for timeout/cancellation, but plugins cannot access or modify this context
4. The practical timeout limit for Stash plugin tasks is **not documented** - it appears to be "until Stash kills the process" or the user cancels

Given these constraints, the dynamic timeout implementation must:
- Track actual processing times per item
- Calculate timeout based on `items_in_queue * avg_time_per_item + safety_buffer`
- Cap timeout at a sensible maximum (existing 600s seems reasonable)
- Provide graceful degradation when timeout is exceeded (direct users to Process Queue)

**Primary recommendation:** Extend the existing `SyncStats` class to provide a rolling average processing time, use this for timeout calculation, and improve the timeout message to guide users to the Process Queue task.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| worker/stats.py | N/A | SyncStats class with processing time tracking | Already tracks `total_processing_time` and `jobs_processed` |
| time (stdlib) | N/A | Timing measurements | Already in use throughout codebase |
| dataclasses (stdlib) | N/A | Stats dataclass structure | Already used by SyncStats |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | N/A | Persist timing data to disk | Already used by SyncStats.save_to_file() |
| os (stdlib) | N/A | File path operations | Already in use |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Simple average from SyncStats | Exponential moving average (EMA) | EMA gives more weight to recent times, better for changing conditions; simple average is already implemented |
| Per-session tracking | Persistent tracking | Persistent survives restarts but may include stale historical data; per-session is fresh but starts at 0 |
| Custom timing module | Extend SyncStats | Keep changes minimal; SyncStats already has all the infrastructure |

**Installation:**
```bash
# No new dependencies - all functionality can be built on existing SyncStats
```

## Architecture Patterns

### Recommended Implementation Structure

Extend existing infrastructure rather than creating new modules:

```
worker/stats.py
  |
  +-- SyncStats (existing)
        |
        +-- avg_processing_time property (existing!)
        +-- NEW: get_estimated_timeout(item_count, buffer_factor=1.5)
        +-- NEW: DEFAULT_TIME_PER_ITEM constant (fallback for cold start)

Stash2Plex.py
  |
  +-- main() timeout calculation (lines 850-876)
        |
        +-- REPLACE static formula with stats.get_estimated_timeout()
        +-- IMPROVE timeout message with Process Queue guidance
```

### Pattern 1: Using Existing SyncStats for Timeout Calculation

**What:** Leverage the already-tracked `total_processing_time` and `jobs_processed` from SyncStats
**When to use:** When stats have been collected from previous processing
**Example:**
```python
# Source: Derived from worker/stats.py existing implementation
class SyncStats:
    # ... existing fields ...

    # Default estimate when no historical data exists
    DEFAULT_TIME_PER_ITEM = 2.0  # seconds

    def get_estimated_timeout(
        self,
        item_count: int,
        buffer_factor: float = 1.5,
        min_timeout: float = 30.0,
        max_timeout: float = 600.0
    ) -> float:
        """
        Calculate estimated timeout for processing item_count items.

        Uses avg_processing_time if available, falls back to default.
        Applies buffer_factor for safety margin.

        Args:
            item_count: Number of items to process
            buffer_factor: Multiplier for safety margin (1.5 = 50% buffer)
            min_timeout: Minimum timeout in seconds
            max_timeout: Maximum timeout in seconds

        Returns:
            Calculated timeout in seconds, clamped to [min_timeout, max_timeout]
        """
        if self.jobs_processed > 0:
            time_per_item = self.avg_processing_time
        else:
            time_per_item = self.DEFAULT_TIME_PER_ITEM

        estimated = item_count * time_per_item * buffer_factor
        return max(min_timeout, min(estimated, max_timeout))
```

### Pattern 2: Cold Start Handling

**What:** Handle case when no historical timing data exists
**When to use:** First run, or when stats file is missing/corrupt
**Example:**
```python
# Source: Conceptual pattern for cold start handling
# Default estimate based on typical Plex API response times
DEFAULT_TIME_PER_ITEM = 2.0  # Conservative default

def get_time_per_item(stats: SyncStats) -> float:
    """
    Get average time per item, with fallback for cold start.

    Returns historical average if available, else default.
    """
    if stats.jobs_processed >= 5:  # Require minimum sample size
        return stats.avg_processing_time
    elif stats.jobs_processed > 0:
        # Have some data but not enough - blend with default
        weight = stats.jobs_processed / 5.0
        return (weight * stats.avg_processing_time) + ((1 - weight) * DEFAULT_TIME_PER_ITEM)
    else:
        return DEFAULT_TIME_PER_ITEM
```

### Pattern 3: Timeout Calculation with Safety Buffer

**What:** Calculate timeout with configurable safety margin
**When to use:** Always - real processing times vary
**Example:**
```python
# Source: Derived from existing Stash2Plex.py timeout logic
def calculate_dynamic_timeout(
    item_count: int,
    avg_time_per_item: float,
    buffer_factor: float = 1.5,  # 50% safety margin
    min_timeout: float = 30.0,
    max_timeout: float = 600.0  # 10 minutes - current cap
) -> float:
    """
    Calculate dynamic timeout based on queue size and processing time.

    Formula: items * avg_time * buffer, clamped to [min, max]
    """
    raw_estimate = item_count * avg_time_per_item * buffer_factor
    return max(min_timeout, min(raw_estimate, max_timeout))
```

### Pattern 4: Enhanced Timeout Message with Process Queue Guidance

**What:** Provide actionable guidance when timeout occurs
**When to use:** When queue processing times out before completion
**Example:**
```python
# Source: Conceptual improvement to Stash2Plex.py timeout handling
if waited >= max_wait and queue.size > 0:
    remaining = queue.size
    estimated_time = remaining * avg_time_per_item

    log_warn(
        f"Timeout after {max_wait}s with {remaining} items remaining. "
        f"Estimated time for remaining items: {estimated_time:.0f}s. "
        f"Run 'Process Queue' task to continue without timeout limits."
    )
```

### Anti-Patterns to Avoid

- **Ignoring existing SyncStats:** Don't create separate timing tracking when SyncStats already provides `avg_processing_time`
- **No cold start handling:** Assuming timing data always exists leads to divide-by-zero or bad estimates
- **Fixed time estimates:** The existing 2s/item is arbitrary; use measured data
- **No safety buffer:** Processing times vary; always add margin
- **Opaque timeout messages:** Users need to know what to do when timeout occurs

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tracking processing time | New timing module | SyncStats.total_processing_time/jobs_processed | Already implemented and persisted |
| Calculating average | Manual sum/count | SyncStats.avg_processing_time property | Already a computed property |
| Persisting stats | Custom JSON handling | SyncStats.save_to_file() / load_from_file() | Already handles file I/O with merge |
| Moving average | External library (pandas) | Simple weighted average in SyncStats | Avoid adding pandas dependency for one calculation |

**Key insight:** The `worker/stats.py` module already has 90% of what's needed. Phase 13 is primarily about *using* this existing data for timeout calculation, not building new tracking infrastructure.

## Common Pitfalls

### Pitfall 1: Divide-by-Zero on Cold Start
**What goes wrong:** `avg_processing_time` returns 0.0 when no jobs processed, causing bad timeout calculation
**Why it happens:** New installation or cleared stats file
**How to avoid:** Always check `jobs_processed > 0` before using average; provide DEFAULT_TIME_PER_ITEM fallback
**Warning signs:** Timeout of 0 or very small values; immediate timeout on first run

### Pitfall 2: Stale Historical Data Skewing Estimates
**What goes wrong:** Old timing data from different conditions (different server, different network) causes poor estimates
**Why it happens:** SyncStats persists indefinitely across sessions
**How to avoid:** Consider using recent data only (weighted average), or reset stats when conditions change significantly
**Warning signs:** Consistent over/under-estimation; timeouts on small queues

### Pitfall 3: Buffer Too Small Under Variable Conditions
**What goes wrong:** 10% buffer insufficient when Plex is under load or network is slow
**Why it happens:** Processing times have high variance
**How to avoid:** Use 50% buffer (1.5x multiplier) as default; consider variance in calculation
**Warning signs:** Frequent timeouts just before completion; last few items take longer

### Pitfall 4: Max Timeout Too Restrictive
**What goes wrong:** 600s cap causes timeout for legitimate large queues (300+ items at 2s each)
**Why it happens:** Fixed cap doesn't account for actual workload
**How to avoid:** Cap is necessary for UX (can't wait forever), but improve timeout message to guide to Process Queue
**Warning signs:** Users repeatedly hitting timeout on bulk syncs; complaints about incomplete syncs

### Pitfall 5: Not Updating Stats During Processing
**What goes wrong:** Stats only saved at end; crash loses all timing data
**Why it happens:** save_to_file() called infrequently
**How to avoid:** Periodic saves (already implemented every 10 jobs in worker); ensure handle_process_queue also saves
**Warning signs:** Stats reset to 0 after crashes; inconsistent timing estimates

## Code Examples

Verified patterns from existing codebase:

### Current Timeout Logic (to be replaced)
```python
# Source: Stash2Plex.py lines 850-856
# Dynamic timeout: ~2 seconds per item, min 30s, max 600s (10 min)
initial_size = queue.size
max_wait = max(30, min(initial_size * 2, 600))  # <-- REPLACE THIS
wait_interval = 0.5
waited = 0
last_size = initial_size
```

### Existing SyncStats Average Calculation
```python
# Source: worker/stats.py lines 106-116
@property
def avg_processing_time(self) -> float:
    """
    Calculate average processing time per job.

    Returns:
        Average time in seconds, or 0.0 if no jobs processed
    """
    if self.jobs_processed == 0:
        return 0.0
    return self.total_processing_time / self.jobs_processed
```

### Existing Stats Persistence
```python
# Source: worker/stats.py - already saves/loads from disk
# Stats are automatically saved to data_dir/stats.json
if self.data_dir is not None:
    stats_path = os.path.join(self.data_dir, 'stats.json')
    self._stats = SyncStats.load_from_file(stats_path)
```

### Process Queue Already Uses Worker Stats
```python
# Source: Stash2Plex.py handle_process_queue() - uses SyncWorker
# which has access to stats via self._stats
worker_local = SyncWorker(queue, dlq_local, config, data_dir=data_dir)
```

## Stash Timeout Limits Investigation

**User Decision:** Research whether Stash exposes actual timeout limit info.

### Findings (MEDIUM confidence)

| Aspect | Finding | Source | Confidence |
|--------|---------|--------|------------|
| Plugin task timeout API | **Does NOT exist** - Stash provides no API for plugins to query/set timeout | [Go plugin pkg](https://pkg.go.dev/github.com/stashapp/stash/pkg/plugin) | MEDIUM |
| Scheduled task timeout | Can configure `timeout: N` in YAML for cron-scheduled scripts only | [Stash Wiki](https://stash.wiki/en/script/scheduled-tasks) | HIGH |
| Hook/task timeout | Uses Go context.Context internally; plugins cannot access | Plugin package docs | MEDIUM |
| Default timeout value | **Not documented** - appears to be effectively unlimited (until user cancels or Stash kills process) | No official documentation found | LOW |
| Max timeout value | **Not documented** - no hard limit found in documentation | WebSearch + official docs | LOW |

### Implications for Implementation

Since Stash does NOT expose timeout information:

1. **Cannot query actual limit** - Must use conservative estimates
2. **Cannot request extended timeout** - Plugin has no API for this
3. **Graceful degradation** - When calculated timeout exceeds cap (600s), guide users to Process Queue
4. **Process Queue is the solution** - Phase 12's Process Queue task has no timeout; dynamic timeout is for normal operation

### Recommendation

Keep the 600-second max timeout cap. This is a reasonable UX limit - users shouldn't wait longer than 10 minutes for a hook/task without feedback. For larger workloads, guide users to the Process Queue task which processes until completion.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed 30s timeout | Dynamic `items * 2, max 600s` | v1.1.4 | Better for variable queue sizes |
| No timing data | SyncStats tracks processing times | Phase 7 | Foundation for dynamic timeout |
| Arbitrary estimate | Measured average | Phase 13 | More accurate timeout calculation |
| Opaque timeout message | Process Queue guidance | Phase 13 | Actionable user experience |

**Deprecated/outdated:**
- Fixed `initial_size * 2` formula: Replace with actual measured `avg_processing_time`
- Static timeout messages: Replace with guidance including estimated time and Process Queue reference

## Open Questions

Things that couldn't be fully resolved:

1. **Stash's actual internal timeout (if any)**
   - What we know: No documented limit; plugins can run until cancelled
   - What's unclear: Whether Stash has any ultimate watchdog timeout
   - Recommendation: Assume no hard limit; use 600s cap for UX reasons

2. **Optimal buffer factor**
   - What we know: Processing times vary based on Plex load, network, item complexity
   - What's unclear: What percentile of variance to accommodate
   - Recommendation: Start with 1.5x (50% buffer); could make configurable later

3. **Stats persistence across sessions**
   - What we know: SyncStats saves to disk and merges cumulatively
   - What's unclear: Whether very old data should be weighted less
   - Recommendation: Current approach is fine; consider EMA if users report issues

4. **Minimum sample size for reliable average**
   - What we know: Need some jobs to calculate average
   - What's unclear: How many jobs before average is reliable
   - Recommendation: Use default for < 5 jobs; blend for 5-10; full average for 10+

## Sources

### Primary (HIGH confidence)
- [PlexSync codebase] - worker/stats.py (existing SyncStats implementation)
- [PlexSync codebase] - Stash2Plex.py lines 850-876 (current timeout logic)
- [PlexSync codebase] - worker/processor.py (timing measurement with time.perf_counter)

### Secondary (MEDIUM confidence)
- [Stash Go plugin package](https://pkg.go.dev/github.com/stashapp/stash/pkg/plugin) - Plugin API structure
- [Stash Wiki Scheduled Tasks](https://stash.wiki/en/script/scheduled-tasks) - Timeout configuration for cron scripts
- [Stash-Docs Plugins](https://dogmadragon.github.io/Stash-Docs/docs/In-app-Manual/Plugins/) - Plugin execution overview

### Tertiary (LOW confidence)
- WebSearch results on Stash plugin timeout - No definitive documentation found
- [GitHub Issue #4207](https://github.com/stashapp/stash/issues/4207) - Task queue feature request (no timeout specifics)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Using existing SyncStats, no new dependencies
- Architecture: HIGH - Extending existing patterns, minimal changes needed
- Stash timeout limits: LOW - No official documentation found; based on code analysis
- Pitfalls: MEDIUM - Based on general timing/estimation knowledge + codebase analysis

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (30 days) - Core patterns stable; Stash plugin system may evolve
