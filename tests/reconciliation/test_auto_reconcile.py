"""Integration tests for auto-reconciliation wiring in Stash2Plex.py."""

from unittest.mock import Mock, MagicMock, patch, call
import pytest


# =============================================================================
# maybe_auto_reconcile() Tests
# =============================================================================

def test_auto_reconcile_disabled_when_never():
    """config.reconcile_interval='never' -> no engine call."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = 'never'

    with patch('Stash2Plex.config', mock_config), \
         patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.queue_manager', MagicMock()), \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine') as mock_engine:

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        # Engine should not be instantiated
        mock_engine.assert_not_called()


def test_auto_reconcile_disabled_when_no_config():
    """config=None -> returns without error."""
    with patch('Stash2Plex.config', None), \
         patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.queue_manager', MagicMock()), \
         patch('reconciliation.engine.GapDetectionEngine') as mock_engine:

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        # Engine should not be called
        mock_engine.assert_not_called()


def test_auto_reconcile_disabled_when_no_stash():
    """stash_interface=None -> returns without error."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = 'hourly'

    with patch('Stash2Plex.config', mock_config), \
         patch('Stash2Plex.stash_interface', None), \
         patch('Stash2Plex.queue_manager', MagicMock()), \
         patch('reconciliation.engine.GapDetectionEngine') as mock_engine:

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        # Engine should not be called
        mock_engine.assert_not_called()


def test_auto_reconcile_startup_trigger():
    """First run triggers startup reconciliation (recent scope)."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = 'daily'
    mock_config.reconcile_scope = '24h'

    mock_scheduler = MagicMock()
    mock_scheduler.is_startup_due.return_value = True
    mock_scheduler.is_due.return_value = False

    mock_result = Mock()
    mock_result.total_gaps = 5
    mock_result.enqueued_count = 3
    mock_result.empty_metadata_count = 2
    mock_result.stale_sync_count = 1
    mock_result.missing_count = 2
    mock_result.scenes_checked = 50

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.config', mock_config), \
         patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.scheduler.ReconciliationScheduler', return_value=mock_scheduler), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        # Verify startup check was called
        mock_scheduler.is_startup_due.assert_called_once()

        # Verify engine was called with 'recent' scope (startup uses recent)
        mock_engine.run.assert_called_once_with(scope='recent')

        # Verify result was recorded
        mock_scheduler.record_run.assert_called_once()
        call_args = mock_scheduler.record_run.call_args
        assert call_args[0][0] == mock_result  # result
        assert call_args[1]['is_startup'] is True


def test_auto_reconcile_interval_trigger():
    """Interval elapsed triggers reconciliation with configured scope."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = 'hourly'
    mock_config.reconcile_scope = '7days'

    mock_scheduler = MagicMock()
    mock_scheduler.is_startup_due.return_value = False
    mock_scheduler.is_due.return_value = True

    mock_result = Mock()
    mock_result.total_gaps = 10
    mock_result.enqueued_count = 8
    mock_result.empty_metadata_count = 3
    mock_result.stale_sync_count = 2
    mock_result.missing_count = 5
    mock_result.scenes_checked = 100

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.config', mock_config), \
         patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.scheduler.ReconciliationScheduler', return_value=mock_scheduler), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        # Verify interval check was called with config value
        mock_scheduler.is_due.assert_called_once_with('hourly')

        # Verify engine was called with mapped scope (7days -> recent_7days)
        mock_engine.run.assert_called_once_with(scope='recent_7days')

        # Verify result was recorded
        mock_scheduler.record_run.assert_called_once()
        call_args = mock_scheduler.record_run.call_args
        assert call_args[0][0] == mock_result  # result
        assert call_args[1]['is_startup'] is False


def test_auto_reconcile_not_due():
    """Neither startup nor interval due -> no engine call."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = 'daily'
    mock_config.reconcile_scope = '24h'

    mock_scheduler = MagicMock()
    mock_scheduler.is_startup_due.return_value = False
    mock_scheduler.is_due.return_value = False

    with patch('Stash2Plex.config', mock_config), \
         patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.queue_manager', MagicMock()), \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.scheduler.ReconciliationScheduler', return_value=mock_scheduler), \
         patch('reconciliation.engine.GapDetectionEngine') as mock_engine:

        from Stash2Plex import maybe_auto_reconcile
        maybe_auto_reconcile()

        # Engine should not be instantiated (neither trigger fired)
        mock_engine.assert_not_called()


def test_auto_reconcile_exception_handling(capfd):
    """Engine error is caught and logged, not raised."""
    mock_config = MagicMock()
    mock_config.reconcile_interval = 'hourly'
    mock_config.reconcile_scope = '24h'

    mock_scheduler = MagicMock()
    mock_scheduler.is_startup_due.return_value = True
    mock_scheduler.is_due.return_value = False

    mock_engine = MagicMock()
    mock_engine.run.side_effect = Exception("Engine failed")

    with patch('Stash2Plex.config', mock_config), \
         patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.scheduler.ReconciliationScheduler', return_value=mock_scheduler), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import maybe_auto_reconcile

        # Should not raise, error should be caught
        maybe_auto_reconcile()

        # Verify error was logged
        captured = capfd.readouterr()
        assert 'Auto-reconciliation failed: Engine failed' in captured.err


# =============================================================================
# _run_auto_reconcile() Tests
# =============================================================================

def test_run_auto_reconcile_records_state():
    """After successful run, scheduler state is updated."""
    mock_config = MagicMock()
    mock_config.reconcile_scope = '24h'
    mock_scheduler = MagicMock()

    mock_result = Mock()
    mock_result.total_gaps = 5
    mock_result.enqueued_count = 3
    mock_result.empty_metadata_count = 2
    mock_result.stale_sync_count = 1
    mock_result.missing_count = 2
    mock_result.scenes_checked = 50

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.config', mock_config), \
         patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import _run_auto_reconcile
        _run_auto_reconcile(mock_scheduler, scope='recent', is_startup=True)

        # Verify scheduler.record_run was called
        mock_scheduler.record_run.assert_called_once()
        # Check the actual call signature: record_run(result, scope=scope_label, is_startup=is_startup)
        args, kwargs = mock_scheduler.record_run.call_args
        assert args[0] == mock_result
        assert kwargs['scope'] == "recent (startup)"
        assert kwargs['is_startup'] is True


def test_run_auto_reconcile_engine_error(capfd):
    """Engine exception is caught and logged."""
    mock_config = MagicMock()
    mock_scheduler = MagicMock()

    mock_engine = MagicMock()
    mock_engine.run.side_effect = Exception("Engine crashed")

    with patch('Stash2Plex.config', mock_config), \
         patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import _run_auto_reconcile

        # Should not raise
        _run_auto_reconcile(mock_scheduler, scope='all', is_startup=False)

        # Verify error was logged
        captured = capfd.readouterr()
        assert 'Auto-reconciliation failed: Engine crashed' in captured.err

        # Verify scheduler.record_run was NOT called (run didn't complete)
        mock_scheduler.record_run.assert_not_called()


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
        'empty_metadata': 3,
        'stale_sync': 2,
        'missing': 5
    }
    mock_state.last_enqueued = 8
    mock_state.is_startup_run = True
    mock_state.run_count = 5

    mock_scheduler = MagicMock()
    mock_scheduler.load_state.return_value = mock_state

    mock_stats = {
        'pending': 10,
        'in_progress': 2,
        'completed': 100,
        'failed': 3
    }

    mock_dlq = MagicMock()
    mock_dlq.get_count.return_value = 5
    mock_dlq.get_error_summary.return_value = {}

    with patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('sync_queue.operations.get_stats', return_value=mock_stats), \
         patch('sync_queue.dlq.DeadLetterQueue', return_value=mock_dlq), \
         patch('reconciliation.scheduler.ReconciliationScheduler', return_value=mock_scheduler):

        from Stash2Plex import handle_queue_status
        handle_queue_status()

        captured = capfd.readouterr()
        stderr = captured.err

        # Verify queue stats are shown
        assert 'Queue Status' in stderr
        assert 'Pending: 10' in stderr

        # Verify reconciliation status section exists
        assert 'Reconciliation Status' in stderr
        assert 'Last run: 2009-02-13' in stderr  # timestamp conversion
        assert 'Scope: recent' in stderr
        assert 'Scenes checked: 100' in stderr
        assert 'Gaps found: 10' in stderr
        assert 'Empty metadata: 3' in stderr
        assert 'Stale sync: 2' in stderr
        assert 'Missing from Plex: 5' in stderr
        assert 'Enqueued: 8' in stderr
        assert 'Triggered by startup' in stderr
        assert 'Total reconciliation runs: 5' in stderr


def test_queue_status_no_reconciliation_runs(capfd):
    """When no state, shows 'No reconciliation runs yet'."""
    mock_state = Mock()
    mock_state.last_run_time = 0.0  # Never run

    mock_scheduler = MagicMock()
    mock_scheduler.load_state.return_value = mock_state

    mock_stats = {
        'pending': 0,
        'in_progress': 0,
        'completed': 0,
        'failed': 0
    }

    mock_dlq = MagicMock()
    mock_dlq.get_count.return_value = 0
    mock_dlq.get_error_summary.return_value = {}

    with patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('sync_queue.operations.get_stats', return_value=mock_stats), \
         patch('sync_queue.dlq.DeadLetterQueue', return_value=mock_dlq), \
         patch('reconciliation.scheduler.ReconciliationScheduler', return_value=mock_scheduler):

        from Stash2Plex import handle_queue_status
        handle_queue_status()

        captured = capfd.readouterr()
        stderr = captured.err

        # Verify "no runs yet" message
        assert 'Reconciliation Status' in stderr
        assert 'No reconciliation runs yet' in stderr


# =============================================================================
# Scope Mapping Tests
# =============================================================================

def test_reconcile_7days_mode_dispatch():
    """mode='reconcile_7days' calls handle_reconcile('recent_7days')."""
    mock_result = Mock()
    mock_result.scenes_checked = 100
    mock_result.total_gaps = 5
    mock_result.empty_metadata_count = 2
    mock_result.stale_sync_count = 1
    mock_result.missing_count = 2
    mock_result.enqueued_count = 4
    mock_result.skipped_already_queued = 0
    mock_result.errors = []

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import handle_task
        handle_task({'mode': 'reconcile_7days'}, stash=None)

        # Verify engine was called with 'recent_7days' scope
        mock_engine.run.assert_called_once_with(scope='recent_7days')
