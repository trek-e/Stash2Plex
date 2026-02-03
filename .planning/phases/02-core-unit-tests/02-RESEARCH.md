# Phase 2: Core Unit Tests - Research

**Researched:** 2026-02-03
**Domain:** Python unit testing with pytest for sync_queue, validation, plex, and hooks modules
**Confidence:** HIGH

## Summary

This phase focuses on achieving >80% unit test coverage for PlexSync's core modules: `sync_queue/` (QueueManager, operations, DLQ), `validation/` (metadata and config validation via Pydantic v2), `plex/` (matching logic, API client), and `hooks/` (handler logic). The project already has a testing foundation from Phase 1: pytest.ini with 80% coverage threshold, requirements-dev.txt with pytest>=9.0.0/pytest-mock>=3.14.0/pytest-cov>=6.0.0, and 11 fixtures in conftest.py.

The standard approach uses pytest with parametrize for comprehensive edge case coverage, pytest-mock's `mocker` fixture for mocking external dependencies (Plex API, file system, time), and pytest's built-in `tmp_path` fixture for SQLite database testing (QueueManager, DLQ). Pydantic v2 models should be tested by exercising `model_validate()` with valid/invalid inputs rather than mocking validation internals.

**Primary recommendation:** Use `@pytest.mark.parametrize` extensively for testing validation edge cases, mock external I/O at module boundaries using `mocker.patch`, and use `tmp_path` for database fixtures to ensure clean isolation.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=9.0.0 | Test framework | Industry standard, superior fixture system, parametrize |
| pytest-mock | >=3.14.0 | Mocking integration | Clean mocker fixture, auto-cleanup of patches |
| pytest-cov | >=6.0.0 | Coverage reporting | Integrates with pytest, fail-under enforcement |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock | stdlib | MagicMock, patch | Underlying mock library, use via mocker fixture |
| pydantic | (project dep) | Validation models | Test model validation behavior |
| tmp_path | pytest builtin | Temp directories | SQLite DB fixtures (QueueManager, DLQ) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pytest-mock | unittest.mock directly | pytest-mock has cleaner fixture integration, auto-cleanup |
| tmp_path | tempfile.TemporaryDirectory | tmp_path integrates with pytest lifecycle, auto-cleanup |
| freezegun | mocker.patch time.time | Simpler for this project, no extra dependency |

**Installation:**
Already in requirements-dev.txt:
```bash
pip install -r requirements-dev.txt
```

## Architecture Patterns

### Recommended Test Directory Structure
```
tests/
├── conftest.py           # Shared fixtures (already exists)
├── sync_queue/
│   ├── __init__.py
│   ├── test_manager.py   # QueueManager tests
│   ├── test_operations.py # enqueue, dequeue, ack tests
│   └── test_dlq.py       # DeadLetterQueue tests
├── validation/
│   ├── __init__.py
│   ├── test_metadata.py  # SyncMetadata validation tests
│   └── test_config.py    # PlexSyncConfig tests
├── plex/
│   ├── __init__.py
│   ├── test_matcher.py   # find_plex_item_by_path tests
│   ├── test_client.py    # PlexClient tests (mocked)
│   └── test_exceptions.py # Exception translation tests
└── hooks/
    ├── __init__.py
    └── test_handlers.py  # on_scene_update handler tests
```

### Pattern 1: Parametrized Validation Testing
**What:** Use `@pytest.mark.parametrize` to test multiple validation scenarios in single test functions
**When to use:** Testing Pydantic models (SyncMetadata, PlexSyncConfig) with valid/invalid inputs
**Example:**
```python
# Source: pytest documentation - parametrization
import pytest
from validation.metadata import SyncMetadata, validate_metadata
from pydantic import ValidationError

@pytest.mark.parametrize("scene_id,title,expected_valid", [
    (1, "Valid Title", True),
    (0, "Valid Title", False),  # scene_id must be positive
    (-1, "Valid Title", False),
    (1, "", False),  # title cannot be empty
    (1, None, False),
    (1, "A" * 255, True),  # max length
    (1, "A" * 256, False),  # exceeds max length
])
def test_sync_metadata_validation(scene_id, title, expected_valid):
    data = {"scene_id": scene_id, "title": title}
    result, error = validate_metadata(data)
    if expected_valid:
        assert result is not None
        assert error is None
    else:
        assert result is None
        assert error is not None
```

### Pattern 2: Temporary Database Fixtures
**What:** Use pytest's `tmp_path` fixture for SQLite-based components
**When to use:** Testing QueueManager, DeadLetterQueue, sync_queue/operations
**Example:**
```python
# Source: pytest docs - tmp_path fixture
import pytest
from sync_queue.manager import QueueManager
from sync_queue.dlq import DeadLetterQueue

@pytest.fixture
def queue_manager(tmp_path):
    """Create QueueManager with temporary database."""
    manager = QueueManager(data_dir=str(tmp_path))
    yield manager
    manager.shutdown()

@pytest.fixture
def dlq(tmp_path):
    """Create DeadLetterQueue with temporary database."""
    return DeadLetterQueue(str(tmp_path))
```

### Pattern 3: Mocker for External Dependencies
**What:** Use pytest-mock's `mocker` fixture to patch external APIs
**When to use:** Testing PlexClient, hooks/handlers without real API calls
**Example:**
```python
# Source: pytest-mock documentation
def test_on_scene_update_enqueues_job(mocker, mock_queue):
    # Patch external dependencies
    mocker.patch('hooks.handlers.is_scan_running', return_value=False)
    mocker.patch('hooks.handlers.validate_metadata', return_value=(mock_metadata, None))
    mocker.patch.object(mock_queue, 'put')

    # Mock Stash interface
    mock_stash = mocker.MagicMock()
    mock_stash.call_GQL.return_value = {"findScene": {"files": [{"path": "/test.mp4"}], "title": "Test"}}

    result = on_scene_update(
        scene_id=123,
        update_data={"title": "New Title"},
        queue=mock_queue,
        stash=mock_stash
    )

    assert result is True
    mock_queue.put.assert_called_once()
```

### Pattern 4: Time Mocking for Deterministic Tests
**What:** Patch `time.time()` for tests that depend on timestamps
**When to use:** Testing backoff calculations, sync timestamps, job timing
**Example:**
```python
# Source: Python unittest.mock docs
def test_sync_timestamp_filtering(mocker, sample_job):
    fixed_time = 1700000000.0
    mocker.patch('time.time', return_value=fixed_time)

    # Job with older timestamp should be filtered
    sync_timestamps = {123: fixed_time + 1}  # Already synced in future
    result = on_scene_update(
        scene_id=123,
        update_data={"title": "Test", "updated_at": fixed_time},
        queue=mock_queue,
        sync_timestamps=sync_timestamps,
        stash=mock_stash
    )
    assert result is False  # Filtered out
```

### Anti-Patterns to Avoid
- **Mocking Pydantic internals:** Test validation by instantiating models, not by mocking field_validator
- **Global patches without cleanup:** Always use mocker fixture (auto-cleanup) instead of manual patch()
- **Testing implementation details:** Test behavior (valid/invalid inputs produce correct outputs), not internal method calls
- **Shared mutable state:** Each test should get fresh fixtures; use function scope for queue fixtures
- **Patching in wrong location:** Patch where the name is looked up, not where it's defined

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Temporary files | Manual tempfile cleanup | pytest `tmp_path` fixture | Auto-cleanup, unique per test |
| Mock objects | Custom fake classes | MagicMock from pytest-mock | Configurable, spec support, assertions |
| Parametrized tests | Multiple test functions | `@pytest.mark.parametrize` | Less code, clearer test matrix |
| Coverage tracking | Manual instrumentation | pytest-cov with --cov | Accurate, integrates with pytest |
| Time freezing | Global time manipulation | mocker.patch('time.time') | Scoped to test, auto-restored |

**Key insight:** pytest's fixture system and pytest-mock handle test isolation and cleanup automatically. Hand-rolling these leads to subtle test pollution and flaky tests.

## Common Pitfalls

### Pitfall 1: Patching in Wrong Location
**What goes wrong:** Mock doesn't take effect; real function gets called
**Why it happens:** Python imports create name bindings; must patch where name is looked up
**How to avoid:** Patch `'hooks.handlers.validate_metadata'` not `'validation.metadata.validate_metadata'` when testing hooks
**Warning signs:** Tests pass but coverage shows mocked code was executed

### Pitfall 2: Queue Import Shadowing
**What goes wrong:** `import queue` fails because project has `queue/` directory
**Why it happens:** PlexSync has `sync_queue/` but older code may have `queue/` references; also affects `plexapi` which uses stdlib queue via urllib3
**How to avoid:** Use TYPE_CHECKING guards for plexapi imports; mock at module boundaries
**Warning signs:** ImportError for stdlib queue module

### Pitfall 3: Shared Database State Between Tests
**What goes wrong:** Tests pass individually but fail when run together
**Why it happens:** SQLite database persists between tests without proper isolation
**How to avoid:** Use `tmp_path` fixture (function scope by default); create fresh QueueManager/DLQ per test
**Warning signs:** Flaky tests, order-dependent failures

### Pitfall 4: Testing Pydantic Validation Incorrectly
**What goes wrong:** Tests mock Pydantic internals instead of testing validation behavior
**Why it happens:** Treating validation like external API instead of testing actual behavior
**How to avoid:** Instantiate models directly, catch ValidationError, use validate_metadata() helper
**Warning signs:** Tests pass but validation bugs slip through

### Pitfall 5: Not Testing Error Paths
**What goes wrong:** Coverage looks good but error handling is untested
**Why it happens:** Focus on happy path; exceptions are harder to trigger
**How to avoid:** Parametrize with invalid inputs; use mocker to raise exceptions from dependencies
**Warning signs:** Coverage of except blocks is low

### Pitfall 6: Time-Dependent Test Flakiness
**What goes wrong:** Tests fail randomly due to timing issues
**Why it happens:** Using real `time.time()` creates race conditions
**How to avoid:** Mock time.time() for any test involving timestamps, backoff, or sync timing
**Warning signs:** Tests fail occasionally, especially on CI

## Code Examples

Verified patterns from official sources and existing codebase:

### Testing QueueManager with tmp_path
```python
# Pattern: Isolated database per test
import pytest
from sync_queue.manager import QueueManager

@pytest.fixture
def queue_manager(tmp_path):
    """Create QueueManager with isolated database."""
    manager = QueueManager(data_dir=str(tmp_path))
    yield manager
    manager.shutdown()

def test_queue_manager_creates_directory(tmp_path):
    manager = QueueManager(data_dir=str(tmp_path))
    assert (tmp_path / 'queue').exists()
    manager.shutdown()

def test_queue_manager_get_queue_returns_queue(queue_manager):
    queue = queue_manager.get_queue()
    assert queue is not None
    assert hasattr(queue, 'put')
    assert hasattr(queue, 'get')
```

### Testing DeadLetterQueue
```python
# Pattern: SQLite database testing with assertions
import pytest
from sync_queue.dlq import DeadLetterQueue

@pytest.fixture
def dlq(tmp_path):
    return DeadLetterQueue(str(tmp_path))

def test_dlq_add_and_retrieve(dlq):
    job = {"pqid": 1, "scene_id": 123, "data": {"title": "Test"}}
    error = ValueError("Test error")

    dlq.add(job, error, retry_count=5)

    assert dlq.get_count() == 1
    recent = dlq.get_recent(limit=1)
    assert len(recent) == 1
    assert recent[0]["scene_id"] == 123
    assert recent[0]["error_type"] == "ValueError"

def test_dlq_get_by_id_unpickles_job(dlq):
    job = {"pqid": 1, "scene_id": 456, "data": {"title": "Pickled"}}
    dlq.add(job, Exception("Error"), retry_count=3)

    recent = dlq.get_recent(limit=1)
    full_job = dlq.get_by_id(recent[0]["id"])

    assert full_job["scene_id"] == 456
    assert full_job["data"]["title"] == "Pickled"
```

### Testing Pydantic Validation Models
```python
# Pattern: Parametrized validation testing
import pytest
from validation.metadata import SyncMetadata, validate_metadata
from pydantic import ValidationError

class TestSyncMetadata:
    """Tests for SyncMetadata Pydantic model."""

    def test_valid_minimal_metadata(self):
        """Minimum required fields create valid model."""
        metadata = SyncMetadata(scene_id=1, title="Test Title")
        assert metadata.scene_id == 1
        assert metadata.title == "Test Title"

    @pytest.mark.parametrize("invalid_scene_id", [0, -1, None])
    def test_invalid_scene_id_rejected(self, invalid_scene_id):
        """scene_id must be positive integer."""
        with pytest.raises(ValidationError):
            SyncMetadata(scene_id=invalid_scene_id, title="Test")

    @pytest.mark.parametrize("invalid_title", ["", None, " " * 10])
    def test_invalid_title_rejected(self, invalid_title):
        """title must be non-empty after sanitization."""
        result, error = validate_metadata({"scene_id": 1, "title": invalid_title})
        assert result is None
        assert error is not None

    def test_sanitizes_control_characters(self):
        """Control characters removed from title."""
        metadata = SyncMetadata(scene_id=1, title="Test\x00Title\x1f")
        assert "\x00" not in metadata.title
        assert "\x1f" not in metadata.title

    @pytest.mark.parametrize("rating,valid", [
        (0, True), (50, True), (100, True),
        (-1, False), (101, False),
    ])
    def test_rating100_range(self, rating, valid):
        """rating100 must be 0-100."""
        if valid:
            m = SyncMetadata(scene_id=1, title="Test", rating100=rating)
            assert m.rating100 == rating
        else:
            with pytest.raises(ValidationError):
                SyncMetadata(scene_id=1, title="Test", rating100=rating)
```

### Testing PlexSyncConfig
```python
# Pattern: Config validation with error messages
import pytest
from validation.config import PlexSyncConfig, validate_config

class TestPlexSyncConfig:
    """Tests for PlexSyncConfig validation."""

    def test_valid_config_with_required_fields(self, valid_config_dict):
        """Config with required fields is valid."""
        config = PlexSyncConfig(**valid_config_dict)
        assert config.plex_url == valid_config_dict["plex_url"]

    def test_plex_url_required(self):
        """plex_url is required."""
        config, error = validate_config({"plex_token": "valid-token-here"})
        assert config is None
        assert "plex_url" in error

    def test_plex_url_must_be_http(self):
        """plex_url must start with http:// or https://."""
        config, error = validate_config({
            "plex_url": "ftp://invalid",
            "plex_token": "valid-token-here"
        })
        assert config is None
        assert "http" in error.lower()

    def test_plex_url_trailing_slash_normalized(self):
        """Trailing slash removed from plex_url."""
        config = PlexSyncConfig(
            plex_url="http://localhost:32400/",
            plex_token="valid-token-here"
        )
        assert not config.plex_url.endswith("/")

    @pytest.mark.parametrize("retries,valid", [
        (1, True), (5, True), (20, True),
        (0, False), (21, False),
    ])
    def test_max_retries_range(self, retries, valid):
        """max_retries must be 1-20."""
        config_dict = {
            "plex_url": "http://localhost:32400",
            "plex_token": "valid-token-here",
            "max_retries": retries
        }
        config, error = validate_config(config_dict)
        assert (config is not None) == valid
```

### Testing Matcher with Mocked Plex Library
```python
# Pattern: Mocking Plex library section
import pytest
from unittest.mock import MagicMock
from plex.matcher import find_plex_item_by_path, find_plex_items_with_confidence, MatchConfidence
from plex.exceptions import PlexNotFound

@pytest.fixture
def mock_plex_item():
    """Mock Plex video item with file path."""
    item = MagicMock()
    item.title = "Test Video"
    item.key = "/library/metadata/123"

    part = MagicMock()
    part.file = "/media/videos/test.mp4"
    media = MagicMock()
    media.parts = [part]
    item.media = [media]

    return item

def test_find_by_path_single_match(mock_plex_item):
    """Single match returns HIGH confidence."""
    library = MagicMock()
    library.search.return_value = [mock_plex_item]
    library.all.return_value = [mock_plex_item]

    confidence, item, candidates = find_plex_items_with_confidence(
        library, "/media/videos/test.mp4"
    )

    assert confidence == MatchConfidence.HIGH
    assert item == mock_plex_item
    assert len(candidates) == 1

def test_find_by_path_no_match_raises(mock_plex_item):
    """No matches raises PlexNotFound."""
    library = MagicMock()
    library.search.return_value = []
    library.all.return_value = []

    with pytest.raises(PlexNotFound):
        find_plex_items_with_confidence(library, "/nonexistent/file.mp4")

def test_find_by_path_multiple_matches_low_confidence():
    """Multiple matches return LOW confidence."""
    item1 = MagicMock()
    item1.key = "/library/metadata/1"
    part1 = MagicMock()
    part1.file = "/media/videos/duplicate.mp4"
    item1.media = [MagicMock(parts=[part1])]

    item2 = MagicMock()
    item2.key = "/library/metadata/2"
    part2 = MagicMock()
    part2.file = "/other/videos/duplicate.mp4"
    item2.media = [MagicMock(parts=[part2])]

    library = MagicMock()
    library.search.return_value = [item1, item2]
    library.all.return_value = [item1, item2]

    confidence, item, candidates = find_plex_items_with_confidence(
        library, "duplicate.mp4"
    )

    assert confidence == MatchConfidence.LOW
    assert item is None
    assert len(candidates) == 2
```

### Testing Hook Handlers with Mocked Dependencies
```python
# Pattern: Mock all external dependencies for handler testing
import pytest
from unittest.mock import MagicMock

def test_on_scene_update_filters_non_sync_events(mocker):
    """Non-metadata updates are filtered."""
    from hooks.handlers import on_scene_update

    mock_queue = MagicMock()

    result = on_scene_update(
        scene_id=123,
        update_data={"play_count": 5},  # Not a sync field
        queue=mock_queue,
        stash=None
    )

    assert result is False
    mock_queue.put.assert_not_called()

def test_on_scene_update_skips_during_scan(mocker):
    """Updates skipped when scan job is running."""
    from hooks.handlers import on_scene_update

    mocker.patch('hooks.handlers.is_scan_running', return_value=True)
    mock_queue = MagicMock()

    result = on_scene_update(
        scene_id=123,
        update_data={"title": "Test"},
        queue=mock_queue,
        stash=MagicMock()
    )

    assert result is False

def test_on_scene_update_validates_metadata(mocker):
    """Metadata is validated before enqueueing."""
    from hooks.handlers import on_scene_update

    mocker.patch('hooks.handlers.is_scan_running', return_value=False)
    mocker.patch('hooks.handlers.is_scene_pending', return_value=False)

    mock_stash = MagicMock()
    mock_stash.call_GQL.return_value = {
        "findScene": {
            "files": [{"path": "/test.mp4"}],
            "title": "Test Title",
            "studio": {"name": "Studio"},
            "performers": [],
            "tags": []
        }
    }

    mock_validate = mocker.patch(
        'hooks.handlers.validate_metadata',
        return_value=(MagicMock(title="Test", scene_id=123), None)
    )

    mock_enqueue = mocker.patch('hooks.handlers.enqueue')
    mock_queue = MagicMock()

    result = on_scene_update(
        scene_id=123,
        update_data={"title": "Test Title"},
        queue=mock_queue,
        stash=mock_stash
    )

    assert result is True
    mock_enqueue.assert_called_once()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `tmpdir` fixture | `tmp_path` fixture | pytest 3.9+ | tmp_path returns pathlib.Path, cleaner API |
| `@validator` (Pydantic v1) | `@field_validator` (Pydantic v2) | Pydantic 2.0 | New decorator name, different signature |
| Manual patch context | `mocker` fixture | pytest-mock | Auto-cleanup, cleaner syntax |
| `assertRaises` (unittest) | `pytest.raises` | pytest standard | Context manager, better assertions |

**Deprecated/outdated:**
- `tmpdir`/`tmpdir_factory`: Use `tmp_path`/`tmp_path_factory` instead (pathlib-based)
- Pydantic v1 `@validator`: Use `@field_validator` with mode='before'/'after'
- `mock.patch` decorator: Use `mocker.patch` fixture for auto-cleanup

## Open Questions

Things that couldn't be fully resolved:

1. **persist-queue testing without full integration**
   - What we know: persist-queue's SQLiteAckQueue is complex; mocking may be fragile
   - What's unclear: Best level of integration testing vs pure unit testing
   - Recommendation: Use real SQLiteAckQueue with tmp_path for queue tests; mock for worker tests

2. **Coverage of async error paths**
   - What we know: Worker runs in background thread; some errors may be hard to trigger
   - What's unclear: How to test thread behavior deterministically
   - Recommendation: Test _process_job and other methods directly, mock threading for worker loop tests

## Sources

### Primary (HIGH confidence)
- [pytest fixtures documentation](https://docs.pytest.org/en/stable/how-to/fixtures.html) - fixture scopes, yield fixtures, teardown
- [pytest parametrize documentation](https://docs.pytest.org/en/stable/how-to/parametrize.html) - parametrization patterns
- [pytest-mock usage documentation](https://pytest-mock.readthedocs.io/en/latest/usage.html) - mocker fixture, spy, patch
- [pytest tmp_path documentation](https://docs.pytest.org/en/stable/how-to/tmp_path.html) - temporary directories
- [Pydantic v2 validators documentation](https://docs.pydantic.dev/latest/concepts/validators/) - field_validator, model_validator

### Secondary (MEDIUM confidence)
- [unittest.mock documentation](https://docs.python.org/3/library/unittest.mock.html) - MagicMock, patch internals
- Project codebase analysis: conftest.py, existing test patterns in test_plex_integration.py, test_backoff.py

### Tertiary (LOW confidence)
- WebSearch results for general best practices - verified against official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - using documented pytest/pytest-mock/pytest-cov versions
- Architecture: HIGH - patterns derived from official pytest documentation
- Pitfalls: HIGH - based on codebase analysis (queue import shadowing confirmed in existing tests)

**Research date:** 2026-02-03
**Valid until:** 60 days (stable testing patterns)
