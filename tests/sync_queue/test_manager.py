"""
Tests for sync_queue/manager.py - QueueManager class.

Tests queue initialization, lifecycle management, and shutdown.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestQueueManager:
    """Tests for QueueManager class."""

    def test_creates_queue_directory(self, tmp_path):
        """QueueManager creates queue directory at data_dir/queue."""
        from sync_queue.manager import QueueManager

        manager = QueueManager(data_dir=str(tmp_path))

        queue_path = tmp_path / "queue"
        assert queue_path.exists()
        assert queue_path.is_dir()

        manager.shutdown()

    def test_get_queue_returns_sqlite_ack_queue(self, tmp_path):
        """get_queue returns a queue with put/get methods."""
        from sync_queue.manager import QueueManager

        manager = QueueManager(data_dir=str(tmp_path))
        queue = manager.get_queue()

        # Verify queue interface
        assert queue is not None
        assert hasattr(queue, "put")
        assert hasattr(queue, "get")
        assert hasattr(queue, "ack")
        assert hasattr(queue, "nack")

        manager.shutdown()

    def test_shutdown_logs_message(self, tmp_path, capsys):
        """shutdown() completes without error and logs message."""
        from sync_queue.manager import QueueManager

        manager = QueueManager(data_dir=str(tmp_path))
        manager.shutdown()

        captured = capsys.readouterr()
        assert "shutting down" in captured.out.lower()

    def test_uses_data_dir_from_argument(self, tmp_path):
        """QueueManager uses data_dir argument when provided."""
        from sync_queue.manager import QueueManager

        custom_dir = tmp_path / "custom_data"
        custom_dir.mkdir()

        manager = QueueManager(data_dir=str(custom_dir))

        assert manager.data_dir == str(custom_dir)
        assert manager.queue_path == str(custom_dir / "queue")

        manager.shutdown()

    def test_uses_stash_plugin_data_env_var(self, tmp_path, monkeypatch):
        """QueueManager uses STASH_PLUGIN_DATA environment variable when set."""
        from sync_queue.manager import QueueManager

        env_data_dir = tmp_path / "env_stash_data"
        env_data_dir.mkdir()
        monkeypatch.setenv("STASH_PLUGIN_DATA", str(env_data_dir))

        manager = QueueManager()

        assert manager.data_dir == str(env_data_dir)

        manager.shutdown()

    def test_queue_is_accessible_after_init(self, tmp_path):
        """Queue can be used immediately after initialization."""
        from sync_queue.manager import QueueManager

        manager = QueueManager(data_dir=str(tmp_path))
        queue = manager.get_queue()

        # Should be able to put a test item
        test_job = {"test": "data"}
        queue.put(test_job)

        # Should be able to get it back
        retrieved = queue.get(timeout=1)
        assert retrieved["test"] == "data"

        # Clean up
        queue.ack(retrieved)
        manager.shutdown()

    def test_raises_import_error_when_persistqueue_missing(self, tmp_path):
        """QueueManager raises ImportError when persistqueue not installed."""
        import sync_queue.manager as manager_module

        # Save original
        original_pq = manager_module.persistqueue

        try:
            # Simulate missing persistqueue
            manager_module.persistqueue = None

            with pytest.raises(ImportError) as exc_info:
                manager_module.QueueManager(data_dir=str(tmp_path))

            assert "persist-queue not installed" in str(exc_info.value)
        finally:
            # Restore
            manager_module.persistqueue = original_pq

    def test_uses_default_fallback_when_no_env_var(self, monkeypatch):
        """QueueManager falls back to home dir when no env var and no data_dir."""
        from sync_queue.manager import QueueManager
        import os

        # Ensure STASH_PLUGIN_DATA is not set
        monkeypatch.delenv("STASH_PLUGIN_DATA", raising=False)

        # Mock expanduser to return a known path
        mock_home = "/mock/home"
        monkeypatch.setattr(os.path, "expanduser", lambda x: mock_home if x == "~" else x)

        # Mock makedirs to avoid actual directory creation
        created_paths = []
        original_makedirs = os.makedirs

        def mock_makedirs(path, exist_ok=False):
            created_paths.append(path)

        monkeypatch.setattr(os, "makedirs", mock_makedirs)

        # Need to also mock _init_queue to avoid actual queue creation
        import sync_queue.manager as manager_module
        monkeypatch.setattr(
            manager_module.QueueManager,
            "_init_queue",
            lambda self: MagicMock()
        )

        manager = QueueManager()

        # Verify fallback path was used
        expected_data_dir = os.path.join(mock_home, ".stash", "plugins", "Stash2Plex", "data")
        assert manager.data_dir == expected_data_dir
        assert manager.queue_path == os.path.join(expected_data_dir, "queue")

        manager.shutdown()
