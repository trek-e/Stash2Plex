# Technology Stack

**Project:** PlexSync Improvements
**Researched:** 2026-01-24
**Confidence:** HIGH

## Executive Summary

The recommended stack focuses on reliability improvements for an existing Python plugin. Choose **Tenacity** for retry logic (battle-tested, actively maintained), **persist-queue** for SQLite-backed task persistence (zero external dependencies), and **Pydantic** for input validation (fast, Rust-backed). Avoid heavyweight task queues like Celery or RQ that require Redis - the plugin context demands lightweight, embedded solutions.

## Recommended Stack

### Core Dependencies (Keep)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.11+ | Runtime | stashapi requires >=3.11; use 3.11 for best compatibility |
| stashapi | 0.1.3 | Stash integration | Official API wrapper, latest release Dec 2025, supports Python 3.11-3.13 |
| requests | 2.32.5 | HTTP client | Industry standard, latest Aug 2025, built-in retry adapter support via HTTPAdapter |
| unidecode | 1.4.0 | Text normalization | Current dependency, latest Apr 2025, adequate for title cleaning |

**Confidence:** HIGH - All verified from official PyPI sources and GitHub releases

### New Dependencies (Add)

| Library | Version | Purpose | Why | Confidence |
|---------|---------|---------|-----|------------|
| tenacity | 9.1.2 | Retry logic | Battle-tested (1,034+ stars), actively maintained fork of deprecated retrying library. Supports exponential backoff, stop conditions, async. Latest Apr 2025. | HIGH |
| persist-queue | 1.1.0 | Task persistence | SQLite-backed queue with no Redis dependency. WAL mode for performance, acknowledgment support via SQLiteAckQueue. Perfect for embedded plugin use. Latest Oct 2025. | HIGH |
| pydantic | 2.12.5 | Input validation | Rust-backed validation (fastest in ecosystem). Type-hint based API. Industry standard (used by FastAPI, LangChain). Latest Nov 2025. | HIGH |
| pybreaker | 1.4.1 | Circuit breaker | Production-stable, prevents cascading failures to Plex. Configurable thresholds, async support. Latest Sep 2025. | MEDIUM |

**Confidence notes:**
- tenacity: Verified via GitHub + PyPI. Clear successor to unmaintained retrying.
- persist-queue: Verified via PyPI. SQLiteAckQueue added recently for acknowledgment patterns.
- pydantic: Verified via PyPI. V2 is stable, V3 mentioned in blogs but not released yet.
- pybreaker: Verified via PyPI. Mature library (production/stable status).

### Optional Dependencies (Defer)

| Library | Version | Purpose | When to Add |
|---------|---------|---------|-------------|
| structlog | Latest | Structured logging | Only if JSON logs needed for production monitoring. Current logging.Logger sufficient for MVP. |
| text-unidecode | Latest | GPL-free alternative | Only if GPL licensing becomes issue. unidecode works fine and is already installed. |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not | Confidence |
|----------|-------------|-------------|---------|------------|
| Retry | tenacity | urllib3.util.Retry with requests.HTTPAdapter | HTTPAdapter only handles HTTP retries; tenacity works for any function including Stash API calls, metadata processing, etc. | HIGH |
| Retry | tenacity | backoff library | backoff is simpler but tenacity has better async support and more granular control. Both good options. | MEDIUM |
| Task Queue | persist-queue (SQLite) | Huey | Huey requires Redis/external broker. Plugin context needs embedded solution. | HIGH |
| Task Queue | persist-queue (SQLite) | RQ (Redis Queue) | RQ requires Redis server. Too heavyweight for plugin that should "just work" without infrastructure. | HIGH |
| Task Queue | persist-queue (SQLite) | Celery | Massive overkill. Requires broker (Redis/RabbitMQ), separate worker processes. Plugin needs lightweight embedded queue. | HIGH |
| Task Queue | persist-queue (SQLite) | litequeue | Both SQLite-based, but persist-queue has better acknowledgment API (nack, ack_failed) and thread safety guarantees. | MEDIUM |
| Circuit Breaker | pybreaker | circuitbreaker | Both viable. pybreaker has better async support and more recent maintenance. | MEDIUM |
| Validation | pydantic | marshmallow | Pydantic faster (Rust-backed), type-hint native. Marshmallow older pattern (schema classes). | HIGH |
| Validation | pydantic | dataclasses + manual validation | Pydantic adds runtime validation to dataclasses pattern. Manual validation error-prone. | HIGH |
| Plex API | requests (direct) | python-plexapi (4.17.2) | PlexSync only needs single PUT endpoint (refresh metadata). python-plexapi is 4.1MB library for full Plex control. Overkill. | MEDIUM |

**Key decision rationale:**

**Why not Huey/RQ/Celery?** Plugin architecture demands embedded, zero-config solution. These require external services (Redis) and separate worker processes. persist-queue uses SQLite (single file, no daemon) and integrates directly in plugin process.

**Why not python-plexapi?** Current code uses simple requests.put() to Plex refresh endpoint. python-plexapi is comprehensive wrapper for full Plex control (playback, library management, etc.). For PlexSync's narrow use case (just metadata refresh), requests is sufficient and reduces attack surface.

**Why Tenacity over HTTPAdapter?** HTTPAdapter (requests built-in) handles HTTP-level retries well, but PlexSync needs retries for:
- Plex API calls (HTTP) - could use HTTPAdapter
- Stash API calls via stashapi (GraphQL) - can't use HTTPAdapter
- Metadata processing logic - can't use HTTPAdapter
- Queue operations - can't use HTTPAdapter

Tenacity provides unified retry decorator for all failure points.

## Installation

### Requirements File

```txt
# Core (existing)
stashapi==0.1.3
requests==2.32.5
unidecode==1.4.0

# Reliability improvements (new)
tenacity==9.1.2
persist-queue==1.1.0
pydantic==2.12.5
pybreaker==1.4.1
```

### Install Command

```bash
pip install -r requirements.txt
```

### Version Pinning Strategy

Pin exact versions (==) for stability in plugin environment. Users install via Stash plugin manager which doesn't do dependency resolution well. Exact pins prevent breakage.

For development/testing, use compatible release (~=) to get patches:
```txt
tenacity~=9.1.2  # allows 9.1.3, 9.1.4, etc but not 9.2.0
```

## Integration Patterns

### Retry with Tenacity

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    reraise=True
)
def refresh_plex_metadata(plex_url, auth_token, item_id):
    """Retry Plex API calls with exponential backoff."""
    response = requests.put(
        f"{plex_url}/library/metadata/{item_id}/refresh",
        headers={"X-Plex-Token": auth_token},
        timeout=10
    )
    response.raise_for_status()
    return response
```

### Task Persistence with persist-queue

```python
from persistqueue import SQLiteAckQueue
import json

# Initialize queue (survives process restarts)
queue = SQLiteAckQueue(path="./plexsync_queue", auto_commit=True)

# Producer: Add task when Stash event fires
def on_scene_update(scene_id, metadata):
    task = {
        "scene_id": scene_id,
        "metadata": metadata,
        "timestamp": time.time()
    }
    queue.put(json.dumps(task))

# Consumer: Process tasks with acknowledgment
def process_queue():
    while True:
        item = queue.get()  # Locks item (status=1)
        try:
            task = json.loads(item)
            refresh_plex_metadata(task["scene_id"], task["metadata"])
            queue.ack(item)  # Mark done (status=2)
        except Exception as e:
            queue.nack(item)  # Return to queue for retry
            log.error(f"Task failed: {e}")
```

### Input Validation with Pydantic

```python
from pydantic import BaseModel, HttpUrl, Field, validator

class PlexConfig(BaseModel):
    url: HttpUrl
    token: str = Field(min_length=20, max_length=200)
    library_id: int = Field(gt=0)

    @validator('token')
    def token_not_placeholder(cls, v):
        if v in ('YOUR_TOKEN_HERE', 'placeholder', ''):
            raise ValueError('Plex token must be configured')
        return v

class SceneMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    date: str | None = None
    performers: list[str] = []

    @validator('title')
    def clean_title(cls, v):
        # Sanitize before sending to Plex
        return unidecode(v.strip())

# Usage
config = PlexConfig(url="http://localhost:32400", token="abc123...", library_id=1)
metadata = SceneMetadata(title="Scene Title", performers=["Performer 1"])
```

### Circuit Breaker with pybreaker

```python
from pybreaker import CircuitBreaker

# Prevent hammering Plex when it's down
plex_breaker = CircuitBreaker(
    fail_max=5,  # Open after 5 failures
    reset_timeout=60,  # Try again after 60s
    name="plex_api"
)

@plex_breaker
def call_plex_api(url, token):
    """Wrapped with circuit breaker - fails fast when Plex is down."""
    response = requests.put(url, headers={"X-Plex-Token": token}, timeout=10)
    response.raise_for_status()
    return response
```

## Migration Path

### Phase 1: Add Validation (Low Risk)
- Add pydantic models for config and metadata
- Validate inputs before processing
- No behavior change, just safety

### Phase 2: Add Retry (Medium Risk)
- Wrap Plex API calls with tenacity
- Start with conservative limits (3 retries, 30s max wait)
- Monitor logs for retry frequency

### Phase 3: Add Queue (High Risk)
- Replace immediate sync with queue-based processing
- Use SQLiteAckQueue for persistence
- Requires testing process restart scenarios

### Phase 4: Add Circuit Breaker (Optional)
- Add pybreaker to prevent cascading failures
- Only needed if Plex downtime is frequent issue

## Version Compatibility Matrix

| Python Version | stashapi | tenacity | persist-queue | pydantic | pybreaker |
|----------------|----------|----------|---------------|----------|-----------|
| 3.11 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 3.12 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 3.13 | ✓ | ✓ | ✓ | ✓ | ✓ |

**Recommendation:** Develop on Python 3.11 (stashapi developer recommendation). Test on 3.12 and 3.13 if users report issues.

## Security Considerations

### Dependency Audit
All recommended libraries are:
- Actively maintained (updates in 2025)
- Popular (tenacity 1K+ stars, pydantic used by FastAPI)
- Pure Python or trusted Rust extensions (pydantic)
- Minimal dependency trees

### Known Issues
- **pydantic:** Uses Rust extensions (pydantic-core). Ensure users have wheel support or Rust compiler.
- **persist-queue:** File-based queue. Ensure queue directory has proper permissions.
- **unidecode:** GPL license. If plugin distribution becomes issue, migrate to text-unidecode (MIT).

### Best Practices
1. Pin exact versions in requirements.txt
2. Validate all external inputs (Stash events, config files) with pydantic
3. Use timeout on all HTTP calls (already in examples)
4. Never log tokens/credentials (pydantic can mark fields as Secret)

## Testing Strategy

### Unit Tests
- Mock stashapi and requests for fast tests
- Test retry logic with controlled failures
- Test pydantic validation with invalid inputs

### Integration Tests
- Test against real Stash instance (GraphQL API)
- Test queue persistence across process restarts
- Test circuit breaker state transitions

### Recommended Libraries
- pytest (test framework)
- pytest-mock (mocking)
- responses (HTTP mocking)
- fakeredis (not needed - using SQLite queue)

## Performance Characteristics

### Memory Footprint
- **persist-queue:** SQLite file-based, minimal RAM. Queue items on disk.
- **pydantic:** Rust-backed validation is faster than pure Python alternatives.
- **tenacity:** Negligible overhead. Only active during retry.

### Disk Usage
- **Queue database:** Grows with unprocessed tasks. Implement cleanup of old completed tasks.
- **SQLite WAL files:** persist-queue uses WAL mode. Expect .db-wal and .db-shm files.

### Network
- **Retry logic:** May increase Plex API calls during failures. Exponential backoff mitigates.
- **Circuit breaker:** Reduces calls when Plex is down (fail-fast instead of retry).

## Future Considerations

### When to Upgrade
- **tenacity:** Watch for 10.x if API changes
- **pydantic:** V3 is mentioned in blogs but not released. Stay on V2 (stable).
- **persist-queue:** Check for async queue improvements in 2.x

### Migration Triggers
- **Stash API changes:** Monitor stashapi releases for breaking changes
- **Python 3.14+:** Verify library compatibility when upgrading Python
- **GPL concerns:** If unidecode license becomes issue, migrate to text-unidecode

### Scaling Limits
Current stack suitable for:
- Single-user Stash instance
- 100s of scenes
- 10s of updates per day

If scaling beyond this (multi-tenant, 1000s of scenes/day):
- Consider migrating persist-queue to Redis-backed Huey
- Add metrics/monitoring (prometheus_client)
- Implement batch processing for Plex refreshes

## Sources

### Official Documentation (HIGH Confidence)
- [Tenacity GitHub](https://github.com/jd/tenacity) - v9.1.2, Apr 2025
- [Tenacity PyPI](https://pypi.org/project/tenacity/) - Official package repository
- [Huey GitHub](https://github.com/coleifer/huey) - v2.6.0, Jan 2026
- [Huey PyPI](https://pypi.org/project/huey/) - Official package repository
- [Pydantic Documentation](https://docs.pydantic.dev/latest/) - Official docs
- [Pydantic PyPI](https://pypi.org/project/pydantic/) - v2.12.5, Nov 2025
- [stashapi PyPI](https://pypi.org/project/stashapi/) - v0.1.3, Dec 2025
- [persist-queue PyPI](https://pypi.org/project/persist-queue/) - v1.1.0, Oct 2025
- [pybreaker PyPI](https://pypi.org/project/pybreaker/) - v1.4.1, Sep 2025
- [requests PyPI](https://pypi.org/project/requests/) - v2.32.5, Aug 2025
- [Unidecode PyPI](https://pypi.org/project/Unidecode/) - v1.4.0, Apr 2025
- [python-plexapi GitHub](https://github.com/pkkid/python-plexapi) - v4.17.2, Nov 2025

### Community Resources (MEDIUM Confidence)
- [Python Retry Best Practices 2025](https://oxylabs.io/blog/python-requests-retry) - Retry patterns
- [How to Retry Failed Python Requests](https://www.zenrows.com/blog/python-requests-retry) - HTTPAdapter vs libraries
- [Python Task Queues Comparison](https://judoscale.com/blog/choose-python-task-queue) - Queue selection guide
- [Lightweight Task Queues 2025](https://medium.com/@g.suryawanshi/lightweight-django-task-queues-in-2025-beyond-celery-74a95e0548ec) - Beyond Celery
- [Python Logging Best Practices](https://betterstack.com/community/guides/logging/python/python-logging-best-practices/) - Structured logging
- [Stash Plugin Development](https://deepwiki.com/stashapp/CommunityScripts/6.2-plugin-development) - Plugin architecture
- [Python Circuit Breaker Pattern](https://thebackenddevelopers.substack.com/p/implementing-the-circuit-breaker) - PyBreaker usage

### Ecosystem Discovery (MEDIUM Confidence)
- [Stash CommunityScripts](https://github.com/stashapp/CommunityScripts) - Plugin repository
- [Pydantic v3 Overview](https://codemagnet.in/2025/12/15/pydantic-v3-the-new-standard-for-data-validation-in-python-why-everything-changed-in-2025/) - Future versions
- [text-unidecode alternative](https://github.com/kmike/text-unidecode) - GPL-free option
