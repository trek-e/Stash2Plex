# Phase 3: Integration Tests - Research

**Researched:** 2026-02-03
**Domain:** Python Integration Testing with pytest (mocked external services)
**Confidence:** HIGH

## Summary

This research focuses on implementing end-to-end integration tests for PlexSync with mocked external services (Plex API, Stash GraphQL API). The project already has a solid unit testing foundation with 445 tests, pytest infrastructure, and extensive fixtures in `conftest.py`. Integration tests should exercise the full sync workflow - from hook handler through queue processing to Plex metadata updates - while maintaining test isolation through mocking.

The standard approach for Python integration testing in 2026 uses pytest with pytest-mock for general mocking, combined with specialized libraries for time control (freezegun or time-machine) when testing delayed retry logic. The existing test patterns in the codebase already demonstrate effective use of `unittest.mock.patch` for simulating external service behavior.

**Primary recommendation:** Build integration tests using the existing pytest-mock infrastructure, extending conftest.py with workflow-level fixtures that compose existing mocks (queue + processor + plex client) into complete test scenarios. Use pytest markers (`@pytest.mark.integration`) to distinguish integration tests from unit tests.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=9.0.0 | Test framework | Already in use, de facto Python standard |
| pytest-mock | >=3.14.0 | Mocking helper | Already in use, cleaner API than raw unittest.mock |
| pytest-cov | >=6.0.0 | Coverage reporting | Already in use, integrated with pytest |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| freezegun | >=1.4.0 | Time mocking | Circuit breaker timeout tests, backoff delay tests |
| pytest-timeout | >=2.3.0 | Test timeout limits | Prevent hanging integration tests |
| responses | >=0.25.0 | HTTP mocking | If testing any direct HTTP (unlikely needed) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| freezegun | time-machine | time-machine is faster (C extension) but less portable to Windows; freezegun is well-supported and simpler |
| responses | httpretty | responses works with requests library specifically; httpretty is socket-level but more complex |
| pytest-timeout | manual timeout | Plugin handles graceful failures; manual requires more boilerplate |

**Installation:**
```bash
pip install freezegun>=1.4.0 pytest-timeout>=2.3.0
```

**Note:** Project already has pytest, pytest-mock, pytest-cov in requirements-dev.txt.

## Architecture Patterns

### Recommended Test Structure
```
tests/
├── conftest.py           # Shared fixtures (already exists)
├── integration/          # NEW: Integration test folder
│   ├── __init__.py
│   ├── conftest.py       # Integration-specific fixtures
│   ├── test_full_sync_workflow.py
│   ├── test_error_scenarios.py
│   ├── test_queue_persistence.py
│   └── test_circuit_breaker.py
├── hooks/
├── plex/
├── sync_queue/
└── worker/
```

### Pattern 1: Layered Mock Composition
**What:** Build integration fixtures by composing existing unit test fixtures
**When to use:** When testing workflows that span multiple modules
**Example:**
```python
# Source: Derived from existing conftest.py patterns
@pytest.fixture
def integration_worker(mock_queue, mock_dlq, mock_config, mock_plex_server):
    """Complete worker with all dependencies mocked."""
    from worker.processor import SyncWorker

    worker = SyncWorker(
        queue=mock_queue,
        dlq=mock_dlq,
        config=mock_config,
    )

    # Mock the Plex client to return our mock server
    mock_client = MagicMock()
    mock_client.server = mock_plex_server
    worker._plex_client = mock_client

    return worker
```

### Pattern 2: Scenario-Based Test Classes
**What:** Group tests by error scenario or workflow path
**When to use:** Organizing integration tests by real-world conditions
**Example:**
```python
# Source: Common pytest pattern
class TestPlexDownScenarios:
    """Tests for when Plex server is unavailable."""

    def test_connection_error_triggers_retry(self, integration_worker):
        """Job retries on Plex connection failure."""
        # Arrange
        # Act
        # Assert

    def test_circuit_breaker_opens_after_repeated_failures(self, integration_worker):
        """Circuit opens after 5 consecutive failures."""
        pass
```

### Pattern 3: Time-Controlled Tests for Retry Logic
**What:** Use freezegun to control time during tests that involve delays
**When to use:** Testing backoff delays, circuit breaker recovery timeouts
**Example:**
```python
# Source: https://github.com/spulec/freezegun
import pytest
from freezegun import freeze_time

class TestCircuitBreakerRecovery:

    @freeze_time("2026-01-01 12:00:00", auto_tick_seconds=0)
    def test_circuit_opens_and_recovers(self, integration_worker, freezer):
        """Circuit transitions CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
        # Open the circuit
        for _ in range(5):
            integration_worker.circuit_breaker.record_failure()

        assert integration_worker.circuit_breaker.state == CircuitState.OPEN

        # Advance time past recovery timeout (60s)
        freezer.move_to("2026-01-01 12:01:30")

        assert integration_worker.circuit_breaker.state == CircuitState.HALF_OPEN
```

### Anti-Patterns to Avoid
- **Testing implementation details:** Don't assert on internal state unless it affects behavior
- **Over-mocking:** Mock at service boundaries only (Plex API, Stash API), not internal classes
- **Slow sequential tests:** Use `pytest-xdist` for parallelization if tests multiply
- **Network-dependent tests:** Never make real API calls in integration tests

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time mocking | Manual `time.time()` patches | freezegun | Handles datetime, time, calendar modules consistently |
| Test timeouts | `signal.alarm()` wrappers | pytest-timeout | Handles thread safety, reports stack traces |
| HTTP mocking | Manual socket patches | responses/httpretty | Edge cases with encoding, redirects, chunked |
| Test fixtures | Test class setUp/tearDown | pytest fixtures | Better composition, scoping, cleanup |
| Coverage tracking | Manual instrumentation | pytest-cov | Integrated reporting, branch coverage |

**Key insight:** Integration tests are complex enough without reinventing test infrastructure. Use the established tools - they handle edge cases you won't anticipate.

## Common Pitfalls

### Pitfall 1: Test State Leakage
**What goes wrong:** One test modifies global state (like `_pending_scene_ids`) that affects other tests
**Why it happens:** Integration tests touch more shared state than unit tests
**How to avoid:** Use `autouse=True` fixtures for cleanup (already done in handlers tests)
**Warning signs:** Tests pass in isolation but fail when run together

### Pitfall 2: Mock Depth Confusion
**What goes wrong:** Mocking at wrong level - too shallow misses bugs, too deep is brittle
**Why it happens:** Integration boundary unclear between "our code" and "external service"
**How to avoid:** Mock at the HTTP/API boundary (PlexServer.library.section.search), not internal methods
**Warning signs:** Tests pass but real integration fails; or tests break on every refactor

### Pitfall 3: Freezegun Fixture Interaction
**What goes wrong:** Time is not frozen in pytest fixtures when using `@freeze_time` decorator
**Why it happens:** Decorator applies only to test function, not fixture setup
**How to avoid:** Use `pytest.mark.freeze_time` from pytest-freezegun, or pass `freezer` fixture
**Warning signs:** Time-sensitive fixtures create unexpected timestamps

### Pitfall 4: SQLite Database Locking in Tests
**What goes wrong:** Tests using real SQLite queue fail with "database is locked"
**Why it happens:** persist-queue uses SQLite, multiple connections conflict
**How to avoid:** Use `tmp_path` fixture for isolated database per test (already done in DLQ tests)
**Warning signs:** Random test failures on CI, especially under parallel execution

### Pitfall 5: Circuit Breaker State Persistence
**What goes wrong:** Circuit breaker state from one test affects another
**Why it happens:** CircuitBreaker instance lives on worker, worker may be reused
**How to avoid:** Create fresh worker per test or call `circuit_breaker.reset()` in teardown
**Warning signs:** Test order matters; first test passes, subsequent fail

### Pitfall 6: Async vs Sync Test Confusion
**What goes wrong:** Testing threaded worker loop with synchronous assertions
**Why it happens:** Worker runs in background thread; test asserts before work completes
**How to avoid:** Don't test the infinite loop directly; test `_process_job()` synchronously
**Warning signs:** Flaky tests, race conditions, tests that pass with `time.sleep()`

## Code Examples

Verified patterns from official sources and existing codebase:

### Full Workflow Integration Test
```python
# Source: Derived from existing test_plex_integration.py patterns
import pytest
from unittest.mock import Mock, MagicMock, patch

class TestFullSyncWorkflow:
    """Integration tests for complete sync flow."""

    @pytest.fixture
    def mock_stash_scene(self):
        """Complete Stash scene data."""
        return {
            "id": "123",
            "title": "Test Scene",
            "details": "Description",
            "studio": {"name": "Test Studio"},
            "performers": [{"name": "Performer One"}],
            "tags": [{"name": "Tag One"}],
            "files": [{"path": "/media/test.mp4"}],
        }

    @pytest.fixture
    def integration_setup(self, mock_queue, mock_dlq, mock_config, mock_plex_item, tmp_path):
        """Complete integration environment."""
        from worker.processor import SyncWorker

        # Create worker with mocked dependencies
        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Mock Plex client to return found item
        mock_section = MagicMock()
        mock_section.search.return_value = [mock_plex_item]

        mock_client = MagicMock()
        mock_client.server.library.sections.return_value = [mock_section]
        mock_client.server.library.section.return_value = mock_section
        worker._plex_client = mock_client

        return worker, mock_plex_item

    def test_metadata_syncs_to_plex(self, integration_setup):
        """Job with valid metadata updates Plex item."""
        worker, mock_plex_item = integration_setup

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {
                'path': '/media/test.mp4',
                'title': 'New Title',
                'studio': 'New Studio',
                'details': 'New description',
            },
            'pqid': 1,
        }

        # Process the job
        worker._process_job(job)

        # Verify Plex item was updated
        mock_plex_item.edit.assert_called()
        call_kwargs = mock_plex_item.edit.call_args.kwargs
        assert call_kwargs.get('title.value') == 'New Title'
        assert call_kwargs.get('studio.value') == 'New Studio'
```

### Error Scenario Test
```python
# Source: Derived from existing error handling patterns
class TestPlexErrorScenarios:
    """Tests for Plex error handling."""

    def test_plex_not_found_raises_transient(self, integration_setup):
        """Missing Plex item raises PlexNotFound (transient)."""
        from plex.exceptions import PlexNotFound

        worker, _ = integration_setup

        # Configure search to return empty (item not found)
        worker._plex_client.server.library.sections.return_value[0].search.return_value = []

        job = {
            'scene_id': 999,
            'update_type': 'metadata',
            'data': {'path': '/nonexistent.mp4'},
            'pqid': 1,
        }

        with pytest.raises(PlexNotFound):
            worker._process_job(job)

    def test_connection_error_raises_transient(self, integration_setup):
        """Connection error translates to PlexTemporaryError."""
        from plex.exceptions import PlexTemporaryError

        worker, _ = integration_setup
        worker._plex_client.server.library.sections.side_effect = ConnectionError("refused")

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/test.mp4'},
            'pqid': 1,
        }

        with pytest.raises(PlexTemporaryError):
            worker._process_job(job)
```

### Circuit Breaker Integration Test with Time Control
```python
# Source: Combined from freezegun docs and existing circuit_breaker tests
from freezegun import freeze_time
from worker.circuit_breaker import CircuitState

class TestCircuitBreakerBehavior:
    """Integration tests for circuit breaker with worker."""

    def test_circuit_opens_after_consecutive_failures(self, integration_setup):
        """5 consecutive failures open the circuit."""
        worker, _ = integration_setup

        # Simulate 5 consecutive transient failures
        for _ in range(5):
            worker.circuit_breaker.record_failure()

        assert worker.circuit_breaker.state == CircuitState.OPEN
        assert worker.circuit_breaker.can_execute() is False

    @freeze_time("2026-01-01 12:00:00")
    def test_circuit_recovers_after_timeout(self, integration_setup, freezer):
        """Circuit transitions to HALF_OPEN after recovery timeout."""
        worker, _ = integration_setup

        # Open the circuit
        for _ in range(5):
            worker.circuit_breaker.record_failure()

        # Advance time past 60s recovery timeout
        freezer.move_to("2026-01-01 12:01:01")

        assert worker.circuit_breaker.state == CircuitState.HALF_OPEN
        assert worker.circuit_breaker.can_execute() is True
```

### Queue Persistence Test
```python
# Source: Derived from existing DLQ test patterns
class TestQueuePersistence:
    """Tests for queue persistence across restarts."""

    def test_retry_metadata_survives_restart(self, tmp_path):
        """Job retry metadata persists in queue."""
        from worker.processor import SyncWorker, TransientError
        import persistqueue

        # Create real queue (not mock) for persistence testing
        queue = persistqueue.SQLiteAckQueue(str(tmp_path / "queue"))

        worker = SyncWorker(
            queue=queue,
            dlq=Mock(),
            config=Mock(poll_interval=1.0),
        )

        # Prepare job with retry metadata
        job = {'scene_id': 123, 'data': {'path': '/test.mp4'}}
        updated_job = worker._prepare_for_retry(job, TransientError("test"))

        # Simulate requeue (what happens on retry)
        queue.put(updated_job)

        # Simulate restart - new queue instance
        queue2 = persistqueue.SQLiteAckQueue(str(tmp_path / "queue"))
        retrieved = queue2.get(timeout=1)

        # Retry metadata should be preserved
        assert retrieved['retry_count'] == 1
        assert 'next_retry_at' in retrieved
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| unittest.TestCase | pytest functions | ~2018 | Simpler, fixtures, better output |
| mock.patch decorators | pytest-mock fixture | ~2020 | Cleaner syntax, automatic cleanup |
| Manual time patching | freezegun/time-machine | ~2020 | Reliable, handles edge cases |
| setUp/tearDown | yield fixtures | pytest 3.0 | Better scoping, composition |

**Deprecated/outdated:**
- `python setup.py test`: Use `pytest` directly
- `pytest-runner`: Deprecated, use pip install + pytest
- `nose`: Maintenance mode, use pytest

## Open Questions

Things that couldn't be fully resolved:

1. **Real Plex/Stash for smoke tests?**
   - What we know: Integration tests use mocks for reliability
   - What's unclear: Should there be optional "real service" smoke tests?
   - Recommendation: Defer to Phase 4 or manual testing; keep integration tests fully mocked

2. **pytest-xdist for parallel tests?**
   - What we know: Parallel execution speeds up large test suites
   - What's unclear: Will SQLite queue tests conflict under parallel execution?
   - Recommendation: Test without parallelization first; add xdist later if needed

3. **Coverage threshold for integration tests?**
   - What we know: Unit tests have 80% threshold, integration tests overlap
   - What's unclear: Should integration tests have separate coverage requirements?
   - Recommendation: Keep combined coverage; integration tests improve path coverage

## Sources

### Primary (HIGH confidence)
- pytest official documentation - good practices, fixture scoping
- Existing PlexSync test files - conftest.py, test_circuit_breaker.py, test_retry_orchestration.py
- freezegun GitHub - time mocking patterns

### Secondary (MEDIUM confidence)
- [pytest Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) - Project structure
- [Mocking External APIs in Python](https://realpython.com/testing-third-party-apis-with-mocks/) - Mock patterns
- [pytest-timeout PyPI](https://pypi.org/project/pytest-timeout/) - Timeout configuration
- [freezegun GitHub](https://github.com/spulec/freezegun) - Time mocking API

### Tertiary (LOW confidence)
- WebSearch results for "pytest integration testing best practices 2026" - General patterns
- WebSearch results for "Python circuit breaker testing patterns" - Error handling approaches

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses existing dependencies plus well-established additions
- Architecture: HIGH - Patterns derived from existing codebase and official docs
- Pitfalls: HIGH - Many observed in existing tests or documented in official sources
- Code examples: HIGH - Adapted from existing test files in codebase

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (30 days - stable domain)
