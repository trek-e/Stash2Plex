"""
Tests for handle_process_queue() exclusion lock and try_acquire_drain_lock().

Uses real fcntl locks (not mocks) with tempfile directories so the OS-level
mutual exclusion is actually exercised. Multiprocessing is used where we need
to verify true cross-process exclusion.
"""
import multiprocessing
import os
import time
from unittest.mock import MagicMock, patch


from worker.processor import SyncWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_worker(tmp_path: str) -> SyncWorker:
    """Build a SyncWorker with minimal mocked dependencies."""
    queue_manager = MagicMock()
    queue_manager.queue_path = os.path.join(tmp_path, "queue")
    queue_manager.get_queue.return_value = MagicMock(size=0)
    dlq = MagicMock()
    # dlq.get_count() must return an int so _log_dlq_status can compare it
    dlq.get_count.return_value = 0
    dlq.get_error_summary.return_value = {}
    config = MagicMock()
    config.dlq_retention_days = 30
    return SyncWorker(queue_manager, dlq, config, data_dir=tmp_path)


def _worker_acquire(tmp_path: str, result_queue):
    """Subprocess worker: try_acquire_drain_lock, push result, hold briefly."""
    worker = _make_worker(tmp_path)
    acquired = worker.try_acquire_drain_lock(resume_orphaned=False)
    result_queue.put(acquired)
    if acquired:
        time.sleep(0.3)  # hold the lock so the peer sees contention
        worker._release_lock()


# ---------------------------------------------------------------------------
# try_acquire_drain_lock basics
# ---------------------------------------------------------------------------


def test_try_acquire_drain_lock_returns_true_when_free(tmp_path):
    """First caller acquires the drain lock successfully."""
    worker = _make_worker(str(tmp_path))
    acquired = worker.try_acquire_drain_lock(resume_orphaned=False)
    assert acquired is True
    worker._release_lock()


def test_try_acquire_drain_lock_returns_false_when_held(tmp_path):
    """Second caller cannot acquire the lock while first holds it."""
    w1 = _make_worker(str(tmp_path))
    w2 = _make_worker(str(tmp_path))

    assert w1.try_acquire_drain_lock(resume_orphaned=False) is True
    assert w2.try_acquire_drain_lock(resume_orphaned=False) is False

    w1._release_lock()


def test_try_acquire_drain_lock_reacquirable_after_release(tmp_path):
    """Lock can be re-acquired after the holder releases it."""
    w1 = _make_worker(str(tmp_path))
    w2 = _make_worker(str(tmp_path))

    assert w1.try_acquire_drain_lock(resume_orphaned=False) is True
    w1._release_lock()

    assert w2.try_acquire_drain_lock(resume_orphaned=False) is True
    w2._release_lock()


# ---------------------------------------------------------------------------
# Cross-process exclusion (real fcntl semantics)
# ---------------------------------------------------------------------------


def test_try_acquire_drain_lock_cross_process_exclusion(tmp_path):
    """
    Two separate processes racing try_acquire_drain_lock: exactly ONE wins.
    Verifies actual OS-level fcntl exclusion, not just in-process logic.
    """
    data_dir = str(tmp_path)
    result_queue = multiprocessing.Queue()

    p1 = multiprocessing.Process(target=_worker_acquire, args=(data_dir, result_queue))
    p2 = multiprocessing.Process(target=_worker_acquire, args=(data_dir, result_queue))

    p1.start()
    p2.start()
    p1.join(timeout=5)
    p2.join(timeout=5)

    results = [result_queue.get_nowait() for _ in range(2)]
    true_count = sum(1 for r in results if r is True)
    assert true_count == 1, f"Expected exactly 1 winner, got {results}"


# ---------------------------------------------------------------------------
# try_start_exclusive uses try_acquire_drain_lock internally
# ---------------------------------------------------------------------------


def test_try_start_exclusive_blocks_second_caller(tmp_path):
    """
    try_start_exclusive() on the second caller returns False because
    try_acquire_drain_lock() is already held.
    """
    w1 = _make_worker(str(tmp_path))
    w2 = _make_worker(str(tmp_path))

    # Acquire directly so we don't spin up a real thread
    assert w1.try_acquire_drain_lock(resume_orphaned=False) is True

    # try_start_exclusive on w2 must fail because the lock is taken
    result = w2.try_start_exclusive(resume_orphaned=False)
    assert result is False

    w1._release_lock()


def test_drain_lock_and_start_exclusive_mutually_exclusive(tmp_path):
    """
    A foreground run_batch holder (try_acquire_drain_lock) and a background
    daemon holder (try_start_exclusive) cannot both hold the lock.

    We patch SyncWorker.start() to a no-op so the test doesn't spin up a real
    worker thread (which would need a real Plex/queue). The lock acquisition
    logic is what we are testing, not the thread lifecycle.
    """
    from unittest.mock import patch as _patch

    w_foreground = _make_worker(str(tmp_path))
    w_background = _make_worker(str(tmp_path))

    with _patch.object(w_foreground, "start"), _patch.object(w_background, "start"):
        # Foreground drain acquires the lock
        assert w_foreground.try_acquire_drain_lock(resume_orphaned=False) is True

        # Background daemon attempt must fail (lock held by foreground)
        assert w_background.try_start_exclusive(resume_orphaned=False) is False

        w_foreground._release_lock()

        # After release, background daemon can now acquire
        assert w_background.try_start_exclusive(resume_orphaned=False) is True
        w_background._release_lock()  # clean up (no thread was started)


# ---------------------------------------------------------------------------
# handle_process_queue() short-circuits when lock is held
# ---------------------------------------------------------------------------


def test_handle_process_queue_skips_when_lock_held(tmp_path):
    """
    handle_process_queue() should exit without calling run_batch() when
    another process already holds the drain lock.
    """
    import fcntl

    data_dir = str(tmp_path)
    lock_path = os.path.join(data_dir, "worker.lock")

    # Hold the lock externally to simulate another process draining
    lock_fd = open(lock_path, "w")
    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    run_batch_called = []

    def fake_run_batch(**kwargs):
        run_batch_called.append(True)
        return {"processed": 0, "failed": 0, "skipped": 0}

    mock_queue_manager = MagicMock()
    mock_queue_manager.queue_path = os.path.join(data_dir, "queue")
    mock_queue_manager.get_queue.return_value = MagicMock(size=0)
    mock_dlq = MagicMock()
    mock_config = MagicMock()
    mock_config.dlq_retention_days = 30

    mock_worker = _make_worker(data_dir)
    mock_worker.run_batch = fake_run_batch

    try:
        with patch("Stash2Plex.config", mock_config), \
             patch("Stash2Plex.queue_manager", mock_queue_manager), \
             patch("Stash2Plex.dlq", mock_dlq), \
             patch("Stash2Plex.worker", None), \
             patch("Stash2Plex.get_plugin_data_dir", return_value=data_dir), \
             patch("Stash2Plex.configure_plex_device_identity"), \
             patch("worker.processor.SyncWorker", return_value=mock_worker):
            from Stash2Plex import handle_process_queue
            handle_process_queue()
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()

    assert run_batch_called == [], "run_batch must NOT be called when lock is held"


def test_handle_process_queue_runs_when_lock_free(tmp_path):
    """
    handle_process_queue() calls run_batch() when no other process holds
    the drain lock.
    """
    data_dir = str(tmp_path)

    mock_queue_manager = MagicMock()
    mock_queue_manager.queue_path = os.path.join(data_dir, "queue")
    mock_queue_manager.get_queue.return_value = MagicMock(size=0)
    mock_dlq = MagicMock()
    mock_config = MagicMock()
    mock_config.dlq_retention_days = 30

    run_batch_called = []
    mock_worker = _make_worker(data_dir)

    def fake_run_batch(**kwargs):
        run_batch_called.append(True)
        return {"processed": 0, "failed": 0, "skipped": 0}

    mock_worker.run_batch = fake_run_batch

    with patch("Stash2Plex.config", mock_config), \
         patch("Stash2Plex.queue_manager", mock_queue_manager), \
         patch("Stash2Plex.dlq", mock_dlq), \
         patch("Stash2Plex.worker", None), \
         patch("Stash2Plex.get_plugin_data_dir", return_value=data_dir), \
         patch("Stash2Plex.configure_plex_device_identity"), \
         patch("worker.processor.SyncWorker", return_value=mock_worker):
        from Stash2Plex import handle_process_queue
        handle_process_queue()

    assert run_batch_called == [True], "run_batch must be called when lock is free"
