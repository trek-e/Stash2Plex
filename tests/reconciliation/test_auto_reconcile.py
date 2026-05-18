"""Integration tests for auto-reconciliation wiring in Stash2Plex.py."""

from unittest.mock import Mock, MagicMock, patch


def _make_result(**kwargs):
    """Build a mock GapDetectionResult with sensible defaults."""
    result = Mock()
    result.total_gaps = kwargs.get("total_gaps", 0)
    result.enqueued_count = kwargs.get("enqueued_count", 0)
    result.empty_metadata_count = kwargs.get("empty_metadata_count", 0)
    result.stale_sync_count = kwargs.get("stale_sync_count", 0)
    result.missing_count = kwargs.get("missing_count", 0)
    result.scenes_checked = kwargs.get("scenes_checked", 0)
    result.skipped_already_queued = kwargs.get("skipped_already_queued", 0)
    result.skipped_no_metadata = kwargs.get("skipped_no_metadata", 0)
    result.errors = kwargs.get("errors", [])
    return result


# =============================================================================
# maybe_auto_reconcile() Tests
# =============================================================================


def test_auto_reconcile_disabled_when_never():
    """config.reconcile_interval='never' -> no engine call."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = "never"

    with patch("Stash2Plex.config", mock_config), \
         patch("Stash2Plex.stash_interface", MagicMock()), \
         patch("Stash2Plex.queue_manager", MagicMock()), \
         patch("Stash2Plex.get_plugin_data_dir", return_value="/tmp/data"), \
         patch("reconciliation.runner.GapDetectionEngine") as mock_engine:

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        mock_engine.assert_not_called()


def test_auto_reconcile_disabled_when_no_config():
    """config=None -> returns without error."""
    with patch("Stash2Plex.config", None), \
         patch("Stash2Plex.stash_interface", MagicMock()), \
         patch("Stash2Plex.queue_manager", MagicMock()), \
         patch("reconciliation.runner.GapDetectionEngine") as mock_engine:

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        mock_engine.assert_not_called()


def test_auto_reconcile_disabled_when_no_stash():
    """stash_interface=None -> returns without error."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = "hourly"

    with patch("Stash2Plex.config", mock_config), \
         patch("Stash2Plex.stash_interface", None), \
         patch("Stash2Plex.queue_manager", MagicMock()), \
         patch("reconciliation.runner.GapDetectionEngine") as mock_engine:

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        mock_engine.assert_not_called()


def test_auto_reconcile_startup_trigger():
    """First run triggers startup reconciliation (recent scope)."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = "daily"
    mock_config.reconcile_scope = "24h"

    mock_scheduler = MagicMock()
    # claim_if_due(is_startup=True) wins the slot → startup run proceeds
    mock_scheduler.claim_if_due.side_effect = lambda interval, is_startup=False: is_startup

    mock_result = _make_result(
        total_gaps=5,
        enqueued_count=3,
        empty_metadata_count=2,
        stale_sync_count=1,
        missing_count=2,
        scenes_checked=50,
    )
    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch("Stash2Plex.config", mock_config), \
         patch("Stash2Plex.stash_interface", MagicMock()), \
         patch("Stash2Plex.queue_manager", MagicMock()), \
         patch("Stash2Plex.get_plugin_data_dir", return_value="/tmp/data"), \
         patch("reconciliation.scheduler.ReconciliationScheduler", return_value=mock_scheduler), \
         patch("reconciliation.runner.GapDetectionEngine", return_value=mock_engine), \
         patch("reconciliation.runner.ReconciliationScheduler", return_value=mock_scheduler):

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        # Startup claim was attempted
        mock_scheduler.claim_if_due.assert_any_call("never", is_startup=True)

        # Engine called with 'recent' scope (startup always uses recent)
        mock_engine.run.assert_called_once_with(scope="recent")

        # Scheduler recorded the run with is_startup=True
        mock_scheduler.record_run.assert_called_once()
        args, kwargs = mock_scheduler.record_run.call_args
        assert args[0] is mock_result
        assert kwargs["is_startup"] is True


def test_auto_reconcile_interval_trigger():
    """Interval elapsed triggers reconciliation with configured scope."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = "hourly"
    mock_config.reconcile_scope = "7days"

    mock_scheduler = MagicMock()
    # Startup claim fails (not due); interval claim succeeds
    mock_scheduler.claim_if_due.side_effect = lambda interval, is_startup=False: not is_startup

    mock_result = _make_result(
        total_gaps=10,
        enqueued_count=8,
        empty_metadata_count=3,
        stale_sync_count=2,
        missing_count=5,
        scenes_checked=100,
    )
    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch("Stash2Plex.config", mock_config), \
         patch("Stash2Plex.stash_interface", MagicMock()), \
         patch("Stash2Plex.queue_manager", MagicMock()), \
         patch("Stash2Plex.get_plugin_data_dir", return_value="/tmp/data"), \
         patch("reconciliation.scheduler.ReconciliationScheduler", return_value=mock_scheduler), \
         patch("reconciliation.runner.GapDetectionEngine", return_value=mock_engine), \
         patch("reconciliation.runner.ReconciliationScheduler", return_value=mock_scheduler):

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        # Interval claim was attempted with the configured interval
        mock_scheduler.claim_if_due.assert_any_call("hourly", is_startup=False)

        # 7days config scope maps to 'recent_7days' engine scope
        mock_engine.run.assert_called_once_with(scope="recent_7days")

        # Scheduler recorded the run with is_startup=False
        mock_scheduler.record_run.assert_called_once()
        args, kwargs = mock_scheduler.record_run.call_args
        assert args[0] is mock_result
        assert kwargs["is_startup"] is False


def test_auto_reconcile_not_due():
    """Neither startup nor interval due -> no engine call."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = "daily"
    mock_config.reconcile_scope = "24h"

    mock_scheduler = MagicMock()
    # Both claim attempts fail → neither run fires
    mock_scheduler.claim_if_due.return_value = False

    with patch("Stash2Plex.config", mock_config), \
         patch("Stash2Plex.stash_interface", MagicMock()), \
         patch("Stash2Plex.queue_manager", MagicMock()), \
         patch("Stash2Plex.get_plugin_data_dir", return_value="/tmp/data"), \
         patch("reconciliation.scheduler.ReconciliationScheduler", return_value=mock_scheduler), \
         patch("reconciliation.runner.GapDetectionEngine") as mock_engine:

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        mock_engine.assert_not_called()


def test_auto_reconcile_exception_handling(capfd):
    """Engine error is caught and logged, not raised."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = "hourly"
    mock_config.reconcile_scope = "24h"

    mock_scheduler = MagicMock()
    # Startup claim succeeds → engine is called → engine raises
    mock_scheduler.claim_if_due.side_effect = lambda interval, is_startup=False: is_startup

    mock_engine = MagicMock()
    mock_engine.run.side_effect = Exception("Engine failed")

    with patch("Stash2Plex.config", mock_config), \
         patch("Stash2Plex.stash_interface", MagicMock()), \
         patch("Stash2Plex.queue_manager", MagicMock()), \
         patch("Stash2Plex.get_plugin_data_dir", return_value="/tmp/data"), \
         patch("reconciliation.scheduler.ReconciliationScheduler", return_value=mock_scheduler), \
         patch("reconciliation.runner.GapDetectionEngine", return_value=mock_engine), \
         patch("reconciliation.runner.ReconciliationScheduler", return_value=mock_scheduler):

        from Stash2Plex import maybe_auto_reconcile

        # Should not raise — caught by maybe_auto_reconcile
        maybe_auto_reconcile()

        captured = capfd.readouterr()
        assert "Auto-reconciliation check failed: Engine failed" in captured.err


# =============================================================================
# handle_queue_status() Enhanced Output Tests
# =============================================================================


def test_queue_status_shows_reconciliation_info(capfd):
    """When state exists, reconciliation info is logged."""
    mock_state = Mock()
    mock_state.last_run_time = 1234567890.0
    mock_state.last_run_scope = "recent"
    mock_state.last_scenes_checked = 100
    mock_state.last_gaps_found = 10
    mock_state.last_gaps_by_type = {
        "empty_metadata": 3,
        "stale_sync": 2,
        "missing": 5,
    }
    mock_state.last_enqueued = 8
    mock_state.is_startup_run = True
    mock_state.run_count = 5

    mock_scheduler = MagicMock()
    mock_scheduler.load_state.return_value = mock_state

    mock_stats = {"pending": 10, "in_progress": 2, "completed": 100, "failed": 3}

    mock_dlq = MagicMock()
    mock_dlq.get_count.return_value = 5
    mock_dlq.get_error_summary.return_value = {}

    with patch("Stash2Plex.get_plugin_data_dir", return_value="/tmp/data"), \
         patch("sync_queue.operations.get_stats", return_value=mock_stats), \
         patch("sync_queue.dlq.DeadLetterQueue", return_value=mock_dlq), \
         patch("reconciliation.scheduler.ReconciliationScheduler", return_value=mock_scheduler):

        from Stash2Plex import handle_queue_status
        handle_queue_status()

        stderr = capfd.readouterr().err

        assert "Queue Status" in stderr
        assert "Pending: 10" in stderr
        assert "Reconciliation Status" in stderr
        assert "Last run: 2009-02-13" in stderr
        assert "Scope: recent" in stderr
        assert "Scenes checked: 100" in stderr
        assert "Gaps found: 10" in stderr
        assert "Empty metadata: 3" in stderr
        assert "Stale sync: 2" in stderr
        assert "Missing from Plex: 5" in stderr
        assert "Enqueued: 8" in stderr
        assert "Triggered by startup" in stderr
        assert "Total reconciliation runs: 5" in stderr


def test_queue_status_no_reconciliation_runs(capfd):
    """When no state, shows 'No reconciliation runs yet'."""
    mock_state = Mock()
    mock_state.last_run_time = 0.0  # Never run

    mock_scheduler = MagicMock()
    mock_scheduler.load_state.return_value = mock_state

    mock_stats = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}

    mock_dlq = MagicMock()
    mock_dlq.get_count.return_value = 0
    mock_dlq.get_error_summary.return_value = {}

    with patch("Stash2Plex.get_plugin_data_dir", return_value="/tmp/data"), \
         patch("sync_queue.operations.get_stats", return_value=mock_stats), \
         patch("sync_queue.dlq.DeadLetterQueue", return_value=mock_dlq), \
         patch("reconciliation.scheduler.ReconciliationScheduler", return_value=mock_scheduler):

        from Stash2Plex import handle_queue_status
        handle_queue_status()

        stderr = capfd.readouterr().err

        assert "Reconciliation Status" in stderr
        assert "No reconciliation runs yet" in stderr


# =============================================================================
# Scope Mapping Tests
# =============================================================================


def test_reconcile_7days_mode_dispatch():
    """mode='reconcile_7days' calls handle_reconcile('recent_7days')."""
    mock_result = _make_result(scenes_checked=100, total_gaps=5,
                               empty_metadata_count=2, stale_sync_count=1,
                               missing_count=2, enqueued_count=4)
    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch("Stash2Plex.stash_interface", MagicMock()), \
         patch("Stash2Plex.config", MagicMock()), \
         patch("Stash2Plex.queue_manager", MagicMock()), \
         patch("Stash2Plex.get_plugin_data_dir", return_value="/tmp/data"), \
         patch("reconciliation.runner.GapDetectionEngine", return_value=mock_engine), \
         patch("reconciliation.runner.ReconciliationScheduler"):

        from Stash2Plex import handle_task
        handle_task({"mode": "reconcile_7days"}, stash=None)

        mock_engine.run.assert_called_once_with(scope="recent_7days")
