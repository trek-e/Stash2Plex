"""
Shared pytest fixtures for Stash2Plex tests.

Provides reusable mock fixtures for:
- Plex API (PlexServer, library sections, media items)
- Configuration objects
- Queue operations (SQLiteAckQueue, DeadLetterQueue)
- Sample test data (jobs, metadata)

These fixtures use unittest.mock to avoid requiring external dependencies
like plexapi or stashapi during test execution.
"""

import pytest
from unittest.mock import Mock, MagicMock
from typing import Any


# =============================================================================
# Plex API Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_plex_server():
    """
    Mock PlexServer instance with basic attributes.

    Provides:
        - friendlyName: Server display name
        - version: Plex server version string
        - library: Mock library with sections() method

    Usage:
        def test_connection(mock_plex_server):
            assert mock_plex_server.friendlyName == "Test Plex Server"
    """
    server = MagicMock()
    server.friendlyName = "Test Plex Server"
    server.version = "1.32.0.0000"

    # Library mock with sections
    server.library = MagicMock()
    server.library.sections.return_value = []
    server.library.section.return_value = MagicMock()

    return server


@pytest.fixture
def mock_plex_section():
    """
    Mock Plex library section (e.g., Movies, TV Shows).

    Provides:
        - title: Section name
        - type: Section type ("movie", "show", etc.)
        - search(): Returns empty list by default
        - all(): Returns empty list by default
        - key: Section ID

    Usage:
        def test_search(mock_plex_section):
            mock_plex_section.search.return_value = [mock_plex_item]
            results = mock_plex_section.search(title="Test")
    """
    section = MagicMock()
    section.title = "Movies"
    section.type = "movie"
    section.key = "1"
    section.search.return_value = []
    section.all.return_value = []

    return section


@pytest.fixture
def mock_plex_item():
    """Mock Plex media item. See tests/factories.py for customization."""
    from tests.factories import make_plex_item
    return make_plex_item()


# =============================================================================
# Configuration Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_config():
    """Mock configuration. See tests/factories.py for customization."""
    from tests.factories import make_config
    return make_config()


@pytest.fixture
def valid_config_dict():
    """
    Dictionary with valid configuration values for Stash2PlexConfig instantiation.

    Can be used to create actual Stash2PlexConfig objects or test config validation.

    Usage:
        def test_config_parsing(valid_config_dict):
            config = Stash2PlexConfig(**valid_config_dict)
    """
    return {
        "plex_url": "http://localhost:32400",
        "plex_token": "test-token-abc123",
        "plex_library": "Movies",
        "stash_url": "http://localhost:9999",
        "stash_api_key": "stash-api-key-xyz",
        "poll_interval": 5,
        "max_retries": 5,
        "initial_backoff": 1.0,
        "max_backoff": 300.0,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_timeout": 60,
    }


# =============================================================================
# Queue Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_queue():
    """
    Mock SQLiteAckQueue for testing queue operations.

    Provides queue-like interface:
        - put(item): Add item to queue
        - get(block, timeout): Get item from queue
        - ack(item): Acknowledge successful processing
        - nack(item): Return item to queue for retry
        - qsize(): Return queue size
        - empty(): Return True if queue is empty

    Usage:
        def test_enqueue(mock_queue):
            mock_queue.put(job)
            mock_queue.put.assert_called_once_with(job)
    """
    queue = MagicMock()
    queue.put.return_value = None
    queue.get.return_value = None
    queue.ack.return_value = None
    queue.nack.return_value = None
    queue.qsize.return_value = 0
    queue.empty.return_value = True

    return queue


@pytest.fixture
def mock_dlq():
    """
    Mock DeadLetterQueue for testing failed job handling.

    Provides DLQ interface:
        - add(job, error, retry_count): Add failed job
        - get_count(): Return number of entries
        - get_recent(limit): Return recent failed jobs
        - get_by_id(dlq_id): Return full job details
        - delete_older_than(days): Cleanup old entries

    Usage:
        def test_dlq_add(mock_dlq):
            mock_dlq.add(job, error, retry_count=5)
            mock_dlq.add.assert_called_once()
    """
    dlq = MagicMock()
    dlq.add.return_value = None
    dlq.get_count.return_value = 0
    dlq.get_recent.return_value = []
    dlq.get_by_id.return_value = None
    dlq.delete_older_than.return_value = None

    return dlq


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture
def sample_job():
    """Sample sync job. See tests/factories.py for customization."""
    from tests.factories import make_job
    return make_job(performers=["Performer One", "Performer Two"], tags=["Tag One", "Tag Two"])


@pytest.fixture
def sample_metadata_dict():
    """
    Valid metadata dictionary for SyncMetadata model instantiation.

    Contains all fields that SyncMetadata accepts:
        - scene_id: Required positive integer
        - title: Required non-empty string
        - details: Optional description
        - date: Optional release date
        - rating100: Optional rating 0-100
        - studio: Optional studio name
        - performers: Optional list of names
        - tags: Optional list of tags

    Usage:
        def test_metadata_validation(sample_metadata_dict):
            metadata = SyncMetadata(**sample_metadata_dict)
            assert metadata.title == "Test Scene Title"
    """
    return {
        "scene_id": 456,
        "title": "Test Scene Title",
        "details": "A detailed description of the test scene.",
        "date": "2024-01-15",
        "rating100": 85,
        "studio": "Premium Studio",
        "performers": ["Jane Doe", "John Smith"],
        "tags": ["HD", "Interview", "Documentary"],
    }


# =============================================================================
# Stash API Mock Fixtures (for integration testing)
# =============================================================================

@pytest.fixture
def mock_stash_interface():
    """
    Mock StashInterface for testing Stash API interactions.

    Provides:
        - find_scene(scene_id): Return mock scene data
        - find_scenes(filter): Return list of scenes

    Usage:
        def test_stash_lookup(mock_stash_interface):
            mock_stash_interface.find_scene.return_value = scene_data
    """
    stash = MagicMock()
    stash.find_scene.return_value = None
    stash.find_scenes.return_value = []

    return stash


@pytest.fixture
def sample_stash_scene():
    """Sample Stash scene data. See tests/factories.py for customization."""
    from tests.factories import make_stash_scene
    return make_stash_scene()
