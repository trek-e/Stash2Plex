# Phase 11: Queue Management UI - Research

**Researched:** 2026-02-03
**Domain:** Stash plugin UI/task development with SQLite queue operations
**Confidence:** MEDIUM

## Summary

Queue Management UI for Stash plugins is implemented through additional task definitions in the plugin's YAML configuration file. Tasks are triggered from the Stash UI (Settings > Plugins or Tasks page) and receive arguments via JSON input. The plugin responds with JSON output containing status messages that Stash logs at appropriate levels.

For PlexSync, this means adding new tasks to `Stash2Plex.yml` that perform destructive queue operations (clear queue, purge DLQ) on the existing SQLiteAckQueue and DeadLetterQueue implementations. Since Stash plugins run non-interactively (no TTY), user confirmation must be built into the task design itself - either through separate "View Status" and "Clear Queue" tasks, or by using descriptive task names that make the destructive nature explicit.

The standard pattern is: (1) User selects task from Stash UI, (2) Plugin executes and logs progress to stderr, (3) Plugin returns JSON with success/error message, (4) Stash displays result in logs and task queue.

**Primary recommendation:** Add 2-4 new tasks to Stash2Plex.yml for queue management (view status, clear queue, clear DLQ, purge old DLQ entries), implement handlers in main plugin file that call queue operations, and provide detailed logging for user feedback.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| persist-queue | >=1.1.0 | SQLite-backed queue with ack/nack support | Already in use, provides direct SQL access via sqlite3 for advanced operations |
| stashapi | Latest | Stash GraphQL API wrapper | Already in use, provides StashInterface for Stash communication |
| sqlite3 | stdlib | Direct SQLite database access | Python standard library, needed for operations not exposed by persist-queue API |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json | stdlib | Plugin input/output protocol | Required - Stash communicates via JSON |
| sys.stderr | stdlib | Stash plugin logging | Required - Stash reads logs from stderr with special prefix format |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct SQL manipulation | persist-queue API only | API doesn't expose clear/purge for all statuses; direct SQL needed for comprehensive management |
| Interactive CLI prompts | Task naming + separate confirm tasks | Stash plugins run non-interactively; can't use input() or TTY detection |
| Rich/questionary prompts | JSON status messages in stderr logs | No TTY available; must use Stash's log viewer as UI feedback mechanism |

**Installation:**
```bash
# Already installed - no new dependencies needed
pip install persist-queue>=1.1.0
pip install stashapi
```

## Architecture Patterns

### Recommended Task Structure in Stash2Plex.yml
```yaml
tasks:
  # Existing tasks
  - name: Sync All Scenes to Plex
    description: Force sync all scenes to Plex
    defaultArgs:
      mode: all
  - name: Sync Recent Scenes to Plex
    description: Sync scenes updated in the last 24 hours
    defaultArgs:
      mode: recent

  # NEW: Queue management tasks
  - name: View Queue Status
    description: Show current queue statistics and DLQ counts
    defaultArgs:
      mode: queue_status
  - name: Clear Queue
    description: "DESTRUCTIVE: Remove all pending queue items (does not affect completed or failed)"
    defaultArgs:
      mode: clear_queue
  - name: Clear Dead Letter Queue
    description: "DESTRUCTIVE: Remove all failed items from DLQ"
    defaultArgs:
      mode: clear_dlq
  - name: Purge Old DLQ Entries
    description: Remove DLQ entries older than 30 days
    defaultArgs:
      mode: purge_dlq
      days: 30
```

### Pattern 1: Task Handler Dispatch
**What:** Route task requests based on `mode` argument to appropriate queue operation handlers
**When to use:** Plugin supports multiple task types distinguished by arguments
**Example:**
```python
# Source: Current PlexSync implementation in Stash2Plex.py
def handle_task(task_args: dict, stash=None):
    """Handle manual task trigger from Stash UI."""
    mode = task_args.get('mode', 'recent')
    log_info(f"Task starting with mode: {mode}")

    if mode in ('all', 'recent'):
        # Existing sync logic
        handle_sync_task(mode, stash)
    elif mode == 'queue_status':
        handle_queue_status()
    elif mode == 'clear_queue':
        handle_clear_queue()
    elif mode == 'clear_dlq':
        handle_clear_dlq()
    elif mode == 'purge_dlq':
        days = task_args.get('days', 30)
        handle_purge_dlq(days)
```

### Pattern 2: Stash Plugin Logging Format
**What:** Use special character sequences to prefix log messages for Stash's log level handling
**When to use:** All plugin output that should appear in Stash logs
**Example:**
```python
# Source: PlexSync logging implementation
def log_trace(msg): print(f"\x01t\x02[Stash2Plex] {msg}", file=sys.stderr)
def log_debug(msg): print(f"\x01d\x02[Stash2Plex] {msg}", file=sys.stderr)
def log_info(msg): print(f"\x01i\x02[Stash2Plex] {msg}", file=sys.stderr)
def log_warn(msg): print(f"\x01w\x02[Stash2Plex] {msg}", file=sys.stderr)
def log_error(msg): print(f"\x01e\x02[Stash2Plex] {msg}", file=sys.stderr)
def log_progress(p): print(f"\x01p\x02{p}")

# Usage
log_info("Queue contains 5 pending items")
log_warn("This operation will delete all pending queue items")
log_error("Failed to clear queue: database locked")
```

### Pattern 3: Queue Statistics Query
**What:** Read SQLite database directly to get status breakdown by AckStatus enum
**When to use:** Displaying queue status to user
**Example:**
```python
# Source: PlexSync sync_queue/operations.py get_stats()
def get_stats(queue_path: str) -> dict:
    """Get queue statistics by status."""
    db_path = os.path.join(queue_path, 'data.db')
    conn = sqlite3.connect(db_path)

    # Find ack_queue table (persist-queue uses ack_queue_default)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ack_queue%'"
    )
    table = cursor.fetchone()
    table_name = table[0]

    cursor = conn.execute(f'''
        SELECT status, COUNT(*) as count
        FROM {table_name}
        GROUP BY status
    ''')

    stats = {'pending': 0, 'in_progress': 0, 'completed': 0, 'failed': 0}
    for row in cursor:
        status_code = row[0]
        count = row[1]
        # Map status codes: 0/1=pending, 2=in_progress, 5=completed, 9=failed
        if status_code in (0, 1):
            stats['pending'] += count
        elif status_code == 2:
            stats['in_progress'] += count
        elif status_code == 5:
            stats['completed'] += count
        elif status_code == 9:
            stats['failed'] += count

    conn.close()
    return stats
```

### Pattern 4: Direct SQL Queue Deletion
**What:** Execute DELETE statements directly on SQLite database for comprehensive clearing
**When to use:** Need to clear statuses not exposed by persist-queue API
**Example:**
```python
# Source: Research findings on SQLite DELETE operations
def clear_all_pending_items(queue_path: str) -> int:
    """Clear all pending items from queue (status 0 and 1)."""
    db_path = os.path.join(queue_path, 'data.db')
    conn = sqlite3.connect(db_path)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ack_queue%'"
    )
    table = cursor.fetchone()
    if not table:
        return 0

    table_name = table[0]

    # Delete items with status 0 (inited) or 1 (ready)
    cursor = conn.execute(
        f"DELETE FROM {table_name} WHERE status IN (0, 1)"
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted
```

### Pattern 5: Confirmation Through Task Design
**What:** Make destructive operations explicit through task naming and description, avoiding need for interactive confirmation
**When to use:** Stash plugins (no TTY available for user prompts)
**Example:**
```yaml
# BAD: Requires runtime confirmation (not possible in Stash)
- name: Clear Queue
  description: Clear all queue items

# GOOD: Warning in description, explicit naming
- name: Clear Queue
  description: "DESTRUCTIVE: Remove all pending queue items (does not affect completed or failed)"

# BETTER: Separate view and action tasks
- name: View Queue Status
  description: Show current queue statistics (safe, read-only)
- name: Clear Queue - CONFIRM
  description: "WARNING: This will permanently delete all pending items"
```

### Anti-Patterns to Avoid
- **Using input() prompts:** Stash plugins run non-interactively; no stdin available for user input
- **Relying on TTY detection:** sys.stdin.isatty() always False in Stash plugin context
- **Silent destructive operations:** Always log counts and status messages for user visibility
- **Assuming queue.clear() exists:** persist-queue SQLiteAckQueue doesn't expose a clear() method; must use direct SQL or clear_acked_data()

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Queue status display | Custom status tracking | `sync_queue.operations.get_stats()` | Already implemented, queries SQLite directly with proper status mapping |
| DLQ operations | Custom failed job tracking | `sync_queue.dlq.DeadLetterQueue` class | Already has get_count(), get_recent(), delete_older_than() methods |
| Stash logging | print() statements | Existing log_info/warn/error functions | Proper \x01level\x02 prefix format required for Stash to parse log levels |
| JSON responses | String concatenation | json.dumps() with dict | Stash expects {"error": "...", "output": "..."} structure |
| Queue clearing | Loop through get()/ack() | Direct SQL DELETE | Much faster, atomic operation, handles status filtering |

**Key insight:** The infrastructure for queue management already exists in sync_queue module. This phase is primarily about exposing existing operations through Stash UI tasks, not building new queue primitives.

## Common Pitfalls

### Pitfall 1: Attempting Interactive Confirmation
**What goes wrong:** Plugin tries to use input(), sys.stdin.isatty(), or interactive prompt libraries (Rich, questionary)
**Why it happens:** Developer applies CLI best practices without understanding Stash's non-interactive execution model
**How to avoid:** Design tasks to be self-contained; use explicit task names and descriptions as "confirmation"; consider separate "View" and "Clear" tasks
**Warning signs:** Plugin hangs or times out; no user input received; sys.stdin reads return empty

### Pitfall 2: Ignoring AckStatus Enum Values
**What goes wrong:** SQL queries delete wrong items because status codes are misunderstood
**Why it happens:** persist-queue documentation doesn't clearly document status integer values
**How to avoid:** Use constants: 0/1=pending, 2=in_progress, 5=acked, 9=ack_failed; always test queries against known queue states
**Warning signs:** clear_queue deletes completed items; purge removes active jobs; counts don't match expectations

### Pitfall 3: Race Conditions with Worker Thread
**What goes wrong:** Worker thread is processing items while clear operation executes, leading to inconsistent state
**Why it happens:** Worker runs in daemon thread that polls continuously; no built-in pause mechanism
**How to avoid:** Accept that race conditions can occur; log counts before/after; document that worker may re-enqueue failed items; consider stopping worker for truly atomic clears (complex)
**Warning signs:** Clear reports N items deleted but queue size doesn't match; items reappear after clear; logs show worker errors during clear

### Pitfall 4: Not Using Transactions for Multi-Step Operations
**What goes wrong:** Partial deletes occur if operation fails mid-execution, leaving queue in inconsistent state
**Why it happens:** Direct SQL without explicit transaction management uses autocommit
**How to avoid:** Wrap DELETE operations in conn.execute() with explicit conn.commit(); use try/except to conn.rollback() on error
**Warning signs:** Some items deleted but not all; error mid-operation leaves queue partially cleared; counts don't add up

### Pitfall 5: Assuming persist-queue API Covers All Operations
**What goes wrong:** Developer tries to find clear() or purge() methods in persist-queue API, gives up when not found
**Why it happens:** persist-queue focuses on producer-consumer operations (put/get/ack/nack), not administrative tasks
**How to avoid:** Recognize that direct SQLite access is intended and necessary for admin operations; use get_stats() as example of direct SQL pattern
**Warning signs:** Workarounds like repeatedly calling get()/ack() to "clear"; performance issues; complex logic for simple operations

### Pitfall 6: Forgetting to Close SQLite Connections
**What goes wrong:** Database locked errors on subsequent operations; file handle leaks
**Why it happens:** Direct sqlite3.connect() calls without proper cleanup
**How to avoid:** Always use try/finally or context manager (with conn:) pattern; close connections explicitly
**Warning signs:** "database is locked" errors; operations work once then fail; need to restart plugin to recover

## Code Examples

Verified patterns from official sources:

### Queue Status Display Handler
```python
# Source: Based on PlexSync sync_queue/operations.py and dlq.py
def handle_queue_status():
    """Display current queue and DLQ statistics."""
    try:
        data_dir = get_plugin_data_dir()
        queue_path = os.path.join(data_dir, 'queue')

        # Get queue stats
        from sync_queue.operations import get_stats
        queue_stats = get_stats(queue_path)

        # Get DLQ stats
        from sync_queue.dlq import DeadLetterQueue
        dlq = DeadLetterQueue(data_dir)
        dlq_count = dlq.get_count()
        dlq_summary = dlq.get_error_summary()

        # Log results
        log_info("=== Queue Status ===")
        log_info(f"Pending: {queue_stats['pending']}")
        log_info(f"In Progress: {queue_stats['in_progress']}")
        log_info(f"Completed: {queue_stats['completed']}")
        log_info(f"Failed: {queue_stats['failed']}")
        log_info(f"Dead Letter Queue: {dlq_count} items")

        if dlq_summary:
            log_info("DLQ Error Breakdown:")
            for error_type, count in dlq_summary.items():
                log_info(f"  {error_type}: {count}")

    except Exception as e:
        log_error(f"Failed to get queue status: {e}")
        import traceback
        traceback.print_exc()
```

### Clear Pending Queue Items
```python
# Source: Research on SQLite DELETE + persist-queue status codes
def handle_clear_queue():
    """Clear all pending queue items (status 0 and 1)."""
    try:
        data_dir = get_plugin_data_dir()
        queue_path = os.path.join(data_dir, 'queue')
        db_path = os.path.join(queue_path, 'data.db')

        # Get count before deletion
        from sync_queue.operations import get_stats
        before_stats = get_stats(queue_path)
        pending_count = before_stats['pending']

        if pending_count == 0:
            log_info("Queue is empty - nothing to clear")
            return

        log_warn(f"Clearing {pending_count} pending queue items...")

        # Direct SQL deletion
        conn = sqlite3.connect(db_path)
        try:
            # Find table name
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ack_queue%'"
            )
            table = cursor.fetchone()
            if not table:
                log_warn("Queue table not found - queue may not be initialized")
                return

            table_name = table[0]

            # Delete pending items (status 0=inited, 1=ready)
            cursor = conn.execute(
                f"DELETE FROM {table_name} WHERE status IN (0, 1)"
            )
            deleted = cursor.rowcount
            conn.commit()

            log_info(f"Successfully cleared {deleted} pending items from queue")

            # Show updated stats
            after_stats = get_stats(queue_path)
            log_info(f"Remaining - Pending: {after_stats['pending']}, In Progress: {after_stats['in_progress']}")

        finally:
            conn.close()

    except Exception as e:
        log_error(f"Failed to clear queue: {e}")
        import traceback
        traceback.print_exc()
```

### Clear Dead Letter Queue
```python
# Source: PlexSync sync_queue/dlq.py
def handle_clear_dlq():
    """Clear all items from dead letter queue."""
    try:
        data_dir = get_plugin_data_dir()

        from sync_queue.dlq import DeadLetterQueue
        dlq = DeadLetterQueue(data_dir)

        # Get count before deletion
        count_before = dlq.get_count()

        if count_before == 0:
            log_info("Dead letter queue is empty - nothing to clear")
            return

        log_warn(f"Clearing {count_before} items from dead letter queue...")

        # Delete all DLQ entries via direct SQL
        with dlq._get_connection() as conn:
            cursor = conn.execute("DELETE FROM dead_letters")
            deleted = cursor.rowcount
            conn.commit()

        log_info(f"Successfully cleared {deleted} items from DLQ")

    except Exception as e:
        log_error(f"Failed to clear DLQ: {e}")
        import traceback
        traceback.print_exc()
```

### Purge Old DLQ Entries
```python
# Source: PlexSync sync_queue/dlq.py delete_older_than() method
def handle_purge_dlq(days: int = 30):
    """Remove DLQ entries older than specified days."""
    try:
        data_dir = get_plugin_data_dir()

        from sync_queue.dlq import DeadLetterQueue
        dlq = DeadLetterQueue(data_dir)

        count_before = dlq.get_count()
        log_info(f"Purging DLQ entries older than {days} days...")

        # Use existing delete_older_than method
        dlq.delete_older_than(days)

        count_after = dlq.get_count()
        removed = count_before - count_after

        log_info(f"Removed {removed} old DLQ entries ({count_after} remain)")

    except Exception as e:
        log_error(f"Failed to purge old DLQ entries: {e}")
        import traceback
        traceback.print_exc()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual SQLite inspection | In-plugin queue status tasks | This phase (11) | Users can view queue state from Stash UI without database tools |
| Delete queue database files | Selective queue clearing via tasks | This phase (11) | Users can clear stuck items without losing completed job records |
| No DLQ visibility | DLQ status and purge tasks | This phase (11) | Users can identify and clear permanently failed jobs from UI |
| stashapi.log module | Custom log_* functions with \x01\x02 prefix | Phase 8 (already implemented) | Proper log level routing in Stash logs |

**Deprecated/outdated:**
- Manual file deletion: Deleting `queue/data.db` or `dlq.db` files directly (destructive, loses all history)
- Using persist-queue's clear_acked_data(): Only clears completed items, not pending/failed; doesn't match user intent for "clear queue"

## Open Questions

Things that couldn't be fully resolved:

1. **Worker Thread Safety During Clear Operations**
   - What we know: Worker runs in daemon thread, polls continuously, may process items during clear
   - What's unclear: Whether stopping worker is worth the complexity; how to communicate pause state
   - Recommendation: Accept potential race conditions; log before/after counts; document behavior in task descriptions

2. **Confirmation Pattern for Destructive Operations**
   - What we know: No interactive prompts available; task names/descriptions serve as "confirmation"
   - What's unclear: Whether users will accidentally trigger destructive tasks; if two-step pattern (view + clear) is better than single clear task
   - Recommendation: Start with explicit task names containing "DESTRUCTIVE" warning; monitor user feedback; consider two-step pattern in future if needed

3. **Should Clear Remove In-Progress Items?**
   - What we know: Status 2 (in_progress/unack) means worker has the item but hasn't completed it
   - What's unclear: If user expects "clear queue" to remove in-progress items, or only pending
   - Recommendation: Only clear pending (status 0/1) initially; document that in-progress items will complete; add separate "Clear All" task if needed

4. **Queue Statistics Refresh Rate**
   - What we know: Stats are read from SQLite on-demand; no caching
   - What's unclear: If stats should show historical trends or just current snapshot
   - Recommendation: Current snapshot only for initial implementation; consider adding trend tracking in future phase if users request it

## Sources

### Primary (HIGH confidence)
- [PlexSync codebase] - sync_queue/operations.py, dlq.py, manager.py (existing queue infrastructure)
- [Stash Plugin Docs](https://dogmadragon.github.io/Stash-Docs/docs/In-app-Manual/Plugins/) - Task configuration and JSON output format
- [persist-queue GitHub](https://github.com/peter-wangxu/persist-queue) - SQLiteAckQueue implementation and status codes

### Secondary (MEDIUM confidence)
- [Command Line Interface Guidelines](https://clig.dev/) - Destructive operation confirmation best practices
- [SQLite DELETE Tutorial](https://www.sqlitetutorial.net/sqlite-delete/) - Direct SQL deletion patterns
- [Dead Letter Queue Best Practices](https://avadasoftware.com/dead-letter-queue-guide/) - DLQ management patterns
- [Azure Service Bus DLQ Docs](https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-dead-letter-queues) - Industry patterns for DLQ clearing/purging

### Tertiary (LOW confidence)
- [Stash CommunityScripts](https://github.com/stashapp/CommunityScripts) - Plugin examples (varied quality, not all Python)
- WebSearch results on Stash plugin development (2026) - Limited official documentation available

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in use, no new dependencies
- Architecture: MEDIUM - Task patterns verified from docs, but direct SQL approach based on codebase inspection + research (not officially documented)
- Pitfalls: MEDIUM - Based on SQLite/Python best practices + specific persist-queue behaviors observed in codebase

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (30 days) - Stash plugin system is stable; persist-queue unlikely to have breaking changes
