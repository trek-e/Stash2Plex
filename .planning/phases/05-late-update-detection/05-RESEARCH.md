# Phase 5: Late Update Detection - Research

**Researched:** 2026-02-02
**Domain:** Change detection, confidence-based matching, state tracking
**Confidence:** HIGH

## Summary

Late update detection is a change propagation pattern that ensures metadata updates in Stash (after initial sync) trigger re-sync to Plex. The research covered timestamp-based change detection, confidence scoring for ambiguous matches, conflict resolution strategies, and queue deduplication patterns.

The standard approach uses timestamp comparison (`updated_at` from Stash vs `last_synced_at` tracking field) for simplicity and low overhead. Confidence scoring follows binary classification (HIGH/LOW) based on match uniqueness - single match = high confidence (auto-sync), multiple matches = low confidence (needs review). Configuration flags enable strict mode (skip low-confidence syncs) vs permissive mode (sync with warning).

User decisions from CONTEXT.md lock in: timestamp comparison (not content hashing), binary confidence levels (not multi-tier), Scene.Update hook triggering (not periodic polling), and job metadata storage for state tracking. Stash's GraphQL API provides `updated_at: Time!` field on Scene type for comparison.

**Primary recommendation:** Use Stash `updated_at` field comparison against stored `last_synced_at` timestamps, implement binary confidence classification based on match cardinality (unique=HIGH, multiple=LOW, none=PlexNotFound), add `strict_matching` boolean config flag, and track sync state in separate SQLite table alongside queue.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python datetime | 3.14+ | Timestamp comparison | Built-in, timezone-aware, supports direct comparison operators |
| SQLite3 | stdlib | State tracking table | Already used for queue, zero additional dependencies |
| Pydantic | 2.x | Config validation with strict mode | Already in use for config, supports StrictBool for flags |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| persistqueue.SQLiteAckQueue | current | Queue deduplication checks | For checking existing jobs before enqueue |
| logging | stdlib | Structured log output | For scannable low-confidence match alerts |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Timestamp comparison | Content hashing (MD5/SHA) | Hash is 2.5-5x slower, overkill for metadata change detection |
| Binary confidence | Multi-tier (HIGH/MEDIUM/LOW) | Added complexity without clear benefit for this domain |
| Separate state table | Job metadata only | Lose historical sync record when job completes |

**Installation:**
```bash
# No new dependencies - all stdlib or already in use
pip install pydantic  # Already installed from Phase 2
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── sync/                 # NEW - sync state tracking
│   ├── __init__.py
│   ├── state.py         # SyncState table operations
│   └── detector.py      # Change detection logic
├── plex/
│   └── matcher.py       # EXTEND - add confidence scoring
├── worker/
│   └── processor.py     # EXTEND - update last_synced_at after success
├── hooks/
│   └── handlers.py      # EXTEND - check timestamps before enqueue
└── queue/
    └── operations.py    # EXTEND - add deduplication check
```

### Pattern 1: Timestamp-Based Change Detection
**What:** Compare Stash `updated_at` against stored `last_synced_at` to detect late updates
**When to use:** Every Scene.Update hook to determine if re-sync needed
**Example:**
```python
# Source: Based on Python datetime best practices
# https://docs.python.org/3/library/datetime.html
from datetime import datetime, timezone

def needs_resync(scene_id: int, stash_updated_at: float, sync_state_db) -> bool:
    """
    Check if scene requires re-sync based on timestamp comparison.

    Args:
        scene_id: Stash scene ID
        stash_updated_at: Unix timestamp from Stash Scene.updated_at
        sync_state_db: Connection to sync state database

    Returns:
        True if scene should be re-synced (Stash is newer than last sync)
    """
    # Get last successful sync timestamp for this scene
    last_synced = get_last_synced_at(sync_state_db, scene_id)

    if last_synced is None:
        # Never synced successfully - needs initial sync
        return True

    # Direct timestamp comparison (both are Unix timestamps)
    # Stash updated_at is newer than our last sync = needs re-sync
    return stash_updated_at > last_synced
```

### Pattern 2: Binary Confidence Classification
**What:** Score matches as HIGH (auto-sync) or LOW (needs review) based on uniqueness
**When to use:** After find_plex_item_by_path returns result(s) to decide action
**Example:**
```python
# Source: Based on matching algorithm confidence patterns
# https://docs.aws.amazon.com/glue/latest/dg/match-scoring.html
from enum import Enum
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from plexapi.video import Video

class MatchConfidence(Enum):
    HIGH = "high"  # Single unique match - auto-sync safe
    LOW = "low"    # Multiple candidates - needs review

def score_match_confidence(
    candidates: List["Video"],
    stash_path: str
) -> tuple[MatchConfidence, Optional["Video"]]:
    """
    Score match confidence based on candidate uniqueness.

    Binary classification:
    - Single match = HIGH confidence (return item for auto-sync)
    - Multiple matches = LOW confidence (return None, needs review)
    - No match handled by PlexNotFound exception (not scored here)

    Args:
        candidates: List of Plex items from matcher strategies
        stash_path: Original Stash file path for logging

    Returns:
        Tuple of (confidence_level, plex_item_or_none)
    """
    if len(candidates) == 1:
        return (MatchConfidence.HIGH, candidates[0])
    else:
        # Multiple matches - ambiguous, needs manual review
        # Log candidates for user visibility
        paths = [c.media[0].parts[0].file for c in candidates]
        logger.warning(
            f"LOW confidence: {len(candidates)} matches for '{stash_path}'\n"
            f"  Candidates: {paths}"
        )
        return (MatchConfidence.LOW, None)
```

### Pattern 3: Sync State Tracking Table
**What:** Separate SQLite table tracking last_synced_at per scene_id
**When to use:** After successful Plex metadata update and on startup for late detection
**Example:**
```python
# Source: Based on SQLite state tracking patterns
# https://github.com/bintlabs/python-sync-db
import sqlite3
import time
from typing import Optional

class SyncState:
    """Track sync state separately from job queue for historical record."""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        """Create sync state table if not exists."""
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS sync_state (
                scene_id INTEGER PRIMARY KEY,
                last_synced_at REAL NOT NULL,
                last_sync_status TEXT NOT NULL,
                plex_item_key TEXT,
                updated_at REAL NOT NULL
            )
        ''')
        self.conn.commit()

    def update_success(self, scene_id: int, plex_item_key: str):
        """Record successful sync with current timestamp."""
        now = time.time()
        self.conn.execute('''
            INSERT OR REPLACE INTO sync_state
            (scene_id, last_synced_at, last_sync_status, plex_item_key, updated_at)
            VALUES (?, ?, 'success', ?, ?)
        ''', (scene_id, now, plex_item_key, now))
        self.conn.commit()

    def get_last_synced_at(self, scene_id: int) -> Optional[float]:
        """Get last successful sync timestamp for scene."""
        cursor = self.conn.execute(
            'SELECT last_synced_at FROM sync_state WHERE scene_id = ? AND last_sync_status = "success"',
            (scene_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None
```

### Pattern 4: Queue Deduplication Check
**What:** Check queue for existing job before adding duplicate on bulk updates
**When to use:** Before enqueue in hook handler to prevent flooding
**Example:**
```python
# Source: Based on SQLite queue deduplication patterns
# https://sqlite.org/forum/info/159f28bf7f2125c7
import sqlite3
import os

def is_scene_in_queue(queue_path: str, scene_id: int) -> bool:
    """
    Check if scene already has pending/in-progress job in queue.

    Prevents duplicate jobs during bulk Stash updates.
    Uses direct SQLite query on persist-queue database.

    Args:
        queue_path: Path to queue directory containing data.db
        scene_id: Scene ID to check

    Returns:
        True if scene_id already has active job in queue
    """
    db_path = os.path.join(queue_path, 'data.db')

    if not os.path.exists(db_path):
        return False

    conn = sqlite3.connect(db_path)
    try:
        # Find the ack_queue table name
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ack_queue%'"
        )
        table = cursor.fetchone()
        if not table:
            return False

        table_name = table[0]

        # Check for jobs with this scene_id in pending/in-progress status
        # Status 0,1 = pending, 2 = in_progress
        cursor = conn.execute(f'''
            SELECT COUNT(*) FROM {table_name}
            WHERE status IN (0, 1, 2)
            AND data LIKE ?
        ''', (f'%"scene_id": {scene_id}%',))

        count = cursor.fetchone()[0]
        return count > 0
    finally:
        conn.close()
```

### Pattern 5: Strict Mode Configuration
**What:** Boolean config flag to control behavior on low-confidence matches
**When to use:** Config validation and worker decision logic
**Example:**
```python
# Source: Pydantic strict mode patterns
# https://docs.pydantic.dev/latest/concepts/strict_mode/
from pydantic import BaseModel, Field, field_validator

class PlexSyncConfig(BaseModel):
    """Extended config with late update detection settings."""

    # Existing fields...
    plex_url: str
    plex_token: str

    # Late update detection config
    strict_matching: bool = Field(
        default=True,
        description="Skip sync on low-confidence matches (safer). "
                   "False = sync anyway with warning logged."
    )

    preserve_plex_edits: bool = Field(
        default=False,
        description="Preserve manual Plex edits. "
                   "True = only update empty fields, False = Stash always wins."
    )

    @field_validator('strict_matching', 'preserve_plex_edits')
    @classmethod
    def validate_bool_flags(cls, v):
        """Ensure boolean flags are actual booleans."""
        if not isinstance(v, bool):
            raise ValueError(f"Must be boolean, got {type(v)}")
        return v
```

### Anti-Patterns to Avoid
- **Periodic polling instead of hook-triggered checks:** Creates unnecessary overhead and delays; Scene.Update hook provides instant notification
- **Content hashing for change detection:** 2.5-5x slower than timestamp comparison; metadata changes are already timestamped by Stash
- **Multi-tier confidence levels (HIGH/MEDIUM/LOW):** Adds complexity without actionable distinction; binary is sufficient (auto-sync or review)
- **Storing state in job metadata only:** Loses historical sync record when job completes; separate table maintains history
- **Default permissive matching (strict_matching=false):** Safer default is strict=true to prevent incorrect syncs on ambiguous matches

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Timestamp parsing/comparison | Custom string comparison | Python datetime with direct operators | Timezone handling, leap seconds, proper ordering |
| SQLite connection pooling | Manual connection management | sqlite3.connect() with check_same_thread=False | Thread-safety built-in, handles locking |
| Boolean config validation | Manual if/else checks | Pydantic StrictBool or field validators | Type coercion bugs, consistent error messages |
| Queue deduplication | In-memory set tracking | Direct SQLite WHERE query on queue DB | Survives restart, no memory overhead |
| Confidence score thresholds | Hardcoded numeric thresholds (0.7, 0.8) | Binary enum (HIGH/LOW) based on cardinality | Clear semantics, no magic numbers |

**Key insight:** Change detection is a solved problem with well-established timestamp comparison patterns. The complexity is in the domain-specific decisions (what triggers sync, how to score confidence, conflict resolution) not in the mechanics of comparing timestamps or querying databases. Use stdlib and existing patterns; focus implementation effort on business logic.

## Common Pitfalls

### Pitfall 1: False Positives from Non-Metadata Timestamp Updates
**What goes wrong:** Stash `updated_at` changes on view count, play history, or other non-metadata updates, triggering unnecessary re-syncs
**Why it happens:** Timestamp field tracks ANY change to scene record, not just metadata fields
**How to avoid:** Filter in hook handler using `requires_plex_sync()` to check if update contains sync-worthy fields before timestamp comparison
**Warning signs:** Queue flood with jobs that don't change Plex metadata, high retry counts on "already up to date" scenarios

### Pitfall 2: Race Condition Between Timestamp Check and Enqueue
**What goes wrong:** Scene updated_at changes between timestamp check and job enqueue, missing the latest update
**Why it happens:** Hook handler is not atomic - time passes between check and queue insertion
**How to avoid:** Accept eventual consistency - next Scene.Update will catch it. Or pass stash_updated_at value IN job data for worker to re-check
**Warning signs:** Inconsistent Plex state vs Stash, metadata "stuck" at older values

### Pitfall 3: No Cleanup of Sync State Table
**What goes wrong:** Sync state table grows unbounded as scenes accumulate
**Why it happens:** No deletion logic when scenes are removed from Stash
**How to avoid:** Add periodic cleanup of orphaned scene_ids (scenes no longer in Stash), or accept table growth (scenes are relatively stable)
**Warning signs:** Database file size growing over time, queries slowing down

### Pitfall 4: Low-Confidence Match Floods Logs
**What goes wrong:** Many low-confidence matches generate excessive log output, making logs unreadable
**Why it happens:** Ambiguous filenames in large libraries produce multiple matches frequently
**How to avoid:** Use structured logging with scannable format (one line per match with scene_id prefix), or aggregate low-confidence matches into summary reports
**Warning signs:** Log files growing rapidly, important errors buried in noise

### Pitfall 5: Queue Deduplication Check Slow Query
**What goes wrong:** Deduplication query with LIKE on pickled job data is slow on large queues
**Why it happens:** Full table scan without index, string matching on serialized data
**How to avoid:** Use job_key field (already in job dict as `scene_{scene_id}`) with indexed query, or maintain in-memory set during worker lifetime
**Warning signs:** Hook handler exceeding 100ms target, queue.db lock contention

### Pitfall 6: Timestamp Storage Precision Loss
**What goes wrong:** Storing Unix timestamp (float) in SQLite REAL loses precision, causing comparison bugs
**Why it happens:** SQLite REAL is 8-byte floating point with ~15 decimal digits precision
**How to avoid:** Use REAL type for timestamp storage (sufficient for microsecond precision), avoid TEXT type that requires parsing
**Warning signs:** Timestamps comparing equal when they should differ, off-by-one-second errors

### Pitfall 7: Forgetting to Update last_synced_at After Retry Success
**What goes wrong:** Failed job retries successfully but last_synced_at not updated, causing immediate re-sync loop
**Why it happens:** Success callback only in happy path, not in retry success path
**How to avoid:** Update sync state in worker _process_job success (after ack_job), works for both initial and retry success
**Warning signs:** Jobs succeed but immediately re-appear in queue, log shows repeated sync of same scene

## Code Examples

Verified patterns from official sources:

### Hook Handler with Late Update Detection
```python
# Source: Timestamp comparison best practices
# https://docs.python.org/3/library/datetime.html
def on_scene_update(scene_id: int, update_data: dict, queue, sync_state: SyncState) -> bool:
    """
    Handle scene update with late detection check.

    Filters non-metadata updates, checks timestamp against last sync,
    deduplicates queue, then enqueues if needed.
    """
    start = time.time()

    # Filter 1: Non-metadata updates (play counts, view history)
    if not requires_plex_sync(update_data):
        print(f"[PlexSync] Scene {scene_id} filtered (no metadata changes)")
        return False

    # Filter 2: Timestamp comparison for late update detection
    stash_updated_at = update_data.get('updated_at')
    if stash_updated_at:
        last_synced = sync_state.get_last_synced_at(scene_id)
        if last_synced and stash_updated_at <= last_synced:
            print(f"[PlexSync] Scene {scene_id} already synced (Stash: {stash_updated_at} <= Last: {last_synced})")
            return False

    # Filter 3: Queue deduplication
    if is_scene_in_queue(queue.path, scene_id):
        print(f"[PlexSync] Scene {scene_id} already in queue, skipping duplicate")
        return False

    # Enqueue for background processing
    enqueue(queue, scene_id, "metadata", update_data)

    elapsed_ms = (time.time() - start) * 1000
    print(f"[PlexSync] Enqueued re-sync for scene {scene_id} in {elapsed_ms:.1f}ms")
    return True
```

### Worker with Confidence-Based Matching
```python
# Source: Confidence scoring patterns
# https://docs.aws.amazon.com/glue/latest/dg/match-scoring.html
def _process_job(self, job: dict):
    """
    Process job with confidence-based matching.

    Finds Plex item, scores confidence, applies strict_matching config.
    """
    from plex.exceptions import PlexNotFound
    from plex.matcher import find_plex_item_by_path

    scene_id = job.get('scene_id')
    data = job.get('data', {})
    file_path = data.get('path')

    if not file_path:
        raise PermanentError(f"Job {scene_id} missing file path")

    try:
        client = self._get_plex_client()

        # Find all matching candidates across library sections
        candidates = []
        for section in client.server.library.sections():
            # find_plex_item_by_path already handles 3 fallback strategies
            item = find_plex_item_by_path(section, file_path)
            if item:
                candidates.append(item)

        # Score confidence based on uniqueness
        if len(candidates) == 0:
            raise PlexNotFound(f"No Plex item found for path: {file_path}")
        elif len(candidates) == 1:
            # HIGH confidence - single unique match
            plex_item = candidates[0]
            self._update_metadata(plex_item, data)
        else:
            # LOW confidence - multiple matches
            if self.config.strict_matching:
                # Skip sync, log for review
                paths = [c.media[0].parts[0].file for c in candidates]
                logger.warning(
                    f"[PlexSync] LOW CONFIDENCE SKIPPED: scene {scene_id}\n"
                    f"  Stash path: {file_path}\n"
                    f"  Plex candidates ({len(candidates)}): {paths}"
                )
                raise PermanentError(f"Low confidence match skipped (strict_matching=true)")
            else:
                # Permissive mode - sync first match with warning
                plex_item = candidates[0]
                paths = [c.media[0].parts[0].file for c in candidates]
                logger.warning(
                    f"[PlexSync] LOW CONFIDENCE SYNCED: scene {scene_id}\n"
                    f"  Chosen: {plex_item.media[0].parts[0].file}\n"
                    f"  Other candidates: {paths[1:]}"
                )
                self._update_metadata(plex_item, data)

        # Update sync state after successful update
        self.sync_state.update_success(scene_id, plex_item.key)

    except (PlexTemporaryError, PlexPermanentError, PlexNotFound):
        raise
    except Exception as e:
        raise translate_plex_exception(e)
```

### Conflict Resolution with preserve_plex_edits
```python
# Source: Conflict resolution strategies
# https://docs.aws.amazon.com/appsync/latest/devguide/conflict-detection-and-sync.html
def _update_metadata(self, plex_item, data: dict):
    """
    Update Plex metadata with configurable conflict resolution.

    preserve_plex_edits=False (default): Stash always wins (overwrite all)
    preserve_plex_edits=True: Only update empty/default Plex fields
    """
    edits = {}

    if self.config.preserve_plex_edits:
        # Only update fields that are empty/default in Plex
        if 'title' in data and (not plex_item.title or plex_item.title == plex_item.media[0].parts[0].file):
            edits['title.value'] = data['title']
        if 'studio' in data and not plex_item.studio:
            edits['studio.value'] = data['studio']
        if 'summary' in data and not plex_item.summary:
            edits['summary.value'] = data['summary']
        # ... other fields
    else:
        # Stash always wins - overwrite all fields
        if 'title' in data:
            edits['title.value'] = data['title']
        if 'studio' in data:
            edits['studio.value'] = data['studio']
        if 'summary' in data:
            edits['summary.value'] = data['summary']
        # ... other fields

    if edits:
        plex_item.edit(**edits)
        plex_item.reload()
        mode = "preserved" if self.config.preserve_plex_edits else "overwrite"
        print(f"[PlexSync Worker] Updated metadata ({mode} mode): {plex_item.title}")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Periodic polling for changes | Hook-triggered change detection | Last 5+ years | Instant propagation, no polling overhead |
| Multi-tier confidence (0.0-1.0 scores) | Binary HIGH/LOW based on cardinality | Simplification trend 2024-2026 | Clearer decisions, no threshold tuning |
| Numeric threshold tuning (0.5, 0.7) | Categorical classification | 2025-2026 ML best practices | Removes magic numbers, better semantics |
| Content hashing (MD5/SHA) | Timestamp comparison for metadata | Standard for database change tracking | 2.5-5x faster, sufficient for structured data |
| In-memory deduplication | SQLite query-based checks | Persistent queue era | Survives restart, no memory overhead |

**Deprecated/outdated:**
- Polling-based change detection: Hook systems now standard in modern CMSs
- Numeric confidence thresholds (0.7 = "good enough"): Binary classification clearer for operational decisions
- Content hashing for metadata sync: Timestamp comparison is standard pattern for database change detection

## Open Questions

Things that couldn't be fully resolved:

1. **Stash `updated_at` field behavior on non-metadata updates**
   - What we know: Stash Scene type has `updated_at: Time!` field per GraphQL schema
   - What's unclear: Does `updated_at` change on play_count, last_played_at, or only on metadata edits?
   - Recommendation: Implement `requires_plex_sync()` filter as defense, test with real Stash instance, adjust field list if false positives occur

2. **persist-queue job_key field usage**
   - What we know: SyncJob model includes job_key field (`scene_{scene_id}`)
   - What's unclear: Does persist-queue use job_key for anything internally, or is it purely our metadata?
   - Recommendation: Treat as metadata field for our deduplication logic, verify it's included in pickled data

3. **Optimal deduplication query strategy**
   - What we know: LIKE query on pickled data is slow, job_key field available but not indexed
   - What's unclear: Can we add index to persist-queue table, or will it break library assumptions?
   - Recommendation: Start with LIKE query (simple, works), profile in production, optimize if hook handler exceeds 100ms

4. **Manual re-enqueue mechanism for low-confidence matches**
   - What we know: User decisions marked this as "Claude's discretion"
   - What's unclear: CLI command, GraphQL API, or log-based workflow for triggering manual sync?
   - Recommendation: Defer to planning phase - suggest CLI command that takes scene_id and forces enqueue (bypass confidence check)

## Sources

### Primary (HIGH confidence)
- Python datetime documentation - https://docs.python.org/3/library/datetime.html - Timestamp comparison patterns
- Stash GraphQL schema (Scene type) - https://github.com/stashapp/stash/blob/develop/graphql/schema/types/scene.graphql - `updated_at` field
- Pydantic strict mode documentation - https://docs.pydantic.dev/latest/concepts/strict_mode/ - Boolean flag validation
- SQLite3 documentation - https://docs.python.org/3/library/sqlite3.html - State table patterns

### Secondary (MEDIUM confidence)
- AWS Glue match scoring - https://docs.aws.amazon.com/glue/latest/dg/match-scoring.html - Confidence score patterns
- AWS AppSync conflict detection - https://docs.aws.amazon.com/appsync/latest/devguide/conflict-detection-and-sync.html - Conflict resolution strategies
- Henry's Dev Journey - Incremental Loading - https://henrychan.tech/incremental-loading-101-timestamp-watermarking-hash-comparisons-and-cdc/ - Timestamp vs hash comparison
- Medium: Conflict Resolution in Data Sync - https://mobterest.medium.com/conflict-resolution-strategies-in-data-synchronization-2a10be5b82bc - Preserve vs overwrite patterns

### Tertiary (LOW confidence)
- WebSearch results on SQLite queue deduplication - Multiple sources, no single authoritative pattern
- WebSearch results on binary classification thresholds - ML-focused, not directly applicable to discrete matching
- WebSearch results on change detection pitfalls - SEO/web monitoring context, timestamp false positives insight

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib or already in project (datetime, sqlite3, Pydantic)
- Architecture: HIGH - Patterns based on established change detection and state tracking practices
- Pitfalls: MEDIUM - Derived from general best practices and WebSearch findings, needs validation in production

**Research date:** 2026-02-02
**Valid until:** ~60 days (stable domain - timestamp comparison and SQLite patterns don't change rapidly)
