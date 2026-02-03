# Phase 7: Performance Optimization - Research

**Researched:** 2026-02-03
**Domain:** Python caching, Plex API optimization, performance profiling
**Confidence:** HIGH

## Summary

This phase focuses on reducing Plex API calls and improving matching speed through caching and lazy loading. The project already uses SQLite for persistence (via persist-queue) and has established patterns for disk storage. The user has decided on disk-based caching (SQLite or JSON) with lazy loading.

Research indicates two strong library choices for disk-based caching: **diskcache** (SQLite-backed, thread-safe, process-safe, decorator support) and **cachetools** (in-memory with TTL support, can be combined with disk persistence). Given the existing SQLite usage in the project and the need for persistence across restarts, **diskcache** is the recommended primary caching library.

For profiling, Python's built-in **cProfile** is sufficient for identifying bottlenecks. The plexapi library already supports batch editing operations (`batchMultiEdits()`) and provides guidance on building lookup dictionaries for faster GUID/path matching.

**Primary recommendation:** Use diskcache for persistent caching of both Plex library data and match results, with TTL-based invalidation for library data (1 hour) and indefinite caching for match results (invalidate on library changes or manual clear).

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| diskcache | 5.6.x | Persistent SQLite-backed cache | Thread-safe, process-safe, memoize decorator, survives restarts, pure Python |
| cachetools | 7.0.0 | In-memory cache with TTL | Standard for TTL caching, integrates with diskcache patterns |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| cProfile | stdlib | Performance profiling | Identifying bottlenecks before optimization |
| pstats | stdlib | Profile statistics analysis | Sorting and filtering profiling data |
| time.perf_counter | stdlib | High-resolution timing | Measuring specific operations |

### Already in Project
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| persist-queue | >=1.1.0 | SQLite queue storage | Similar pattern to diskcache |
| plexapi | >=4.17.0 | Plex server communication | Has built-in batch editing, caching hints |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| diskcache | shelved-cache + cachetools | More complex setup, less integrated |
| diskcache | cachew | Type-hint focused, less mature |
| diskcache | JSON files | Already using for timestamps; diskcache adds atomic ops, TTL, decorator support |

**Installation:**
```bash
pip install diskcache>=5.6.0
# cachetools only if needed for specific in-memory TTL cases
pip install cachetools>=7.0.0
```

## Architecture Patterns

### Recommended Cache Structure
```
data_dir/
├── queue/               # Existing persist-queue SQLite
├── sync_timestamps.json # Existing timestamp storage
└── cache/               # NEW: diskcache directory
    ├── library_data/    # Plex library item cache (TTL: 1 hour)
    └── match_results/   # Path-to-item match cache (no TTL)
```

### Pattern 1: Lazy Loading with Disk Cache
**What:** Fetch Plex data only when needed, cache results to disk
**When to use:** Any Plex library operation (search, all(), getGuid())
**Example:**
```python
# Source: diskcache tutorial + plexapi documentation
from diskcache import Cache

class CachedPlexLibrary:
    """Lazy-loading Plex library wrapper with disk caching."""

    def __init__(self, plex_client, library_name: str, cache_dir: str):
        self.client = plex_client
        self.library_name = library_name
        self._section = None
        self.cache = Cache(cache_dir)
        self.library_cache_ttl = 3600  # 1 hour

    @property
    def section(self):
        """Lazy load library section."""
        if self._section is None:
            self._section = self.client.server.library.section(self.library_name)
        return self._section

    def get_all_items(self) -> list:
        """Get all library items, cached for TTL duration."""
        cache_key = f"library:{self.library_name}:all"

        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        # Fetch from Plex API
        items = self.section.all()
        self.cache.set(cache_key, items, expire=self.library_cache_ttl)
        return items
```

### Pattern 2: Match Result Caching
**What:** Cache file path to Plex item mappings
**When to use:** After successful file-to-item match
**Example:**
```python
# Source: plexapi guid lookup pattern + diskcache
class MatchCache:
    """Cache for file path to Plex item matches."""

    def __init__(self, cache_dir: str):
        self.cache = Cache(os.path.join(cache_dir, 'match_results'))

    def get_match(self, library_name: str, file_path: str):
        """Get cached match result."""
        key = self._make_key(library_name, file_path)
        return self.cache.get(key)

    def store_match(self, library_name: str, file_path: str, plex_key: str):
        """Store match result (no TTL - invalidate manually)."""
        key = self._make_key(library_name, file_path)
        self.cache.set(key, plex_key)  # No expire = permanent

    def invalidate_library(self, library_name: str):
        """Invalidate all matches for a library."""
        prefix = f"match:{library_name}:"
        for key in list(self.cache):
            if key.startswith(prefix):
                del self.cache[key]

    def _make_key(self, library_name: str, file_path: str) -> str:
        return f"match:{library_name}:{file_path}"
```

### Pattern 3: Profile-First Optimization
**What:** Measure before optimizing, log timing for key operations
**When to use:** Before any optimization work, ongoing monitoring
**Example:**
```python
# Source: Python docs cProfile + project logging patterns
import cProfile
import pstats
import io
import time
from functools import wraps

def profile_sync(func):
    """Decorator to profile sync operations."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()
        start = time.perf_counter()

        try:
            result = func(*args, **kwargs)
            return result
        finally:
            profiler.disable()
            elapsed = time.perf_counter() - start

            # Only log detailed profile if slow (>1s)
            if elapsed > 1.0:
                stream = io.StringIO()
                stats = pstats.Stats(profiler, stream=stream)
                stats.sort_stats('cumulative')
                stats.print_stats(10)  # Top 10 functions
                log_debug(f"Profile for {func.__name__} ({elapsed:.2f}s):\n{stream.getvalue()}")
            else:
                log_trace(f"{func.__name__} completed in {elapsed:.3f}s")

    return wrapper
```

### Pattern 4: GUID Lookup Dictionary (plexapi pattern)
**What:** Pre-build lookup dictionary for batch operations
**When to use:** When processing multiple items against same library
**Example:**
```python
# Source: plexapi documentation - recommended optimization pattern
def build_path_lookup(library_section) -> dict:
    """Build file path to item lookup dictionary."""
    lookup = {}
    for item in library_section.all():
        if hasattr(item, 'media') and item.media:
            for media in item.media:
                if hasattr(media, 'parts') and media.parts:
                    for part in media.parts:
                        if hasattr(part, 'file') and part.file:
                            lookup[part.file.lower()] = item
    return lookup
```

### Anti-Patterns to Avoid
- **Eager loading:** Don't fetch entire library on startup - use lazy loading
- **Per-request library scans:** Don't call `library.all()` for each file match - cache or use lookup dict
- **Uncached repeated searches:** Don't repeat `library.search()` for same title without caching
- **Memory-only caching:** Don't use functools.lru_cache alone - loses data on restart
- **Overly aggressive TTL:** Don't expire library cache too fast (<5 min) - wastes API calls

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Disk-based caching | Custom SQLite cache | diskcache | Thread-safety, atomic ops, TTL, tested |
| TTL cache decorator | Manual timestamp tracking | cachetools.TTLCache or diskcache.memoize | Handles expiration automatically |
| Profiling | Manual timing everywhere | cProfile + pstats | Built-in, low overhead, detailed output |
| Batch Plex edits | Multiple edit() calls | plexapi batchMultiEdits() | Single API call vs N calls |
| Path normalization | Manual string manipulation | pathlib.Path | Cross-platform, handles edge cases |

**Key insight:** The project already uses SQLite-based persistence (persist-queue). Adding diskcache maintains consistency and leverages proven patterns rather than building custom cache management.

## Common Pitfalls

### Pitfall 1: Cache Stampede
**What goes wrong:** Multiple requests hit expired cache simultaneously, all fetch from API
**Why it happens:** TTL expires, N threads all see cache miss, all call Plex API
**How to avoid:** Use diskcache's built-in locking or implement cache refresh before expiry
**Warning signs:** Sudden spike in API calls after cache expiry period

### Pitfall 2: Stale Match Results
**What goes wrong:** Cached path-to-item match becomes invalid after library changes
**Why it happens:** Plex library rescanned, items moved/renamed, cache not invalidated
**How to avoid:** Invalidate match cache on library scan events, or use TTL as safety net
**Warning signs:** Jobs failing with PlexNotFound after library changes

### Pitfall 3: Memory Bloat from Full Library Cache
**What goes wrong:** Caching all library items keeps plexapi objects in memory indefinitely
**Why it happens:** plexapi objects contain references, may not be garbage collected
**How to avoid:** Cache only essential data (keys, paths, GUIDs), not full objects
**Warning signs:** Memory usage grows over time, never decreases

### Pitfall 4: Over-optimization Without Measurement
**What goes wrong:** Optimizing the wrong code paths, minimal improvement
**Why it happens:** Assuming where bottlenecks are instead of measuring
**How to avoid:** Profile first, identify actual hot paths, then optimize
**Warning signs:** Optimization effort doesn't reduce total sync time

### Pitfall 5: SQLite Thread/Process Conflicts
**What goes wrong:** Database locked errors, corrupted cache
**Why it happens:** Multiple threads/processes accessing same SQLite file without proper handling
**How to avoid:** Use diskcache (handles this) or configure SQLite journal_mode=WAL
**Warning signs:** "database is locked" errors in logs

## Code Examples

Verified patterns from official sources:

### Creating Disk Cache with TTL
```python
# Source: diskcache tutorial
from diskcache import Cache

cache = Cache('/path/to/cache/directory')

# Set with TTL (expires after 3600 seconds)
cache.set('key', value, expire=3600)

# Get (returns None if expired/missing)
value = cache.get('key')

# Delete
del cache['key']

# Clear all
cache.clear()
```

### Memoization with Disk Cache
```python
# Source: diskcache tutorial
from diskcache import Cache

cache = Cache('/path/to/cache')

@cache.memoize(typed=True, expire=3600, tag='plex_search')
def search_plex_library(library_name: str, title: str):
    """Search Plex library - results cached for 1 hour."""
    section = plex.library.section(library_name)
    return section.search(title=title)
```

### Cache Statistics
```python
# Source: diskcache tutorial
cache = Cache('/path/to/cache')

# Enable stats collection
cache.stats(enable=True)

# ... operations ...

# Get and reset stats
hits, misses = cache.stats(enable=False, reset=True)
hit_rate = hits / (hits + misses) if (hits + misses) > 0 else 0
log_info(f"Cache hit rate: {hit_rate:.1%} ({hits} hits, {misses} misses)")
```

### Batch Multi-Edit in PlexAPI
```python
# Source: plexapi library documentation
# Enable batch mode - accumulates edits
items = library.all()
library.batchMultiEdits(items)

# Make multiple edits (no API calls yet)
for item in items:
    item.editTitle(...)
    item.editSummary(...)

# Single API call for all edits
library.saveMultiEdits()
```

### Simple Timing Decorator
```python
# Source: Python docs time module
import time
from functools import wraps

def timed(func):
    """Log execution time for function."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        log_debug(f"{func.__name__} took {elapsed:.3f}s")
        return result
    return wrapper
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| functools.lru_cache only | Disk-backed caching (diskcache) | 2020+ | Cache survives restarts |
| Per-item Plex edits | batchMultiEdits() | plexapi 4.13+ | N API calls to 1 |
| Library.all() per search | Cached lookup dictionary | Best practice | Massive API reduction |
| cProfile manual analysis | SnakeViz visualization | Available | Easier bottleneck identification |

**Deprecated/outdated:**
- shelve module: Replaced by diskcache for similar use cases (better thread safety)
- Custom SQLite caching: diskcache provides this with better API

## Cache Invalidation Recommendations

Based on CONTEXT.md granting discretion on invalidation strategy:

### Library Data Cache (Plex items, search results)
**Strategy:** TTL-based with 1-hour expiry
**Rationale:** Library changes are infrequent (scans, new media), 1 hour balances freshness vs API savings
**Implementation:**
```python
cache.set('library:Movies:all', items, expire=3600)
```

### Match Results Cache (path-to-item mappings)
**Strategy:** Indefinite storage with manual/event invalidation
**Rationale:** File paths don't change often; invalidate when:
1. Plex library scan detected (event-based)
2. Match failure suggests stale cache (auto-invalidation on PlexNotFound)
3. Manual clear via config option (optional)

**Implementation:**
```python
# Store match (no TTL)
cache.set(match_key, plex_item_key)

# Invalidate on failed lookup
if match_failed:
    del cache[match_key]
```

### Manual Cache Clear (Claude's Discretion)
**Recommendation:** Add optional `clear_cache` config flag
**Rationale:** Useful for debugging, not needed for normal operation
**Implementation:** Check flag on startup, clear cache directories if True

## Batch Processing Recommendations

Based on CONTEXT.md granting discretion on batching:

### Operations to Batch
1. **Plex metadata edits:** Use batchMultiEdits() when updating multiple items in same library
2. **Cache writes:** diskcache handles batching internally via SQLite transactions

### Operations NOT to Batch
1. **Job processing:** Process one job at a time (matches existing queue pattern)
2. **Plex library scanning:** Don't batch multiple library.all() calls (each is already complete)

### Batch Error Handling
**Recommendation:** Fail entire batch for Plex edits
**Rationale:** batchMultiEdits() is atomic; partial success complicates error handling and retry logic

## Open Questions

Things that couldn't be fully resolved:

1. **plexapi object serialization**
   - What we know: diskcache uses pickle for serialization
   - What's unclear: Whether plexapi Video objects pickle cleanly or need simplification
   - Recommendation: Test during implementation; may need to cache only essential fields (key, title, file paths)

2. **Cache size limits**
   - What we know: diskcache supports size_limit parameter
   - What's unclear: Optimal size for typical Plex library (1000s of items)
   - Recommendation: Start with 100MB limit, monitor and adjust

3. **Library scan event detection**
   - What we know: Plex has webhooks, plexapi has alerts
   - What's unclear: Best way to detect library scans for cache invalidation
   - Recommendation: Start with TTL-only; add event detection if needed

## Sources

### Primary (HIGH confidence)
- [diskcache tutorial](https://grantjenks.com/docs/diskcache/tutorial.html) - Core API, memoize decorator, thread safety
- [cachetools documentation](https://cachetools.readthedocs.io/en/stable/) - TTLCache API, decorator patterns
- [Python profilers documentation](https://docs.python.org/3/library/profile.html) - cProfile usage
- [plexapi library documentation](https://python-plexapi.readthedocs.io/en/latest/modules/library.html) - batchMultiEdits, guid lookup pattern

### Secondary (MEDIUM confidence)
- [plexapi base module](https://python-plexapi.readthedocs.io/en/latest/modules/base.html) - cached_data_property, lazy loading
- [Talk Python diskcache episode](https://talkpython.fm/episodes/show/534/diskcache-your-secret-python-perf-weapon) - Real-world usage patterns

### Tertiary (LOW confidence)
- WebSearch results for batch API patterns - General best practices, verify with implementation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Libraries are well-documented, widely used
- Architecture: HIGH - Patterns verified in official documentation
- Pitfalls: MEDIUM - Based on general caching knowledge plus project specifics
- Batch operations: MEDIUM - plexapi batchMultiEdits verified, but limited real-world examples

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (30 days - stable domain)
