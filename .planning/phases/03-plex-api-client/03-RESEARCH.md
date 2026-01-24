# Phase 3: Plex API Client - Research

**Researched:** 2026-01-24
**Domain:** Plex API integration, retry patterns, file path matching
**Confidence:** HIGH

## Summary

This phase integrates the python-plexapi library for Plex server communication, adds tenacity for immediate retry handling of network blips, and implements file path matching to locate Plex items. The research confirms that python-plexapi (v4.17.2) provides built-in timeout support both at session and per-request levels, and tenacity (v9.1.2) offers robust retry patterns with exponential backoff and jitter. File path matching in PlexAPI uses the `Media__Part__file` attribute with operators like `__contains`, `__startswith`, and `__icontains` for case-insensitive matching.

The key architectural decision is to use PlexAPI's session-level timeout for most calls (configured via PlexSyncConfig), with tenacity decorators wrapping connection-error-prone operations. Plex-specific exceptions will subclass the existing TransientError/PermanentError hierarchy from Phase 2, maintaining compatibility with the worker's error routing.

**Primary recommendation:** Use python-plexapi with configurable session timeouts (connect: 5s, read: 30s), wrap Plex operations with tenacity retry for connection errors only, and implement case-insensitive filename matching with path prefix stripping as fallback.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| plexapi | 4.17.2 | Plex server communication | Official Python bindings, BSD-3-Clause, 1.3k stars, used by 2.6k projects |
| tenacity | 9.1.2 | Retry with backoff/jitter | Apache-2.0, de facto standard for Python retries, composable wait strategies |
| requests | 2.32+ | HTTP client (PlexAPI dependency) | Already a plexapi dependency, provides timeout tuples |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pathlib | stdlib | Path normalization | Cross-platform path handling |
| urllib3 | (requests dep) | Low-level HTTP | Timeout object for explicit config |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| tenacity | backoff | tenacity is more flexible with wait strategies, better composability |
| tenacity | urllib3.util.retry | tenacity works at application level, not just HTTP; cleaner decorator API |
| plexapi | direct HTTP | plexapi handles auth, pagination, XML parsing; don't reinvent |

**Installation:**
```bash
pip install plexapi>=4.17.0 tenacity>=9.0.0
```

## Architecture Patterns

### Recommended Project Structure
```
PlexSync/
├── plex/                    # NEW: Plex client module
│   ├── __init__.py
│   ├── client.py            # PlexClient wrapper with timeouts
│   ├── exceptions.py        # PlexTemporaryError, PlexPermanentError, PlexNotFound
│   └── matcher.py           # File path matching logic
├── validation/
│   └── errors.py            # Existing - import error classification
└── worker/
    └── processor.py         # Existing - uses PlexClient
```

### Pattern 1: Session-Level Timeout Configuration
**What:** Configure PlexServer with custom timeout at initialization
**When to use:** All Plex API calls
**Example:**
```python
# Source: https://python-plexapi.readthedocs.io/en/stable/configuration.html
from plexapi.server import PlexServer
import requests

# Create session with timeout adapter (requests doesn't support session.timeout)
session = requests.Session()

# PlexServer accepts timeout parameter directly
plex = PlexServer(
    baseurl=config.plex_url,
    token=config.plex_token,
    timeout=config.plex_read_timeout  # Applied to all requests
)
```

### Pattern 2: Tenacity Retry for Connection Errors
**What:** Wrap Plex operations with retry decorator for network-level failures only
**When to use:** Operations that may fail due to network blips (timeouts, refused connections)
**Example:**
```python
# Source: https://tenacity.readthedocs.io/en/latest/
from tenacity import (
    retry,
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    before_sleep_log
)
import logging

logger = logging.getLogger(__name__)

@retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    wait=wait_exponential_jitter(initial=0.1, max=0.5, jitter=0.1),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True  # Raise original exception after final failure
)
def find_plex_item(plex: PlexServer, file_path: str):
    """Find Plex item by file path with automatic retry on network errors."""
    # PlexAPI raises requests.exceptions on network issues
    # These inherit from ConnectionError/OSError
    pass
```

### Pattern 3: Exception Hierarchy with Subclassing
**What:** Plex-specific exceptions that integrate with Phase 2 error classification
**When to use:** All Plex error handling
**Example:**
```python
# Source: Phase 2 existing pattern
from worker.processor import TransientError, PermanentError

class PlexTemporaryError(TransientError):
    """Retry-able Plex errors (network, timeout, 5xx, rate limits)."""
    pass

class PlexPermanentError(PermanentError):
    """Non-retry-able Plex errors (auth, bad request, unsupported)."""
    pass

class PlexNotFound(TransientError):
    """Item not found in Plex - may appear after library scan completes.

    Distinct from PlexTemporaryError to allow different retry timing.
    Plex library scanning can take minutes to hours.
    """
    pass
```

### Pattern 4: File Path Matching with Fallback
**What:** Multi-strategy path matching from exact to fuzzy
**When to use:** Finding Plex items by Stash file path
**Example:**
```python
# Source: https://python-plexapi.readthedocs.io/en/latest/modules/base.html
def find_by_path(library_section, file_path: str):
    """Find Plex item by file path with fallback strategies.

    Strategies (in order):
    1. Exact path match (fastest, most accurate)
    2. Filename-only match (handles path prefix differences)
    3. Case-insensitive filename match (cross-platform)
    """
    from pathlib import Path

    # Strategy 1: Exact path (PlexAPI server-side filtering)
    # Using fetchItems is more efficient than search for path matching
    results = library_section.search(Media__Part__file=file_path)
    if results:
        return results[0]

    # Strategy 2: Filename only (handles Stash vs Plex path differences)
    filename = Path(file_path).name
    results = library_section.search(Media__Part__file__endswith=filename)
    if len(results) == 1:
        return results[0]

    # Strategy 3: Case-insensitive filename (Windows/macOS)
    results = library_section.search(Media__Part__file__iendswith=filename.lower())
    if len(results) == 1:
        return results[0]

    # Multiple matches or no match
    return None
```

### Anti-Patterns to Avoid
- **Global timeout via config file:** Don't rely on ~/.config/plexapi/config.ini - it affects all PlexAPI users on the system. Pass timeout explicitly.
- **Retry on all exceptions:** Only retry on connection-level errors. HTTP 4xx errors won't improve with retry.
- **Blocking on not found:** PlexNotFound should not block the worker - re-queue with exponential backoff for library scanning.
- **Case-sensitive matching:** Always provide case-insensitive fallback for cross-platform compatibility.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry logic | Custom loops with sleep | tenacity | Handles edge cases: jitter, exponential backoff, exception filtering, statistics |
| Plex authentication | Manual X-Plex-Token header | plexapi.server.PlexServer | Handles token refresh, connection selection, header management |
| HTTP timeouts | Thread-based timeouts | requests timeout tuple | Native socket-level timeout, no thread overhead |
| Path matching | String manipulation | PlexAPI operators with pathlib | PlexAPI filters server-side when possible, pathlib handles OS differences |
| Error classification | Manual status code checks | Extend existing classify_http_error | Reuse Phase 2 logic, maintain consistency |

**Key insight:** PlexAPI and tenacity handle the non-obvious edge cases that simple implementations miss: PlexAPI handles connection negotiation (local vs remote, http vs https), and tenacity handles retry statistics, callback hooks, and async support.

## Common Pitfalls

### Pitfall 1: Infinite Timeout Hangs
**What goes wrong:** Plex server becomes unresponsive, API call hangs forever, worker thread blocks
**Why it happens:** Default requests timeout is None (infinite). PlexAPI inherits this.
**How to avoid:** Always pass explicit timeout to PlexServer constructor
**Warning signs:** Worker stops processing new jobs, no error logs, high thread count

### Pitfall 2: Thundering Herd on Retry
**What goes wrong:** Multiple workers retry simultaneously after Plex recovers, overwhelming server
**Why it happens:** Fixed retry intervals cause synchronization
**How to avoid:** Use wait_exponential_jitter or wait_random_exponential from tenacity
**Warning signs:** Plex 503 errors spike after recovery, retry storms in logs

### Pitfall 3: Retrying Permanent Errors
**What goes wrong:** Invalid token keeps retrying, wasting resources, filling logs
**Why it happens:** Catching all exceptions instead of connection-specific ones
**How to avoid:** Use retry_if_exception_type with (ConnectionError, TimeoutError, OSError) only
**Warning signs:** Same error repeated 3+ times for non-network issues

### Pitfall 4: Path Mismatch Between Stash and Plex
**What goes wrong:** File exists in both systems but paths differ (e.g., /media/stash/file.mp4 vs /media/plex/file.mp4)
**Why it happens:** Different mount points, Docker volumes, or network paths
**How to avoid:** Implement fallback matching strategy (exact -> filename -> case-insensitive)
**Warning signs:** High PlexNotFound rate despite files existing

### Pitfall 5: PlexAPI Partial Object Reloads
**What goes wrong:** Accessing attribute triggers unexpected API call, potential timeout
**Why it happens:** PlexAPI auto-reloads PlexPartialObject on missing attribute access
**How to avoid:** Either reload() explicitly when needed, or disable autoreload in config
**Warning signs:** Extra API calls in logs, unexpected latency

### Pitfall 6: PlexNotFound vs Permanent Not Found
**What goes wrong:** Items that genuinely don't exist keep retrying forever
**Why it happens:** PlexNotFound is transient (library scanning), but some items never will exist
**How to avoid:** Track PlexNotFound retry count separately, DLQ after extended retries (e.g., 24 hours)
**Warning signs:** Old PlexNotFound jobs accumulating in queue

## Code Examples

Verified patterns from official sources:

### PlexServer Connection with Timeout
```python
# Source: https://python-plexapi.readthedocs.io/en/latest/modules/server.html
from plexapi.server import PlexServer

def create_plex_client(url: str, token: str, timeout: int = 30) -> PlexServer:
    """Create Plex server connection with explicit timeout."""
    return PlexServer(
        baseurl=url,
        token=token,
        timeout=timeout
    )
```

### Tenacity Retry with Exponential Backoff and Jitter
```python
# Source: https://tenacity.readthedocs.io/en/latest/
from tenacity import (
    retry,
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    before_sleep_log
)
import requests.exceptions
import logging

logger = logging.getLogger(__name__)

# Connection errors that warrant immediate retry
RETRIABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)

@retry(
    retry=retry_if_exception_type(RETRIABLE_EXCEPTIONS),
    wait=wait_exponential_jitter(initial=0.1, max=0.4, jitter=0.1),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def plex_operation_with_retry(func, *args, **kwargs):
    """Execute Plex operation with automatic retry on connection errors."""
    return func(*args, **kwargs)
```

### File Path Matching with PlexAPI Operators
```python
# Source: https://python-plexapi.readthedocs.io/en/latest/modules/base.html
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional
from plexapi.library import LibrarySection
from plexapi.video import Video

def find_plex_item_by_path(
    library: LibrarySection,
    stash_path: str,
    plex_path_prefix: Optional[str] = None,
    stash_path_prefix: Optional[str] = None
) -> Optional[Video]:
    """
    Find Plex item matching a Stash file path.

    Args:
        library: Plex library section to search
        stash_path: File path from Stash
        plex_path_prefix: Optional prefix to prepend for Plex paths
        stash_path_prefix: Optional prefix to strip from Stash paths

    Returns:
        Matching Plex item or None
    """
    # Normalize path (handle both Windows and POSIX paths)
    path = Path(stash_path)
    filename = path.name

    # Apply path prefix mapping if configured
    search_path = stash_path
    if stash_path_prefix and plex_path_prefix:
        if stash_path.startswith(stash_path_prefix):
            search_path = plex_path_prefix + stash_path[len(stash_path_prefix):]

    # Strategy 1: Exact path match (most accurate)
    results = library.search(Media__Part__file=search_path)
    if results:
        return results[0]

    # Strategy 2: Path contains filename (handles directory differences)
    results = library.search(Media__Part__file__endswith=f"/{filename}")
    if len(results) == 1:
        return results[0]

    # Strategy 3: Case-insensitive (Windows/macOS compatibility)
    # Note: __iendswith is case-insensitive endswith
    results = library.search(Media__Part__file__iendswith=f"/{filename.lower()}")
    if len(results) == 1:
        return results[0]

    # Multiple matches: could log for manual review
    return None
```

### Exception Translation from PlexAPI to Phase 2 Hierarchy
```python
# Source: Phase 2 validation/errors.py pattern
from plexapi.exceptions import BadRequest, NotFound, Unauthorized
import requests.exceptions

from worker.processor import TransientError, PermanentError

class PlexTemporaryError(TransientError):
    """Retry-able Plex errors."""
    pass

class PlexPermanentError(PermanentError):
    """Non-retry-able Plex errors."""
    pass

class PlexNotFound(TransientError):
    """Item not in Plex library - may appear after scan."""
    pass

def translate_plex_exception(exc: Exception) -> Exception:
    """Translate PlexAPI or requests exception to Phase 2 hierarchy."""
    # PlexAPI exceptions
    if isinstance(exc, Unauthorized):
        return PlexPermanentError(f"Authentication failed: {exc}")
    if isinstance(exc, NotFound):
        return PlexNotFound(f"Item not found in Plex: {exc}")
    if isinstance(exc, BadRequest):
        return PlexPermanentError(f"Bad request to Plex: {exc}")

    # Network/connection errors (requests)
    if isinstance(exc, (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        ConnectionError,
        TimeoutError,
        OSError
    )):
        return PlexTemporaryError(f"Connection error: {exc}")

    # HTTP errors with status codes
    if hasattr(exc, 'response') and exc.response is not None:
        status = exc.response.status_code
        if status == 401:
            return PlexPermanentError(f"Unauthorized (401): {exc}")
        if status == 404:
            return PlexNotFound(f"Not found (404): {exc}")
        if status in (429, 500, 502, 503, 504):
            return PlexTemporaryError(f"Server error ({status}): {exc}")
        if 400 <= status < 500:
            return PlexPermanentError(f"Client error ({status}): {exc}")

    # Unknown - default to transient (safer, allows retry)
    return PlexTemporaryError(f"Unknown Plex error: {exc}")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No timeout (infinite) | Explicit timeout tuple (connect, read) | Always been best practice | Prevents hung workers |
| Fixed retry sleep | tenacity with jitter | tenacity 4.0+ (2017) | Prevents thundering herd |
| Global plexapi config.ini | Per-instance timeout parameter | plexapi has always supported | Isolation, no side effects |
| String path manipulation | pathlib + PlexAPI operators | Python 3.4+, PlexAPI 4.x | Cross-platform, server-side filtering |

**Deprecated/outdated:**
- plexapi config file timeout: Still works but per-instance is cleaner
- Manual retry loops: tenacity handles all edge cases

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal timeout values for Plex**
   - What we know: PlexAPI default is 30s. Large libraries can take longer.
   - What's unclear: Optimal connect vs read timeout ratio for typical Plex setups
   - Recommendation: Start with connect=5s, read=30s (configurable). Monitor and adjust.

2. **PlexNotFound retry strategy timing**
   - What we know: Library scanning can take minutes to hours
   - What's unclear: When to give up (PlexNotFound vs truly non-existent)
   - Recommendation: Separate retry timing for PlexNotFound (longer delays), DLQ after 24h of NotFound

3. **Multiple match disambiguation**
   - What we know: Filename-only matching can return multiple results
   - What's unclear: Best strategy when multiple Plex items have same filename
   - Recommendation: Log for manual review, don't auto-pick. Return first match with warning.

## Sources

### Primary (HIGH confidence)
- [Python PlexAPI Documentation](https://python-plexapi.readthedocs.io/en/stable/) - Configuration, PlexServer, LibrarySection, operators
- [Tenacity Documentation](https://tenacity.readthedocs.io/en/latest/) - Retry decorators, wait strategies, exception filtering
- [PlexAPI GitHub](https://github.com/pkkid/python-plexapi) - v4.17.2, BSD-3-Clause, active maintenance
- [Tenacity GitHub](https://github.com/jd/tenacity) - v9.1.2, Apache-2.0, active maintenance

### Secondary (MEDIUM confidence)
- [Requests Documentation - Timeouts](https://requests.readthedocs.io/en/latest/user/advanced/) - Timeout tuple (connect, read)
- [Python pathlib Documentation](https://docs.python.org/3/library/pathlib.html) - case_sensitive parameter (3.12+)

### Tertiary (LOW confidence)
- PlexAPI GitHub Issues - Timeout problems and workarounds (user reports, may be version-specific)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official documentation verified for plexapi and tenacity
- Architecture: HIGH - Patterns derived from official docs and existing Phase 2 code
- Pitfalls: MEDIUM - Combination of documentation and user-reported issues
- Path matching: MEDIUM - PlexAPI operators documented, but real-world path differences vary

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - stable libraries, infrequent releases)
