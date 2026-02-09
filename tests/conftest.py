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
    """
    Mock Plex media item (movie or episode).

    Provides:
        - title: Item title
        - studio: Studio name
        - summary: Description/details
        - actors: List of mock actors
        - genres: List of mock genres
        - collections: List of mock collections
        - media[0].parts[0].file: File path
        - ratingKey: Unique Plex item ID
        - guid: Plex GUID for item

    Usage:
        def test_item(mock_plex_item):
            assert mock_plex_item.title == "Test Scene"
            path = mock_plex_item.media[0].parts[0].file
    """
    item = MagicMock()
    item.title = "Test Scene"
    item.studio = "Test Studio"
    item.summary = "Test description for the scene."
    item.ratingKey = 12345
    item.guid = "plex://movie/abc123"

    # Actors (Plex uses 'actors' attribute for cast)
    actor1 = MagicMock()
    actor1.tag = "Performer One"
    actor2 = MagicMock()
    actor2.tag = "Performer Two"
    item.actors = [actor1, actor2]

    # Genres
    genre1 = MagicMock()
    genre1.tag = "Genre One"
    item.genres = [genre1]

    # Collections
    collection1 = MagicMock()
    collection1.tag = "Collection One"
    item.collections = [collection1]

    # File path through media hierarchy
    part = MagicMock()
    part.file = "/media/videos/test_scene.mp4"

    media = MagicMock()
    media.parts = [part]

    item.media = [media]

    # Edit method for updating metadata
    item.edit.return_value = None
    item.reload.return_value = None

    return item


# =============================================================================
# Configuration Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_config():
    """
    Mock configuration object with all Stash2Plex settings.

    Provides all config attributes needed by Stash2Plex components:
        - plex_url: Plex server URL
        - plex_token: Authentication token
        - plex_library: Library section name
        - stash_url: Stash server URL
        - stash_api_key: Stash API key
        - poll_interval: Queue poll interval in seconds
        - max_retries: Maximum retry attempts
        - initial_backoff: Initial backoff delay
        - max_backoff: Maximum backoff delay
        - circuit_breaker_threshold: Failures before opening circuit
        - circuit_breaker_timeout: Time to wait in open state

    Usage:
        def test_worker(mock_config):
            assert mock_config.max_retries == 5
    """
    config = Mock()
    config.plex_url = "http://localhost:32400"
    config.plex_token = "test-token-abc123"
    config.plex_library = "Movies"
    config.plex_libraries = ["Movies"]
    config.stash_url = "http://localhost:9999"
    config.stash_api_key = "stash-api-key-xyz"
    config.poll_interval = 5
    config.max_retries = 5
    config.initial_backoff = 1.0
    config.max_backoff = 300.0
    config.circuit_breaker_threshold = 5
    config.circuit_breaker_timeout = 60
    config.debug_logging = False
    config.obfuscate_paths = False
    config.max_tags = 100

    return config


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
    """
    Sample sync job dictionary matching SyncJob structure.

    Returns job dict with:
        - scene_id: Stash scene ID
        - update_type: Type of update ("metadata")
        - data: Metadata to sync (path, title, studio, details)
        - enqueued_at: Timestamp
        - job_key: Deduplication key

    Usage:
        def test_process_job(sample_job):
            result = processor.process(sample_job)
    """
    return {
        "scene_id": 123,
        "update_type": "metadata",
        "data": {
            "path": "/media/videos/test_scene.mp4",
            "title": "Test Scene Title",
            "studio": "Test Studio",
            "details": "A test scene description.",
            "performers": ["Performer One", "Performer Two"],
            "tags": ["Tag One", "Tag Two"],
        },
        "enqueued_at": 1700000000.0,
        "job_key": "scene_123",
    }


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
    """
    Sample Stash scene data structure as returned by StashInterface.

    Matches the structure returned by stashapi for scene queries.

    Usage:
        def test_scene_processing(sample_stash_scene):
            title = sample_stash_scene["title"]
    """
    return {
        "id": "789",
        "title": "Stash Scene Title",
        "details": "Scene details from Stash.",
        "date": "2024-02-20",
        "rating100": 75,
        "studio": {"name": "Stash Studio"},
        "performers": [
            {"name": "Performer A"},
            {"name": "Performer B"},
        ],
        "tags": [
            {"name": "Tag A"},
            {"name": "Tag B"},
        ],
        "files": [
            {"path": "/stash/media/scene_789.mp4"}
        ],
    }
