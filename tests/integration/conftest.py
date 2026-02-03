"""
Integration test fixtures for PlexSync.

These fixtures compose the unit test fixtures from tests/conftest.py
into complete workflow scenarios for testing:
- Full sync workflows
- Error scenarios
- Queue persistence
- Circuit breaker behavior

All integration tests should be marked with @pytest.mark.integration
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import time


# Integration fixtures inherit from tests/conftest.py automatically via pytest


@pytest.fixture
def integration_config(mock_config):
    """
    Extended mock config with all attributes needed by SyncWorker.

    Adds timeout and behavior settings to base mock_config.
    """
    # Add timeout settings for PlexClient
    mock_config.plex_connect_timeout = 10.0
    mock_config.plex_read_timeout = 30.0

    # Add behavior settings
    mock_config.preserve_plex_edits = False
    mock_config.strict_matching = False
    mock_config.dlq_retention_days = 30

    return mock_config


@pytest.fixture
def integration_worker(mock_queue, mock_dlq, integration_config, mock_plex_item, tmp_path):
    """
    Complete SyncWorker with all dependencies mocked for integration testing.

    Provides:
        - worker: SyncWorker instance with mocked queue, DLQ, config
        - mock_plex_item: The mock Plex item that will be "found"
        - Plex client mocked to return mock_plex_item on search

    Usage:
        def test_sync_workflow(integration_worker):
            worker, plex_item = integration_worker
            # worker processes jobs, plex_item.edit() will be called
    """
    from worker.processor import SyncWorker

    worker = SyncWorker(
        queue=mock_queue,
        dlq=mock_dlq,
        config=integration_config,
        data_dir=str(tmp_path),
    )

    # Mock Plex client to return found item
    mock_section = MagicMock()
    mock_section.search.return_value = [mock_plex_item]
    mock_section.all.return_value = [mock_plex_item]
    mock_section.title = "Test Library"
    mock_section.type = "movie"

    mock_client = MagicMock()
    mock_client.server.library.sections.return_value = [mock_section]
    mock_client.server.library.section.return_value = mock_section
    worker._plex_client = mock_client

    return worker, mock_plex_item


@pytest.fixture
def integration_worker_no_match(mock_queue, mock_dlq, integration_config, tmp_path):
    """
    SyncWorker configured to return no Plex matches (PlexNotFound scenario).

    Usage:
        def test_not_found_scenario(integration_worker_no_match):
            worker = integration_worker_no_match
            # Processing will raise PlexNotFound
    """
    from worker.processor import SyncWorker

    worker = SyncWorker(
        queue=mock_queue,
        dlq=mock_dlq,
        config=integration_config,
        data_dir=str(tmp_path),
    )

    # Mock Plex client to return empty results
    mock_section = MagicMock()
    mock_section.search.return_value = []
    mock_section.all.return_value = []
    mock_section.title = "Test Library"

    mock_client = MagicMock()
    mock_client.server.library.sections.return_value = [mock_section]
    mock_client.server.library.section.return_value = mock_section
    worker._plex_client = mock_client

    return worker


@pytest.fixture
def integration_worker_connection_error(mock_queue, mock_dlq, integration_config, tmp_path):
    """
    SyncWorker configured to raise connection errors (Plex down scenario).

    Usage:
        def test_plex_down_scenario(integration_worker_connection_error):
            worker = integration_worker_connection_error
            # Processing will raise PlexTemporaryError
    """
    from worker.processor import SyncWorker

    worker = SyncWorker(
        queue=mock_queue,
        dlq=mock_dlq,
        config=integration_config,
        data_dir=str(tmp_path),
    )

    # Mock Plex client to raise connection error
    mock_client = MagicMock()
    mock_client.server.library.section.side_effect = ConnectionError("Connection refused")
    mock_client.server.library.sections.side_effect = ConnectionError("Connection refused")
    worker._plex_client = mock_client

    return worker


@pytest.fixture
def real_queue(tmp_path):
    """
    Real SQLiteAckQueue for testing persistence across restarts.

    Uses tmp_path to create isolated database per test.

    Usage:
        def test_queue_persistence(real_queue):
            real_queue.put({'scene_id': 123})
            # Simulate restart by creating new queue with same path
    """
    import persistqueue
    queue_path = str(tmp_path / "test_queue")
    return persistqueue.SQLiteAckQueue(queue_path, auto_resume=True)


@pytest.fixture
def sample_sync_job():
    """
    Complete sync job dictionary for integration tests.

    Contains all fields expected by SyncWorker._process_job().
    """
    return {
        'scene_id': 123,
        'update_type': 'metadata',
        'data': {
            'path': '/media/videos/test_scene.mp4',
            'title': 'Test Scene Title',
            'studio': 'Test Studio',
            'details': 'A test scene description.',
            'performers': ['Performer One', 'Performer Two'],
            'tags': ['Tag One', 'Tag Two'],
        },
        'enqueued_at': time.time(),
        'job_key': 'scene_123',
        'pqid': 1,
    }


@pytest.fixture
def fresh_circuit_breaker():
    """
    Fresh circuit breaker instance for each test.

    Prevents state leakage between tests.
    """
    from worker.circuit_breaker import CircuitBreaker
    return CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60.0,
        success_threshold=1
    )
