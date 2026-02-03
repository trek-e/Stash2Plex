# Phase 1: Testing Infrastructure - Research

**Researched:** 2026-02-03
**Domain:** Python testing with pytest, mocking external APIs (Plex, Stash)
**Confidence:** HIGH

## Summary

This phase establishes pytest-based testing infrastructure for PlexSync, a Python plugin that syncs metadata from Stash to Plex. The project already has basic tests using both unittest and pytest styles, but lacks formal pytest configuration, fixtures for mocking PlexServer/StashInterface, proper test directory structure, and coverage reporting.

The standard approach for Python testing in 2026 uses pytest 9.x with pytest-mock for mocking, pytest-cov for coverage, and a test directory structure that mirrors the source layout. For this project, the key challenge is mocking external APIs (plexapi and stashapi) that make network calls without requiring actual servers.

**Primary recommendation:** Configure pytest with pytest.ini, create reusable fixtures in conftest.py for mocking PlexServer and StashInterface, mirror the source directory structure in tests/, and enable coverage reporting with pytest-cov targeting 80%+ coverage.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=9.0.0 | Test framework | De facto Python testing standard; supports fixtures, parametrization, plugins |
| pytest-mock | >=3.14.0 | Mocking utilities | Provides `mocker` fixture, integrates cleanly with pytest |
| pytest-cov | >=6.0.0 | Coverage reporting | Wrapper around coverage.py with pytest integration |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| coverage | >=7.6.0 | Coverage measurement | Underlying engine for pytest-cov; configure via .coveragerc |
| pytest-asyncio | >=0.24.0 | Async test support | If async functions need testing (not currently needed) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pytest-mock | unittest.mock directly | pytest-mock adds `mocker` fixture with auto-cleanup; cleaner syntax |
| pytest-cov | coverage run pytest | pytest-cov handles multiprocess, auto-combines data, better reporting |

**Installation:**
```bash
pip install pytest>=9.0.0 pytest-mock>=3.14.0 pytest-cov>=6.0.0
```

Or add to requirements.txt / requirements-dev.txt:
```
pytest>=9.0.0
pytest-mock>=3.14.0
pytest-cov>=6.0.0
```

## Architecture Patterns

### Recommended Project Structure
```
PlexSync/
├── plex/                    # Plex API client
├── sync_queue/              # Queue management
├── worker/                  # Background processor
├── validation/              # Pydantic models
├── hooks/                   # Event handlers
├── tests/
│   ├── conftest.py          # Shared fixtures (mock Plex, mock Stash, mock queue)
│   ├── plex/
│   │   ├── __init__.py
│   │   ├── test_client.py   # Tests for plex/client.py
│   │   ├── test_matcher.py  # Tests for plex/matcher.py
│   │   └── test_exceptions.py
│   ├── sync_queue/
│   │   ├── __init__.py
│   │   ├── test_manager.py
│   │   ├── test_operations.py
│   │   └── test_dlq.py
│   ├── worker/
│   │   ├── __init__.py
│   │   ├── test_processor.py
│   │   ├── test_backoff.py
│   │   └── test_circuit_breaker.py
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── test_metadata.py
│   │   └── test_config.py
│   └── hooks/
│       ├── __init__.py
│       └── test_handlers.py
├── pytest.ini               # pytest configuration
└── .coveragerc              # coverage configuration (optional)
```

### Pattern 1: Fixture-Based Mock Injection
**What:** Define mock objects as pytest fixtures in conftest.py, inject into tests via function arguments
**When to use:** All tests that need mocked external dependencies
**Example:**
```python
# tests/conftest.py
# Source: pytest official fixtures documentation
import pytest
from unittest.mock import Mock, MagicMock

@pytest.fixture
def mock_plex_server():
    """Mock PlexServer with common attributes."""
    server = MagicMock()
    server.friendlyName = "Test Plex Server"
    server.library.sections.return_value = []
    return server

@pytest.fixture
def mock_plex_library():
    """Mock Plex library section."""
    section = MagicMock()
    section.search.return_value = []
    section.title = "Test Library"
    return section

@pytest.fixture
def mock_plex_item():
    """Mock Plex video item for metadata updates."""
    item = MagicMock()
    item.title = "Test Video"
    item.studio = None
    item.summary = None
    item.actors = []
    item.genres = []
    item.collections = []
    item.media = [MagicMock()]
    item.media[0].parts = [MagicMock()]
    item.media[0].parts[0].file = "/test/path/video.mp4"
    return item

@pytest.fixture
def mock_config():
    """Mock PlexSyncConfig for worker tests."""
    config = Mock()
    config.plex_url = "http://localhost:32400"
    config.plex_token = "test_token_12345"
    config.plex_connect_timeout = 5.0
    config.plex_read_timeout = 30.0
    config.plex_library = "Test Library"
    config.poll_interval = 1.0
    config.strict_matching = True
    config.preserve_plex_edits = False
    return config
```

### Pattern 2: Patching Module-Level Imports
**What:** Use mocker.patch() to replace external library imports at the module where they're used
**When to use:** When code imports external libraries (plexapi, persistqueue) that would fail without servers
**Example:**
```python
# tests/plex/test_client.py
# Source: pytest-mock documentation
def test_plex_client_connects(mocker, mock_plex_server):
    """Test PlexClient connects to Plex server."""
    # Patch where PlexServer is USED, not where it's defined
    mock_server_class = mocker.patch('plex.client.PlexServer')
    mock_server_class.return_value = mock_plex_server

    from plex.client import PlexClient

    client = PlexClient(
        url="http://test:32400",
        token="test_token",
    )

    # Access server property triggers connection
    server = client.server

    mock_server_class.assert_called_once()
    assert server.friendlyName == "Test Plex Server"
```

### Pattern 3: Parametrized Tests for Edge Cases
**What:** Use @pytest.mark.parametrize to test multiple inputs with single test function
**When to use:** Testing validation, error handling, multiple scenarios
**Example:**
```python
# tests/validation/test_metadata.py
# Source: pytest parametrize documentation
import pytest
from pydantic import ValidationError

@pytest.mark.parametrize("scene_id,expected_valid", [
    (1, True),       # Valid positive int
    (100, True),     # Valid larger int
    (0, False),      # Invalid: must be > 0
    (-1, False),     # Invalid: negative
])
def test_scene_id_validation(scene_id, expected_valid):
    """Test SyncMetadata scene_id validation."""
    from validation.metadata import SyncMetadata

    if expected_valid:
        model = SyncMetadata(scene_id=scene_id, title="Test")
        assert model.scene_id == scene_id
    else:
        with pytest.raises(ValidationError):
            SyncMetadata(scene_id=scene_id, title="Test")
```

### Anti-Patterns to Avoid
- **Patching in wrong location:** Patch at the module that imports the object, not where it's defined. `mocker.patch('plex.client.PlexServer')` not `mocker.patch('plexapi.server.PlexServer')`
- **Tests that hit real servers:** Never let tests make actual network calls. Always mock plexapi and stashapi.
- **Enormous conftest.py:** Split into multiple fixture files if conftest.py exceeds ~200 lines. Use `pytest_plugins` to load them.
- **Fixture scope mismatch:** Use function scope (default) for mutable fixtures. Session/module scope only for immutable or expensive-to-create fixtures.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Mock objects | Custom stub classes | unittest.mock.Mock/MagicMock | Handles attribute access, call tracking, assertions |
| Test isolation | Manual cleanup code | pytest fixtures with yield | Automatic teardown, proper scope handling |
| Coverage reporting | Manual line counting | pytest-cov | Branch coverage, HTML reports, CI integration |
| Async mock waiting | sleep() calls in tests | pytest-mock + MagicMock | Mocks are synchronous, no waiting needed |
| Fixture sharing | Copy-paste fixtures | conftest.py | Automatic discovery, DRY, maintainable |

**Key insight:** pytest and its ecosystem have solved all common testing problems. The only custom code needed is project-specific fixtures for mocking PlexServer and StashInterface.

## Common Pitfalls

### Pitfall 1: Import-Time Side Effects
**What goes wrong:** Tests fail because importing a module triggers plexapi/requests imports which require network
**Why it happens:** PlexSync uses lazy imports but some modules still have import-time dependencies
**How to avoid:**
1. Use `TYPE_CHECKING` guards for type hints
2. Patch modules BEFORE importing code under test
3. Use `sys.modules` patching for stubborn imports
**Warning signs:** `ImportError` or `ModuleNotFoundError` during test collection

### Pitfall 2: Mocking at Wrong Location
**What goes wrong:** Mock not applied, real code executes, tests fail or make network calls
**Why it happens:** Patching where object is defined instead of where it's used
**How to avoid:** Always patch at the import location: `mocker.patch('mymodule.PlexServer')` not `mocker.patch('plexapi.server.PlexServer')`
**Warning signs:** Mock's assert_called methods fail unexpectedly

### Pitfall 3: Shared Mutable State Between Tests
**What goes wrong:** Test A modifies mock, Test B sees modified state, tests pass/fail depending on order
**Why it happens:** Using module-scope fixtures for mutable objects or forgetting to reset mocks
**How to avoid:** Use function-scope fixtures (default). Call `mock.reset_mock()` in setup if reusing.
**Warning signs:** Tests pass individually but fail when run together

### Pitfall 4: Missing __init__.py in Test Directories
**What goes wrong:** pytest can't discover tests in subdirectories
**Why it happens:** Forgetting to create `__init__.py` when adding test subdirectories
**How to avoid:** Always create `__init__.py` in every test directory/subdirectory
**Warning signs:** `pytest --collect-only` shows 0 tests from a directory

### Pitfall 5: Pydantic Model Mock Complexity
**What goes wrong:** Trying to mock Pydantic models instead of using real models with test data
**Why it happens:** Treating Pydantic like regular classes; Pydantic has validation magic
**How to avoid:** Create real Pydantic model instances with test data. Only mock external I/O.
**Warning signs:** Mocked model doesn't validate like real model

## Code Examples

Verified patterns from official sources:

### pytest.ini Configuration
```ini
# pytest.ini
# Source: pytest documentation
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --tb=short
    --strict-markers
    --cov=plex
    --cov=sync_queue
    --cov=worker
    --cov=validation
    --cov=hooks
    --cov-report=term-missing
    --cov-report=html:coverage_html
    --cov-fail-under=80

markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests
```

### .coveragerc Configuration (Optional)
```ini
# .coveragerc
# Source: pytest-cov documentation
[run]
branch = True
source =
    plex
    sync_queue
    worker
    validation
    hooks
omit =
    */tests/*
    */__pycache__/*
    */.venv/*

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise NotImplementedError
    if TYPE_CHECKING:
    if __name__ == .__main__.:

[html]
directory = coverage_html
```

### Complete conftest.py Example
```python
# tests/conftest.py
# Source: pytest fixtures documentation + project-specific patterns
"""
Shared pytest fixtures for PlexSync tests.

Provides mock fixtures for:
- PlexServer and related plexapi objects
- SQLiteAckQueue (persist-queue)
- PlexSyncConfig
- Common test data
"""
import pytest
import sys
from unittest.mock import Mock, MagicMock, patch


# ============================================================================
# Plex API Mocks
# ============================================================================

@pytest.fixture
def mock_plex_server():
    """
    Mock plexapi.server.PlexServer.

    Returns a MagicMock configured with common server attributes
    and methods used by PlexClient.
    """
    server = MagicMock()
    server.friendlyName = "Test Plex Server"
    server.version = "1.32.0.0"
    server.library.sections.return_value = []
    return server


@pytest.fixture
def mock_plex_section():
    """
    Mock plexapi library section.

    Provides a mock library section with search() that returns empty by default.
    Configure section.search.return_value in individual tests.
    """
    section = MagicMock()
    section.title = "Test Library"
    section.type = "movie"
    section.search.return_value = []
    return section


@pytest.fixture
def mock_plex_item():
    """
    Mock Plex video item for metadata operations.

    Pre-configured with common attributes that _update_metadata accesses.
    """
    item = MagicMock()
    item.title = "Test Video"
    item.studio = None
    item.summary = None
    item.tagline = None
    item.originallyAvailableAt = None
    item.actors = []
    item.genres = []
    item.collections = []

    # Media/Parts structure for path matching
    part = MagicMock()
    part.file = "/test/media/video.mp4"
    media = MagicMock()
    media.parts = [part]
    item.media = [media]
    item.key = "/library/metadata/12345"

    return item


@pytest.fixture
def mock_plexapi_module(mocker):
    """
    Mock the entire plexapi module to prevent import-time failures.

    Use this fixture when testing code that imports from plexapi directly.
    """
    mock_exceptions = MagicMock()
    mock_exceptions.Unauthorized = type('Unauthorized', (Exception,), {})
    mock_exceptions.NotFound = type('NotFound', (Exception,), {})
    mock_exceptions.BadRequest = type('BadRequest', (Exception,), {})

    mock_plexapi = MagicMock()
    mock_plexapi.exceptions = mock_exceptions
    mock_plexapi.server.PlexServer = MagicMock()

    mocker.patch.dict('sys.modules', {
        'plexapi': mock_plexapi,
        'plexapi.server': mock_plexapi.server,
        'plexapi.exceptions': mock_exceptions,
    })

    return mock_plexapi


# ============================================================================
# Configuration Mocks
# ============================================================================

@pytest.fixture
def mock_config():
    """
    Mock PlexSyncConfig with sensible test defaults.

    All values are valid and typical; override in individual tests as needed.
    """
    config = Mock()
    config.plex_url = "http://localhost:32400"
    config.plex_token = "test_token_12345"
    config.plex_connect_timeout = 5.0
    config.plex_read_timeout = 30.0
    config.plex_library = "Test Library"
    config.poll_interval = 1.0
    config.max_retries = 5
    config.strict_matching = True
    config.preserve_plex_edits = False
    config.enabled = True
    config.strict_mode = False
    config.dlq_retention_days = 30
    config.stash_url = None
    config.stash_api_key = None
    config.stash_session_cookie = None
    return config


@pytest.fixture
def valid_config_dict():
    """
    Valid configuration dictionary for PlexSyncConfig instantiation.
    """
    return {
        "plex_url": "http://localhost:32400",
        "plex_token": "test_token_12345678",
        "enabled": True,
        "max_retries": 5,
        "poll_interval": 1.0,
    }


# ============================================================================
# Queue Mocks
# ============================================================================

@pytest.fixture
def mock_queue():
    """
    Mock persist-queue SQLiteAckQueue.

    Provides mock for queue operations without SQLite dependency.
    """
    queue = MagicMock()
    queue.put = MagicMock()
    queue.get = MagicMock(return_value=None)
    queue.ack = MagicMock()
    queue.nack = MagicMock()
    queue.clear_acked_data = MagicMock()
    queue.size = 0
    return queue


@pytest.fixture
def mock_dlq():
    """
    Mock DeadLetterQueue for worker tests.
    """
    dlq = MagicMock()
    dlq.add = MagicMock()
    dlq.get_count.return_value = 0
    dlq.get_recent.return_value = []
    dlq.delete_older_than = MagicMock()
    return dlq


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_job():
    """
    Sample sync job dictionary.
    """
    return {
        'scene_id': '12345',
        'update_type': 'metadata',
        'data': {
            'path': '/media/videos/test.mp4',
            'title': 'Test Scene',
            'studio': 'Test Studio',
            'details': 'Test description',
        },
        'enqueued_at': 1700000000.0,
        'job_key': 'scene_12345',
    }


@pytest.fixture
def sample_metadata_dict():
    """
    Valid metadata dictionary for SyncMetadata model.
    """
    return {
        'scene_id': 1,
        'title': 'Test Scene Title',
        'details': 'This is a test scene description.',
        'studio': 'Test Studio',
        'date': '2024-01-15',
        'performers': ['Performer One', 'Performer Two'],
        'tags': ['tag1', 'tag2'],
    }
```

### Example Test Using Fixtures
```python
# tests/worker/test_processor.py
"""Tests for SyncWorker using mock fixtures."""
import pytest
from unittest.mock import Mock, patch


class TestSyncWorkerInit:
    """Test SyncWorker initialization."""

    def test_worker_initializes_with_config(self, mock_queue, mock_dlq, mock_config):
        """Worker accepts queue, dlq, and config parameters."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
        )

        assert worker.queue is mock_queue
        assert worker.dlq is mock_dlq
        assert worker.config is mock_config
        assert worker._plex_client is None  # Lazy init

    def test_worker_has_circuit_breaker(self, mock_queue, mock_dlq, mock_config):
        """Worker creates circuit breaker on init."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitBreaker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
        )

        assert hasattr(worker, 'circuit_breaker')
        assert isinstance(worker.circuit_breaker, CircuitBreaker)


class TestProcessJob:
    """Test SyncWorker._process_job method."""

    def test_missing_path_raises_permanent_error(
        self, mock_queue, mock_dlq, mock_config
    ):
        """Job without file path raises PermanentError."""
        from worker.processor import SyncWorker, PermanentError

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
        )

        job = {
            'scene_id': '123',
            'update_type': 'metadata',
            'data': {},  # Missing 'path'
        }

        with pytest.raises(PermanentError, match="missing file path"):
            worker._process_job(job)

    def test_updates_plex_item_metadata(
        self, mocker, mock_queue, mock_dlq, mock_config, mock_plex_item
    ):
        """Successful job updates Plex item metadata."""
        from worker.processor import SyncWorker

        # Setup mock client that returns our mock item
        mock_client = Mock()
        mock_section = Mock()
        mock_section.search.return_value = [mock_plex_item]
        mock_client.server.library.section.return_value = mock_section

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
        )
        worker._get_plex_client = Mock(return_value=mock_client)

        job = {
            'scene_id': '123',
            'update_type': 'metadata',
            'data': {
                'path': '/test/media/video.mp4',
                'title': 'Updated Title',
                'studio': 'New Studio',
            },
        }

        # Mock find_plex_items_with_confidence to return our item
        mocker.patch(
            'worker.processor.find_plex_items_with_confidence',
            return_value=(Mock(), mock_plex_item, [mock_plex_item])
        )
        mocker.patch('worker.processor.save_sync_timestamp')

        worker._process_job(job)

        # Verify edit was called
        mock_plex_item.edit.assert_called_once()
        mock_plex_item.reload.assert_called()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| unittest.TestCase | pytest functions | 2015+ | Cleaner syntax, fixtures, parametrize |
| nose | pytest | 2016 (nose EOL) | pytest became dominant |
| setup.py test | pytest directly | 2020 | pytest-runner deprecated |
| coverage run | pytest-cov | 2015+ | Better integration, multiprocess support |
| pytest <8.0 | pytest 9.x | Dec 2025 | Python 3.10+ required, improved typing |

**Deprecated/outdated:**
- `nose`: EOL since 2016, migrate to pytest
- `pytest-runner` / `setup.py test`: Deprecated, use `pytest` directly
- `pytest <8.0`: Dropped Python 3.8/3.9 support
- `--import-mode=prepend` (default): New projects should use `--import-mode=importlib`

## Open Questions

Things that couldn't be fully resolved:

1. **Async test requirements**
   - What we know: Current codebase uses threading, not async/await
   - What's unclear: Whether future features will need async testing
   - Recommendation: Don't install pytest-asyncio yet; add when needed

2. **Coverage threshold**
   - What we know: 80% is common industry standard
   - What's unclear: Appropriate threshold given existing test coverage
   - Recommendation: Start at 80%, adjust based on initial coverage report

3. **Integration test separation**
   - What we know: Current tests are all unit tests with mocks
   - What's unclear: Whether real Plex/Stash integration tests are needed
   - Recommendation: Defer integration tests; focus on comprehensive unit tests first

## Sources

### Primary (HIGH confidence)
- [pytest fixtures documentation](https://docs.pytest.org/en/stable/how-to/fixtures.html) - fixture scopes, conftest patterns
- [pytest-cov configuration](https://pytest-cov.readthedocs.io/en/latest/config.html) - coverage options
- [pytest-mock usage](https://pytest-mock.readthedocs.io/en/latest/usage.html) - mocker fixture patterns
- [PyPI pytest 9.0.2](https://pypi.org/project/pytest/) - current version, requirements

### Secondary (MEDIUM confidence)
- [pytest Good Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) - directory structure, import modes
- [pytest-with-eric conftest patterns](https://pytest-with-eric.com/pytest-best-practices/pytest-conftest/) - practical examples
- [pytest 8.0 release notes](https://docs.pytest.org/en/stable/announce/release-8.0.0.html) - breaking changes

### Tertiary (LOW confidence)
- WebSearch results on plexapi mocking - community patterns, not officially documented

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official documentation for pytest, pytest-mock, pytest-cov
- Architecture: HIGH - pytest documentation on good practices + project analysis
- Pitfalls: HIGH - Based on documented pytest patterns and existing project code

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (pytest ecosystem is stable; 30 days validity)
